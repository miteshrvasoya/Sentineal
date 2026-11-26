.PHONY: dev backend frontend test seed lint install tour-check migrate db-up db-down db-reset db-psql db-import openrouter-check refresh-symbols
install:
	cd backend && uv sync
	cd frontend && npm install --no-audit --no-fund
backend:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
frontend:
	cd frontend && npm run dev
dev:
	$(MAKE) -j2 backend frontend
test:
	cd backend && uv run pytest -q
	cd frontend && npx tsc --noEmit
lint:
	cd backend && uv run ruff check .
seed:
	cd backend && uv run python scripts/seed.py

tour-check:
	cd frontend && node e2e/tour-check.cjs

migrate:
	cd backend && uv run alembic upgrade head

# ---- database in Docker (only the database; backend and frontend run locally) ----
db-up:
	docker compose up -d --wait db
	@echo "PostgreSQL is ready. Put this in .env:  DATABASE_URL=postgresql+psycopg://quantlens:quantlens@127.0.0.1:5432/quantlens"
db-down:
	docker compose stop db
db-reset:
	docker compose down -v
db-psql:
	docker compose exec db psql -U quantlens -d quantlens
db-import:
	cd backend && uv run python scripts/sqlite_to_postgres.py

openrouter-check:
	cd backend && uv run python scripts/openrouter_best_free.py

refresh-symbols:
	cd backend && uv run python scripts/refresh_symbols.py
