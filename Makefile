# ─── Infrastructure ───────────────────────────────────────────
# up: app stack (migrations run first). up-ops: also Flower, Prometheus, Grafana.
up:
	docker compose up -d
up-ops:
	docker compose --profile ops up -d
down:
	docker compose --profile ops down
build:
	docker compose build
logs:
	docker compose logs -f
reset:
	docker compose --profile ops down -v && docker compose up -d

# ─── Shell Access ──────────────────────────────────────────────
shell-django:
	docker compose exec django bash
shell-fastapi:
	docker compose exec fastapi bash
psql:
	docker compose exec postgres psql -U devmind
redis-flush:
	docker compose exec redis redis-cli FLUSHDB

# ─── Django Management ────────────────────────────────────────
migrate:
	docker compose exec django uv run python manage.py migrate
makemigrations:
	docker compose exec django uv run python manage.py makemigrations
createsuperuser:
	docker compose exec django uv run python manage.py createsuperuser

# ─── Testing ──────────────────────────────────────────────────
# Same test commands as CI (.github/workflows/ci.yml), run inside the containers
test: test-django test-fastapi
test-django:
	docker compose exec -e DJANGO_ALLOW_ASYNC_UNSAFE=1 django uv run pytest --cov
test-fastapi:
	docker compose exec fastapi uv run pytest
test-all: test

# ─── Code Quality ─────────────────────────────────────────────
format:
	docker compose exec django uv run black .

# ─── Frontend ─────────────────────────────────────────────────
frontend-dev:
	cd frontend && pnpm dev

# ─── Observability ────────────────────────────────────────────
grafana-open:
	open http://localhost:3000
prometheus-open:
	open http://localhost:9090
grafana-logs:
	docker compose logs -f grafana
prometheus-logs:
	docker compose logs -f prometheus
prometheus-targets:
	@echo "Prometheus targets status:" && curl -s http://localhost:9090/api/v1/targets | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  {t[\"labels\"][\"job\"]}: {t[\"health\"]}') for t in d['data']['activeTargets']]"

# ─── Development Utilities ────────────────────────────────────
ngrok:
	ngrok http 8000
