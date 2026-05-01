#!/usr/bin/env bash
# PreToolUse hook on the Agent tool.
# Blocks subagent spawn if the prompt doesn't reference AGENTS.md.
# See /Users/themrburn/git/sanctum-terminal/AGENTS.md (subagent briefing pattern).

input=$(cat)
prompt=$(echo "$input" | jq -r '.tool_input.prompt // ""')

if echo "$prompt" | grep -qi 'AGENTS\.md'; then
  exit 0
fi

echo "Subagent briefing required: prompt MUST include 'Read AGENTS.md and <subsystem>/AGENTS.md before starting.' See /Users/themrburn/git/sanctum-terminal/AGENTS.md subagent briefing pattern." >&2
exit 2
