.PHONY: format lint typecheck test build verify up down

format:
	cd backend && .venv/bin/ruff format .

lint:
	cd backend && .venv/bin/ruff format --check . && .venv/bin/ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && .venv/bin/mypy app
	cd frontend && npm run typecheck

test:
	cd backend && .venv/bin/pytest
	cd frontend && npm run test

build:
	cd frontend && npm run build

verify: lint typecheck test build

up:
	docker compose up -d --build

down:
	docker compose down
