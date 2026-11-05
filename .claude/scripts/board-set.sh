#!/usr/bin/env bash
# Set any board field for an issue (adds the issue to the board if missing).
# Usage: .claude/scripts/board-set.sh <issue> <field> <value>
#   Single-select fields (Status, Wave, Epic) take an option name; text fields (Agent, PR) take any text.
set -euo pipefail

issue="$1"
field="$2"
value="$3"
config="$(dirname "$0")/../board.json"
owner=$(jq -r .owner "$config")
project=$(jq -r .number "$config")
repo=$(jq -r .repo "$config")

project_id=$(gh project view "$project" --owner "$owner" --format json -q .id)
field_json=$(gh project field-list "$project" --owner "$owner" --format json)
field_id=$(jq -r --arg f "$field" '.fields[] | select(.name==$f) | .id' <<<"$field_json")
[[ -n "$field_id" ]] || { echo "No field named '$field'" >&2; exit 1; }

item_id=$(gh project item-list "$project" --owner "$owner" --limit 300 --format json \
  | jq -r --argjson n "$issue" '.items[] | select(.content.number==$n) | .id')
if [[ -z "$item_id" ]]; then
  item_id=$(gh project item-add "$project" --owner "$owner" --url "https://github.com/$repo/issues/$issue" --format json -q .id)
fi

option_id=$(jq -r --arg f "$field" --arg v "$value" \
  '.fields[] | select(.name==$f) | (.options // [])[] | select(.name==$v) | .id' <<<"$field_json")
if [[ -n "$option_id" ]]; then
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --single-select-option-id "$option_id" >/dev/null
elif [[ -z "$value" ]]; then
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --clear >/dev/null
else
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --text "$value" >/dev/null
fi
echo "#$issue $field -> $value"
