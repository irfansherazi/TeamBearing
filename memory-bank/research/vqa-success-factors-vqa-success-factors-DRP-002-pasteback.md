# Deep Research Pasteback — DRP-002

<!--
  Human-assist path: paste Claude.ai Deep Research output here, set Status: COMPLETE, signal proceed.
  The orchestrator normalizes this into a standard spike card (per the shared contract) before Phase 2 synthesis.
-->

**Work slug**: `vqa-success-factors`
**Artifact slug**: `vqa-success-factors`
**Probe ID**: `DRP-002`
**Run mode**: `human-pasted`
**Surface**: `claude.ai-deep-research`
**Run date**: `2026-07-16`
**Status**: `PENDING`

## Probe question

> In production LangGraph / ReAct agent systems navigating stateful SPAs, what action-budget sizes and loop-detection heuristics are used, at what firing frequency does a circuit breaker indicate the navigation strategy itself needs architectural change, and what self-correction patterns (model escalation, KB injection, deterministic fallback) have documented success rates?

## Raw Deep Research Output

<!-- Paste the full Claude.ai Deep Research report below this comment. Leave empty until the chat-product step is done. -->

## Normalized Spike Card

<!--
  Orchestrator fills this block after human pastes the raw report above.
-->

```markdown
## Spike Card: Deep Research (DRP-002)
**Work slug**: vqa-success-factors   |   **Status**: PENDING
**run_id**: 20260716-13383c61b543
**framing_sha**: 13383c61b543
**approved_depth**: deep
**approved_lanes**: Academic/SOTA, OSS/Production, Practitioner Discourse, Official Docs, Internal/Codebase
**MCP used**: N/A (chat product)
**mcp_servers_available**: none
**fallback_used**: yes
**Sources consulted**: TBD

### Findings
| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| (pending paste) | | | | |

### TRAP Candidates
(pending)

### Open Questions
(pending)
```

## Evidence notes

- **Grade cap for unsourced DR synthesis**: B at best, often C until URLs verified (shared rubric).
- **ADOPT gate unchanged**: ≥1 A-grade or ≥2 independent B-grade sources (enforced at Phase 2 synthesis).
- **Identity fields** (`run_id`/`framing_sha`/`approved_depth`/`approved_lanes`) are copied from the current run so the staging card is reuse-safe like any lane card.

## Provenance (required)

| Field | Value |
|-------|-------|
| `deep_research_probes_run` | `DRP-002` |
| `probe_approval_gate` | Phase 0 Gate #1 — approved |
| `run_mode` | `human-pasted` |
| `surface` | `claude.ai-deep-research` |
| `human_operator` | `self` |
| `agent_steps` | N/A |
