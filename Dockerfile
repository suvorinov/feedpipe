FROM python:3.11-slim

WORKDIR /app

# Зеркало PyPI
RUN pip config set global.index-url https://pypi.org/simple/

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем пакет app
COPY app/ /app/app/

# Копируем шаблоны и статику
COPY templates/ /app/templates/
COPY static/ /app/static/

# Создаем директорию для данных
RUN mkdir -p /app/app/data

# Запускаем приложение
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]