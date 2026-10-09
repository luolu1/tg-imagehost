from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot import admin, common, deletion, info, upload
from app.bot.middlewares import ContextMiddleware
from app.config import settings
from app.db import init_db

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="开始使用"),
    BotCommand(command="help", description="帮助"),
    BotCommand(command="id", description="获取用户/群组/频道 ID"),
    BotCommand(command="token", description="获取 API Token"),
    BotCommand(command="stats", description="我的用量"),
    BotCommand(command="delete", description="删除图片"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await init_db()

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(ContextMiddleware())

    dp.include_router(common.router)
    dp.include_router(info.router)
    dp.include_router(upload.router)
    dp.include_router(deletion.router)
    dp.include_router(admin.router)

    await bot.set_my_commands(COMMANDS)
    me = await bot.get_me()
    info.set_bot_username(me.username)
    log.info("Bot started as @%s", me.username)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
