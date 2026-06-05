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
