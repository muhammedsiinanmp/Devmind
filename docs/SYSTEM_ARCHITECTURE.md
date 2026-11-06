# System Architecture

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Inventory](#2-service-inventory)
3. [Network Topology](#3-network-topology)
   - [Deployment diagram](#deployment-diagram-docker-composeyml)
   - [Redis usage by database](#redis-usage-by-database)
4. [End-to-End Flows](#4-end-to-end-flows)
   - [PR review triggered by a GitHub webhook](#pr-review-triggered-by-a-github-webhook)
5. [AI Review Pipeline](#5-ai-review-pipeline)
6. [Authentication and Authorization](#6-authentication-and-authorization)
7. [GitHub Integration](#7-github-integration)
8. [Data Model](#8-data-model)
   - [Django entities](#django-entities)
   - [FastAPI tables](#fastapi-tables-sqlalchemy-modelsembeddingspy)
9. [Reliability and Failure Handling](#9-reliability-and-failure-handling)
10. [Observability](#10-observability)
11. [Security Model](#11-security-model)
12. [Architectural Decisions](#12-architectural-decisions)

---

## 1. System Overview

DevMind is a monorepo with two backend processes and a React frontend:

- **Django** (`backend/django`) handles GitHub OAuth, users, repositories, webhook ingestion, review orchestration (in Celery tasks), the BYOK settings API and posting comments to GitHub. It uses the Django ORM, DRF, SimpleJWT and Celery. It serves HTTP only; review status reaches the browser by polling (see [Review status updates](#review-status-updates)).
- **FastAPI** (`backend/fastapi`) runs the AI work: diff parsing, embeddings and pgvector similarity search, prompt building, the LangGraph review agent and the multi-provider LLM client.
- **Frontend** (`frontend`) is a React + Vite single-page app. It talks only to Django (`/api/v1`) and never calls FastAPI.

Celery workers call FastAPI over HTTP with a shared secret (`X-Internal-Secret`), and FastAPI calls Django's internal BYOK endpoint the same way. In `docker-compose.yml` FastAPI's port 8001 is published to the host, and Nginx proxies `/fastapi-metrics` to it. FastAPI's `/health`, `/metrics` and `/docs` are unauthenticated. The routes that do work (`/review/*`, `/embeddings/*`) reject requests without the secret with 403.

---

## 2. Service Inventory

Services defined in `docker-compose.yml`:

| Service | Image / build | Host port | Role |
|---|---|---|---|
| `migrate` | same image as Django | - | One-shot `manage.py migrate --noinput` (includes enabling pgvector); Django, FastAPI and the worker start after it exits successfully |
| `nginx` | `./nginx` | 80 | Reverse proxy: `/metrics` and `/` to Django, `/fastapi-metrics` to FastAPI |
| `django` | `backend/django` (dev target, `runserver`) | 8000 | REST API, OAuth, webhook receiver |
| `fastapi` | `backend/fastapi` (dev target, `uvicorn --reload`) | 8001 | AI service |
| `celery_worker` | same image as Django | - | Consumes queues `default`, `review`, `notifications` |
| `frontend` | `frontend` (dev target, Vite) | 5173 | Vite dev server; proxies `/api` to `django:8000` |
| `flower` | `mher/flower:2.0` | 5555 | `ops` profile. Celery monitor UI, on the same `CELERY_BROKER_URL` as the worker |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary datastore; the `core.0001_enable_pgvector` migration enables the `vector` extension |
| `redis` | `redis:7-alpine` | 6379 | Cache, Celery broker/results, LLM rate limiter |
| `prometheus` | `prom/prometheus:latest` | 9090 | `ops` profile. Scrapes Django and FastAPI via Nginx; 15-day retention |
| `grafana` | `grafana/grafana:latest` | 3000 | `ops` profile. Provisioned Prometheus datasource and `devmind-overview` dashboard |

`make up` starts every service except the three in the `ops` profile (`flower`, `prometheus`, `grafana`); `make up-ops` adds them. The `frontend` service builds the `dev` target of `frontend/Dockerfile`.

Redis database allocation (db 0 for cache and rate limiter; db 1 broker; db 2 results) is broken down in [Redis usage by database](#redis-usage-by-database). Flower reads `CELERY_BROKER_URL` too, so it watches the same broker database as the worker.

---

## 3. Network Topology

### Deployment diagram (docker-compose.yml)

The only deployment definition in the repo is `docker-compose.yml`, which builds the `dev` targets of the backend and frontend images. Ports in the labels are published to the host. All eleven services (eight by default, three more with the `ops` profile) share the default compose network and reach each other by service name.

```mermaid
flowchart TB
    Browser["Browser"]
    GH["GitHub<br/>webhooks and REST API"]
    LLM["LLM providers<br/>and Google embeddings API"]
    subgraph compose["docker-compose.yml, default network"]
        VITE["frontend :5173<br/>Vite dev server"]
        MIG["migrate<br/>one-shot, exits"]
        NGX["nginx :80"]
        DJ["django :8000<br/>runserver, dev settings"]
        CW["celery_worker<br/>queues default, review, notifications"]
        FA["fastapi :8001<br/>uvicorn --reload"]
        FL["flower :5555<br/>ops profile"]
        PG[("postgres :5432<br/>pgvector/pgvector:pg16")]
        RD[("redis :6379<br/>db 0, db 1, db 2")]
        PROM["prometheus :9090<br/>ops profile"]
        GRAF["grafana :3000<br/>ops profile"]
    end

    Browser --> VITE
    VITE -->|"proxies /api to django:8000"| DJ
    GH -->|"webhook POST, HMAC-SHA256<br/>via DEVMIND_PUBLIC_URL"| DJ
    NGX -->|"/ and /health/ and /metrics"| DJ
    NGX -->|"/fastapi-metrics to /metrics"| FA
    PROM -->|"scrape every 15s"| NGX
    GRAF -->|"queries"| PROM

    DJ -->|"enqueue tasks, db 1"| RD
    CW -->|"consume db 1, results db 2"| RD
    FL -->|"monitor broker db 1"| RD
    DJ -->|"cache db 0"| RD
    FA -->|"rate-limit counters, db 0"| RD

    MIG -->|"migrate, CREATE EXTENSION vector"| PG
    DJ --> PG
    CW --> PG
    FA -->|"asyncpg, pgvector"| PG

    CW -->|"POST /review/analyze<br/>X-Internal-Secret"| FA
    FA -->|"GET /api/v1/auth/internal/llm-configs/<br/>X-Internal-Secret"| DJ

    CW -->|"diff fetch, comment posting,<br/>repo sync, webhook install"| GH
    FA -->|"chat completions, embeddings"| LLM
    DJ -->|"BYOK key test, GET /models"| LLM
```

Notes on the diagram:

- **Nginx routes** (`nginx/nginx.conf`): `/metrics` goes to `django:8000/metrics`, `/fastapi-metrics` to `fastapi:8001/metrics`, and `/health/` and `/` to Django. Nginx has no WebSocket upgrade block and doesn't route `/api` anywhere other than Django.
- **Published ports.** Django (8000) and FastAPI (8001) are published directly as well as sitting behind Nginx. Postgres (5432) and Redis (6379) are published too, which suits local development only.
- **Webhooks.** GitHub calls whatever URL `DEVMIND_PUBLIC_URL` points to. The `make ngrok` target tunnels to port 8000, so in local development webhooks reach Django directly. Nginx's `/` route would also forward them to Django.
- **Vite** runs in the `frontend` service. Its proxy (`frontend/vite.config.ts`) forwards `/api` to `API_PROXY_TARGET`, which compose sets to `http://django:8000` (it defaults to `http://localhost:8000` when Vite runs on the host with `pnpm dev`).
- **Prometheus** scrapes both apps through `nginx:80` (`prometheus/prometheus.yml`), and Grafana reads from Prometheus with a provisioned datasource.

### Redis usage by database

All values come from the defaults in `.env.example` and `devmind/settings/base.py`; FastAPI's `redis_url` defaults to db 0 as well.

| DB | Variable | Used by | What for (verified in code) |
|---|---|---|---|
| 0 | `REDIS_URL` | Django | Django cache (`django_redis`): OAuth `state` tokens (10 min, `apps/accounts/oauth.py`) and DRF throttle counters (base settings only; development and test settings turn throttling off). `/health/` pings this connection. |
| 0 | `redis_url` | FastAPI | LLM rate-limit counters `ratelimit:{provider}:{minute}` (`services/rate_limiter.py`) |
| 1 | `CELERY_BROKER_URL` | Django, Celery worker, Flower | Task broker |
| 2 | `CELERY_RESULT_BACKEND` | Celery worker | Task results |

### Trust boundaries in this topology

- Browser traffic reaches Django only (through Vite in development). The frontend never calls FastAPI.
- Celery to FastAPI and FastAPI to Django use the shared `X-Internal-Secret` header. Calls on the compose network are plain HTTP.
- FastAPI's CORS middleware allows only `http://localhost:8000`. That stops browsers on other origins from calling it, but it isn't access control. Access control comes from the internal secret.
- FastAPI's `/health`, `/metrics` and `/docs` need no secret (`/docs` is disabled when `SENTRY_ENVIRONMENT=production`), and port 8001 is published, so anyone who can reach the host can read them.

---

## 4. End-to-End Flows

### PR review triggered by a GitHub webhook

```mermaid
sequenceDiagram
    participant GH as GitHub
    participant DJ as Django (web)
    participant RD as Redis
    participant CW as Celery worker
    participant FA as FastAPI
    participant PG as PostgreSQL

    GH->>DJ: POST /api/v1/webhooks/github/ (X-Hub-Signature-256)
    DJ->>DJ: verify HMAC-SHA256 (403 if missing, wrong, or no secret configured)
    DJ->>RD: enqueue repositories.trigger_review (queue "review")
    DJ-->>GH: 200 {"status": "accepted"}

    CW->>PG: Review exists for (repo, pr_number, head_sha)?
    alt new commit
        CW->>PG: INSERT Review (status=pending)
    end
    CW->>RD: enqueue apps.reviews.tasks.trigger_review_task

    CW->>PG: Review.status = processing
    CW->>GH: GET pull request diff (user's OAuth token)
    CW->>FA: POST /review/analyze {diff, repo_full_name, pr_number, user_id}
    FA->>FA: parse diff, similarity search per hunk (excluding this PR)
    FA->>FA: skip generated files, batch files to fit prompts (8192-token budget), run LangGraph agent per batch
    FA-->>CW: {comments[], risk_score, model_used, provider, latency_ms, analyzer_runs, files_reviewed, files_skipped}
    FA->>FA: background task: embed this PR's hunks (source_ref PR#<n>)

    CW->>PG: INSERT ReviewRun (+ diff_text) and ReviewComment rows
    CW->>PG: Review.status = completed, risk_score, summary (+ "Reviewed X of Y files"), completed_at
    CW->>RD: enqueue post_github_comments_task

    CW->>GH: POST /repos/{owner}/{repo}/pulls/{pr}/reviews (event COMMENT)
```

The orchestrator only writes status to Postgres. While a review is `pending` or `processing`, the frontend's `ReviewStatus` component polls `GET /api/v1/reviews/<id>/` every 3 seconds and stops on `completed`, `failed`, an unrecoverable error or unmount.

### Idempotency

`repositories.trigger_review` looks for an existing `Review` with the same repository, PR number and head SHA. If one exists, it doesn't create another. It re-dispatches the review task only when the existing review is `pending` or `failed`.

### Trigger: manual retrigger

`POST /api/v1/reviews/<id>/retrigger/` is available to the repository owner and only when the review is `pending` or `failed`. A review in `processing` returns 409, and a `completed` review returns 400. The view resets the review to `pending`, clears the risk score, summary and completion time, and queues `trigger_review_task`.

There is no API route for creating a review by hand. `GET /api/v1/reviews/` is read-only. (`ReviewCreateView` exists in `apps/reviews/views.py` and returns 405, but it isn't routed.)

---

## 5. AI Review Pipeline

### LangGraph agent: 4-node StateGraph

Defined in `backend/fastapi/agents/review_agent.py`:

```mermaid
flowchart TD
    START([Start]) --> AS[analyze_security<br/>LLM call]
    START --> AQ[analyze_quality<br/>LLM call]
    START --> AT[analyze_tests<br/>LLM call]
    AS --> SY
    AQ --> SY
    AT --> SY[synthesize<br/>dedupe by file + line + category<br/>sort by severity, set model_used]
    SY --> END([Return state])
```

**One pass.** The graph has no loop. A batch makes one LLM call per analyzer, so 3 calls whether or not anything is found, unless a response can't be parsed (below). A diff that fits one prompt is one batch.

**File batches.** `run_review_agent` plans the diff with `plan_batches` (`services/diff_batching.py`) before running the graph:

- Files whose path or name matches a glob in `REVIEW_SKIP_PATTERNS` (lockfiles, `*.min.js`, `*.map`, `*.snap`, `*_snapshot.json`, `*_pb2.py`, `vendor/`, `node_modules/` and similar) are skipped with reason `generated`. A diff of only such files makes no LLM call.
- The other files are packed in diff order. A file's cost is the lines it shows on its own (after the 120-per-hunk and 200-per-file caps) and the tokens of that rendering. A batch takes files while their lines total at most 600 and their tokens at most the prompt's diff budget (`diff_token_budget`, computed with the retrieved patterns). A file too big on its own gets its own batch and is trimmed by the caps as before.
- At most `REVIEW_MAX_BATCHES` (default 6) batches run; files in later batches are skipped with reason `batch_limit`.
- Batches run as concurrent tasks, at most `REVIEW_MAX_CONCURRENT_BATCHES` (default 2) at a time, so at most 6 analyzer calls are in flight. If one batch fails (for example every provider is rate limited), the others are cancelled, no partial result is returned and that batch's exception is raised, so the router still returns 429 for `AllProvidersDownError`. A batch that was waiting for a slot checks a shared flag before starting, so no batch makes calls after another has failed.
- **Deadline.** The batches must finish within `REVIEW_DEADLINE_SECONDS` (default 100), counted from the start of `POST /review/analyze` (retrieval included). Batches still running then are cancelled, the findings of finished batches are returned, and the unfinished batches' files are listed in `files_skipped` with reason `deadline`. If no batch finished, including when the deadline ran out during retrieval (then no batch is started and no LLM call is made), nothing was reviewed: the agent raises `ReviewDeadlineError` and the router returns 504 `{"error": "review_deadline"}` instead of an empty review. Django marks the review `failed` with that reason, and the Celery task retries it 60 s later, after FastAPI has stopped. No batch task outlives the request.
- **Calls per review.** 3 per batch, so 3 to 18 with the defaults, and up to twice that when every reply needs its one parse retry. With 2 batches at a time, 6 batches run in 3 rounds. Google's server key allows 15 requests per minute and Groq's 30 (`rpm_limit` in `services/llm_client.py`), and the rate limiter makes a call wait for the next minute window when the current one is full, so a 6-batch review on Google alone can wait up to 60 s once. The 100 s deadline covers that wait plus the rounds; Django's `FASTAPI_TIMEOUT_SECONDS` (default 120) leaves 20 s after it for anchoring, the response and the network. These defaults are reasoned from the rate limits above, not measured on real large PRs.
- The batches' findings are deduplicated and sorted again over the whole diff. `analyzer_runs` keeps one entry per analyzer, summing latency, tokens and attempts over batches; `parsed` is true only if every batch's reply parsed. `model_used` is the first batch's.
- The response lists `files_reviewed` and `files_skipped`. These count the files `parse_diff` returns, which are the files with added or removed lines; binary, rename-only and mode-only changes aren't counted. Django appends "Reviewed X of Y files." and the skipped files with their reasons (`coverage_line` in `apps/reviews/services/github_poster.py`) to the review summary, which is the body of the GitHub review.

A diff that fits in one batch with nothing skipped gets exactly the prompts it got before batching; `tests/test_review_golden.py` compares them byte for byte with prompts captured before the change.

**One output schema.** `ReviewFindings` and `ReviewFinding` in `models/review.py` define the reply: a JSON object `{"findings": [...]}` whose items have `file_path`, `line_number`, `category`, `severity` (the `Severity` enum: `critical`, `error`, `warning`, `info`), `body` and `suggested_fix`. `output_format_text()` generates the "Output format" part of `REVIEW_SYSTEM_PROMPT` from these models, and the parser validates every item with `ReviewFinding`, so the prompt and the parser can't disagree.

**Messages.** Each analyzer sends two messages: a system message (`REVIEW_SYSTEM_PROMPT` plus the analyzer's focus) and a user message (the prompt from `build_review_prompt`, then the analyzer's instruction). The system prompt is not repeated in the user message. Calls pass `temperature=REVIEW_TEMPERATURE` (default 0.1) and `json_mode=True`; `llm_client` turns `json_mode` into `response_format: {"type": "json_object"}` for Google, Google Vertex, Groq, OpenAI and Mistral. `custom` BYOK endpoints get no `response_format`, and the tolerant parser below handles their replies. If a provider answers a JSON-mode request with a 4xx other than 401, 403, 404 or 429 (for example Groq's 400 `json_validate_failed`), the client logs `llm.json_mode_rejected provider= model= status=` and retries the same provider once without `response_format` before failing over. JSON mode has not been checked against the live providers yet.

**Untrusted input.** The diff and each retrieved section (similar patterns, quality patterns, past reviews, repo conventions) are wrapped in `<untrusted_data source="...">` and `</untrusted_data>`. The system prompt says everything between those tags is data, never instructions, and that requests in it to ignore instructions, change the output format or return no findings must not be followed. Any `<untrusted_data` or `</untrusted_data` text inside the content has its `<` escaped as `&lt;`, so a diff can't close the block early. This reduces prompt-injection risk; it doesn't remove it.

**Retry on unparseable output only.** Each analyzer's instruction asks for only the JSON object, and for `{"findings": []}` when there are no issues. If `_parse_llm_comment_list` can't find findings in an analyzer's response (or the response is empty), that analyzer repeats its call once (`MAX_PARSE_RETRIES = 1`). The retry sends the original messages plus the model's reply as an assistant turn (left out when the reply was empty, since some OpenAI-compatible endpoints reject an empty assistant message) and a corrective user turn (`CORRECTIVE_PROMPT`: "Your previous reply was not the JSON object described in the output format. Reply with only that JSON object, or {"findings": []} if there are no issues."). The other analyzers are not re-run. An empty list of findings is a valid result, and so are a bare `[]`, `{}` and a known wrapper key set to null, such as `{"issues": null}`. A parse failure is logged as `llm_parse_failed` with the reply's length and the first 12 hex characters of its SHA-256, not its content, since a reply can quote diff code.

**Parallel branches.** The three analyzer nodes write to `security_comments`, `quality_comments` and `test_comments`, which use the `_extend_list` reducer in `agents/states.py`. All three also write `analyzer_runs` in the same step, each under its own key (`security`, `quality`, `tests`); the `_merge_dict` reducer combines them. `synthesize` then deduplicates the findings.

**`analyzer_runs`.** Each entry holds `model`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `attempts` and `parsed`. Latency and token counts are summed over attempts; token counts stay `null` if the provider never reports them. `parsed` is false when every attempt was unparseable, which tells a failed analyzer apart from one that found nothing. `POST /review/analyze` returns it as `analyzer_runs`.

**`model_used`.** `synthesize` takes the model of the first analyzer in the order security, quality, tests that has one, so the value doesn't depend on which branch finished last.

**LLM response parsing** (`_parse_llm_comment_list`):

1. Strip markdown code fences, then `json.loads`. This handles the `{"findings": [...]}` object, a bare array, or an object that wraps an array under `issues`, `comments`, `results` or `data`.
2. If that fails, extract the outermost `[...]` and parse that.

Each item is validated against `ReviewFinding` (Pydantic); items that fail validation are skipped. Severities `high`, `medium` and `low` map to `error`, `warning` and `info`; any other unknown severity becomes `warning`.

**Risk score** (`calculate_risk_score` in `routers/review.py`): the base for the highest severity (critical 70, error 45, warning 20, info 5), plus 3 for each other finding above info, at most +15, so the maximum is 85. Unknown severities count as info. Many info or warning notes can't outscore one critical finding.

### Retrieval (RAG) steps in `POST /review/analyze`

```
parse_diff(diff)                       -> DiffChunk[] (file, language, added/removed/context lines,
                                          hunks with new-file line numbers)
generate_embeddings(up to 20 hunks)  -> one batchEmbedContents call, Google gemini-embedding-001,
                                          task_type RETRIEVAL_QUERY, outputDimensionality 768
for each query embedding:
    search_similar_by_embedding(..., repo, top_k=5, threshold=0.6, exclude_source_ref="PR#<n>")
                                       -> ordered by pgvector cosine distance (HNSW index)
merge results                          -> drop untagged rows with file_path "PR#<n>",
                                          drop results whose whitespace-normalized text equals a hunk
                                          of this diff, dedupe by text (keep highest similarity),
                                          keep the top 5
plan_batches(chunks, ...)             -> skip generated files, pack the rest into batches that each
                                          fit one prompt (see "File batches")
build_review_prompt(...)  per batch   -> user message, 8192-token budget (tiktoken cl100k_base; the
                                          system prompt is sent separately and not counted); diff first,
                                          then similar patterns, quality patterns, past reviews, conventions,
                                          each in untrusted-data delimiters
run_review_agent(...)                  -> the graph once per batch, results merged
anchor_comments(chunks, comments)      -> keep comments on added/context lines; see "Comment anchoring"
store_review_async(...)                -> background task after the response is built: of up to 20
                                          chunks, drop those whose sha256 is already stored, embed
                                          the rest in one batchEmbedContents call (RETRIEVAL_DOCUMENT,
                                          768 dims), insert each with source_ref="PR#<n>"; an
                                          IntegrityError or DataError on one chunk is rolled back and
                                          the rest are still stored, any other database error stops
                                          the task
```

Nothing is stored before the search, and rows tagged with the current PR's `source_ref` are filtered out in SQL (`source_ref IS DISTINCT FROM 'PR#<n>'`, so untagged rows are kept). That keeps a review, including a re-review after a new push, from retrieving its own diff. When `pr_number` is 0, chunks are stored with no `source_ref` and nothing is excluded. The duplicate check compares against every hunk in the diff, even though only the first 20 are used as queries. Files matching `REVIEW_SKIP_PATTERNS` aren't used as queries, so a lockfile can't take query slots. Retrieval runs once per review, and every batch's prompt gets the same retrieved patterns.

**Transition gap:** rows written before `source_ref` existed carry no tag, and hunk rows used real file paths. If a PR was reviewed before the change and gets a new push afterwards, its old hunks can still be retrieved for it, unless their text exactly matches a hunk in the new diff.

Each retrieved chunk is logged as `review.rag_context.retrieved` with repo, PR number, file path and similarity. Chunk text and the query are not logged, and the SQLAlchemy engine sets `hide_parameters=True` so bound values stay out of database error messages.

The handler runs the search inside a `try`. A failure in embedding or search is logged as `review.rag_context_partial`, and the review continues without similar-code context.

### Diff rendering and comment anchoring

`format_diff_chunks` (`services/prompt_builder.py`) renders each hunk line with its new-file number: `L42 + code` for added lines, `L41   code` for context lines, and `- code` with no number for removed lines. The system prompt asks the model to use only numbers shown in the diff.

The rendered diff is trimmed to fit the prompt:

- At most 120 lines per hunk, 200 per file and 600 in total are shown. Lines longer than 300 characters are cut.
- Every file first gets its best line (an added line, else a removed line, else context), as long as the total allows one line per file, so a deletion-only file isn't hidden by other files' added lines. The rest of the total is spent on added lines, then removed lines, then context lines nearest a change. Each of those is shared evenly between files, so context lines in early files can't crowd out changes in later ones.
- The token budget for the diff is what's left after the diff's delimiters, the predicted size of the similar-pattern, quality-pattern, past-review and conventions sections (each with its header and delimiters), and a 200-token margin. It is never less than half the prompt.
- Retrieved sections get at most 2000 (similar patterns), 1500 (quality patterns), 1000 (past reviews) and 500 (conventions) tokens of text, counted after their header and delimiters. A section that doesn't fit is left out. If the assembled prompt is still over budget, it is cut at a line boundary and an untrusted block left open by the cut is closed.
- If the rendering is over that budget, the line total is lowered and the diff is rendered again, scaling down from the lines the diff can show (at most 600), so a single large file shrinks too. If headers alone are too big, the text is cut at a line boundary with a marker.
- Each gap is marked `... N lines omitted`, and a final `[N files / M lines omitted from this diff]` line says how much was left out.

`anchor_comments` (`services/comment_anchoring.py`) runs on the agent's comments before the risk score is computed:

- a comment on an added or context line of its file is kept as is (`anchored`);
- a comment within 3 lines of exactly one hunk is moved to the nearest line of that hunk (`snapped`). Its `suggested_fix` is moved into the body as a plain code block, so GitHub doesn't offer it as a one-click suggestion on a different line;
- any other comment, including one between two hunks that are both within 3 lines, gets `line_number` 0 (`unanchored`). The GitHub poster puts it in the review body.

The counts are logged as `review.anchoring` and returned in the response as `anchored`, `snapped` and `unanchored`.

Embeddings are cached in process by an LRU cache (`_BoundedCache`, max 1000 entries) keyed by `sha256(f"{task_type}:{text}")`; only texts not in the cache are sent. All embedding calls share one `httpx.AsyncClient` (30 s timeout), closed on app shutdown. No database session is open while an embedding call is in flight: queries are embedded before the search session opens, and the store task closes its duplicate-check session before embedding.

**Embedding model change:** the default `EMBEDDING_MODEL` is `gemini-embedding-001` (Google retired `text-embedding-004`), requested with `outputDimensionality` 768 to fit `Vector(768)`. Vectors from the two models aren't comparable, so `code_embeddings` rows written before the switch should be deleted or re-embedded; nothing does this automatically. `gemini-embedding-001` vectors below 3072 dimensions aren't normalized, which doesn't affect cosine distance.

**Setup gap:** the `core.0001_enable_pgvector` migration enables the `vector` extension, but nothing creates the `code_embeddings` / `review_embeddings` tables (`models/embeddings.py` defines them; nothing calls `create_all`). On a fresh database the retrieval steps fail and get logged, and reviews run without retrieved context.

### LLM provider failover

```mermaid
flowchart LR
    A[generate] --> B[GET Django internal BYOK endpoint<br/>user's active configs, by priority]
    B --> C[User providers<br/>OpenAI-compatible chat/completions]
    C -->|429 / 404 / 5xx / non-200 / timeout| D[Google GOOGLE_MODEL<br/>default gemini-3.5-flash]
    D -->|fail| E[Groq GROQ_MODEL<br/>default openai/gpt-oss-120b]
    E -->|fail| G[AllProvidersDownError<br/>FastAPI responds 429]
```

- A server provider is included only if its key (`GOOGLE_AI_API_KEY`, `GROQ_API_KEY`) is set. GitHub Models was retired on 2026-07-30 and was removed.
- Model IDs come from settings (`core/config.py`). A 404 is logged as `llm.model_not_found` and fails over like any other error. The cause is a retired or misspelled model, or one closed to new keys. `make providers-check` sends a real chat request to each configured model, which makes it the authoritative check. A model that appears in a provider's `/models` listing (as `/health` reports) may still be unusable. There is no server-side OpenAI provider; OpenAI is available only as a user BYOK provider.
- BYOK providers are mapped to an OpenAI-compatible base URL: `openai`, `groq`, `mistral`, `google_vertex`, or `custom` with an explicit URL. `anthropic` isn't mapped, so Anthropic configs are skipped with an `llm.byok_unsupported_provider` warning (Django's BYOK choices have no GitHub Models option).
- `LLM_FAILOVER_ENABLED=False` uses only the first provider in the chain.

**Rate limiting** (`services/rate_limiter.py`): a fixed one-minute window per provider, using the Redis key `ratelimit:{provider}:{minute}` with atomic `INCR` and a 60-second expiry. Default limits are Google 15 RPM and Groq 30; BYOK providers get 30. When a window is full, the call **sleeps until the next minute** rather than failing over. If Redis is unavailable, the limiter lets the request through.

---

## 6. Authentication and Authorization

### GitHub OAuth flow

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant DJ as Django
    participant RD as Redis (cache)
    participant GH as GitHub

    FE->>DJ: GET /api/v1/auth/github/start/
    DJ->>RD: cache oauth_state:{token} (TTL 600s)
    DJ-->>FE: {authorize_url} (scope repo,user)
    FE->>GH: redirect to authorize_url
    GH-->>FE: redirect to OAuth App callback (/auth/callback?code&state)
    FE->>DJ: GET /api/v1/auth/github/callback/?code=...&state=...
    DJ->>RD: check state exists, then delete (single use)
    DJ->>GH: POST /login/oauth/access_token
    DJ->>GH: GET /user
    DJ->>DJ: upsert CustomUser, store GithubToken (encrypted)
    DJ-->>FE: {access, refresh}
```

The state token comes from `secrets.token_urlsafe(32)` (`apps/accounts/oauth.py`). The redirect target is the callback URL configured on the GitHub OAuth App; Django doesn't send a `redirect_uri`.

### JWT configuration (`SIMPLE_JWT` in `devmind/settings/base.py`)

| Parameter | Value |
|---|---|
| Algorithm | `JWT_ALGORITHM`, default HS256 |
| Signing key | `JWT_SECRET_KEY` |
| Access lifetime | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, default 60 |
| Refresh lifetime | `JWT_REFRESH_TOKEN_EXPIRE_DAYS`, default 30 |
| Rotation / blacklist | `ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION` both on |

The frontend stores both tokens in `localStorage` and refreshes on 401 (`frontend/src/api/client.ts`).

### Review status updates

There are no WebSockets. `devmind/asgi.py` is the plain Django ASGI app, the production image runs `gunicorn devmind.wsgi:application`, and Nginx has no upgrade block. The browser reads status through the same JWT-authenticated REST endpoint as everything else, so the ownership checks on `GET /api/v1/reviews/<id>/` apply. While a review is `pending` or `processing`, the frontend's `ReviewStatus` component polls `GET /api/v1/reviews/<id>/` every 3 seconds and stops on `completed`, `failed` or unmount. Each request waits for the previous one. A 403 or 404 stops polling at once. A 5xx or network failure backs off: the next request waits 3, 6, 12, 24, 48 and then 60 seconds, and polling gives up after 10 consecutive failures. A successful request resets the backoff. When polling stops on an error, the badge keeps the last known status and shows "Status updates stopped". A 401 is handled by the API client's token-refresh interceptor. On the review page, a change to `completed` or `failed` refetches the review, so the summary and comments appear without a reload. If that refetch fails, the page keeps the review it already shows and adds an inline notice: "Couldn't load the final results. Reload to try again." A response that arrives after the page has moved to a different review is ignored. The loop is in `frontend/src/lib/reviewStatusPolling.ts`; the page's load and refetch logic is in `frontend/src/lib/reviewLoader.ts`.

### Service-to-service authentication

- Header: `X-Internal-Secret: <FASTAPI_INTERNAL_SECRET>`
- FastAPI checks it with `hmac.compare_digest` (`core/security.py`) on the `/review` and `/embeddings` routers. An empty secret on either side counts as a failure (403).
- Django's `InternalLLMConfigListView` applies the same check to `GET /api/v1/auth/internal/llm-configs/`. That endpoint returns decrypted BYOK keys to FastAPI.

### DRF defaults

- Authentication: JWT only. Default permission: `IsAuthenticated`.
- Throttling in `base.py`: anonymous 100/hour, authenticated `API_GLOBAL_RATE_LIMIT`/hour (default 1000). The development and test settings turn throttling off.
- Pagination: `PageNumberPagination`, page size 20.

---

## 7. GitHub Integration

### Webhook handling

Endpoint: `POST /api/v1/webhooks/github/`. It has no JWT authentication (`authentication_classes = []`) and requires an HMAC signature (`apps/repositories/webhooks.py`).

```python
configured_secret = settings.GITHUB_WEBHOOK_SECRET or ""
if not configured_secret:
    raise WebhookVerificationError(...)          # -> 403
expected = "sha256=" + hmac.new(secret, request.body, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, signature_header):
    raise WebhookVerificationError(...)          # -> 403
```

| Event | Action | Behavior |
|---|---|---|
| `pull_request` | `opened`, `synchronize`, `reopened` | Repo must be known, active and `review_enabled`; enqueue `repositories.trigger_review` |
| `pull_request` | anything else | Ignored |
| `ping` | - | Logged |
| any other event | - | Ignored |

### Webhook lifecycle

```mermaid
flowchart LR
    A[POST /repositories/connect/] --> B[repositories.initial_sync]
    B --> C[Upsert Repository rows from GitHub]
    C --> D[repositories.install_webhook per repo without webhook_id]
    D --> E[POST /repos/owner/repo/hooks<br/>events: pull_request, push<br/>url: DEVMIND_PUBLIC_URL/api/v1/webhooks/github/]
    E --> F[Store webhook_id]
```

`install_webhook_task` skips repositories that already have a `webhook_id`. It retries GitHub rate-limit errors after one hour (`RATE_LIMIT_RETRY_COUNTDOWN = 3600`) and other failures up to 5 times. `remove_webhook_task` exists, but only the Django admin calls it; there is no API route for disconnecting a repository.

### Comment posting

`GitHubPoster` (`apps/reviews/services/github_poster.py`):

- Comments with `line_number > 0` are posted inline (`line`, `side: RIGHT`), grouped by file and sent in batches of 50 per review.
- Comments without a usable line number are folded into the review body. FastAPI sets `line_number` to 0 for any comment it could not anchor to a diff line.
- If GitHub returns 422 for an inline batch, the poster retries the batch as a body-only review so the findings still appear.
- Every review is posted with `event: COMMENT`, so DevMind never approves a PR or requests changes.

---

## 8. Data Model

### Django entities

Fields are taken from the models in `apps/accounts`, `apps/repositories` and `apps/reviews`. The diagram shows selected fields: timestamps (`created_at`, `updated_at`), auth bookkeeping (`password`, `last_login`, `is_superuser`) and descriptive text such as `Repository.description` are left out to keep it readable. `encrypted` marks an `EncryptedCharField`: a `varchar` column holding a Fernet token.

```mermaid
erDiagram
    CustomUser {
        bigint id PK
        varchar email UK
        bigint github_id UK "nullable"
        varchar github_login
        varchar avatar_url
        bool is_active
        bool is_staff
    }
    GithubToken {
        bigint id PK
        bigint user_id FK, UK "one-to-one"
        encrypted access_token
        varchar token_type
        varchar_array scopes
        timestamptz expires_at "nullable"
    }
    UserLLMConfig {
        bigint id PK
        bigint user_id FK
        varchar provider
        varchar model_name
        encrypted api_key
        varchar base_url
        bool is_active
        int priority
    }
    Repository {
        bigint id PK
        bigint github_id UK
        varchar full_name
        varchar name
        bigint owner_id FK
        bool is_private
        varchar default_branch
        varchar html_url
        varchar clone_url
        varchar language
        jsonb topics
        int stargazers_count
        bigint webhook_id "nullable, null means not installed"
        bool is_active
        bool review_enabled
        timestamptz last_synced_at "nullable"
    }
    Review {
        bigint id PK
        bigint repository_id FK
        int pr_number
        varchar pr_title
        varchar head_sha
        varchar base_sha
        varchar diff_url
        varchar status
        int risk_score "nullable, 0-100"
        text summary
        timestamptz completed_at "nullable"
    }
    ReviewRun {
        bigint id PK
        bigint review_id FK, UK "one-to-one"
        int agent_iterations
        varchar model_used
        int prompt_tokens
        int completion_tokens
        int latency_ms
        text diff_text
    }
    ReviewComment {
        bigint id PK
        bigint review_id FK
        varchar file_path
        int line_number
        varchar severity
        varchar category
        text body
        text suggested_fix
    }

    CustomUser ||--o| GithubToken : has
    CustomUser ||--o{ UserLLMConfig : owns
    CustomUser ||--o{ Repository : owns
    Repository ||--o{ Review : has
    Review ||--o| ReviewRun : produces
    Review ||--o{ ReviewComment : contains
```

Constraints the diagram can't show:

- `UserLLMConfig`: unique on `(user, provider, model_name)`, default ordering `priority`, then newest first.
- `Review` has no unique constraint on `(repository, pr_number, head_sha)`. Duplicate webhooks are filtered in `repositories.trigger_review` instead (see [Idempotency](#idempotency)).
- `Repository.github_id` is unique, so a GitHub repository has exactly one DevMind owner. `initial_sync` upserts by `github_id` and sets `owner` to the syncing user, so a second user syncing the same repository takes it over.
- Deleting a user cascades to their token, LLM configs and repositories (and so their reviews).

### Indexes

| Table | Index |
|---|---|
| `reviews_review` | `(repository, pr_number)`, `(completed_at)`, `status` |
| `reviews_reviewcomment` | `(review, severity)`, `(review, file_path, line_number)` |
| `repositories_repository` | `(owner, is_active)`, `(github_id)`, `full_name`, `is_active` |

### FastAPI tables (SQLAlchemy, `models/embeddings.py`)

FastAPI owns two pgvector tables in the same Postgres database. They are defined only in SQLAlchemy, have no Django model and no migration that creates them, and aren't joined to Django tables by any foreign key.

```mermaid
erDiagram
    code_embeddings {
        bigint id PK
        varchar repo_full_name "indexed, logical ref to Repository.full_name"
        varchar file_path
        text chunk_text
        varchar language "indexed"
        varchar chunk_type
        vector embedding "Vector(768)"
        varchar sha256 UK "dedupe key for the chunk text"
        varchar source_ref "nullable, e.g. PR#12"
        timestamptz created_at
    }
    review_embeddings {
        bigint id PK
        bigint review_id UK "indexed, logical ref to Review.id"
        bigint user_id "indexed, logical ref to CustomUser.id"
        varchar code_hash "indexed"
        text feedback_text
        varchar language
        vector embedding "Vector(768)"
        jsonb extra_data "nullable"
        timestamptz created_at
    }
    Repository {
        bigint id PK
        varchar full_name
    }
    Review {
        bigint id PK
    }
    CustomUser {
        bigint id PK
    }

    Repository |o..o{ code_embeddings : "full_name, logical only"
    Review |o..o| review_embeddings : "review_id, logical only"
    CustomUser |o..o{ review_embeddings : "user_id, logical only"
```

The dotted lines are **logical references, not foreign keys**. Nothing enforces that the Django row exists, and deleting a Django repository or review leaves its embeddings in place.

- `code_embeddings.repo_full_name` is the `repo_full_name` the Celery worker sends to `POST /review/analyze`. It holds a name, not an ID, so when `initial_sync` picks up a renamed repository, its older chunks stay under the old name. After each review, a background task writes up to 20 diff chunks here with `source_ref` `PR#<number>` (none when `pr_number` is 0). Older versions also wrote one untagged row for the first 1000 characters of the diff (`file_path` `PR#<number>`, `chunk_type` `pr`); retrieval skips those rows for the PR being reviewed.
- `review_embeddings.review_id` and `user_id` are meant to hold Django `Review` and `CustomUser` IDs, but nothing in the application writes this table today. `VectorStore.store_review_embedding` is only called from tests, and the `/review/analyze` request carries `user_id` but no review ID. As a result, the "past reviews" section of the prompt is always empty.

There are B-tree indexes on `repo_full_name`, `language`, `review_id`, `user_id` and `code_hash`. `code_embeddings.embedding` has an HNSW index with `vector_cosine_ops` (`ix_code_embeddings_embedding_hnsw`) for the cosine-distance `ORDER BY ... LIMIT` in similarity search. The planner still picks a sequential or `repo_full_name` scan when it estimates that to be cheaper, which it did on a local 20,000-row table. Each search session runs `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector 0.8+), so when the index is used it keeps scanning until enough rows pass the repository and `source_ref` filters; results are re-sorted by similarity in Python because `relaxed_order` can return them slightly out of order. On an older pgvector the `SET` fails, is logged once as `vector_store.iterative_scan_unavailable`, and search runs without it. As noted in section 5, nothing in the repo creates these tables yet. For a table created by hand, apply `backend/fastapi/migrations/sql/0001_code_embeddings_source_ref.sql` (adds `source_ref`) and `0002_code_embeddings_hnsw_index.sql` (adds the HNSW index) in order. Both are idempotent and must be applied by hand.

### Enum values

- `Review.status`: `pending`, `processing`, `completed`, `failed`
- `ReviewComment.severity`: `info`, `warning`, `error`, `critical`
- `ReviewComment.category`: `security`, `quality`, `tests`, `style`, `performance`
- `UserLLMConfig.provider`: `openai`, `anthropic`, `google_vertex`, `mistral`, `custom`

---

## 9. Reliability and Failure Handling

### Retry strategy

| Layer | Mechanism |
|---|---|
| Orchestrator to FastAPI | tenacity: 3 attempts, exponential backoff 5-60s, on connection errors (connect error, connect or pool timeout), 502 and 503 only. Not retried there: a read timeout (FastAPI may still be reviewing, and a retry would start a second review), 500 (it can come after all of a review's LLM calls, up to 18, which a retry would repeat), 504 `review_deadline` (nothing was reviewed in time), 429 (FastAPI asks for 60 s) and 403. The Celery task's own retry, 60 s later, handles these. Django warns at startup (`reviews.W001`) unless `FASTAPI_TIMEOUT_SECONDS` is at least 10 s above `REVIEW_DEADLINE_SECONDS`; the check reads `REVIEW_DEADLINE_SECONDS` from Django's environment, so it assumes both services share it through the same `.env`, as they do in docker-compose. One rare duplicate-work path remains: if retrieval hangs past Django's timeout, the Celery retry can start while the first request is still running, since the deadline only cuts off batches. |
| `apps.reviews.tasks.trigger_review_task` | Celery `max_retries=3`, 60s delay. Resets a `failed` review to `pending` before each retry; on the final attempt it stays `failed`. |
| `post_github_comments_task` | Celery `max_retries=3`, independent of the review task |
| `repositories.trigger_review` | Celery `max_retries=3`, `acks_late=True` |
| `repositories.install_webhook` | Celery `max_retries=5`; 1-hour countdown on GitHub rate limits |
| GitHub API calls in `GitHubService` | tenacity retries on transient server errors |

### Review status machine

```mermaid
stateDiagram-v2
    [*] --> pending: Review row created by Celery task
    pending --> processing: orchestrator starts
    processing --> completed: FastAPI result saved
    processing --> failed: any exception
    failed --> pending: Celery retry (retries left) or retrigger API
```

### Graceful degradation

| Failure | Behavior |
|---|---|
| Redis unavailable (FastAPI) | Rate limiter logs and lets the request through |
| Status poll request fails | 403 or 404: `ReviewStatus` stops polling and shows "Status updates stopped". 5xx or network error: retries with backoff (3 s doubling to 60 s) and stops after 10 consecutive failures |
| Refetch after a terminal status fails | The review page keeps the review on screen and shows "Couldn't load the final results. Reload to try again." |
| An LLM provider fails | Next provider in the chain; all failed means FastAPI returns 429 and the review fails |
| Embedding/search fails | Logged; review runs without retrieved context |

### Celery queues

Routes from `CELERY_TASK_ROUTES` in `base.py`:

| Queue | Tasks |
|---|---|
| `review` | `repositories.trigger_review` |
| `default` | `apps.reviews.tasks.trigger_review_task`, `post_github_comments_task`, `cleanup_old_reviews`, `repositories.initial_sync`, `install_webhook`, `remove_webhook`; also the default for unrouted tasks |
| `notifications` | Consumed by the worker; no task is currently routed to it |

There is no Celery beat service, so `cleanup_old_reviews` runs only if someone calls it.

---

## 10. Observability

### Metrics endpoints

| Endpoint | Source |
|---|---|
| `/metrics` (Django, also via Nginx) | `django_prometheus` middleware and URLs |
| `/metrics` on FastAPI, `/fastapi-metrics` via Nginx | `prometheus_fastapi_instrumentator` |

`prometheus/prometheus.yml` scrapes both through `nginx:80` every 15 seconds.

Recorded metrics:

- **Django:** only the HTTP metrics from django-prometheus (for example `django_http_requests_total_by_view_transport_method_total` and `django_http_requests_latency_seconds_by_view_method`). Django defines no custom metrics.
- **FastAPI HTTP:** `http_requests_total` and `http_request_duration_seconds` from the instrumentator.
- **FastAPI custom** (`core/metrics.py`, recorded in `routers/review.py`): `agent_iterations_total` (one per `POST /review/analyze`), `rag_pipeline_duration_ms` (successful reviews only) and `review_errors_total` by `error_type`.

**Grafana:** the provisioned "DevMind Overview" dashboard (`grafana/provisioning/dashboards/devmind-overview.json`) charts Django and FastAPI request rate and p50/p95/p99 latency, plus the three FastAPI review metrics. There are no Celery or LLM-token metrics.

### Logging

Django logs to the console with a `verbose` text formatter. Some modules use `structlog`. FastAPI configures logging in `core/logging.py` at startup.

### Health checks

| Endpoint | Checks | Response |
|---|---|---|
| Django `GET /health/` | DB connection, Redis `PING` | Always HTTP 200; body reports `db` / `redis` as `ok` or `error` |
| FastAPI `GET /health` | `SELECT 1`, pgvector extension present, `GET /models` on each configured server provider | 503 if DB or pgvector check fails, else 200. Exception details are logged server-side and not returned. |

### Error tracking

Each service calls `sentry_sdk.init` when its DSN (`SENTRY_DSN_DJANGO` / `SENTRY_DSN_FASTAPI`) is non-empty. `traces_sample_rate` defaults to 0.1.

---

## 11. Security Model

To report a vulnerability, follow [SECURITY.md](../SECURITY.md).

### Trust boundaries

```
Browser -> Django                 JWT (Bearer), DRF throttling (base settings), CORS allow-list
GitHub  -> Django webhook         HMAC-SHA256; rejected when no secret is configured
Celery  -> FastAPI work routes    X-Internal-Secret, constant-time compare
FastAPI -> Django BYOK endpoint   X-Internal-Secret, constant-time compare
User-supplied BYOK base_url      https + public-address check in Django on save and before
                                  the key test; FastAPI calls the stored URL without
                                  re-validating it (rows saved before the check are unguarded)
```

### Encryption at rest

| Data | Mechanism |
|---|---|
| `GithubToken.access_token` | `EncryptedCharField`: Fernet with a key derived from `SECRET_KEY` (HKDF-SHA256, fixed salt) |
| `UserLLMConfig.api_key` | Same field type and key |

There's no separate encryption-key variable. Changing `DJANGO_SECRET_KEY` makes existing tokens and API keys impossible to decrypt.

### Where secrets leave the server

- `GET /api/v1/auth/github/token/` returns the authenticated user's decrypted GitHub token to the browser.
- `GET /api/v1/auth/internal/llm-configs/` returns decrypted BYOK keys to FastAPI (secret-protected).

### Input validation

- The webhook signature is verified before the payload is dispatched.
- BYOK `base_url` is validated in the serializer and again right before the key-test request (`validate_public_https_url`). It must be https, and every resolved address must be public. DNS rebinding between check and use isn't covered, as the code comments say.
- `ReviewOrchestrator._save_results` maps unknown categories to `quality` and unknown severities to `info` before inserting.
- LLM output is validated with Pydantic before it reaches the response model.

### BYOK key validation

When a user creates a config, `_validate_provider_key` sends `GET <base>/models` to the provider, and keys that fail are rejected. The test settings skip this (`SKIP_LLM_KEY_VALIDATION=True`).

---

## 12. Architectural Decisions

Each decision lists what the code does, why, and the trade-offs. Some also note what would change at larger scale; those notes are considerations, not plans or measured limits.

- [Two backends (Django + FastAPI)](#two-backends-django--fastapi)
- [Celery for review jobs](#celery-for-review-jobs)
- [LangGraph for the review agent](#langgraph-for-the-review-agent)
- [pgvector instead of a dedicated vector database](#pgvector-instead-of-a-dedicated-vector-database)
- [Redis-backed LLM rate limiter](#redis-backed-llm-rate-limiter)
- [Storing the diff in `ReviewRun.diff_text`](#storing-the-diff-in-reviewrundiff_text)
- [Removing Kafka instead of keeping it as unused infrastructure](#removing-kafka-instead-of-keeping-it-as-unused-infrastructure)
- [Removing the organizations app](#removing-the-organizations-app)
- [BYOK-first LLM failover with server providers as fallback](#byok-first-llm-failover-with-server-providers-as-fallback)
- [Token encryption with Fernet and a key derived from SECRET_KEY](#token-encryption-with-fernet-and-a-key-derived-from-secret_key)
- [JWTs in localStorage](#jwts-in-localstorage)
- [GitHub OAuth App and per-repository webhooks instead of a GitHub App](#github-oauth-app-and-per-repository-webhooks-instead-of-a-github-app)
- [Polling instead of WebSockets for review status](#polling-instead-of-websockets-for-review-status)
- [One Redis instance in several roles](#one-redis-instance-in-several-roles)
- [Shared-secret service-to-service authentication](#shared-secret-service-to-service-authentication)

### Two backends (Django + FastAPI)

**What:** Django owns the user-facing API and data. FastAPI owns the LLM and vector work.

**Why:** Django provides the ORM, admin, DRF and Celery integration needed for CRUD, OAuth and background jobs. The AI path is I/O-bound, with concurrent LLM calls and async database queries, which suits an async framework with Pydantic models.

**Tradeoffs:** two dependency sets and images, a shared secret to keep in sync, and an HTTP hop between them.

### Celery for review jobs

**What:** Webhook handling only queues work; reviews run in Celery tasks.

**Why:** A review involves several LLM calls and can take much longer than a webhook delivery should wait. Queuing lets the webhook return immediately and keeps slow reviews from tying up web workers.

**Tradeoffs:** another moving part (broker and workers), and results reach the UI only when it fetches them.

### LangGraph for the review agent

**What:** The review is a `StateGraph` with typed state and parallel analyzer branches that merge in one `synthesize` node.

**Why:** The graph makes the pipeline explicit, so each node can be tested in isolation, and adding an analyzer means adding a node and two edges.

**Tradeoffs:** Parallel branches need explicit reducers. Without `_extend_list`, results from all but one analyzer are lost.

### pgvector instead of a dedicated vector database

**What:** Embeddings live in the same PostgreSQL instance as everything else.

**Why:** It avoids a second datastore to run, back up and secure. The interface is contained in `services/vector_store.py`.

**Tradeoffs:** shared connection pool; the HNSW index is approximate, and the repository and `source_ref` filters are applied to the rows it returns. Iterative scans (pgvector 0.8+) make up for filtered-out rows up to pgvector's `hnsw.max_scan_tuples` limit; without them a filtered search can return fewer than `top_k` rows when most near neighbours belong to other repositories.

### Redis-backed LLM rate limiter

**What:** Per-provider RPM counters live in Redis rather than in process memory.

**Why:** Each uvicorn worker has its own memory, so in-process counters would let every worker use the full provider limit.

**Tradeoffs:** If Redis fails, rate limiting turns off. Over-limit calls sleep until the next minute instead of trying another provider.

### Storing the diff in `ReviewRun.diff_text`

**What:** The diff sent to FastAPI is saved with the review run.

**Why:** The review page can render the diff without calling GitHub again with the user's token.

**Tradeoffs:** unbounded `TextField`, no compression or size cap.

### Removing Kafka instead of keeping it as unused infrastructure

**What:** Commit `cd590b5` removed the Kafka producer (`devmind/kafka.py`), its call sites in the webhook handler and the orchestrator, the `confluent-kafka` dependency, the `KAFKA_BOOTSTRAP_SERVERS` setting and the `kafka` compose service. Commit `ab47a35` removed the `celery_beat` service for the same reason: no periodic tasks were defined.

**Why:** The producer published events such as `devmind.pr.opened` and `devmind.review.completed` fire-and-forget, but nothing consumed them. No consumer exists anywhere in the git history. The broker added a container, a dependency, settings and tests while doing no work that anything depended on.

**Tradeoffs:** There's no event log for a future consumer such as analytics or an audit trail. Adding one means re-adding the producer calls as well as the broker. Celery tasks are now the only asynchronous path.

**What would change at larger scale:** If several independent consumers need the same events, a durable event stream could be worth reintroducing. With a single consumer per event, a Celery task covers the same need.

### Removing the organizations app

**What:** `apps.organizations` (organizations, team memberships, org-repository links, Redis-backed invites, and the `send_invite_email_task` and `sync_org_members_task` Celery tasks) was removed along with its `organizations/` routes. Migration `core.0002_drop_organizations_tables` drops its three tables if they exist, deletes its rows from `django_migrations`, and deletes its content types, which cascades to their permissions and any user or group grants of them.

**Why:** No user flow reached it. The frontend never called its routes, no other app imported it, nothing called `sync_org_members_task`, and membership granted no access because repository, review and scan views all filter by `Repository.owner`.

**Tradeoffs:** The migration's reverse is a no-op, so rolling back doesn't bring the tables or their data back. Any organization data on an existing database is deleted when the migration runs.

### BYOK-first LLM failover with server providers as fallback

**What:** For each LLM call, `LLMClient.generate` (`backend/fastapi/services/llm_client.py`) fetches the user's active BYOK configs from Django's internal endpoint, ordered by `priority`, and puts them ahead of the server chain: Google, then Groq, with models from settings (defaults `gemini-3.5-flash`, `openai/gpt-oss-120b`). GitHub Models was retired on 2026-07-30 and was removed. Each server provider is included only if its key is set. A 429, a 404 (logged as `model_not_found`), a 5xx, any other non-200 status or a timeout moves the call to the next entry. All entries are called through the OpenAI-compatible `/chat/completions` API.

**Why:** A user's own key is used whenever it works, and a review still runs when it doesn't, or when the user has none. One request format covers every provider, so adding a provider means adding a base URL.

**Tradeoffs:**
- Failover is silent. An invalid or revoked user key (401) and a failed BYOK fetch (the client logs it and returns an empty list) both fall through to the server's keys, so the server pays for that review.
- The BYOK configs are fetched from Django on every `generate` call. Each pass makes three calls (one per analyzer) and the agent can make up to three passes, so one review can make up to nine internal requests that return decrypted keys.
- Providers without an OpenAI-compatible endpoint, such as Anthropic, are skipped.
- When a provider's per-minute window is full, the rate limiter waits for the next minute instead of moving to the next provider.

**What would change at larger scale:** Caching the BYOK configs per review, and surfacing to the user which provider actually served a review (the response already includes `model_used` and `provider`), would reduce internal traffic and make silent fallbacks visible.

### Token encryption with Fernet and a key derived from SECRET_KEY

**What:** `EncryptedCharField` (`apps/accounts/encryption.py`) encrypts GitHub OAuth tokens and BYOK API keys with Fernet. The Fernet key is derived from Django's `SECRET_KEY` with HKDF-SHA256, using the salt `b"devmind-github-token-encryption-v1"` and the info string `b"fernet-encryption-key"`, both hard-coded.

**Why:** Database rows and backups don't hold plaintext secrets, and there's no extra key to provision: any deployment with a `SECRET_KEY` can encrypt.

**Tradeoffs:**
- **Rotation.** There's one key and no key list (`MultiFernet`) or re-encryption command. Changing `DJANGO_SECRET_KEY` makes every stored token and API key undecryptable, and `from_db_value` doesn't catch the resulting `InvalidToken`, so reading those rows raises.
- **Coupled secrets.** `SECRET_KEY` both signs Django data and protects these credentials, so anyone who has it and a database copy can decrypt everything.
- **Hard-coded salt.** The salt is in source, and the code comment says it should move to an environment variable in production. HKDF doesn't need a secret salt, so the real protection is the secrecy of `SECRET_KEY`. Changing the salt has the same effect as changing the key.

**What would change at larger scale:** A dedicated encryption key (or a key-management service) separate from `SECRET_KEY`, with `MultiFernet` to decrypt with old keys while re-encrypting with a new one, would allow rotation without data loss.

### JWTs in localStorage

**What:** SimpleJWT issues an access token (60 minutes by default) and a refresh token (30 days by default, rotated and blacklisted after rotation). The frontend stores both in `localStorage` and sends `Authorization: Bearer` (`frontend/src/api/client.ts`).

**Why:** It's the simplest setup for a SPA: the axios client adds the header in one interceptor and refreshes on 401, and the API needs no cookie or CSRF configuration. Because the browser never attaches a bearer token on its own, the JWT-authenticated API isn't exposed to CSRF.

**Tradeoffs:** Any script that runs on the frontend's origin can read both tokens. A stolen refresh token stays usable for up to 30 days unless it's rotated or blacklisted first, and with an access token an attacker can also call `GET /api/v1/auth/github/token/`, which returns the user's decrypted GitHub token (scope `repo,user`). Neither `nginx.conf` nor the Django settings set a Content-Security-Policy.

**What would change at larger scale:** Moving the refresh token to an `HttpOnly`, `Secure`, `SameSite` cookie (with CSRF protection on the refresh endpoint), adding a CSP, and removing the GitHub-token endpoint would shrink what a single XSS bug exposes.

### GitHub OAuth App and per-repository webhooks instead of a GitHub App

**What:** Users sign in through a GitHub OAuth App with scope `repo,user`. `POST /repositories/connect/` queues `initial_sync`, which lists every repository the token can see (`/user/repos?type=all`) and queues `install_webhook` for each one without a `webhook_id`. That task calls `POST /repos/{owner}/{repo}/hooks` with the user's token, subscribing to `pull_request` and `push` and using the single `GITHUB_WEBHOOK_SECRET`. Diffs are fetched and review comments posted with the repository owner's token.

**Why:** One OAuth flow covers both sign-in and repository access. There's no app installation step and no app private key or installation-token exchange to manage.

**Tradeoffs:**
- The `repo` scope gives read and write access to all of the user's repositories, not only the ones DevMind reviews.
- Webhooks go onto every synced repository, not just ones the user picked. Creating a webhook needs admin rights on the repository; GitHub's 422 response is raised as `WebhookInstallError`.
- Review comments appear as the repository owner, not as a bot account.
- Every repository shares one webhook secret. `push` events are delivered but ignored.
- Removing webhooks is only possible from the Django admin.

**What would change at larger scale:** A GitHub App would allow per-repository installation, fine-grained permissions, short-lived installation tokens, one app-level webhook and a bot identity for comments. Adopting one would mean replacing the token storage, sync and webhook-install code.

### Polling instead of WebSockets for review status

**What:** The dashboard and review pages fetch `GET /reviews/` or `GET /reviews/<id>/` when they load. For each review shown as `pending` or `processing`, `ReviewStatus.tsx` then polls `GET /reviews/<id>/` every 3 seconds until the status is `completed` or `failed` or the component unmounts.

**Why:** Django Channels consumers and an optional Supabase status push used to exist but were never served: there was no ASGI server, the production image runs gunicorn on WSGI and Nginx had no upgrade block. They were removed rather than finished. Polling reuses the existing authenticated REST endpoint and its ownership checks, so there's no second auth path (such as a JWT in a WebSocket query string) to secure.

**Tradeoffs:** Status shows up to 3 seconds late, and every open page with an unfinished review sends a request every 3 seconds. In exchange, the server only handles short HTTP requests under WSGI, with no long-lived connections and no channel layer.

**What would change at larger scale:** Many open dashboards would make polling the main read load. At that point, server-sent events or WebSockets behind an ASGI server, with a per-review ownership check, would push changes instead.

### One Redis instance in several roles

**What:** A single `redis:7-alpine` service is the Celery broker (db 1) and result backend (db 2), the Django cache for OAuth state and DRF throttle counters, and the FastAPI rate-limit store (all db 0). See [Redis usage by database](#redis-usage-by-database).

**Why:** It's one service to run, and every role needs short-lived keys or queues, which Redis handles well. Separate database numbers keep broker and result keys apart from cache keys.

**Tradeoffs:** Redis is a single point of failure, and the failure behavior varies:
- The webhook view doesn't catch errors from `.delay()`, so webhook deliveries fail with a server error and reviews aren't queued.
- GitHub sign-in fails, because the OAuth state can't be stored or checked.
- The FastAPI rate limiter fails open and lets requests through.
- `/health/` reports `redis: error` but still answers 200.

`docker-compose.yml` gives Redis no named volume, persistence options or password, and database numbers aren't access control: any client that can reach the port can select any database.

**What would change at larger scale:** Splitting the broker from the cache, adding persistence or a managed Redis with failover, and alerting on the `/health/` Redis field are the obvious first steps.

### Shared-secret service-to-service authentication

**What:** Celery to FastAPI (`/review`, `/embeddings`) and FastAPI to Django (`/api/v1/auth/internal/llm-configs/`) both authenticate with one value, `FASTAPI_INTERNAL_SECRET`, sent as `X-Internal-Secret` and compared with `hmac.compare_digest`. An empty secret on either side fails closed with 403.

**Why:** Both services run on one compose network and are deployed together, so one environment variable is enough. There are no certificates to issue and no token service to run.

**Tradeoffs:**
- The secret is static and identical in both directions, so a leak lets the holder call FastAPI and read every user's decrypted BYOK keys from Django.
- Requests aren't signed and have no expiry, so a captured request can be replayed.
- The calls are plain HTTP, so anything that can observe compose-network traffic can read the secret.
- Rotation means updating both services at the same time.

**What would change at larger scale:** Separate secrets per direction, short-lived signed tokens (for example JWTs with an audience and expiry), or mTLS between services would limit what one leaked credential exposes. Network isolation that keeps port 8001 unpublished would also help.
