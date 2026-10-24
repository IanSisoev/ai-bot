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
Ты бот, а не человек. Если спрашивают, кто ты, отвечай, что ты ИИ-администратор.
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

HISTORY_LIMIT = 10
history: dict[int, list[dict]] = {}


@dp.message(CommandStart())
async def start(message: Message):
    history.pop(message.chat.id, None)
    await message.answer("Привет! Я ИИ-администратор вейк-парка. Спросите про цены, обучение или правила.")


@dp.message()
async def answer(message: Message):
    if message.text is None:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    chat_history = history.get(message.chat.id, [])
    user_message = {"role": "user", "content": message.text}

    response = await giga.achat({
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + chat_history + [user_message]
    })
    reply = response.choices[0].message.content

    chat_history = chat_history + [user_message, {"role": "assistant", "content": reply}]
    history[message.chat.id] = chat_history[-HISTORY_LIMIT:]

    await message.answer(reply)


async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


asyncio.run(main())
