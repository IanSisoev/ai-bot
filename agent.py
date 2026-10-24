import json
import logging
import re
from datetime import date, datetime, timedelta

from aiogram.types import User
from gigachat import GigaChat

import schedule
import storage
from config import GIGACHAT_CREDENTIALS, KNOWLEDGE

logger = logging.getLogger(__name__)

MAX_STEPS = 5
HANDOFF_PHRASE = "Тут лучше поможет администратор. Нажмите кнопку, и я передам ему ваш вопрос."
HANDOFF_MARK = "поможет администратор"

SYSTEM_PROMPT = f"""Ты ИИ-администратор вейк-парка. Название, цены и правила парка указаны в базе знаний ниже.
Ты бот, а не человек. Если спрашивают, кто ты, отвечай, что ты ИИ-администратор.
Отвечай коротко и дружелюбно.
Отвечай, только если ответ прямо написан в базе знаний или пришёл из функций.
Свободное время и записи клиента узнавай только через функции, никогда не придумывай их.
Не делай выводов о том, чего в базе нет.
Никогда не придумывай цены: если цены нет в базе знаний, например у блюда из меню, значит, прямого ответа нет.
Если прямого ответа нет или клиент просит живого человека, ответь ровно так: «{HANDOFF_PHRASE}»
Запись, отмена и перенос выполняются, только когда клиент нажмёт кнопку «Подтвердить» под сообщением.
Даты клиенту называй словами, например «25 октября», а не 2026-10-25.

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

giga = GigaChat(
    credentials=GIGACHAT_CREDENTIALS,
    model="GigaChat-2",
    verify_ssl_certs=False,
)


def system_prompt() -> str:
    today = date.today()
    return f"Сегодня {today.isoformat()}, {WEEKDAYS[today.weekday()]}.\n{SYSTEM_PROMPT}"


def join_thousands(text: str) -> str:
    return re.sub(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))", "", text)


KNOWN_NUMBERS = set(re.findall(r"\d+", join_thousands(KNOWLEDGE)))


def invented_prices(reply: str) -> list[str]:
    prices = re.findall(r"(\d+)\s*(?:₽|руб)", join_thousands(reply))
    return [price for price in prices if price not in KNOWN_NUMBERS]


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
            action = {"booking_id": booking["id"], "day": booking["day"], "time": booking["time"]}
            check = {"ok": True}
            if name == "move":
                action["old_day"], action["old_time"] = booking["day"], booking["time"]
                action["day"], action["time"] = iso(args["new_day"]), str(args["new_time"])
                check = check_new_set(mine, action["day"], action["time"])
        else:
            return {"ok": False, "error": f"Нет такой функции: {name}"}
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Неверные параметры: дата нужна в формате ГГГГ-ММ-ДД, время в формате ЧЧ:ММ"}

    if not check["ok"]:
        return check
    storage.set_pending(user.id, name, action)
    return {"ok": True, "status": "Ждёт, когда клиент нажмёт кнопку «Подтвердить»"}


def short_day(day: str) -> str:
    return date.fromisoformat(day).strftime("%d.%m")


def confirmation_text(name: str, action: dict) -> str:
    if name == "book":
        return f"Записать вас на {short_day(action['day'])} в {action['time']}?"
    if name == "cancel":
        return f"Отменить запись на {short_day(action['day'])} в {action['time']}?"
    return (f"Перенести запись с {short_day(action['old_day'])} {action['old_time']} "
            f"на {short_day(action['day'])} {action['time']}?")


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
    if name == "book":
        return f"Готово, вы записаны на {short_day(result['day'])} в {result['time']}."
    return f"Готово, запись перенесена на {short_day(result['day'])} в {result['time']}."


async def ask_gigachat(messages: list[dict], user: User) -> str:
    for _ in range(MAX_STEPS):
        response = await giga.achat({
            "messages": messages,
            "functions": FUNCTIONS,
            "function_call": "auto",
            "temperature": 0.1,
        })
        choice = response.choices[0]
        if choice.finish_reason != "function_call":
            return choice.message.content or "Не получилось ответить, попробуйте ещё раз."

        call = choice.message.function_call
        arguments = call.arguments or {}
        result = run_function(call.name, arguments, user)
        logger.info("Функция %s(%s) -> %s", call.name, arguments, str(result)[:150])
        pending = storage.get_pending(user.id)
        if pending:
            return confirmation_text(*pending)

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


async def answer_client(text: str, user: User, chat_id: int) -> str:
    messages = (
        [{"role": "system", "content": system_prompt()}]
        + storage.get_history(chat_id)
        + [{"role": "user", "content": text}]
    )
    reply = await ask_gigachat(messages, user)
    if invented_prices(reply):
        logger.warning("Цена не из базы, ответ заменён: %s", reply)
        reply = HANDOFF_PHRASE
    return reply
