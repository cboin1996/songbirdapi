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
endif

# variables as a list, required for pytest targets
# in this makefile
ENV_VARS = $(shell cat $(ENV).env | xargs)

.PHONY: setup
setup:
	@echo sets up the development environment
	python3 -m venv venv
	@echo activate your venv with 'source venv/bin/activate'

# /app/data folder is legacy for backwards compatability
# from the times before songbird was split across
# core, cli and api.
.PHONY: volumesinit
volumesinit:
	mkdir -p ./$(APP_NAME)/data/dump
	mkdir -p ./$(APP_NAME)/data/local_chromium
	mkdir -p ./$(APP_NAME)/data/gdrive

.PHONY: volumesclean
volumesclean:
	rm -rf ./$(APP_NAME)/data/dump
	rm -rf ./$(APP_NAME)/data/local_chromium
	rm -rf ./$(APP_NAME)/data/gdrive

.PHONY: requirements
requirements:
	pip install black isort click
	pip install -r $(APP_NAME)/requirements.txt
	pip install -e ../songbirdcore

.PHONY: build
build:
	docker build -t $(APP_NAME):latest $(APP_NAME)

.PHONY: clean
clean:
	docker rm $(APP_NAME) || true

.PHONY: stop
stop:
	docker kill $(APP_NAME)

.PHONY: dev
dev: clean build run

lint:
	black $(APP_NAME)/.

test:
	$(ENV_VARS) python -m pytest test/unit -v