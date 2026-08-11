import datetime
import os
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Python 3.12+ помечает встроенный адаптер datetime как устаревший.
# Регистрируем свой: храним даты в ISO-формате (совместимо со строками,
# которые уже лежат в базе, и с format_date в шаблонах).
sqlite3.register_adapter(datetime.datetime, lambda dt: dt.isoformat(sep=" "))
sqlite3.register_adapter(datetime.date, lambda d: d.isoformat())

# Каталог данных можно переопределить через окружение (важно для Docker,
# где volume монтируется в /app/data). По умолчанию — рядом с кодом.
DATA_DIR = os.environ.get("FEEDPIPE_DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "feedpipe.db")

# SQLite допускает только одного писателя. Чтобы не ловить
# "database is locked" при одновременной записи из парсера и веб-запросов,
# все write-операции в пределах процесса сериализуем этой блокировкой.
write_lock = threading.RLock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    link TEXT UNIQUE,
    description TEXT,
    published_at TIMESTAMP,
    source_url TEXT,
    status TEXT DEFAULT 'inbox'
);
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    secret_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_url);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
"""

def _ensure_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("SELECT 1 FROM articles LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False, isolation_level="DEFERRED")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn

def init_db():
    with write_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level="DEFERRED")
        conn.executescript(SCHEMA_SQL)
        conn.close()

def migrate_feeds_txt():
    """Одноразовая функция: переносит ссылки из feeds.txt в БД при первом запуске"""
    txt_path = os.path.join(BASE_DIR, "feeds.txt")

    if not os.path.exists(txt_path):
        return

    with write_lock:
        conn = get_db()
        cursor = conn.cursor()

        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        cursor.execute("INSERT OR IGNORE INTO feeds (url) VALUES (?)", (line,))
                    except Exception:
                        pass

        conn.commit()
        conn.close()
    os.rename(txt_path, txt_path + ".migrated")