import asyncio
import logging
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import (
    COOKIE_NAME,
    SECURE_COOKIE,
    build_auth_cookie_value,
    hash_passphrase,
    verify_auth_cookie,
    verify_passphrase,
)
from app.db import get_db
from app.repositories.users import UserRepository
from app.template_filters import templates

logger = logging.getLogger(__name__)
router = APIRouter()

# Против брутфорса: считаем неудачные попытки ввода ключа в окне времени.
# Храним в памяти — для односерверного приложения этого достаточно.
MAX_FAILED_ATTEMPTS = 5
FAIL_WINDOW = timedelta(minutes=15)
_failed_attempts: dict[str, list[datetime]] = defaultdict(list)
_attempts_lock = threading.Lock()


def _too_many_attempts(ip: str) -> bool:
    now = datetime.now()
    with _attempts_lock:
        recent = [t for t in _failed_attempts[ip] if now - t < FAIL_WINDOW]
        _failed_attempts[ip] = recent
        return len(recent) >= MAX_FAILED_ATTEMPTS


def _record_failure(ip: str) -> None:
    with _attempts_lock:
        _failed_attempts[ip].append(datetime.now())


def _clear_attempts(ip: str) -> None:
    with _attempts_lock:
        _failed_attempts.pop(ip, None)


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    error: str | None = None,
    feedpipe_user: str | None = Cookie(None),
) -> HTMLResponse:
    if feedpipe_user and verify_auth_cookie(feedpipe_user):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/api/auth")
async def handle_auth(request: Request, db: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    form = await request.form()
    username = form.get("username", "").strip().lower()
    passphrase = form.get("passphrase", "").strip()

    if not username or not passphrase:
        return templates.TemplateResponse(request, "login.html", {"error": "Заполните все поля"})

    # За NPM приходит IP прокси — для персонального сервера это и есть наш клиент.
    client_ip = request.client.host if request.client else "unknown"
    if _too_many_attempts(client_ip):
        return templates.TemplateResponse(request, "login.html", {"error": "Слишком много попыток. Подождите 15 минут"})

    repo = UserRepository(db)
    user = repo.find_by_username(username)

    if user:
        if not verify_passphrase(passphrase, user["secret_hash"]):
            _record_failure(client_ip)
            return templates.TemplateResponse(request, "login.html", {"error": "Invalid key"})
    else:
        hashed = hash_passphrase(passphrase)
        await asyncio.to_thread(repo.create, username, hashed)

    _clear_attempts(client_ip)
    response = RedirectResponse(url="/", status_code=303)
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key=COOKIE_NAME,
        value=build_auth_cookie_value(username),
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIE,
    )
    return response


@router.post("/api/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.headers["HX-Redirect"] = "/login"
    response.delete_cookie(COOKIE_NAME)
    return response
