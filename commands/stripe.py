"""
/stripe — Stripe single-card auth checker.
Thin aiogram wrapper around ``commands.st.check_card``.
"""
import re
from aiogram import Router, types
from aiogram.filters import Command

from commands.st import check_card as _stripe_check
import database.db as db

router = Router()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _clean(s) -> str:
    return _ANSI.sub("", str(s)) if s is not None else ""


@router.message(Command("stripe"))
async def cmd_stripe(message: types.Message):
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await message.answer(
            "❌ <b>Usage:</b> <code>/stripe CC|MM|YY|CVV [proxy]</code>\n"
            "Example: <code>/stripe 4111111111111111|12|27|123</code>"
        )
        return

    parts = args[1].split()
    raw = parts[0]
    proxy = parts[1] if len(parts) > 1 else None

    cc_parts = [p.strip() for p in raw.split("|")]
    if len(cc_parts) != 4:
        await message.answer("❌ Invalid format. Use <code>CC|MM|YY|CVV</code>")
        return

    cc, mm, yy, cvv = cc_parts
    if len(yy) == 4:
        yy = yy[-2:]

    ok, why = await db.can_hit(message.from_user.id)
    if not ok:
        await message.answer(f"⛔ {why}")
        return

    progress = await message.answer("⏳ Checking via Stripe gate...")

    try:
        result = await _stripe_check(cc, mm, yy, cvv, proxy=proxy)
    except Exception as e:
        await progress.edit_text(f"❌ Gate error: <code>{str(e)[:200]}</code>")
        return

    is_live = bool(result.get("is_live"))
    response = _clean(result.get("response", ""))
    icon = "✅" if is_live else "❌"
    status = "LIVE" if is_live else "DECLINED"

    await db.increment_daily_hits(message.from_user.id)
    try:
        await db.log_check(
            message.from_user.id, raw, "stripe", "Stripe", "",
            "LIVE" if is_live else "DECLINED", response, 0.0,
        )
    except Exception:
        pass

    await progress.edit_text(
        f"{icon} <b>{status}</b>\n"
        f"💳 <code>{cc}|{mm}|{yy}|{cvv}</code>\n"
        f"📝 <i>{response[:300]}</i>\n"
        f"🏪 Gate: Stripe Auth"
    )
