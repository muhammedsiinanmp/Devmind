# Learning from reviewer feedback

DevMind records what trusted developers think of its inline comments, and shows later reviews of the same repository the most similar accepted and rejected comments. This page defines what counts as accepted or rejected and whose signals count, where the data flows, what to set up, the threat model, and what the evals measured. Issue: #74.

## Whose signals count

Only signals from **trusted users** count (`TrustChecker` in `backend/django/apps/reviews/services/feedback.py`):

- the DevMind user who connected the repository, matched by GitHub numeric user id (`CustomUser.github_id`), never by login: a renamed owner's old login is free for anyone to take;
- the repository owner (`author_association` `OWNER` on a reply);
- anyone whose permission on the repository is `write` or `admin`, according to `GET /repos/{repo}/collaborators/{user}/permission`. GitHub reports `maintain` as `write` and `triage` as `read` in that field, and maps a custom role to its base role.

`author_association` is used only as a first filter on replies. Per GitHub's REST documentation, `MEMBER` means a member of the organization that owns the repository and `COLLABORATOR` means a user invited to the repository. Neither implies write access: an organization member can have read-only base permission, and a collaborator can be invited with the read role. So `MEMBER`, `COLLABORATOR` and resolved-thread senders (whose payload has no association) always get the permission check. Every other association (`CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, `FIRST_TIMER`, `MANNEQUIN`, `NONE`) is rejected without a GitHub call. Bot accounts never count.

**The pull request's own author never counts on that pull request**, even if trusted. The person being reviewed can't silence the findings about their own code. Permission lookups are cached for one task run, use the repository owner's token, and stay within the rate-limit floor described below. A user GitHub doesn't know (404), or an owner with no stored token, means not trusted.

## What counts as accepted or rejected

Only DevMind's inline comments get feedback. Comments folded into the review body (no valid line) have no GitHub comment of their own, so nothing can be attributed to them.

| Source | When it is read | Accepted | Rejected | No signal |
| --- | --- | --- | --- | --- |
| `reaction` | When the PR closes (merged or not), from trusted users' 👍 (`+1`) and 👎 (`-1`) on each comment | more trusted 👍 than 👎 | more trusted 👎 than 👍 | a tie, including no trusted reactions; any earlier reaction verdict is removed. Other reactions are ignored. |
| `reply` | `pull_request_review_comment` webhook, for a trusted user's reply to a DevMind comment | the reply starts with `fixed`, `done`, `good catch`, `nice catch`, `addressed` or `agreed` | the reply starts with `false positive`, `not an issue`, `not a bug`, `won't fix`, `wont fix`, `wontfix` or `disagree` | any other reply |
| `resolved` | `pull_request_review_thread` webhook | a trusted user resolves the comment's thread | (none) | a trusted user unresolves it: the verdict is removed |

Reply matching is case-insensitive, ignores quoted lines (`> ...`), and needs the phrase to end at a word boundary (`Fixed.` matches, `Doneness` doesn't). The phrase lists are `ACCEPTED_REPLY_PHRASES` and `REJECTED_REPLY_PHRASES` in `feedback.py`.

A reply verdict remembers which reply gave it (`CommentFeedback.source_github_id`):

- Deleting that reply removes the verdict.
- Editing it re-evaluates it: a new verdict replaces the old one, and no verdict removes it.

These removals don't need a trusted actor, since only the reply's author or a maintainer can delete or edit it. Deleting or editing a different reply leaves the verdict alone.

**Event order.** Celery retries and GitHub redeliveries can deliver an old event after a newer one, so each row stores `event_at`, the time of the event that set it, and an older event for the same comment and source is ignored.
- **Clearing keeps a marker:** a tie, an unresolve or a removed reply keeps the row with no signal, holding its time.
- **Where `event_at` comes from:**
  - created or edited replies: the reply's `updated_at`;
  - deleted replies and thread events: the time the webhook was received (GitHub sends no time for those);
  - reaction counts: the time the task runs.
- **Deleted replies:** the reply's id is also recorded (`DeletedFeedbackReply`), so a created or edited event for it that arrives later is always ignored.
- **Limit:** a manual redelivery of an old thread event gets a new receipt time, so it counts as new.

Each comment has at most one `CommentFeedback` row per source (unique on comment and source). A later event from the same source replaces the row: a second reaction count, a later reply with a verdict, or unresolving a thread. Reactions are counted again if the PR is reopened and closed again.

When sources disagree, the comment's verdict comes from the first source in this order: `reaction`, `reply`, `resolved`. A vote is the most explicit signal; people also resolve threads to dismiss comments they disagree with, so resolving counts least.

## Data flow

1. **Posting.** After creating a review on GitHub, `GitHubPoster` lists that review's comments (`GET /repos/{repo}/pulls/{n}/reviews/{id}/comments`) and stores each one's id in `ReviewComment.github_comment_id`, matched by file path and body. If the lookup fails, the comments are still posted but get no feedback. A body-only fallback review (after a 422) has no inline comments, so no ids.
2. **Webhooks.** `pull_request_review_thread` and `pull_request_review_comment` go through the same HMAC check as `pull_request`. The webhook reduces the payload to the fields needed (comment ids, actor, association, PR author) and queues `record_feedback_event_task`. The task finds the DevMind comment by GitHub id within the repository named in the payload (active repositories only), applies the trust rules and records the verdict. It is a task because the permission check calls GitHub. `pull_request` `closed` queues `fetch_comment_reactions_task` with the PR author's login.
3. **Reactions.** The task runs only for an active repository and uses the repository owner's token.
   - One paginated call per PR, `GET /repos/{repo}/pulls/{n}/comments`, gives each comment's reaction counts.
   - Only comments with a 👍 or 👎 then get their reactions listed with users (`GET /repos/{repo}/pulls/comments/{id}/reactions`).
   - Each reacting user gets one permission lookup, cached.
   - Comments whose counts are zero lose their reaction verdict without another call.
   - Comments deleted on GitHub keep their earlier verdict.
4. **GitHub limits and errors.** Every feedback read checks the quota left from the previous response, and stops before the next request when fewer than 100 requests are left in the token's hourly quota (`RATE_LIMIT_FLOOR`).
   - Pagination only follows `Link` URLs on `https://api.github.com`.
   - A 429, or a 403 with `X-RateLimit-Remaining: 0` or a `Retry-After` header, is a rate limit. The tasks retry after the reset, waiting between 1 minute and 1 hour, at most 5 times.
   - Any other 403, a 404 or a 401 is not retried.
   - Recording is idempotent, so a rerun is safe.
5. **Sync to FastAPI.** Whenever a comment's verdict changes, `sync_comment_feedback_task` posts it to FastAPI's internal `POST /feedback/upsert` (header `X-Internal-Secret`, the same secret the review call uses). The body has the comment, its PR number and its code hunk, cut from the diff stored on the review's `ReviewRun`.
   - A null signal deletes the stored example.
   - The route rejects oversized fields (hunk over 20,000 characters, body over 10,000, path over 1,000, category or severity over 50).
   - Failures are retried 5 times, a minute apart.
6. **Embedding.** FastAPI renders the hunk the way review retrieval renders a diff hunk, embeds it with `EMBEDDING_MODEL` (`RETRIEVAL_DOCUMENT`) and stores one row per comment and model in `feedback_embeddings`. The row is tagged `source_ref = "PR#<n>"` and replaces that comment's earlier row for the model.
7. **Review time.** The review reuses the query embeddings of its code search (one per hunk, at most 20) and reads the repository's `feedback_embeddings` rows of the configured model.
   - **Rows from the pull request under review are left out** (`source_ref` excluded, like code search does), so a PR's own feedback never steers its later reviews.
   - Examples need a cosine similarity of at least 0.7 to one of the hunks (`FEEDBACK_THRESHOLD`, a guess, not tuned), and the 3 closest of each signal (`FEEDBACK_TOP_K`) are used.
   - If the search fails (for example, the table doesn't exist), it is logged as `review.feedback_context_failed` and the review runs without examples.
8. **Prompt.** Accepted examples go in a `PREVIOUSLY ACCEPTED FINDINGS` section and rejected ones in `PREVIOUSLY REJECTED FINDINGS`, after every other section.
   - Each example is the file, category, severity, the comment (up to 600 characters) and its code (up to 30 lines).
   - The examples are wrapped and escaped in the review's untrusted-data delimiters like the diff, with one fixed line before each block saying how to use it.
   - The sections only get the tokens left after the diff and the other context sections, at most 1,000 tokens each, and are left out unless more than 150 tokens are free.
   - The diff's budget doesn't count them, so feedback never shortens the diff, and a review without feedback gets exactly the prompt it got before.

The review detail API returns each comment's verdict as `feedback: {signal, source, updated_at}` (or `null`), and the review page shows it as an Accepted or Rejected badge.

## Setup

- **Webhook events.** New webhooks are installed with `pull_request_review_comment` and `pull_request_review_thread` as well as `pull_request` and `push`. Webhooks installed before this change don't send the new events: add them in the repository's Settings → Webhooks, or reinstall the webhook. Reaction counting only needs `pull_request`.
- **Database.** Apply `backend/fastapi/migrations/sql/0004_feedback_embeddings.sql` by hand (see the file; it is idempotent and also adds `source_ref` to a table created by an earlier draft). Until it is applied, storing feedback fails (the Django task retries, then gives up) and reviews run without examples. Django's migration `reviews/0006_comment_feedback` adds `github_comment_id` and the `CommentFeedback` table.
- **Earlier reviews.** Comments posted before this change have no `github_comment_id`, so they get no feedback.

## Threat model

Rejected examples steer later reviews of a repository away from similar findings, so who can create them matters.

- **Can't influence feedback:**
  - anyone without write access to the repository: on a public repository, a stranger who opens a fork PR, reacts 👎, replies "false positive" or resolves a thread;
  - read-only organization members and collaborators;
  - bots;
  - the author of the pull request being reviewed, for that pull request, even with write access.

  Their signals are dropped before anything is stored.
- **Can't influence the same PR's later reviews:** feedback is stored tagged with its PR and that PR's reviews leave it out.
- **Can't impersonate the owner:** the connecting owner is recognised by GitHub user id, so someone who registers the owner's old login after a rename gets no trust from it, and the PR author is excluded by id as well as login.
- **Can't replay old events to undo newer ones:** see "Event order" above.
- **Can influence feedback:** the DevMind user who connected the repository, the repository owner, and users with write or admin permission. Their verdicts on comments in *other people's* pull requests are stored and can suppress similar findings in later reviews of the repository.
- **What remains:** a malicious or careless collaborator with write access can mark real findings as rejected on someone else's PR and so make similar findings less likely later. Write access already lets them merge code, so this doesn't give them anything they couldn't already do.

  Several things limit the effect:
  - only the 3 most similar rejected examples above the similarity threshold are used per review;
  - examples are shown as data inside the untrusted-data delimiters, not as instructions;
  - removing a verdict (thumbs, deleting the reply, unresolving) removes the example.

  The evals below include a control showing that a rejected "MD5 is weak" example did not hide a real MD5 password bug, but one control case is not a guarantee.

## Limits

- Reply verdicts come from fixed phrases, so a reply like "this is fine" is not counted.
- Reaction counting costs one call per comment with a 👍 or 👎 plus one cached permission lookup per reacting user, within the quota floor.
- The evals inject feedback examples straight into the prompt (`feedback:` in a case file), so they measure whether the examples change the model's output, not how well retrieval picks them.

## Evals

Cases with a `feedback:` block live in `backend/fastapi/evals/cases/feedback/`, outside the default case set, so the default run stays comparable with the committed reference results. The harness passes their examples to the review agent through the same formatter production uses.

- `feedback-md5-cache-key` and `feedback-random-jitter` are clean diffs, each with a rejected example of a false positive on the same pattern.
- `feedback-control-md5-password` is a real bug (MD5 for passwords) with the rejected "MD5 is weak" example from a cache key, to check that feedback doesn't hide real problems.

`--no-feedback` runs the cases without their examples. Its cassettes are `<case>.no-feedback.json`, or `<case>.no-feedback.<i>.json` with `--repeat`.

### Recorded results

The cases were recorded live twice with and twice without feedback, on commit `3d590c6`, with `groq/openai/gpt-oss-120b`. They are in `backend/fastapi/evals/results/feedback-runs/`: `fb1`, `fb2`, `nofb1` and `nofb2`, each a cassette directory plus `.json`/`.md` results. `tests/test_evals_feedback.py` checks that all four still replay to their recorded findings on the current code: the security fixes after `3d590c6` didn't change these cases' prompts.

Replay them with:

```bash
make eval EVAL_ARGS="--cases-dir evals/cases/feedback --cassettes-dir evals/results/feedback-runs/fb1"
make eval EVAL_ARGS="--cases-dir evals/cases/feedback --cassettes-dir evals/results/feedback-runs/nofb1 --no-feedback"
```

What the four runs show (from the results files):

- **Safety control holds.** `feedback-control-md5-password`: the MD5 password bug was found as `security/critical` at the labeled line in all 4 runs, with and without the rejected "MD5 is weak" example.
- **Suppression is not demonstrated.** The no-feedback runs didn't produce the false positive that the rejected examples describe, so these cases can't show feedback suppressing it.
  - `feedback-md5-cache-key`: without feedback, both runs mentioned MD5 only as `security/info` ("acceptable for non-cryptographic purposes"). With feedback, one run still had an MD5 comment as `security/warning` ("MD5 is a weak hash function; while not used for security here, using SHA-256 ...") and the other as `quality/info`.
  - `feedback-random-jitter`: no run, with or without feedback, said to use `secrets`. Every run instead flagged that the jitter makes the function nondeterministic for tests. That comment was `info` in both runs with feedback and `warning` in both runs without. Two samples per side are too few to claim an effect.

Conclusion: the feedback pipeline and the eval harness work, and the one safety control passed. Whether feedback reduces repeated false positives has not been measured, because these cases aren't discriminative: the model doesn't make the targeted mistake without feedback either. A follow-up will build cases from false positives seen recurring in real runs.
