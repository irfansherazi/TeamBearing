---
description: Derive the slug from the card + sub-task description, then delegate to /bmb:task and /bmb:build. Wraps BMB, does not reimplement it.
argument-hint: <CARD-KEY> [sub-task-key-or-description]
---

# /vc:fix — Delegate implementation to BMB

Turns a diagnosed Jira card into a BMB task and kicks off the build. This is a **wrapper**, not a reimplementation — we call `/bmb:task` and `/bmb:build` via the Skill tool. Never inline BMB logic here.

## Preflight

1. Read `.claude/plugins/vc/config.md`. Extract `cloudId` and plugin version.
2. Validate `$1` matches `^[A-Z]+-\d+$`.
3. Fetch card via `mcp__claude_ai_Atlassian__getJiraIssue` (cloudId + `$1`) to confirm AI Stage is at least `Diagnosed`. If not, STOP and instruct the user to run `/vc:diagnose $1` first.

## Step 1 — Pick the sub-task description

- If `$2` is present and matches `^[A-Z]+-\d+$`, fetch that sub-task's summary via the MCP.
- Otherwise treat `$2` (or the parent card's summary if `$2` is empty) as the working description.

## Step 2 — Derive the slug

Format: `abc-1234-short-description` (from `.claude/plugins/vc/config.md` → **Slug convention**).

Algorithm:
- Card key lowercased with hyphen preserved: `VC2-8990` → `vc2-8990`.
- Short description: take the sub-task summary, strip filler words (`the`, `a`, `fix`, `bug`, `issue`), lowercase, kebab-case, cap at 5 tokens.
- Join with `-`. Result: `vc2-8990-add-script-library-slideout-close`.

Show the derived slug to the user in one line and proceed.

## Step 3 — Delegate to `/bmb:task`

Invoke via the `Skill` tool:

```
Skill: bmb:task
args: --slug <derived-slug> <sub-task-description-summary>
```

BMB owns everything from here — memory-bank task file creation, branch cut, worktree provisioning. Do not touch memory-bank yourself (**Invariant I9 — wrap, don't fork**).

## Step 4 — Delegate to `/bmb:build`

Once `/bmb:task` reports success, invoke:

```
Skill: bmb:build
args: <derived-slug>
```

Let BMB run the phase. Do not interpret its output beyond surfacing the final status to the user.

## Step 5 — (Optional) Update card

If the BMB build reaches phase completion cleanly, post a short `## AI Fix` comment with:
- The slug used
- The `/bmb:build` outcome summary
- Plugin version footer:
  ```
  <!-- posted by vc plugin v<PLUGIN_VERSION> -->
  ```

This step is optional for now — leave it commented out until we decide whether `/vc:evidence` fully replaces it.

## Invariants

- **I9 — Wrap BMB, never fork.** All memory-bank / git / build behavior comes from BMB via `Skill`. If you feel the urge to write to `memory-bank/`, STOP.
- Slug format is non-negotiable — it rides through branch names, commits, and PR titles.
- `cloudId` on every MCP call.
