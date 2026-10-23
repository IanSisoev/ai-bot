import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from gigachat import GigaChat


load_dotenv()

KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE", "knowledge.example.md")
with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
    KNOWLEDGE = f.read()

print(f"База знаний: {KNOWLEDGE_FILE}, {len(KNOWLEDGE)} символов")

SYSTEM_PROMPT = f"""Ты ИИ-администратор вейк-парка. Название, цены и правила парка указаны в базе знаний ниже.
Отвечай коротко и дружелюбно.
Отвечай, только если ответ прямо написан в базе знаний.
Не делай выводов о том, чего в базе нет.
Если прямого ответа нет, ответь ровно так: «У меня нет такой информации, уточните, пожалуйста, у администратора парка».

База знаний:
{KNOWLEDGE}"""

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
giga = GigaChat(
    credentials=os.getenv("GIGACHAT_CREDENTIALS"),
    model="GigaChat-2",
    verify_ssl_certs=False,
)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Я ИИ-администратор вейк-парка. Спросите про цены, обучение или правила.")


@dp.message()
async def echo(message: Message):
    if message.text is None:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
    else:
        response = await giga.achat({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text},
            ]
        })
        await message.answer(response.choices[0].message.content)


async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


asyncio.run(main())
