import asyncio
import logging
import threading
from datetime import datetime

from app.db import db_conn_context
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

# Ссылка на активную задачу/фьючу синхронизации. Держим намеренно: asyncio
# хранит задачи в WeakSet, и без сильной ссылки pending-задача может быть
# собрана сборщиком мусора посреди синхронизации.
_sync_task: asyncio.Future | None = None

# Защищает проверку/установку флага is_running от гонки между потоками.
_sync_lock = threading.Lock()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def _forget_sync_task(_: asyncio.Future) -> None:
    """Освобождает ссылку на завершённую задачу, чтобы следующий синк её заменил."""
    global _sync_task
    _sync_task = None


async def run_parser_async() -> None:
    with _sync_lock:
        if SYNC_STATUS["is_running"]:
            return
        SYNC_STATUS["is_running"] = True

    await manager.broadcast({"type": "sync_start"})

    try:
        await parser_main()

        with db_conn_context() as conn:
            new_count = ArticleRepository(conn).get_inbox_count()

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
        # Сброс тоже под lock: иначе первая завершившаяся задача могла бы
        # стереть is_running=True, только что поставленный второй задачей.
        with _sync_lock:
            SYNC_STATUS["is_running"] = False


def fire_and_forget_sync() -> None:
    """Запускает синхронизацию в фоне, не дожидаясь результата.

    Во всех ветках сохраняем ссылку на задачу (см. _sync_task), чтобы
    планировщик не собрал её GC посреди работы.

    - Из основного loop (веб-запрос, BackgroundTasks) — через create_task.
    - Из чужого потока (APScheduler) — через run_coroutine_threadsafe в главный loop.
    - Вне приложения (python -m app.parser) — через asyncio.run.
    """
    global _sync_task
    if _main_loop is not None:
        task = asyncio.run_coroutine_threadsafe(run_parser_async(), _main_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            task = loop.create_task(run_parser_async())
        else:
            asyncio.run(run_parser_async())
            return

    _sync_task = task
    task.add_done_callback(_forget_sync_task)
