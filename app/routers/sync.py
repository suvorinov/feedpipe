import asyncio
import logging

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.sync_state import SYNC_STATUS, run_parser_async

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/sync")
async def trigger_sync(user: str = Depends(get_current_user)) -> dict:
    asyncio.create_task(run_parser_async())
    return {"status": "sync_started", "is_running": SYNC_STATUS["is_running"]}


@router.get("/api/status")
def get_status(user: str = Depends(get_current_user)) -> dict:
    return SYNC_STATUS
