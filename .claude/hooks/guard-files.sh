#!/usr/bin/env bash
# PreToolUse(Edit|Write): keep secrets and generated output out of reach.
set -euo pipefail

path=$(jq -r '.tool_input.file_path // ""')
name=$(basename "$path")

if [[ "$name" == .env* && "$name" != ".env.example" ]]; then
  echo "Blocked by .claude/hooks/guard-files.sh: $name holds real secrets; edit .env.example instead." >&2
  exit 2
fi
if [[ "$path" == */graphify-out/* ]]; then
  echo "Blocked by .claude/hooks/guard-files.sh: graphify-out/ is generated; run 'graphify update .' instead." >&2
  exit 2
fi
exit 0
