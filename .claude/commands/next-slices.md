---
description: List open DevMind slices that are unblocked and ready for an agent
---

1. List open slice issues: `gh issue list --label slice --state open --limit 100 --json number,title,labels`.
2. For each one, read its blockers: `gh api repos/muhammedsiinanmp/Devmind/issues/<n>/dependencies/blocked_by -q '.[] | "\(.number) \(.state)"'`.

Reply with a table of three groups:
1. **Ready now:** every blocker closed and labelled `agent-ready`.
2. **Needs the owner:** labelled `needs-human`.
3. **Blocked:** with the open blockers.

Then say which "Ready now" slices can run in parallel without editing the same files, based on each issue's Scope section.
