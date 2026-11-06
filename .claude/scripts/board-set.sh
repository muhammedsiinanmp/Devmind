#!/usr/bin/env bash
# Set a board field for an issue: one GraphQL mutation per call once the cache is warm.
# Usage: .claude/scripts/board-set.sh <issue> <Status|Wave|Epic|Agent|PR> "<value>"
#        .claude/scripts/board-set.sh --refresh   (rebuild the ID cache)
# IDs are cached in .claude/board-cache.json (gitignored); --refresh rebuilds it.
set -euo pipefail

dir="$(cd "$(dirname "$0")/.." && pwd)"
config="$dir/board.json"
cache="$dir/board-cache.json"
owner=$(jq -r .owner "$config")
project=$(jq -r .number "$config")
repo=$(jq -r .repo "$config")

refresh() {
  local fields items
  fields=$(gh project field-list "$project" --owner "$owner" --format json)
  items=$(gh project item-list "$project" --owner "$owner" --limit 300 --format json)
  jq -n --arg pid "$(gh project view "$project" --owner "$owner" --format json -q .id)" \
    --argjson f "$fields" --argjson i "$items" '{
      project_id: $pid,
      fields: ($f.fields | map({key: .name, value: {id, options: ((.options // []) | map({key: .name, value: .id}) | from_entries)}}) | from_entries),
      items: ($i.items | map(select(.content.number != null) | {key: (.content.number | tostring), value: .id}) | from_entries)
    }' > "$cache"
}

if [[ "${1:-}" == "--refresh" ]]; then refresh; echo "cache rebuilt: $cache"; exit 0; fi

issue="$1"
field="$2"
value="${3:-}"
[[ -f "$cache" ]] || refresh

project_id=$(jq -r .project_id "$cache")
field_id=$(jq -r --arg f "$field" '.fields[$f].id // empty' "$cache")
[[ -n "$field_id" ]] || { echo "No field named '$field' (try --refresh)" >&2; exit 1; }

item_id=$(jq -r --arg n "$issue" '.items[$n] // empty' "$cache")
if [[ -z "$item_id" ]]; then
  item_id=$(gh project item-add "$project" --owner "$owner" --url "https://github.com/$repo/issues/$issue" --format json -q .id)
  tmp=$(mktemp) && jq --arg n "$issue" --arg id "$item_id" '.items[$n] = $id' "$cache" > "$tmp" && mv "$tmp" "$cache"
fi

option_id=$(jq -r --arg f "$field" --arg v "$value" '.fields[$f].options[$v] // empty' "$cache")
if [[ -n "$option_id" ]]; then
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --single-select-option-id "$option_id" >/dev/null
elif [[ -z "$value" ]]; then
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --clear >/dev/null
else
  gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --text "$value" >/dev/null
fi
echo "#$issue $field -> $value"
