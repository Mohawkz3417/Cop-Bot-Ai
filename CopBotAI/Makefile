.PHONY: install dev run test lint clean docker-build docker-up freeze

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev: install
	$(PIP) install -r requirements-dev.txt

run:
	$(PY) -m backend.main

test: dev
	$(VENV)/bin/pytest

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -f data/copbot_history.db

docker-build:
	docker compose build

docker-up:
	docker compose up

freeze:
	$(PIP) freeze > requirements.lock.txt
