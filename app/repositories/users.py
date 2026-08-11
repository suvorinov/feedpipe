import sqlite3

from app.db import write_lock


class UserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def find_by_username(self, username: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None

    def create(self, username: str, secret_hash: str) -> None:
        with write_lock:
            self.conn.execute(
                "INSERT INTO users (username, secret_hash) VALUES (?, ?)",
                (username, secret_hash),
            )
            self.conn.commit()
