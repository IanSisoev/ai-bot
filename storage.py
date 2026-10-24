import json

from db import db

HISTORY_LIMIT = 10

db.executescript("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pending (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        action TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS handoff_questions (
        user_id INTEGER PRIMARY KEY,
        question TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_threads (
        message_id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        question TEXT NOT NULL
    );
""")


# История диалога

def get_history(chat_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT role, content FROM ("
        "    SELECT id, role, content FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?"
        ") ORDER BY id",
        (chat_id, HISTORY_LIMIT),
    )
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def remember(chat_id: int, user_text: str, reply: str) -> None:
    with db:
        db.executemany(
            "INSERT INTO history (chat_id, role, content) VALUES (?, ?, ?)",
            [(chat_id, "user", user_text), (chat_id, "assistant", reply)],
        )


def clear_history(chat_id: int) -> None:
    with db:
        db.execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))


# Действия, которые ждут кнопку «Подтвердить»

def set_pending(user_id: int, name: str, action: dict) -> None:
    with db:
        db.execute(
            "INSERT OR REPLACE INTO pending (user_id, name, action) VALUES (?, ?, ?)",
            (user_id, name, json.dumps(action, ensure_ascii=False)),
        )


def get_pending(user_id: int) -> tuple[str, dict] | None:
    row = db.execute("SELECT name, action FROM pending WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return row["name"], json.loads(row["action"])


def pop_pending(user_id: int) -> tuple[str, dict] | None:
    pending = get_pending(user_id)
    with db:
        db.execute("DELETE FROM pending WHERE user_id = ?", (user_id,))
    return pending


# Вопросы, которые клиент может передать администратору кнопкой

def set_handoff_question(user_id: int, question: str) -> None:
    with db:
        db.execute(
            "INSERT OR REPLACE INTO handoff_questions (user_id, question) VALUES (?, ?)",
            (user_id, question),
        )


def pop_handoff_question(user_id: int) -> str | None:
    row = db.execute("SELECT question FROM handoff_questions WHERE user_id = ?", (user_id,)).fetchone()
    with db:
        db.execute("DELETE FROM handoff_questions WHERE user_id = ?", (user_id,))
    return row["question"] if row else None


# Какое сообщение в группе администраторов относится к какому клиенту

def save_admin_thread(message_id: int, chat_id: int, question: str) -> None:
    with db:
        db.execute(
            "INSERT OR REPLACE INTO admin_threads (message_id, chat_id, question) VALUES (?, ?, ?)",
            (message_id, chat_id, question),
        )


def get_admin_thread(message_id: int) -> tuple[int, str] | None:
    row = db.execute(
        "SELECT chat_id, question FROM admin_threads WHERE message_id = ?", (message_id,)
    ).fetchone()
    if row is None:
        return None
    return row["chat_id"], row["question"]
