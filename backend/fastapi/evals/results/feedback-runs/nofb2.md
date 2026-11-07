# Review eval results (live)

**Scored 3 of 3 cases.**

- Commit: `3d590c699527d5ad10145e0468750677a0784720`
- Date (UTC): 2026-11-07T09:17:44Z (run)
- Models used: groq/openai/gpt-oss-120b
- Run flags: {"allow_partial": true, "feedback": false, "only": ["feedback-control-md5-password", "feedback-md5-cache-key", "feedback-random-jitter"], "pause": 60.0, "provider": "groq", "record": true, "temperatures": {"google": "omit", "groq": null, "review": 0.1}}
- Post-processing: anchor_comments, drop_empty_body, review_comment_validation
- Harness sha256: `8d1f184b568fce2d`, case set sha256: `4697f58e92e5ab91`
- Cases: 3 (2 clean)

| Metric | Value |
| --- | --- |
| Precision (exact location) | 0.125 (1/8 findings) |
| Precision, duplicates collapsed | 0.143 (1/7 unique findings) |
| Precision (location-tolerant) | 0.125 (1/8 findings) |
| Recall (exact line) | 1.000 (1/1 expected) |
| Recall (location-tolerant) | 1.000 (1/1 expected) |
| False-positive rate on clean diffs | 1.000 (2/2 cases) |
| Valid-line rate (agent output, before anchoring) | 1.000 (8/8 findings) |
| Near / partial matches | 0 / 0 |
| Analyzer parse failures | 0 |
| Anchoring (anchored / snapped / file-level) | 8 / 0 / 0 |
| Latency per case, ms (measured; providers: groq) | mean 2294, p50 2033, max 3000 |
| Model calls / prompt tokens / completion tokens | 9 / 6474 / 3548 |
| Cost (USD) | not priced |

Latency depends on the provider chain, quotas and network; compare it only between runs that used the same providers. Precision is measured against the labels: a real issue nobody labeled, or a duplicate, counts as an extra. Exact recall needs the exact labeled line range; location-tolerant recall also accepts the same file within 3 lines or in the same hunk.

| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| feedback-control-md5-password | 1 | 1 | 1 | 0 | 0 | 0 | 0 |  |
| feedback-md5-cache-key | 0 | 6 | 0 | 0 | 0 | 0 | 6 |  |
| feedback-random-jitter | 0 | 1 | 0 | 0 | 0 | 0 | 1 |  |
