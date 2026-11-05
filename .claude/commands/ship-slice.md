---
description: Ship one slice issue - implement it in a worktree, review it, open the PR, update the board
argument-hint: <issue-number> [more issue numbers to run in parallel]
---

Ship slice issue(s): $ARGUMENTS

For each issue number:
1. Check that its blockers are closed and that it is labelled `agent-ready`. Skip it and explain if not.
2. Move its board card to **In Progress** with `.claude/scripts/board-status.sh <n> "In Progress"`.
3. Start a `slice-implementer` agent with `isolation: "worktree"` in the background, passing the issue number. Run several issues in parallel only if their Scope sections don't name the same files.
4. When it returns a PR, review it with `ai-pipeline-reviewer` if the PR touches `backend/fastapi/agents`, `services` or `evals`, otherwise with `verifier`. Post the review result as a PR comment (`gh pr comment`).
5. If the review says REQUEST CHANGES or FAIL, send the findings back to the same implementer agent once. Then re-review.
6. Move the card to **In Review** with `.claude/scripts/board-status.sh <n> "In Review"`.

Never merge. Finish with a table: issue, PR, review verdict, CI state, open questions for the owner.
