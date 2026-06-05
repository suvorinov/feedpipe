import asyncio
import logging
import re
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from .db import get_db, init_db
from .auth import hash_passphrase, verify_passphrase
from .parser import main as parser_main


def get_current_user(request: Request) -> str:
    user = request.cookies.get("feedpipe_user")
    if not user:
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        fire_and_forget_sync,
        IntervalTrigger(minutes=30),
        id="auto_sync",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()

app = FastAPI(title="Feedpipe API", lifespan=lifespan)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/manifest.json", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

def format_date(value: datetime | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    now = datetime.now()
    diff = now - value
    if diff.days == 0:
        hours = diff.seconds // 3600
        mins = (diff.seconds % 3600) // 60
        if hours > 0:
            return f"{hours}ч назад"
        elif mins > 0:
            return f"{mins}м назад"
        else:
            return "только что"
    elif diff.days == 1:
        return "вчера"
    elif diff.days < 7:
        return f"{diff.days}д назад"
    else:
        return value.strftime("%d %b")

class CustomJinja2Templates(Jinja2Templates):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.env.filters["format_date"] = format_date

templates = CustomJinja2Templates(directory="templates", cache_size=0)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SYNC_STATUS = {
    "is_running": False,
    "last_sync": None,
    "last_count": 0,
}

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

async def run_parser_async() -> None:
    global SYNC_STATUS
    if SYNC_STATUS["is_running"]:
        return

    SYNC_STATUS["is_running"] = True
    await manager.broadcast({"type": "sync_start"})

    try:
        await parser_main()

        conn = get_db()
        cursor = conn.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'")
        new_count = cursor.fetchone()[0]
        conn.close()

        SYNC_STATUS["last_sync"] = datetime.now().isoformat()
        SYNC_STATUS["last_count"] = new_count

        await manager.broadcast({
            "type": "sync_complete",
            "count": new_count,
            "timestamp": SYNC_STATUS["last_sync"],
        })
    except Exception as e:
        logger.error(f"Parser error: {e}")
        await manager.broadcast({"type": "sync_error", "error": str(e)})
    finally:
        SYNC_STATUS["is_running"] = False

def fire_and_forget_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(run_parser_async(), loop)
    elif loop:
        asyncio.ensure_future(run_parser_async(), loop=loop)
    else:
        asyncio.run(run_parser_async())



@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({
            "type": "status",
            "is_running": SYNC_STATUS["is_running"],
            "last_sync": SYNC_STATUS["last_sync"],
            "count": SYNC_STATUS["last_count"],
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    lang: Optional[str] = None,
    feedpipe_lang: Optional[str] = Cookie(None),
    view: str = "inbox",
    offset: int = 0,
    feedpipe_user: Optional[str] = Cookie(None),
) -> HTMLResponse:
    user = feedpipe_user
    is_auth = bool(user)
    current_lang = lang or feedpipe_lang or "ru"
    
    inbox_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'").fetchone()[0]
    later_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='later'").fetchone()[0]
    
    # Изменяем SQL запрос: пропускаем 'offset' записей и берем 50
    if view == "later":
        cursor = db.execute(
            "SELECT id, title, link, description, source_url, published_at FROM articles WHERE status='later' ORDER BY id DESC LIMIT 50 OFFSET ?", 
            (offset,)
        )
    else:
        cursor = db.execute(
            "SELECT id, title, link, description, source_url, published_at FROM articles WHERE status='inbox' ORDER BY id DESC LIMIT 50 OFFSET ?", 
            (offset,)
        )
        
    articles = [dict(row) for row in cursor.fetchall()]
    feeds = [dict(row) for row in db.execute("SELECT id, url, title FROM feeds ORDER BY id DESC").fetchall()]

    if not is_auth:
        response = templates.TemplateResponse("login.html", {"request": request, "error": None})
        if lang:
            response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)
        return response

    context = {
        "request": request,
        "articles": articles,
        "total_count": inbox_count,
        "later_count": later_count,
        "feeds": feeds,
        "lang": current_lang,
        "view": view,
        "view_count": later_count if view == "later" else inbox_count,
        "next_offset": offset + 50,
        "user": user,
    }
    
    is_htmx_request = request.headers.get("HX-Request") == "true"

    if is_htmx_request:
        response = templates.TemplateResponse("articles_list.html", context)
    else:
        response = templates.TemplateResponse("index.html", context)

    if lang:
        response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)

    return response

async def _update_article_status(
    article_id: int,
    status: str,
    db: sqlite3.Connection,
) -> HTMLResponse:
    valid_statuses = ("inbox", "later", "archived")
    if status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    cursor = db.execute(
        "UPDATE articles SET status = ? WHERE id = ? AND status != ?",
        (status, article_id, status)
    )
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(404, "Article not found or already has this status")

    inbox_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'").fetchone()[0]
    later_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='later'").fetchone()[0]

    await manager.broadcast({
        "type": "counter_update",
        "inbox_count": inbox_count,
        "later_count": later_count
    })

    return HTMLResponse(content="", status_code=200)


@app.patch("/api/articles/{article_id}/status")
async def update_article_status(
    article_id: int,
    status: str,
    user: str = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    return await _update_article_status(article_id, status, db)


@app.delete("/api/articles/{article_id}")
async def delete_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "archived", db)

@app.patch("/api/articles/{article_id}/hold")
async def hold_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "later", db)

@app.patch("/api/articles/{article_id}/restore")
async def restore_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "inbox", db)

@app.post("/api/feeds")
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

    # --- Валидация URL ---
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        return JSONResponse(status_code=400, content={"error": "Неверный URL!"})
    if parsed_url.scheme not in ("http", "https"):
        return JSONResponse(status_code=400, content={"error": "Поддерживаются только HTTP и HTTPS!"})

    # --- Авто-дискавери RSS ---
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

    # --- Получение заголовка фида и валидация ---
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

    # --- Сохранение в БД ---
    try:
        db.execute("INSERT INTO feeds (url, title) VALUES (?, ?)", (url, title))
        db.commit()
    except sqlite3.IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"error": "Уже подписан!"}
        )

    background_tasks.add_task(run_parser_async)

    # --- МАГИЯ: Просим Jinja2 отрендерить ТОЛЬКО список фидов ---
    feeds = [dict(row) for row in db.execute("SELECT id, url, title FROM feeds ORDER BY id DESC").fetchall()]
    return templates.TemplateResponse(
        "feeds_list.html", 
        {"request": request, "feeds": feeds}
    )

@app.delete("/api/feeds/{feed_id}")
def delete_feed(feed_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    db.commit()
    return HTMLResponse(content="", status_code=200)

@app.post("/api/sync")
async def trigger_sync(user: str = Depends(get_current_user)) -> dict:
    asyncio.create_task(run_parser_async())
    return {"status": "sync_started", "is_running": SYNC_STATUS["is_running"]}

@app.get("/api/status")
def get_status(user: str = Depends(get_current_user)) -> dict:
    return SYNC_STATUS

@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    error: Optional[str] = None,
    feedpipe_user: Optional[str] = Cookie(None),
) -> HTMLResponse:
    if feedpipe_user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/api/auth")
async def handle_auth(request: Request, db: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    form = await request.form()
    username = form.get("username", "").strip().lower()
    passphrase = form.get("passphrase", "").strip()

    if not username or not passphrase:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Заполните все поля"})

    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    if user:
        if not verify_passphrase(passphrase, user['secret_hash']):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid key"})
    else:
        hashed = hash_passphrase(passphrase)
        db.execute("INSERT INTO users (username, secret_hash) VALUES (?, ?)", (username, hashed))
        db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key="feedpipe_user", value=username, max_age=30*24*3600,
        httponly=True, samesite="lax",
    )
    return response

@app.post("/api/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.headers["HX-Redirect"] = "/login"
    response.delete_cookie("feedpipe_user")
    return response

