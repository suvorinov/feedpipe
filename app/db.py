import sqlite3
import os

# BASE_DIR теперь указывает на /app внутри контейнера
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "feedpipe.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False, isolation_level="DEFERRED")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Инициализирует БД правильной структурой"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            link TEXT UNIQUE,
            description TEXT,
            published_at TIMESTAMP,
            source_url TEXT,
            status TEXT DEFAULT 'inbox'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_url)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at)')

    conn.commit()
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
                except: pass
                
    conn.commit()
    conn.close()
    os.rename(txt_path, txt_path + ".migrated")