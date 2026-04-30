"""Stripe gate via Dilaboards - /mst single, /mass-st mass.

Powered by `bot_st_legacy.check_cc` (woocommerce + Stripe SetupIntent on dilaboards.com).
"""
import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor

from aiogram import Router, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import database.db as db
from config import OWNER_IDS, FREE_DAILY_LIMIT, OWNER_USERNAME
from functions.emojis import EMOJI
from functions.file_input import read_attached_txt
from commands import bot_st_legacy as _st_lib

router = Router()
_executor = ThreadPoolExecutor(max_workers=8)
_CARD_RE = re.compile(r"(\d{15,16})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})")


async def _is_priv(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True
    return await db.is_admin(uid)


async def _can_check(uid: int) -> tuple[bool, str]:
    if await _is_priv(uid):
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


def _format(card: str, status: str, msg: str, brand: str, elapsed: float) -> str:
    if status == "APPROVED":
        head = f"{EMOJI['charged']} <b>APPROVED</b>"
    elif status == "LIVE":
        head = f"{EMOJI['live']} <b>LIVE</b> · CCN"
    elif status == "3DS":
        head = f"{EMOJI['3ds']} <b>3D-SECURE</b>"
    elif status == "DECLINED":
        head = f"{EMOJI['declined']} <b>DECLINED</b>"
    else:
        head = f"{EMOJI['error']} <b>{status}</b>"

    return (
        f"{head}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Card:</b>  <code>{card}</code>\n"
        f"<b>Brand:</b> {brand}\n"
        f"<b>Gate:</b>  Stripe Setup-Intent\n"
        f"<b>Reply:</b> <code>{msg}</code>\n"
        f"<b>Time:</b>  {elapsed:.2f}s\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )


async def _check_async(card: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _st_lib.check_cc, card, None)


@router.message(Command("mst", prefix="/."))
async def cmd_mst(msg: Message, command: CommandObject):
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
            f"{EMOJI['question']} Usage: <code>/mst cc|mm|yy|cvv</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    sent = await msg.answer(
        f"{EMOJI['hitting']} <b>Checking on Stripe Setup-Intent…</b>\n<code>{card}</code>",
        parse_mode=ParseMode.HTML,
    )
    t0 = time.time()
    try:
        status, response, brand = await _check_async(card)
    except Exception as e:
        await sent.edit_text(
            f"{EMOJI['error']} Gate error: <code>{str(e)[:80]}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    elapsed = time.time() - t0
    await sent.edit_text(_format(card, status, response, brand, elapsed), parse_mode=ParseMode.HTML)
    if not await _is_priv(uid):
        await db.increment_daily_hits(uid)
    if status in ("APPROVED", "LIVE", "3DS"):
        await db.log_check(uid, card, "", "Stripe SI", "$0", status, response, 0.0)


@router.message(Command("mass-st", prefix="/."))
async def cmd_mass_st(msg: Message, command: CommandObject, bot: Bot):
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
            f"{EMOJI['question']} Usage:\n<code>/mass-st\ncc|mm|yy|cvv\ncc|mm|yy|cvv</code>\n"
            f"…or attach / reply to a <code>.txt</code> file containing cards.",
            parse_mode=ParseMode.HTML,
        )
        return

    cap = 200 if txt_blob else 25
    cards = cards[:cap]
    is_priv = await _is_priv(uid)
    progress = await msg.answer(
        f"{EMOJI['hitting']} <b>Mass Stripe</b>\nQueued <code>{len(cards)}</code>…",
        parse_mode=ParseMode.HTML,
    )

    approved = live = three_ds = declined = errors = 0
    lines: list[str] = []
    for idx, card in enumerate(cards, 1):
        try:
            status, response, brand = await _check_async(card)
        except Exception as e:
            status, response, brand = "ERROR", str(e)[:40], "?"

        if status == "APPROVED":
            approved += 1
            lines.append(f"{EMOJI['charged']} <code>{card}</code>")
            await db.log_check(uid, card, "", "Stripe SI", "$0", status, response, 0.0)
            await msg.answer(
                f"{EMOJI['charged']} <b>APPROVED</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: Stripe SI\n"
                f"Reply: <code>{response[:80]}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif status == "LIVE":
            live += 1
            lines.append(f"{EMOJI['live']} <code>{card}</code> · CCN")
            await db.log_check(uid, card, "", "Stripe SI", "$0", status, response, 0.0)
            await msg.answer(
                f"{EMOJI['live']} <b>LIVE / CCN</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: Stripe SI\n"
                f"Reply: <code>{response[:80]}</code>",
                parse_mode=ParseMode.HTML,
            )
        elif status == "3DS":
            three_ds += 1
            lines.append(f"{EMOJI['3ds']} <code>{card}</code>")
            await msg.answer(
                f"{EMOJI['3ds']} <b>3D-SECURE</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: Stripe SI",
                parse_mode=ParseMode.HTML,
            )
        elif status == "DECLINED":
            declined += 1
            lines.append(f"{EMOJI['declined']} <code>{card}</code> · {response[:40]}")
        else:
            errors += 1
            lines.append(f"{EMOJI['error']} <code>{card}</code>")

        if not is_priv:
            await db.increment_daily_hits(uid)

        body = "\n".join(lines[-12:])
        try:
            await progress.edit_text(
                f"{EMOJI['hitting']} <b>ST {idx}/{len(cards)}</b>\n"
                f"{EMOJI['charged']} {approved} · {EMOJI['live']} {live} · "
                f"{EMOJI['3ds']} {three_ds} · {EMOJI['declined']} {declined} · "
                f"{EMOJI['error']} {errors}\n━━━━━━━━━━━━━━\n{body}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    summary = (
        f"{EMOJI['stats']} <b>Stripe Mass Done</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{EMOJI['charged']} Approved:  <code>{approved}</code>\n"
        f"{EMOJI['live']} Live (CCN): <code>{live}</code>\n"
        f"{EMOJI['3ds']} 3D-Secure:  <code>{three_ds}</code>\n"
        f"{EMOJI['declined']} Declined:   <code>{declined}</code>\n"
        f"{EMOJI['error']} Errors:     <code>{errors}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )
    try:
        await progress.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await msg.answer(summary, parse_mode=ParseMode.HTML)
