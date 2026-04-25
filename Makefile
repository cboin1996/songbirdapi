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

.PHONY: test-integration
test-integration:
	ENV=dev uv run pytest tests/integration -v

.PHONY: local-run
local-run:
	uv run uvicorn $(APP_NAME).server:app --host 0.0.0.0 --reload

POSTGRES_PERSISTENCE_DIR=./data/postgres/
SONGBIRD_API_PERSISTENCE_DIR=./data/songbirdapi/
SONGBIRD_API_DOWNLOADS_DIR=$(SONGBIRD_API_PERSISTENCE_DIR)downloads

.PHONY: volumes
volumes:
	mkdir -p $(POSTGRES_PERSISTENCE_DIR) || true
	mkdir -p $(SONGBIRD_API_PERSISTENCE_DIR) || true
	mkdir -p $(SONGBIRD_API_DOWNLOADS_DIR) || true

.PHONY: docker-build
docker-build:
	docker build -t $(APP_NAME):latest .

DOCKER_POSTGRES_NAME=$(APP_NAME)-postgres
DOCKER_NETWORK_NAME=$(APP_NAME)

.PHONY: docker-network
docker-network:
	docker network create $(DOCKER_NETWORK_NAME) || true

.PHONY: docker-run-postgres
docker-run-postgres: volumes docker-network
	docker run --network $(DOCKER_NETWORK_NAME) --name $(DOCKER_POSTGRES_NAME) \
		-p 5432:5432 \
		-v $(POSTGRES_PERSISTENCE_DIR):/var/lib/postgresql/data \
		-e POSTGRES_DB=songbirdapi \
		-e POSTGRES_USER=songbirdapi \
		-e POSTGRES_PASSWORD=songbirdapi \
		-d postgres:16-alpine

.PHONY: docker-connect-postgres
docker-connect-postgres:
	docker exec -it $(DOCKER_POSTGRES_NAME) psql -U songbirdapi -d songbirdapi

.PHONY: docker-stop-postgres
docker-stop-postgres:
	docker kill $(DOCKER_POSTGRES_NAME) || true
	docker rm $(DOCKER_POSTGRES_NAME) || true

.PHONY: docker-clean-postgres
docker-clean-postgres:
	docker rm $(DOCKER_POSTGRES_NAME) || true

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
docker-run-all: docker-run-postgres docker-run-songbirdapi

.PHONY: docker-stop-all
docker-stop-all: docker-stop-postgres docker-stop-songbirdapi

.PHONY: docker-clean-all
docker-clean-all: docker-stop-all docker-clean-postgres docker-clean-songbirdapi

.PHONY: docker-dev
docker-dev: docker-clean-all docker-build docker-run-all
