---
description: Compile evidence for a Jira card (tests, screenshots, PR, artifacts) and post "## AI Evidence" comment.
argument-hint: <CARD-KEY>
---

# /vc:evidence — Post evidence back to Jira

Closes the loop: takes what BMB produced (branch, PR, tests, artifacts) and reports it back on the card in one structured comment.

## Preflight

1. Read `.claude/plugins/vc/config.md`. Extract `cloudId`, `AI Stage` customfield ID, and plugin version.
2. Validate `$1` matches `^[A-Z]+-\d+$`.

## Step 1 — Resolve the slug

Look up the slug for this card:
- Preferred: `git -C $(git rev-parse --show-toplevel) branch --list "feature/*$(echo $1 | tr A-Z a-z)*" "task/*$(echo $1 | tr A-Z a-z)*"`
- Fall back to asking the user if the branch listing is ambiguous.

## Step 2 — Compile evidence

> **TODO(next step):** paste the vCreative evidence prompt here.
>
> Placeholder scaffold — collect and summarize the following, each with a link/path:
> - **Branch**: `feature/<slug>` (from Step 1)
> - **PR**: `gh pr list --head <branch> --json url,state,title` — one line
> - **BMB task file**: `memory-bank/tasks/<slug>.md` — link the section that shows current phase state
> - **Reflection**: `memory-bank/reflection/<slug>-reflection.md` if it exists
> - **Test artifacts**: newest matching entry under `playwright-report/`, `.claude-logs/`, or `storage/ac_parse_baseline/`
> - **Screenshots/GIFs**: any `*.png`/`*.gif` produced during the run (path only, don't inline)
>
> Do NOT read entire artifact files into the comment. One-line pointer per artifact.

## Step 3 — Post the comment

`mcp__claude_ai_Atlassian__addCommentToJiraIssue` with:
- `cloudId` (from config)
- `issueIdOrKey`: `$1`
- Body:

```
## AI Evidence

**Slug:** <slug>
**Branch:** <branch>
**PR:** <url> — <state>

### Artifacts
- <bulleted pointer list from Step 2>

### Verification
- <one-line status per test / check run>

---
<!-- posted by vc plugin v<PLUGIN_VERSION> -->
```

## Step 4 — Update AI Stage

`mcp__claude_ai_Atlassian__editJiraIssue`:
- `cloudId`
- `issueIdOrKey`: `$1`
- Fields: `{ "<AI_Stage_customfield_id>": { "value": "Evidence Ready" } }`

## Step 5 — Report

One sentence to the user: card, slug, PR state, `Evidence Ready` set.

## Invariants

- **I9 — Wrap BMB, never fork.** Read from `memory-bank/` and `git`, never write.
- `cloudId` on every MCP call.
- Plugin version footer on the posted comment — mandatory for attributing prompt-quality changes.
- Do not inline large artifacts. Pointers only.
