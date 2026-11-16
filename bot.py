"""Entry point: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    try:
        async with Bot(token=BOT_TOKEN) as bot:
            # Drop updates that piled up while the bot was offline.
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        raise SystemExit(
            "Telegram rejected BOT_TOKEN (Unauthorized). Check .env and replace it "
            "with the current token from @BotFather."
        ) from None


if __name__ == "__main__":
    asyncio.run(main())
