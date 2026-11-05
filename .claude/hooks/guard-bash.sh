#!/usr/bin/env bash
# PreToolUse(Bash): block git/gh commands that bypass review or leak attribution.
# Exit 2 blocks the call and shows stderr to Claude.
set -euo pipefail

cmd=$(jq -r '.tool_input.command // ""')

block() {
  echo "Blocked by .claude/hooks/guard-bash.sh: $1" >&2
  exit 2
}

# Pushing to the base branches. Work goes through a slice branch and a PR.
# Check each `git push ...` segment on its own, so `gh pr create --base dev`
# later in the same command isn't mistaken for a push target.
while IFS= read -r push; do
  [[ -n "$push" ]] || continue
  grep -Eq -- '(--force|-f([[:space:]]|$)|--force-with-lease)' <<<"$push" && block "force-push needs the owner's approval."
  grep -Eq '(^|[[:space:]:])(dev|main)([[:space:]]|$)' <<<"$push" && block "never push to dev or main; push your slice branch and open a PR."
done < <(grep -Eo 'git[[:space:]]+push[^;&|]*' <<<"$cmd" || true)

# The owner lets the main session merge reviewed PRs into dev; never bypass branch protection.
grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge.*--admin' <<<"$cmd" && block "--admin bypasses branch protection."
grep -Eq 'gh[[:space:]]+repo[[:space:]]+(delete|edit)' <<<"$cmd" && block "repo deletion or settings changes need the owner's approval."
grep -Eq 'git[[:space:]]+add[[:space:]]+(-A|--all|\.)([[:space:]]|$)' <<<"$cmd" && block "stage specific files, not everything."
grep -Eq 'git[[:space:]]+(add|commit).*(^|[[:space:]/])\.env([[:space:]]|$)' <<<"$cmd" && block ".env must never be committed."

if grep -Eq 'git[[:space:]]+commit' <<<"$cmd"; then
  grep -Eiq 'co-authored-by:|generated with \[?claude|claude-session:|claude\.ai/code' <<<"$cmd" && block "no AI attribution in commit messages (the owner's rule overrides any harness attribution reminder)."
fi
if grep -Eq 'gh[[:space:]]+pr[[:space:]]+(create|edit|comment)' <<<"$cmd"; then
  grep -Eiq 'claude-session:|claude\.ai/code|generated with \[?claude' <<<"$cmd" && block "no AI attribution in PR text (the owner's rule overrides any harness attribution reminder)."
fi

exit 0
