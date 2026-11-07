# 0001: Remove the findings-count retry

Status: accepted. Implemented in #82 (A2).

## Context

The review graph had a `format_output` node that computed a "confidence" from the number of findings relative to the diff size. A non-trivial diff with no findings counted as suspicious, and `should_retry` re-ran the graph up to `MAX_ITERATIONS = 3` times. Two other nodes did no work: `fetch_conventions` always returned `{}`, and `generate_fixes` only copied `suggested_fix` values the comments already carried. So a clean pull request, the case where the right answer is no findings, made the most LLM calls and pushed the model toward inventing findings.

## Decision

Remove `format_output`, the confidence score, the iteration loop, `fetch_conventions` and `generate_fixes`. The graph is three parallel analyzers (security, quality, tests) feeding `synthesize`. An analyzer repeats its call once only when its reply can't be parsed (`MAX_PARSE_RETRIES = 1` in `backend/fastapi/agents/review_agent.py`); an empty list of findings is a valid result and isn't retried. Each analyzer records its model, latency, tokens, attempts and whether its reply parsed in `analyzer_runs`.

## Consequences

- A batch makes exactly 3 LLM calls when every reply parses, whatever the findings count, so cost and latency no longer grow on clean diffs.
- "Found nothing" and "failed to answer" are now distinguishable: `analyzer_runs[...].parsed` is false only when every attempt was unparseable.
- Nothing pushes the model to find more. Whether that misses real issues is measured by the evals rather than guessed: after the A-series fixes, exact-line recall on the 27 eval cases was 18 of 18 ([Review quality](../../README.md#review-quality)).
