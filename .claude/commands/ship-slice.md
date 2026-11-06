---
description: Ship one slice issue - implement it in a worktree, review it, merge it into dev, update the board
argument-hint: <issue-number> [more issue numbers to run in parallel]
---

Ship slice issue(s): $ARGUMENTS

The board is in `.claude/board.json`. Set any card field with `.claude/scripts/board-set.sh <issue> <Status|Wave|Epic|Agent|PR> "<value>"`.

For each issue number:
1. Check that its blockers are closed and that it is labelled `agent-ready`. Skip it and explain if not.
2. Set Status **Agent working** and Agent `slice-implementer`.
3. Start a `slice-implementer` agent with `isolation: "worktree"` in the background, passing the issue number. Run several issues in parallel only if their Scope sections don't name the same files.
4. When it returns a PR, set Status **In review** and the PR field. Review the PR with `ai-pipeline-reviewer` if it touches `backend/fastapi/agents`, `services` or `evals`, otherwise with `verifier`. Post the review as a PR comment (`gh pr comment`).
5. If the review says REQUEST CHANGES or FAIL, set Status back to **Agent working**, send the findings to the same implementer agent once, then re-review.
6. If the verdict is PASS/APPROVE and CI is green, the main session (never a subagent) merges into `dev` with `gh pr merge <pr> --merge`, then sets Status **Done**. Hold the merge if the owner queue (#86) says something must happen first.
7. Anything only the owner can do goes into the pinned issue #86, never only into chat.

Finish with a table: issue, PR, review verdict, CI state, merged or held (and why).
