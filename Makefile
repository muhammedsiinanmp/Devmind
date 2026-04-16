.PHONY: up down build logs shell-django shell-fastapi migrate test test-django test-fastapi lint format

# Start all services
up:
	docker compose up -d

# Stop all services
down:
	docker compose down

# Rebuild images
build:
	docker compose build

# Tail logs
logs:
	docker compose logs -f

# Django shell
shell-django:
	docker compose exec django poetry run python manage.py shell

# FastAPI shell
shell-fastapi:
	docker compose exec fastapi bash

# Run Django migrations
migrate:
	docker compose exec django poetry run python manage.py migrate

# Make Django migrations
makemigrations:
	docker compose exec django poetry run python manage.py makemigrations

# Run all tests
test: test-django test-fastapi

# Run Django tests
test-django:
	docker compose exec django poetry run pytest

# Run FastAPI tests
test-fastapi:
	docker compose exec fastapi poetry run pytest

# Lint everything
lint:
	cd backend/django && poetry run ruff check . && cd ../../backend/fastapi && poetry run ruff check .

# Format everything
format:
	cd backend/django && poetry run black . && poetry run ruff check . --fix && cd ../../backend/fastapi && poetry run black . && poetry run ruff check . --fix

# Create Django superuser
createsuperuser:
	docker compose exec django poetry run python manage.py createsuperuser

# View postgres
psql:
	docker compose exec postgres psql -U devmind -d devmind

# Flush redis
redis-flush:
	docker compose exec redis redis-cli FLUSHALL

# Full reset (nuclear option)
reset:
	docker compose down -v
	docker compose up -d
	sleep 5
	docker compose exec django poetry run python manage.py migrate
