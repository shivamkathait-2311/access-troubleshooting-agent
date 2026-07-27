.PHONY: install run worker test lint fmt typecheck compose-up compose-down migrate

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	uv run arq app.workers.self_diagnosis_worker.WorkerSettings

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

typecheck:
	uv run mypy app

compose-up:
	docker compose up -d

compose-down:
	docker compose down

migrate:
	uv run alembic upgrade head
