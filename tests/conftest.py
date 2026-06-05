import os
import sqlite3
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient


def _patch_db_path(tmp_path: Path) -> None:
    import app.db
    app.db.DB_PATH = str(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def test_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    _patch_db_path(tmp_path)
    import app.db
    app.db.init_db()
    conn = app.db.get_db()
    yield conn
    conn.close()


@pytest.fixture
def client(test_db: sqlite3.Connection) -> Generator[TestClient, None, None]:
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_db(test_db: sqlite3.Connection) -> sqlite3.Connection:
    test_db.execute(
        "INSERT INTO feeds (url, title) VALUES (?, ?)",
        ("https://example.com/rss", "Test Feed"),
    )
    test_db.execute(
        "INSERT INTO articles (title, link, description, published_at, source_url, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Test Article", "https://example.com/article1", "Description",
         "2024-01-01T00:00:00", "https://example.com/rss", "inbox"),
    )
    test_db.execute(
        "INSERT INTO articles (title, link, description, published_at, source_url, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Later Article", "https://example.com/article2", "Later desc",
         "2024-01-02T00:00:00", "https://example.com/rss", "later"),
    )
    test_db.commit()
    return test_db


@pytest.fixture
def auth_client(client: TestClient) -> Generator[TestClient, None, None]:
    client.post("/api/auth", data={"username": "testuser", "passphrase": "testkey"})
    yield client
