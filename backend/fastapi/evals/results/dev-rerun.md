# Review eval results (live)

**Scored 23 of 27 cases.** Errored cases count as missed (defects) or as false positives (clean diffs); see the Error column.

- Commit: `9dd6824c7a893bd7615594d52b456b6e58841bbd` (uncommitted or untracked files present)
- Date (UTC): 2026-11-06T19:16:23Z (run)
- Models used: groq/openai/gpt-oss-120b
- Run flags: {"allow_partial": true, "only": null, "pause": 75.0, "provider": "groq", "record": true}
- Post-processing: anchor_comments, drop_empty_body, review_comment_validation
- Harness sha256: `eaac3e46dc90dc92`, case set sha256: `00dad82dc88b8d2f`
- Cases: 27 (9 clean)

| Metric | Value |
| --- | --- |
| Precision (exact location) | 0.241 (14/58 findings) |
| Precision, duplicates collapsed | 0.255 (14/55 unique findings) |
| Precision (location-tolerant) | 0.241 (14/58 findings) |
| Recall (exact line) | 0.778 (14/18 expected) |
| Recall (location-tolerant) | 0.778 (14/18 expected) |
| False-positive rate on clean diffs | 0.889 (8/9 cases) |
| Valid-line rate (agent output, before anchoring) | 1.000 (58/58 findings) |
| Near / partial matches | 0 / 0 |
| Analyzer parse failures | 0 |
| Anchoring (anchored / snapped / file-level) | 58 / 0 / 0 |
| Latency per case, ms (measured; providers: groq) | mean 2358, p50 2263, max 4740 |
| Model calls / prompt tokens / completion tokens | 69 / 48328 / 24687 |
| Cost (USD) | not priced |

Latency depends on the provider chain, quotas and network; compare it only between runs that used the same providers. Precision is measured against the labels: a real issue nobody labeled, or a duplicate, counts as an extra. Exact recall needs the exact labeled line range; location-tolerant recall also accepts the same file within 3 lines or in the same hunk.

| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bare-except-swallows | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| clean-config-timeout | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-docstring | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-function-with-tests | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-js-const | 0 | 2 | 0 | 0 | 0 | 0 | 2 |  |
| clean-log-message | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-parameterized-query | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
| clean-rename-variable | 0 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| clean-test-only | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| clean-type-hints | 0 | 3 | 0 | 0 | 0 | 0 | 3 |  |
| command-injection | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| go-ignored-error | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| hardcoded-secret | 1 | 3 | 1 | 0 | 0 | 0 | 2 |  |
| insecure-deserialization | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| jwt-signature-disabled | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| missing-auth-check | 1 | 7 | 1 | 0 | 0 | 0 | 6 |  |
| missing-await | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| missing-test-for-new-branch | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| mutable-default-argument | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| n-plus-one-query | 1 | 4 | 1 | 0 | 0 | 0 | 3 |  |
| off-by-one-range | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| path-traversal | 1 | 5 | 1 | 0 | 0 | 0 | 4 |  |
| sql-injection-fstring | 1 | 2 | 1 | 0 | 0 | 0 | 1 |  |
| ssrf-user-url | 1 | 0 | 0 | 0 | 0 | 1 | 0 | AllProvidersDownError: All LLM providers unavailable |
| unhandled-none | 1 | 0 | 0 | 0 | 0 | 1 | 0 | AllProvidersDownError: All LLM providers unavailable |
| weak-password-hash | 1 | 0 | 0 | 0 | 0 | 1 | 0 | AllProvidersDownError: All LLM providers unavailable |
| xss-innerhtml | 1 | 0 | 0 | 0 | 0 | 1 | 0 | AllProvidersDownError: All LLM providers unavailable |
