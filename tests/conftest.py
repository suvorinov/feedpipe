import os
import socket
import sqlite3
from collections.abc import Generator
from pathlib import Path

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
    def __init__(self, text: str, url: str | None = None):
        self.text = text
        self.url = url or ""
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    """Подменяет httpx.AsyncClient: отдаёт заранее заготовленные ответы по URL."""

    def __init__(self, *args, **kwargs):
        # responses — атрибут экземпляра, а не класса: тесты могут добавлять
        # свои ответы (add_response), не отравляя моки других тестов.
        self.calls = []
        self.responses = {
            "https://site.example": FakeResponse(SITE_HTML),
            "https://site.example/feed": FakeResponse(RSS_XML),
            "https://example.com/rss": FakeResponse(RSS_XML),
        }

    def add_response(self, url: str, text: str, final_url: str | None = None) -> None:
        """Регистрирует ответ; final_url имитирует редирект на другой адрес."""
        self.responses[url] = FakeResponse(text, url=final_url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, *args, **kwargs):
        self.calls.append(url)
        try:
            template = self.responses[url]
        except KeyError:
            raise httpx.ConnectError(f"no mock for {url}") from None
        # Отдаём свежий ответ: url по умолчанию — запрошенный. Можно переопределить
        # (final_url), чтобы сымитировать редирект на другой хост.
        return FakeResponse(template.text, url=template.url or url)


def _fake_getaddrinfo(host, *args, **kwargs):
    """SSRF-проверка резолвит хостнеймы; в тестах DNS подменяем на публичный IP."""
    if host in ("site.example", "example.com"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    raise socket.gaierror(f"no fake DNS for {host}")


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncClient:
    client = FakeAsyncClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    return client


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Счётчик неудачных попыток логина глобален на процесс pytest —
    сбрасываем между тестами, чтобы локдаун из одного теста не ломал остальные."""
    from app.routers import auth as auth_router

    yield
    auth_router._failed_attempts.clear()


def _patch_db_path(tmp_path: Path) -> None:
    import app.db

    app.db.DB_PATH = str(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def test_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    _patch_db_path(tmp_path)
    import app.db

    app.db.init_db()
    with app.db.db_conn_context() as conn:
        yield conn


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
        "INSERT INTO articles (title, link, description, published_at, source_url, status) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Test Article",
            "https://example.com/article1",
            "Description",
            "2024-01-01T00:00:00",
            "https://example.com/rss",
            "inbox",
        ),
    )
    test_db.execute(
        "INSERT INTO articles (title, link, description, published_at, source_url, status) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Later Article",
            "https://example.com/article2",
            "Later desc",
            "2024-01-02T00:00:00",
            "https://example.com/rss",
            "later",
        ),
    )
    test_db.commit()
    return test_db


@pytest.fixture
def auth_client(client: TestClient) -> Generator[TestClient, None, None]:
    client.post("/api/auth", data={"username": "testuser", "passphrase": "testkey"})
    yield client
