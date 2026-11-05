# Engineering Guide

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration](#2-environment-configuration)
3. [Local Development Setup](#3-local-development-setup)
4. [Service Ports Reference](#4-service-ports-reference)
5. [Development Workflows](#5-development-workflows)
6. [API Reference](#6-api-reference)
7. [Testing](#7-testing)
8. [Deployment Notes](#8-deployment-notes)
9. [Troubleshooting Runbook](#9-troubleshooting-runbook)
10. [Known Gaps](#10-known-gaps)

---

## 1. Prerequisites

| Tool | Version used in this repo | Purpose |
|---|---|---|
| Docker + Compose v2 | - | Runs the backend stack (`docker-compose.yml`) |
| Node.js + pnpm | Node 20, pnpm 9 (CI and `frontend/Dockerfile`) | Frontend dev server and build |
| Python + `uv` | Python 3.12 (`.python-version`: 3.12.4) | Running backend tests outside Docker |
| GitHub OAuth App | - | Client ID + secret for login |

The backend containers install their own Python and `uv`. You need local Python and `uv` only to run tests outside Docker.

---

## 2. Environment Configuration

Copy `.env.example` to `.env`. Compose passes the file to every backend container (`env_file: .env`). Django also reads it directly (`environ.Env.read_env` in `devmind/settings/base.py`), and so does FastAPI (pydantic-settings, `../../.env` by default; override with `DEVMIND_ENV_FILE`, or set it to an empty string to turn it off).

### Required

| Variable | Read by | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django | Django `SECRET_KEY`, required. Also the master secret for encrypting GitHub tokens and BYOK keys (Fernet key derived with HKDF in `apps/accounts/encryption.py`). Changing it makes stored encrypted values unreadable. Generate with `python -c "import secrets; print(secrets.token_hex(50))"`. |
| `JWT_SECRET_KEY` | Django | Required. Signs access and refresh tokens. |
| `DATABASE_URL` | Django | Required. Template value: `postgresql://devmind:devmind_secret@postgres:5432/devmind` |
| `FASTAPI_INTERNAL_SECRET` | Django, FastAPI | Shared secret sent as `X-Internal-Secret`. If it's empty, FastAPI rejects every work request with 403 and Django's internal BYOK endpoint returns 403. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Django | GitHub OAuth App credentials |
| `GITHUB_WEBHOOK_SECRET` | Django | HMAC key for webhook signatures. If it's empty, every webhook is rejected with 403. |

There's no `FERNET_KEY` variable. The encryption key comes from `DJANGO_SECRET_KEY`.

### LLM providers (FastAPI): set at least one, or configure BYOK keys

| Variable | Description |
|---|---|
| `GOOGLE_AI_API_KEY` | Google AI Studio key. Used for `gemini-2.0-flash` (first server provider) and for `text-embedding-004` embeddings. |
| `GROQ_API_KEY` | Groq key for `llama-3.3-70b-versatile` (second) |
| `GITHUB_TOKEN` | GitHub token with access to GitHub Models, for `gpt-4o-mini` (third) |
| `LLM_FAILOVER_ENABLED` | Default `True`. When `False`, only the first provider in the chain is tried. |

There's no server-side OpenAI provider. OpenAI keys can be added per user through the BYOK settings.

### Infrastructure and URLs

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Django cache (OAuth state), Channels layer, FastAPI rate limiter |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery results |
| `FASTAPI_BASE_URL` | `http://fastapi:8001` | Where the Celery worker reaches FastAPI |
| `FASTAPI_TIMEOUT_SECONDS` | `60` | HTTP timeout for worker-to-FastAPI calls |
| `FASTAPI_DATABASE_URL` | `postgresql+asyncpg://devmind:devmind_secret@postgres:5432/devmind` | FastAPI's async database URL |
| `DJANGO_BASE_URL` | `http://django:8000` | Where FastAPI fetches BYOK configs from |
| `DEVMIND_PUBLIC_URL` | `http://localhost:8000` | Base for the webhook URL registered on GitHub (`<url>/api/v1/webhooks/github/`) and for organization invite links |
| `FRONTEND_URL` | `http://localhost:5173` | Read into settings. No code uses it currently. The OAuth redirect is whatever callback URL the GitHub OAuth App has configured. |

### Django tunables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_DEBUG` | `False` | Used by base settings. `development.py` forces `DEBUG=True` regardless. |
| `DJANGO_ALLOWED_HOSTS` | `localhost` | Used by base settings. `development.py` sets `["*"]`. |
| `DJANGO_CORS_ORIGINS` | `http://localhost:5173` | CORS allow-list |
| `API_GLOBAL_RATE_LIMIT` | `1000` | Authenticated requests per hour (DRF throttle; off in development and test settings) |
| `REVIEW_RATE_LIMIT_PER_HOUR` | `20` | Read into settings but not enforced anywhere |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm |

### Optional integrations

| Variable | Description |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | If both are set, the orchestrator pushes review status changes to Supabase. Leave empty to turn it off. |
| `SENTRY_DSN_DJANGO`, `SENTRY_DSN_FASTAPI` | Empty in `.env.example`, so Sentry is off by default. Set a DSN to enable it for that service. |
| `SENTRY_ENVIRONMENT` | Sentry environment tag. When it's `production`, FastAPI turns off `/docs`. |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password, used by compose interpolation; `devmind` if unset |

`AWS_REGION`, `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` appear in `.env.example`, but no code reads them.

---

## 3. Local Development Setup

### Step 1: Configure

```bash
git clone https://github.com/muhammedsiinanmp/Devmind.git
cd Devmind
cp .env.example .env
# Fill in the "Required" variables above and at least one LLM key.
# Sentry is off by default; set SENTRY_DSN_DJANGO / SENTRY_DSN_FASTAPI to enable it.
```

### Step 2: Start the backend stack

```bash
docker compose up -d --build      # or: make build && make up
```

### Step 3: Migrate

```bash
docker compose exec django uv run python manage.py migrate    # or: make migrate
```

### Step 4: Enable pgvector

```bash
docker compose exec postgres psql -U devmind -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Until you run this, FastAPI `GET /health` returns 503 (`pgvector: error: extension not installed`). The embedding tables still won't exist afterwards; see [Known Gaps](#10-known-gaps).

### Step 5: Configure the GitHub OAuth App

In GitHub, go to Settings, then Developer settings, then OAuth Apps:

| Field | Value |
|---|---|
| Homepage URL | `http://localhost:5173` |
| Authorization callback URL | `http://localhost:5173/auth/callback` |

### Step 6: Start the frontend

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev            # http://localhost:5173 (or: make frontend-dev)
```

The Vite dev server proxies `/api` to `http://localhost:8000` (`frontend/vite.config.ts`).

### Step 7 (optional): Receive webhooks locally

GitHub can't reach `localhost`. Start a tunnel to Django:

```bash
make ngrok          # runs: ngrok http 8000
```

Set `DEVMIND_PUBLIC_URL` to the https tunnel URL, then run `docker compose restart django celery_worker`. Webhooks are installed when repositories sync (`POST /api/v1/repositories/connect/`).

**Warning:** the compose stack runs Django with `devmind.settings.development` (the default in `manage.py` and `devmind/celery.py`). That means `DEBUG=True`, `ALLOWED_HOSTS=["*"]` and no throttling. A tunnel makes that development server public, so keep it up only while testing, and never point it at real data.

---

## 4. Service Ports Reference

| Service | Host port | Notes |
|---|---|---|
| Nginx | 80 | Proxies `/`, `/health/`, `/metrics` to Django and `/fastapi-metrics` to FastAPI |
| Django | 8000 | `runserver` (development settings) |
| FastAPI | 8001 | Published by compose. `/health`, `/metrics` and `/docs` are open; work routes need `X-Internal-Secret`. |
| PostgreSQL | 5432 | user `devmind`, password `devmind_secret`, db `devmind` |
| Redis | 6379 | |
| Flower | 5555 | Uses the same `CELERY_BROKER_URL` as the worker (`redis://redis:6379/1` in the template) |
| Prometheus | 9090 | |
| Grafana | 3000 | User `admin`, password from `GRAFANA_ADMIN_PASSWORD` (default `devmind`). Provisions the "DevMind Overview" dashboard. |
| Frontend | 5173 | Vite dev server; not in compose |

---

## 5. Development Workflows

### Make targets

| Target | Command |
|---|---|
| `up` / `down` / `build` / `logs` / `reset` | `docker compose up -d`, `down`, `build`, `logs -f`, `down -v && up -d` |
| `shell-django` / `shell-fastapi` | bash inside the container |
| `psql` / `redis-flush` | Postgres shell / `FLUSHDB` |
| `migrate` / `makemigrations` / `createsuperuser` | Django management commands in the container |
| `test` (`test-all`) / `test-django` / `test-fastapi` | Backend test suites in the containers |
| `format` | `black .` in the Django container |
| `frontend-dev` | `cd frontend && pnpm dev` |
| `grafana-open` / `prometheus-open` / `prometheus-targets` | Observability helpers |
| `ngrok` | `ngrok http 8000` |

### Django management commands

```bash
docker compose exec django uv run python manage.py <command>
# e.g. shell, makemigrations <app>, migrate, showmigrations, createsuperuser
```

### Logs

```bash
docker compose logs -f django
docker compose logs -f fastapi
docker compose logs -f celery_worker
```

### Re-running a review

No API route creates a review by hand. Reviews start from webhooks. To run one again, retrigger it. This works only when the review is `pending` or `failed`:

```bash
curl -X POST http://localhost:8000/api/v1/reviews/<id>/retrigger/ \
  -H "Authorization: Bearer <access_jwt>"
```

### Inspecting Celery

```bash
docker compose exec celery_worker uv run celery -A devmind inspect active
docker compose exec celery_worker uv run celery -A devmind inspect active_queues
docker compose exec celery_worker uv run celery -A devmind inspect stats
```

### PostgreSQL

```bash
docker compose exec postgres psql -U devmind -d devmind
-- SELECT id, status, risk_score, created_at FROM reviews_review ORDER BY created_at DESC LIMIT 10;
-- SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

### Adding a Python dependency

```bash
docker compose exec django uv add <package>     # then rebuild django and celery_worker
docker compose exec fastapi uv add <package>    # then rebuild fastapi
```

Both containers mount the source directory, so `pyproject.toml` and `uv.lock` change on the host as well.

---

## 6. API Reference

Interactive schema: `http://localhost:8000/api/schema/swagger-ui/` (also `/api/schema/redoc/` and the raw `/api/schema/`).

All Django routes need `Authorization: Bearer <access_jwt>` unless marked otherwise. Paths are relative to `/api/v1/`.

`devmind/urls.py` mounts `apps/accounts/urls.py` under both `auth/` and `settings/`, so each accounts route answers under both prefixes. The tables below show the prefix the frontend uses.

### Auth

| Endpoint | Method | Description |
|---|---|---|
| `auth/github/start/` | GET | No auth. Returns `{authorize_url}` and stores a single-use state in the cache for 10 minutes. |
| `auth/github/callback/?code=&state=` | GET | No auth. Validates the state, exchanges the code and returns `{access, refresh}`. |
| `auth/token/refresh/` | POST | SimpleJWT refresh (rotates and blacklists the old refresh token) |
| `auth/logout/` | POST | Blacklists the given refresh token |
| `auth/me/` | GET | Current user profile |
| `auth/github/token/` | GET | Returns the user's **decrypted** GitHub access token |

### Repositories

| Endpoint | Method | Description |
|---|---|---|
| `repositories/` | GET | User's active repositories; `?review_enabled=true` filter |
| `repositories/<id>/` | GET, PATCH | Detail; PATCH updates `review_enabled` and `default_branch` |
| `repositories/connect/` | POST | Queues a GitHub repository sync, which installs webhooks on new repos (202) |
| `repositories/<id>/scan/` | POST | Queues a full-repository scan. Limited to one per repository per 24 hours (429 with `retry_after`). |

### Reviews and scans

| Endpoint | Method | Description |
|---|---|---|
| `reviews/` | GET | Paginated (20 per page). Filters `status`, `repository`; `search` over PR title and repo name; `ordering` by `created_at`, `risk_score`, `status`; `detail=true` returns full objects. |
| `reviews/<id>/` | GET | Review with nested comments and run (owner only) |
| `reviews/<id>/retrigger/` | POST | Re-queue a `pending`/`failed` review (409 if processing, 400 if completed) |
| `reviews/scans/<id>/` | GET | Scan status |

### LLM settings (BYOK)

| Endpoint | Method | Description |
|---|---|---|
| `settings/llm/` | GET, POST | List and create configs. Create validates the key with a live `GET /models` call. |
| `settings/llm/test/` | POST | Validate a key without saving |
| `settings/llm/<id>/` | GET, PATCH, DELETE | Manage one config |
| `settings/llm/<id>/set_default/` | POST | Set priority 0 and bump the others (`POST settings/llm/<id>/` does the same) |

### Organizations

| Endpoint | Description |
|---|---|
| `organizations/` | Create an organization |
| `organizations/<id>/` | Organization detail |
| `organizations/<org_id>/invite/` | Invite a member (queues an invite email) |
| `organizations/<org_id>/members/` | List members |
| `organizations/<org_id>/members/<user_id>/` | Remove a member |
| `organizations/invite/accept/` | Accept an invite |

See `apps/organizations/views.py` for methods and permissions.

### Webhook and internal

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `webhooks/github/` | POST | HMAC `X-Hub-Signature-256` | GitHub webhook receiver; 403 on a bad or missing signature, or when no secret is configured |
| `auth/internal/llm-configs/?user_id=` | GET | `X-Internal-Secret` | Active BYOK configs with decrypted keys, for FastAPI |

### Health and metrics (outside `/api/v1/`)

| Endpoint | Description |
|---|---|
| `GET /health/` | DB and Redis status. Always HTTP 200. |
| `GET /metrics` | django-prometheus |

### FastAPI (port 8001)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/review/analyze` | POST | `X-Internal-Secret` | Run the retrieval steps and review agent. Returns comments, risk score, model, provider and latency. |
| `/embeddings/store` | POST | `X-Internal-Secret` | Store a code embedding |
| `/embeddings/search` | POST, GET | `X-Internal-Secret` | Similarity search |
| `/scan/full` | POST | `X-Internal-Secret` | Start a background repository scan (202) |
| `/scan/status/{scan_id}` | GET | `X-Internal-Secret` | Scan progress (in-process memory) |
| `/scan/report/{scan_id}` | GET | `X-Internal-Secret` | Scan report |
| `/health` | GET | none | DB, pgvector and provider reachability; 503 if DB or pgvector check fails |
| `/metrics` | GET | none | Prometheus instrumentator |
| `/docs` | GET | none | OpenAPI UI (off when `SENTRY_ENVIRONMENT=production`) |

### WebSocket (not currently served)

`realtime/routing.py` defines `ws/reviews/<review_id>/?token=<access_jwt>` and `ws/notifications/`, but no ASGI server is configured. See [SYSTEM_ARCHITECTURE.md, WebSocket status](SYSTEM_ARCHITECTURE.md#websocket-status). The frontend's `ReviewStatus` component tries to connect and falls back to a static view if it can't.

---

## 7. Testing

### Django

Django tests need PostgreSQL and Redis. `pytest` uses `devmind.settings.test` (configured in `pyproject.toml`).

```bash
cd backend/django
uv sync --frozen
DJANGO_SECRET_KEY=dev JWT_SECRET_KEY=dev \
DATABASE_URL=postgresql://devmind:devmind_secret@localhost:5432/devmind \
REDIS_URL=redis://localhost:6379/0 DJANGO_ALLOW_ASYNC_UNSAFE=1 \
uv run pytest --cov

# Inside the running stack:
make test-django
```

`devmind/settings/test.py` sets Celery to eager mode (`CELERY_TASK_ALWAYS_EAGER`), uses an in-memory channel layer, the MD5 password hasher and no throttling, turns off Sentry and Supabase, and sets `SKIP_LLM_KEY_VALIDATION=True`. The cache is still django-redis, which is why Redis must be running.

Test modules:

| Area | Files |
|---|---|
| Accounts | `apps/accounts/tests/test_views.py`, `test_oauth.py`, `test_byok.py`, `test_base_url_ssrf.py`, `test_url_safety.py`, `test_models.py` |
| Repositories | `apps/repositories/tests/test_webhooks.py`, `test_views.py`, `test_tasks.py`, `test_services.py`, `test_models.py`, `test_managers.py`, `test_admin.py` |
| Reviews | `apps/reviews/tests/test_orchestrator.py`, `test_views.py`, `test_github_poster.py`, `test_models.py` |
| Organizations | `apps/organizations/tests/test_views.py` |
| Realtime | `realtime/tests/test_consumers.py` |
| End to end | `tests/test_e2e.py` |

### FastAPI

FastAPI tests need no external services. `backend/fastapi/conftest.py` sets `DEVMIND_ENV_FILE=""` and fake keys before the app is imported, so a real `.env` is never read.

```bash
cd backend/fastapi
uv sync --frozen
uv run pytest            # pyproject addopts include --cov

# Inside the running stack:
make test-fastapi
```

The tests in `backend/fastapi/tests/` cover the agent, diff parser, prompt builder, LLM client, rate limiter (with `fakeredis`), vector store, review/embeddings/scan/health routers and internal-secret enforcement.

### Frontend

The frontend has no automated tests. CI runs:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm exec tsc -p tsconfig.app.json --noEmit
pnpm build
pnpm lint
```

### Measured results

These were measured locally on this branch. Coverage method: `pytest --cov`, then `coverage report --omit='*/tests/*,*/migrations/*,*conftest.py'`, so test files, migrations and conftest are excluded. Including the test files would give a higher figure.

| Suite | Result | Line coverage |
|---|---|---|
| Django | 244 passed | 83% |
| FastAPI | 176 passed | 80% |
| Frontend | `tsc`, `build` pass; `lint` 0 errors, 3 warnings | n/a |

### CI

`.github/workflows/ci.yml` runs on pushes to `main` and `dev` and on all pull requests:

- **Django (pytest):** Postgres (`pgvector/pgvector:pg16`) and Redis service containers; `ruff check`, `black --check`, `makemigrations --check --dry-run`, `pytest --cov`
- **FastAPI (pytest):** `ruff check`, `black --check`, `pytest`
- **Frontend (typecheck, build, lint):** pnpm 9 and Node 20; `tsc`, `pnpm build`, `pnpm lint`

CI doesn't enforce a coverage threshold.

---

## 8. Deployment Notes

The repo doesn't include deployment infrastructure (no Terraform, Helm or Kubernetes manifests) or a production compose file. The facts below come from the code.

- **Django image:** the `production` target of `backend/django/Dockerfile` runs `uv sync --frozen --no-dev` and `collectstatic`, and starts `gunicorn devmind.wsgi:application --workers 4`. WhiteNoise serves static files.
- **Settings:** `devmind/wsgi.py` and `devmind/asgi.py` default to `devmind.settings.production`. That file sets `DEBUG=False`, `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, secure session and CSRF cookies, and HSTS for one year with subdomains and preload. `manage.py` and `devmind/celery.py` default to `devmind.settings.development`, so set `DJANGO_SETTINGS_MODULE=devmind.settings.production` explicitly for Celery and management commands in production.
- **FastAPI image:** see `backend/fastapi/Dockerfile`.
- **Frontend image:** the `production-serve` target of `frontend/Dockerfile` builds the app and serves `dist/` with `nginx:alpine`.

### Checklist

- [ ] Set `DJANGO_SETTINGS_MODULE=devmind.settings.production` for web and worker
- [ ] Set `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ORIGINS` and `DEVMIND_PUBLIC_URL` for your domains
- [ ] Use strong random values for `DJANGO_SECRET_KEY`, `JWT_SECRET_KEY` and `FASTAPI_INTERNAL_SECRET`, and set `GITHUB_WEBHOOK_SECRET`
- [ ] Treat `DJANGO_SECRET_KEY` as the encryption key: rotating it makes stored tokens and API keys unreadable
- [ ] Don't publish FastAPI's port; only the Celery workers need to reach it
- [ ] Enable the `vector` extension and create the embedding tables (see [Known Gaps](#10-known-gaps))
- [ ] Run `migrate` before starting new code that depends on schema changes
- [ ] Set `SENTRY_DSN_*` and `SENTRY_ENVIRONMENT=production` (this also turns off FastAPI `/docs`)

### Scaling levers in the code

| Concern | Lever |
|---|---|
| Review throughput | More `celery_worker` processes or replicas |
| AI service | More uvicorn workers or replicas; the LLM rate limit is shared through Redis |
| Database connections | Django `conn_max_age=600` with health checks; FastAPI's pool settings are in `core/database.py` |
| LLM limits | More server providers, or user BYOK keys |

---

## 9. Troubleshooting Runbook

### FastAPI `/health` returns 503 with `pgvector: error: extension not installed`

```bash
docker compose exec postgres psql -U devmind -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Review stuck in `processing`

The worker probably died mid-task (`trigger_review_task` doesn't use `acks_late`).

```bash
docker compose logs celery_worker --tail=200 | grep "review_id=<id>"
```

Retrigger only accepts `pending`/`failed` reviews, so reset the status first:

```bash
docker compose exec django uv run python manage.py shell -c "
from apps.reviews.models import Review
Review.objects.filter(pk=<id>).update(status='failed')
"
curl -X POST http://localhost:8000/api/v1/reviews/<id>/retrigger/ -H "Authorization: Bearer <jwt>"
```

### Review failed with "FastAPI rejected the request with 403"

`FASTAPI_INTERNAL_SECRET` is empty or differs between Django and FastAPI. Both read the root `.env`. Fix it, then:

```bash
docker compose restart django fastapi celery_worker
```

### Review failed with "LLM providers rate limited (429)"

FastAPI raised `AllProvidersDownError`: every provider in the chain returned 429, 5xx, a non-200 response or timed out, or no provider is configured. Check that at least one of `GOOGLE_AI_API_KEY`, `GROQ_API_KEY` or `GITHUB_TOKEN` is set, or that the user has an active BYOK config. Then look at:

```bash
docker compose logs fastapi | grep "llm\."
```

### Reviews complete but nothing appears on GitHub

```bash
docker compose logs celery_worker | grep "github_poster\|github_comments"
docker compose exec django uv run python manage.py shell -c "
from apps.reviews.models import Review
print(Review.objects.get(pk=<id>).comments.count())
"
```

A 422 on inline comments triggers a body-only retry. A zero comment count means FastAPI returned no findings.

### Webhooks don't trigger reviews

Possible causes:

1. `GITHUB_WEBHOOK_SECRET` is empty, or differs from the secret on the GitHub hook (Django logs `webhook.secret.not_configured` or `webhook.signature.mismatch`).
2. The repo isn't in DevMind, is inactive or has `review_enabled=False` (`webhook.pr.unknown_repository` / `webhook.pr.review_disabled`).
3. The hook points to the wrong URL. `DEVMIND_PUBLIC_URL` must be reachable from GitHub.

```bash
docker compose exec django uv run python manage.py shell -c "
from apps.repositories.models import Repository
for r in Repository.objects.all(): print(r.full_name, r.webhook_id, r.review_enabled)
"
docker compose logs django | grep webhook
```

Recent deliveries appear in GitHub under the repo's Settings, Webhooks.

### Grafana dashboard shows no data

The "DevMind Overview" dashboard charts django-prometheus and prometheus-fastapi-instrumentator request rate and latency, plus FastAPI's `rag_pipeline_duration_ms`, `agent_iterations_total` and `review_errors_total`. Check that Prometheus can scrape both apps through Nginx:

```bash
make prometheus-targets    # django and fastapi should be "up"
```

The three review panels stay empty until `POST /review/analyze` has been called, and `review_errors_total` has no series until the first review error.

### Redis connection refused

```bash
docker compose ps redis
docker compose exec redis redis-cli ping    # PONG
docker compose restart redis
```

---

## 10. Known Gaps

These gaps are confirmed in the current code.

### WebSockets are not served

The Channels consumers, routing and JWT query middleware exist and are tested. However, `ASGI_APPLICATION` isn't set, `daphne` isn't in `INSTALLED_APPS`, the production image runs gunicorn on WSGI, and Nginx has no upgrade block. `ReviewStatusConsumer` also doesn't check that the user owns the review. Add that check before serving it.

### pgvector schema is never created

Nothing enables the `vector` extension or creates `code_embeddings` / `review_embeddings` (FastAPI never calls `create_all`, and no Django migration covers them). Until both exist, the retrieval steps log errors and reviews run without similar-code context. There's also no vector index defined.

### `fetch_conventions` is a placeholder

The first agent node returns `{}`. Repository conventions never reach the prompt, even though `build_review_prompt` has a slot for them.

### GitHub token returned to the browser

`GET /api/v1/auth/github/token/` returns the decrypted OAuth token, and the frontend calls it (`src/api/client.ts`). JWTs are stored in `localStorage`.

### Repository scans don't complete in Django

`full_repo_scan_task` starts `/scan/full` and records the FastAPI scan ID. Django never calls `/scan/status` or `/scan/report`, so `RepoScan` stays in `scanning`. Django also passes no GitHub token, so private repositories can't be read. FastAPI keeps progress in a module-level dict, which is lost on restart and not shared between workers.

### Token counts not reported

`ReviewResponse` has no token fields, so `ReviewRun.prompt_tokens`, `completion_tokens` and `agent_iterations` keep their defaults.

### BYOK provider coverage

All LLM calls go to OpenAI-compatible `/chat/completions` endpoints. `anthropic` configs can be saved and validated but are skipped in the failover chain.

### Rate limiter waits instead of failing over

When a provider's per-minute window is full, `wait_for_token` sleeps until the next window instead of moving to the next provider.

### Settings that do nothing

`REVIEW_RATE_LIMIT_PER_HOUR` and `FRONTEND_URL` are read but unused. The `AWS_*` variables in `.env.example` aren't read by any code. The worker consumes the `notifications` queue, but no task is routed to it.

### `cleanup_old_reviews` is never scheduled

The task exists in `apps/reviews/tasks.py`, but there is no Celery beat service, so it runs only if someone calls it.

### `diff_text` is unbounded

`ReviewRun.diff_text` is a `TextField` with no size cap or compression.

### Frontend has no tests

CI covers the type check, build and lint only.
