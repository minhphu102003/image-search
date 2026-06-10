.PHONY: help install test lint format typecheck migrate migrate-new docker-up docker-down docker-build docker-logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ──

install: ## Install all deps (core + dev + ai)
	uv sync --extra dev --extra ai

install-core: ## Install core deps only
	uv sync

# ── Quality Gates ──

test: ## Run unit tests (skip integration that need DB/Redis)
	uv run pytest --ignore=tests/test_siglip_service.py --ignore=tests/test_models.py --ignore=tests/test_repositories.py --ignore=tests/test_redis_event_bus.py

test-all: ## Run all tests (needs local DB + Redis)
	uv run pytest

test-file: ## Run single test file (usage: make test-file F=tests/test_upload_api.py)
	uv run pytest $(F) -v

lint: ## Lint with ruff
	uv run ruff check src/ tests/

format: ## Format code with ruff
	uv run ruff format src/ tests/

format-check: ## Check formatting (CI mode)
	uv run ruff format --check src/ tests/

typecheck: ## Type check with mypy
	uv run mypy src/

check: lint format-check typecheck test ## Run all quality gates

# ── Database ──

migrate: ## Run pending migrations
	uv run alembic upgrade head

migrate-down: ## Rollback one migration
	uv run alembic downgrade -1

migrate-new: ## Create new migration (usage: make migrate-new M="description")
	uv run alembic revision --autogenerate -m "$(M)"

# ── Docker ──

docker-up: ## Start all services
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

docker-down-volumes: ## Stop and remove all data (destructive)
	docker compose down -v

docker-build: ## Rebuild images
	docker compose build

docker-logs: ## Tail logs for all services
	docker compose logs -f

docker-logs-api: ## Tail API logs
	docker compose logs -f api

docker-logs-worker: ## Tail worker logs
	docker compose logs -f worker

docker-restart: ## Rebuild and restart
	docker compose build && docker compose up -d

# ── Run Locally (without Docker) ──

run-api: ## Run API server locally
	uv run uvicorn image_search.adapters.input.app:app --host 0.0.0.0 --port 8000 --reload

run-worker: ## Run ingest worker locally
	uv run python -m image_search.adapters.input.ingest_worker

# ── Clean ──

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info
