from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import db
from .config import load_settings
from .handlers import admin, client, forwarder, payments


async def amain():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = load_settings()
    db.set_db_path(settings.db_path)
    await db.init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["settings"] = settings

    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(client.router)
    dp.include_router(forwarder.router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "edited_message",
            "channel_post",
            "callback_query",
            "pre_checkout_query",
            "my_chat_member",
        ],
    )


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
