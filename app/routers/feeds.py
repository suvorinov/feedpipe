import asyncio
import ipaddress
import logging
import re
import socket
import sqlite3
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.config import FEED_DISCOVERY_TIMEOUT, FEED_FETCH_TIMEOUT
from app.db import get_db
from app.repositories.feeds import FeedRepository
from app.sync_state import run_parser_async
from app.template_filters import templates

logger = logging.getLogger(__name__)
router = APIRouter()

# Сети, в которые сервер ходить не должен: защита от SSRF.
# Любой URL, который резолвится в эти диапазоны, отклоняем до запроса.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::"),
    ipaddress.ip_network("::1"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in network for network in _PRIVATE_NETWORKS)


async def _assert_public_url(url: str) -> None:
    """Отклоняет URL, ведущий на внутренние адреса (SSRF-защита).

    - IP-литералы проверяем сразу, без DNS.
    - Хостнеймы резолвим в потоке (getaddrinfo блокирующий) и проверяем
      каждый адрес: хост может отдавать и публичный, и приватный IP.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        raise ValueError("В URL нет хоста")

    if _is_private_ip(hostname):
        raise ValueError("Внутренние адреса не поддерживаются")

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Не удалось определить адрес хоста") from None

    for info in infos:
        if _is_private_ip(info[4][0]):
            raise ValueError("Хост резолвится во внутренний адрес")


async def _fetch_page(url: str, timeout: float) -> httpx.Response:
    """GET с проверкой и URL до запроса, и итогового URL после редиректов.

    Редирект — классический способ обойти SSRF-фильтр: фильтруют стартовый
    URL, а сервер послушно идёт на внутренний адрес.
    """
    await _assert_public_url(url)
    headers = {"User-Agent": "Feedpipe/1.0"}
    async with httpx.AsyncClient(headers=headers) as client:
        response = await client.get(url, timeout=timeout, follow_redirects=True)
    await _assert_public_url(str(response.url))
    return response


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
            resp = await _fetch_page(url, FEED_DISCOVERY_TIMEOUT)
            resp.raise_for_status()
            match = re.search(
                r'<link\b(?=[^>]*type=["\']application/(?:rss|atom)\+xml["\'])'
                r'(?=[^>]*href=["\']([^"\']+)["\'])[^>]*>',
                resp.text,
                re.IGNORECASE,
            )
            if match:
                found_rss = match.group(1)
                if found_rss.startswith("/"):
                    found_rss = urljoin(url, found_rss)
                url = found_rss
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": f"{e}!"})
        except Exception:
            pass

    try:
        resp = await _fetch_page(url, FEED_FETCH_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)

        if parsed.bozo and not parsed.entries:
            return JSONResponse(
                status_code=400, content={"error": f"Фид повреждён или пуст: {str(parsed.bozo_exception)[:100]}!"}
            )

        title = parsed.feed.get("title", url)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"{e}!"})
    except httpx.TimeoutException:
        return JSONResponse(status_code=400, content={"error": "Таймаут при получении фида!"})
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=400, content={"error": f"Ошибка HTTP: {e.response.status_code}!"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Не удалось распознать фид: {str(e)[:100]}!"})

    repo = FeedRepository(db)
    try:
        await asyncio.to_thread(repo.add, url, title)
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=409, content={"error": "Уже подписан!"})

    background_tasks.add_task(run_parser_async)

    feeds = await asyncio.to_thread(repo.get_all)
    return templates.TemplateResponse(request, "feeds_list.html", {"feeds": feeds})


@router.delete("/api/feeds/{feed_id}")
def delete_feed(
    request: Request,
    feed_id: int,
    user: str = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    repo = FeedRepository(db)
    repo.delete(feed_id)
    # htmx: основной swap убирает <li> (hx-target="closest li"), а этот фрагмент
    # out-of-band обновляет счётчик фидов в сайдбаре.
    feeds = repo.get_all()
    return templates.TemplateResponse(request, "feeds_count_oob.html", {"feeds": feeds})
