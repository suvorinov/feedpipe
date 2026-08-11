import os
import sqlite3
from pathlib import Path
from typing import Generator

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("FEEDPIPE_SECRET", "test-secret-not-for-production")

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<link>https://site.example</link>
<description>Test channel</description>
<item><title>Article One</title><link>https://site.example/a1</link>
<description>First article</description>
<pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate></item>
<item><title>Article Two</title><link>https://site.example/a2</link>
<description>Second article</description>
<pubDate>Tue, 02 Jan 2024 12:00:00 +0000</pubDate></item>
</channel></rss>
"""

SITE_HTML = """<html><head>
<link rel="alternate" type="application/rss+xml" href="/feed">
</head><body>site</body></html>
"""


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    """Подменяет httpx.AsyncClient: отдаёт заранее заготовленные ответы по URL."""

    responses = {
        "https://site.example": FakeResponse(SITE_HTML),
        "https://site.example/feed": FakeResponse(RSS_XML),
        "https://example.com/rss": FakeResponse(RSS_XML),
    }

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, *args, **kwargs):
        self.calls.append(url)
        try:
            return self.responses[url]
        except KeyError:
            raise httpx.ConnectError(f"no mock for {url}") from None


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncClient:
    client = FakeAsyncClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)
    return client


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
