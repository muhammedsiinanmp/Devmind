# 0004: Review deadline with partial results

Status: accepted. Implemented in #105 (A5).

## Context

Large diffs are split into batches of whole files (`backend/fastapi/services/diff_batching.py`), and each batch makes 3 LLM calls. With the defaults (`REVIEW_MAX_BATCHES` 6, `REVIEW_MAX_CONCURRENT_BATCHES` 2) a review can make 18 calls, and the rate limiter can make a call wait up to a minute for the next window. The Celery worker calls FastAPI with a 120 s timeout (`FASTAPI_TIMEOUT_SECONDS`). Without a limit inside FastAPI, a slow review would hit that timeout and lose every finished batch, or keep running after Django had given up.

## Decision

- Batches must finish within `REVIEW_DEADLINE_SECONDS` (default 100), counted from the start of `POST /review/analyze`, retrieval included.
- At the deadline, unfinished batches are cancelled and the finished batches' findings are returned. The unreviewed files are listed in `files_skipped` with reason `deadline`, and Django appends "Reviewed X of Y files" and the skipped files to the review summary.
- If no batch finished, the router returns 504 `{"error": "review_deadline"}` instead of an empty review. Django marks the review failed and the Celery task retries it.
- If one batch fails (for example every provider is rate limited), the others are cancelled and the error is raised; no partial result is returned for failures, only for the deadline.
- Django warns at startup (`reviews.W001`) if `FASTAPI_TIMEOUT_SECONDS` isn't at least 10 s above the deadline.

## Consequences

- A slow review returns what it finished, with the gaps stated in the review itself, and never looks clean when nothing was reviewed.
- No batch task outlives the request.
- The 100 s and 120 s defaults are reasoned from the providers' rate limits (`rpm_limit` in `services/llm_client.py`), not measured on real large pull requests.
