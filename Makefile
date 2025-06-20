APP_NAME=songbirdapi
.PHONY: env
env:
# check ENV env var has been set
ifndef ENV
	$(error Must set ENV variable!)
endif
# load env vars from .env file if present
ifneq ("$(wildcard $(ENV).env)", "")
	@echo "Loading configuration from $(ENV).env"
# include cannot be indented
include $(ENV).env
else
	@echo "Continuing without .env file."
	@echo "Creating template $(ENV).env file"
# conditionally setup env based on app choice via APP_NAME env var.
	echo 'RUN_LOCAL=false' > $(ENV).env
endif

# variables as a list, required for pytest targets
# in this makefile
ENV_VARS = $(shell cat $(ENV).env | xargs)

.PHONY: setup
setup:
	@echo sets up the development environment
	python3 -m venv venv
	@echo activate your venv with 'source venv/bin/activate'

.PHONY: requirements
requirements:
	pip install black isort click
	pip install -r $(APP_NAME)/requirements.txt

local-run-songbirdapi:
	uvicorn $(APP_NAME).server:app --host 0.0.0.0

VALKEY_PERSISTENCE_DIR=./data/redis/
SONGBIRD_API_PERSISTENCE_DIR=./data/songbirdapi/
SONGBIRD_API_DOWNLOADS_DIR=$(SONGBIRD_API_PERSISTENCE_DIR)/downloads
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
docker-network:
	docker network create $(DOCKER_NETWORK_NAME) || true

.PHONY: run-redis
docker-run-redis: volumes docker-network
	@echo starting redis
	# TODO: turn on persistence, and validate it works
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
	docker network rm $(APP_NAME)

.PHONY: docker-stop-songbirdapi
docker-stop-songbirdapi:
	docker kill $(APP_NAME) || true
	docker rm $(APP_NAME) || true

.PHONY: docker-run-all
docker-run-all: docker-run-redis docker-run-songbirdapi

.PHONY: docker-clean-all
docker-clean-all: docker-stop-all docker-clean-redis docker-clean-songbirdapi

.PHONY: docker-stop-all
docker-stop-all: docker-stop-redis docker-stop-songbirdapi

.PHONY: docker-dev
docker-dev: docker-clean-all docker-build-all docker-run-all

lint:
	black $(APP_NAME)/.

test:
	$(ENV_VARS) python -m pytest test/unit -v
