import logging
import re
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
import sqlite3

from app.auth import get_current_user
from app.db import get_db
from app.repositories.feeds import FeedRepository
from app.template_filters import templates
from app.sync_state import run_parser_async

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/feeds")
async def add_feed(
    request: Request,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    form = await request.form()
    url = form.get("url")

    if not url:
        return JSONResponse(status_code=400, content={"error": "Нет URL!"})

    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        return JSONResponse(status_code=400, content={"error": "Неверный URL!"})
    if parsed_url.scheme not in ("http", "https"):
        return JSONResponse(status_code=400, content={"error": "Поддерживаются только HTTP и HTTPS!"})

    if not url.endswith(".xml") and not url.endswith("/rss") and "feed" not in url:
        try:
            headers = {"User-Agent": "Feedpipe/1.0"}
            async with httpx.AsyncClient(headers=headers) as client:
                resp = await client.get(url, timeout=5.0, follow_redirects=True)
                match = re.search(
                    r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"',
                    resp.text, re.IGNORECASE,
                )
                if match:
                    found_rss = match.group(1)
                    if found_rss.startswith("/"):
                        found_rss = urljoin(url, found_rss)
                    url = found_rss
        except Exception:
            pass

    headers = {"User-Agent": "Feedpipe/1.0"}
    try:
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(url, timeout=10.0, follow_redirects=True)
            parsed = feedparser.parse(resp.text)

            if parsed.bozo and not parsed.entries:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Фид повреждён или пуст: {str(parsed.bozo_exception)[:100]}!"}
                )

            title = parsed.feed.get("title", url)
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=400,
            content={"error": "Таймаут при получении фида!"}
        )
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Ошибка HTTP: {e.response.status_code}!"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Не удалось распознать фид: {str(e)[:100]}!"}
        )

    repo = FeedRepository(db)
    try:
        repo.add(url, title)
    except sqlite3.IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"error": "Уже подписан!"}
        )

    background_tasks.add_task(run_parser_async)

    feeds = repo.get_all()
    return templates.TemplateResponse(
        "feeds_list.html",
        {"request": request, "feeds": feeds}
    )


@router.delete("/api/feeds/{feed_id}")
def delete_feed(feed_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    FeedRepository(db).delete(feed_id)
    return HTMLResponse(content="", status_code=200)
