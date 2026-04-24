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
| DELETE | `/api/feeds/{id}` | Удалить фид |
| PATCH | `/api/articles/{id}/status?status=later\|inbox\|archived` | Изменить статус статьи |
| POST | `/api/sync` | Запустить синхронизацию |
| GET | `/api/status` | Статус синхронизации |

## Структура

```
app/
  main.py      # FastAPI приложение
  db.py        # Работа с SQLite
  parser.py    # Парсинг RSS/Atom
templates/     # HTML шаблоны
static/        # CSS, JS
```