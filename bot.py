import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from gigachat import GigaChat

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
giga = GigaChat(
    credentials=os.getenv("GIGACHAT_CREDENTIALS"),
    model="GigaChat-2",
    verify_ssl_certs=False,
)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Я бот поддержки.")


@dp.message()
async def echo(message: Message):
    if message.text is None:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
    else:
        response = await giga.achat(message.text)
        await message.answer(response.choices[0].message.content)


async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


asyncio.run(main())
