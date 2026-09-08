---
description: Fetch a Jira card, run grooming, post "## AI Grooming" comment, set AI Stage = Groomed.
argument-hint: <CARD-KEY>
---

# /vc:pull — Grooming pass on a Jira card

Wraps the Atlassian MCP + our grooming prompt. Does **not** touch code. Downstream: `/vc:diagnose` reads what this posts.

## Preflight (must complete before any Jira call)

1. Read `.claude/plugins/vc/config.md`. Extract:
   - `cloudId`
   - `AI Stage` customfield ID
   - Plugin version (read from `.claude/plugins/vc/.claude-plugin/plugin.json` `.version`)
2. If `cloudId` is still the `<REPLACE_...>` placeholder, STOP and tell the user to fill config.md first.
3. Validate `$1` (the card key) matches `^[A-Z]+-\d+$`. If not, STOP.

## Step 1 — Fetch the card

Call `mcp__claude_ai_Atlassian__getJiraIssue` with:
- `cloudId`: from config
- `issueIdOrKey`: `$1`
- Include comments, description, acceptance criteria, current AI Stage value.

Also pull linked/sub-task keys so grooming can reason about scope.

## Step 2 — Run grooming prompt

> **TODO(next step):** paste the vCreative grooming prompt here.
>
> Placeholder behavior for now: produce a short markdown block with sections
> `### Understanding`, `### Assumptions`, `### Open Questions`, `### Proposed Sub-tasks`.

Constraints on the grooming output:
- Reference the card by key (`$1`), not by summary.
- If sub-tasks are proposed, each gets a suggested slug in the `abc-1234-short-description` format from `config.md`.

## Step 3 — Post the comment

Call `mcp__claude_ai_Atlassian__addCommentToJiraIssue` with:
- `cloudId`: from config
- `issueIdOrKey`: `$1`
- Body (ADF or wiki-markdown — whichever the MCP currently accepts):

```
## AI Grooming

<grooming output from Step 2>

---
<!-- posted by vc plugin v<PLUGIN_VERSION> -->
```

The version stamp is **mandatory** — future prompt changes must be attributable.

## Step 4 — Set AI Stage = Groomed

Call `mcp__claude_ai_Atlassian__editJiraIssue` with:
- `cloudId`: from config
- `issueIdOrKey`: `$1`
- Fields: `{ "<AI_Stage_customfield_id>": { "value": "Groomed" } }`

## Step 5 — Report

One-sentence summary to the user: card key, Groomed stage set, link to the posted comment if the MCP returns one.

## Invariants (do not violate)

- **I9 — Wrap BMB, never fork.** This command does not touch memory-bank or run BMB. It only produces Jira artifacts that later `/vc:*` commands (and eventually `/bmb:task`) consume.
- Pass `cloudId` on **every** MCP call. No exceptions.
- Always include the plugin version footer in the posted comment.
