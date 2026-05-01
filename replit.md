# Deven Hitter — Telegram Bot

Async Telegram bot built on **aiogram 3** with a MongoDB-style data layer
(motor in production, mongomock-motor for local in-memory dev).

## Stack

- Python 3.12 (runtime in Replit; `runtime.txt` requests 3.11 for Railway)
- aiogram >= 3
- motor / mongomock-motor (drop-in fallback when `MONGO_URL` is empty)
- httpx, requests, curl_cffi, tls_client (HTTP / TLS clients used by checkers)
- python-dotenv (env loading)

## Layout

```
main.py                     entrypoint (bot polling)
config.py                   bot token, owner ids, plans, proxies, branding
database/db.py              all data access (motor / mongomock)
commands/                   aiogram routers (one router per command file)
  __init__.py               aggregates and registers every router
  start.py                  /start + main menu callbacks
  auth.py                   /auth — auth-only checker
  shopify.py                /sh — shopify checker (uses external gate)
  gen.py / co.py            card gen, mass checker
  proxy.py                  /proxy management
  admin.py                  /admin, /ban, /unban, /broadcast, redeem codes
  tempmail.py               /temp1 /temp2 /temp3 — temp mail
  wallet.py                 /wallet
  referral.py               /ref
  adb.py                    /adb — Adobe-style auth checker (newly wired)
  b3.py                     /b3 — Braintree-style auth wrapper (newly wired,
                              calls into commands/b3_auth_lib.py)
  stripe.py                 /stripe — Stripe single-card wrapper
                              (newly wired, calls into commands/st.py)
  b3_auth_lib.py            checker library used by /b3 (was "b3 auth.py")
  sh.py / shop.py / st.py   standalone checker libraries (used by wrappers)
  bot_st_legacy.py          old standalone telebot Stripe bot (reference)
  bot_pp_legacy.py          old standalone telebot PayPal bot (reference)
  bot_cc_legacy.py          old standalone telethon CC bot (reference)
functions/                  middleware, helpers, BIN lookup, emojis, etc.
```

## Owner / branding

- Permanent owner Telegram user ID: **6699193683**
- Owner / support handle: **@hqdeven**
- All previous third-party branding has been stripped from the source.

## Configuration

Defaults are baked into `config.py` so the bot runs out of the box, but every
value can still be overridden by environment variables / Replit Secrets:

| Var | Default | Notes |
| --- | --- | --- |
| `BOT_TOKEN` | permanent value baked in | Telegram bot token |
| `OWNER_IDS` | `6699193683` | comma-separated ints |
| `MONGO_URL` | empty → mongomock in-memory | set to a real Mongo URI to persist |
| `DB_NAME` | `codevenbot` | Mongo database name |
| `LOG_CHANNEL_ID` | empty | optional log channel |
| `FORCE_JOIN_CHANNELS` | empty | optional, comma-separated |

## Running

`python main.py` (the **Telegram Bot** workflow runs this automatically).

## Recent changes (this Replit setup)

### First pass — bootstrap
- Hard-coded permanent owner id `6699193683` and `BOT_TOKEN` defaults in
  `config.py` so the bot starts without external secrets.
- Added in-memory `mongomock_motor` fallback in `database/db.py` so the bot
  runs without a MongoDB server (warns at startup; data not persisted).
- Owner ids are auto-seeded as admins in DB on every startup.
- Renamed orphan files with spaces / parens to valid module names
  (`b3 auth.py`, `bot.py`, `bot (1).py`, `bot (2).py` →
  `b3_auth_lib.py`, `bot_st_legacy.py`, `bot_pp_legacy.py`, `bot_cc_legacy.py`).
- Stripped third-party branding from `commands/shop.py` (now `@hqdeven`).
- Wired previously-unregistered routers `/adb`, `/b3`, `/stripe` and
  configured the **Telegram Bot** workflow (`python main.py`).

### Second pass — UX + new gates + deployment
- **Admin badge fixed.** `/start`, `/credits`, `/admin`, `/whoami` and the
  Credits inline screen now detect role (owner / admin / user) up-front and
  show an `OWNER`/`ADMIN` badge with `Unlimited ♾` instead of treating
  staff as a Free user. Hits are never deducted from staff accounts.
- **Three new card gates wired as fresh aiogram routers** (legacy
  checker libs reused via direct function call — the legacy bot loops
  themselves are never started):
  - `commands/pp.py`  — `/pp` single, `/mpp` mass (PayPal Commerce $1)
  - `commands/mst.py` — `/mst` single, `/mass-st` mass (Stripe SetupIntent)
  - `commands/chk.py` — `/chk` single, `/mchk` mass (direct Shopify API)
- `commands/lib_shop_api.py` — pure-async helper extracted from
  `bot_cc_legacy.py` (no telethon import, safe to load).
- Modern home / credits / admin / help screens use a card layout
  (`╭─ … │ … ╰─`) and clean spacing instead of the old `「 」` brackets.
- `/help` now lists every command grouped by **Card gates / Tools /
  Account / Admin**.
- Configured **Reserved VM** deployment so the polling bot stays online
  (autoscale would sleep). Click *Publish* to deploy.

### `/gad` — fake address generator (per country)
- New router `commands/gad.py` exposing `/gad <country>` (aliases:
  `/fake`, `/addr`). Uses the `Faker` library with locale per country
  (e.g. `us` → `en_US`, `de` → `de_DE`, `in` → `en_IN`).
- Output is a styled card with **Identity** (name, gender, DOB, job),
  **Address** (street, city, state, zip, country) and **Contact**
  (phone, generated email, SSN/national ID where Faker supports it).
- Inline **Regenerate** button calls back into the same locale and
  produces a fresh identity each time (no caching).
- Country lookup supports both ISO codes and full names with fuzzy
  prefix match (`/gad united` → United States, etc.) and is registered
  in `functions/cmd_registry.py` so `/cmd off /gad` works and the
  command appears in Telegram's slash menu and in `/help`.

### `.txt` file input + per-hit notifications
- New shared helper `functions/file_input.py` (`read_attached_txt`,
  `read_lines_from_txt`) reads a `.txt` document attached to the
  message itself or to the message it replies to (5 MB cap, UTF-8).
- `/mass-st`, `/mpp`, `/mchk` and `/hit` now accept a `.txt` file as a
  card source; cap raised from 25 → 200 when input came from a file.
- During mass runs each **APPROVED / CHARGED / LIVE / 3DS** card now
  triggers an additional one-shot `msg.answer(...)` so live hits land
  in the chat one at a time alongside the rolling progress edit.
- `/proxy add` accepts the same: send `/proxy add` with an attached or
  replied-to `.txt` (one proxy per line) and every line is tested and
  saved if alive. Inline text and the file are merged + de-duped.
