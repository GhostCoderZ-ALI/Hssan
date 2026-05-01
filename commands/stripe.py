"""Stripe Auth gate — /stripe single, /mstripe mass.

Powered by ``commands.st.check_card`` (eastlondonprintmakers WooCommerce).
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
from functions.proxy_gate import get_user_proxy
from commands.st import check_card as _stripe_check

router = Router()
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


def _format(card: str, is_live: bool, response: str, elapsed: float) -> str:
    if is_live:
        head = f"{EMOJI['charged']} <b>LIVE / APPROVED</b>"
        status = "LIVE"
    else:
        head = f"{EMOJI['declined']} <b>DECLINED</b>"
        status = "DECLINED"
    return (
        f"{head}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Card:</b>  <code>{card}</code>\n"
        f"<b>Gate:</b>  Stripe Auth\n"
        f"<b>Reply:</b> <code>{response[:120]}</code>\n"
        f"<b>Time:</b>  {elapsed:.2f}s\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )


async def _check_async(card: str, proxy: str | None = None) -> dict:
    parts = card.split("|")
    cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    return await _stripe_check(cc, mm, yy, cvv, proxy=proxy)


@router.message(Command("stripe", prefix="/."))
async def cmd_stripe(msg: Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return
    ok, why = await _can_check(uid)
    if not ok:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return

    ok_p, proxy, err_p = await get_user_proxy(uid)
    if not ok_p:
        await msg.answer(err_p, parse_mode=ParseMode.HTML)
        return

    txt_blob = await read_attached_txt(msg, bot)
    if txt_blob:
        await _run_mass(msg, command, bot, proxy=proxy, prefilled_blob=txt_blob)
        return

    raw = (command.args or "").strip()
    card = _normalise(raw)
    if not card:
        await msg.answer(
            f"{EMOJI['question']} Usage:\n"
            f"<code>/stripe cc|mm|yy|cvv</code>\n"
            f"…or attach / reply to a <code>.txt</code> file with cards.",
            parse_mode=ParseMode.HTML,
        )
        return

    sent = await msg.answer(
        f"{EMOJI['hitting']} <b>Checking on Stripe Auth…</b>\n<code>{card}</code>",
        parse_mode=ParseMode.HTML,
    )
    t0 = time.time()
    try:
        result = await _check_async(card, proxy=proxy)
    except Exception as e:
        await sent.edit_text(
            f"{EMOJI['error']} Gate error: <code>{str(e)[:80]}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    elapsed = time.time() - t0
    is_live = result.get("is_live", False)
    response = result.get("response", "")
    await sent.edit_text(_format(card, is_live, response, elapsed), parse_mode=ParseMode.HTML)

    if not await _is_priv(uid):
        await db.increment_daily_hits(uid)
    if is_live:
        await db.log_check(uid, card, "", "Stripe Auth", "$0", "LIVE", response, elapsed)


@router.message(Command("mstripe", prefix="/."))
async def cmd_mstripe(msg: Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    if await db.is_banned(uid):
        await msg.answer(f"{EMOJI['ban']} You are banned.", parse_mode=ParseMode.HTML)
        return
    ok, why = await _can_check(uid)
    if not ok:
        await msg.answer(f"{EMOJI['lock']} {why}", parse_mode=ParseMode.HTML)
        return
    ok_p, proxy, err_p = await get_user_proxy(uid)
    if not ok_p:
        await msg.answer(err_p, parse_mode=ParseMode.HTML)
        return
    await _run_mass(msg, command, bot, proxy=proxy)


async def _run_mass(msg: Message, command: CommandObject, bot: Bot, proxy: str | None = None, prefilled_blob: str | None = None):
    uid = msg.from_user.id
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

    txt_blob = prefilled_blob if prefilled_blob is not None else await read_attached_txt(msg, bot)
    if txt_blob:
        for line in txt_blob.splitlines():
            _add(line)

    if not cards:
        await msg.answer(
            f"{EMOJI['question']} Usage:\n<code>/mstripe\ncc|mm|yy|cvv\ncc|mm|yy|cvv</code>\n"
            f"…or attach / reply to a <code>.txt</code> file containing cards.",
            parse_mode=ParseMode.HTML,
        )
        return

    cap = 200 if txt_blob else 25
    cards = cards[:cap]
    is_priv = await _is_priv(uid)
    progress = await msg.answer(
        f"{EMOJI['hitting']} <b>Mass Stripe Auth</b>\nQueued <code>{len(cards)}</code>…",
        parse_mode=ParseMode.HTML,
    )

    live = declined = errors = 0
    lines: list[str] = []
    for idx, card in enumerate(cards, 1):
        try:
            result = await _check_async(card, proxy=proxy)
        except Exception as e:
            result = {"is_live": False, "response": str(e)[:40]}

        is_live = result.get("is_live", False)
        response = result.get("response", "")

        if is_live:
            live += 1
            lines.append(f"{EMOJI['charged']} <code>{card}</code>")
            await db.log_check(uid, card, "", "Stripe Auth", "$0", "LIVE", response, 0.0)
            await msg.answer(
                f"{EMOJI['charged']} <b>LIVE</b>\n"
                f"<code>{card}</code>\n"
                f"Gate: Stripe Auth\n"
                f"Reply: <code>{response[:80]}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            declined += 1
            lines.append(f"{EMOJI['declined']} <code>{card}</code> · {response[:40]}")

        if not is_priv:
            await db.increment_daily_hits(uid)

        body = "\n".join(lines[-12:])
        try:
            await progress.edit_text(
                f"{EMOJI['hitting']} <b>Stripe {idx}/{len(cards)}</b>\n"
                f"{EMOJI['charged']} {live} · {EMOJI['declined']} {declined} · {EMOJI['error']} {errors}\n"
                f"━━━━━━━━━━━━━━\n{body}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    summary = (
        f"{EMOJI['stats']} <b>Stripe Auth Mass Done</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{EMOJI['charged']} Live:     <code>{live}</code>\n"
        f"{EMOJI['declined']} Declined: <code>{declined}</code>\n"
        f"{EMOJI['error']} Errors:   <code>{errors}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>by {OWNER_USERNAME}</i>"
    )
    try:
        await progress.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await msg.answer(summary, parse_mode=ParseMode.HTML)
