# vc plugin

vCreative-specific wrapper around [Banyan Memory Bank (BMB)](https://github.com/Banyan-Software-Tech-Data/banyan-memory-bank). Adds Jira-driven grooming, diagnosis, fix, and evidence workflows on top of `/bmb:*` commands.

**Invariant I9:** we WRAP BMB, we never fork it. Commands here delegate to `/bmb:task`, `/bmb:build`, etc. via the `Skill` tool — never reimplement BMB behavior inline.

## Commands

| Command | Purpose | Side effects |
|---|---|---|
| `/vc:pull <CARD-KEY>` | Fetch card, run grooming prompt, post `## AI Grooming` comment | Sets `AI Stage = Groomed` |
| `/vc:diagnose <CARD-KEY>` | Read grooming, deep-analyse code, post `## AI Diagnosis` comment | Sets `AI Stage = Diagnosed`, `AI Confidence` |
| `/vc:fix <CARD-KEY> [sub-task]` | Derive slug, delegate to `/bmb:task` + `/bmb:build` | Creates BMB branch/task; no direct memory-bank writes |
| `/vc:evidence <CARD-KEY>` | Compile artifacts (PR, tests, screenshots), post `## AI Evidence` comment | Sets `AI Stage = Evidence Ready` |

Every posted comment ends with a `<!-- posted by vc plugin vX.Y.Z -->` footer so future prompt-quality changes are attributable to a specific plugin version.

## First-time setup

1. Fill in the placeholders in `.claude/plugins/vc/config.md`:
   - `cloudId` (once, via `mcp__claude_ai_Atlassian__getAccessibleAtlassianResources`)
   - `AI Stage` customfield ID
   - `AI Confidence` customfield ID
2. Verify the project-scope MCP config: `../../.mcp.json` at the repo root already declares the `atlassian` server.
3. Install the plugin locally so `/vc:*` commands are discoverable:
   ```
   claude plugin install --plugin-dir .claude/plugins/vc
   ```
   (Or add this directory as a marketplace; see Claude Code plugin docs.)

## Slug convention

`abc-1234-short-description` — lowercase, kebab-case, card key first.

The slug rides through:
- BMB branch names (`feature/<slug>` or `task/<slug>`)
- Commit messages
- PR titles
- Every Jira comment posted by `/vc:evidence`

So the card key is always traceable from any git artifact.

## Configuration source of truth

`config.md` is read at the top of **every** command. If you catch a command hardcoding a cloudId or customfield ID, that's a bug — fix it by moving the value to `config.md`.
