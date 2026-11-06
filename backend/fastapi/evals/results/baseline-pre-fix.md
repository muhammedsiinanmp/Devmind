# Review eval results (replay)

**Scored 27 of 27 cases.**

- Commit: `6e5638a1561d5936e9445d996f725ae981922669` (uncommitted or untracked files present)
- Date (UTC): n/a (not stored in cassettes)
- Models used: groq/openai/gpt-oss-120b
- Run flags: {"allow_partial": false, "only": null, "pause": 0.0, "provider": null, "record": false}
- Post-processing: drop_empty_body, review_comment_validation
- Harness sha256: `eaac3e46dc90dc92`, case set sha256: `00dad82dc88b8d2f`
- Cases: 27 (9 clean)

| Metric | Value |
| --- | --- |
| Precision (exact location) | 0.066 (10/152 findings) |
| Precision, duplicates collapsed | 0.081 (10/123 unique findings) |
| Precision (location-tolerant) | 0.112 (17/152 findings) |
| Recall (exact line) | 0.556 (10/18 expected) |
| Recall (location-tolerant) | 0.944 (17/18 expected) |
| False-positive rate on clean diffs | 1.000 (9/9 cases) |
| Valid-line rate (agent output, before anchoring) | 0.914 (139/152 findings) |
| Near / partial matches | 7 / 1 |
| Analyzer parse failures | unknown (this code doesn't report analyzer_runs[...].parsed, so parse failures can't be counted) |
| Anchoring (anchored / snapped / file-level) | not applied |
| Latency per case, ms (recorded; providers: groq) | mean 3545, p50 3319, max 5566 |
| Model calls / prompt tokens / completion tokens | 81 / 31353 / 52786 |
| Cost (USD) | not priced |

Latency depends on the provider chain, quotas and network; compare it only between runs that used the same providers. Precision is measured against the labels: a real issue nobody labeled, or a duplicate, counts as an extra. Exact recall needs the exact labeled line range; location-tolerant recall also accepts the same file within 3 lines or in the same hunk.

| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bare-except-swallows | 1 | 8 | 1 | 0 | 0 | 0 | 7 |  |
| clean-config-timeout | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-docstring | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-function-with-tests | 0 | 9 | 0 | 0 | 0 | 0 | 9 |  |
| clean-js-const | 0 | 4 | 0 | 0 | 0 | 0 | 4 |  |
| clean-log-message | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-parameterized-query | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-rename-variable | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-test-only | 0 | 9 | 0 | 0 | 0 | 0 | 9 |  |
| clean-type-hints | 0 | 6 | 0 | 0 | 0 | 0 | 6 |  |
| command-injection | 1 | 2 | 0 | 0 | 1 | 0 | 1 |  |
| go-ignored-error | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| hardcoded-secret | 1 | 6 | 0 | 1 | 0 | 0 | 5 |  |
| insecure-deserialization | 1 | 3 | 0 | 1 | 0 | 0 | 2 |  |
| jwt-signature-disabled | 1 | 3 | 0 | 1 | 0 | 0 | 2 |  |
| missing-auth-check | 1 | 15 | 0 | 1 | 0 | 0 | 14 |  |
| missing-await | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| missing-test-for-new-branch | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| mutable-default-argument | 1 | 5 | 1 | 0 | 0 | 0 | 4 |  |
| n-plus-one-query | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| off-by-one-range | 1 | 6 | 0 | 1 | 0 | 0 | 5 |  |
| path-traversal | 1 | 14 | 1 | 0 | 0 | 0 | 13 |  |
| sql-injection-fstring | 1 | 6 | 1 | 0 | 0 | 0 | 5 |  |
| ssrf-user-url | 1 | 5 | 0 | 1 | 0 | 0 | 4 |  |
| unhandled-none | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| weak-password-hash | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| xss-innerhtml | 1 | 3 | 0 | 1 | 0 | 0 | 2 |  |
