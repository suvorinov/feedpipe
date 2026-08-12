import socket

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def auth_headers(client: TestClient) -> None:
    client.post("/api/auth", data={"username": "testuser", "passphrase": "testkey"})


class TestLoginPage:
    def test_get_login_returns_html(self, client: TestClient):
        response = client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "AUTH" in response.text

    def test_login_page_with_error(self, client: TestClient):
        response = client.get("/login?error=Invalid+key")
        assert response.status_code == 200
        assert "Invalid" in response.text

    def test_login_redirects_when_authenticated(self, client: TestClient):
        auth_headers(client)
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("location") == "/"


class TestAuth:
    def test_auth_creates_user_and_returns_redirect(self, client: TestClient):
        response = client.post(
            "/api/auth", data={"username": "newuser", "passphrase": "secret123"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/"
        assert "feedpipe_user" in response.cookies
        assert response.cookies["feedpipe_user"].startswith("newuser.")

    def test_auth_sets_httponly_cookie(self, client: TestClient):
        response = client.post(
            "/api/auth", data={"username": "user_secure", "passphrase": "key"}, follow_redirects=False
        )
        cookie_header = response.headers.get("set-cookie", "")
        assert "httponly" in cookie_header.lower()
        assert "samesite" in cookie_header.lower()

    def test_auth_existing_user_valid_key(self, client: TestClient):
        client.post("/api/auth", data={"username": "existing", "passphrase": "validkey"})
        response = client.post(
            "/api/auth", data={"username": "existing", "passphrase": "validkey"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/"

    def test_auth_existing_user_wrong_key(self, client: TestClient):
        client.post("/api/auth", data={"username": "existing2", "passphrase": "correctkey"})
        response = client.post("/api/auth", data={"username": "existing2", "passphrase": "wrongkey"})
        assert response.status_code == 200
        assert "Invalid key" in response.text

    def test_auth_empty_fields(self, client: TestClient):
        response = client.post("/api/auth", data={"username": "", "passphrase": ""})
        assert response.status_code == 200
        assert "Заполните все поля" in response.text

    def test_auth_username_case_insensitive(self, client: TestClient):
        client.post("/api/auth", data={"username": "CaseUser", "passphrase": "key"})
        response = client.post("/api/auth", data={"username": "caseuser", "passphrase": "key"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/"


class TestAuthSecurity:
    def test_forged_cookie_rejected(self, client: TestClient):
        client.cookies.set("feedpipe_user", "admin")
        response = client.get("/api/status")
        assert response.status_code == 401

    def test_malformed_cookie_rejected(self, client: TestClient):
        client.cookies.set("feedpipe_user", "admin.no-valid-signature")
        response = client.get("/api/status")
        assert response.status_code == 401

    def test_forged_cookie_shows_login_page(self, client: TestClient):
        client.cookies.set("feedpipe_user", "admin")
        response = client.get("/")
        assert "AUTH" in response.text

    def test_valid_cookie_accepted(self, client: TestClient):
        auth_headers(client)
        response = client.get("/api/status")
        assert response.status_code == 200


class TestLogout:
    def test_logout_clears_cookie(self, client: TestClient):
        client.cookies.set("feedpipe_user", "testuser")
        response = client.post("/api/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/login"

    def test_logout_without_login(self, client: TestClient):
        response = client.post("/api/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/login"


class TestMainPage:
    def test_root_redirects_to_login_when_unauthenticated(self, client: TestClient):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 200
        assert "AUTH" in response.text

    def test_root_returns_html_when_authenticated(self, client: TestClient):
        auth_headers(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "feedpipe" in response.text.lower()

    def test_root_with_lang_param(self, client: TestClient):
        auth_headers(client)
        response = client.get("/?lang=en")
        assert response.status_code == 200
        assert "feedpipe_lang" in response.cookies
        assert response.cookies["feedpipe_lang"] == "en"

    def test_root_htmx_redirects_when_unauthenticated(self, client: TestClient):
        response = client.get("/", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert "AUTH" in response.text

    def test_root_with_invalid_view(self, client: TestClient):
        auth_headers(client)
        response = client.get("/?view=unknown")
        assert response.status_code == 200

    def test_root_pagination(self, client: TestClient):
        auth_headers(client)
        response = client.get("/?before=1")
        assert response.status_code == 200

    def test_root_with_before_and_has_more(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "lazy-trigger" not in response.text  # статей мало: дальше нечего грузить


class TestUnauthenticatedApi:
    def test_status_needs_auth(self, client: TestClient):
        response = client.get("/api/status")
        assert response.status_code == 401

    def test_sync_needs_auth(self, client: TestClient):
        response = client.post("/api/sync")
        assert response.status_code == 401

    def test_delete_feed_needs_auth(self, client: TestClient):
        response = client.delete("/api/feeds/1")
        assert response.status_code == 401

    def test_delete_article_needs_auth(self, client: TestClient):
        response = client.delete("/api/articles/1")
        assert response.status_code == 401

    def test_htmx_api_returns_redirect_header(self, client: TestClient):
        response = client.get("/api/status", headers={"HX-Request": "true"})
        assert response.status_code == 401
        assert response.headers.get("HX-Redirect") == "/login"


class TestArticleStatus:
    def test_update_to_later(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch(
            "/api/articles/1/status",
            params={"status": "later"},
        )
        assert response.status_code == 200

    def test_update_to_archived(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch(
            "/api/articles/1/status",
            params={"status": "archived"},
        )
        assert response.status_code == 200

    def test_update_invalid_status(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch(
            "/api/articles/1/status",
            params={"status": "invalid"},
        )
        assert response.status_code == 400

    def test_update_nonexistent_article(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch(
            "/api/articles/999/status",
            params={"status": "archived"},
        )
        assert response.status_code == 404

    def test_hold_article(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch("/api/articles/1/hold")
        assert response.status_code == 200

    def test_restore_article(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.patch("/api/articles/2/restore")
        assert response.status_code == 200

    def test_delete_article(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.delete("/api/articles/1")
        assert response.status_code == 200


class TestStatus:
    def test_get_status(self, client: TestClient):
        auth_headers(client)
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "is_running" in data
        assert "last_sync" in data
        assert "last_count" in data
        assert data["is_running"] is False


class TestSync:
    def test_trigger_sync(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.post("/api/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sync_started"


class TestFeeds:
    def test_delete_feed(self, client: TestClient, seeded_db):
        auth_headers(client)
        response = client.delete("/api/feeds/1")
        assert response.status_code == 200

    def test_delete_feed_cascades_articles(self, client: TestClient, seeded_db):
        auth_headers(client)
        feed_url = seeded_db.execute("SELECT url FROM feeds WHERE id = 1").fetchone()[0]
        assert client.delete("/api/feeds/1").status_code == 200
        remaining = seeded_db.execute("SELECT COUNT(*) FROM articles WHERE source_url = ?", (feed_url,)).fetchone()[0]
        assert remaining == 0

    def test_delete_nonexistent_feed(self, client: TestClient):
        auth_headers(client)
        response = client.delete("/api/feeds/999")
        assert response.status_code == 200


class TestCsrf:
    def test_post_with_foreign_origin_rejected(self, client: TestClient):
        response = client.post(
            "/api/feeds",
            data={"url": "https://evil.example"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403

    def test_patch_with_foreign_origin_rejected(self, client: TestClient):
        response = client.patch(
            "/api/articles/1/status",
            params={"status": "later"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403

    def test_post_same_origin_allowed(self, client: TestClient, fake_http):
        auth_headers(client)
        response = client.post(
            "/api/feeds",
            data={"url": "https://example.com/rss"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200

    def test_post_without_origin_allowed(self, client: TestClient, fake_http):
        """curl/утилиты не шлют Origin — трактуем как доверенный клиент."""
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "https://example.com/rss"})
        assert response.status_code == 200

    def test_session_header_skips_csrf(self, client: TestClient, fake_http):
        """Расширение шлёт chrome-extension:// Origin — его пропускает сессионный заголовок."""
        client.post("/api/auth", data={"username": "extuser", "passphrase": "extkey"})
        session = client.cookies.get("feedpipe_user")
        client.cookies.clear()
        response = client.post(
            "/api/feeds",
            data={"url": "https://example.com/rss"},
            headers={
                "X-Feedpipe-Session": session,
                "Origin": "chrome-extension://abcd1234",
            },
        )
        assert response.status_code == 200


class TestSessionHeaderAuth:
    def test_api_accepts_session_header_without_cookie(self, client: TestClient):
        client.post("/api/auth", data={"username": "hdruser", "passphrase": "hdrkey"})
        session = client.cookies.get("feedpipe_user")
        client.cookies.clear()
        response = client.get("/api/status", headers={"X-Feedpipe-Session": session})
        assert response.status_code == 200

    def test_api_rejects_invalid_session_header(self, client: TestClient):
        response = client.get("/api/status", headers={"X-Feedpipe-Session": "admin.bad"})
        assert response.status_code == 401


class TestHealth:
    def test_health_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"


class TestManifest:
    def test_manifest_returns_json(self, client: TestClient):
        response = client.get("/manifest.json")
        assert response.status_code == 200


class TestAuthFlow:
    def test_full_login_logout_flow(self, client: TestClient):
        # 1. Not logged in -> see login page at /
        response = client.get("/", follow_redirects=False)
        assert "AUTH" in response.text

        # 2. Login (without following redirect so we can read the cookie)
        response = client.post(
            "/api/auth", data={"username": "flowuser", "passphrase": "flowkey"}, follow_redirects=False
        )
        assert response.status_code == 303
        cookie = response.cookies.get("feedpipe_user")
        assert cookie is not None
        assert cookie.startswith("flowuser.")

        # 3. Now logged in -> see main page
        client.cookies.set("feedpipe_user", cookie)
        response = client.get("/")
        assert response.status_code == 200
        assert "feedpipe" in response.text.lower()

        # 4. Visit login page -> redirect to /
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("location") == "/"

        # 5. Logout
        response = client.post("/api/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/login"

        # 6. API requires auth after logout
        client.cookies.clear()
        response = client.get("/api/status")
        assert response.status_code == 401


class TestAddFeed:
    def test_add_feed(self, client: TestClient, fake_http):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "https://example.com/rss"})
        assert response.status_code == 200

    def test_add_feed_empty_url(self, client: TestClient):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": ""})
        assert response.status_code == 400

    def test_add_feed_invalid_url(self, client: TestClient):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "not-a-url"})
        assert response.status_code == 400


class TestSsrf:
    """Сервер не должен ходить на внутренние адреса (SSRF-защита)."""

    def test_loopback_ip_rejected(self, client: TestClient, fake_http):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "http://127.0.0.1:8000/health"})
        assert response.status_code == 400

    def test_private_ip_rejected(self, client: TestClient, fake_http):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "http://192.168.1.1/rss"})
        assert response.status_code == 400

    def test_linklocal_ip_rejected(self, client: TestClient, fake_http):
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "http://169.254.169.254/latest/meta-data"})
        assert response.status_code == 400

    def test_hostname_resolving_to_private_rejected(self, client: TestClient, fake_http, monkeypatch):
        def private_dns(host, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", private_dns)
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "http://internal.example/feed"})
        assert response.status_code == 400

    def test_redirect_to_internal_rejected(self, client: TestClient, fake_http):
        # Стартовый URL публичный, но сервер отвечает редиректом на 127.0.0.1.
        fake_http.add_response("https://example.com/rss", "not-xml", final_url="http://127.0.0.1:8000/health")
        auth_headers(client)
        response = client.post("/api/feeds", data={"url": "https://example.com/rss"})
        assert response.status_code == 400


class TestWebSocket:
    def test_ws_rejects_unauthenticated(self, client: TestClient):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_text()

    def test_ws_accepts_authenticated(self, client: TestClient):
        auth_headers(client)
        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            assert data["type"] == "status"
            assert "is_running" in data
