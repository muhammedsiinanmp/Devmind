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
    LLM["LLM and embedding APIs<br/>server keys: Gemini, Groq<br/>or the user's own keys"]

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
        LLM["LLM providers<br/>Gemini / Groq<br/>+ user BYOK"]
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
    CW -->|"POST /review/analyze<br/>X-Internal-Secret"| FA
    FA -->|"BYOK key lookup<br/>X-Internal-Secret"| API
    FA --> LLM
    FA -->|"embeddings + similarity search"| PG
    FA -->|"rate-limit counters"| RD
    API --- PG
    CW --- PG
    PR -->|"scrape /metrics, /fastapi-metrics"| NGX
```

The deployment view (all nine compose services, ports and Redis databases), the review flow and the data model are in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

A review moves through the system like this:

1. GitHub sends a webhook to `POST /api/v1/webhooks/github/`. Django checks the signature (constant-time compare). It returns 403 if the signature is wrong or if `GITHUB_WEBHOOK_SECRET` isn't set. Valid requests get a Celery task queued.
2. The Celery worker creates the `Review` row (one per repo, PR number and head SHA, so a redelivered webhook doesn't create a duplicate). It fetches the diff from GitHub and calls FastAPI.
3. FastAPI parses the diff, embeds up to 20 changed hunks in one batched call, and searches pgvector once per hunk for similar code elsewhere in the repository, leaving out the PR's own chunks. It builds a prompt within a token budget and runs the LangGraph agent. After it responds, a background task embeds the PR's hunks that aren't stored yet, again in one batched call, so later reviews can retrieve them.
4. The worker saves the comments and a `ReviewRun` record, then queues a separate task that posts the comments to GitHub. If posting fails, that task can be retried without re-running the review.

The full design, including [architectural decisions and their trade-offs](docs/SYSTEM_ARCHITECTURE.md#12-architectural-decisions), is in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## Engineering highlights

**LangGraph review agent** (`backend/fastapi/agents/review_agent.py`). The agent is a 4-node `StateGraph`:

```
START -> [analyze_security | analyze_quality | analyze_tests] -> synthesize -> END
```

- The three analyzers run as parallel branches, one LLM call each, so a review normally makes 3 LLM calls. The output format in the system prompt is generated from one Pydantic schema (`ReviewFindings` in `models/review.py`), which also validates every reply: a JSON object `{"findings": [...]}`, and `{"findings": []}` when there are no issues. Calls use JSON mode (`response_format: json_object`) on the built-in Google and Groq providers and on OpenAI, Groq, Mistral and Google BYOK keys (not yet checked against the live APIs), and run at temperature 0.1 (`REVIEW_TEMPERATURE`). An analyzer repeats its call once only if the model's response can't be parsed, adding a turn that asks for only that JSON object. An empty list of findings (also a bare `[]`, `{}` or `{"issues": null}`) is a valid result and is not retried.
- The diff and every retrieved context section are wrapped in `<untrusted_data source="...">` ... `</untrusted_data>` tags, and the system prompt says their content is data, never instructions. Delimiter text inside the content is escaped so it can't close the block. This lowers the risk of prompt injection from a PR; it doesn't rule it out. The system prompt is sent once, as the system message.
- Each analyzer records its model, latency, token counts, attempts and whether its reply parsed in `analyzer_runs` (merged by the `_merge_dict` reducer in `agents/states.py`), and `POST /review/analyze` returns it.
- `synthesize` removes duplicates (same file, line and category), sorts by severity and sets `model_used` from the security, quality and tests analyzers in that order, so it doesn't depend on which branch finished last.
- The risk score is driven by the worst finding: a base for the highest severity (critical 70, error 45, warning 20, info 5) plus 3 for each other finding above info, at most +15, so the maximum is 85.
- The LLM output parser is the fallback for providers without JSON mode. It handles several formats: bare JSON, JSON inside markdown fences, JSON wrapped in an object, and JSON with prose around it. Each comment is then validated with the same schema. An unparseable reply is logged with its length and a hash, not its content.

**Line-anchored comments** (`backend/fastapi/services/comment_anchoring.py`):

- The diff parser records the new-file line number of every added and context line. The prompt shows each diff line with that number (`L42 + code`) and asks the model to use only numbers it was shown. On the 27 eval cases, all 64 findings in the after run pointed at a line shown in the diff, compared with 139 of 152 before (valid-line rate, see [Review quality](#review-quality)).
- The rendered diff is capped at 120 lines per hunk and 200 per file, and the diff's token budget is whatever the retrieved-pattern sections leave. Every file first gets its most important line (while the line budget has one per file), so a deletion-only file stays visible. Then added lines are kept before removed lines, then context, and each tier is shared evenly between files. Markers say how many lines and files were left out.
- Before the response is built, each comment is checked against the diff:
  - A comment on an added or context line stays inline.
  - A comment within 3 lines of exactly one hunk moves to that hunk's nearest line, and its suggested fix goes into the body as plain text.
  - Any other comment becomes a file-level note (`line_number` 0), which the GitHub poster puts in the review body.
- Every inline comment therefore points at a line of the parsed diff.
- `/review/analyze` logs and returns the `anchored`, `snapped` and `unanchored` counts.

**LLM provider failover** (`backend/fastapi/services/llm_client.py`):

- A user's own active provider configs are tried first, in priority order.
- After that come the server's providers: Google (`GOOGLE_MODEL`, default `gemini-3.5-flash`), then Groq (`GROQ_MODEL`, default `openai/gpt-oss-120b`). Any provider without a configured key is skipped. GitHub Models was retired on 2026-07-30 and was removed.
- Any non-200 response (including 429 and 5xx) or a timeout moves the request to the next provider. A 404 is logged as `llm.model_not_found`, which usually means the configured model was retired.
- `make providers-check` lists each keyed provider's models, sends one tiny chat request and prints provider, model, whether the model is listed, the result and latency. On a 404 it also prints the provider's error message, truncated and with keys redacted. It never prints keys and exits non-zero if no provider works. FastAPI's `/health` also reports each provider's configured model and whether the provider lists it (cached for `LLM_HEALTH_CACHE_SECONDS`, default 300). Listed doesn't mean usable, because Google lists models that are closed to new keys. The chat request in `make providers-check` is the authoritative check.
- Per-provider requests-per-minute limits are enforced with a Redis counter (`services/rate_limiter.py`), so all FastAPI workers share one budget. If Redis is down, requests go through instead of being blocked.

**Security hardening**:

- **Webhooks:** the HMAC signature is checked before any payload parsing, and webhooks are rejected outright when no secret is configured.
- **Service-to-service calls:** FastAPI's `/review/analyze` and `/embeddings/*` routes, and Django's internal BYOK endpoint, all require an `X-Internal-Secret` header (compared in constant time).
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
| Compose (profiles) | `docker compose config` with `.env.example`: Flower, Prometheus and Grafana appear only under the `ops` profile |
| Evals (replay) | Pull requests only, and only when they change FastAPI agent, service, model, router, core or eval code: `make eval` replay compared with the committed after-fixes results, posted as one PR comment (see [Evals](#evals)) |

Measured locally on this branch:

| Suite | Tests | Line coverage |
|---|---|---|
| Django | 225 passed | 86% |
| FastAPI | 433 passed | 94% |

Coverage method: `pytest --cov`, then `coverage report --omit='*/tests/*,*/migrations/*,*conftest.py'`, so test files, migrations and conftest are excluded. Including the test files would give a higher figure.

CI doesn't enforce a coverage threshold. The frontend has 19 Vitest tests: 17 for the review status polling loop (including error handling and the review page's refetch-on-completion handler) and 2 checking that the removed scan page and API stay removed. Frontend coverage isn't measured.

## Tech stack

| Layer | Technology |
|---|---|
| API, auth, orchestration | Django 5, Django REST Framework, SimpleJWT (rotating refresh tokens with blacklist), drf-spectacular |
| Background work | Celery 5 with Redis broker and result backend |
| AI service | FastAPI 0.111, LangGraph, SQLAlchemy (async) + asyncpg, tiktoken |
| Retrieval | PostgreSQL 16 + pgvector (`Vector(768)`, HNSW cosine index), Google `gemini-embedding-001` embeddings at 768 dimensions |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS 4, Zustand, React Router 7, axios |
| Observability | django-prometheus and prometheus-fastapi-instrumentator (HTTP request metrics) plus three FastAPI review metrics, Prometheus, a provisioned Grafana dashboard, Flower, optional Sentry |
| Tooling | Python 3.12, uv, pnpm, Docker Compose, GitHub Actions |

## Quick start (local development)

Prerequisites: Docker with Compose v2 and a [GitHub OAuth App](https://github.com/settings/developers) whose callback URL is `http://localhost:5173/auth/callback`.

```bash
cp .env.example .env
#    Set DJANGO_SECRET_KEY, JWT_SECRET_KEY, FASTAPI_INTERNAL_SECRET,
#    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET
#    and at least one of GOOGLE_AI_API_KEY / GROQ_API_KEY.
#    Sentry is off by default; set SENTRY_DSN_DJANGO / SENTRY_DSN_FASTAPI to enable it.
make up
```

`make up` (`docker compose up -d`) builds the images on first run and starts Postgres, Redis, Django, FastAPI, the Celery worker, Nginx and the Vite frontend. A one-shot `migrate` service applies Django migrations first, including the one that enables the pgvector extension, and the app services wait for it to finish.

Flower, Prometheus and Grafana sit behind the compose `ops` profile. Start them with `make up-ops`.

Other `Makefile` shortcuts: `make down`, `make logs`, `make migrate`, `make test`, `make providers-check` to check the server LLM keys and models (runs on the host, needs `uv`), and `make frontend-dev` to run Vite on the host instead (needs Node.js 20 and pnpm).

| Service | URL |
|---|---|
| Frontend (Vite, proxies `/api` to Django) | http://localhost:5173 |
| Django API | http://localhost:8000/api/v1/ |
| Swagger UI | http://localhost:8000/api/schema/swagger-ui/ |
| Django health | http://localhost:8000/health/ |
| FastAPI docs / health | http://localhost:8001/docs, http://localhost:8001/health |
| Flower (`make up-ops`) | http://localhost:5555 |
| Prometheus / Grafana (`make up-ops`) | http://localhost:9090, http://localhost:3000 |

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

## Evals

`backend/fastapi/evals/` measures review quality. It runs `run_review_agent` on 27 hand-written synthetic diffs in `evals/cases/` (9 of them clean, with `expected: []`), skipping the database/RAG step, so no Postgres is needed. The agent's comments then go through the same steps the router applies before posting: comments without a body are dropped, each is validated as a `ReviewComment`, and they're anchored to diff lines with `anchor_comments()` when the code has it. The results record which of these steps ran.

Each posted finding is matched to the labeled ones. A label gives a file and line range (or several acceptable locations), a category and a minimum severity. Model category labels such as "SQL Injection" or "test-coverage" are folded into security, quality or tests.

What it reports:
- **Precision**, measured against the labels: a real issue nobody labeled counts as an extra, and so does a duplicate. It's reported three ways: exact location, with duplicates collapsed (same file, line and folded category), and location-tolerant.
- **Recall, exact line:** the finding's line must fall inside the labeled range.
- **Recall, location-tolerant:** also accepts a finding in the same file with the right category and severity that is within 3 lines of the range or in the same hunk.
- **False-positive rate on clean diffs:** the share of clean cases with at least one posted finding.
- **Valid-line rate:** the share of the agent's findings, before anchoring, that point at a line shown in the diff.
- **Analyzer parse failures:** the number of analyzer runs whose reply couldn't be parsed, or "unknown" for code that doesn't report it.
- **Latency, token counts and cost.** Latency depends on the providers and quotas, so compare it only between runs that used the same providers. Cost is reported only when a price is set in `PRICES_PER_MTOK` in `evals/run.py`. None are set, so it shows "not priced".

A case that errors (missing or stale cassette, a provider failure, an analyzer reply that can't be parsed) is never dropped. Its labeled findings count as missed, and an errored clean case counts as a false positive. Every report states how many cases were scored, and `--results-dir` refuses to write results that include errored cases unless you pass `--allow-partial`.

```bash
make eval         # replay: offline and deterministic, uses evals/cassettes/, no keys needed
make eval-record  # live: calls the providers configured in .env, re-records the
                  # cassettes, writes evals/results/<sha>.json and <sha>.md
# Free-tier quotas: pin one server provider and wait between cases
make eval-record EVAL_ARGS="--provider groq --pause 75"
```

`--provider NAME` (live only) limits the server chain to one provider for the run, so a quota running out partway through can't silently switch models. `--pause SECONDS` waits that long between cases. `--only id1,id2` runs a subset, `--results-name` sets the results file name, and `--allow-partial` writes results even when some cases errored. Results record these flags, the recording date, the providers, the commit (and whether there were uncommitted or untracked files), a hash of the harness code and a hash of the case set.

Cassettes store only the SHA-256 of each prompt, the response text, the model name and provider, token counts and the recording time. They don't store prompts, headers or keys, and recording stops if a configured key appears in a response.

**Replay can't measure a prompt change.** Cassettes are keyed by prompt hash, so replay only re-scores responses that were already recorded. After the agent's prompts or a case's diff change, replay reports those cases as stale. Measuring the effect of a prompt or model change needs a live run (`make eval-record`). Replay is for re-scoring a recorded run, for example after a change to the scorer or the labels. `evals/cassettes/` holds the recordings of the "after" run below, so `make eval` replays them by default. They match the current prompts; once a change alters a prompt, re-record them.

**CI.** On a pull request that changes `backend/fastapi/{agents,services,models,routers,core,evals}/**` (or `scripts/eval_compare.py`), the `Evals (replay)` job runs `make eval` against the committed cassettes and compares the result with `evals/results/after-fixes.json` using `scripts/eval_compare.py`. It posts one PR comment with the marker `<!-- devmind-eval-report -->` and updates that comment on later pushes. The comment says one of three things:
- **No metric changed.**
- **Metrics changed**, with a before/after table of the changes. This happens when the change touches scoring, labels or post-processing but not prompts.
- **Prompt changed: replay can't measure this PR.** Some prompts have no recording, so nothing is scored. Re-record with `make eval-record EVAL_ARGS="--provider groq --pause 75"`, which needs provider keys in `.env`. Commit the new cassettes and the results file, and copy the results file over `after-fixes.json` if it becomes the new reference.

The job needs no secrets and doesn't fail because of eval results. It fails only if the harness or the comparison can't run. On pull requests from forks it writes the report to the job summary and doesn't comment. To compare two results files locally, run `cd backend/fastapi && uv run python -m scripts.eval_compare BASE.json CURRENT.json`.

The test suite checks the scoring against hand-written fixture responses in `backend/fastapi/tests/fixtures/evals/`. Those are test data, not model output.

### Review quality

The same 27 cases (9 clean, 18 labeled defects), scored with the same harness, for the review agent before the A-series fixes and for the agent on `dev` after them. Both runs used `groq/openai/gpt-oss-120b` for every model call. Every number in the table comes from [`baseline-pre-fix.json`](backend/fastapi/evals/results/baseline-pre-fix.json) and [`after-fixes.json`](backend/fastapi/evals/results/after-fixes.json) in `backend/fastapi/evals/results/`. The table is the output of `scripts/eval_compare.py` on those two files, and a test (`tests/test_eval_compare.py`) checks that it still matches them.

| Metric | Before (pre-fix) | After (dev) | Change |
|---|---|---|---|
| Recall, exact line | 0.556 (10/18) | 1.000 (18/18) | +0.444 |
| Precision, exact location | 0.066 (10/152) | 0.281 (18/64) | +0.215 |
| Precision, duplicates collapsed | 0.081 (10/123) | 0.300 (18/60) | +0.219 |
| Precision, location-tolerant | 0.112 (17/152) | 0.281 (18/64) | +0.169 |
| Recall, location-tolerant | 0.944 (17/18) | 1.000 (18/18) | +0.056 |
| False-positive rate on clean diffs | 1.000 (9/9) | 1.000 (9/9) | no change |
| Findings on clean diffs | 42 | 16 | -26 |
| Findings on clean diffs at critical or error severity | 1 | 0 | -1 |
| Findings posted | 152 | 64 | -88 |
| Valid-line rate (agent output, before anchoring) | 0.914 (139/152) | 1.000 (64/64) | +0.086 |
| Analyzer parse failures | not reported by this code | 0 | n/a |
| Anchoring (anchored / snapped / file-level) | not applied | 64 / 0 / 0 | n/a |
| Cases scored | 27 of 27 | 27 of 27 | no change |

How to read it:
- **Recall and precision.** After the fixes, all 18 labeled defects get a finding on the labeled line, compared with 10 before. Precision is still low: 46 of the 64 posted findings match no label. Precision counts a real issue nobody labeled as an extra, so it is a lower bound.
- **Clean diffs.** The false-positive rate on clean diffs didn't change: each of the 9 clean diffs still gets at least one comment. There are fewer of them (16, down from 42), and none is critical or error. Before, there were 41 warnings and 1 critical. After, there are 13 warnings and 3 info. By folded category, 9 of the 16 are tests (mostly "no test covers this") and 7 are quality (input validation, indentation, a hard-coded timeout, an extra variable).
- **Analyzer parse failures.** The pre-fix agent doesn't report whether a reply parsed, so the before count can't be observed. After, 0 analyzer runs failed to parse.
- **Latency: not compared.** Both results record per-case latency (before: mean 3545 ms, after: mean 2307 ms), but they aren't comparable. The before run went through the server chain with Google first and Google's daily quota exhausted, so its times may include failed Google calls before the failover to Groq. The cassettes don't record this. The after run used only Groq.
- **Tokens.** Model calls: 81 in both runs. Prompt tokens went from 31353 to 56463 and completion tokens from 52786 to 27612.
- **Small, synthetic set.** 27 hand-written diffs, and each run was recorded once. The numbers show what this agent and model did on these cases. They are not an estimate of performance on real pull requests.

After-run provenance:
- **Code:** recorded with the E1 harness at commit `40b8853` (an ancestor of `dev`). Its `agents/`, `services/`, `models/`, `core/` and `routers/` code is identical to `dev` at `bccc370`: `git diff --stat 40b8853 bccc370` on those directories is empty.
- **Model:** `groq/openai/gpt-oss-120b` for all 81 calls (`models_used` in the results file).
- **Recording:** all 27 cases recorded live on 2026-11-06. The cassettes are in `backend/fastapi/evals/cassettes/` (commit `01095e3`). The `40b8853` harness didn't store the provider or recording time in cassettes, so the results file has no date (`date_source: not stored in cassettes`). The 2026-11-06 date is the commit date. The first live pass was interrupted by a network (DNS) outage after 14 cases; the remaining 13 were recorded in a second pass with the same harness, model and flags. The 40b8853 cassettes store no timestamps, so this comes from the recording session's logs, not from a committed artifact. No case was dropped: all 27 are scored.
- **Scoring:** [`after-fixes.md`](backend/fastapi/evals/results/after-fixes.md) and `.json`, from replaying those cassettes on a clean checkout of `01095e3` (`dirty_worktree: false`). The results file has `harness_sha256` `eaac3e46…` and `case_set_sha256` `00dad82d…`, the same as the baseline, so both runs were scored by the same code on the same cases and labels. A replay on this branch gives the same metrics.

Baseline provenance:
- **Code:** commit `8e606d6` on branch `eval/baseline-prefix` is the first version of this harness on top of `dev` at `ebb335a` (the pre-fix agent). It changes only the model IDs in `services/llm_client.py`, because the original models could no longer be called. `gemini-2.0-flash` became `gemini-3.5-flash`, `llama-3.3-70b-versatile` became `openai/gpt-oss-120b`, and GitHub Models was disabled (retired 2026-07-30). These are the same model IDs #96 adopted.
- **Model:** `groq/openai/gpt-oss-120b` only. Google's free daily quota had run out, so every call went to Groq.
- **Recording:** all 27 cases (9 clean), recorded on 2026-11-06 (the commit date of `6e5638a`; the cassettes from that run don't store a timestamp). Cases were run one at a time from a shell loop with a pause between them, because `--pause` didn't exist yet; the pause length isn't recorded in any artifact. The cassettes are in commit `6e5638a` on the same branch. They're keyed to the pre-fix prompts, so they replay only against that code.
- **Scoring:** [`backend/fastapi/evals/results/baseline-pre-fix.md`](backend/fastapi/evals/results/baseline-pre-fix.md) and `.json`. These come from replaying those cassettes on a checkout of `6e5638a` whose `evals/` directory (harness code and case labels only, no agent code) was replaced with this branch's. That's why the results file shows commit `6e5638a` with uncommitted files present. Its `harness_sha256` (`eaac3e46…`) and `case_set_sha256` (`00dad82d…`) match this branch's `evals/` code and cases. Replaying produced the same agent output, case for case, as the original run.
- **Why the numbers moved from the first report** (precision 0.059, recall 0.500, 9 matches): one more exact match comes from the alternative location added to `missing-test-for-new-branch` (`tests/test_pricing.py`), and the new location-tolerant bucket counts 7 near matches that were previously misses.
- **Caveat on that extra exact match:** the finding it credits (`tests/test_pricing.py:4`) is about a different untested case (a discount equal to the subtotal). The finding that names the labeled defect (the untested quantity `ValueError`) is at line 1, just outside the alternative range, and would have been a near match. Read by hand, the split is 9 exact and 8 near. Tolerant recall (17/18) is unaffected. The matcher matches on location, category and severity, not on the finding's text, so this can happen whenever several findings share a category in one hunk.

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
| `GOOGLE_AI_API_KEY`, `GROQ_API_KEY` | FastAPI | Server LLM providers. The Google key is also used for embeddings. |
| `GOOGLE_MODEL`, `GROQ_MODEL` | FastAPI | Model per server provider. Check with `make providers-check`. |
| `DJANGO_BASE_URL` | FastAPI | Where FastAPI fetches BYOK configs from |

[docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md) lists every variable.

## API overview

All routes are under `/api/v1/` and need `Authorization: Bearer <access token>` unless noted. The interactive schema is at `/api/schema/swagger-ui/`.

| Area | Routes |
|---|---|
| Auth | `GET auth/github/start/` and `GET auth/github/callback/?code=&state=` (no auth), `POST auth/token/refresh/`, `POST auth/logout/`, `GET auth/me/`, `GET auth/github/token/` |
| Repositories | `GET repositories/`, `GET/PATCH repositories/<id>/`, `POST repositories/connect/` (queues a GitHub sync and webhook install) |
| Reviews | `GET reviews/` (filters `status`, `repository`; `search`; `ordering`), `GET reviews/<id>/`, `POST reviews/<id>/retrigger/` |
| LLM settings (BYOK) | `GET/POST settings/llm/`, `GET/PATCH/DELETE settings/llm/<id>/`, `POST settings/llm/<id>/set_default/`, `POST settings/llm/test/` |
| Webhooks | `POST webhooks/github/` (no JWT; HMAC signature required) |
| Internal | `GET auth/internal/llm-configs/?user_id=` (`X-Internal-Secret` only) |

## Project structure

```
backend/
  django/            Django project (devmind/ settings, urls, celery)
    apps/accounts/   GitHub OAuth, users, encrypted tokens, BYOK LLM configs
    apps/repositories/  repo sync, webhook install + receiver
    apps/reviews/    Review models, orchestrator, GitHub comment poster
    apps/core/       structlog configuration, database-level migrations (pgvector)
    tests/           end-to-end pipeline test
  fastapi/           AI service
    agents/          LangGraph review agent and state
    evals/           review-quality eval cases, harness, cassettes, results
    routers/         /review, /embeddings, /health
    services/        LLM client, rate limiter, vector store, diff parser, prompt builder
frontend/            React + Vite app
nginx/  prometheus/  grafana/   local infrastructure config
.github/workflows/ci.yml
```

## Known limitations

These are current gaps in the code, listed so nobody has to find them by surprise:

- **No repository conventions.** Nothing loads repo-specific conventions, so `build_review_prompt`'s `repo_conventions` slot is always empty.
- **No embedding tables.** A Django migration enables the `vector` extension, but nothing creates the `code_embeddings` / `review_embeddings` tables. Until they exist, embedding storage and similarity search fail (logged), and reviews run without retrieved context. If you created `code_embeddings` by hand, apply the files in [`backend/fastapi/migrations/sql/`](backend/fastapi/migrations/sql/) in order: `0001` adds `source_ref` (without it, retrieval and storage fail with a missing-column error, and the failure is only logged), and `0002` adds the HNSW index used by similarity search.
- **Old untagged chunks can match their own PR.** Before `source_ref`, each review stored its hunks under their real file paths with no tag. If a PR was reviewed before this change and gets a new push afterwards, its old hunks can still be retrieved for it, unless their text exactly matches a hunk in the new diff. The cleanup for the embedding model change below removes them. Don't delete by `source_ref IS NULL`: `/embeddings/store` and reviews with `pr_number` 0 still write untagged rows.
- **Embeddings from `text-embedding-004` must be cleared or re-embedded.** Google retired `text-embedding-004`, and the default `EMBEDDING_MODEL` is now `gemini-embedding-001` (requested at 768 dimensions). Vectors from the two models aren't comparable, so rows stored before the switch give meaningless similarity scores. Nothing removes them automatically. Delete the rows written before you deployed the switch, for example `DELETE FROM code_embeddings WHERE created_at < '<deploy time>';`, or re-embed their `chunk_text`.
- **`GET /api/v1/auth/github/token/` sends the user's decrypted GitHub token to the browser.** The frontend also keeps JWTs in `localStorage`.
- **Token counts are always zero in Django.** FastAPI returns token counts only per analyzer in `analyzer_runs`, which Django doesn't read, so `ReviewRun.prompt_tokens` and `completion_tokens` stay at 0.
- **Anthropic keys aren't used for reviews.** They can be saved and validated, but the FastAPI client sends only OpenAI-compatible `/chat/completions` requests, so it skips them.
- **Frontend tests are minimal.** Vitest covers only the review status polling loop and the review page's refetch-on-completion handler (`frontend/src/lib/reviewStatusPolling.test.ts`) and a check that the removed scan page and API stay removed (`frontend/src/api/scanRemoved.test.ts`); there are no component or page tests.

## Further reading

| Document | Contents |
|---|---|
| [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Services, deployment topology, review flow, AI pipeline, data model (Django and pgvector tables), failure handling, security model, architectural decisions |
| [docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md) | Environment variables, local setup, workflows, full API reference, testing, deployment notes, troubleshooting, known gaps |
| [frontend/README.md](frontend/README.md) | Frontend stack, scripts and how it talks to the API |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branches, pull requests, required CI checks and the checks to run locally |
| [SECURITY.md](SECURITY.md) | How to report a vulnerability |

## Contributing and security

Contributions go through pull requests into `dev`; see [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## License

DevMind is released under the [MIT License](LICENSE).
