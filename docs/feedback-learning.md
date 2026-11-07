# Learning from reviewer feedback

DevMind records what developers think of its inline comments, and shows later reviews of the same repository the most similar accepted and rejected comments. This page defines what counts as accepted or rejected, where the data flows, and what to set up. Issue: #74.

## What counts as accepted or rejected

Only DevMind's inline comments get feedback. Comments folded into the review body (no valid line) have no GitHub comment of their own, so nothing can be attributed to them.

| Source | When it is read | Accepted | Rejected | No signal |
| --- | --- | --- | --- | --- |
| `reaction` | When the PR closes (merged or not), from the 👍 (`+1`) and 👎 (`-1`) counts on each comment | more 👍 than 👎 | more 👎 than 👍 | a tie, including no reactions; any earlier reaction verdict is removed. Other reactions are ignored. |
| `reply` | `pull_request_review_comment` webhook, `created` or `edited`, for a reply to a DevMind comment | the reply starts with `fixed`, `done`, `good catch`, `nice catch`, `addressed` or `agreed` | the reply starts with `false positive`, `not an issue`, `not a bug`, `won't fix`, `wont fix`, `wontfix` or `disagree` | any other reply. Replies from bot accounts are ignored. |
| `resolved` | `pull_request_review_thread` webhook | the comment's thread is `resolved` | (none) | `unresolved` removes the verdict |

Reply matching is case-insensitive, ignores quoted lines (`> ...`), and needs the phrase to end at a word boundary (`Fixed.` matches, `Doneness` doesn't). The phrase lists are `ACCEPTED_REPLY_PHRASES` and `REJECTED_REPLY_PHRASES` in `backend/django/apps/reviews/services/feedback.py`.

Each comment has at most one `CommentFeedback` row per source (unique on comment and source). A later event from the same source replaces the row: a second reaction count, a later reply with a verdict, or unresolving a thread. Reactions are counted again if the PR is reopened and closed again.

When sources disagree, the comment's verdict comes from the first source in this order: `reaction`, `reply`, `resolved`. A vote is the most explicit signal; people also resolve threads to dismiss comments they disagree with, so resolving counts least.

DevMind posts with the repository owner's token, so its comments appear as the owner's. Reactions and replies from the owner count like anyone else's.

## Data flow

1. **Posting.** After creating a review on GitHub, `GitHubPoster` lists that review's comments (`GET /repos/{repo}/pulls/{n}/reviews/{id}/comments`) and stores each one's id in `ReviewComment.github_comment_id`, matched by file path and body. If the lookup fails, the comments are still posted but get no feedback. A body-only fallback review (after a 422) has no inline comments, so no ids.
2. **Webhooks.** `pull_request_review_thread` and `pull_request_review_comment` go through the same HMAC check as `pull_request`. The handler finds the DevMind comment by GitHub id within the repository named in the payload (active repositories only) and records the verdict in the request; it is one small write. `pull_request` `closed` queues `fetch_comment_reactions_task`.
3. **Reactions.** The task makes one paginated call per PR, `GET /repos/{repo}/pulls/{n}/comments`, whose items include reaction counts. It uses the repository owner's token. It stops before the next page when fewer than 100 requests are left in the token's hourly quota (`RATE_LIMIT_FLOOR`), and a 403 or 429 rate-limit response makes it retry after the reset (`X-RateLimit-Reset` or `Retry-After`), waiting between 1 minute and 1 hour, at most 5 times. Recording is idempotent, so a rerun is safe. Comments deleted on GitHub keep their earlier verdict.
4. **Sync to FastAPI.** Whenever a comment's verdict changes, `sync_comment_feedback_task` posts it to FastAPI's internal `POST /feedback/upsert` (header `X-Internal-Secret`, the same secret the review call uses) with the comment body and its code hunk, cut from the diff stored on the review's `ReviewRun`. A null signal deletes the stored example. Failures are retried 5 times, a minute apart.
5. **Embedding.** FastAPI renders the hunk the way review retrieval renders a diff hunk, embeds it with `EMBEDDING_MODEL` (`RETRIEVAL_DOCUMENT`) and stores one row per comment and model in `feedback_embeddings`, replacing that comment's earlier row for the model.
6. **Review time.** The review reuses the query embeddings of its code search (one per hunk, at most 20) and reads the repository's `feedback_embeddings` rows of the configured model. Examples need a cosine similarity of at least 0.7 to one of the hunks (`FEEDBACK_THRESHOLD`, a guess, not tuned), and the 3 closest of each signal (`FEEDBACK_TOP_K`) are used. If the search fails (for example, the table doesn't exist), it is logged as `review.feedback_context_failed` and the review runs without examples.
7. **Prompt.** Accepted examples go in a `PREVIOUSLY ACCEPTED FINDINGS` section and rejected ones in `PREVIOUSLY REJECTED FINDINGS`, after every other section. Each example is the file, category, severity, the comment (up to 600 characters) and its code (up to 30 lines). The examples are wrapped in the review's untrusted-data delimiters like the diff, with one fixed line before each block saying how to use it. The sections only get the tokens left after the diff and the other context sections, at most 1,000 tokens each, and are left out unless more than 150 tokens are free. The diff's budget doesn't count them, so feedback never shortens the diff, and a review without feedback gets exactly the prompt it got before.

The review detail API returns each comment's verdict as `feedback: {signal, source, updated_at}` (or `null`), and the review page shows it as an Accepted or Rejected badge.

## Setup

- **Webhook events.** New webhooks are installed with `pull_request_review_comment` and `pull_request_review_thread` as well as `pull_request` and `push`. Webhooks installed before this change don't send the new events: add them in the repository's Settings → Webhooks, or reinstall the webhook. Reaction counting only needs `pull_request`.
- **Database.** Apply `backend/fastapi/migrations/sql/0004_feedback_embeddings.sql` by hand (see the file). Until it is applied, storing feedback fails (the Django task retries, then gives up) and reviews run without examples. Django's migration `reviews/0006_comment_feedback` adds `github_comment_id` and the `CommentFeedback` table.
- **Earlier reviews.** Comments posted before this change have no `github_comment_id`, so they get no feedback.

## Limits

- Anyone who can react, reply or resolve threads on the repository can mark comments rejected, and rejected examples steer later reviews of that repository away from similar findings. Only the 3 most similar rejected examples above the threshold are used per review, and they are shown as data, not instructions, but a determined collaborator can still suppress a kind of finding in their repository.
- Reply verdicts come from fixed phrases, so a reply like "this is fine" is not counted.
- The evals inject feedback examples straight into the prompt (`feedback:` in a case file), so they measure whether the examples change the model's output, not how well retrieval picks them.

## Evals

Cases with a `feedback:` block (`backend/fastapi/evals/cases/feedback-*.yaml`) pass their examples to the review agent through the same formatter production uses. `feedback-md5-cache-key` and `feedback-random-jitter` are clean diffs with a rejected example of the same false positive; `feedback-control-md5-password` is a real bug (MD5 for passwords) with the rejected "MD5 is weak" example from a cache key, to check that feedback doesn't hide real problems.

Run them with and without their examples:

```bash
make eval EVAL_ARGS="--only feedback-md5-cache-key,feedback-random-jitter,feedback-control-md5-password"
make eval EVAL_ARGS="--only feedback-md5-cache-key,feedback-random-jitter,feedback-control-md5-password --no-feedback"
```

`--no-feedback` drops the examples, and its cassettes are stored as `<case>.no-feedback.json` next to the normal ones. Record both with `make eval-record` (add `--no-feedback` for the second). Results are reported only from recorded runs.
