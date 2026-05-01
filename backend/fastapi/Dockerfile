# ---- base ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy uv binary from official image (no pip install needed)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./

# ---- dev ----
FROM base AS dev
RUN uv sync --frozen
COPY . .
EXPOSE 8001

# ---- production ----
FROM base AS production
RUN uv sync --frozen --no-dev
COPY . .
EXPOSE 8001
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
