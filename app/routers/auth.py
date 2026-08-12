import asyncio
import logging
import sqlite3

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import COOKIE_NAME, build_auth_cookie_value, hash_passphrase, verify_auth_cookie, verify_passphrase
from app.db import get_db
from app.repositories.users import UserRepository
from app.template_filters import templates

logger = logging.getLogger(__name__)
router = APIRouter()


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

    repo = UserRepository(db)
    user = repo.find_by_username(username)

    if user:
        if not verify_passphrase(passphrase, user["secret_hash"]):
            return templates.TemplateResponse(request, "login.html", {"error": "Invalid key"})
    else:
        hashed = hash_passphrase(passphrase)
        await asyncio.to_thread(repo.create, username, hashed)

    response = RedirectResponse(url="/", status_code=303)
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key=COOKIE_NAME,
        value=build_auth_cookie_value(username),
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.headers["HX-Redirect"] = "/login"
    response.delete_cookie(COOKIE_NAME)
    return response
