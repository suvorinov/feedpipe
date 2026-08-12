"""Сквозные сценарии: добавление источника, синхронизация, отложенные, удаление.

HTTP наружу подменяется фикстурой fake_http (см. conftest.py), поэтому
никакие реальные сайты не запрашиваются.
"""

import re

from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    client.post("/api/auth", data={"username": "testuser", "passphrase": "testkey"})


class TestAddSourceFlow:
    def test_empty_feed_renders_empty_state(self, client: TestClient):
        _login(client)
        page = client.get("/")
        assert page.status_code == 200
        assert "ЛЕНТА_ПУСТА" in page.text

    def test_add_feed_discovers_and_parses(self, client: TestClient, fake_http):
        _login(client)
        # сайт без явного RSS: сервер сам найдёт /feed и распарсит ленту
        response = client.post("/api/feeds", data={"url": "https://site.example"})
        assert response.status_code == 200
        assert "Test Feed" in response.text
        assert 'class="feed-item"' in response.text
        # фид добавлен, background-синхронизация подтянула статьи
        page = client.get("/")
        assert "Article One" in page.text
        assert "Article Two" in page.text

    def test_add_duplicate_feed_returns_409(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://site.example/feed"})
        response = client.post("/api/feeds", data={"url": "https://site.example/feed"})
        assert response.status_code == 409

    def test_add_feed_empty_url_400(self, client: TestClient):
        _login(client)
        response = client.post("/api/feeds", data={"url": ""})
        assert response.status_code == 400

    def test_add_feed_invalid_url_400(self, client: TestClient):
        _login(client)
        response = client.post("/api/feeds", data={"url": "not-a-url"})
        assert response.status_code == 400

    def test_delete_feed(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})
        response = client.delete("/api/feeds/1")
        assert response.status_code == 200
        assert "Test Feed" not in client.get("/").text


class TestSyncFlow:
    def test_manual_sync_populates_feed(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})

        response = client.post("/api/sync")
        assert response.status_code == 200
        assert response.json()["status"] == "sync_started"

        page = client.get("/")
        assert "Article One" in page.text

    def test_status_tracks_sync(self, client: TestClient, fake_http):
        _login(client)
        status = client.get("/api/status").json()
        assert status["is_running"] is False


class TestLaterArticles:
    def test_hold_moves_to_later(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})

        assert client.patch("/api/articles/1/hold").status_code == 200

        inbox = client.get("/", headers={"HX-Request": "true"})
        later = client.get("/?view=later", headers={"HX-Request": "true"})
        assert "Article One" in later.text
        assert "Article One" not in inbox.text

    def test_restore_returns_to_inbox(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})

        client.patch("/api/articles/1/hold")
        assert client.patch("/api/articles/1/restore").status_code == 200

        inbox = client.get("/", headers={"HX-Request": "true"})
        assert "Article One" in inbox.text


class TestDeleteArticle:
    def test_delete_archives_article(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})

        assert client.delete("/api/articles/1").status_code == 200

        inbox = client.get("/", headers={"HX-Request": "true"})
        assert "Article One" not in inbox.text
        assert "Article Two" in inbox.text


class TestFeedCounter:
    """Счётчик фидов должен обновляться без перезагрузки страницы (htmx OOB)."""

    @staticmethod
    def _count(response) -> int:
        return int(re.search(r'feeds-count">(\d+)<', response.text).group(1))

    def test_counter_rendered_on_page(self, client: TestClient):
        _login(client)
        assert 'id="feeds-count"' in client.get("/").text

    def test_counter_updates_on_add(self, client: TestClient, fake_http):
        _login(client)
        response = client.post("/api/feeds", data={"url": "https://site.example/feed"})
        assert response.status_code == 200
        assert 'hx-swap-oob="outerHTML:#feeds-count"' in response.text
        assert self._count(response) == 1

    def test_counter_updates_on_delete(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})
        response = client.delete("/api/feeds/1")
        assert response.status_code == 200
        assert "hx-swap-oob" in response.text
        assert self._count(response) == 0

    def test_counter_decrements_on_delete_with_two_feeds(self, client: TestClient, fake_http):
        _login(client)
        client.post("/api/feeds", data={"url": "https://example.com/rss"})
        client.post("/api/feeds", data={"url": "https://site.example/feed"})
        response = client.delete("/api/feeds/1")
        assert response.status_code == 200
        assert self._count(response) == 1
