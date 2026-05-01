# ---- base ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy uv binary from official image (no pip install needed)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock* ./

# ---- dev ----
FROM base AS dev
RUN uv sync --frozen
COPY . .
EXPOSE 8000

# ---- production ----
FROM base AS production
RUN uv sync --frozen --no-dev
COPY . .
RUN uv run python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["uv", "run", "gunicorn", "devmind.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
