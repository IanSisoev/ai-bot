import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from dotenv import load_dotenv
from gigachat import GigaChat

import schedule

load_dotenv()

KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE", "knowledge.example.md")
with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
    KNOWLEDGE = f.read()
print(f"База знаний: {KNOWLEDGE_FILE}, {len(KNOWLEDGE)} символов")

SYSTEM_PROMPT = f"""Ты ИИ-администратор вейк-парка. Название, цены и правила парка указаны в базе знаний ниже.
Ты бот, а не человек. Если спрашивают, кто ты, отвечай, что ты ИИ-администратор.
Отвечай коротко и дружелюбно.
Отвечай, только если ответ прямо написан в базе знаний или пришёл из функций.
Свободное время и записи клиента узнавай только через функции, никогда не придумывай их.
Не делай выводов о том, чего в базе нет.
Если прямого ответа нет, ответь ровно так: «У меня нет такой информации, уточните, пожалуйста, у администратора парка».
Запись, отмена и перенос выполняются, только когда клиент нажмёт кнопку «Подтвердить». Когда вызываешь такую функцию, назови клиенту день и время и попроси нажать кнопку.

База знаний:
{KNOWLEDGE}"""

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

FUNCTIONS = [
    {
        "name": "free_sets",
        "description": "Возвращает свободные промежутки времени на реверсивной лебёдке на указанный день. Сеты длятся 10 минут и начинаются каждые 10 минут",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Дата в формате ГГГГ-ММ-ДД"},
            },
            "required": ["day"],
        },
    },
    {
        "name": "book",
        "description": "Готовит запись клиента на сет реверсивной лебёдки. Запись создаётся, когда клиент нажмёт кнопку «Подтвердить»",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Дата в формате ГГГГ-ММ-ДД"},
                "time": {"type": "string", "description": "Время начала сета, например 12:10"},
            },
            "required": ["day", "time"],
        },
    },
    {
        "name": "my_bookings",
        "description": "Возвращает будущие записи клиента: день и время",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel",
        "description": "Готовит отмену записи клиента. Отмена выполняется, когда клиент нажмёт кнопку «Подтвердить»",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Дата записи в формате ГГГГ-ММ-ДД"},
                "time": {"type": "string", "description": "Время записи, например 12:10"},
            },
            "required": ["day", "time"],
        },
    },
    {
        "name": "move",
        "description": "Готовит перенос записи клиента на другой день или время. Перенос выполняется, когда клиент нажмёт кнопку «Подтвердить»",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Текущая дата записи в формате ГГГГ-ММ-ДД"},
                "time": {"type": "string", "description": "Текущее время записи, например 12:10"},
                "new_day": {"type": "string", "description": "Новая дата в формате ГГГГ-ММ-ДД"},
                "new_time": {"type": "string", "description": "Новое время начала сета, например 12:30"},
            },
            "required": ["day", "time", "new_day", "new_time"],
        },
    },
]

CONFIRM_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="Подтвердить", callback_data="confirm"),
    InlineKeyboardButton(text="Не надо", callback_data="reject"),
]])

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
giga = GigaChat(
    credentials=os.getenv("GIGACHAT_CREDENTIALS"),
    model="GigaChat-2",
    verify_ssl_certs=False,
)

HISTORY_LIMIT = 10
MAX_STEPS = 5
history: dict[int, list[dict]] = {}
pending: dict[int, tuple[str, dict]] = {}


def system_prompt() -> str:
    today = date.today()
    return f"Сегодня {today.isoformat()}, {WEEKDAYS[today.weekday()]}.\n{SYSTEM_PROMPT}"


def remember(chat_id: int, user_text: str, reply: str) -> None:
    chat_history = history.get(chat_id, []) + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": reply},
    ]
    history[chat_id] = chat_history[-HISTORY_LIMIT:]


def to_ranges(times: list[str]) -> list[str]:
    ranges = []
    for t in times:
        start = datetime.strptime(t, "%H:%M")
        end = start + timedelta(minutes=schedule.SET_MINUTES)
        if ranges and ranges[-1][1] == start:
            ranges[-1][1] = end
        else:
            ranges.append([start, end])
    return [f"с {a:%H:%M} до {b:%H:%M}" for a, b in ranges]


def iso(day) -> str:
    return date.fromisoformat(str(day)).isoformat()


def as_slots(bookings: list[dict]) -> list[dict]:
    return [{"day": b["day"], "time": b["time"]} for b in bookings]


def find_booking(bookings: list[dict], day: str, time: str) -> dict | None:
    for b in bookings:
        if b["day"] == day and b["time"] == time:
            return b
    return None


def check_new_set(bookings: list[dict], day: str, time: str) -> dict:
    if find_booking(bookings, day, time):
        return {"ok": False, "error": "Клиент уже записан на это время"}
    return schedule.check_set(day, time)


def run_function(name: str, args: dict, user: User) -> dict:
    try:
        if name == "free_sets":
            result = schedule.free_sets(str(args["day"]))
            if result["ok"]:
                result["free"] = to_ranges(result["free"])
            return result

        mine = schedule.my_bookings(user.id)["bookings"]
        if name == "my_bookings":
            return {"ok": True, "bookings": as_slots(mine)}

        if name == "book":
            action = {"day": iso(args["day"]), "time": str(args["time"])}
            check = check_new_set(mine, action["day"], action["time"])
        elif name in ("cancel", "move"):
            booking = find_booking(mine, iso(args["day"]), str(args["time"]))
            if booking is None:
                return {"ok": False, "error": "У клиента нет записи на это время", "bookings": as_slots(mine)}
            action = {"booking_id": booking["id"]}
            check = {"ok": True}
            if name == "move":
                action["day"], action["time"] = iso(args["new_day"]), str(args["new_time"])
                check = check_new_set(mine, action["day"], action["time"])
        else:
            return {"ok": False, "error": f"Нет такой функции: {name}"}
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Неверные параметры: дата нужна в формате ГГГГ-ММ-ДД, время в формате ЧЧ:ММ"}

    if not check["ok"]:
        return check
    pending[user.id] = (name, action)
    return {"ok": True, "status": "Ждёт, когда клиент нажмёт кнопку «Подтвердить»"}


def execute(name: str, action: dict, user: User) -> str:
    if name == "book":
        result = schedule.book(action["day"], action["time"], user.id, user.full_name)
    elif name == "move":
        result = schedule.move(action["booking_id"], user.id, action["day"], action["time"])
    else:
        result = schedule.cancel(action["booking_id"], user.id)

    if not result["ok"]:
        return f"Не получилось: {result['error']}"
    if name == "cancel":
        return "Готово, запись отменена."
    day = date.fromisoformat(result["day"]).strftime("%d.%m")
    if name == "book":
        return f"Готово, вы записаны на {day} в {result['time']}."
    return f"Готово, запись перенесена на {day} в {result['time']}."


async def ask_gigachat(messages: list[dict], user: User) -> str:
    for _ in range(MAX_STEPS):
        response = await giga.achat({
            "messages": messages,
            "functions": FUNCTIONS,
            "function_call": "auto",
        })
        choice = response.choices[0]
        if choice.finish_reason != "function_call":
            return choice.message.content or "Не получилось ответить, попробуйте ещё раз."

        call = choice.message.function_call
        arguments = call.arguments or {}
        result = run_function(call.name, arguments, user)
        print(f"Функция {call.name}({arguments}) -> {str(result)[:150]}")

        messages.append({
            "role": "assistant",
            "content": "",
            "function_call": {"name": call.name, "arguments": arguments},
            "functions_state_id": choice.message.functions_state_id,
        })
        messages.append({
            "role": "function",
            "name": call.name,
            "content": json.dumps(result, ensure_ascii=False),
        })
    return "Не получилось выполнить запрос, попробуйте сформулировать иначе."


@dp.message(CommandStart())
async def start(message: Message):
    history.pop(message.chat.id, None)
    pending.pop(message.from_user.id, None)
    await message.answer("Привет! Я ИИ-администратор вейк-парка. Спросите про цены и правила или запишитесь на реверс.")


@dp.message()
async def answer(message: Message):
    if message.text is None:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    user = message.from_user
    pending.pop(user.id, None)
    messages = (
        [{"role": "system", "content": system_prompt()}]
        + history.get(message.chat.id, [])
        + [{"role": "user", "content": message.text}]
    )

    try:
        reply = await ask_gigachat(messages, user)
    except Exception:
        logging.exception("Ошибка при обращении к GigaChat")
        await message.answer("Не получилось ответить, попробуйте через минуту.")
        return

    remember(message.chat.id, message.text, reply)
    keyboard = CONFIRM_KEYBOARD if user.id in pending else None
    await message.answer(reply, reply_markup=keyboard)


@dp.callback_query(F.data == "confirm")
async def confirm(callback: CallbackQuery):
    action = pending.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    if action is None:
        await callback.answer("Это действие уже неактуально")
        return
    name, details = action
    text = execute(name, details, callback.from_user)
    remember(callback.message.chat.id, "Подтверждаю", text)
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "reject")
async def reject(callback: CallbackQuery):
    pending.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    text = "Хорошо, ничего не меняю."
    remember(callback.message.chat.id, "Не надо", text)
    await callback.message.answer(text)
    await callback.answer()


async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())