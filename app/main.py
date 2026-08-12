import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import SESSION_HEADER
from app.db import db_conn_context, init_db
from app.repositories.articles import cleanup_archived_articles
from app.routers import articles, auth, feeds, sync, web
from app.sync_state import fire_and_forget_sync, set_main_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Методы, которые меняют состояние на сервере: для них проверяем Origin
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Парсим один раз при старте, а не на каждом запросе (CSRF-мидлварь).
ALLOWED_ORIGINS = {
    origin.strip() for origin in os.environ.get("FEEDPIPE_ALLOWED_ORIGINS", "").split(",") if origin.strip()
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    set_main_loop(asyncio.get_running_loop())
    scheduler.add_job(
        fire_and_forget_sync,
        IntervalTrigger(minutes=30),
        id="auto_sync",
        replace_existing=True,
    )
    # Раз в сутки вычищаем архив: статусы "archived" старше N дней удаляются.
    scheduler.add_job(
        cleanup_archived_articles,
        CronTrigger(hour=4, minute=0),
        id="archive_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Feedpipe API", lifespan=lifespan)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Защита от CSRF: на изменяющих запросах Origin/Referer должен быть "своим".

    Браузер сам шлёт Origin на POST-запросы, поэтому отсутствие Origin
    (curl, утилиты) трактуем как доверенный клиент вне браузера.
    Запросы с заголовком X-Feedpipe-Session идут из расширения
    (chrome-extension:// origin) — их пропускаем.
    """
    if request.method in UNSAFE_METHODS and not request.headers.get(SESSION_HEADER):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source_netloc = urlparse(origin).netloc if origin else (urlparse(referer).netloc if referer else "")
        if source_netloc:
            host = request.headers.get("host", "")
            allowed = {host, *ALLOWED_ORIGINS} - {""}
            if source_netloc not in allowed:
                return JSONResponse(status_code=403, content={"error": "CSRF: недопустимый Origin"})
    return await call_next(request)


@app.get("/health")
async def health():
    try:
        with db_conn_context() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "error"})


app.include_router(auth.router)
app.include_router(articles.router)
app.include_router(feeds.router)
app.include_router(sync.router)
app.include_router(web.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
