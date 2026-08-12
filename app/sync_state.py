import asyncio
import logging
import threading
from datetime import datetime

from app.db import get_db
from app.parser import main as parser_main
from app.repositories.articles import ArticleRepository
from app.ws_manager import manager

logger = logging.getLogger(__name__)

SYNC_STATUS = {
    "is_running": False,
    "last_sync": None,
    "last_count": 0,
}

# Event loop основного приложения: задаётся в lifespan.
# Нужен, чтобы синхронизация из потока APScheduler вещала в WebSocket
# правильного loop, а не создавала чужой.
_main_loop: asyncio.AbstractEventLoop | None = None

# Защищает проверку/установку флага is_running от гонки между потоками.
_sync_lock = threading.Lock()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


async def run_parser_async() -> None:
    with _sync_lock:
        if SYNC_STATUS["is_running"]:
            return
        SYNC_STATUS["is_running"] = True

    await manager.broadcast({"type": "sync_start"})

    try:
        await parser_main()

        conn = get_db()
        try:
            new_count = ArticleRepository(conn).get_inbox_count()
        finally:
            conn.close()

        SYNC_STATUS["last_sync"] = datetime.now().isoformat()
        SYNC_STATUS["last_count"] = new_count

        await manager.broadcast(
            {
                "type": "sync_complete",
                "count": new_count,
                "timestamp": SYNC_STATUS["last_sync"],
            }
        )
    except Exception as e:
        logger.error(f"Parser error: {e}")
        await manager.broadcast({"type": "sync_error", "error": str(e)})
    finally:
        SYNC_STATUS["is_running"] = False


def fire_and_forget_sync() -> None:
    """Запускает синхронизацию в фоне, не дожидаясь результата.

    - Из основного loop (веб-запрос, BackgroundTasks) — через create_task.
    - Из чужого потока (APScheduler) — через run_coroutine_threadsafe в главный loop.
    - Вне приложения (python -m app.parser) — через asyncio.run.
    """
    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(run_parser_async(), _main_loop)
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(run_parser_async())
    else:
        asyncio.run(run_parser_async())
