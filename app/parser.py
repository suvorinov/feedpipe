import asyncio
import email.utils
import logging
import httpx
import feedparser
import re
from datetime import datetime, timezone

REQUEST_TIMEOUT = 5.0
CONCURRENT_LIMIT = 10

logger = logging.getLogger(__name__)

from .db import get_db, init_db, migrate_feeds_txt
from .repositories.articles import ArticleRepository
from .repositories.feeds import FeedRepository


async def save_articles(articles: list[dict], retries: int = 3) -> int:
    if not articles:
        return 0

    for attempt in range(retries):
        conn = None
        try:
            conn = get_db()
            repo = ArticleRepository(conn)
            saved_count = repo.bulk_insert(articles)
            conn.close()
            return saved_count
        except Exception as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise
        finally:
            if conn:
                conn.close()

    return 0

def clean_html(raw_text: str) -> str:
    import html
    clean = re.sub(r'<[^>]+>', '', raw_text)
    clean = html.unescape(clean)
    clean = re.sub(r'submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]?', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def parse_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now()
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed:
            return parsed.replace(tzinfo=None)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except Exception:
        logger.warning(f"Не удалось распарсить дату: {date_str}")
    return datetime.now()

def normalize_entry(entry: dict, feed_url: str) -> dict:
    raw_desc = entry.get('summary') or entry.get('description') or ""
    cleaned_desc = clean_html(raw_desc)
    if len(cleaned_desc) > 200:
        truncated = cleaned_desc[:200]
        last_space = truncated.rfind(' ')
        if last_space > 100:
            short_desc = truncated[:last_space] + "..."
        else:
            short_desc = truncated + "..."
    else:
        short_desc = cleaned_desc
    
    return {
        "title": entry.get("title", "Без заголовка").strip(),
        "link": entry.get("link", ""),
        "description": short_desc,
        "published_at": parse_date(entry.get("published") or entry.get("updated")),
        "source_url": feed_url
    }

async def fetch_feed(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> list[dict]:
    async with semaphore:
        try:
            response = await client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            parsed = feedparser.parse(response.text)
            
            if parsed.bozo and not parsed.entries:
                logger.warning(f"Фид поврежден или пуст: {url} | Ошибка: {parsed.bozo_exception}")
                return []

            feed_title = parsed.feed.get('title', url)
            articles = []
            for entry in parsed.entries:
                norm_entry = normalize_entry(entry, url)
                if norm_entry['link']:
                    articles.append(norm_entry)

            logger.info(f"[{feed_title[:30]}] Спарсено статей: {len(articles)}")
            return articles

        except httpx.TimeoutException:
            logger.warning(f"Таймаут: {url}")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка {e.response.status_code}: {url}")
            return []
        except Exception as e:
            logger.error(f"Неизвестная ошибка {url}: {e}")
            return []

async def main():
    logger.info("Feedpipe Parser запущен")

    init_db()
    migrate_feeds_txt()

    conn = get_db()
    feed_repo = FeedRepository(conn)
    urls = feed_repo.get_all_urls()
    conn.close()

    if not urls:
        logger.info("В базе нет подписок. Добавьте их через веб-интерфейс.")
        return

    logger.info(f"Загружено подписок из БД: {len(urls)}")

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Feedpipe/1.0)"}

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [fetch_feed(client, url, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)

    all_articles = [article for sublist in results for article in sublist]

    logger.info("Сохранение в базу данных...")
    new_saved = await save_articles(all_articles)

    conn = get_db()
    repo = ArticleRepository(conn)
    inbox_count = repo.get_inbox_count()
    conn.close()

    logger.info(f"Всего найдено статей: {len(all_articles)}")
    logger.info(f"Новых добавлено: {new_saved}")
    logger.info(f"Непрочитанных в Inbox: {inbox_count}")

if __name__ == "__main__":
    asyncio.run(main())