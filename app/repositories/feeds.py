import logging
import sqlite3

from app.db import write_lock

logger = logging.getLogger(__name__)


class FeedRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_all(self) -> list[dict]:
        cursor = self.conn.execute("SELECT id, url, title FROM feeds ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]

    def get_all_urls(self) -> list[str]:
        cursor = self.conn.execute("SELECT url FROM feeds")
        return [row["url"] for row in cursor.fetchall()]

    def add(self, url: str, title: str) -> None:
        with write_lock:
            self.conn.execute("INSERT INTO feeds (url, title) VALUES (?, ?)", (url, title))
            self.conn.commit()

    def delete(self, feed_id: int) -> None:
        """Удаляет фид и все его статьи.

        Статьи без своего источника никому не нужны: иначе они молча
        висели бы во Входящих вечно.
        """
        with write_lock:
            feed = self.conn.execute("SELECT url FROM feeds WHERE id = ?", (feed_id,)).fetchone()
            if feed is not None:
                self.conn.execute("DELETE FROM articles WHERE source_url = ?", (feed["url"],))
            self.conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
            self.conn.commit()
