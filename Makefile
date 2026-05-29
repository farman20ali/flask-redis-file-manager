.PHONY: help env env-local env-new-redis env-docker install run start-local stop-local uninstall-local local docker-build docker-up docker-down docker-logs redis-up redis-down redis-uninstall deploy-local deploy-docker deploy-new-redis setup setup-local start-docker stop-docker uninstall-docker

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
COMPOSE ?= docker compose
ENV_FILE ?= .env
ENV_EXAMPLE ?= .env.example
REDIS_CONTAINER ?= flask-redis-file-manager-redis
REDIS_IMAGE ?= redis:7-alpine
REDIS_PORT ?= 6379
REDIS_HOST_PORT ?= 6380
APP_PORT ?= 5000
REDIS_PASSWORD ?=
REDIS_DATA ?= redis-data
APP_PID_FILE ?= .app.pid
APP_LOG_FILE ?= app.log

help:
	@printf '%s\n' "Available targets:"
	@printf '%s\n' "  make env            Create .env from .env.example if it does not exist"
	@printf '%s\n' "  make env-local      Write .env for a local Redis server"
	@printf '%s\n' "  make env-new-redis  Write .env for a new local Redis container"
	@printf '%s\n' "  make env-docker     Write .env for Docker Compose"
	@printf '%s\n' "  make install        Install Python dependencies"
	@printf '%s\n' "  make run            Start the Flask app locally"
	@printf '%s\n' "  make deploy-local   Prepare env and run the app locally"
	@printf '%s\n' "  make setup-local    Prepare local env and run against an existing Redis"
	@printf '%s\n' "  make deploy-new-redis  Prepare env and start a fresh Redis container locally"
	@printf '%s\n' "  make redis-up       Start a local Redis container"
	@printf '%s\n' "  make redis-down     Stop the local Redis container"
	@printf '%s\n' "  make redis-uninstall  Stop and remove the local Redis container and data volume"
	@printf '%s\n' "  make start-local    Start the app in the background"
	@printf '%s\n' "  make stop-local     Stop the background local app"
	@printf '%s\n' "  make uninstall-local  Stop local app and remove generated files"
	@printf '%s\n' "  make docker-up      Build and start the Docker stack"
	@printf '%s\n' "  make deploy-docker  Prepare env and start the Docker stack"
	@printf '%s\n' "  make docker-down    Stop the Docker stack"
	@printf '%s\n' "  make start-docker   Start the Docker stack"
	@printf '%s\n' "  make stop-docker    Stop the Docker stack"
	@printf '%s\n' "  make uninstall-docker  Stop Docker stack and remove containers/volumes"
	@printf '%s\n' "  make docker-logs    Follow Docker logs"
	@printf '%s\n' "  make setup          Prepare local env and start Redis + app"

env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp "$(ENV_EXAMPLE)" "$(ENV_FILE)"; \
		printf '%s\n' "Created $(ENV_FILE) from $(ENV_EXAMPLE)"; \
	else \
		printf '%s\n' "$(ENV_FILE) already exists"; \
	fi

env-local:
	@printf '%s\n' "FLASK_SECRET_KEY=your_secret_key_change_this_in_production" > "$(ENV_FILE)"
	@printf '%s\n' "FLASK_DEBUG=True" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_HOST=0.0.0.0" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_PORT=$(APP_PORT)" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_HOST=localhost" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PORT=$(REDIS_PORT)" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PASSWORD=$(REDIS_PASSWORD)" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_USER=your_username" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_ROLE=admin" >> "$(ENV_FILE)"
	@printf '%s\n' "CHUNK_SIZE=1048576" >> "$(ENV_FILE)"
	@printf '%s\n' "Wrote local Redis settings to $(ENV_FILE)"

env-new-redis:
	@printf '%s\n' "FLASK_SECRET_KEY=your_secret_key_change_this_in_production" > "$(ENV_FILE)"
	@printf '%s\n' "FLASK_DEBUG=True" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_HOST=0.0.0.0" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_PORT=$(APP_PORT)" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_HOST=localhost" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PORT=$(REDIS_HOST_PORT)" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PASSWORD=$(REDIS_PASSWORD)" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_USER=your_username" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_ROLE=admin" >> "$(ENV_FILE)"
	@printf '%s\n' "CHUNK_SIZE=1048576" >> "$(ENV_FILE)"
	@printf '%s\n' "Wrote new Redis container settings to $(ENV_FILE)"

env-docker:
	@printf '%s\n' "FLASK_SECRET_KEY=your_secret_key_change_this_in_production" > "$(ENV_FILE)"
	@printf '%s\n' "FLASK_DEBUG=True" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_HOST=0.0.0.0" >> "$(ENV_FILE)"
	@printf '%s\n' "FLASK_PORT=$(APP_PORT)" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_HOST=redis" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PORT=6379" >> "$(ENV_FILE)"
	@printf '%s\n' "REDIS_PASSWORD=" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_USER=your_username" >> "$(ENV_FILE)"
	@printf '%s\n' "DEFAULT_ROLE=admin" >> "$(ENV_FILE)"
	@printf '%s\n' "CHUNK_SIZE=1048576" >> "$(ENV_FILE)"
	@printf '%s\n' "Wrote Docker settings to $(ENV_FILE)"

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) app.py

local: run

start-local:
	@nohup $(PYTHON) app.py > "$(APP_LOG_FILE)" 2>&1 & echo $$! > "$(APP_PID_FILE)"
	@printf '%s\n' "App started in background. PID stored in $(APP_PID_FILE)"

stop-local:
	@if [ -f "$(APP_PID_FILE)" ]; then \
		kill "$$(cat $(APP_PID_FILE))" 2>/dev/null || true; \
		rm -f "$(APP_PID_FILE)"; \
		printf '%s\n' "Stopped local app"; \
	else \
		printf '%s\n' "No local app PID file found"; \
	fi

uninstall-local: stop-local
	@rm -f "$(APP_LOG_FILE)" "$(ENV_FILE)"
	@printf '%s\n' "Removed generated local files"

docker-build: env-docker
	$(COMPOSE) build

docker-up: env-docker
	$(COMPOSE) up --build -d

start-docker: docker-up

stop-docker: docker-down

uninstall-docker:
	$(COMPOSE) down --volumes --remove-orphans
	@rm -f "$(ENV_FILE)"
	@printf '%s\n' "Stopped and removed Docker deployment files"

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f

redis-up:
	docker run -d \
		--name $(REDIS_CONTAINER) \
		-p $(REDIS_HOST_PORT):6379 \
		-v $(REDIS_DATA):/data \
		$(REDIS_IMAGE) redis-server --appendonly yes

redis-down:
	-docker stop $(REDIS_CONTAINER)
	-docker rm $(REDIS_CONTAINER)

redis-uninstall: redis-down
	-docker volume rm $(REDIS_DATA)

deploy-local: env-local install run

deploy-docker: env-docker docker-up

deploy-new-redis: env-new-redis install redis-up start-local

setup: env-new-redis install redis-up run

setup-local: env-local install start-local