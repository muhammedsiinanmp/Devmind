#!/usr/bin/env bash
# Move an issue's card on the DevMind GitHub Project to a Status column.
# Usage: .claude/scripts/board-status.sh <issue-number> "<Status option name>"
# Needs a gh token with the `project` scope (gh auth refresh -s project).
set -euo pipefail

issue="$1"
status="$2"
config="$(dirname "$0")/../board.json"
owner=$(jq -r .owner "$config")
project=$(jq -r .number "$config")

project_id=$(gh project view "$project" --owner "$owner" --format json -q .id)
field_json=$(gh project field-list "$project" --owner "$owner" --format json)
field_id=$(jq -r '.fields[] | select(.name=="Status") | .id' <<<"$field_json")
option_id=$(jq -r --arg s "$status" '.fields[] | select(.name=="Status") | .options[] | select(.name==$s) | .id' <<<"$field_json")
[[ -n "$option_id" ]] || { echo "No Status option named '$status'" >&2; exit 1; }

item_id=$(gh project item-list "$project" --owner "$owner" --limit 200 --format json \
  | jq -r --argjson n "$issue" '.items[] | select(.content.number==$n) | .id')
if [[ -z "$item_id" ]]; then
  repo=$(jq -r .repo "$config")
  item_id=$(gh project item-add "$project" --owner "$owner" --url "https://github.com/$repo/issues/$issue" --format json -q .id)
fi

gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --single-select-option-id "$option_id" >/dev/null
echo "#$issue -> $status"
