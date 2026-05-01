"""
/b3 — Braintree-style auth checker.
"""
import asyncio
import re
from aiogram import Router, types
from aiogram.filters import Command

from commands.b3_auth_lib import check_card as _b3_check
import database.db as db
from functions.proxy_gate import get_user_proxy

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

    ok_p, proxy, err_p = await get_user_proxy(message.from_user.id)
    if not ok_p:
        await message.answer(err_p)
        return

    progress = await message.answer("⏳ Checking via Braintree gate...")

    try:
        # run the sync function in a thread, passing proxy
        is_live, msg = await asyncio.to_thread(_b3_check, cc, mm, yy, cvv, proxy)
    except Exception as e:
        await progress.edit_text(f"❌ Gate error: <code>{str(e)[:200]}</code>")
        return

    msg_clean = _strip_ansi(msg) if msg else "No response"
    status = "LIVE" if is_live else "DEAD"
    icon = "✅" if is_live else "❌"

    await db.increment_daily_hits(message.from_user.id)
    try:
        await db.log_check(
            message.from_user.id, raw, "braintree", "Braintree", "",
            "LIVE" if is_live else "DECLINED", msg_clean, 0.0,
        )
    except Exception:
        pass

    await progress.edit_text(
        f"{icon} <b>{status}</b>\n"
        f"💳 <code>{cc}|{mm}|{yy}|{cvv}</code>\n"
        f"📝 <i>{msg_clean[:300]}</i>\n"
        f"🏪 Gate: Braintree Auth"
    )
