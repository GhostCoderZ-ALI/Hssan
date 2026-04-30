"""Helpers for accepting `.txt` attachments as input to commands.

Mass-checking commands and `/proxy add` accept an attached or replied-to
`.txt` file. This module reads the file's text content and exposes parsed
helpers (cards / proxies / raw lines).
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message


_MAX_TXT_BYTES = 5 * 1024 * 1024  # 5 MB cap — Telegram lets us go higher but
                                  # parsing huge lists synchronously is bad UX.


async def _read_document(bot: Bot, document) -> str | None:
    """Download a Telegram document and decode it as UTF-8 text."""
    if not document or not document.file_name:
        return None
    if not document.file_name.lower().endswith(".txt"):
        return None
    if document.file_size and document.file_size > _MAX_TXT_BYTES:
        return None
    try:
        file = await bot.get_file(document.file_id)
        buf = await bot.download_file(file.file_path)
        if buf is None:
            return None
        raw = buf.read() if hasattr(buf, "read") else buf
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return None


async def read_attached_txt(msg: Message, bot: Bot) -> str:
    """Return concatenated text from any `.txt` attached to *msg* itself
    or to the message it is replying to. Empty string when nothing found.
    """
    chunks: list[str] = []

    if msg.document:
        text = await _read_document(bot, msg.document)
        if text:
            chunks.append(text)

    if msg.reply_to_message and msg.reply_to_message.document:
        text = await _read_document(bot, msg.reply_to_message.document)
        if text:
            chunks.append(text)

    return "\n".join(chunks)


async def read_lines_from_txt(msg: Message, bot: Bot) -> list[str]:
    """Same as :func:`read_attached_txt` but returns a list of stripped
    non-empty lines.
    """
    text = await read_attached_txt(msg, bot)
    if not text:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]
