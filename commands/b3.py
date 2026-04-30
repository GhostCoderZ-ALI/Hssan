"""
/b3 — Braintree-style auth checker.
Thin aiogram wrapper around ``commands.b3_auth_lib.check_card``.
"""
import asyncio
import re
from aiogram import Router, types
from aiogram.filters import Command

from commands.b3_auth_lib import check_card as _b3_check
import database.db as db

router = Router()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI.sub("", s) if isinstance(s, str) else s


@router.message(Command("b3"))
async def cmd_b3(message: types.Message):
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await message.answer(
            "❌ <b>Usage:</b> <code>/b3 CC|MM|YYYY|CVV</code>\n"
            "Example: <code>/b3 4111111111111111|12|2027|123</code>"
        )
        return

    raw = args[1].strip().split()[0]
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 4:
        await message.answer("❌ Invalid format. Use <code>CC|MM|YYYY|CVV</code>")
        return

    cc, mm, yy, cvv = parts
    if len(yy) == 2:
        yy = "20" + yy

    ok, why = await db.can_hit(message.from_user.id)
    if not ok:
        await message.answer(f"⛔ {why}")
        return

    progress = await message.answer("⏳ Checking via Braintree gate...")

    try:
        result = await asyncio.to_thread(_b3_check, cc, mm, yy, cvv)
    except Exception as e:
        await progress.edit_text(f"❌ Gate error: <code>{str(e)[:200]}</code>")
        return

    msg = _strip_ansi(result) if result else "No response from gate"
    is_live = result and (
        "added" in str(result).lower()
        or "success" in str(result).lower()
        or "payment method" in str(result).lower()
    )
    icon = "✅" if is_live else "❌"
    status = "LIVE" if is_live else "DEAD"

    await db.increment_daily_hits(message.from_user.id)
    try:
        await db.log_check(
            message.from_user.id, raw, "braintree", "Braintree", "",
            "LIVE" if is_live else "DECLINED", msg, 0.0,
        )
    except Exception:
        pass

    await progress.edit_text(
        f"{icon} <b>{status}</b>\n"
        f"💳 <code>{cc}|{mm}|{yy}|{cvv}</code>\n"
        f"📝 <i>{msg[:300]}</i>\n"
        f"🏪 Gate: Braintree Auth"
    )
