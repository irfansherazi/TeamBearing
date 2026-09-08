---
name: Performance Architecture Patterns
globs: ["backend/config.py", "backend/engine/*.py", "backend/kb/*.py"]
paths: ["backend/engine/", "backend/kb/", "backend/config.py"]
topics: ["performance", "feature-flags", "speculative-execution", "parallelism", "asyncio"]
priority: high
auto_generated: true
evidence_count: 2
last_reinforced: 2026-05-31
source_tasks: ["TASK-080"]
derived_from: []
last_validated: 2026-07-22
---


# Learned Rules: performance-architecture

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **feature-flag-first-performance** (`backend/config.py`, `backend/engine/*.py`): For any performance overhaul with multiple independent sub-features, ALL sub-features MUST be gated by independent feature flags in `config.py` from the FIRST commit. Convention: additive/safe features (compression, caching, prompt assembly) default to `true`; destructive/parallel/state-sharing features (parallel execution, Redis-backed stores) default to `false`. This enables: (1) production A/B measurement of individual features, (2) instant feature-level rollback without a full revert, (3) independent metric collection per feature. Never merge a performance sub-feature without its own `ENABLE_*` env var. Established by FEAT-060's 12 feature flags (`model_router_enabled`, `prompt_compression_enabled`, `parallel_tickets_enabled`, etc.).
  - _Source_: reflection-TASK-080 (2026-05-31)
  - _Reinforced_: 0x

- **speculative-execution-poison-signal** (`backend/engine/speculative_planner.py`, `backend/kb/prefetcher.py`): Any speculative pre-computation (plan generation, KB pre-fetch, action preparation) MUST implement an explicit poison-signal discard path invoked when the current action fails. Pattern: `if action_result.failed: speculative_cache.discard()`. Without explicit discard, stale speculative state bleeds into the next execution cycle — the next step's plan or context is based on a page state that no longer exists. The discard path must be unconditional (not gated by the speculative feature flag) so that disabling speculation does not leave orphaned cache entries. `SpeculativePlanner.discard_if_poisoned()` and `KBPrefetcher.invalidate_on_failure()` are the reference implementations.
  - _Source_: reflection-TASK-080 (2026-05-31)
  - _Reinforced_: 0x

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Feature-flag-first for performance architecture | [TASK-080.md](../tasks/TASK-080.md) | 2026-05-31 |
| Speculative execution poison-signal discard | [TASK-080.md](../tasks/TASK-080.md) | 2026-05-31 |
