.PHONY: dev test lint build gate

dev:
	uv sync --frozen
	pnpm --dir frontend install --frozen-lockfile
	pnpm --dir frontend build
	uv run --no-env-file uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

test:
	uv sync --frozen
	uv run --no-env-file pytest
	pnpm --dir frontend install --frozen-lockfile
	pnpm --dir frontend test

lint:
	uv sync --frozen
	uv run --no-env-file ruff check backend
	uv run --no-env-file ruff format --check backend
	pnpm --dir frontend install --frozen-lockfile
	pnpm --dir frontend lint

build:
	docker compose --env-file .env.example build

gate:
	uv run --no-env-file python scripts/phase_gate.py
