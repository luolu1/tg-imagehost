"""Entry point for the Telegram bot process."""

import asyncio

from app.bot.main import main

if __name__ == "__main__":
    asyncio.run(main())
