.PHONY: format lint typecheck test build verify up down seed-demo

# Verification environment, mirroring .github/workflows/ci.yml so that a green
# `make verify` means a green CI. Every value is overridable from the shell:
#
#   DATABASE_URL=postgresql+asyncpg://... make test
#
# Without these exported, `pytest` fails constructing Settings before it
# collects a single test, which reads as a broken suite rather than a missing
# environment — a failure recorded under Known Problems.
JWT_SECRET_KEY        ?= 01234567890123456789012345678901
DATABASE_URL          ?= postgresql+asyncpg://nexora_app:app_pw@127.0.0.1:5432/nexora_test
DATABASE_URL_SYNC     ?= postgresql+psycopg://nexora_app:app_pw@127.0.0.1:5432/nexora_test
DATABASE_OWNER_URL    ?= postgresql+psycopg://nexora_owner:owner_pw@127.0.0.1:5432/nexora_test
REDIS_URL             ?= redis://127.0.0.1:6379/0
CELERY_BROKER_URL     ?= redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND ?= redis://127.0.0.1:6379/2
BFF_REDIS_URL         ?= redis://127.0.0.1:6379/3

export JWT_SECRET_KEY DATABASE_URL DATABASE_URL_SYNC DATABASE_OWNER_URL
export REDIS_URL CELERY_BROKER_URL CELERY_RESULT_BACKEND BFF_REDIS_URL

format:
	cd backend && .venv/bin/ruff format .

lint:
	cd backend && .venv/bin/ruff format --check . && .venv/bin/ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && .venv/bin/mypy app
	cd frontend && npm run typecheck

# Coverage gate matches CI. Without it `make test` can pass while the
# backend-tests job fails on --cov-fail-under=80, which is exactly what
# happened at 61.91% in BUILD 9.
test:
	cd backend && .venv/bin/pytest --cov=app --cov-report=term-missing --cov-fail-under=80
	cd frontend && npm run test

build:
	cd frontend && npm run build

# Requires PostgreSQL and Redis reachable at the URLs above, with migrations
# applied: cd backend && .venv/bin/alembic upgrade head
verify: lint typecheck test build

up:
	docker compose up -d --build

down:
	docker compose down

# Idempotent — safe to re-run. Prints the demo login on completion.
seed-demo:
	cd backend && .venv/bin/python -m scripts.seed_demo
