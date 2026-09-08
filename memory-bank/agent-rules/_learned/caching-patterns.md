---
name: LLM Output Caching Patterns
globs: ["backend/engine/*.py", "backend/jira/*.py"]
paths: ["backend/engine/", "backend/jira/", "storage/"]
topics: ["caching", "llm", "determinism", "content-hash", "ci-gateable"]
priority: low
auto_generated: true
evidence_count: 1
last_reinforced: 2026-07-28
source_tasks: ["vqa-tier2-planner-memory-hardening"]
derived_from: ["vqa-tier2-planner-memory-hardening"]
last_validated: 2026-07-28
---

# LLM Output Caching Patterns

Rules for building content-hash-keyed disk caches that make LLM-parsed outputs deterministic and CI-gateable. Complements `storage-layer-pattern.md` (which is about generic filesystem-backed stores). These rules are specific to caching non-deterministic LLM outputs so the same input yields the same output across runs.

## Rules

- **content-hash-key-for-llm-parsed-outputs** (`backend/engine/ac_parse_cache.py`, `backend/engine/ac_parser.py`): Use SHA-256 of the raw input text as the cache key for LLM-parsed outputs. Store each entry as a JSON file at `storage/<cache_name>/<sha256>.json`. The cache lookup is a shallow disk read (< 50ms round-trip; asserted in `test_cache_hit_under_50ms`). Same content → same key → same cached parse → byte-identical output across runs. Modified content → different key → cache miss → LLM re-parse.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **temperature-zero-on-cache-miss-paths** (`backend/engine/ac_parser.py`): On the cache-miss path (the LLM actually runs), set `temperature=0.0` explicitly — do not inherit the provider default (Bedrock and most providers default to a non-zero temperature). Temperature 0.0 is a necessary-but-not-sufficient condition for reproducibility; the content-hash cache still needs to catch the run-to-run drift that survives greedy sampling in multi-stage pipelines.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **min-max-gate-before-cache-write** (`backend/engine/ac_parser.py`): Validate parsed LLM output with a heuristic gate (e.g., `min_steps <= count <= max_steps` from ordered-list markers in the source text) BEFORE writing to the cache. This turns "the parser hallucinated 51 steps for a 17-step ticket" from a silent poisoning of the cache into a re-parse-and-retry event. The gate is the CI-gateable regression trap: if the count goes outside the gate, the CI test fails.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **layer-above-not-replacement-of-existing-cache** (`backend/engine/ac_parser.py`, `backend/jira/cache.py`): When adding a content-hash disk cache above an existing in-memory / tuple-keyed cache (e.g., `ACStepCache`), layer it — do not replace. The new cache runs first (cheap disk hit); the existing cache still handles the in-memory hot path. This preserves the in-memory tier's latency win while adding the cross-run determinism guarantee.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **best-effort-backfill-with-log-skip-no-stub** (`scripts/backfill_ac_parse_cache.py`): Backfill scripts for content-hash caches must skip un-migratable entries (e.g., raw text no longer re-fetchable) and log the skip — NEVER write a stub / empty / placeholder entry. A stub entry poisons `RecipeRegistry.match()`-like consumers by claiming coverage that doesn't exist. This is the same non-poisoning principle as trace-parse failure (see `memory-patterns.md`).
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x
