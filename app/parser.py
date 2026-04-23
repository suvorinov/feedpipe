import asyncio
import httpx
import feedparser
import sqlite3
import re
from datetime import datetime

REQUEST_TIMEOUT = 5.0 
CONCURRENT_LIMIT = 10 

from .db import get_db, init_db, migrate_feeds_txt

def save_articles(articles, retries=3):
    if not articles:
        return 0

    for attempt in range(retries):
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            saved_count = 0

            for article in articles:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO articles
                        (title, link, description, published_at, source_url, status)
                        VALUES (?, ?, ?, ?, ?, 'inbox')
                    ''', (
                        article['title'],
                        article['link'],
                        article['description'],
                        article['published_at'],
                        article['source_url']
                    ))
                    if cursor.rowcount > 0:
                        saved_count += 1
                except sqlite3.Error as e:
                    print(f"❌ Ошибка БД при сохранении {article['link']}: {e}")

            conn.commit()
            conn.close()
            return saved_count
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                import time
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
        finally:
            if conn:
                conn.close()

    return 0

def clean_html(raw_text):
    import html
    clean = re.sub(r'<[^>]+>', '', raw_text)
    clean = html.unescape(clean)
    clean = re.sub(r'submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]?', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def parse_date(date_str):
    if not date_str:
        return datetime.now()
    try:
        parsed_time = feedparser.parse(date_str)
        if parsed_time and 'published_parsed' in parsed_time:
            t = parsed_time['published_parsed']
            return datetime(*t[:6])
    except Exception:
        pass
    return datetime.now()

def normalize_entry(entry, feed_url):
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

async def fetch_feed(client, url, semaphore):
    async with semaphore:
        try:
            response = await client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            parsed = feedparser.parse(response.text)
            
            if parsed.bozo and not parsed.entries:
                print(f"⚠️  Фид поврежден или пуст: {url} | Ошибка: {parsed.bozo_exception}")
                return []

            feed_title = parsed.feed.get('title', url)
            articles = []
            for entry in parsed.entries:
                norm_entry = normalize_entry(entry, url)
                if norm_entry['link']:
                    articles.append(norm_entry)
                    
            print(f"✅ [{feed_title[:30]}] Спарсено статей: {len(articles)}")
            return articles

        except httpx.TimeoutException:
            print(f"⏳ Таймаут: {url}")
            return []
        except httpx.HTTPStatusError as e:
            print(f"🚫 Ошибка {e.response.status_code}: {url}")
            return []
        except Exception as e:
            print(f"❌ Неизвестная ошибка {url}: {e}")
            return []

async def main():
    print("="*50)
    print("🚀 Feedpipe Parser запущен")
    print("="*50)
    
    init_db()
    migrate_feeds_txt()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM feeds")
    urls = [row['url'] for row in cursor.fetchall()]
    conn.close()

    if not urls:
        print("📝 В базе нет подписок. Добавьте их через веб-интерфейс.")
        return
        
    print(f"📝 Загружено подписок из БД: {len(urls)}\n")

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Feedpipe/1.0)"}

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [fetch_feed(client, url, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)
        
    all_articles = [article for sublist in results for article in sublist]
    
    print("\n" + "="*50)
    print("💾 Сохранение в базу данных...")
    new_saved = save_articles(all_articles)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'")
    inbox_count = cursor.fetchone()[0]
    conn.close()
    
    print(f"✨ Всего найдено статей: {len(all_articles)}")
    print(f"🆕 Новых добавлено: {new_saved}")
    print(f"📬 Непрочитанных в Inbox: {inbox_count}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())