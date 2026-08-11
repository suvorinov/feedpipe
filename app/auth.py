import hashlib
import hmac
import os

from fastapi import HTTPException, Request
from passlib.context import CryptContext

from app.db import DATA_DIR

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "feedpipe_user"
SECRET_FILE = os.path.join(DATA_DIR, "secret.key")


def _load_secret() -> bytes:
    """Возвращает секрет для подписи cookie.

    Приоритет: переменная окружения FEEDPIPE_SECRET -> файл в DATA_DIR.
    Файл создаётся один раз, чтобы сессии переживали перезапуск приложения.
    """
    secret = os.environ.get("FEEDPIPE_SECRET")
    if secret:
        return secret.encode()

    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            return f.read()

    secret = os.urandom(32)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SECRET_FILE, "wb") as f:
        f.write(secret)
    return secret


def _sign(value: str) -> str:
    digest = hmac.new(_load_secret(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def build_auth_cookie_value(username: str) -> str:
    """Подписывает имя пользователя: 'username.<hmac>'."""
    return _sign(username)


def verify_auth_cookie(value: str | None) -> str | None:
    """Возвращает username, если подпись валидна, иначе None."""
    if not value or "." not in value:
        return None

    username, _, signature = value.rpartition(".")
    expected = hmac.new(_load_secret(), username.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return username


def hash_passphrase(passphrase: str) -> str:
    return pwd_context.hash(passphrase)


def verify_passphrase(passphrase: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(passphrase, hashed)
    except Exception:
        return False


def get_current_user(request: Request) -> str:
    user = verify_auth_cookie(request.cookies.get(COOKIE_NAME))
    if not user:
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user
