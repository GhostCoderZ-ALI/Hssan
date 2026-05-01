from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import database.db as db
from config import OWNER_IDS, FREE_DAILY_LIMIT, OWNER_USERNAME
from functions.emojis import EMOJI

router = Router()


async def _role(uid: int) -> str:
    if uid in OWNER_IDS:
        return "owner"
    if await db.is_admin(uid):
        return "admin"
    return "user"


@router.message(Command("wallet", prefix="/."))
async def wallet(msg: Message):
    uid = msg.from_user.id
    role = await _role(uid)

    if role in ("owner", "admin"):
        label = "OWNER" if role == "owner" else "ADMIN"
        text = (
            f"{EMOJI['crown']} <b>{label} Wallet</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Plan    ·  <b>{label}</b>\n"
            f"Hits    ·  Unlimited {EMOJI['infinity']}\n"
            f"Expiry  ·  Never\n"
            f"━━━━━━━━━━━━━━\n"
            f"<i>Staff bypass — no deductions.</i>"
        )
        await msg.answer(text, parse_mode=ParseMode.HTML)
        return

    plan = await db.get_user_plan(uid)
    if plan["unlimited"]:
        hpd = plan.get("hits_per_day", 0)
        hpd_str = f"{hpd}/day" if hpd > 0 else f"Unlimited {EMOJI['infinity']}"
        used = await db.get_daily_hits(uid)
        text = (
            f"{EMOJI['card']} <b>Wallet</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Plan    ·  <b>{plan['label']}</b>\n"
            f"Hits    ·  {hpd_str}\n"
            f"Used    ·  {used} today\n"
            f"Expires ·  {plan['expiry']}\n"
            f"━━━━━━━━━━━━━━"
        )
    else:
        used = await db.get_daily_hits(uid)
        remaining = max(0, FREE_DAILY_LIMIT - used)
        text = (
            f"{EMOJI['card']} <b>Wallet</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Plan ·  {EMOJI['free']} Free\n"
            f"Used ·  {used}/{FREE_DAILY_LIMIT} today\n"
            f"Left ·  {remaining}\n"
            f"━━━━━━━━━━━━━━\n"
            f"<i>Contact {OWNER_USERNAME} for premium.</i>"
        )

    await msg.answer(text, parse_mode=ParseMode.HTML)
