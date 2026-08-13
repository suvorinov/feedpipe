import os
from datetime import datetime

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def format_date(value: datetime | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

    # Приводим к naive: datetime.now() без таймзоны, а смещение дало бы TypeError
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)

    now = datetime.now()
    diff = now - value

    if diff.days < 0:
        return "только что"
    if diff.days == 0:
        hours = diff.seconds // 3600
        mins = (diff.seconds % 3600) // 60
        if hours > 0:
            return f"{hours}ч назад"
        if mins > 0:
            return f"{mins}м назад"
        return "только что"
    if diff.days == 1:
        return "вчера"
    if diff.days < 7:
        return f"{diff.days}д назад"
    return value.strftime("%d %b")


class CustomJinja2Templates(Jinja2Templates):
    def __init__(self, directory: str = TEMPLATES_DIR, cache_size: int = 0):
        super().__init__(directory=directory)
        self.env = Environment(
            loader=FileSystemLoader(directory),
            autoescape=select_autoescape(["html", "xml"]),
            cache_size=cache_size,
        )
        self.env.filters["format_date"] = format_date


templates = CustomJinja2Templates()
