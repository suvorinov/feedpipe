import sqlite3
import os

# BASE_DIR теперь указывает на /app внутри контейнера
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "feedpipe.db")

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
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level="DEFERRED")
    conn.executescript(SCHEMA_SQL)
    conn.close()

def migrate_feeds_txt():
    """Одноразовая функция: переносит ссылки из feeds.txt в БД при первом запуске"""
    txt_path = os.path.join(BASE_DIR, "feeds.txt")

    if not os.path.exists(txt_path):
        return
    
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