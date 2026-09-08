---
legacy_id: FEAT-118
version: next
linked_tasks: [FEAT-118-vqa-tier3-architectural-hardening]
status: completed
completed: 2026-07-29
---

### FEAT-118: vQA Tier 3 — Architectural Hardening (Isolation, Registry, Reflex, Determinism)
- **Version**: next
- **Status**: completed
- **Completed**: 2026-07-29 (task FEAT-118-vqa-tier3-architectural-hardening — see `memory-bank/archive/FEAT-118-vqa-tier3-architectural-hardening-archive.md`)
- **Priority**: medium
- **Complexity**: Level 4
- **Description**: The architectural shifts needed to turn vQA from "an LLM-driven best-effort tester" into "a deterministic testing platform that gets faster and cheaper with every run." Tier 3 addresses four systemic issues surfaced by the 2026-07-27 analysis: (i) product isolation is not enforced — vPromotions runs use vProMedia terminology and get 90+ negotiator complaints per ticket; (ii) the planner still defaults to `get_by_text` even when a selector registry entry exists for the target; (iii) ~40% of Bedrock LLM calls in the logs are for failure signatures that a hard-coded reflex layer could handle without an LLM; (iv) AC parsing drift is currently observed and tolerated instead of asserted against.

  Implementation is phased:
  1. **First-Class Product Isolation (T3-a)** — Formalize `products.yaml` as a registry with per-product `personas`, `knowledge/`, `selector_registry/`, `test_matcher/` roots. Reject a run whose ticket product does not have a matching KB rather than silently falling back to vProMedia terminology. Every LLM prompt receives ONLY the active product's persona list, KB workflows, and selector registry. The AC negotiator's per-product complaint rate drops toward zero.
  2. **Selector-Registry-First Planner (T3-b)** — Replace "click text + hope" with a required lookup against `knowledge/selector_registry.json` before any `get_by_text` fallback. Registered selectors become fast, deterministic paths; every miss becomes an auto-opened Jira ticket to enrich the registry. Over time the registry saturates the vSuite surface area and `get_by_text` becomes the exception, not the rule.
  3. **Reflex Layer (T3-c)** — Introduce `backend/engine/reflex.py`: a hard-coded catalog of failure-signature → deterministic-recovery mappings. Entries include: "strict mode 0 visible → check parents", "native `<select>` detected → switch to `select_option`", "spinner present → wait 500ms", "aria-expanded=false → click trigger first". Runs BEFORE any Bedrock call in the retry path. Analysis of today's logs suggests ~40% of LLM iterations are recoverable this way. Massive cost + latency reduction.
  4. **Determinism Budget Assertion (T3-d)** — Add a per-run assertion: `if abs(current_ac_step_count - baseline_ac_step_count) > 2: fail_run("AC parse drift")`. Baselines are stored per ticket in the `storage/ac_parse_baseline/` directory (auto-populated by T2-a's cache). Drift is now a first-class error rather than tolerated noise; CI can regression-gate on it.

- **Acceptance Criteria**:
    - AC-1: `products.yaml` schema enforces per-product `personas`, `knowledge`, `selector_registry`, and `test_matcher` root paths. A run started with an unregistered product (or a product whose KB directory does not exist) fails fast with a clear error, not a silent fallback.
    - AC-2: When product=vpromotions is active, `KBLoader.query_workflows()` returns ONLY vpromotions KB entries — no vProMedia workflow is included in any planner prompt. The AC negotiator's cross-product complaint volume drops ≥ 80% on a curated 10-ticket vpromotions sample.
    - AC-3: The planner's target-resolution pipeline first queries `selector_registry` before emitting a `get_by_text` action. A registry hit is used directly (with `strategy=css_selector`); a miss auto-emits a `Registry Enrichment Needed` telemetry event that surfaces in the dashboard.
    - AC-4: Given the QA-358 "Select Contest from PRF Category dropdown" step and a registry entry for `pvpromotions.new_prf.category`, the planner does NOT emit `get_by_text("Contest")` — it emits a scoped selector click and succeeds on iteration 1.
    - AC-5: `backend/engine/reflex.py` handles at least 6 failure signatures (strict-mode-0-visible, native-select-detected, spinner-present, aria-expanded-false, portal-not-open, action-repeat-loop). Reflex runs in the retry path BEFORE any Bedrock call.
    - AC-6: On a replay of the 5 sessions captured today (2026-07-27), reflex handles ≥ 40% of the retry-path LLM invocations — measured as `reflex_hits / (reflex_hits + bedrock_retries)`. LLM cost per run drops proportionally.
    - AC-7: A run whose AC parse count deviates from its baseline by > 2 fails with `AC_PARSE_DRIFT`, not `success=partial`. The baseline directory `storage/ac_parse_baseline/` is auto-populated by T2-a's cache.
    - AC-8: CI gate: a new test in `.github/workflows/` runs `pytest tests/regression/ac_parse_baseline_check.py -v` and blocks merge if any tracked ticket has drifted from baseline.

- **Key Files**:
    - `backend/config/products.yaml` — T3-a: promote to strict schema; add `personas`/`knowledge`/`selector_registry`/`test_matcher` root paths
    - `backend/api/routes.py` — T3-a: reject unregistered product; enforce product-scoped loading
    - `backend/kb/loader.py` — T3-a: strict product filter (no cross-product fallback)
    - `backend/engine/planner.py` — T3-b: mandatory selector-registry lookup before `get_by_text`; enrichment-needed telemetry
    - `backend/kb/selector_registry.py` — T3-b: expose product-scoped lookup API
    - `knowledge/selector_registry.json` — T3-b: seed with QA-358 and top-10 failing ticket selectors
    - `backend/engine/reflex.py` (New) — T3-c: reflex catalog with signature → recovery mappings
    - `backend/engine/executor.py` — T3-c: reflex hook in the retry path
    - `backend/engine/ac_parser.py` — T3-d: baseline comparison + `AC_PARSE_DRIFT` failure mode
    - `storage/ac_parse_baseline/` (New) — per-ticket parse baselines
    - `tests/regression/ac_parse_baseline_check.py` (New) — CI-gating drift test
    - `.github/workflows/ac-parse-drift.yml` (New) — CI hook for drift check
- **Linked Tasks**: None
- **Branch**: feature/FEAT-118-vqa-tier3-architectural-hardening
- **Created**: 2026-07-28
- **Depends On**: FEAT-116 (Tier 1), FEAT-117 (Tier 2 — specifically T2-a for baseline population)
