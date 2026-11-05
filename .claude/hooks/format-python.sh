#!/usr/bin/env bash
# PostToolUse(Edit|Write): run the service's own black on an edited Python file,
# so CI's `black --check` never fails on formatting. Silent no-op when the
# service's virtualenv isn't synced.
set -uo pipefail

path=$(jq -r '.tool_input.file_path // ""')
[[ "$path" == *.py ]] || exit 0

case "$path" in
  */backend/django/*) svc="${path%%/backend/django/*}/backend/django" ;;
  */backend/fastapi/*) svc="${path%%/backend/fastapi/*}/backend/fastapi" ;;
  *) exit 0 ;;
esac

[[ -x "$svc/.venv/bin/black" ]] || exit 0
"$svc/.venv/bin/black" -q "$path" || true
exit 0
