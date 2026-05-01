import asyncio
from aiogram import Router, types
from aiogram.filters import Command
from commands.pf06_lib import check_pf06
from functions.proxy_gate import get_user_proxy
import database.db as db

router = Router()

@router.message(Command("pf0.6"))
async def cmd_pf06(message: types.Message):
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await message.answer("Usage: <code>/pf0.6 CC|MM|YY|CVV</code>", parse_mode='html')
        return

    raw = args[1].strip()
    parts = raw.split('|')
    if len(parts) != 4:
        await message.answer("❌ Invalid format. Use CC|MM|YY|CVV")
        return

    cc, mm, yy, cvv = parts

    ok, why = await db.can_hit(message.from_user.id)
    if not ok:
        await message.answer(f"⛔ {why}")
        return

    ok_p, proxy, err_p = await get_user_proxy(message.from_user.id)
    if not ok_p:
        await message.answer(err_p)
        return

    progress = await message.answer("⏳ Checking PayFast...")
    try:
        is_live, msg = await asyncio.to_thread(check_pf06, cc, mm, yy, cvv, proxy)
    except Exception as e:
        await progress.edit_text(f"❌ Error: {str(e)[:200]}")
        return

    status = "LIVE" if is_live else "DEAD"
    icon = "✅" if is_live else "❌"

    await db.increment_daily_hits(message.from_user.id)
    try:
        await db.log_check(message.from_user.id, raw, "payfast", "PayFast", "", "LIVE" if is_live else "DECLINED", msg, 0.0)
    except:
        pass

    await progress.edit_text(
        f"{icon} <b>{status}</b>\n"
        f"💳 <code>{raw}</code>\n"
        f"📝 <i>{msg[:300]}</i>\n"
        f"🏪 Gate: PayFast $0.6"
    )
