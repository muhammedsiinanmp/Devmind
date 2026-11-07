# Review-quality evals

How `backend/fastapi/evals/` measures the review agent, how CI uses it, and where every committed result came from. The headline results are in the README's [Review quality](../README.md#review-quality) section. The reasons behind the method are in [ADR 0006](adr/0006-eval-methodology.md).

## What the harness runs

`backend/fastapi/evals/` measures review quality. It runs `run_review_agent` on 27 hand-written synthetic diffs in `evals/cases/` (9 of them clean, with `expected: []`), skipping the database/RAG step, so no Postgres is needed. The agent's comments then go through the same steps the router applies before posting: comments without a body are dropped, each is validated as a `ReviewComment`, and they're anchored to diff lines with `anchor_comments()` when the code has it. The results record which of these steps ran.

Three more cases in `evals/cases/feedback/` (not in the default set) carry rejected feedback examples, which the harness gives straight to the agent; `--no-feedback` runs them without. Recorded twice each way with `groq/openai/gpt-oss-120b` (`evals/results/feedback-runs/`): the control case's real MD5 password bug was found as critical in all 4 runs, so a rejected "MD5 is weak" example didn't hide it. Suppression of false positives was **not** demonstrated: the model didn't make the targeted mistakes without feedback either, so these cases can't measure it. Details in [docs/feedback-learning.md](feedback-learning.md#evals).

## Metrics

Each posted finding is matched to the labeled ones. A label gives a file and line range (or several acceptable locations), a category and a minimum severity. Model category labels such as "SQL Injection" or "test-coverage" are folded into security, quality or tests.

What it reports:
- **Precision**, measured against the labels: a real issue nobody labeled counts as an extra, and so does a duplicate. It's reported three ways: exact location, with duplicates collapsed (same file, line and folded category), and location-tolerant.
- **Recall, exact line:** the finding's line must fall inside the labeled range.
- **Recall, location-tolerant:** also accepts a finding in the same file with the right category and severity that is within 3 lines of the range or in the same hunk.
- **False-positive rate on clean diffs:** the share of clean cases with at least one posted finding.
- **Valid-line rate:** the share of the agent's findings, before anchoring, that point at a line shown in the diff.
- **Analyzer parse failures:** the number of analyzer runs whose reply couldn't be parsed, or "unknown" for code that doesn't report it.
- **Latency, token counts and cost.** Latency depends on the providers and quotas, so compare it only between runs that used the same providers. Cost is reported only when a price is set in `PRICES_PER_MTOK` in `evals/run.py`. None are set, so it shows "not priced".

A case that errors (missing or stale cassette, a provider failure, an analyzer reply that can't be parsed) is never dropped. Its labeled findings count as missed, and an errored clean case counts as a false positive. Every report states how many cases were scored, and `--results-dir` refuses to write results that include errored cases unless you pass `--allow-partial`.

## Running it

```bash
make eval         # replay: offline and deterministic, uses evals/cassettes/, no keys needed
make eval-record  # live: calls the providers configured in .env, re-records the
                  # cassettes, writes evals/results/<sha>.json and <sha>.md
# Free-tier quotas: pin one server provider and wait between cases
make eval-record EVAL_ARGS="--provider groq --pause 75"
```

`--provider NAME` (live only) limits the server chain to one provider for the run, so a quota running out partway through can't silently switch models. `--pause SECONDS` waits that long between cases. `--only id1,id2` runs a subset, `--results-name` sets the results file name, and `--allow-partial` writes results even when some cases errored. `--repeat N` (live only) runs every case N times, one full pass per run, and records `<case>.<i>.json` cassettes; replay finds and replays every numbered run. A multi-run report shows each metric's mean, min–max and per-run values, and per case how many runs agree on its scores and on its posted findings (file, line, category and severity). Results record these flags, the recording date, the providers, the commit (and whether there were uncommitted or untracked files), a hash of the harness code and a hash of the case set.

**Quota.** Each case makes 3 model calls (81 calls for 27 cases in the committed results), so `--repeat 3` over 27 cases is about 243 Groq calls. That can exhaust Groq's free daily quota partway through: the second dev run (`dev-rerun.json`, see the README's run-to-run variance paragraph) lost its last 4 cases to `AllProvidersDownError` when the quota ran out. Use `--pause` to stay under the per-minute limits (the second dev run used `--pause 75`; a pause doesn't raise the daily quota), and if a run can't finish in a day, record the remaining cases on another day with `--only` and `--allow-partial`.

Cassettes store only the SHA-256 of each prompt, the response text, the model name and provider, token counts and the recording time. They don't store prompts, headers or keys, and recording stops if a configured key appears in a response.

**Replay can't measure a prompt change.** Cassettes are keyed by prompt hash, so replay only re-scores responses that were already recorded. After the agent's prompts or a case's diff change, replay reports those cases as stale. Measuring the effect of a prompt or model change needs a live run (`make eval-record`). Replay is for re-scoring a recorded run, for example after a change to the scorer or the labels. `evals/cassettes/` holds the recordings of the current reference run (A7, see [Review quality](../README.md#review-quality)), so `make eval` replays them by default. The recordings of the "after" run (provenance below) predate the per-review delimiter tag (#99), no longer match the prompts and were replaced; they remain in commit `01095e3`. The eval harness uses a fixed delimiter nonce (`EVAL_DELIMITER_NONCE` in `evals/run.py`), so cassettes recorded from now on replay. Live results also record the temperature settings in `run_flags.temperatures`, since cassettes don't store them.

## Eval report on a pull request

**CI.** On a pull request that changes `backend/fastapi/{agents,services,models,routers,core,evals}/**` (or `scripts/eval_compare.py`), the `Evals (replay)` job runs `make eval` against the committed cassettes and compares the result with the reference run `evals/results/after-a7.json` using `scripts/eval_compare.py`. It posts one PR comment with the marker `<!-- devmind-eval-report -->` and updates that comment on later pushes. The comment says one of three things:
- **No metric changed.**
- **Metrics changed**, with a before/after table of the changes. This happens when the change touches scoring, labels or post-processing but not prompts.
- **Prompt changed: replay can't measure this PR.** Some prompts have no recording, so nothing is scored. Re-record with `make eval-record EVAL_ARGS="--provider groq --pause 75"`, which needs provider keys in `.env`. Commit the new cassettes and the results file. If the new run becomes the reference, point the CI job at its results file.

Both committed runs have one run each, so a "metrics changed" comment adds a note that differences of a few findings may be noise. When both results files hold 2 or more runs, the table shows each metric's mean and min–max, and a changed metric is marked *within noise* if either side's mean falls inside the other side's min–max. That rule is deliberately simple; with 3 runs per side there is too little data for a significance test.

The job needs no secrets and doesn't fail because of eval results. It fails only if the harness or the comparison can't run. On pull requests from forks it writes the report to the job summary and doesn't comment. To compare two results files locally, run `cd backend/fastapi && uv run python -m scripts.eval_compare BASE.json CURRENT.json`.

After re-recording, commit the new `evals/cassettes/*.json` and results file. If the new run becomes the reference, point the `Evals (replay)` job in `.github/workflows/ci.yml` at its results file and update the README's "Current reference run" paragraph. Keep earlier results files as history: `tests/test_eval_compare.py` checks the README table against `baseline-pre-fix.json` and `after-fixes.json`, and `tests/test_eval_noise.py` checks the variance block against `after-fixes.json` and `dev-rerun.json`.

The test suite checks the scoring against hand-written fixture responses in `backend/fastapi/tests/fixtures/evals/`. Those are test data, not model output.

## Reading the before/after table

How to read it:
- **Recall and precision.** After the fixes, all 18 labeled defects get a finding on the labeled line, compared with 10 before. Precision is still low: 46 of the 64 posted findings match no label. Precision counts a real issue nobody labeled as an extra, so it is a lower bound.
- **Clean diffs.** The false-positive rate on clean diffs didn't change: each of the 9 clean diffs still gets at least one comment. There are fewer of them (16, down from 42), and none is critical or error. Before, there were 41 warnings and 1 critical. After, there are 13 warnings and 3 info. By folded category, 9 of the 16 are tests (mostly "no test covers this") and 7 are quality (input validation, indentation, a hard-coded timeout, an extra variable).
- **Analyzer parse failures.** The pre-fix agent doesn't report whether a reply parsed, so the before count can't be observed. After, 0 analyzer runs failed to parse.
- **Latency: not compared.** Both results record per-case latency (before: mean 3545 ms, after: mean 2307 ms), but they aren't comparable. The before run went through the server chain with Google first and Google's daily quota exhausted, so its times may include failed Google calls before the failover to Groq. The cassettes don't record this. The after run used only Groq.
- **Tokens.** Model calls: 81 in both runs. Prompt tokens went from 31353 to 56463 and completion tokens from 52786 to 27612.
- **Small, synthetic set.** 27 hand-written diffs, and each run was recorded once. The numbers show what this agent and model did on these cases. They are not an estimate of performance on real pull requests.

## Provenance of the committed runs

A7 reference provenance:
- **Code:** recorded on commit `4df00bd` and scored by replay on `ce71960` (the `commit` in the results file). `backend/fastapi/` is identical in `ce71960` and in `dev` after #107 (`git diff --stat ce71960 d5f039b -- backend/fastapi` is empty). Replaying the cassettes on `dev` finds a recording for every prompt and reproduces the results file's metrics and per-case findings exactly, so the prompts `dev` sends are the recorded ones.
- **Model:** `groq/openai/gpt-oss-120b` for all 81 calls (`models_used`).
- **Recording:** the cassettes' `recorded_utc` times show two passes on 2026-11-06: 13 cases from 17:50 to 18:05 UTC and the other 14 from 18:58 to 19:15 UTC, about 77 s apart within each pass. The recording session reports the gap as a network (DNS) outage; no committed artifact records the cause. No case was dropped: all 27 are scored.
- **Scoring:** `harness_sha256` `2e4482ab…` (the harness after #99, which pins the delimiter nonce) and `case_set_sha256` `00dad82d…`, the same case set as the baseline and the after run.

After-run provenance:
- **Code:** recorded with the E1 harness at commit `40b8853` (an ancestor of `dev`). Its `agents/`, `services/`, `models/`, `core/` and `routers/` code is identical to `dev` at `bccc370`: `git diff --stat 40b8853 bccc370` on those directories is empty.
- **Model:** `groq/openai/gpt-oss-120b` for all 81 calls (`models_used` in the results file).
- **Recording:** all 27 cases recorded live on 2026-11-06. The cassettes are in `backend/fastapi/evals/cassettes/` (commit `01095e3`). The `40b8853` harness didn't store the provider or recording time in cassettes, so the results file has no date (`date_source: not stored in cassettes`). The 2026-11-06 date is the commit date. The first live pass was interrupted by a network (DNS) outage after 14 cases; the remaining 13 were recorded in a second pass with the same harness, model and flags. The 40b8853 cassettes store no timestamps, so this comes from the recording session's logs, not from a committed artifact. No case was dropped: all 27 are scored.
- **Scoring:** [`after-fixes.md`](../backend/fastapi/evals/results/after-fixes.md) and `.json`, from replaying those cassettes on a clean checkout of `01095e3` (`dirty_worktree: false`). The results file has `harness_sha256` `eaac3e46…` and `case_set_sha256` `00dad82d…`, the same as the baseline, so both runs were scored by the same code on the same cases and labels. A replay on the E1 branch gave the same metrics.

Baseline provenance:
- **Code:** commit `8e606d6` on branch `eval/baseline-prefix` is the first version of this harness on top of `dev` at `ebb335a` (the pre-fix agent). It changes only the model IDs in `services/llm_client.py`, because the original models could no longer be called. `gemini-2.0-flash` became `gemini-3.5-flash`, `llama-3.3-70b-versatile` became `openai/gpt-oss-120b`, and GitHub Models was disabled (retired 2026-07-30). These are the same model IDs #96 adopted.
- **Model:** `groq/openai/gpt-oss-120b` only. Google's free daily quota had run out, so every call went to Groq.
- **Recording:** all 27 cases (9 clean), recorded on 2026-11-06 (the commit date of `6e5638a`; the cassettes from that run don't store a timestamp). Cases were run one at a time from a shell loop with a pause between them, because `--pause` didn't exist yet; the pause length isn't recorded in any artifact. The cassettes are in commit `6e5638a` on the same branch. They're keyed to the pre-fix prompts, so they replay only against that code.
- **Scoring:** [`backend/fastapi/evals/results/baseline-pre-fix.md`](../backend/fastapi/evals/results/baseline-pre-fix.md) and `.json`. These come from replaying those cassettes on a checkout of `6e5638a` whose `evals/` directory (harness code and case labels only, no agent code) was replaced with the E1 branch's. That's why the results file shows commit `6e5638a` with uncommitted files present. Its `harness_sha256` (`eaac3e46…`) and `case_set_sha256` (`00dad82d…`) matched the E1 branch's `evals/` code and cases. Replaying produced the same agent output, case for case, as the original run.
- **Why the numbers moved from the first report** (precision 0.059, recall 0.500, 9 matches): one more exact match comes from the alternative location added to `missing-test-for-new-branch` (`tests/test_pricing.py`), and the new location-tolerant bucket counts 7 near matches that were previously misses.
- **Caveat on that extra exact match:** the finding it credits (`tests/test_pricing.py:4`) is about a different untested case (a discount equal to the subtotal). The finding that names the labeled defect (the untested quantity `ValueError`) is at line 1, just outside the alternative range, and would have been a near match. Read by hand, the split is 9 exact and 8 near. Tolerant recall (17/18) is unaffected. The matcher matches on location, category and severity, not on the finding's text, so this can happen whenever several findings share a category in one hunk.
