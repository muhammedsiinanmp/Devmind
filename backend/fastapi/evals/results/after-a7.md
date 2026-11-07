# Review eval results (replay)

**Scored 27 of 27 cases.**

- Commit: `ce719609c24b7afd35a215a8079f64d840da6ade` (uncommitted or untracked files present)
- Date (UTC): 2026-11-06T19:15:26Z (cassettes)
- Models used: groq/openai/gpt-oss-120b
- Run flags: {"allow_partial": false, "only": null, "pause": 0.0, "provider": null, "record": false}
- Post-processing: anchor_comments, drop_empty_body, review_comment_validation
- Harness sha256: `2e4482ab5443fae5`, case set sha256: `00dad82dc88b8d2f`
- Cases: 27 (9 clean)

| Metric | Value |
| --- | --- |
| Precision (exact location) | 0.235 (16/68 findings) |
| Precision, duplicates collapsed | 0.258 (16/62 unique findings) |
| Precision (location-tolerant) | 0.265 (18/68 findings) |
| Recall (exact line) | 0.889 (16/18 expected) |
| Recall (location-tolerant) | 1.000 (18/18 expected) |
| False-positive rate on clean diffs | 1.000 (9/9 cases) |
| Valid-line rate (agent output, before anchoring) | 1.000 (68/68 findings) |
| Near / partial matches | 2 / 0 |
| Analyzer parse failures | 0 |
| Anchoring (anchored / snapped / file-level) | 68 / 0 / 0 |
| Latency per case, ms (recorded; providers: groq) | mean 2032, p50 1990, max 3915 |
| Model calls / prompt tokens / completion tokens | 81 / 59541 / 28997 |
| Cost (USD) | not priced |

Latency depends on the provider chain, quotas and network; compare it only between runs that used the same providers. Precision is measured against the labels: a real issue nobody labeled, or a duplicate, counts as an extra. Exact recall needs the exact labeled line range; location-tolerant recall also accepts the same file within 3 lines or in the same hunk.

| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bare-except-swallows | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| clean-config-timeout | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-docstring | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-function-with-tests | 0 | 5 | 0 | 0 | 0 | 0 | 5 |  |
| clean-js-const | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-log-message | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-parameterized-query | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-rename-variable | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-test-only | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-type-hints | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| command-injection | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| go-ignored-error | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| hardcoded-secret | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| insecure-deserialization | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| jwt-signature-disabled | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| missing-auth-check | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| missing-await | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| missing-test-for-new-branch | 1 | 3 | 0 | 1 | 0 | 0 | 2 |  |
| mutable-default-argument | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| n-plus-one-query | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| off-by-one-range | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| path-traversal | 1 | 6 | 0 | 1 | 0 | 0 | 5 |  |
| sql-injection-fstring | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| ssrf-user-url | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| unhandled-none | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| weak-password-hash | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| xss-innerhtml | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
