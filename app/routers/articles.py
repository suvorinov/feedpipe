import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
import sqlite3

from app.auth import get_current_user
from app.db import get_db
from app.repositories.articles import ArticleRepository
from app.ws_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


async def _update_article_status(
    article_id: int,
    status: str,
    db: sqlite3.Connection,
) -> HTMLResponse:
    valid_statuses = ("inbox", "later", "archived")
    if status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    repo = ArticleRepository(db)
    if not repo.update_status(article_id, status):
        raise HTTPException(404, "Article not found or already has this status")

    inbox_count = repo.get_inbox_count()
    later_count = repo.get_later_count()

    await manager.broadcast({
        "type": "counter_update",
        "inbox_count": inbox_count,
        "later_count": later_count
    })

    return HTMLResponse(content="", status_code=200)


@router.patch("/api/articles/{article_id}/status")
async def update_article_status(
    article_id: int,
    status: str,
    user: str = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    return await _update_article_status(article_id, status, db)


@router.delete("/api/articles/{article_id}")
async def delete_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "archived", db)


@router.patch("/api/articles/{article_id}/hold")
async def hold_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "later", db)


@router.patch("/api/articles/{article_id}/restore")
async def restore_article(article_id: int, user: str = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    return await _update_article_status(article_id, "inbox", db)
