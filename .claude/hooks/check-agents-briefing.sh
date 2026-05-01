#!/usr/bin/env bash
# PreToolUse hook on the Agent tool.
# Blocks subagent spawn if the prompt doesn't reference AGENTS.md properly.
# See /Users/themrburn/git/sanctum-terminal/AGENTS.md (subagent briefing pattern).

input=$(cat)
prompt=$(echo "$input" | jq -r '.tool_input.prompt // ""')
log_dir="$(dirname "$0")"
log_file="$log_dir/blocked.log"

# Require the imperative form: "Read AGENTS.md" or "read ... AGENTS.md".
# Closes the accidentally-bypass case (e.g. a passing mention or "do not read AGENTS.md").
if echo "$prompt" | grep -qiE 'read[^.]{0,80}AGENTS\.md'; then
  exit 0
fi

# Log the block so we can audit hook frequency over time.
ts=$(date '+%Y-%m-%d %H:%M:%S')
preview=$(echo "$prompt" | head -c 200 | tr '\n' ' ')
printf '%s | blocked | %s\n' "$ts" "$preview" >> "$log_file"

echo "Subagent briefing required: prompt MUST include 'Read AGENTS.md and <subsystem>/AGENTS.md before starting.' See /Users/themrburn/git/sanctum-terminal/AGENTS.md subagent briefing pattern." >&2
exit 2
