# DevMind

[![CI](https://github.com/muhammedsiinanmp/Devmind/actions/workflows/ci.yml/badge.svg)](https://github.com/muhammedsiinanmp/Devmind/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

DevMind is an AI pull-request reviewer for GitHub. When a pull request is opened or updated, it reads the diff, runs it through a multi-step LLM review pipeline, and posts the findings back to the pull request as inline review comments.

## What it does

- Receives GitHub `pull_request` webhooks (`opened`, `synchronize`, `reopened`) and checks each one's HMAC-SHA256 signature.
- Fetches the PR diff, then reviews it for security, code quality and test coverage in parallel LLM calls.
- Stores the review (risk score 0-100, comments by severity and category, the diff itself) and posts the comments to GitHub as a `COMMENT` review.
- Lets each user add their own LLM API keys ("bring your own key"). These are tried before the server's own providers.
- Includes a React dashboard for browsing reviews with a diff viewer, managing connected repositories and configuring LLM providers.

## Architecture

**Context.** Who and what DevMind talks to:

```mermaid
flowchart LR
    Author["PR author<br/>opens or updates a pull request"]
    User["DevMind user<br/>signs in, connects repositories,<br/>reads reviews, adds BYOK keys"]
    DM["DevMind<br/>React app, Django API, Celery worker,<br/>FastAPI AI service, Postgres, Redis"]
    GH["GitHub<br/>OAuth, repositories, webhooks,<br/>pull request reviews"]
    LLM["LLM and embedding APIs<br/>server keys: Gemini, Groq, GitHub Models<br/>or the user's own keys"]

    Author -->|"push to a pull request"| GH
    User -->|"browser"| DM
    GH -->|"pull_request webhook, HMAC-signed"| DM
    DM -->|"OAuth, repo sync, webhook install,<br/>diff fetch, review comments"| GH
    DM -->|"chat completions, embeddings"| LLM
```

**Containers.** The processes inside DevMind and how they connect:

```mermaid
flowchart LR
    subgraph External
        GH["GitHub"]
        LLM["LLM providers<br/>Gemini / Groq / GitHub Models<br/>+ user BYOK"]
    end

    FE["React app<br/>Vite dev server :5173"]
    NGX["Nginx :80"]

    subgraph Django["Django :8000"]
        API["REST API + OAuth<br/>webhook receiver"]
    end

    subgraph Workers["Celery"]
        CW["celery_worker"]
    end

    FA["FastAPI :8001<br/>LangGraph review agent"]

    PG[("PostgreSQL 16<br/>+ pgvector")]
    RD[("Redis")]
    PR["Prometheus"] --> GR["Grafana"]

    FE -->|"/api proxy"| API
    GH -->|"webhook"| API
    NGX -->|"/ and /metrics"| API
    API -->|"enqueue"| RD
    RD --> CW
    CW -->|"fetch diff, post comments"| GH
    CW -->|"POST /review/analyze, /scan/full<br/>X-Internal-Secret"| FA
    FA -->|"BYOK key lookup<br/>X-Internal-Secret"| API
    FA --> LLM
    FA -->|"embeddings + similarity search"| PG
    FA -->|"rate-limit counters"| RD
    API --- PG
    CW --- PG
    PR -->|"scrape /metrics, /fastapi-metrics"| NGX
```

The deployment view (all nine compose services, ports and Redis databases), the data model and the scan flow are in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

A review moves through the system like this:

1. GitHub sends a webhook to `POST /api/v1/webhooks/github/`. Django checks the signature (constant-time compare). It returns 403 if the signature is wrong or if `GITHUB_WEBHOOK_SECRET` isn't set. Valid requests get a Celery task queued.
2. The Celery worker creates the `Review` row (one per repo, PR number and head SHA, so a redelivered webhook doesn't create a duplicate). It fetches the diff from GitHub and calls FastAPI.
3. FastAPI parses the diff and searches pgvector once per changed hunk for similar code elsewhere in the repository, leaving out the PR's own chunks. It builds a prompt within a token budget and runs the LangGraph agent. After it responds, a background task embeds the PR's hunks so later reviews can retrieve them.
4. The worker saves the comments and a `ReviewRun` record, then queues a separate task that posts the comments to GitHub. If posting fails, that task can be retried without re-running the review.

The full design, including [architectural decisions and their trade-offs](docs/SYSTEM_ARCHITECTURE.md#12-architectural-decisions), is in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## Engineering highlights

**LangGraph review agent** (`backend/fastapi/agents/review_agent.py`). The agent is a 7-node `StateGraph`:

```
fetch_conventions -> [analyze_security | analyze_quality | analyze_tests] -> synthesize -> generate_fixes -> format_output
```

- The three analyzers run as parallel branches. A custom list reducer (`_extend_list` in `agents/states.py`) merges their results; without it, a later branch would overwrite an earlier one.
- `synthesize` removes duplicates (same file, line and category) and sorts by severity.
- `format_output` computes a confidence score from the number of findings relative to the diff size. If the score is below 0.7, the graph goes back to the start, up to 3 passes in total.
- The LLM output parser handles several formats: bare JSON, JSON inside markdown fences, JSON wrapped in an object, and JSON with prose around it. Each comment is then validated with Pydantic.

**Line-anchored comments** (`backend/fastapi/services/comment_anchoring.py`):

- The diff parser records the new-file line number of every added and context line. The prompt shows each diff line with that number (`L42 + code`) and asks the model to use only numbers it was shown. No evaluation has measured how often the model follows this yet.
- The rendered diff is capped at 120 lines per hunk and 200 per file, and the diff's token budget is whatever the retrieved-pattern sections leave. Added lines are kept before removed lines, then context, and each tier is shared evenly between files. Markers say how many lines and files were left out.
- Before the response is built, each comment is checked against the diff:
  - A comment on an added or context line stays inline.
  - A comment within 3 lines of exactly one hunk moves to that hunk's nearest line, and its suggested fix goes into the body as plain text.
  - Any other comment becomes a file-level note (`line_number` 0), which the GitHub poster puts in the review body.
- Every inline comment therefore points at a line of the parsed diff.
- `/review/analyze` logs and returns the `anchored`, `snapped` and `unanchored` counts.

**LLM provider failover** (`backend/fastapi/services/llm_client.py`):

- A user's own active provider configs are tried first, in priority order.
- After that come the server's providers: Google `gemini-2.0-flash`, then Groq `llama-3.3-70b-versatile`, then GitHub Models `gpt-4o-mini`. Any provider without a configured key is skipped.
- Any non-200 response (including 429 and 5xx) or a timeout moves the request to the next provider.
- Per-provider requests-per-minute limits are enforced with a Redis counter (`services/rate_limiter.py`), so all FastAPI workers share one budget. If Redis is down, requests go through instead of being blocked.

**Security hardening**:

- **Webhooks:** the HMAC signature is checked before any payload parsing, and webhooks are rejected outright when no secret is configured.
- **Service-to-service calls:** FastAPI's `/review/analyze`, `/embeddings/*` and `/scan/*` routes, and Django's internal BYOK endpoint, all require an `X-Internal-Secret` header (compared in constant time).
- **Stored secrets:** GitHub OAuth tokens and BYOK API keys are encrypted at rest with Fernet (`apps/accounts/encryption.py`). The key is derived from `SECRET_KEY` with HKDF.
- **SSRF protection:** a user-supplied BYOK `base_url` must use https and resolve only to public IP addresses (`apps/accounts/url_safety.py`). This blocks requests to internal services and cloud metadata endpoints, with two caveats:
  - DNS rebinding between the check and the request isn't prevented.
  - FastAPI uses the stored `base_url` without re-validating it, so rows saved before this check existed are unguarded.
- **OAuth:** the OAuth `state` value is random, stored in Redis for 10 minutes and accepted only once.

**Testing and CI**: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on pushes to `main` and `dev` and on pull requests:

| Job | What it runs |
|---|---|
| Django (pytest) | ruff, black, missing-migration check, pytest against Postgres (pgvector image) and Redis service containers |
| FastAPI (pytest) | ruff, black, pytest (no external services) |
| Frontend (typecheck, build, lint) | `tsc`, `vite build`, `eslint`, `vitest run` |

Measured locally on this branch:

| Suite | Tests | Line coverage |
|---|---|---|
| Django | 241 passed | 83% |
| FastAPI | 218 passed | 83% |

Coverage method: `pytest --cov`, then `coverage report --omit='*/tests/*,*/migrations/*,*conftest.py'`, so test files, migrations and conftest are excluded. Including the test files would give a higher figure.

CI doesn't enforce a coverage threshold. The frontend has 6 Vitest tests, all for the review status polling loop; coverage isn't measured.

## Tech stack

| Layer | Technology |
|---|---|
| API, auth, orchestration | Django 5, Django REST Framework, SimpleJWT (rotating refresh tokens with blacklist), drf-spectacular |
| Background work | Celery 5 with Redis broker and result backend |
| AI service | FastAPI 0.111, LangGraph, SQLAlchemy (async) + asyncpg, tiktoken |
| Retrieval | PostgreSQL 16 + pgvector (`Vector(768)`), Google `text-embedding-004` embeddings |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS 4, Zustand, React Router 7, axios |
| Observability | django-prometheus and prometheus-fastapi-instrumentator (HTTP request metrics) plus three FastAPI review metrics, Prometheus, a provisioned Grafana dashboard, Flower, optional Sentry |
| Tooling | Python 3.12, uv, pnpm, Docker Compose, GitHub Actions |

## Quick start (local development)

Prerequisites: Docker with Compose v2, Node.js 20 with pnpm, and a [GitHub OAuth App](https://github.com/settings/developers) whose callback URL is `http://localhost:5173/auth/callback`.

```bash
# 1. Configure
cp .env.example .env
#    Set DJANGO_SECRET_KEY, JWT_SECRET_KEY, FASTAPI_INTERNAL_SECRET,
#    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET
#    and at least one of GOOGLE_AI_API_KEY / GROQ_API_KEY / GITHUB_TOKEN.
#    Sentry is off by default; set SENTRY_DSN_DJANGO / SENTRY_DSN_FASTAPI to enable it.

# 2. Start the backend stack (Postgres, Redis, Django, FastAPI,
#    Celery worker, Flower, Nginx, Prometheus, Grafana)
docker compose up -d --build

# 3. Apply migrations
docker compose exec django uv run python manage.py migrate

# 4. Enable the pgvector extension (no migration does this yet)
docker compose exec postgres psql -U devmind -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 5. Start the frontend separately (it is not part of docker-compose.yml)
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

The `Makefile` has shortcuts: `make up`, `make migrate`, `make logs`, `make test`, `make frontend-dev`.

| Service | URL |
|---|---|
| Frontend (Vite, proxies `/api` to Django) | http://localhost:5173 |
| Django API | http://localhost:8000/api/v1/ |
| Swagger UI | http://localhost:8000/api/schema/swagger-ui/ |
| Django health | http://localhost:8000/health/ |
| FastAPI docs / health | http://localhost:8001/docs, http://localhost:8001/health |
| Flower | http://localhost:5555 |
| Prometheus / Grafana | http://localhost:9090, http://localhost:3000 |

To get webhooks from GitHub while developing locally, expose Django with a tunnel (`make ngrok`) and set `DEVMIND_PUBLIC_URL` to the tunnel URL. The compose stack runs Django with **development settings** (`DEBUG=True`, all hosts allowed, throttling off), so only expose it briefly and only for testing.

## Running tests

```bash
# Django: needs Postgres and Redis (the compose services work)
cd backend/django
uv sync --frozen
DJANGO_SECRET_KEY=dev JWT_SECRET_KEY=dev \
DATABASE_URL=postgresql://devmind:devmind_secret@localhost:5432/devmind \
REDIS_URL=redis://localhost:6379/0 DJANGO_ALLOW_ASYNC_UNSAFE=1 \
uv run pytest --cov

# FastAPI: no services needed; conftest.py disables the .env file and sets fake keys
cd backend/fastapi
uv sync --frozen
uv run pytest

# Frontend
cd frontend
pnpm exec tsc -p tsconfig.app.json --noEmit && pnpm build && pnpm lint && pnpm test

# Or run both backend suites inside the running containers
make test
```

## Configuration

All services read the root `.env` (template: [.env.example](.env.example)). These are the main variables:

| Variable | Used by | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django | Django secret. Also the master key for encrypting stored tokens, so changing it makes existing encrypted values unreadable. |
| `JWT_SECRET_KEY` | Django | Signs access and refresh tokens |
| `DATABASE_URL` / `FASTAPI_DATABASE_URL` | Django / FastAPI | Postgres connection strings |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Both | Cache and rate limiter (db 0), broker (db 1), results (db 2) |
| `FASTAPI_INTERNAL_SECRET` | Both | Shared secret for internal calls. Must match on both sides. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Django | GitHub OAuth App |
| `GITHUB_WEBHOOK_SECRET` | Django | Webhook HMAC key. Webhooks are rejected if it's empty. |
| `DEVMIND_PUBLIC_URL` | Django | Base URL that installed GitHub webhooks point to |
| `GOOGLE_AI_API_KEY`, `GROQ_API_KEY`, `GITHUB_TOKEN` | FastAPI | Server LLM providers. The Google key is also used for embeddings. |
| `DJANGO_BASE_URL` | FastAPI | Where FastAPI fetches BYOK configs from |

[docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md) lists every variable.

## API overview

All routes are under `/api/v1/` and need `Authorization: Bearer <access token>` unless noted. The interactive schema is at `/api/schema/swagger-ui/`.

| Area | Routes |
|---|---|
| Auth | `GET auth/github/start/` and `GET auth/github/callback/?code=&state=` (no auth), `POST auth/token/refresh/`, `POST auth/logout/`, `GET auth/me/`, `GET auth/github/token/` |
| Repositories | `GET repositories/`, `GET/PATCH repositories/<id>/`, `POST repositories/connect/` (queues a GitHub sync and webhook install), `POST repositories/<id>/scan/` |
| Reviews | `GET reviews/` (filters `status`, `repository`; `search`; `ordering`), `GET reviews/<id>/`, `POST reviews/<id>/retrigger/`, `GET reviews/scans/<id>/` |
| LLM settings (BYOK) | `GET/POST settings/llm/`, `GET/PATCH/DELETE settings/llm/<id>/`, `POST settings/llm/<id>/set_default/`, `POST settings/llm/test/` |
| Organizations | `POST organizations/`, `organizations/<id>/`, `.../invite/`, `.../members/`, `organizations/invite/accept/` |
| Webhooks | `POST webhooks/github/` (no JWT; HMAC signature required) |
| Internal | `GET auth/internal/llm-configs/?user_id=` (`X-Internal-Secret` only) |

## Project structure

```
backend/
  django/            Django project (devmind/ settings, urls, celery)
    apps/accounts/   GitHub OAuth, users, encrypted tokens, BYOK LLM configs
    apps/repositories/  repo sync, webhook install + receiver
    apps/reviews/    Review models, orchestrator, GitHub comment poster, scans
    apps/organizations/ organizations, members, invites
    apps/core/       structlog configuration
    tests/           end-to-end pipeline test
  fastapi/           AI service
    agents/          LangGraph review agent and state
    routers/         /review, /embeddings, /scan, /health
    services/        LLM client, rate limiter, vector store, diff parser, prompt builder
frontend/            React + Vite app
nginx/  prometheus/  grafana/   local infrastructure config
.github/workflows/ci.yml
```

## Known limitations

These are current gaps in the code, listed so nobody has to find them by surprise:

- **`fetch_conventions` is a placeholder.** The first agent node returns an empty dict, so reviews get no repo-specific conventions.
- **No pgvector setup.** Nothing creates the `vector` extension or the `code_embeddings` / `review_embeddings` tables. On a fresh database, FastAPI `/health` returns 503 until the extension is enabled. Until the tables exist, embedding storage and similarity search fail (logged), and reviews run without retrieved context. If you created `code_embeddings` by hand before `source_ref` existed, apply [`backend/fastapi/migrations/sql/0001_code_embeddings_source_ref.sql`](backend/fastapi/migrations/sql/0001_code_embeddings_source_ref.sql). Without it, retrieval and storage fail with a missing-column error, and the failure is only logged.
- **Old untagged chunks can match their own PR.** Before `source_ref`, each review stored its hunks under their real file paths with no tag. If a PR was reviewed before this change and gets a new push afterwards, its old hunks can still be retrieved for it, unless their text exactly matches a hunk in the new diff. Deleting rows where `source_ref IS NULL` removes them, along with all other context stored before the change.
- **`GET /api/v1/auth/github/token/` sends the user's decrypted GitHub token to the browser.** The frontend also keeps JWTs in `localStorage`.
- **Repository scans never complete in Django.** Django starts a scan on FastAPI but never reads the result back, so `RepoScan` rows stay in `scanning`. FastAPI holds scan progress in process memory.
- **Token counts are always zero.** FastAPI doesn't return token counts, so `ReviewRun.prompt_tokens` and `completion_tokens` stay at 0.
- **Anthropic keys aren't used for reviews.** They can be saved and validated, but the FastAPI client sends only OpenAI-compatible `/chat/completions` requests, so it skips them.
- **Frontend tests are minimal.** Vitest covers only the review status polling loop (`frontend/src/lib/reviewStatusPolling.test.ts`); there are no component or page tests.

## Further reading

| Document | Contents |
|---|---|
| [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Services, deployment topology, review and scan flows, AI pipeline, data model (Django and pgvector tables), failure handling, security model, architectural decisions |
| [docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md) | Environment variables, local setup, workflows, full API reference, testing, deployment notes, troubleshooting, known gaps |
| [frontend/README.md](frontend/README.md) | Frontend stack, scripts and how it talks to the API |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branches, pull requests, required CI checks and the checks to run locally |
| [SECURITY.md](SECURITY.md) | How to report a vulnerability |

## Contributing and security

Contributions go through pull requests into `dev`; see [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## License

DevMind is released under the [MIT License](LICENSE).
