import logging
import sqlite3

from app.db import db_conn_context, write_lock

logger = logging.getLogger(__name__)

# Сколько дней архив хранится, прежде чем его вычистит ночная джоба.
ARCHIVE_RETENTION_DAYS = 90


class ArticleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_count_by_status(self, status: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM articles WHERE status = ?", (status,)).fetchone()
        return row[0]

    def get_inbox_count(self) -> int:
        return self.get_count_by_status("inbox")

    def get_later_count(self) -> int:
        return self.get_count_by_status("later")

    def get_by_status(self, status: str, before_id: int | None = None, limit: int = 50) -> tuple[list[dict], bool]:
        """Возвращает (статьи, has_more).

        Keyset-пагинация по id вместо OFFSET: берём на одну запись больше,
        чем нужно, чтобы узнать, есть ли следующая страница.
        """
        if before_id is None:
            cursor = self.conn.execute(
                "SELECT id, title, link, description, source_url, published_at "
                "FROM articles WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit + 1),
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, title, link, description, source_url, published_at "
                "FROM articles WHERE status = ? AND id < ? ORDER BY id DESC LIMIT ?",
                (status, before_id, limit + 1),
            )
        rows = [dict(row) for row in cursor.fetchall()]
        has_more = len(rows) > limit
        return rows[:limit], has_more

    def update_status(self, article_id: int, new_status: str) -> bool:
        with write_lock:
            cursor = self.conn.execute(
                "UPDATE articles SET status = ? WHERE id = ? AND status != ?",
                (new_status, article_id, new_status),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def bulk_insert(self, articles: list[dict]) -> int:
        """Пакетная вставка. Считаем реально добавленные через total_changes:
        INSERT OR IGNORE не трогает счётчик для пропущенных (уже есть link)."""
        saved_count = 0
        with write_lock:
            cursor = self.conn.cursor()
            rows = [(a["title"], a["link"], a["description"], a["published_at"], a["source_url"]) for a in articles]
            try:
                before = self.conn.total_changes
                cursor.executemany(
                    "INSERT OR IGNORE INTO articles "
                    "(title, link, description, published_at, source_url, status) "
                    "VALUES (?, ?, ?, ?, ?, 'inbox')",
                    rows,
                )
                saved_count = self.conn.total_changes - before
            except sqlite3.Error as e:
                # Одна битая строка не должна ронять всю пачку: вставляем по одной.
                logger.error(f"Пакетная вставка не удалась ({e}), вставляем по одной")
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
                    except sqlite3.Error as e2:
                        logger.error(f"Ошибка БД при сохранении {article['link']}: {e2}")
            self.conn.commit()
        return saved_count

    def delete_archived_older_than(self, days: int = ARCHIVE_RETENTION_DAYS) -> int:
        """Удаляет архив старше N дней. Возвращает число удалённых строк."""
        with write_lock:
            cursor = self.conn.execute(
                "DELETE FROM articles WHERE status = 'archived' AND datetime(published_at) < datetime('now', ?)",
                (f"-{days} days",),
            )
            self.conn.commit()
            return cursor.rowcount


def cleanup_archived_articles(days: int = ARCHIVE_RETENTION_DAYS) -> int:
    """Джоба планировщика: открывает свою консоль, чистит и закрывает."""
    with db_conn_context() as conn:
        return ArticleRepository(conn).delete_archived_older_than(days)
