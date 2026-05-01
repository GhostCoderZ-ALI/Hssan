import time
import random
from aiogram import Router, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

from faker import Faker

import database.db as db
from functions.force_join import check_force_join, force_join_keyboard, FORCE_JOIN_MSG
from functions.emojis import EMOJI, EMOJI_PLAIN

router = Router()

# Cached Faker instances per locale
_fakers = {}

def _get_faker(locale: str) -> Faker:
    if locale not in _fakers:
        _fakers[locale] = Faker(locale)
    return _fakers[locale]

# Fallback locale if a field isn't available for the requested locale
FALLBACK_LOCALE = "en_US"

COUNTRIES = {
    "us":  ("en_US", "United States",  "US", "🇺🇸"),
    "usa": ("en_US", "United States",  "US", "🇺🇸"),
    "america": ("en_US", "United States", "US", "🇺🇸"),
    "united states": ("en_US", "United States", "US", "🇺🇸"),
    "uk":  ("en_GB", "United Kingdom", "GB", "🇬🇧"),
    "gb":  ("en_GB", "United Kingdom", "GB", "🇬🇧"),
    "britain": ("en_GB", "United Kingdom", "GB", "🇬🇧"),
    "england": ("en_GB", "United Kingdom", "GB", "🇬🇧"),
    "ca":  ("en_CA", "Canada",         "CA", "🇨🇦"),
    "canada": ("en_CA", "Canada",      "CA", "🇨🇦"),
    "au":  ("en_AU", "Australia",      "AU", "🇦🇺"),
    "australia": ("en_AU", "Australia","AU", "🇦🇺"),
    "in":  ("en_IN", "India",          "IN", "🇮🇳"),
    "india": ("en_IN", "India",        "IN", "🇮🇳"),
    "de":  ("de_DE", "Germany",        "DE", "🇩🇪"),
    "germany": ("de_DE", "Germany",    "DE", "🇩🇪"),
    "fr":  ("fr_FR", "France",         "FR", "🇫🇷"),
    "france": ("fr_FR", "France",      "FR", "🇫🇷"),
    "es":  ("es_ES", "Spain",          "ES", "🇪🇸"),
    "spain": ("es_ES", "Spain",        "ES", "🇪🇸"),
    "it":  ("it_IT", "Italy",          "IT", "🇮🇹"),
    "italy": ("it_IT", "Italy",        "IT", "🇮🇹"),
    "br":  ("pt_BR", "Brazil",         "BR", "🇧🇷"),
    "brazil": ("pt_BR", "Brazil",      "BR", "🇧🇷"),
    "pt":  ("pt_PT", "Portugal",       "PT", "🇵🇹"),
    "portugal": ("pt_PT", "Portugal",  "PT", "🇵🇹"),
    "nl":  ("nl_NL", "Netherlands",    "NL", "🇳🇱"),
    "netherlands": ("nl_NL", "Netherlands", "NL", "🇳🇱"),
    "ru":  ("ru_RU", "Russia",         "RU", "🇷🇺"),
    "russia": ("ru_RU", "Russia",      "RU", "🇷🇺"),
    "jp":  ("ja_JP", "Japan",          "JP", "🇯🇵"),
    "japan": ("ja_JP", "Japan",        "JP", "🇯🇵"),
    "cn":  ("zh_CN", "China",          "CN", "🇨🇳"),
    "china": ("zh_CN", "China",        "CN", "🇨🇳"),
    "mx":  ("es_MX", "Mexico",         "MX", "🇲🇽"),
    "mexico": ("es_MX", "Mexico",      "MX", "🇲🇽"),
    "ar":  ("es_AR", "Argentina",      "AR", "🇦🇷"),
    "argentina": ("es_AR", "Argentina","AR", "🇦🇷"),
    "co":  ("es_CO", "Colombia",       "CO", "🇨🇴"),
    "colombia": ("es_CO", "Colombia",  "CO", "🇨🇴"),
    "cl":  ("es_CL", "Chile",          "CL", "🇨🇱"),
    "chile": ("es_CL", "Chile",        "CL", "🇨🇱"),
    "pe":  ("es_PE", "Peru",           "PE", "🇵🇪"),
    "peru": ("es_PE", "Peru",          "PE", "🇵🇪"),
    "pl":  ("pl_PL", "Poland",         "PL", "🇵🇱"),
    "poland": ("pl_PL", "Poland",      "PL", "🇵🇱"),
    "se":  ("sv_SE", "Sweden",         "SE", "🇸🇪"),
    "sweden": ("sv_SE", "Sweden",      "SE", "🇸🇪"),
    "no":  ("no_NO", "Norway",         "NO", "🇳🇴"),
    "norway": ("no_NO", "Norway",      "NO", "🇳🇴"),
    "dk":  ("da_DK", "Denmark",        "DK", "🇩🇰"),
    "denmark": ("da_DK", "Denmark",    "DK", "🇩🇰"),
    "fi":  ("fi_FI", "Finland",        "FI", "🇫🇮"),
    "finland": ("fi_FI", "Finland",    "FI", "🇫🇮"),
    "tr":  ("tr_TR", "Turkey",         "TR", "🇹🇷"),
    "turkey": ("tr_TR", "Turkey",      "TR", "🇹🇷"),
    "ch":  ("de_CH", "Switzerland",    "CH", "🇨🇭"),
    "switzerland": ("de_CH", "Switzerland", "CH", "🇨🇭"),
    "at":  ("de_AT", "Austria",        "AT", "🇦🇹"),
    "austria": ("de_AT", "Austria",    "AT", "🇦🇹"),
    "be":  ("nl_BE", "Belgium",        "BE", "🇧🇪"),
    "belgium": ("nl_BE", "Belgium",    "BE", "🇧🇪"),
    "ie":  ("en_IE", "Ireland",        "IE", "🇮🇪"),
    "ireland": ("en_IE", "Ireland",    "IE", "🇮🇪"),
    "nz":  ("en_NZ", "New Zealand",    "NZ", "🇳🇿"),
    "newzealand": ("en_NZ", "New Zealand", "NZ", "🇳🇿"),
    "za":  ("en_ZA", "South Africa",   "ZA", "🇿🇦"),
    "southafrica": ("en_ZA", "South Africa", "ZA", "🇿🇦"),
    "ph":  ("en_PH", "Philippines",    "PH", "🇵🇭"),
    "philippines": ("en_PH", "Philippines", "PH", "🇵🇭"),
    "pk":  ("en_PK", "Pakistan",       "PK", "🇵🇰"),
    "pakistan": ("en_PK", "Pakistan",  "PK", "🇵🇰"),
    "kr":  ("ko_KR", "South Korea",    "KR", "🇰🇷"),
    "korea": ("ko_KR", "South Korea",  "KR", "🇰🇷"),
    "th":  ("th_TH", "Thailand",       "TH", "🇹🇭"),
    "thailand": ("th_TH", "Thailand",  "TH", "🇹🇭"),
    "id":  ("id_ID", "Indonesia",      "ID", "🇮🇩"),
    "indonesia": ("id_ID", "Indonesia","ID", "🇮🇩"),
    "vn":  ("vi_VN", "Vietnam",        "VN", "🇻🇳"),
    "vietnam": ("vi_VN", "Vietnam",    "VN", "🇻🇳"),
    "il":  ("he_IL", "Israel",         "IL", "🇮🇱"),
    "israel": ("he_IL", "Israel",      "IL", "🇮🇱"),
    "ua":  ("uk_UA", "Ukraine",        "UA", "🇺🇦"),
    "ukraine": ("uk_UA", "Ukraine",    "UA", "🇺🇦"),
    "gr":  ("el_GR", "Greece",         "GR", "🇬🇷"),
    "greece": ("el_GR", "Greece",      "GR", "🇬🇷"),
    "hu":  ("hu_HU", "Hungary",        "HU", "🇭🇺"),
    "hungary": ("hu_HU", "Hungary",    "HU", "🇭🇺"),
    "cz":  ("cs_CZ", "Czechia",        "CZ", "🇨🇿"),
    "czech": ("cs_CZ", "Czechia",      "CZ", "🇨🇿"),
    "ro":  ("ro_RO", "Romania",        "RO", "🇷🇴"),
    "romania": ("ro_RO", "Romania",    "RO", "🇷🇴"),
    "bg":  ("bg_BG", "Bulgaria",       "BG", "🇧🇬"),
    "bulgaria": ("bg_BG", "Bulgaria",  "BG", "🇧🇬"),
}


def _resolve_country(query: str):
    if not query:
        return None
    key = query.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    if key in COUNTRIES:
        return COUNTRIES[key]
    aliased = query.strip().lower()
    if aliased in COUNTRIES:
        return COUNTRIES[aliased]
    for k, v in COUNTRIES.items():
        if k.startswith(key) and len(key) >= 2:
            return v
    return None


def _safe(fn, default="─"):
    try:
        v = fn()
        return v if v not in (None, "") else default
    except Exception:
        return default


def _generate(locale: str) -> dict:
    f = _get_faker(locale)
    fb = _get_faker(FALLBACK_LOCALE) if locale != FALLBACK_LOCALE else None

    # Name: use first_name + last_name for better results
    first = _safe(f.first_name) or (fb and _safe(fb.first_name)) or "John"
    last  = _safe(f.last_name) or (fb and _safe(fb.last_name)) or "Doe"
    name  = f"{first} {last}"

    # Street address
    street = _safe(f.street_address) or (fb and _safe(fb.street_address)) or "123 Main St"

    # City
    city = _safe(f.city) or (fb and _safe(fb.city)) or "Unknown City"

    # State / region
    state = None
    if hasattr(f, "state"):
        state = _safe(f.state)
    if not state and hasattr(f, "administrative_unit"):
        state = _safe(f.administrative_unit)
    if not state and fb:
        state = _safe(fb.state) if hasattr(fb, "state") else "Unknown State"
    state = state or "─"

    # Postal code
    zipc = _safe(f.postcode) or (fb and _safe(fb.postcode)) or "00000"

    # Phone number
    phone = _safe(f.phone_number) or (fb and _safe(fb.phone_number)) or "+1-555-0100"

    # Email from name
    parts = "".join(c for c in name.lower() if c.isalpha() or c == " ").split()
    if len(parts) >= 2:
        local = f"{parts[0]}.{parts[-1]}{random.randint(10,9999)}"
    else:
        local = f"{parts[0] if parts else 'user'}{random.randint(100,99999)}"
    domain = random.choice(["gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "proton.me"])
    email = f"{local}@{domain}"

    # Date of birth
    dob = "─"
    try:
        dob = _safe(lambda: f.date_of_birth(minimum_age=21, maximum_age=65).strftime("%Y-%m-%d"))
    except Exception:
        pass

    # Job
    job = "─"
    try:
        job = _safe(f.job)
    except Exception:
        try:
            if fb:
                job = _safe(fb.job)
        except:
            pass

    # SSN / ID number (use ssn for US, may not exist for many locales)
    ssn = "─"
    if hasattr(f, "ssn"):
        ssn = _safe(f.ssn)
    elif fb and hasattr(fb, "ssn"):
        ssn = _safe(fb.ssn)

    return {
        "name": name, "gender": random.choice(["Male", "Female"]),
        "street": street, "city": city, "state": state,
        "zip": zipc, "phone": phone, "email": email,
        "ssn": ssn, "job": job, "dob": dob,
    }


def _build_text(person: dict, country_name: str, iso: str, flag: str, elapsed_ms: int) -> str:
    return (
        f"「 ADDRESS GENERATOR 」\n\n"
        f"Country ❝ {flag} <code>{country_name}</code> (<code>{iso}</code>)\n\n"
        f"<b>Identity</b>\n"
        f"Name ❝ <code>{person['name']}</code>\n"
        f"Gender ❝ <code>{person['gender']}</code>\n"
        f"DOB ❝ <code>{person['dob']}</code>\n"
        f"Job ❝ <code>{person['job']}</code>\n\n"
        f"<b>Address</b>\n"
        f"Street ❝ <code>{person['street']}</code>\n"
        f"City ❝ <code>{person['city']}</code>\n"
        f"State ❝ <code>{person['state']}</code>\n"
        f"Zip ❝ <code>{person['zip']}</code>\n"
        f"Country ❝ {flag} <code>{country_name}</code>\n\n"
        f"<b>Contact</b>\n"
        f"Phone ❝ <code>{person['phone']}</code>\n"
        f"Email ❝ <code>{person['email']}</code>\n"
        f"ID/SSN ❝ <code>{person['ssn']}</code>\n\n"
        f"Time ❝ <code>{elapsed_ms}ms</code>"
    )


def _regen_kb(country_key: str, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"{EMOJI_PLAIN['regenerate']} Regenerate",
            callback_data=f"gad:{country_key}:{uid}",
        )
    ]])

@router.message(Command("gad", "fake", "addr", prefix="/."))
async def cmd_gad(msg: Message, command: CommandObject, bot: Bot):
    uid = msg.from_user.id
    await db.upsert_user(uid, msg.from_user.username, msg.from_user.first_name)
    if await db.is_banned(uid):
        return

    if not await check_force_join(bot, uid):
        kb = await force_join_keyboard()
        await msg.answer(FORCE_JOIN_MSG, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    arg = (command.args or "").strip()
    if not arg:
        examples = "us, uk, ca, au, in, de, fr, es, it, br, jp, mx, ru, nl, tr, ph"
        await msg.answer(
            f"「 ADDRESS GENERATOR 」\n\n"
            f"Usage: <code>/gad &lt;country&gt;</code>\n"
            f"Example: <code>/gad us</code>\n\n"
            f"<b>Supported (short names / ISO):</b>\n<code>{examples}</code> ...",
            parse_mode=ParseMode.HTML,
        )
        return

    country_word = arg.split()[0]
    resolved = _resolve_country(country_word)
    if not resolved:
        await msg.answer(
            f"{EMOJI['declined']} Unknown country: <code>{country_word}</code>\n"
            f"Try: <code>/gad us</code>, <code>/gad uk</code>, <code>/gad de</code>, <code>/gad in</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    locale, country_name, iso, flag = resolved
    t0 = time.perf_counter()
    person = _generate(locale)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    text = _build_text(person, country_name, iso, flag, elapsed_ms)
    await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=_regen_kb(country_word.lower(), uid))


@router.callback_query(lambda q: q.data and q.data.startswith("gad:"))
async def cb_gad_regen(query: CallbackQuery):
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return await query.answer()
    country_key = parts[1]
    try:
        target_uid = int(parts[2])
    except ValueError:
        return await query.answer()
    if query.from_user.id != target_uid:
        return await query.answer("Not your session.", show_alert=True)

    resolved = _resolve_country(country_key)
    if not resolved:
        return await query.answer("Unknown country.", show_alert=True)

    locale, country_name, iso, flag = resolved
    t0 = time.perf_counter()
    person = _generate(locale)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    text = _build_text(person, country_name, iso, flag, elapsed_ms)

    try:
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=_regen_kb(country_key, target_uid),
        )
    except Exception:
        pass
    await query.answer("Regenerated")
