from app.auth import hash_passphrase, verify_passphrase


class TestHashPassphrase:
    def test_hash_returns_string(self):
        hashed = hash_passphrase("mykey")
        assert isinstance(hashed, str)
        assert len(hashed) > 20

    def test_hash_differs_each_call(self):
        h1 = hash_passphrase("samekey")
        h2 = hash_passphrase("samekey")
        assert h1 != h2


class TestVerifyPassphrase:
    def test_verify_correct(self):
        hashed = hash_passphrase("mykey")
        assert verify_passphrase("mykey", hashed) is True

    def test_verify_incorrect(self):
        hashed = hash_passphrase("mykey")
        assert verify_passphrase("wrongkey", hashed) is False

    def test_verify_empty(self):
        hashed = hash_passphrase("mykey")
        assert verify_passphrase("", hashed) is False

    def test_verify_invalid_hash(self):
        assert verify_passphrase("key", "not-a-valid-hash") is False

    def test_verify_empty_hash(self):
        assert verify_passphrase("key", "") is False


class TestRateLimit:
    def test_lockout_after_many_failures(self, client):
        client.post("/api/auth", data={"username": "rluser", "passphrase": "correctkey"})
        for _ in range(5):
            client.post("/api/auth", data={"username": "rluser", "passphrase": "wrongkey"})
        response = client.post("/api/auth", data={"username": "rluser", "passphrase": "correctkey"})
        assert "Слишком много попыток" in response.text

    def test_correct_key_below_threshold(self, client):
        client.post("/api/auth", data={"username": "rluser2", "passphrase": "correctkey"})
        for _ in range(4):
            client.post("/api/auth", data={"username": "rluser2", "passphrase": "wrongkey"})
        response = client.post(
            "/api/auth", data={"username": "rluser2", "passphrase": "correctkey"}, follow_redirects=False
        )
        assert response.status_code == 303
