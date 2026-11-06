# Review eval results (replay)

**Scored 27 of 27 cases.**

- Commit: `bccc370eec4edb600731670a43f89c20bf20111d` (uncommitted or untracked files present)
- Date (UTC): n/a (not stored in cassettes)
- Models used: groq/openai/gpt-oss-120b
- Run flags: {"allow_partial": false, "only": null, "pause": 0.0, "provider": null, "record": false}
- Post-processing: anchor_comments, drop_empty_body, review_comment_validation
- Harness sha256: `eaac3e46dc90dc92`, case set sha256: `00dad82dc88b8d2f`
- Cases: 27 (9 clean)

| Metric | Value |
| --- | --- |
| Precision (exact location) | 0.281 (18/64 findings) |
| Precision, duplicates collapsed | 0.300 (18/60 unique findings) |
| Precision (location-tolerant) | 0.281 (18/64 findings) |
| Recall (exact line) | 1.000 (18/18 expected) |
| Recall (location-tolerant) | 1.000 (18/18 expected) |
| False-positive rate on clean diffs | 1.000 (9/9 cases) |
| Valid-line rate (agent output, before anchoring) | 1.000 (64/64 findings) |
| Near / partial matches | 0 / 0 |
| Analyzer parse failures | 0 |
| Anchoring (anchored / snapped / file-level) | 64 / 0 / 0 |
| Latency per case, ms (recorded; providers: groq) | mean 2307, p50 2202, max 3920 |
| Model calls / prompt tokens / completion tokens | 81 / 56463 / 27612 |
| Cost (USD) | not priced |

Latency depends on the provider chain, quotas and network; compare it only between runs that used the same providers. Precision is measured against the labels: a real issue nobody labeled, or a duplicate, counts as an extra. Exact recall needs the exact labeled line range; location-tolerant recall also accepts the same file within 3 lines or in the same hunk.

| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bare-except-swallows | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| clean-config-timeout | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-docstring | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-function-with-tests | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-js-const | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-log-message | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-parameterized-query | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-rename-variable | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-test-only | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-type-hints | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| command-injection | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| go-ignored-error | 1 | 5 | 1 | 0 | 0 | 0 | 4 |  |
| hardcoded-secret | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| insecure-deserialization | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| jwt-signature-disabled | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| missing-auth-check | 1 | 6 | 1 | 0 | 0 | 0 | 5 |  |
| missing-await | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| missing-test-for-new-branch | 1 | 5 | 1 | 0 | 0 | 0 | 4 |  |
| mutable-default-argument | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| n-plus-one-query | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| off-by-one-range | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| path-traversal | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| sql-injection-fstring | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| ssrf-user-url | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| unhandled-none | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| weak-password-hash | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| xss-innerhtml | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
