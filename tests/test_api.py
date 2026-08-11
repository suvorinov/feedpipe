import pytest
from fastapi.testclient import TestClient


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
        response = client.post("/api/auth", data={
            "username": "newuser", "passphrase": "secret123"
        }, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/"
        assert "feedpipe_user" in response.cookies
        assert response.cookies["feedpipe_user"].startswith("newuser.")

    def test_auth_sets_httponly_cookie(self, client: TestClient):
        response = client.post("/api/auth", data={
            "username": "user_secure", "passphrase": "key"
        }, follow_redirects=False)
        cookie_header = response.headers.get("set-cookie", "")
        assert "httponly" in cookie_header.lower()
        assert "samesite" in cookie_header.lower()

    def test_auth_existing_user_valid_key(self, client: TestClient):
        client.post("/api/auth", data={
            "username": "existing", "passphrase": "validkey"
        })
        response = client.post("/api/auth", data={
            "username": "existing", "passphrase": "validkey"
        }, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers.get("hx-redirect") == "/"

    def test_auth_existing_user_wrong_key(self, client: TestClient):
        client.post("/api/auth", data={
            "username": "existing2", "passphrase": "correctkey"
        })
        response = client.post("/api/auth", data={
            "username": "existing2", "passphrase": "wrongkey"
        })
        assert response.status_code == 200
        assert "Invalid key" in response.text

    def test_auth_empty_fields(self, client: TestClient):
        response = client.post("/api/auth", data={
            "username": "", "passphrase": ""
        })
        assert response.status_code == 200
        assert "Заполните все поля" in response.text

    def test_auth_username_case_insensitive(self, client: TestClient):
        client.post("/api/auth", data={
            "username": "CaseUser", "passphrase": "key"
        })
        response = client.post("/api/auth", data={
            "username": "caseuser", "passphrase": "key"
        }, follow_redirects=False)
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
        response = client.get("/?offset=0")
        assert response.status_code == 200


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

    def test_delete_nonexistent_feed(self, client: TestClient):
        auth_headers(client)
        response = client.delete("/api/feeds/999")
        assert response.status_code == 200


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
        response = client.post("/api/auth", data={
            "username": "flowuser", "passphrase": "flowkey"
        }, follow_redirects=False)
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
