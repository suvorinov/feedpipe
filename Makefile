.PHONY: help build up up-attach down logs restart parse dev shell clean

# ========================
# Справка
# ========================

help: ## Показать справку
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ========================
# Docker Compose
# ========================

build: ## Собрать образ
	docker compose build

up: ## Запустить сервис (в фоне)
	docker compose up -d

up-attach: ## Запустить сервис (в консоли)
	docker compose up

down: ## Остановить и удалить контейнеры
	docker compose down

logs: ## Посмотреть логи
	docker compose logs -f

restart: ## Перезапустить сервис
	docker compose restart

# ========================
# Парсер
# ========================

parse: ## Запустить парсер (сбор фидов)
	docker compose run --rm feedpipe python -m app.parser

# ========================
# Разработка
# ========================

dev: ## Запустить сервис в режиме разработки (авто-перезагрузка, только loopback)
	.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8700

shell: ## Открыть shell в контейнере
	docker compose exec feedpipe /bin/bash

clean: ## Остановить и очистить volumes
	docker compose down -v
	docker system prune -f
