import sqlite3

from config import DB_FILE

db = sqlite3.connect(DB_FILE)
db.row_factory = sqlite3.Row
