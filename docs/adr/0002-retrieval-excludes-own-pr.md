# 0002: Retrieval excludes the pull request's own chunks

Status: accepted. Implemented in #81 and follow-up fixes in #90 (A4).

## Context

`POST /review/analyze` retrieves similar code from the same repository to give the agent context. Before this change, the review stored the first 1000 characters of its own diff before searching, so the closest "similar code" was often the diff itself. On a re-review after a new push, the PR's earlier hunks were retrieved as well. Either way the context repeated the code under review and spent prompt tokens on it.

## Decision

- Search before storing anything. Each changed hunk (up to 20) is embedded and searched once.
- Store hunks only after the review, tagged `source_ref = "PR#<n>"`, and exclude that tag in SQL (`source_ref IS DISTINCT FROM 'PR#<n>'`, so untagged rows are kept).
- Also drop untagged legacy rows whose `file_path` is `PR#<n>`, and any result whose whitespace-normalized text equals a hunk of the current diff.
- Merge the per-hunk results, deduplicate by text, keep the top 5, and log only file path and similarity.

Code: `backend/fastapi/routers/review.py` and `backend/fastapi/services/vector_store.py`.

## Consequences

- A review, including a re-review after a push, doesn't retrieve its own diff.
- When `pr_number` is 0, nothing is tagged or excluded.
- Rows written before `source_ref` existed carry no tag, so a PR reviewed before the change can still retrieve its own old hunks unless their text matches the new diff. The cleanup is in [ENGINEERING_GUIDE.md, Known Gaps](../ENGINEERING_GUIDE.md#10-known-gaps).
- The same exclusion was reused for feedback examples (#109): a PR's own feedback never steers its later reviews.
