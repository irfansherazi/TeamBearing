---
name: Prompt Budget & Eviction Priority
globs: ["backend/engine/prompt_budget.py", "backend/engine/planner.py"]
paths: ["backend/engine/"]
topics: ["prompt-budget", "eviction", "planner", "context-preservation"]
priority: low
auto_generated: true
evidence_count: 1
last_reinforced: 2026-07-28
source_tasks: ["vqa-tier2-planner-memory-hardening"]
derived_from: ["vqa-tier2-planner-memory-hardening"]
last_validated: 2026-07-28
---

# Prompt Budget & Eviction Priority

Rules for constraining what a PromptBudget drops when it must trim to fit under `max_tokens`. Complements `context-budget.md` (which is about reference-not-copy for large artifacts). These rules govern the eviction ordering itself — which sections are protected and which are trimmed first.

## Rules

- **evictable-field-on-prompt-sections** (`backend/engine/prompt_budget.py`): Add an `evictable: bool = True` field to `PromptSection` (default `True` for backward compatibility — existing callers stay evictable unless they opt-in). When over-budget, `PromptBudget.assemble()` must never drop sections with `evictable=False`. This shields load-bearing sections from a naive tier-priority drop that would otherwise remove the planner's reasoning framework precisely when it needs it most (retry loops with a swollen failure diary).
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **protect-reasoning-workflow-and-current-task** (`backend/engine/planner.py`): At the `.add()` call sites in `planner.py`, mark these sections `evictable=False`: `reasoning_workflow` (the planner's thinking framework, slot 50), `current_task` / `current_ac_step` (slot 4), `interactive_elements` (RAG-tier — the planner cannot plan without seeing what's on the page), and `selector_hints` / `skill_hints` (targeted retrieval). Everything else — `failure_diary`, `global_run_context`, ambient history — remains evictable.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **named-eviction-first-list-for-drop-order** (`backend/engine/prompt_budget.py`): Enforce a named `EVICTION_FIRST_NAMES` constant (e.g., `["failure_diary", "global_run_context"]`) that `assemble()` consults BEFORE the standard tier-priority drop order. The failure diary is trimmed first among evictable candidates because retry noise carries the least marginal value per token. This makes the drop order legible in one place and easy to extend without touching the assembly hot path.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **prompt-budget-fixture-based-assertions** (`backend/engine/test_prompt_budget.py`): Test the over-budget path with a fixture scenario that populates all protected sections + at least two evictable sections that together exceed `max_tokens`. Assert (a) no protected section appears in `dropped_names`; (b) `failure_diary` appears in `dropped_names` before any other evictable section. Backward-compat: also assert `PromptSection(...)` returns `evictable=True` by default.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x
