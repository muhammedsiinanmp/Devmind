# ---- base ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1 \
    POETRY_VERSION=1.8.3

RUN pip install --no-cache-dir poetry==${POETRY_VERSION}

WORKDIR /app
COPY pyproject.toml poetry.lock* ./

# ---- dev ----
FROM base AS dev
RUN poetry install --no-root
COPY . .
EXPOSE 8000

# ---- production ----
FROM base AS production
RUN poetry install --no-root --only main
COPY . .
RUN poetry run python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["poetry", "run", "gunicorn", "devmind.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
