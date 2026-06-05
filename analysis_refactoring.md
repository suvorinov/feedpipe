# Анализ проекта Feedpipe и план рефакторинга

## 1. Общая информация

Feedpipe — бруталистский RSS/Atom агрегатор с веб-интерфейсом. Стек: **FastAPI + SQLite + Jinja2 + HTMX + APScheduler**. Есть Chrome-расширение для быстрого добавления фидов.

---

## 2. Текущая архитектура

```
feedpipe/
├── app/
│   ├── __init__.py          # пустой
│   ├── main.py              # FastAPI приложение (459 строк) — МОНОЛИТ
│   ├── parser.py            # парсинг RSS/Atom (177 строк)
│   ├── db.py                # работа с SQLite (75 строк)
│   ├── auth.py              # bcrypt-хэширование (14 строк)
│   ├── manifest.json        # PWA manifest
│   └── data/                # SQLite БД + feeds.txt
├── templates/               # 12 Jinja2 шаблонов
├── static/                  # CSS, JS, иконки
├── extension/               # Chrome extension (manifest, popup)
├── tests/                   # 3 тестовых файла
├── Dockerfile / docker-compose.yml
└── Makefile
```

---

## 3. Проблемы и узкие места

### 3.1. Монолит `main.py` (459 строк)

Файл содержит **всё**: lifespan, ConnectionManager, sync-логику, format_date, все API эндпоинты, HTML-роуты, валидацию URL, авто-дискавери RSS, статику.

**Что нужно вынести:**

| Компонент | Куда |
|---|---|
| `ConnectionManager` | `app/ws_manager.py` |
| `SYNC_STATUS`, `run_parser_async()`, `fire_and_forget_sync()` | `app/sync.py` |
| `format_date()`, `CustomJinja2Templates` | `app/template_filters.py` |
| Роуты `/api/feeds` | `app/routers/feeds.py` |
| Роуты `/api/articles` | `app/routers/articles.py` |
| Роуты `/api/auth`, `/login`, `/logout` | `app/routers/auth.py` |
| Роуты `/api/sync`, `/api/status` | `app/routers/sync.py` |
| Веб-роуты `/`, `/ws` | `app/routers/web.py` |

### 3.2. Глобальные мутабельные состояния

- `SYNC_STATUS = {"is_running": False, ...}` — меняется из разных мест, нет синхронизации.
- `manager = ConnectionManager()` — глобальный экземпляр.
- `scheduler = BackgroundScheduler()` — глобальный экземпляр.
- `templates = CustomJinja2Templates(...)` — глобальный.
- `DB_PATH` в `db.py` — глобальная переменная, изменяется в тестах через monkey-patch.

### 3.3. SQL-запросы в роутах

Роуты содержат прямые SQL-запросы вместо слоя репозитория:

```python
# main.py:151
conn = get_db()
cursor = conn.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'")
```

Нужно вынести логику доступа к данным в отдельный дата-слой.

### 3.4. Проблемы парсера

- `save_articles()` — цикл с retry + sleep при блокировке БД; использует `get_db()` внутри цикла.
- `clean_html()` — сырой regex для удаления HTML (лучше `bleach` или `lxml`).
- `main()` не разделена на этапы; нет graceful cancellation.
- Константы `REQUEST_TIMEOUT` и `CONCURRENT_LIMIT` хардкодом в модуле.

### 3.5. Проблемы тестов

- `test_add_feed` помечен как `skip` (нет моков для HTTP).
- Нет тестов для WebSocket.
- Нет тестов для `parser.main()`.
- `test_db` фикстура использует monkey-patch глобальной `DB_PATH`.
- Нет изоляции тестов — переиспользуют один клиент.

### 3.6. Инлайн JavaScript в шаблонах

В `sidebar_add_source.html` (строка 11-22) — inline JS-обработчик `htmx:responseError`. Нарушает Content Security Policy и усложняет поддержку.

### 3.7. Локализация (i18n)

- Если/else по `lang` в каждом шаблоне.
- В `script.js` строки захардкожены: `isEnglish ? 'SYNC IN PROGRESS...' : 'СИНХРОНИЗАЦИЯ...'`.
- Нет единого механизма i18n.

### 3.8. Обработка ошибок

- `get_current_user()` выбрасывает `HTTPException` — нет нормальной обработки ошибок ни на клиенте, ни на сервере.
- Нет глобального exception handler для неожиданных ошибок.

### 3.9. Чистота кода

- Нет статической типизации (mypy).
- Нет линтера (ruff/flake8).
- Нет CI/CD.
- `requirements.txt` содержит конкретные версии без указания диапазонов.
- Dockerfile без `healthcheck`.
- Нет `python-dotenv` для конфигурации (хотя есть в зависимостях).

---

## 4. План рефакторинга (по этапам)

### Этап 1: Разделение `main.py` на модули

```
app/
├── routers/
│   ├── __init__.py
│   ├── auth.py          # /api/auth, /login, /logout
│   ├── articles.py      # /api/articles/...
│   ├── feeds.py         # /api/feeds
│   ├── sync.py          # /api/sync, /api/status
│   └── web.py           # / (index), /ws
├── ws_manager.py        # ConnectionManager
├── sync.py              # SYNC_STATUS, run_parser_async, fire_and_forget_sync
├── template_filters.py  # format_date, CustomJinja2Templates
└── main.py              # только lifespan + include_routers
```

### Этап 2: Слой репозиториев

```
app/
├── repositories/
│   ├── __init__.py
│   ├── articles.py      # ArticleRepository
│   ├── feeds.py         # FeedRepository
│   └── users.py         # UserRepository
```

### Этап 3: Выделение конфигурации

```python
# app/config.py — читать из переменных окружения с dotenv
# DATABASE_URL, SYNC_INTERVAL, REQUEST_TIMEOUT, CONCURRENT_LIMIT...
```

### Этап 4: Улучшение парсера

- Разделить `main()` на отдельные шаги.
- Добавить graceful shutdown.
- Вынести константы в конфиг.
- Опционально: заменить `html.clean()` на `bleach`.

### Этап 5: Тесты

- Добавить моки для HTTP-запросов (httpx + respx).
- Тесты для WebSocket.
- Тесты для `parser.main()`.
- Убрать monkey-patch `DB_PATH` через `tmp_path`.
- Заменить `pytest.mark.skip` на рабочие тесты.

### Этап 6: Чистка шаблонов

- Вынести inline JS в `static/script.js`.
- Внедрить единый механизм i18n.
- Убрать дублирование в `article_card_actions.html`.

### Этап 7: Инфраструктура

- Добавить `pyproject.toml` с настройками ruff/mypy/pytest.
- Настроить pre-commit hooks.
- Docker healthcheck.
- Rate limiting (slowapi или встроенный).

---

## 5. Оценка приоритетов

| Этап | Приоритет | Сложность | Эффект |
|---|---|---|---|
| Этап 1 — разделение main.py | 🔴 Высокий | Средняя | Устраняет главный монолит |
| Этап 2 — слой репозиториев | 🔴 Высокий | Средняя | Изоляция БД, тестируемость |
| Этап 3 — конфигурация | 🟡 Средний | Низкая | Убирает хардкод |
| Этап 4 — улучшение парсера | 🟡 Средний | Средняя | Надёжность парсинга |
| Этап 5 — тесты | 🔴 Высокий | Высокая | Покрытие, уверенность в изменениях |
| Этап 6 — чистка шаблонов | 🟢 Низкий | Низкая | Чистота фронтенда |
| Этап 7 — инфраструктура | 🟡 Средний | Средняя | Качество кода, CI/CD |

---

## 6. Итого

Проект небольшой и качественно написан для своего масштаба, но страдает от классической проблемы "быстрого прототипа": вся серверная логика склеена в `main.py`. Основной приоритет — **разделение на модули** и **добавление тестов** перед внесением новых фич. Без этого каждый следующий коммит будет усложнять поддержку.
