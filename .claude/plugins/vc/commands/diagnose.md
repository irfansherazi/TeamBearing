---
description: Read prior grooming, deep-analyse against current code, post "## AI Diagnosis" comment, set AI Stage = Diagnosed with AI Confidence.
argument-hint: <CARD-KEY>
---

# /vc:diagnose — Code-grounded diagnosis on a Jira card

Consumes the `## AI Grooming` comment posted by `/vc:pull` and pairs it with a real read of the code in this repo. Downstream: `/vc:fix` uses the diagnosis to scope the BMB task.

## Preflight

1. Read `.claude/plugins/vc/config.md`. Extract `cloudId`, `AI Stage` customfield ID, `AI Confidence` customfield ID, and the plugin version from `.claude/plugins/vc/.claude-plugin/plugin.json` `.version`.
2. If any config value is still a `<REPLACE_...>` placeholder, STOP.
3. Validate `$1` matches `^[A-Z]+-\d+$`.

## Step 1 — Fetch card + prior grooming

Call `mcp__claude_ai_Atlassian__getJiraIssue` (cloudId + `$1`) and locate the most recent `## AI Grooming` comment. If none exists, STOP and instruct the user to run `/vc:pull $1` first.

## Step 2 — Code-grounded analysis

> **TODO(next step):** paste the vCreative diagnosis prompt here.
>
> Placeholder scaffold:
> - Identify the code area(s) implicated by the card + grooming.
> - Use Grep/Read (never speculate) to confirm suspected paths.
> - Prefer the `Explore` agent when the surface is > 3 files.
> - Section the output as `### Root Cause`, `### Affected Files`, `### Risk`, `### Proposed Fix Sketch`.

The diagnosis MUST produce an **AI Confidence** verdict (`Low` | `Medium` | `High`) at the end, with a one-line justification.

## Step 3 — Post the comment

`mcp__claude_ai_Atlassian__addCommentToJiraIssue` with:
- `cloudId` (from config)
- `issueIdOrKey`: `$1`
- Body:

```
## AI Diagnosis

<diagnosis output from Step 2>

**AI Confidence:** <Low|Medium|High> — <justification>

---
<!-- posted by vc plugin v<PLUGIN_VERSION> -->
```

## Step 4 — Update card fields

Single `mcp__claude_ai_Atlassian__editJiraIssue` call:
- `cloudId` (from config)
- `issueIdOrKey`: `$1`
- Fields:
  - `<AI_Stage_customfield_id>`: `{ "value": "Diagnosed" }`
  - `<AI_Confidence_customfield_id>`: `{ "value": "<Low|Medium|High>" }`

## Step 5 — Report

One sentence: card, Diagnosed stage set, Confidence value, comment link.

## Invariants

- **I9 — Wrap BMB, never fork.** No memory-bank writes here.
- `cloudId` on every MCP call.
- Plugin version footer on the posted comment.
- No file edits. Reads only. If you catch yourself wanting to fix code, stop and hand off to `/vc:fix`.
