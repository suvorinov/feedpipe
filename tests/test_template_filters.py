from datetime import UTC, datetime, timedelta

from app.template_filters import format_date


class TestFormatDate:
    def test_none(self):
        assert format_date(None) == ""

    def test_empty_string(self):
        assert format_date("") == ""

    def test_unparseable_string_passthrough(self):
        assert format_date("not-a-date") == "not-a-date"

    def test_timezone_aware_string_does_not_crash(self):
        value = "2024-01-01T12:00:00+00:00"
        assert isinstance(format_date(value), str)

    def test_timezone_aware_datetime_does_not_crash(self):
        value = datetime.now(UTC) - timedelta(hours=1)
        assert "ч назад" in format_date(value)

    def test_future_date(self):
        value = datetime.now() + timedelta(days=1)
        assert format_date(value) == "только что"

    def test_minutes_ago(self):
        value = datetime.now() - timedelta(minutes=5)
        assert format_date(value) == "5м назад"

    def test_hours_ago(self):
        value = datetime.now() - timedelta(hours=2)
        assert format_date(value) == "2ч назад"

    def test_yesterday(self):
        value = datetime.now() - timedelta(days=1)
        assert format_date(value) == "вчера"

    def test_older_than_week(self):
        value = datetime(2024, 1, 1)
        result = format_date(value)
        assert result.startswith("01 ") and len(result) <= 8
