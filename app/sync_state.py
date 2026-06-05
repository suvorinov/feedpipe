import asyncio
import logging
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


async def run_parser_async() -> None:
    global SYNC_STATUS
    if SYNC_STATUS["is_running"]:
        return

    SYNC_STATUS["is_running"] = True
    await manager.broadcast({"type": "sync_start"})

    try:
        await parser_main()

        conn = get_db()
        repo = ArticleRepository(conn)
        new_count = repo.get_inbox_count()
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
