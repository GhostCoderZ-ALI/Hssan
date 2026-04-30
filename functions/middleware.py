import re

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from config import OWNER_IDS
import database.db as db


class MaintenanceMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):

        user = event.from_user

        if not user:
            return await handler(event, data)

        if user.id in OWNER_IDS:
            return await handler(event, data)

        mode = await db.get_setting("maintenance", "off")

        if mode == "on":

            if isinstance(event, Message):
                await event.answer(
                    "⚙️ Bot under maintenance.\n\nTry again later."
                )

            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Bot under maintenance",
                    show_alert=True
                )

            return

        return await handler(event, data)


class CommandDisabledMiddleware(BaseMiddleware):
    """Silently swallow messages that invoke an /off-toggled command.

    Applies to everyone — including owners — so the toggle is testable.
    A small allow-list of management commands (cmd, start, admin, whoami,
    help) is always reachable so the bot can never be rendered unusable.
    """

    _CMD_RE = re.compile(r"^[/.]([A-Za-z][\w-]*)")
    _ALWAYS_ON = {"cmd", "start", "admin", "whoami", "help"}

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        text = (event.text or event.caption or "").strip()
        m = self._CMD_RE.match(text)
        if not m:
            return await handler(event, data)

        cmd = m.group(1).split("@", 1)[0].lower()
        if cmd in self._ALWAYS_ON:
            return await handler(event, data)

        val = await db.get_setting(f"cmd_{cmd}", "on")
        if val == "off":
            # Pretend the command does not exist for this user.
            return

        return await handler(event, data)
