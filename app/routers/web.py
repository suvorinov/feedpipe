import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from app.auth import COOKIE_NAME, SESSION_HEADER, verify_auth_cookie
from app.db import get_db
from app.repositories.articles import ArticleRepository
from app.repositories.feeds import FeedRepository
from app.sync_state import SYNC_STATUS
from app.template_filters import templates
from app.ws_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE.parent / "manifest.json"


@router.get("/manifest.json", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(str(MANIFEST_PATH))


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "status",
                "is_running": SYNC_STATUS["is_running"],
                "last_sync": SYNC_STATUS["last_sync"],
                "count": SYNC_STATUS["last_count"],
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    lang: str | None = None,
    feedpipe_lang: str | None = Cookie(None),
    view: str = "inbox",
    before: int | None = None,
) -> HTMLResponse:
    user = verify_auth_cookie(request.cookies.get(COOKIE_NAME))
    if not user:
        user = verify_auth_cookie(request.headers.get(SESSION_HEADER))
    is_auth = bool(user)
    current_lang = lang or feedpipe_lang or "ru"

    article_repo = ArticleRepository(db)
    feed_repo = FeedRepository(db)

    inbox_count = article_repo.get_inbox_count()
    later_count = article_repo.get_later_count()

    status = "later" if view == "later" else "inbox"
    articles, has_more = article_repo.get_by_status(status, before_id=before)
    feeds = feed_repo.get_all()

    if not is_auth:
        response = templates.TemplateResponse(request, "login.html", {"error": None})
        if lang:
            response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)
        return response

    context = {
        "articles": articles,
        "total_count": inbox_count,
        "later_count": later_count,
        "feeds": feeds,
        "lang": current_lang,
        "view": view,
        "has_more": has_more,
        "next_cursor": articles[-1]["id"] if has_more and articles else None,
        "user": user,
    }

    is_htmx_request = request.headers.get("HX-Request") == "true"

    if is_htmx_request:
        response = templates.TemplateResponse(request, "articles_list.html", context)
    else:
        response = templates.TemplateResponse(request, "index.html", context)

    if lang:
        response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)

    return response
