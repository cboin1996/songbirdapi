APP_NAME=songbirdapi

.PHONY: setup
setup:
	uv sync --extra dev

.PHONY: upgrade
upgrade:
	uv lock --upgrade
	uv sync --extra dev

.PHONY: lint
lint:
	uv run black $(APP_NAME)/.

.PHONY: test
test:
	uv run pytest tests/unit -v

.PHONY: local-run
local-run:
	uv run uvicorn $(APP_NAME).server:app --host 0.0.0.0

VALKEY_PERSISTENCE_DIR=./data/redis/
SONGBIRD_API_PERSISTENCE_DIR=./data/songbirdapi/
SONGBIRD_API_DOWNLOADS_DIR=$(SONGBIRD_API_PERSISTENCE_DIR)downloads

.PHONY: volumes
volumes:
	mkdir -p $(VALKEY_PERSISTENCE_DIR) || true
	mkdir -p $(SONGBIRD_API_PERSISTENCE_DIR) || true
	mkdir -p $(SONGBIRD_API_DOWNLOADS_DIR) || true

.PHONY: docker-build
docker-build:
	docker build -t $(APP_NAME):latest .

DOCKER_VALKEY_NAME=$(APP_NAME)-redis-ext
DOCKER_NETWORK_NAME=$(APP_NAME)

.PHONY: docker-network
docker-network:
	docker network create $(DOCKER_NETWORK_NAME) || true

.PHONY: docker-run-redis
docker-run-redis: volumes docker-network
	docker run --network $(DOCKER_NETWORK_NAME) --name $(DOCKER_VALKEY_NAME) -p 6379:6379 -v $(VALKEY_PERSISTENCE_DIR):/data -d redis redis-server --save 10 1

.PHONY: docker-connect-redis
docker-connect-redis:
	docker run -it --network $(DOCKER_NETWORK_NAME) --rm redis redis-cli -h $(DOCKER_VALKEY_NAME)

.PHONY: docker-stop-redis
docker-stop-redis:
	docker kill $(DOCKER_VALKEY_NAME) || true
	docker rm $(DOCKER_VALKEY_NAME) || true

.PHONY: docker-clean-redis
docker-clean-redis:
	docker rm $(DOCKER_VALKEY_NAME) || true

.PHONY: docker-run-songbirdapi
docker-run-songbirdapi:
	docker run --network $(DOCKER_NETWORK_NAME) --env-file docker.env -p 8000:8000 -v $(SONGBIRD_API_DOWNLOADS_DIR):/songbirdapi/downloads $(APP_NAME):latest

.PHONY: docker-clean-songbirdapi
docker-clean-songbirdapi:
	docker rm $(APP_NAME) || true
	docker network rm $(APP_NAME) || true

.PHONY: docker-stop-songbirdapi
docker-stop-songbirdapi:
	docker kill $(APP_NAME) || true
	docker rm $(APP_NAME) || true

.PHONY: docker-run-all
docker-run-all: docker-run-redis docker-run-songbirdapi

.PHONY: docker-stop-all
docker-stop-all: docker-stop-redis docker-stop-songbirdapi

.PHONY: docker-clean-all
docker-clean-all: docker-stop-all docker-clean-redis docker-clean-songbirdapi

.PHONY: docker-dev
docker-dev: docker-clean-all docker-build docker-run-all
