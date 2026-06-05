from datetime import datetime

from fastapi.templating import Jinja2Templates


def format_date(value: datetime | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    now = datetime.now()
    diff = now - value
    if diff.days == 0:
        hours = diff.seconds // 3600
        mins = (diff.seconds % 3600) // 60
        if hours > 0:
            return f"{hours}ч назад"
        elif mins > 0:
            return f"{mins}м назад"
        else:
            return "только что"
    elif diff.days == 1:
        return "вчера"
    elif diff.days < 7:
        return f"{diff.days}д назад"
    else:
        return value.strftime("%d %b")


class CustomJinja2Templates(Jinja2Templates):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.env.filters["format_date"] = format_date


templates = CustomJinja2Templates(directory="templates", cache_size=0)
