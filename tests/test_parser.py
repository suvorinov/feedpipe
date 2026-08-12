import threading
import time
from datetime import datetime, timedelta

import pytest

from app.db import write_lock
from app.parser import clean_html, normalize_entry, parse_date, save_articles
from app.repositories.articles import ArticleRepository


class TestCleanHtml:
    def test_removes_tags(self):
        assert clean_html("<p>Hello</p>") == "Hello"

    def test_removes_nested_tags(self):
        assert clean_html("<div><p>Text</p></div>") == "Text"

    def test_unescapes_entities(self):
        assert clean_html("Hello &amp; World") == "Hello & World"

    def test_removes_reddit_footer(self):
        raw = "Some text submitted by /u/testuser [link] [comments]"
        assert clean_html(raw) == "Some text"

    def test_collapses_whitespace(self):
        assert clean_html("Hello    World") == "Hello World"

    def test_empty_string(self):
        assert clean_html("") == ""

    def test_no_html(self):
        assert clean_html("Plain text") == "Plain text"

    def test_strips_whitespace(self):
        assert clean_html("  spaced  ") == "spaced"


class TestParseDate:
    def test_returns_datetime_for_valid_rfc2822(self):
        result = parse_date("Mon, 01 Jan 2024 12:00:00 +0000")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_returns_datetime_for_valid_iso(self):
        result = parse_date("2024-01-01T12:00:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_returns_now_for_none(self):
        before = datetime.now()
        result = parse_date(None)
        after = datetime.now()
        assert before <= result <= after

    def test_returns_now_for_empty(self):
        result = parse_date("")
        assert isinstance(result, datetime)

    def test_returns_now_for_garbage(self):
        result = parse_date("not a date at all")
        assert isinstance(result, datetime)


class TestNormalizeEntry:
    def test_basic_entry(self):
        entry = {
            "title": "Test Article",
            "link": "https://example.com/article",
            "summary": "<p>Some description</p>",
            "published": "Mon, 01 Jan 2024 12:00:00 +0000",
        }
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["title"] == "Test Article"
        assert result["link"] == "https://example.com/article"
        assert result["description"] == "Some description"
        assert result["source_url"] == "https://example.com/rss"
        assert isinstance(result["published_at"], datetime)

    def test_fallback_description(self):
        entry = {
            "title": "No Summary",
            "link": "https://example.com/article",
            "description": "Desc field",
        }
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["description"] == "Desc field"

    def test_title_stripped(self):
        entry = {
            "title": "  Spaced Title  ",
            "link": "https://example.com/article",
        }
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["title"] == "Spaced Title"

    def test_default_title(self):
        entry = {"link": "https://example.com/article"}
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["title"] == "Без заголовка"

    def test_description_truncated(self):
        long_desc = "word " * 100
        entry = {
            "title": "Long Article",
            "link": "https://example.com/article",
            "summary": long_desc,
        }
        result = normalize_entry(entry, "https://example.com/rss")
        assert len(result["description"]) <= 203
        assert result["description"].endswith("...")

    def test_empty_link_skipped(self):
        entry = {"title": "No Link", "link": ""}
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["link"] == ""

    def test_published_fallback_to_updated(self):
        entry = {
            "title": "Test",
            "link": "https://example.com/article",
            "updated": "Mon, 01 Jan 2024 12:00:00 +0000",
        }
        result = normalize_entry(entry, "https://example.com/rss")
        assert result["published_at"].year == 2024


class TestSaveArticles:
    @pytest.mark.asyncio
    async def test_inserts_and_dedups(self, test_db):
        articles = [
            {
                "title": "Article A",
                "link": "https://example.com/a",
                "description": "Desc A",
                "published_at": "2024-01-01 00:00:00",
                "source_url": "https://example.com/rss",
            },
            {
                "title": "Article B",
                "link": "https://example.com/b",
                "description": "Desc B",
                "published_at": "2024-01-01 00:00:00",
                "source_url": "https://example.com/rss",
            },
        ]
        assert await save_articles(articles) == 2
        assert await save_articles(articles) == 0

    @pytest.mark.asyncio
    async def test_empty_list(self, test_db):
        assert await save_articles([]) == 0


class TestArchiveCleanup:
    def _seed_article(self, test_db, title: str, link: str, status: str, published_at: str):
        test_db.execute(
            "INSERT INTO articles (title, link, status, published_at) VALUES (?, ?, ?, ?)",
            (title, link, status, published_at),
        )

    def test_removes_old_archived_keeps_fresh_and_inbox(self, test_db):
        old_archived = (datetime.now() - timedelta(days=100)).isoformat(sep=" ")
        recent_archived = (datetime.now() - timedelta(days=10)).isoformat(sep=" ")
        old_inbox = (datetime.now() - timedelta(days=200)).isoformat(sep=" ")
        self._seed_article(test_db, "old-archived", "http://old-a", "archived", old_archived)
        self._seed_article(test_db, "fresh-archived", "http://fresh-a", "archived", recent_archived)
        self._seed_article(test_db, "old-inbox", "http://old-i", "inbox", old_inbox)
        test_db.commit()

        from app.repositories.articles import cleanup_archived_articles

        deleted = cleanup_archived_articles()
        assert deleted == 1
        remaining = test_db.execute("SELECT title FROM articles").fetchall()
        assert sorted(r["title"] for r in remaining) == ["fresh-archived", "old-inbox"]


class TestKeysetPagination:
    def test_pages_and_has_more(self, test_db):
        for i in range(55):
            test_db.execute(
                "INSERT INTO articles (title, link, status) VALUES (?, ?, 'inbox')",
                (f"Article {i}", f"http://a{i}"),
            )
        test_db.commit()
        repo = ArticleRepository(test_db)

        page1, more1 = repo.get_by_status("inbox")
        assert len(page1) == 50
        assert more1 is True

        page2, more2 = repo.get_by_status("inbox", before_id=page1[-1]["id"])
        assert len(page2) == 5
        assert more2 is False

        ids = [a["id"] for a in page1 + page2]
        assert ids == sorted(ids, reverse=True)

    def test_no_pagination_when_few_articles(self, test_db):
        test_db.execute("INSERT INTO articles (title, link, status) VALUES ('A', 'http://a', 'inbox')")
        test_db.commit()
        page, more = ArticleRepository(test_db).get_by_status("inbox")
        assert len(page) == 1
        assert more is False


class TestWriteSerialization:
    def test_update_status_waits_for_write_lock(self, test_db):
        """update_status не падает с 'database is locked', а ждёт завершения записи парсера."""
        lock_held = threading.Event()
        release = threading.Event()

        def hold_lock():
            with write_lock:
                lock_held.set()
                release.wait(timeout=5)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        assert lock_held.wait(timeout=5)

        cursor = test_db.execute("INSERT INTO articles (title, link, status) VALUES ('B', 'http://b', 'inbox')")
        test_db.commit()
        article_id = cursor.lastrowid

        result = {}

        def do_update():
            result["ok"] = ArticleRepository(test_db).update_status(article_id, "later")

        updater = threading.Thread(target=do_update)
        updater.start()
        time.sleep(0.2)
        assert updater.is_alive(), "update должен ждать write_lock, а не падать"

        release.set()
        holder.join(timeout=5)
        updater.join(timeout=5)
        assert result["ok"] is True
