---
name: vc plugin config
purpose: Shared constants read at the top of every /vc:* command. Single source of truth so cloudId, custom-field IDs, and stage labels aren't duplicated across prompts.
---

# vc Plugin Config

Every `/vc:*` command reads this file **first**, before making any Jira call.
Update values here — never inline them in individual command prompts.

## Atlassian

- **cloudId**: `25b35a1e-0984-4453-88df-b99a19d5eb92`
  - Site: `vcreative.atlassian.net`
  - Passed explicitly on every `mcp__claude_ai_Atlassian__*` call. Tokens are not cloudId-bound.
  - Find via `mcp__claude_ai_Atlassian__getAccessibleAtlassianResources` once, then paste here.

## Jira custom fields

Resolve these customfield IDs once (via `getJiraIssueTypeMetaWithFields` on a sample card) and record them here. Commands reference them by the human name below; the model maps to the ID at call time.

- **AI Stage** → `customfield_10653`
  - Allowed values: `Groomed`, `Diagnosed`, `Fixing`, `Evidence Ready`
- **AI Confidence** → `customfield_10655`
  - Jira field name: `Confidence` (single-select). Assumed to be the AI Confidence field — please confirm on first use.
  - Scale: `Low` | `Medium` | `High`

## Slug convention

`abc-1234-short-description` — lowercase, kebab-case, card key as prefix.

Rules:
- Card key is lowercased with the hyphen preserved: `VC2-8990` → `vc2-8990`.
- Short description: 2–5 words, kebab-cased, no filler words.
- The slug rides through everything downstream: BMB branch name (`feature/<slug>` or `task/<slug>`), commit messages, PR title.

## Plugin version stamp

Every structured comment posted to Jira ends with a footer:

```
<!-- posted by vc plugin v{{PLUGIN_VERSION}} -->
```

Read `{{PLUGIN_VERSION}}` from `.claude/plugins/vc/.claude-plugin/plugin.json` `.version` at comment-composition time. Never hardcode.
