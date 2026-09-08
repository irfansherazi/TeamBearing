---
name: HITL Memory & Trace-to-Recipe Patterns
globs: ["backend/engine/*.py"]
paths: ["backend/engine/"]
topics: ["memory", "hitl", "playwright-trace", "recipe", "amnesia", "replay"]
priority: low
auto_generated: true
evidence_count: 1
last_reinforced: 2026-07-28
source_tasks: ["vqa-tier2-planner-memory-hardening"]
derived_from: ["vqa-tier2-planner-memory-hardening"]
last_validated: 2026-07-28
---

# HITL Memory & Trace-to-Recipe Patterns

Rules for converting human-in-the-loop takeovers into replayable memory so that every HITL becomes a permanent Recipe, not a one-shot rescue. Derived from FEAT-117 T2-b, which replaced the amnesic JS click-capture listener with a full Playwright tracing session.

## Rules

- **synchronous-trace-parse-in-source-node** (`backend/engine/hitl_trace_parser.py`, `backend/engine/human_takeover.py`): Parse HITL Playwright traces synchronously inside the node that produced them — never in a background asyncio task, external filesystem-watcher, or admin API. Synchronous parse guarantees the Recipe is registered before the next planner turn observes state (happens-before guarantee needed for auto-replay tests). The 500–1500ms parse latency is imperceptible because it happens after the operator clicks "Done" and is amortized as agent latency, not user-visible latency.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **result-dataclass-never-raise-at-node-boundary** (`backend/engine/hitl_trace_parser.py`): Trace parsers invoked synchronously inside a LangGraph node MUST return a result dataclass (e.g., `TraceParserResult(ok: bool, recipe: Optional[Recipe], reason: Optional[str])`) — never raise. A raised exception at the node boundary corrupts LangGraph node state and takes the whole run down. The result-dataclass pattern lets the node inspect `.ok` and route to either "recipe registered" or "trace-parse-failed diagnostic" without disrupting the graph.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **preserve-artifact-on-parse-failure** (`backend/engine/human_takeover.py`, `backend/engine/hitl_trace_parser.py`): When a trace-to-Recipe parse fails, preserve the source `.zip` on disk (NOT deleted), emit a WARN log with `hitl_trace_parse_failed: run_id=... reason=...`, continue the run (parse failure is non-fatal), and NEVER write a stub/empty Recipe file to the KB (non-poisoning principle — a broken recipe would poison future `RecipeRegistry.match()` calls). Post-mortem is always possible because the artifact is retained.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **playwright-trace-schema-version-pinning** (`backend/engine/hitl_trace_parser.py`): When parsing Playwright's internal `trace.trace` NDJSON directly (via `zipfile` + `json.loads`) instead of using `playwright show-trace` tooling, pin the Playwright version (e.g., `playwright==1.49.*`) and commit a real-session fixture `.zip` (`hitl_trace_sample.zip`) that exercises the parser. Every Playwright upgrade must re-run the fixture-based parse test to detect schema drift before the upgrade lands.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x

- **auto-recipe-trigger-phrase-synthesis** (`backend/engine/hitl_trace_parser.py`, `backend/engine/recipe_runner.py`): Auto-generated recipes need `trigger_phrases` synthesized from the AC-step goal at the point of takeover (plus optional DOM text hints from the trace), not the human-curated hand-authored phrases used elsewhere. This preserves the existing `RecipeRegistry.match()` token-Jaccard semantics without requiring human curation before the recipe becomes matchable.
  - _Source_: reflection-vqa-tier2-planner-memory-hardening (2026-07-28)
  - _Reinforced_: 1x
