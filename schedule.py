import sqlite3
from datetime import date, datetime, timedelta

from db import db

OPEN_HOUR = 10
CLOSE_HOUR = 21
SET_MINUTES = 10
DAYS_AHEAD = 14

db.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY,
        day TEXT NOT NULL,
        time TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'не оплачено',
        cancel_reason TEXT
    )
""")
db.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS one_rider_per_set
    ON bookings (day, time) WHERE status != 'отменено'
""")


def free_sets(day: str) -> dict:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return {"ok": False, "error": "Дата должна быть в формате ГГГГ-ММ-ДД"}
    today = date.today()
    if d < today:
        return {"ok": False, "error": "Эта дата уже прошла"}
    if d > today + timedelta(days=DAYS_AHEAD):
        return {"ok": False, "error": f"Записаться можно не больше чем на {DAYS_AHEAD} дней вперёд"}

    day = d.isoformat()
    rows = db.execute(
        "SELECT time FROM bookings WHERE day = ? AND status != 'отменено'", (day,)
    )
    busy = {row["time"] for row in rows}

    now = datetime.now()
    t = datetime(d.year, d.month, d.day, OPEN_HOUR)
    end = datetime(d.year, d.month, d.day, CLOSE_HOUR)
    free = []
    while t < end:
        if t > now and t.strftime("%H:%M") not in busy:
            free.append(t.strftime("%H:%M"))
        t += timedelta(minutes=SET_MINUTES)
    return {"ok": True, "day": day, "free": free}


def check_set(day: str, time: str) -> dict:
    slots = free_sets(day)
    if not slots["ok"]:
        return slots
    if time not in slots["free"]:
        return {"ok": False, "error": "Это время занято или недоступно"}
    return {"ok": True, "day": slots["day"]}


def book(day: str, time: str, user_id: int, name: str) -> dict:
    check = check_set(day, time)
    if not check["ok"]:
        return check
    try:
        with db:
            cur = db.execute(
                "INSERT INTO bookings (day, time, user_id, name) VALUES (?, ?, ?, ?)",
                (check["day"], time, user_id, name),
            )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Это время только что заняли"}
    return {"ok": True, "booking_id": cur.lastrowid, "day": check["day"], "time": time}


def my_bookings(user_id: int) -> dict:
    rows = db.execute(
        "SELECT id, day, time, status FROM bookings "
        "WHERE user_id = ? AND status != 'отменено' AND day >= ? ORDER BY day, time",
        (user_id, date.today().isoformat()),
    )
    return {"ok": True, "bookings": [dict(row) for row in rows]}


def cancel(booking_id: int, user_id: int) -> dict:
    with db:
        cur = db.execute(
            "UPDATE bookings SET status = 'отменено', cancel_reason = 'отмена клиентом' "
            "WHERE id = ? AND user_id = ? AND status != 'отменено'",
            (booking_id, user_id),
        )
    if cur.rowcount == 0:
        return {"ok": False, "error": "Запись не найдена"}
    return {"ok": True, "booking_id": booking_id}


def move(booking_id: int, user_id: int, day: str, time: str) -> dict:
    check = check_set(day, time)
    if not check["ok"]:
        return check
    try:
        with db:
            cur = db.execute(
                "UPDATE bookings SET day = ?, time = ? "
                "WHERE id = ? AND user_id = ? AND status != 'отменено'",
                (check["day"], time, booking_id, user_id),
            )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Это время только что заняли"}
    if cur.rowcount == 0:
        return {"ok": False, "error": "Запись не найдена"}
    return {"ok": True, "booking_id": booking_id, "day": check["day"], "time": time}
