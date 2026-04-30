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
	ENV=$(or $(ENV),test) uv run pytest tests/integration -v

.PHONY: migrate
migrate:
	uv run alembic upgrade head

.PHONY: local-run
local-run:
	uv run uvicorn $(APP_NAME).server:app --host 0.0.0.0 --reload

.PHONY: local-run-no-reload
local-run-no-reload:
	uv run uvicorn $(APP_NAME).server:app --host 0.0.0.0

POSTGRES_PERSISTENCE_DIR=./data/postgres/
SONGBIRD_API_PERSISTENCE_DIR=./data/songbirdapi/
SONGBIRD_API_DOWNLOADS_DIR=$(SONGBIRD_API_PERSISTENCE_DIR)downloads

.PHONY: dev-wipe
dev-wipe:
	@echo "Wiping dev DB..."
	docker exec $(DOCKER_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'songbirdapi' AND pid <> pg_backend_pid();"
	docker exec $(DOCKER_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "DROP DATABASE IF EXISTS songbirdapi;"
	docker exec $(DOCKER_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "CREATE DATABASE songbirdapi;"
	@echo "Wiping file storage..."
	rm -rf ./data/artwork/* ./data/downloads/* ./data/songbirdapi/downloads/*
	@echo "Running migrations..."
	$(MAKE) migrate
	@echo "Done. Clear browser site data manually (DevTools → Application → Clear site data)."

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

# ----------------------------------------------------------------------------
# E2E parity harness — mirrors what test.yml does in CI:
#   - Fresh postgres on alt port (5433) so it doesn't collide with dev (5432)
#   - API on alt port (8001) so it doesn't collide with dev (8000)
#   - Reads e2e.env (alt DSN + cors_origins for next dev on :3001)
# Pair with songbirdweb's `make test-e2e-local` which talks to :8001 + :3001.
# Run `make e2e-up` once per session; `make e2e-reset` between suite runs to
# wipe DB state (mirrors the fresh postgres container per CI matrix job).
# ----------------------------------------------------------------------------

E2E_POSTGRES_NAME=$(APP_NAME)-e2e-postgres
E2E_API_PORT=8001
E2E_PG_PORT=5433
E2E_API_PIDFILE=/tmp/$(APP_NAME)-e2e-api.pid

.PHONY: e2e-postgres-up
e2e-postgres-up:
	@docker rm -f $(E2E_POSTGRES_NAME) >/dev/null 2>&1 || true
	docker run -d --rm --name $(E2E_POSTGRES_NAME) \
		-p $(E2E_PG_PORT):5432 \
		-e POSTGRES_DB=songbirdapi \
		-e POSTGRES_USER=songbirdapi \
		-e POSTGRES_PASSWORD=songbirdapi \
		postgres:17
	@echo "waiting for e2e postgres on :$(E2E_PG_PORT)..."
	@for i in $$(seq 1 30); do \
		docker exec $(E2E_POSTGRES_NAME) pg_isready -U songbirdapi >/dev/null 2>&1 && echo "ready" && exit 0; \
		sleep 1; \
	done; echo "postgres failed to start" && exit 1

.PHONY: e2e-migrate
e2e-migrate:
	ENV=e2e uv run alembic upgrade head

.PHONY: e2e-api-up
e2e-api-up:
	@if [ -f $(E2E_API_PIDFILE) ] && kill -0 $$(cat $(E2E_API_PIDFILE)) 2>/dev/null; then \
		echo "e2e api already running (pid $$(cat $(E2E_API_PIDFILE)))"; \
	else \
		echo "starting e2e api on :$(E2E_API_PORT)..."; \
		ENV=e2e nohup uv run uvicorn $(APP_NAME).server:app --host 0.0.0.0 --port $(E2E_API_PORT) > /tmp/$(APP_NAME)-e2e-api.log 2>&1 & echo $$! > $(E2E_API_PIDFILE); \
		for i in $$(seq 1 30); do \
			curl -sf http://localhost:$(E2E_API_PORT)/v1/health >/dev/null && echo "api ready" && exit 0; \
			sleep 1; \
		done; \
		echo "api failed to start — check /tmp/$(APP_NAME)-e2e-api.log" && exit 1; \
	fi

.PHONY: e2e-up
e2e-up: e2e-postgres-up e2e-migrate e2e-api-up
	@echo ""
	@echo "✓ e2e stack ready"
	@echo "  postgres: localhost:$(E2E_PG_PORT)"
	@echo "  api:      localhost:$(E2E_API_PORT)"
	@echo "  logs:     /tmp/$(APP_NAME)-e2e-api.log"
	@echo ""
	@echo "next: cd ../songbirdweb && make test-e2e-local"

.PHONY: e2e-reset
e2e-reset:
	@echo "wiping e2e DB..."
	@docker exec $(E2E_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'songbirdapi' AND pid <> pg_backend_pid();" >/dev/null
	@docker exec $(E2E_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "DROP DATABASE IF EXISTS songbirdapi;"
	@docker exec $(E2E_POSTGRES_NAME) psql -U songbirdapi -d postgres -c "CREATE DATABASE songbirdapi;"
	$(MAKE) e2e-migrate
	@echo "✓ e2e db reset"
	@if [ -f $(E2E_API_PIDFILE) ] && kill -0 $$(cat $(E2E_API_PIDFILE)) 2>/dev/null; then \
		echo "restarting e2e api to clear connection pool..."; \
		kill $$(cat $(E2E_API_PIDFILE)); rm -f $(E2E_API_PIDFILE); \
		$(MAKE) e2e-api-up; \
	fi

.PHONY: e2e-down
e2e-down:
	@if [ -f $(E2E_API_PIDFILE) ]; then \
		kill $$(cat $(E2E_API_PIDFILE)) 2>/dev/null || true; rm -f $(E2E_API_PIDFILE); \
		echo "stopped e2e api"; \
	fi
	@docker rm -f $(E2E_POSTGRES_NAME) >/dev/null 2>&1 || true
	@echo "✓ e2e stack down"
