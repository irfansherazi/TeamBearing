# Architecture Decision: vQA Tier 3 — Architectural Hardening (Isolation, Registry, Reflex, Determinism)

**Created**: 2026-07-29
**Status**: DECIDED
**Decision Type**: Architecture
**Complexity**: Level 4
**Feature**: FEAT-118-vqa-tier3-architectural-hardening

---

## Decision Summary Table

| CQ ID  | Decision                                                                                                                        | Confidence | Impact on Build Phase                                                                                                |
| ------ | ------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| CQ-A1  | **Reject-at-startup** (fail-fast in `load_product_registry()`) with a supplementary `POST /execute` guard for hot-reload safety | HIGH       | Phase 1 (T3-a) adds `validate_product_kb_roots()` to `product_registry.py`; startup exits non-zero on missing roots  |
| CQ-A2  | **Newly introduced structured log tag `ac_negotiator_complaint`** with a first-class `complaints_by_product` state counter      | HIGH       | Phase 1 introduces `ComplaintCounter` in `ac_enricher.py`; reporter surfaces per-product totals                      |
| CQ-A3  | **Subdirectory partition** (`knowledge/<product>/*.md`) — already partially adopted; codify + backfill                          | HIGH       | Phase 1 moves the last flat files into `knowledge/vpromedia/`; `kb/loader.py` walks per-product roots                |
| CQ-B1  | **Hybrid: (a) single pre-emit gate in `_build_action()` + (c) LLM-prompt-time registry hits injection**                         | HIGH       | Phase 2 adds `RegistryFirstGate` in planner.py; prompt-side injection reuses existing selector_rag machinery         |
| CQ-B2  | **Structured log event** on the existing WS `execution_log` channel with `event_type=registry_enrichment_needed`                | HIGH       | Phase 2 emits via existing `logger.info(..., extra={...})`; no frontend work                                         |
| CQ-B3  | **`(ticket_key, ac_step_text, target_semantic_name, playwright_locator)` tuple in `knowledge/selector_registry.json`**          | HIGH       | Phase 2 pre-work: `scripts/extract_seed_selectors.py` mines top-10 recent failing tickets + QA-358                   |
| CQ-C1  | **Hybrid: YAML catalog for signatures + Python dispatch table for handler functions** (lookup-table shape, no state machine)    | HIGH       | Phase 3 introduces `backend/engine/reflex/catalog.yaml` + `reflex.py` dispatcher — **Algorithm creative NOT REQUIRED** |
| CQ-C2  | **(b) reflex.py sits BEFORE recovery_router in retry path** — reflex handles NEW signatures; recovery_router unchanged          | HIGH       | Phase 3 wires reflex → recovery_router → planner chain in evaluator.py; no changes to FEAT-022 code paths            |
| CQ-C3  | **`evaluator.py` at line 655** — before `new_retry_count` bump, symmetric with existing `attempt_recovery()` call site          | HIGH       | Phase 3 inserts `reflex.attempt_short_circuit()` call ~evaluator.py:653; executor.py untouched                       |
| CQ-C4  | **`storage/replay/2026-07-27/` directory of `.jsonl` execution traces + `scripts/replay_reflex_benchmark.py`**                  | MEDIUM     | Phase 3 pre-work: capture traces from existing 5 sessions; replay harness is deterministic (no browser, no Bedrock)  |
| CQ-D1  | **Fresh-capture script `scripts/populate_ac_parse_baseline.py`** — content_hash keyed but tracked in `_manifest.json`           | HIGH       | Phase 4 script runs once; baseline JSON = `{ticket_key, content_hash, step_count, captured_at}`; manifest is index   |
| CQ-D2  | **Fail-fast for tracked tickets + WARN + record for un-tracked** — startup check only validates manifest integrity              | HIGH       | Phase 4 adds baseline-lookup in ac_parser.py:~550 post-Stage-2; drift > ±2 raises `ACParseDriftError`                |
| CQ-D3  | **(c) Enumerate every file in `storage/ac_parse_baseline/*.json`** — no manifest coupling in CI YAML                            | HIGH       | Phase 4 workflow uses `jq -r '.ticket_key'` over the JSON files; adding a baseline auto-onboards to CI               |

---

## Context

### System Requirements

- **R1** Every LLM prompt (planner, verifier, ac_parser) must be scoped to a **single active product's** persona list, KB workflows, and selector registry. Cross-product term bleed (e.g., a vPromotions run receiving vProMedia's "Production Orders" KB) must be architecturally impossible, not merely discouraged.
- **R2** The planner must consult `knowledge/selector_registry.json` **BEFORE** any `get_by_text` fallback path is taken. Every miss must be observable so registry coverage grows monotonically.
- **R3** A hard-coded reflex layer must short-circuit deterministic failure signatures (e.g., `RETURN_TO_LIST_AFTER_ORDER_DETAIL`, `PRIMENG_DROPDOWN_OVERLAY_MISS_ON_FIRST_CLICK`, `TABLE_ROW_STRICT_MODE_VIOLATION`, `LOGGED_IN_AS_WRONG_ROLE`) **BEFORE** any Bedrock retry is invoked.
- **R4** AC parsing must be asserted against a per-ticket baseline; drift > ±2 steps must fail the run with a stable `failure_type="AC_PARSE_DRIFT"`.
- **R5** No new UI components. All new telemetry piggybacks on the existing WS `execution_log` channel and reporter HTML.
- **R6** FEAT-022's `recovery_router` pipeline must remain byte-identical; T3-c can only extend, never replace.

### Technical Constraints

- The planner is a 5,460-line file with 7+ known `get_by_text` fallback sites (planner.py:432, 448, 469, 515, 571, 608, 663). Repointing each site independently is a refactoring hazard; single-point-of-control is preferred.
- `products.yaml` (`schema_version: 1`) is already the source of truth for product-slug → roles/environments/tests_dir mapping. T3-a extends the schema (adds required per-product KB/selector roots) rather than introducing a parallel registry.
- `backend/kb/loader.py:181` currently does `_KB_DIR.glob("*.md")` — flat scan, no product filter. `KBWorkflow.product` already exists (loader.py:192) but the loader itself does not partition the walk.
- `backend/engine/recovery_router.py` handles exactly 5 signatures (STRICT_MODE, TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED) via classification-then-dispatch. Its architecture is proven; the new reflex layer must be **compositional**, not disruptive.
- The 5-session 2026-07-27 baseline was captured by observation, not by an artifact — the "5 sessions" are ephemeral log lines in production log tails. Design must acknowledge this and prescribe how to capture equivalents for replay.
- T2-a's `storage/ac_parse_cache/` is content-hash keyed (visible in the two files under it: `7c98fe48…json`, `ee0e6dd6…json`). Reusing this as a baseline is a category error: cache is `hash → parse_result`; baseline needs `ticket_key → expected_step_count`.

### Non-Functional Requirements

- **NFR-1 Startup-time validation** — T3-a's product registry validation must complete in < 500ms and must fail fast on any structural problem (missing KB root, missing persona directory, missing selector registry). Partial-load state is forbidden.
- **NFR-2 Zero-silent-fallback** — no code path may quietly substitute a default. Every fallback must be either (a) explicit and telemetried, or (b) removed.
- **NFR-3 First-hit correctness** — QA-358's "Select Contest from PRF Category dropdown" must succeed on iteration 1 given a seeded registry entry (AC-INTEGRATION-2).
- **NFR-4 Observability of every deterministic decision** — every reflex hit, every registry miss, every drift check, every product-KB lookup must emit a structured event that shows up in the reporter.
- **NFR-5 Cost** — target ≥40% reduction in Bedrock InvokeModel calls in the retry path (AC-INTEGRATION-3).
- **NFR-6 Locality of reasoning** — a future engineer must be able to reason about a single sub-tier by reading ≤2 files. Cross-cutting concerns must have a named seam.

### Guiding Principles Compliance

This design respects and **strengthens** the guiding principles in `systemPatterns.md`:

- **Semantic Locators First** — T3-b enforces this at the code level rather than at the prompt level.
- **Failure Diary Pattern** — T3-c's reflex hits are recorded in `recovery_log` (compatible with existing failure diary).
- **Programmatic Tier 1 Verification** — T3-c is a programmatic tier that sits BEFORE the LLM retry path, extending this principle to the recovery pipeline.
- **12-Factor App** — Reflex catalog YAML lives under `backend/engine/reflex/catalog.yaml` (not `.env`), but the enable-flag lives in env (`REFLEX_LAYER_ENABLED`, default `true`).

**No deviations required.**

---

## Component Analysis

### Core Components

| Component                            | Purpose                                                                                              | Responsibilities                                                                                                                                                                                    |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ProductRegistry** (existing)       | Single source of truth for product slug → config                                                     | (extended) Validate `personas_dir`, `knowledge_dir`, `selector_registry_dir`, `test_matcher_dir` at startup; raise `ProductKBMissingError` on any gap                                               |
| **ProductKBValidator** (new)         | Startup-time gate for T3-a                                                                           | Enumerate every product in `products.yaml`; for each, assert per-product roots exist and are non-empty; emit exit-code 1 on failure                                                                 |
| **LocalKnowledgeBase** (existing)    | KB workflow loader (loader.py)                                                                       | (modified) Walk per-product roots when `product` is passed; refuse to load global-neutral files for a product query if a product-specific version exists                                            |
| **ComplaintCounter** (new)           | Observable signal for AC-INTEGRATION-1                                                               | In `ac_enricher.py`, tag every AC-negotiator complaint with `product_slug`; expose `state["complaints_by_product"]` and emit `ac_negotiator_complaint` log tag                                      |
| **RegistryFirstGate** (new)          | Mandatory registry lookup gate for T3-b                                                              | In planner.py's `_build_action()`, before any `get_by_text` emission, look up `(active_product, ac_step_text)` in `selector_registry`; on hit → force `get_by_role`/`vqa_id`; on miss → emit event  |
| **ReflexLayer** (new)                | Hard-coded catalog of signature → recovery for T3-c                                                  | Load YAML catalog at module load; expose `attempt_short_circuit(state, error_msg, planned_action) -> ReflexResult \| None`; runs BEFORE `recovery_router.attempt_recovery`                          |
| **RecoveryRouter** (existing)        | FEAT-022 typed-failure recovery                                                                      | Unchanged. Handlers for STRICT_MODE / TIMEOUT / NOT_VISIBLE / DETACHED / INTERCEPTED remain the second link in the retry chain                                                                      |
| **ACParseBaselineStore** (new)       | Per-ticket baseline persistence for T3-d                                                             | Read/write `storage/ac_parse_baseline/<ticket_key>.json`; maintain `_manifest.json` (registry of tracked tickets); expose `assert_drift(ticket_key, current_step_count, raw_ac_text)`               |
| **ACParseDriftGuard** (new)          | Fail-fast drift assertion for T3-d                                                                   | Injected into `ac_parser.py` at Stage-2 completion (~line 550); on drift > ±2, raise `ACParseDriftError` → reporter emits terminal `failed` with `failure_type="AC_PARSE_DRIFT"`                    |
| **RegistryMissEmitter** (new)        | Async structured-log emission for T3-b's telemetry                                                   | Emits `event_type=registry_enrichment_needed` on existing WS channel; no dashboard changes, no queue write                                                                                          |

### Component Interactions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STARTUP (uvicorn boot)                              │
│                                                                              │
│   load_product_registry()                                                    │
│      └─▶ ProductKBValidator.validate_all()  ◀── T3-a fail-fast              │
│              │                                                               │
│              ├─▶ for each product: assert personas_dir exists                │
│              ├─▶ for each product: assert knowledge/<slug>/ non-empty        │
│              └─▶ on any miss: exit(1) with ProductKBMissingError             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          REQUEST (POST /execute)                             │
│                                                                              │
│   ExecuteRequest.validate_role_product_match  (existing)                    │
│      └─▶ product_kb_available(product_slug)   ◀── T3-a hot-reload guard     │
│              └─▶ 4xx { "code": "product_kb_missing" } BEFORE browser launch │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          AC PARSING                                          │
│                                                                              │
│   ac_parser_node                                                             │
│     ├─▶ Stage 1 BDD normalization                                            │
│     ├─▶ Stage 2 JSON compile                                                 │
│     ├─▶ [existing T2-a heuristic warn gate]                                  │
│     ├─▶ ACParseDriftGuard.assert_drift()     ◀── T3-d fail-fast             │
│     │       │                                                                │
│     │       └─▶ if |current - baseline| > 2  → raise ACParseDriftError      │
│     └─▶ ac_enricher.enrich()                                                 │
│             └─▶ ComplaintCounter.record()    ◀── T3-a observable signal    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          PLANNING (planner_node)                             │
│                                                                              │
│   _build_action()                                                            │
│      ├─▶ RegistryFirstGate.check()          ◀── T3-b pre-emit gate         │
│      │       ├─▶ hit  → forced strategy = get_by_role / vqa_id             │
│      │       └─▶ miss → emit `registry_enrichment_needed` + continue        │
│      │                                                                       │
│      └─▶ LLM planner call                                                    │
│            └─▶ (prompt already contains registry-hits list — CQ-B1 hybrid)  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          RECOVERY (evaluator_node)                           │
│                                                                              │
│   evaluator.py:~653                                                          │
│      ├─▶ ReflexLayer.attempt_short_circuit()  ◀── T3-c NEW, first          │
│      │       ├─▶ hit  → return ReflexResult (skip Bedrock retry)            │
│      │       └─▶ miss → fall through                                         │
│      │                                                                       │
│      ├─▶ recovery_router.attempt_recovery()   ◀── FEAT-022 unchanged        │
│      │       ├─▶ hit  → RecoveryResult (STRICT_MODE etc.)                   │
│      │       └─▶ miss → fall through                                         │
│      │                                                                       │
│      └─▶ new_retry_count = retry_count + 1   → planner_node                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## T3-a — First-Class Product Isolation

### CQ-A1 Decision: Reject-at-startup (fail-fast) with a supplementary POST /execute guard

**Options explored:**

1. **Reject-at-startup** (fail-fast in `load_product_registry()`) — process exits with code 1 on any missing KB root.
2. **Reject-at-first-request** (`POST /execute` returns 4xx) — server keeps running; only the affected product fails.
3. **Reject-at-first-KB-hit** (lazy) — `kb.query()` raises on demand.

**Chosen: Option 1 + Option 2 layered.** Startup validation is the primary gate; the `POST /execute` guard is a defense-in-depth against products.yaml hot-reloads (which the codebase already supports via `_load_product_registry_cached()`).

**Rationale:**
- NFR-1 mandates startup-time validation. Silent lazy binding contradicts the "zero-silent-fallback" invariant. Reject-at-startup surfaces configuration bugs at deploy time, before any user is impacted.
- Lazy binding (Option 3) is the current behavior — this is exactly what we're eliminating. It's how a vPromotions run silently fell back to vProMedia terminology.
- Option 2 alone is insufficient: it lets the server boot in a broken state, which fails the "healthy service" contract for load balancers and container orchestrators.
- The layered approach costs one extra ~30ms KB-root probe at every `POST /execute` — negligible; it catches the case where an operator swaps `products.yaml` at runtime.

**Trade-off:** A missing KB directory for a stub product (e.g., `psn`, `vep` currently have zero roles) will now block startup. Mitigation: the validator treats a product with `roles: []` as **exempt from KB completeness** (they cannot run anyway) but still validates that `personas_dir` and `knowledge_dir` paths in `products.yaml` are syntactically well-formed. This preserves the "add a stub product without a KB" workflow while still enforcing completeness where it matters.

### CQ-A2 Decision: Newly introduced structured log tag `ac_negotiator_complaint` + state counter

**Options explored:**

1. Reuse an existing log tag — grep of `ac_enricher.py` shows no stable, machine-parseable tag today; complaints are emitted via `logger.warning(...)` with unstructured messages.
2. Add a state counter only (`state["complaint_count_by_product"]`) — measurable at report time but invisible during a run.
3. **Newly introduced structured log event `ac_negotiator_complaint` + first-class state counter** — dual surface.

**Chosen: Option 3.**

**Rationale:**
- NFR-4 requires **observability of every deterministic decision**. A grep-friendly log tag lets the CI benchmark script tail structured events; the state counter lets the reporter render "23 complaints in vpromedia, 2 in vpromotions" as a headline metric.
- The signal must be pinnable **before build starts** (per CQ-A2 requirement). Introducing a new tag is unambiguous — a reused-but-inconsistent existing tag is not.
- Emission site: every existing `logger.warning(...)` complaint call in `ac_enricher.py` gains an `extra={"event_type": "ac_negotiator_complaint", "product": product_slug, "phrase": complaint_phrase}` kwarg; the `ComplaintCounter` context manager wraps `enrich()` and increments per-run state.

**Baseline definition for AC-INTEGRATION-1:** capture `main@1a7e818` complaint volume for the curated 10-ticket vpromotions sample using a one-shot instrumentation branch (adds the tag without adding the counter). The post-implementation delta measurement uses the same tag.

### CQ-A3 Decision: Subdirectory partition (`knowledge/<product>/*.md`)

**Options explored:**

1. Flat filename convention (`vpromotions-workflows.md`, `vpromedia-workflows.md`) — glob remains `_KB_DIR.glob("*.md")`; product inferred from prefix.
2. **Subdirectory partition (`knowledge/vpromedia/*.md`, `knowledge/vpromotions/*.md`)** — glob becomes `_KB_DIR.glob("<product>/*.md")` + `_KB_DIR.glob("*.md")` for global-neutral files (e.g., `angular_timing_contracts.md`).
3. Hybrid — flat with YAML frontmatter declaring `product: vpromotions`.

**Chosen: Option 2** — already partially adopted in the repo (`knowledge/vpromedia/`, `knowledge/vpromotions/` directories exist per the `ls`; some legacy flat files remain).

**Rationale:**
- Discovery is O(1) filesystem lookup: "give me vpromotions KB" = walk one directory. No parse-frontmatter cost, no filename-prefix ambiguity.
- `LocalKnowledgeBase.KBWorkflow.product` already exists (loader.py:192) — the loader just needs to walk product subdirs and set the field from the parent directory name.
- Directory-level file operations (git mv, cp, chmod) are trivial. Filename-prefix schemes are error-prone when adding a new product.
- Files at the KB root (e.g., `angular_timing_contracts.md`, `api_contracts.md`) are treated as "global-neutral" (product=None) and included in every product's query — behavior already coded and tested per systemPatterns.md's Product Registry Pattern section.

**Trade-off:** Requires a one-time migration commit moving remaining flat files (grep confirms: `human_guidance.md`, `vSuite-actions.md.bak`, `dropdown_registry.json`, `unified_components.json`, `ui_paradigms.md`) to appropriate subdirectories or keeping them at root as global-neutral. Mitigation: Phase 1 first commit is `chore: migrate flat KB files to per-product subdirs` — pure `git mv`, zero logic change.

---

## T3-b — Selector-Registry-First Planner

### CQ-B1 Decision: Hybrid — single pre-emit gate in `_build_action()` + LLM-prompt-time registry-hits injection

**Options explored:**

1. **(a) Single pre-emit gate in `_build_action()`** — one code site checks `selector_registry` for the AC step's target semantic name before any strategy is emitted; a hit forces `get_by_role`/`vqa_id`; a miss falls through to the LLM.
2. **(b) Inline registry checks at each `get_by_text` fallback site** — planner.py:432, 448, 469, 515, 571, 608, 663 each grow a `_check_registry(...)` guard.
3. **(c) LLM-facing prompt-time injection** — assemble a "registry hits for this AC step" block in the planner system prompt and forbid `get_by_text` for any target with a hit.

**Chosen: Hybrid (a) + (c).**

**Rationale:**
- Option (b) fails NFR-6 (locality of reasoning): 7 injection sites means every future fallback addition risks silently bypassing the registry. Every past reliability bug on this planner was caused by exactly this class of "missed one site" error.
- Option (a) alone gives us a single seam and single test surface, but it fires **after** the LLM has already emitted the plan. A registry hit could still result in a wasted LLM call.
- Option (c) alone gives us early steering but no hard guarantee — the LLM could ignore the hint under prompt pressure.
- **The hybrid**: `RegistryFirstGate.check()` in `_build_action()` is the authoritative enforcement point (turns any `get_by_text` for a registered target into `get_by_role`/`vqa_id` deterministically). `RegistryFirstGate.build_prompt_block()` produces a small `<registry_hits>` block injected into the system prompt so the LLM makes the right choice on the first pass, saving tokens on retries.
- Prompt injection reuses the existing `_SEL_REG_CACHE` at planner.py:188 — the machinery already exists.
- The "5,460-line planner" concern is addressed: the gate is one function, ~50 lines, with a single call site at `_build_action()` entry.

**Implementation sketch:**

```python
# backend/engine/registry_first_gate.py (NEW)
class RegistryFirstGate:
    @staticmethod
    def check(planned_action: dict, ac_step_text: str, product_slug: str) -> dict:
        """
        Returns the possibly-rewritten action. Emits registry_miss event on miss.
        Idempotent, side-effect-free apart from telemetry.
        """
        target_name = planned_action.get("name") or _infer_target_from_step(ac_step_text)
        hit = selector_registry.lookup(product_slug, ac_step_text, target_name)
        if hit:
            planned_action["strategy"] = hit["playwright_strategy"]  # e.g. "get_by_role"
            planned_action["role"] = hit.get("role")
            planned_action["name"] = hit.get("name", target_name)
            planned_action["_registry_hit"] = True
            return planned_action
        _emit_registry_miss(product_slug, ac_step_text, target_name)
        return planned_action

# planner.py — single call site at _build_action() start
action = RegistryFirstGate.check(action, ac_step_text, active_product_slug)
```

### CQ-B2 Decision: Structured log event on existing WS `execution_log` channel

**Options explored:**

1. Sync emission to a new dashboard widget — requires frontend work; violates the "no new UI" constraint.
2. Async queue write to `storage/registry_misses/` — durable but invisible during a run.
3. **Structured log event `event_type=registry_enrichment_needed` on the existing WS `execution_log` channel** — visible in real time, appears in the HTML report, no new UI.

**Chosen: Option 3.**

**Rationale:**
- The "no new UI" constraint is explicit. The dashboard already renders WS `execution_log` entries with rich formatting; a new event_type is a filter on the same stream.
- The reporter already surfaces log events by tag; existing infra renders `event_type=…` groups.
- If durable analysis is later needed, a log-to-storage sink can be added without changing emission-site code.

**Event schema:**
```json
{
  "event_type": "registry_enrichment_needed",
  "product": "vpromotions",
  "ac_step_text": "Select Contest from PRF Category dropdown",
  "inferred_target": "PRF Category",
  "run_id": "…",
  "ac_step_index": 3,
  "timestamp": "2026-07-29T…Z"
}
```

### CQ-B3 Decision: `(ticket_key, ac_step_text, target_semantic_name, playwright_locator)` tuple in `knowledge/selector_registry.json`

**Seed extraction methodology (Phase-0 checkpoint):**

Register a Phase 2 pre-work script `scripts/extract_seed_selectors.py` that:

1. Pins seed baseline: QA-358 (`select Contest from PRF Category dropdown`) → `page.get_by_role("option", { name: "Contest" }).first()` with `vqa_id="prf-category-contest-option"` when available.
2. Enumerates the top 10 most recent failing tickets by grepping `storage/qa/` and `storage/test/` for `verifier_verdict=failed` + `failure_type=STRICT_MODE|TIMEOUT|NOT_VISIBLE`.
3. For each ticket, extracts `(ticket_key, ac_step_text, target_semantic_name)` from the run's audit log.
4. For each row, the operator (or, in the follow-up, a semi-automated tool) fills in `playwright_locator` by hand or by scraping a passing run of the same step.
5. The output is a diff-able JSON patch to `knowledge/selector_registry.json`.

**Schema entry (nested under product key):**

```json
{
  "vpromotions": {
    "prf_category_dropdown_contest_option": {
      "ticket_seed": "QA-358",
      "ac_step_patterns": [
        "Select Contest from PRF Category dropdown",
        "Choose Contest.*PRF Category"
      ],
      "target_semantic_name": "PRF Category → Contest",
      "playwright_strategy": "get_by_role",
      "role": "option",
      "name": "Contest",
      "vqa_id": "prf-category-contest-option",
      "protected": true,
      "seed_source": "T3-b/QA-358",
      "captured_at": "2026-07-29"
    }
  }
}
```

**Rationale:**
- The tuple grounds each entry in a real ticket, making regressions traceable.
- Nesting under product slug preserves T3-a's isolation invariant (`selector_registry.lookup(product_slug, …)` never returns cross-product entries).
- `protected: true` reuses the existing merge-and-protect ingestion pattern (systemPatterns.md), preventing later automated selector-sync from overwriting hand-optimized seeds.

---

## T3-c — Reflex Layer

### CQ-C1 Decision: Hybrid — YAML catalog for signatures + Python dispatch table for handlers

**Options explored:**

1. **Pure YAML catalog** (aligned with `knowledge/blueprints/*.yaml`) — declarative, editable without code changes.
2. **Pure Python dispatch table** — every reflex signature is a Python function in `reflex.py`.
3. **Hybrid** — YAML declares signature-matching patterns and metadata; Python provides the actual recovery-action factories (referenced by name from YAML).
4. **State machine** — reflex signatures compose into a finite-state model of the retry path.

**Chosen: Option 3 (hybrid). This is a lookup table with delegated handlers, NOT a state machine.**

**Rationale:**
- Option 4 (state machine) is over-engineered: reflex is a *stateless* signature → action mapping, one entry per invocation. There is no state to model. **Algorithm creative is therefore NOT required.**
- Option 1 (pure YAML) is expressive for signature regexes but forces action-generation to also live in YAML strings — brittle, no type-checking, hard to test.
- Option 2 (pure Python) buries the failure-signature-to-signature mapping in code, making it hard to review by non-Python operators (QA leads should be able to add a new signature).
- Option 3 hits the sweet spot: signature patterns and recovery metadata are declarative (reviewable by anyone reading YAML), while the actual recovery-action factory functions are typed Python (unit-testable). This matches the existing `knowledge/blueprints/*.yaml` conventions.

**Catalog schema:**

```yaml
# backend/engine/reflex/catalog.yaml
schema_version: 1
signatures:

  - id: primeng_dropdown_overlay_miss
    match:
      any_of:
        - error_regex: "strict mode violation.*p-dropdown"
        - error_regex: "timeout.*p-select-overlay.*not visible"
      preconditions:
        prev_action_type: click
        prev_target_selector_regex: "p-select|p-dropdown"
    action:
      factory: press_escape_then_reopen
      params:
        wait_ms: 200

  - id: table_row_strict_mode_by_status_badge
    match:
      any_of:
        - error_regex: "strict mode violation.*status.*(Needs Producing|Needs Writing)"
      preconditions:
        page_state_contains: "p-table"
    action:
      factory: rewrite_to_row_client_name_click
      params: {}

  - id: logged_in_as_wrong_role
    match:
      any_of:
        - error_regex: "expected role.*got.*username.*mismatch"
      preconditions:
        state_field: authenticated_as
        state_field_ne: state.required_role
    action:
      factory: force_logout_then_relogin
      params: {}

  - id: return_to_list_after_order_detail
    match:
      any_of:
        - ac_step_regex: "^Return to (production orders|list|dashboard)"
        - error_regex: "timeout.*(Back to List|home)"
    action:
      factory: click_breadcrumb_or_back
      params: {}
```

```python
# backend/engine/reflex/factories.py
FACTORY_REGISTRY: dict[str, Callable[..., ReflexResult]] = {
    "press_escape_then_reopen": _press_escape_then_reopen,
    "rewrite_to_row_client_name_click": _rewrite_to_row_click,
    "force_logout_then_relogin": _force_logout_relogin,
    "click_breadcrumb_or_back": _click_breadcrumb,
}
```

**Trade-off:** Two files (YAML + Python) instead of one. Mitigation: they live in the same subpackage (`backend/engine/reflex/`), with a README pointing operators to the YAML for signature editing and to `factories.py` for adding new handler types.

### CQ-C2 Decision: (b) reflex.py sits BEFORE recovery_router in retry path

**Options explored:**

1. **(a)** reflex.py subsumes recovery_router — breaking change; violates R6.
2. **(b) reflex.py sits BEFORE recovery_router** — reflex fires first; on miss, recovery_router runs unchanged.
3. **(c)** reflex.py handles ONLY the four non-overlapping signatures — but "non-overlapping" is fuzzy; a p-dropdown miss can match both `INTERCEPTED` (recovery_router) and `primeng_dropdown_overlay_miss` (reflex).

**Chosen: Option (b).**

**Rationale:**
- R6 is a hard constraint. Option (a) is off the table.
- Option (c) requires classifying every signature as "reflex vs. recovery_router" territory — that classification is itself a design decision that could shift over time. Better to give reflex first-pick and let recovery_router act as a proven backstop.
- With reflex first, the AC-INTEGRATION-3 target (≥40% short-circuit rate) is achievable independent of recovery_router's classifier quality — reflex catches the deterministic subset before recovery_router's more general classifier even runs.
- Recovery_router's five signatures (STRICT_MODE, TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED) are broad classifications; reflex signatures are narrower and more specific. Broad-classification → specific-handler is a well-known failure pattern (over-triggering). Specific-first → broad-fallback is safer.

**Wiring:**

```python
# evaluator.py:~653 (INSERT before existing recovery_router call)
reflex_result = ReflexLayer.attempt_short_circuit(state, verifier_error, planned_action)
if reflex_result:
    # Short-circuit: skip Bedrock retry entirely
    return _emit_reflex_transition(state, reflex_result)

# ── existing FEAT-022 recovery_router call remains unchanged ──
recovery_result = attempt_recovery(state, verifier_error, planned_action)
if recovery_result:
    return _emit_recovery_transition(state, recovery_result)

# ── existing retry-count-bump path remains unchanged ──
new_retry_count = state.get("retry_count", 0) + 1
# … existing behavior …
```

### CQ-C3 Decision: `evaluator.py:~653` — symmetric with existing `attempt_recovery()` call site

**Options explored:**

1. **`evaluator.py` at line 655** — before `new_retry_count` bump.
2. **`executor.py:~770`** — inside `_dispatch_action` failure path.

**Chosen: Option 1.**

**Rationale:**
- Reflex is a **recovery policy**, not an **action-dispatch mechanism**. Policy decisions belong in the evaluator (the LangGraph node whose responsibility is "what next?"), not in the executor (whose responsibility is "run this Playwright command").
- Executor already has cv_fallback, angular_readiness, proactive overlay dismissal, coordinate normalization, mark_id handling, and the FEAT-058 predictive verifier — piling reflex on top would push executor beyond its cognitive-load ceiling.
- Placing reflex in evaluator gives it access to state's `retry_count`, `verifier_verdict`, `agent_critique`, `page_state_snapshot`, and `recovery_attempted_types` — everything a signature match needs.
- Symmetric placement with `attempt_recovery()` (recovery_router lives at the same call site) means future engineers reading evaluator see: **reflex first, then recovery_router, then retry** — three layers, one file, one seam.

### CQ-C4 Decision: `storage/replay/2026-07-27/` directory of `.jsonl` execution traces + `scripts/replay_reflex_benchmark.py`

**Options explored:**

1. Reuse existing `storage/qa/*/audit.json` if present — but the 2026-07-27 sessions were captured on production log tails, not persisted.
2. **New `storage/replay/2026-07-27/` directory of `.jsonl` traces** — one JSONL per session, each line is a `(pre_action_state, planned_action, executor_result, verifier_verdict)` record; a deterministic replay harness re-drives reflex against these traces.
3. Live re-run — infeasible for benchmarking (non-deterministic, requires browser + Bedrock).

**Chosen: Option 2.**

**Rationale:**
- AC-INTEGRATION-3 measures `reflex_hits / (reflex_hits + bedrock_retries)`. Deterministic replay against captured traces is the only way to attribute the ratio to reflex alone (isolating from Bedrock and browser variability).
- Traces are cheap to produce: `scripts/capture_replay_traces.py` tails production `execution_log` records and materializes JSONL — one-time cost.
- Once captured, `scripts/replay_reflex_benchmark.py` runs `ReflexLayer.attempt_short_circuit()` against each frame and computes hit rate — pure Python, no browser, no Bedrock, deterministic.
- Traces are gitignored by pattern (`storage/replay/**/*.jsonl`) but manifest (`storage/replay/2026-07-27/README.md` + `sessions.json`) is committed.

**Trace record schema:**

```json
{
  "session_id": "prod-2026-07-27-001",
  "step_index": 3,
  "pre_action_state": {
    "authenticated_as": "vpromotions_user",
    "ac_step_text": "Select Contest from PRF Category dropdown",
    "page_state_snapshot": "…",
    "retry_count": 1,
    "recovery_attempted_types": ["STRICT_MODE"]
  },
  "planned_action": {"action": "click", "strategy": "get_by_text", "name": "Contest"},
  "executor_result": {"success": false, "error_message": "strict mode violation: p-select-overlay …"},
  "verifier_verdict": "failed"
}
```

**Replay command:** `python scripts/replay_reflex_benchmark.py --traces storage/replay/2026-07-27/ --report reports/reflex-hit-rate.md`.

---

## T3-d — Determinism Budget Assertion

### CQ-D1 Decision: Fresh-capture script `scripts/populate_ac_parse_baseline.py` — content-hash keyed with ticket manifest

**Options explored:**

1. **(a) Backfill from `storage/ac_parse_cache/`** — cache is content-hash keyed (files like `7c98fe48….json`), not ticket-keyed; there is no `ticket_key → parse_result` map anywhere. Infeasible.
2. **(b) Fresh-capture script** `scripts/populate_ac_parse_baseline.py` that fetches each tracked ticket's raw AC from Jira, runs Stage 1+2, and writes `storage/ac_parse_baseline/<ticket_key>.json`.
3. **(c) Reframe as `content_hash(<raw_ac>) → step_count`** — the baseline becomes hash-keyed, matching the existing cache convention.

**Chosen: Option (b), with a design tweak from (c): the baseline JSON stores BOTH `ticket_key` AND `content_hash(raw_ac)`.**

**Rationale:**
- Option (a) is architecturally infeasible.
- Option (c) alone loses ticket-identity: two tickets with identical AC text (rare but possible for template'd tickets) would share one baseline, and CI drift attribution would be ambiguous.
- Option (b) preserves ticket-identity but doesn't detect the "AC text was edited in Jira" case — the baseline would silently disagree with the new text. Adding the content hash lets the drift guard distinguish "same ticket, drifting parser" (real drift, fail) from "same ticket, edited AC" (invalidated baseline, WARN + recapture).

**Baseline JSON schema:**

```json
{
  "ticket_key": "QA-358",
  "content_hash": "sha256:7c98fe48…",
  "raw_ac_snippet": "Given a user with role vpromotions_user…",
  "expected_step_count": 7,
  "captured_at": "2026-07-29T14:00:00Z",
  "captured_from": "scripts/populate_ac_parse_baseline.py@main@1a7e818",
  "notes": ""
}
```

**Manifest:**

```json
// storage/ac_parse_baseline/_manifest.json
{
  "schema_version": 1,
  "generated_at": "2026-07-29T14:05:00Z",
  "tickets": [
    {"ticket_key": "QA-358", "content_hash": "sha256:7c98fe48…"},
    {"ticket_key": "QA-421", "content_hash": "sha256:1a2b3c…"}
  ]
}
```

### CQ-D2 Decision: Fail-fast for tracked tickets + WARN + auto-record for un-tracked

**Options explored:**

1. Skip with WARN + populate on-the-fly — hides drift silently the first time.
2. Fail-fast startup-time completeness check — every ticket must have a baseline before it can run. Too restrictive for exploratory runs.
3. **Fail-fast for tracked tickets + WARN + record for un-tracked** — a ticket is "tracked" iff it appears in `_manifest.json`.

**Chosen: Option 3.**

**Rationale:**
- Startup-time completeness (Option 2) blocks exploratory PM runs on brand-new tickets. Not aligned with the tool's primary user flow.
- Option 1 destroys the invariant: any silent baseline-write means we can't detect drift on the first regression.
- Option 3 gives us both: tickets we care about (opted into `_manifest.json`) are protected by the strict `|current - baseline| > 2` assertion; un-tracked tickets emit a WARN and auto-write a *provisional* baseline to `storage/ac_parse_baseline/<ticket>.provisional.json`. Provisional baselines never fail the run; an operator promotes them to real baselines via the `scripts/populate_ac_parse_baseline.py --promote <ticket>` command after review.
- The startup check validates **manifest integrity only** — that every entry in `_manifest.json` has a corresponding `<ticket_key>.json` file. Missing baseline files for tracked tickets = exit(1).

### CQ-D3 Decision: (c) Enumerate every file in `storage/ac_parse_baseline/*.json`

**Options explored:**

1. **(a) Hard-coded ticket list in workflow YAML** — brittle; two sources of truth (baseline files + YAML).
2. **(b) Read from `_manifest.json`** — one source of truth, but requires manifest health; a missing manifest = broken CI.
3. **(c) Enumerate every `*.json` file** — filesystem is the source of truth.

**Chosen: Option (c).**

**Rationale:**
- Adding a new baseline (via `populate_ac_parse_baseline.py`) automatically onboards to CI without touching the workflow YAML.
- No coupling between the manifest and CI — if manifest generation ever regresses, CI still works from the raw files.
- The workflow YAML uses `jq -r '.ticket_key' storage/ac_parse_baseline/*.json | grep -v provisional` — one line, zero fragility.
- The `_manifest.json` remains useful for the runtime (fast lookup during `assert_drift`) but no longer sits on the CI critical path.

**Workflow sketch:**

```yaml
# .github/workflows/ac-parse-drift.yml
name: AC Parse Drift Guard
on: [pull_request]
jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Enumerate tracked tickets
        id: tickets
        run: |
          tickets=$(jq -r '.ticket_key' storage/ac_parse_baseline/*.json \
                    | grep -v provisional | jq -R -s -c 'split("\n") | map(select(length>0))')
          echo "matrix=$tickets" >> "$GITHUB_OUTPUT"
      - name: Run drift check for each ticket
        run: python scripts/check_ac_parse_drift.py --tickets "${{ steps.tickets.outputs.matrix }}"
```

---

## Observability Architecture

### Logging

- **Library**: existing project logger (Python stdlib `logging` with structured `extra`); no new library.
- **Format**: JSON via existing formatter; new `event_type` values are additive.
- **New event types introduced by this feature**:
  - `product_kb_missing` — startup validation failure (T3-a)
  - `ac_negotiator_complaint` — per complaint, with `product` field (T3-a)
  - `registry_enrichment_needed` — per registry miss (T3-b)
  - `registry_hit` — per registry hit (T3-b, debug-level)
  - `reflex_short_circuit` — per reflex hit (T3-c)
  - `ac_parse_drift_detected` — per baseline mismatch (T3-d)
  - `ac_parse_baseline_provisional_written` — per auto-recorded baseline (T3-d)

### Distributed Tracing

Not applicable — vQA is a single-process LangGraph runtime; no OTel setup exists today and this feature does not introduce inter-service boundaries.

### Metrics

Reporter-emitted metrics (already collected via `state`):

| Metric                                    | Labels               | Purpose                                         |
| ----------------------------------------- | -------------------- | ----------------------------------------------- |
| `complaints_by_product`                   | product              | AC-INTEGRATION-1 measurement                    |
| `registry_hits`                           | product              | T3-b coverage growth                            |
| `registry_misses`                         | product, ac_step     | T3-b enrichment backlog                         |
| `reflex_hits_by_signature`                | signature_id         | T3-c effectiveness by signature                 |
| `bedrock_retries_in_retry_path`           | -                    | AC-INTEGRATION-3 denominator                    |
| `ac_parse_drift_events`                   | ticket_key           | T3-d drift frequency                            |

### Configuration Variables

| Variable                                  | Purpose                                                       | Default   |
| ----------------------------------------- | ------------------------------------------------------------- | --------- |
| `PRODUCT_KB_VALIDATION_ENABLED`           | T3-a startup check; set to false only for tests               | `true`    |
| `REGISTRY_FIRST_GATE_ENABLED`             | T3-b enforcement; can be dropped to shadow-only for rollout   | `true`    |
| `REGISTRY_FIRST_GATE_SHADOW_MODE`         | Emit registry_hit event but do not rewrite action             | `false`   |
| `REFLEX_LAYER_ENABLED`                    | T3-c short-circuit; set to false to fall back to FEAT-022     | `true`    |
| `AC_PARSE_DRIFT_GUARD_ENABLED`            | T3-d assertion; can be disabled for exploratory branches      | `true`    |
| `AC_PARSE_DRIFT_TOLERANCE`                | ±N step count tolerance                                       | `2`       |

---

## Evaluation Matrix

Each CQ was evaluated against these dimensions on a 1–5 scale (5 = best). Table shows only the chosen option per CQ.

| CQ    | Scalability | Maintainability | Performance | Observability | Cost | Simplicity |
| ----- | ----------- | --------------- | ----------- | ------------- | ---- | ---------- |
| CQ-A1 | 5           | 5               | 4           | 5             | 5    | 5          |
| CQ-A2 | 5           | 4               | 5           | 5             | 5    | 4          |
| CQ-A3 | 5           | 5               | 5           | 4             | 5    | 5          |
| CQ-B1 | 5           | 5               | 4           | 5             | 5    | 4          |
| CQ-B2 | 5           | 5               | 5           | 5             | 5    | 5          |
| CQ-B3 | 4           | 5               | 5           | 5             | 5    | 4          |
| CQ-C1 | 5           | 5               | 5           | 5             | 5    | 5          |
| CQ-C2 | 5           | 5               | 5           | 5             | 5    | 5          |
| CQ-C3 | 5           | 5               | 5           | 5             | 5    | 5          |
| CQ-C4 | 4           | 4               | 5           | 5             | 4    | 4          |
| CQ-D1 | 5           | 4               | 5           | 5             | 5    | 4          |
| CQ-D2 | 5           | 5               | 5           | 5             | 5    | 4          |
| CQ-D3 | 5           | 5               | 5           | 5             | 5    | 5          |

---

## Impact on System Patterns

New entries to be added to `systemPatterns.md` during Phase 5 (Documentation Agent):

- **Product-Isolated KB Loader (T3-a)** — `LocalKnowledgeBase.query()` walks `knowledge/<product>/*.md` for the active product plus root-level global-neutral files; cross-product bleed is architecturally prevented.
- **Registry-First Planner Gate (T3-b)** — Every planner action passes through `RegistryFirstGate.check()` before emission; `get_by_text` for a registered target is deterministically rewritten to `get_by_role`/`vqa_id`.
- **Reflex Layer (T3-c)** — Stateless signature → recovery-action lookup runs BEFORE FEAT-022's recovery_router in the evaluator retry path. YAML catalog + Python dispatch table; new signatures added by editing YAML alone (unless a new factory type is needed).
- **AC Parse Drift Baseline (T3-d)** — Per-ticket step-count baseline in `storage/ac_parse_baseline/`; content-hash-keyed to detect edited-AC vs drifting-parser; CI enumerates baseline files rather than a hard-coded ticket list.

---

## Implementation Guidelines

1. **Phase 1 (T3-a)**: extend `product_registry.py` with `validate_product_kb_roots()`; migrate flat KB files under `knowledge/vpromedia/`; add `POST /execute` `product_kb_available` guard; introduce `ac_negotiator_complaint` structured log tag + `ComplaintCounter`.
2. **Phase 2 (T3-b)**: create `backend/engine/registry_first_gate.py`; wire into `_build_action()` at planner.py; extend selector_registry schema to nest by product slug; write `scripts/extract_seed_selectors.py`; seed QA-358 + top-10 failures.
3. **Phase 3 (T3-c)**: create `backend/engine/reflex/` subpackage with `catalog.yaml`, `factories.py`, `reflex.py`; insert at evaluator.py:~653 before existing `attempt_recovery()`; capture `storage/replay/2026-07-27/*.jsonl` traces; add `scripts/replay_reflex_benchmark.py`.
4. **Phase 4 (T3-d)**: create `backend/engine/ac_parse_drift.py`; wire assertion into ac_parser.py:~550 post-Stage-2; write `scripts/populate_ac_parse_baseline.py`; add `.github/workflows/ac-parse-drift.yml`.
5. **Phase 5 (integration + docs)**: update `systemPatterns.md` with 4 new pattern entries; smoke-test end-to-end on the curated 10-ticket vpromotions sample; verify AC-INTEGRATION-1/2/3 targets hit.

---

## Validation Checklist

- [x] Meets all system requirements (R1–R6)
- [x] Respects technical constraints (planner size, FEAT-022 preservation, no UI additions)
- [x] Addresses non-functional requirements (NFR-1 through NFR-6)
- [x] Technically feasible (all anchors verified against actual code)
- [x] Risks identified and acceptable (see Risk Assessment)
- [x] Complies with Guiding Principles in systemPatterns.md — no deviations required
- [x] Respects established patterns (Failure Diary, Merge-and-Protect, Product Registry, Automated Registry Sync)
- [x] Observability architecture defined (new event tags, metrics, config vars)
- [x] Logging strategy consistent with existing structured-log conventions
- [x] Metrics strategy follows existing state-driven reporting pattern

---

## Risk Assessment

| Risk                                                                                              | Likelihood | Impact | Mitigation                                                                                                                            |
| ------------------------------------------------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| Startup-time KB validation blocks stub products (`psn`, `vep`, `vppo`) with `roles: []`           | M          | L      | Validator exempts zero-role products from KB completeness; still validates path syntactic well-formedness                             |
| RegistryFirstGate rewrites an action but the registry entry is stale (framework moved the button) | M          | M      | `_registry_hit` flag on rewritten action feeds into existing failure diary; three consecutive failures on a hit auto-mark it stale    |
| Reflex signature over-matches and short-circuits a case that needed Bedrock                       | M          | M      | Every reflex hit emits full pre/post state in `reflex_short_circuit` event; shadow-mode env var lets us disable specific signatures   |
| Baseline recapture on Jira AC edit is missed by an operator; tracked ticket drift-alarms silently | L          | H      | `ac_parse_drift_detected` event fires with both current and baseline `content_hash`; reporter shows "AC EDITED" banner when they diff |
| Trace-based replay (CQ-C4) doesn't exactly match live behavior                                    | M          | L      | Replay is used only for the AC-INTEGRATION-3 ratio measurement; production correctness is validated by live smoke run in Phase 5     |
| YAML reflex catalog grows unbounded and becomes an alternative planner                            | L          | M      | Catalog schema enforces `signatures: []` (not `signatures: {}`) so entries are ordered and reviewable; CI check on file size          |

---

## Algorithm-Creative Gate

**Given CQ-C1 decision = "Hybrid YAML catalog + Python dispatch table (lookup shape, not state machine)", an Algorithm creative pass is NOT REQUIRED because:**

- The reflex layer is a stateless O(N) signature-match iteration where N is small (~10 signatures, growing to ~30 over time). There is no algorithm to design — it is a filtered scan over a list.
- Recovery-action factory functions are simple, deterministic transformations (`press_escape_then_reopen`, `rewrite_to_row_client_name_click`, etc.) that operate on a single `planned_action` dict without cross-signature interaction.
- No state machine, no ranking, no dynamic programming, no ML — decisions are strict regex/string matches on `error_msg` + preconditions on `state`.
- Signature ordering is authored (first-match-wins), not computed — no algorithmic choice.
- The one place a small algorithm exists — the "logout-then-relogin" factory sequence — is a fixed 3-step recipe already resembling existing blueprint YAML runners; it reuses the existing `recipe_runner.py` conventions.

Algorithm creative can be skipped; Phase 3 build can proceed directly from this architecture doc.

---

## Next Steps

1. Orchestrator: skip Algorithm creative pass; proceed to any remaining creative passes required by the Level 4 workflow.
2. Phase 0 (this doc's follow-up): capture the `main@1a7e818` baseline complaint volume for AC-INTEGRATION-1 (run the 10-ticket vpromotions curated sample with a lightweight instrumentation branch that adds the `ac_negotiator_complaint` tag but no counter or gate).
3. Phase 1 kick-off: `/bmb:build` on T3-a.

---

## New Terms Introduced

| Term                          | Definition                                                                                                            |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Product KB Partition**      | The `knowledge/<product>/*.md` subdirectory convention that scopes KB workflows to a single product.                  |
| **Registry-First Gate**       | Planner pre-emit gate that consults `selector_registry` before any `get_by_text` fallback is emitted.                 |
| **Registry Miss / Registry Hit** | A registry lookup outcome; each is a structured log event (`registry_enrichment_needed` / `registry_hit`).         |
| **Reflex Signature**          | An entry in `backend/engine/reflex/catalog.yaml` — a regex/precondition pattern paired with a recovery-action factory. |
| **Reflex Short-Circuit**      | A retry-path decision to skip Bedrock and directly emit a deterministic recovery action.                              |
| **Reflex Factory**            | A typed Python function (in `factories.py`) that produces a `ReflexResult` from a matched signature + state.          |
| **AC Parse Baseline**         | Per-ticket JSON in `storage/ac_parse_baseline/` recording expected step count for drift assertion.                    |
| **Provisional Baseline**      | An auto-recorded baseline (`<ticket>.provisional.json`) for un-tracked tickets; never fails the run.                  |
| **Tracked Ticket**            | A ticket appearing in `storage/ac_parse_baseline/_manifest.json`; subject to fail-fast drift assertion.               |
| **AC Negotiator Complaint**   | A structured log event (`event_type=ac_negotiator_complaint`) emitted by `ac_enricher.py` per complaint, tagged with product. |
| **Complaint Counter**         | An in-run state accumulator that surfaces per-product complaint totals in the reporter.                               |
| **Drift Tolerance**           | The absolute step-count delta (`|current - baseline| ≤ 2`) below which a run passes the T3-d assertion.               |
