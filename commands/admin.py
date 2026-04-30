from aiogram import Router, Bot
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.filters import Command

import database.db as db
from config import OWNER_IDS, OWNER_USERNAME
from functions.emojis import EMOJI
from functions.cmd_registry import (
    KNOWN_COMMAND_NAMES,
    set_command_state,
    update_bot_commands,
    get_disabled_commands,
)

router = Router()


# ADMIN CHECK
async def is_admin(uid: int):
    if uid in OWNER_IDS:
        return True
    return await db.is_admin(uid)


async def _role(uid: int) -> str:
    if uid in OWNER_IDS:
        return "owner"
    if await db.is_admin(uid):
        return "admin"
    return "user"


# ADMIN PANEL
@router.message(Command("admin"))
async def admin_panel(msg: Message):
    role = await _role(msg.from_user.id)
    if role == "user":
        await msg.answer(
            f"{EMOJI['lock']} <b>Admins only.</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    label = "OWNER" if role == "owner" else "ADMIN"
    text = (
        f"╭─ {EMOJI['crown']} <b>{label} CONTROL</b>\n"
        f"│\n"
        f"│  <b>★ Users</b>\n"
        f"│  <code>/ban &lt;id&gt;</code>      ban user\n"
        f"│  <code>/unban &lt;id&gt;</code>    unban user\n"
        f"│  <code>/user &lt;id&gt;</code>     user info\n"
        f"│\n"
        f"│  <b>★ Staff</b>\n"
        f"│  <code>/addadmin &lt;id&gt;</code>     promote\n"
        f"│  <code>/removeadmin &lt;id&gt;</code>  demote\n"
        f"│  <code>/admins</code>             list staff\n"
        f"│\n"
        f"│  <b>★ Bot</b>\n"
        f"│  <code>/broadcast &lt;text&gt;</code>  blast all\n"
        f"│  <code>/stats</code>              global counters\n"
        f"│  <code>/resetstats</code>         zero counters\n"
        f"│  <code>/maintenance on|off</code> kill switch\n"
        f"│  <code>/cmd on|off &lt;command&gt;</code> toggle cmd\n"
        f"│\n"
        f"│  <b>★ System</b>\n"
        f"│  <code>/whoami</code>  role check\n"
        f"╰─ <i>Owner: {OWNER_USERNAME}</i>"
    )
    if role != "owner":
        disabled = await get_disabled_commands()
        if disabled:
            from functions.cmd_registry import filter_help_text
            text = filter_help_text(text, disabled)
    await msg.answer(text, parse_mode=ParseMode.HTML)


# WHOAMI
@router.message(Command("whoami"))
async def whoami(msg: Message):
    uid = msg.from_user.id
    role = await _role(uid)
    if role == "owner":
        await msg.answer(
            f"{EMOJI['crown']} <b>OWNER</b>\n"
            f"<code>{uid}</code>\n"
            f"<i>Bypasses every limit. Hardcoded into config.</i>",
            parse_mode=ParseMode.HTML,
        )
    elif role == "admin":
        await msg.answer(
            f"{EMOJI['crown']} <b>ADMIN</b>\n"
            f"<code>{uid}</code>\n"
            f"<i>Staff access · unlimited hits.</i>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.answer(
            f"{EMOJI['users']} <b>USER</b>\n"
            f"<code>{uid}</code>\n"
            f"<i>Free plan · contact {OWNER_USERNAME} for upgrade.</i>",
            parse_mode=ParseMode.HTML,
        )


# ADD ADMIN
@router.message(Command("addadmin"))
async def add_admin(msg: Message):

    if msg.from_user.id not in OWNER_IDS:
        return

    try:
        uid = int(msg.text.split()[1])
    except:
        await msg.answer("Usage: /addadmin USER_ID")
        return

    await db.add_admin(uid)

    await msg.answer("✅ Admin added.")


# REMOVE ADMIN
@router.message(Command("removeadmin"))
async def remove_admin(msg: Message):

    if msg.from_user.id not in OWNER_IDS:
        return

    try:
        uid = int(msg.text.split()[1])
    except:
        await msg.answer("Usage: /removeadmin USER_ID")
        return

    await db.remove_admin(uid)

    await msg.answer("✅ Admin removed.")


# LIST ADMINS
@router.message(Command("admins"))
async def admins(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    admins = await db.get_all_admins()

    if not admins:
        await msg.answer("No admins found.")
        return

    text = "👑 ADMINS\n\n"

    for a in admins:
        text += f"{a}\n"

    await msg.answer(text)


# BAN USER
@router.message(Command("ban"))
async def ban(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    if msg.reply_to_message:
        uid = msg.reply_to_message.from_user.id
    else:
        try:
            uid = int(msg.text.split()[1])
        except:
            await msg.answer("Usage: /ban USER_ID or reply")
            return

    await db.ban_user(uid)

    await msg.answer("🚫 User banned.")


# UNBAN USER
@router.message(Command("unban"))
async def unban(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    try:
        uid = int(msg.text.split()[1])
    except:
        await msg.answer("Usage: /unban USER_ID")
        return

    await db.unban_user(uid)

    await msg.answer("✅ User unbanned.")


# USER INFO
@router.message(Command("user"))
async def user(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    try:
        uid = int(msg.text.split()[1])
    except:
        await msg.answer("Usage: /user USER_ID")
        return

    info = await db.get_user_info(uid)

    if not info:
        await msg.answer("User not found.")
        return

    text = f"""
USER INFO

ID: {uid}
Username: {info.get("username")}
Name: {info.get("first_name")}
Join: {info.get("join_date")}
Banned: {info.get("is_banned")}
"""

    await msg.answer(text)


# GLOBAL STATS
@router.message(Command("stats"))
async def stats(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    s = await db.get_global_stats()

    text = f"""
BOT STATS

Users: {s['users']}
Checks: {s['checks']}
Charged: {s['charged']}
Live: {s['live']}
Banned: {s['banned']}
Active Codes: {s['active_codes']}
"""

    await msg.answer(text)


# RESET STATS
@router.message(Command("resetstats"))
async def resetstats(msg: Message):

    if msg.from_user.id not in OWNER_IDS:
        return

    await db.reset_global_stats()

    await msg.answer("⚠️ Global stats reset.")


# BROADCAST
@router.message(Command("broadcast"))
async def broadcast(msg: Message):

    if not await is_admin(msg.from_user.id):
        return

    try:
        text = msg.text.split(" ", 1)[1]
    except:
        await msg.answer("Usage: /broadcast message")
        return

    users = await db.get_all_user_ids()

    sent = 0

    for u in users:
        try:
            await msg.bot.send_message(u, text)
            sent += 1
        except:
            pass

    await msg.answer(f"📢 Broadcast sent to {sent} users.")


# MAINTENANCE MODE
@router.message(Command("maintenance"))
async def maintenance(msg: Message):

    if msg.from_user.id not in OWNER_IDS:
        return

    try:
        mode = msg.text.split()[1]
    except:
        await msg.answer("Usage: /maintenance on/off")
        return

    if mode not in ["on", "off"]:
        await msg.answer("Use on/off")
        return

    await db.set_setting("maintenance", mode)

    await msg.answer(f"⚙️ Maintenance → {mode}")


# COMMAND ENABLE / DISABLE
@router.message(Command("cmd"))
async def cmd_control(msg: Message, bot: Bot):

    if msg.from_user.id not in OWNER_IDS:
        return

    args = msg.text.split()

    if len(args) < 2:
        disabled = sorted(await get_disabled_commands())
        disabled_line = ", ".join(f"<code>/{c}</code>" for c in disabled) if disabled else "<i>none</i>"
        await msg.answer(
            "Usage:\n"
            "<code>/cmd on &lt;command&gt;</code>\n"
            "<code>/cmd off &lt;command&gt;</code>\n"
            "<code>/cmd list</code>\n\n"
            f"<b>Disabled:</b> {disabled_line}",
            parse_mode=ParseMode.HTML,
        )
        return

    sub = args[1].lower()

    if sub == "list":
        disabled = sorted(await get_disabled_commands())
        if not disabled:
            await msg.answer("✅ All commands enabled.")
        else:
            lines = "\n".join(f"• <code>/{c}</code>" for c in disabled)
            await msg.answer(f"<b>Disabled commands:</b>\n{lines}", parse_mode=ParseMode.HTML)
        return

    if sub not in ("on", "off") or len(args) < 3:
        await msg.answer("Use <code>/cmd on|off &lt;command&gt;</code>", parse_mode=ParseMode.HTML)
        return

    cmd = args[2].lstrip("/.").split("@", 1)[0].lower()
    if not cmd:
        await msg.answer("Invalid command name.")
        return

    if cmd not in KNOWN_COMMAND_NAMES:
        await msg.answer(
            f"⚠️ <code>/{cmd}</code> isn't a known command. Saved anyway, but it won't appear in the menu.",
            parse_mode=ParseMode.HTML,
        )

    await set_command_state(cmd, sub)
    await update_bot_commands(bot)

    if sub == "off":
        await msg.answer(
            f"🚫 <code>/{cmd}</code> disabled — hidden from the menu and ignored for users.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.answer(
            f"✅ <code>/{cmd}</code> enabled — visible again.",
            parse_mode=ParseMode.HTML,
        )
