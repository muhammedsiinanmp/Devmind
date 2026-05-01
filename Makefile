# ─── Infrastructure ───────────────────────────────────────────
up:
	docker compose up -d
down:
	docker compose down
build:
	docker compose build
logs:
	docker compose logs -f
reset:
	docker compose down -v && docker compose up -d

# ─── Shell Access ──────────────────────────────────────────────
shell-django:
	docker compose exec django bash
shell-fastapi:
	docker compose exec fastapi bash
shell-analytics:
	docker compose exec analytics bash
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
test:
	docker compose exec django uv run pytest --cov --cov-fail-under=95
test-django:
	docker compose exec django uv run pytest backend/django/ --cov --cov-fail-under=95
test-fastapi:
	docker compose exec fastapi uv run pytest backend/fastapi/ --cov --cov-fail-under=90
test-analytics:
	docker compose exec analytics uv run pytest backend/analytics/ --cov --cov-fail-under=90
test-all:
	make test-django & make test-fastapi & make test-analytics

# ─── Code Quality ─────────────────────────────────────────────
format:
	docker compose exec django uv run black .

# ─── Kafka ────────────────────────────────────────────────────
kafka-topics:
	confluent kafka topic list
kafka-consume:
	confluent kafka topic consume $(topic) --from-beginning

# ─── Lambda ───────────────────────────────────────────────────
lambda-deploy:
	cd lambda/$(function) && zip -r function.zip . && aws lambda update-function-code --function-name $(function) --zip-file fileb://function.zip

# ─── Terraform ────────────────────────────────────────────────
terraform-plan:
	cd infra/terraform/aws && terraform plan
terraform-apply:
	cd infra/terraform/aws && terraform apply -auto-approve

# ─── Frontend ─────────────────────────────────────────────────
frontend-dev:
	cd frontend && pnpm dev

# ─── Observability ────────────────────────────────────────────
grafana-open:
	open https://devmind.grafana.net/dashboards

# ─── Development Utilities ────────────────────────────────────
ngrok:
	ngrok http 8000
seed:
	docker compose exec django uv run python manage.py seed_demo_data
demo:
	docker compose down -v && docker compose up -d && sleep 10 && make migrate && make seed
