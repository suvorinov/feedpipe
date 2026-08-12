# Feedpipe

RSS/Atom агрегатор с веб-интерфейсом.

## Функционал

- Автоматический сбор статей с RSS/Atom лент каждые 30 минут
- Просмотр: Входящие / Отложенные
- Добавление/удаление фидов
- Поиск по списку фидов
- Real-time обновления через WebSocket
- Пагинация с кнопкой "Загрузить ещё"

## Требования

- Python 3.11+
- Docker (опционально)

## Установка

### Локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Docker

```bash
docker-compose up -d
```

## Запуск

### Локально

```bash
uvicorn app.main:app --reload --port 8000
```

### Docker

```bash
docker-compose up -d
```

Открыть http://localhost:8700

## Переменные окружения

- `TZ` — часовой пояс (по умолчанию Europe/Moscow)

## API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Главная страница |
| GET | `/ws` | WebSocket |
| POST | `/api/feeds` | Добавить фид |
| DELETE | `/api/feeds/{id}` | Удалить фид (вместе со статьями) |
| PATCH | `/api/articles/{id}/status?status=later\|inbox\|archived` | Изменить статус статьи |
| POST | `/api/sync` | Запустить синхронизацию |
| GET | `/api/status` | Статус синхронизации |
| GET | `/health` | Healthcheck (включая БД) |

### Авторизация

- Обычный пользователь: cookie `feedpipe_user` (HMAC-подпись), HttpOnly, SameSite=Lax.
- Расширение: та же подписанная сессия заголовком `X-Feedpipe-Session` (cookie cross-origin не отправилась бы).
- CSRF: изменяющие запросы с Origin/Referer проверяются на совпадение с Host. Дополнительные доверенные origins — через `FEEDPIPE_ALLOWED_ORIGINS` (через запятую).

### Пагинация

Список статей — keyset-пагинация по id: `/?view=inbox&before=123` (следующая страница после id 123).

## Расширение

`extension/` — Chrome-расширение «Feedpipe Injector». В попапе укажите адрес сервера.
Авторизация — автоматически: расширение читает валидную сессию из cookie-хранилища браузера
(достаточно один раз войти на сервере в этом браузере).

## Структура

```
app/
  main.py      # FastAPI приложение
  db.py        # Работа с SQLite
  parser.py    # Парсинг RSS/Atom
templates/     # HTML шаблоны
static/        # CSS, JS
```

## Качество кода

```bash
make lint      # ruff check
make fmt       # ruff format
make test      # pytest
```