import sqlite3
import logging

logger = logging.getLogger(__name__)


class ArticleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_count_by_status(self, status: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = ?", (status,)
        ).fetchone()
        return row[0]

    def get_inbox_count(self) -> int:
        return self.get_count_by_status("inbox")

    def get_later_count(self) -> int:
        return self.get_count_by_status("later")

    def get_by_status(self, status: str, offset: int = 0, limit: int = 50) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, title, link, description, source_url, published_at "
            "FROM articles WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_status(self, article_id: int, new_status: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE articles SET status = ? WHERE id = ? AND status != ?",
            (new_status, article_id, new_status),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def bulk_insert(self, articles: list[dict]) -> int:
        saved_count = 0
        cursor = self.conn.cursor()
        for article in articles:
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO articles "
                    "(title, link, description, published_at, source_url, status) "
                    "VALUES (?, ?, ?, ?, ?, 'inbox')",
                    (
                        article["title"],
                        article["link"],
                        article["description"],
                        article["published_at"],
                        article["source_url"],
                    ),
                )
                if cursor.rowcount > 0:
                    saved_count += 1
            except sqlite3.Error as e:
                logger.error(f"Ошибка БД при сохранении {article['link']}: {e}")
        self.conn.commit()
        return saved_count
