import logging
import os

from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.sync_state import fire_and_forget_sync
from app.routers import auth, articles, feeds, sync, web

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

app.include_router(auth.router)
app.include_router(articles.router)
app.include_router(feeds.router)
app.include_router(sync.router)
app.include_router(web.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
