.PHONY: dev backend frontend test seed lint install
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
