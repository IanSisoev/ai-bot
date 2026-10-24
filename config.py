import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID") or 0)
KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE") or "knowledge.example.md"
DB_FILE = os.getenv("DB_FILE") or "bot.db"

with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
    KNOWLEDGE = f.read()
