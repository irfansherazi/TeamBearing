#!/usr/bin/env bash
# Assertion-immutability guardrail for the Edit tool.
# Blocks edits to test files whose diff touches an expect(...) or assert(...) line.
# Adding non-assertion changes (e.g., data-testid attributes) is allowed.

set -euo pipefail

REASON="Test assertions are immutable. Escalate instead of editing."

INPUT="$(cat)"

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
if [[ "$TOOL_NAME" != "Edit" ]]; then
  exit 0
fi

FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"
OLD_STRING="$(printf '%s' "$INPUT" | jq -r '.tool_input.old_string // empty')"
NEW_STRING="$(printf '%s' "$INPUT" | jq -r '.tool_input.new_string // empty')"

is_test_file() {
  local p="$1"
  case "$p" in
    *.test.ts|*.test.tsx|*.test.js|*.test.jsx|*.test.mjs|*.test.cjs) return 0 ;;
    *.spec.ts|*.spec.tsx|*.spec.js|*.spec.jsx|*.spec.mjs|*.spec.cjs) return 0 ;;
    *_test.py|*test_*.py|*.test.py) return 0 ;;
  esac
  case "$p" in
    */tests/*|*/test/*|*/__tests__/*|*/playwright/tests/*|*/spec/*) return 0 ;;
  esac
  return 1
}

if ! is_test_file "$FILE_PATH"; then
  exit 0
fi

touches_assertion() {
  local content="$1"
  if printf '%s' "$content" | grep -qE '(\bexpect[[:space:]]*\()|(\bassert[[:space:]]*[.(])'; then
    return 0
  fi
  return 1
}

if touches_assertion "$OLD_STRING" || touches_assertion "$NEW_STRING"; then
  jq -n --arg r "$REASON" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  printf '%s\n' "$REASON" >&2
  exit 2
fi

exit 0
