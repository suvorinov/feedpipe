# Feedpipe

RSS/Atom агрегатор с веб-интерфейсом.

## Функционал

- Автоматический сбор статей с RSS/Atom лент каждые 30 минут
- Просмотр: Входящие / Отложенные
- Добавление/удаление фидов
- Поиск по списку фидов
- Real-time обновления через WebSocket
- Бесконечная прокрутка (keyset-пагинация по id)

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
- `FEEDPIPE_DATA_DIR` — каталог для данных (БД и `secret.key`), по умолчанию `app/data`
- `FEEDPIPE_SECRET` — секрет подписи сессий (иначе генерируется и хранится в `DATA_DIR/secret.key`)
- `FEEDPIPE_ALLOWED_ORIGINS` — дополнительные доверенные origins для CSRF-проверки (через запятую)
- `FEEDPIPE_SECURE_COOKIE` — `1`, если приложение отдаётся по HTTPS: сессионный cookie получит флаг `Secure`

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
Подгрузка — бесконечная прокрутка: невидимый сентинел в конце ленты запрашивает следующую страницу
и заменяется её содержимым.

## Расширение

`extension/` — Chrome-расширение «Feedpipe Injector». В попапе укажите адрес сервера.
Авторизация — автоматически: расширение читает валидную сессию из cookie-хранилища браузера
(достаточно один раз войти на сервере в этом браузере).

## Структура

```
app/
  main.py              # FastAPI-приложение: lifespan, планировщик, CSRF-guard, /health
  config.py            # Таймауты и лимиты сетевой работы
  db.py                # SQLite: схема, WAL, write_lock, get_db-зависимость
  auth.py              # HMAC-сессии, bcrypt, единая проверка авторизации
  parser.py            # Сбор и парсинг RSS/Atom (feedparser + httpx)
  sync_state.py        # Оркестрация синхронизации, статусы, рассылка по WebSocket
  ws_manager.py        # Управление WebSocket-соединениями
  template_filters.py  # Jinja2-фильтры (format_date)
  routers/             # HTTP-эндпоинты: web, articles, feeds, auth, sync
  repositories/        # Доступ к БД: articles, feeds, users
templates/             # HTML-шаблоны (Jinja2 + htmx)
static/                # CSS, JS, иконки
extension/             # Chrome-расширение «Feedpipe Injector»
tests/                 # pytest: юнит, интеграционные, безопасность
```

## Качество кода

```bash
make lint      # ruff check
make fmt       # ruff format
make test      # pytest
```