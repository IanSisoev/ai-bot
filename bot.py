import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Я бот поддержки.")


@dp.message()
async def echo(message: Message):
    await message.answer(message.text)


async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


asyncio.run(main())
