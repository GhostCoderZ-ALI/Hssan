import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, BOT_NAME
import database.db as db

from commands import router as main_router
from functions.middleware import MaintenanceMiddleware, CommandDisabledMiddleware
from functions.cmd_registry import update_bot_commands


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_bot():

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    logger.info("Initialising database...")
    await db.get_db()
    logger.info("Database ready.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    # ROUTERS
    dp.include_router(main_router)

    # MIDDLEWARE
    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())
    dp.message.middleware(CommandDisabledMiddleware())

    logger.info(f"Starting {BOT_NAME}...")

    await bot.delete_webhook(drop_pending_updates=True)

    # Sync the slash menu so disabled commands stay hidden across restarts.
    try:
        await update_bot_commands(bot)
    except Exception as e:
        logger.warning("could not sync bot commands menu: %s", e)

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


async def main():

    retries = 0

    while True:

        try:
            await run_bot()
            break

        except KeyboardInterrupt:
            break

        except Exception as e:

            retries += 1
            logger.error(f"Bot crashed {retries}: {e}")

            if retries >= 10:
                break

            await asyncio.sleep(min(retries * 5, 60))


if __name__ == "__main__":
    asyncio.run(main())
