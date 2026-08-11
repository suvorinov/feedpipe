.PHONY: help build up up-attach down logs restart parse dev shell clean network-create network-connect npm-up npm-logs npm-restart setup

# Общая сеть с NPM и имя контейнера NPM (можно переопределить при вызове)
NETWORK ?= proxy
NPM_CONTAINER ?= nginx-proxy-manager

# Файл compose для Nginx Proxy Manager
NPM_COMPOSE = npm/docker-compose.yml

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
# Сеть с Nginx Proxy Manager
# ========================

# Сеть proxy создаёт и «владеет» сам NPM (см. npm/docker-compose.yml).
# Два сервиса (make up / make npm-up) могут стартовать в любом порядке,
# поэтому ниже остаётся резервная команда на случай, если NPM уже работает
# где-то ещё и без сети proxy.

network-create: ## Создать общую сеть с NPM (один раз, если NPM запущен вручную)
	docker network inspect $(NETWORK) >/dev/null 2>&1 || docker network create $(NETWORK)

network-connect: ## Подключить контейнер NPM к общей сети (один раз, если NPM запущен вручную)
	@docker network connect $(NETWORK) $(NPM_CONTAINER) 2>/dev/null \
		&& echo "NPM ($(NPM_CONTAINER)) подключён к сети $(NETWORK)" \
		|| echo "Не удалось подключить $(NPM_CONTAINER): контейнер не найден или уже в сети. Используйте: make network-connect NPM_CONTAINER=<имя>"

npm-up: ## Запустить Nginx Proxy Manager (создаёт сеть proxy)
	docker compose -f $(NPM_COMPOSE) up -d

npm-logs: ## Логи Nginx Proxy Manager
	docker compose -f $(NPM_COMPOSE) logs -f

npm-restart: ## Перезапустить Nginx Proxy Manager
	docker compose -f $(NPM_COMPOSE) restart

setup: ## Первичная настройка: NPM (сеть proxy) + запуск feedpipe
	docker compose -f $(NPM_COMPOSE) up -d
	docker compose up -d

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
