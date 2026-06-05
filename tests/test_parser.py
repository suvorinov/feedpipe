from datetime import datetime

from app.parser import clean_html, parse_date, normalize_entry


class TestCleanHtml:
    def test_removes_tags(self):
        assert clean_html("<p>Hello</p>") == "Hello"

    def test_removes_nested_tags(self):
        assert clean_html("<div><p>Text</p></div>") == "Text"

    def test_unescapes_entities(self):
        assert clean_html("Hello &amp; World") == "Hello & World"

    def test_removes_reddit_footer(self):
        raw = 'Some text submitted by /u/testuser [link] [comments]'
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
