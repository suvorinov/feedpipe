import asyncio
import html
import sqlite3
import tempfile
from datetime import datetime

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
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

# В app/main.py должно быть так:
from .db import get_db, init_db
from .parser import main as parser_main

app = FastAPI(title="Feedpipe API")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

def format_date(value):
    if not value:
        return ""
    from datetime import datetime
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except:
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

init_db()

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

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

async def run_parser_async():
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
        print(f"Parser error: {e}")
        await manager.broadcast({"type": "sync_error", "error": str(e)})
    finally:
        SYNC_STATUS["is_running"] = False

def fire_and_forget_sync():
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

scheduler = BackgroundScheduler()
scheduler.add_job(
    fire_and_forget_sync,
    IntervalTrigger(minutes=30),
    id="auto_sync",
    replace_existing=True,
)
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

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
    lang: str = None,
    feedpipe_lang: str = Cookie(None),
    view: str = "inbox",
    offset: int = 0 
):
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

    context = {
        "request": request, 
        "articles": articles,
        "total_count": inbox_count,
        "later_count": later_count,
        "feeds": feeds,
        "lang": current_lang,
        "view": view,
        "next_offset": offset + 50  # <-- ДОБАВИЛИ ЭТО
    }
    
    is_htmx_request = request.headers.get("HX-Request") == "true"

    if is_htmx_request:
        # Если это HTMX — отдаем ТОЛЬКО список статей и триггер
        return templates.TemplateResponse("articles_list.html", context)
    else:
        # Если это обычный заход в браузере — отдаем полноценную страницу
        return templates.TemplateResponse("index.html", context)
    
    # Куки ставим в любом случае (FastAPI умеет ставить куки даже на HTMLResponse)
    if lang:
        response = templates.TemplateResponse("articles_list.html" if is_htmx_request else "index.html", context)
        response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)
        return response

@app.delete("/api/articles/{article_id}")
def purge_article(article_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("UPDATE articles SET status='archived' WHERE id = ?", (article_id,))
    db.commit()
    if cursor.rowcount == 0: raise HTTPException(404)
    return HTMLResponse(content="", status_code=200)

@app.patch("/api/articles/{article_id}/hold")
def hold_article(article_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("UPDATE articles SET status='later' WHERE id = ? AND status='inbox'", (article_id,))
    db.commit()
    if cursor.rowcount == 0: raise HTTPException(404)
    return HTMLResponse(content="", status_code=200)

@app.post("/api/feeds")
async def add_feed(
    request: Request,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    form = await request.form()
    url = form.get("url")

    if not url:
        raise HTTPException(400, "Нет URL")

    # --- Валидация URL ---
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        raise HTTPException(400, "Неверный URL")
    if parsed_url.scheme not in ("http", "https"):
        raise HTTPException(400, "Поддерживаются только HTTP и HTTPS")

    # --- Авто-дискавери RSS ---
    if not url.endswith(".xml") and not url.endswith("/rss") and "feed" not in url:
        try:
            headers = {"User-Agent": "Feedpipe/1.0"}
            async with httpx.AsyncClient(headers=headers) as client:
                resp = await client.get(url, timeout=5.0, follow_redirects=True)
                import re
                match = re.search(
                    r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"',
                    resp.text, re.IGNORECASE,
                )
                if match:
                    found_rss = match.group(1)
                    if found_rss.startswith("/"):
                        from urllib.parse import urljoin
                        found_rss = urljoin(url, found_rss)
                    url = found_rss
        except Exception:
            pass

    # --- Получение заголовка фида ---
    try:
        import feedparser
        headers = {"User-Agent": "Feedpipe/1.0"}
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(url, timeout=5.0, follow_redirects=True)
            parsed = feedparser.parse(resp.text)
            title = parsed.feed.get("title", url)
    except:
        title = url

    # --- Сохранение в БД ---
    try:
        db.execute("INSERT INTO feeds (url, title) VALUES (?, ?)", (url, title))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Уже подписан")

    # Запускаем парсер в фоне
    background_tasks.add_task(run_parser_async)

    # --- МАГИЯ: Просим Jinja2 отрендерить ТОЛЬКО список фидов ---
    feeds = [dict(row) for row in db.execute("SELECT id, url, title FROM feeds ORDER BY id DESC").fetchall()]
    return templates.TemplateResponse(
        "feeds_list.html", 
        {"request": request, "feeds": feeds}
    )

@app.delete("/api/feeds/{feed_id}")
def delete_feed(feed_id: int, db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    db.commit()
    return HTMLResponse(content="", status_code=200)

@app.post("/api/sync")
async def trigger_sync():
    asyncio.create_task(run_parser_async())
    return {"status": "sync_started", "is_running": SYNC_STATUS["is_running"]}

@app.get("/api/status")
def get_status():
    return SYNC_STATUS

