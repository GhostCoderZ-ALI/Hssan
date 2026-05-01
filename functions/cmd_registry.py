"""Command registry + on/off helpers.

A single source of truth for which user-facing commands the bot exposes.
The /cmd on|off toggle stores `cmd_<name>` settings; the middleware,
help-text filter and Telegram slash menu all read from here so that a
disabled command disappears from everywhere at once.
"""
import re

from aiogram import Bot
from aiogram.types import BotCommand

import database.db as db


# (command, description). Description is used for Telegram's slash menu.
# Only plain `[a-z][a-z0-9_]*` names appear in the slash menu (Telegram limit);
# names with dashes still get filtered everywhere else.
ALL_COMMANDS: list[tuple[str, str]] = [
    ("start",    "Open home screen"),
    ("help",     "Full command menu"),
    ("stripe",   "Stripe Auth"),
    ("mstripe",  "Mass Stripe Auth"),
    ("st",       "Stripe Setup-Intent"),
    ("mst",      "Mass Stripe SI"),
    ("auth",     "Stripe Auth (alt)"),
    ("b3",       "Braintree 3D"),
    ("pp",       "PayPal $1"),
    ("mpp",      "Mass PayPal"),
    # removed: /sh /msh /mchk /adb
    ("gen",      "Card generator"),
    ("gad",      "Fake address (per country)"),
    ("bin",      "BIN lookup"),
    ("savebin",  "Save BIN"),
    ("mybins",   "List saved BINs"),
    ("delbin",   "Delete BIN"),
    ("proxy",    "Proxy management"),
    ("temp1",    "Temp email 1"),
    ("temp2",    "Temp email 2"),
    ("temp3",    "Temp email 3"),
    ("credits",  "Plan info"),
    ("myhits",   "Hit history"),
    ("redeem",   "Claim plan"),
    ("wallet",   "Balance"),
    ("ref",      "Referral code"),
    ("ping",     "Latency"),
    ("admin",    "Admin panel"),
    ("whoami",   "Role check"),
    # NEW GATES
    ("st2",      "Stripe Charged"),
    ("pf0.6",    "PayFast Charged"),
    ("b3-5",     "Braintree Charged"),
    ("b3n",      "Braintree Auth"),
    ("st15",     "Stripe $15 Charge"),
]

KNOWN_COMMAND_NAMES: set[str] = {c.lower() for c, _ in ALL_COMMANDS}

_HELP_LINE_RE = re.compile(r"<code>/([\w-]+)")
_SLASH_MENU_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


# ─── State ──────────────────────────────────────────────────────────────────

async def get_disabled_commands() -> set[str]:
    """Return the set of currently disabled command names (lowercased)."""
    database = await db.get_db()
    cursor = database.bot_settings.find(
        {"key": {"$regex": "^cmd_"}, "value": "off"},
        {"_id": 0, "key": 1},
    )
    rows = await cursor.to_list(length=1000)
    return {r["key"][4:].lower() for r in rows if r.get("key", "").startswith("cmd_")}


async def is_command_disabled(cmd: str) -> bool:
    val = await db.get_setting(f"cmd_{cmd.lower()}", "on")
    return val == "off"


async def set_command_state(cmd: str, mode: str) -> None:
    """mode: 'on' or 'off'."""
    await db.set_setting(f"cmd_{cmd.lower()}", mode)


# ─── Telegram slash menu ────────────────────────────────────────────────────

async def update_bot_commands(bot: Bot) -> None:
    """Push the current enabled-command list to Telegram's slash menu."""
    disabled = await get_disabled_commands()
    cmds = [
        BotCommand(command=c.lower(), description=d)
        for c, d in ALL_COMMANDS
        if c.lower() not in disabled and _SLASH_MENU_RE.match(c.lower())
    ]
    try:
        await bot.set_my_commands(cmds)
    except Exception:
        # Don't crash the toggle handler if Telegram complains.
        pass


# ─── Help-text filter ───────────────────────────────────────────────────────

def filter_help_text(text: str, disabled: set[str]) -> str:
    """Drop any help line whose first /<command> token is disabled."""
    if not disabled:
        return text
    out: list[str] = []
    for line in text.split("\n"):
        m = _HELP_LINE_RE.search(line)
        if m and m.group(1).lower() in disabled:
            continue
        out.append(line)
    return "\n".join(out)
