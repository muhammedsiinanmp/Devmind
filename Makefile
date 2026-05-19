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
	docker compose exec -e DJANGO_ALLOW_ASYNC_UNSAFE=1 django uv run pytest --cov --cov-fail-under=90
test-fastapi:
	docker compose exec fastapi uv run pytest --cov --cov-fail-under=90
test-all:
	make test-django && make test-fastapi

# ─── Code Quality ─────────────────────────────────────────────
format:
	docker compose exec django uv run black .

# ─── Kafka ────────────────────────────────────────────────────
kafka-topics:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
kafka-create-topics:
	@echo "Creating DevMind Kafka topics..."
	@for topic in devmind.pr.opened devmind.pr.merged devmind.review.requested devmind.review.completed devmind.repo.indexed devmind.cve.detected devmind.digest.generate; do \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic $$topic --partitions 1 --replication-factor 1 --if-not-exists; \
	done
	@echo "All topics created."
kafka-consume:
	docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic $(topic) --from-beginning

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
seed:
	docker compose exec django uv run python manage.py seed_demo_data
demo:
	docker compose down -v && docker compose up -d && sleep 10 && make migrate && make seed
