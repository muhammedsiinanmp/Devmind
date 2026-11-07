# 0005: Feedback trust model

Status: accepted. Implemented in #109 (D1).

## Context

DevMind stores developers' verdicts on its inline comments (reactions when the PR closes, verdict replies such as "false positive", resolved threads) and shows later reviews of the same repository the most similar accepted and rejected comments. A rejected example steers later reviews away from similar findings. If anyone could create one, a stranger on a public repository, or the author of the code under review, could suppress real findings: a feedback-poisoning attack.

## Decision

Count a signal only from a trusted user (`TrustChecker` in `backend/django/apps/reviews/services/feedback.py`):

- the DevMind user who connected the repository, matched by GitHub numeric id, never by login;
- the repository owner;
- users whose permission on the repository is `write` or `admin`, checked with GitHub's collaborator-permission API. `MEMBER` and `COLLABORATOR` associations always get that check, because neither implies write access.

Never count bots, and never count the pull request's own author on that pull request. Store feedback tagged with its PR and exclude that PR's examples from its later reviews. Ignore events older than the stored one for the same comment and source, so retries and redeliveries can't undo newer verdicts. Show examples to the model as data inside the untrusted-data delimiters, at most 3 per signal above a similarity threshold.

## Consequences

- People without write access, bots and the PR author can't influence feedback; renaming the owner's account doesn't transfer trust to whoever takes the old login.
- A collaborator with write access can still mark real findings as rejected on someone else's PR. Write access already lets them merge code, so this gives them nothing new; removing the verdict removes the example.
- Each reaction check costs GitHub API calls (one per comment with a 👍 or 👎, plus one cached permission lookup per reacting user), bounded by a rate-limit floor.
- Whether feedback actually reduces repeated false positives hasn't been measured: the recorded cases weren't discriminative (#111). One control case showed a rejected "MD5 is weak" example didn't hide a real MD5 password bug. Full threat model: [feedback-learning.md](../feedback-learning.md#threat-model).
