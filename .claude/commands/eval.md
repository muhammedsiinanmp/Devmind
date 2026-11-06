---
description: Run the review-quality evals and compare with the committed baseline
argument-hint: [--live]
---

Run the DevMind eval harness (issue E1) in `backend/fastapi/evals`.

- Default: `make eval` (replay mode, no API cost).
- With `--live` in "$ARGUMENTS": `make eval ARGS=--live`. This calls real providers, so say how many cases will run before starting.

If `backend/fastapi/evals` doesn't exist yet, say that E1 hasn't been merged and stop.

Report precision, recall, false-positive rate on clean cases, valid-line rate, latency and cost next to the baseline values, and list the cases whose result changed. Quote only numbers from the run output.
