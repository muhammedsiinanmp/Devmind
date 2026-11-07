# 0006: Eval methodology

Status: accepted. Implemented in #85 (E1), #103 (E2) and #110 (E3).

## Context

The A-series changes (line anchoring, the honest graph, retrieval, batching) needed evidence that they improved reviews, and later changes needed a check that they didn't make reviews worse. Three things make that easy to get wrong: a finding can name the right problem a line or two off, a run that errors can quietly drop out of the average, and the model's output differs between runs of the same code.

## Decision

- **Fixed, labeled cases.** 27 hand-written synthetic diffs in `backend/fastapi/evals/cases/` (9 clean, 18 with a labeled file, line range, category and minimum severity). The agent's comments go through the same post-processing the router applies before posting.
- **Exact and tolerant metrics, both reported.** Exact-line recall needs the finding inside the labeled range. Location-tolerant recall also accepts a finding in the same file with the right category and severity within 3 lines or in the same hunk. Precision is reported exact, with duplicates collapsed, and tolerant. Neither number replaces the other, so a gain from tolerance can't pass as a gain in accuracy.
- **Errors count against the code.** A case that errors (missing cassette, provider failure, unparseable reply) is never dropped: its labeled findings count as missed and an errored clean case counts as a false positive. Every report states how many cases were scored, and results with errored cases aren't written without `--allow-partial`.
- **Record once, replay in CI.** Live runs record cassettes keyed by prompt hash (no prompts, headers or keys stored). CI replays them on PRs that touch the agent or eval code and posts the comparison with the reference run. Replay can't measure a prompt change; that needs a live run.
- **Report variance.** `--repeat N` records several runs per case and reports each metric's mean and min–max; `scripts/eval_compare.py` marks a change *within noise* when either side's mean falls inside the other's min–max. `scripts/eval_noise.py` compares two single runs of the same code.

## Consequences

- The README's numbers are generated, and tests (`tests/test_eval_compare.py`, `tests/test_eval_noise.py`) fail if the README stops matching the committed results files.
- Two live runs of unchanged code changed the scores of 11 of 23 commonly scored cases while totals moved by at most one, so a difference of a few findings between two single runs isn't evidence of a change.
- The committed before/after comparison is one run per side; the case set is small and synthetic, so the numbers describe these cases, not real pull requests.
- Live runs cost quota: 3 calls per case, about 243 Groq calls for `--repeat 3`.

Details: [evals.md](../evals.md).
