.PHONY: check db-up migrate-check

check:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .
	uv run --frozen mypy src tests scripts
	uv run --frozen python manage.py check
	uv run --frozen python scripts/check_docs.py

db-up:
	docker compose up --detach --wait db

migrate-check:
	uv run --frozen python scripts/migrate_check.py
