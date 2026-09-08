# Architecture Decision: Accessibility Tree Grounding

**Created**: 2026-07-30
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: `accessibility-tree-grounding`
**Complexity**: Level 3 (NFR / infrastructure)
**Related PRs / features**: FEAT-037 (CV fallback, merged — closest precedent); FEAT-042 (RAG selector registry — enrichment shares KB touchpoints)

---

## Context

### Feature Overview

The feature operationalizes the **Semantic Locators First** guiding principle (`systemPatterns.md`) end-to-end. Today, the AC parser emits `TestPlanStep.target_component` (a free-text component identifier) and `TestPlanStep.target_element_types` (a list of ARIA roles), and the executor resolves locators via `_resolve_locator()` at `backend/engine/executor.py:503`, which relies almost entirely on strategy strings the *planner* LLM chose per action. When the planner picks a `css_selector` (or a `get_by_role` with a wrong `name`), execution flakes on UI reshuffles.

The feature introduces:

1. **AC-parser enrichment** — the compiler propagates `aria_role` / `aria_name` onto each `TestPlanStep` (from the ARIA tree, never hallucinated) so downstream nodes have a semantically stable target *before* the planner runs.
2. **`A11yLocatorResolver`** — a three-branch chain (a11y → selector → CV signal) that wraps the existing `_resolve_locator()` seam at `executor.py:503`. When `aria_role` is present on the current action's step, it attempts `page.get_by_role(...)` first; otherwise it falls through to today's selector logic bit-for-bit (AC-VERIFY-9). On probe exception → WARN + fall through (AC-ERROR-1).

Two decisions define the module boundaries for the feature. Both are architectural (module location + pipeline placement), so they belong in one Architecture creative doc.

### System Requirements

- **REQ-1** — `A11yLocatorResolver.resolve(page, step) -> (locator, resolution_path)` MUST be the single new integration seam called from `executor.py:503`.
- **REQ-2** — When `aria_role is None` on the step, resolver behavior MUST be **bit-for-bit identical** to today's `_resolve_locator()` (AC-VERIFY-9).
- **REQ-3** — ARIA-tree probe exceptions MUST NOT propagate to LangGraph (AC-ERROR-1); WARN log + fall-through only.
- **REQ-4** — `aria_role` / `aria_name` MUST NEVER be hallucinated. They MUST originate from either (a) the live ARIA snapshot in the compiler's LLM context, or (b) a deterministic post-compile matcher on `page.accessibility.snapshot()` — not from LLM free-generation on the AC text alone (AC-VERIFY-2).
- **REQ-5** — Feature MUST be shippable behind a feature flag with the legacy path preserved.

### Technical Constraints

- **CON-1** — `backend/browser/accessibility.py` already exists and is owned by `planner_node` for LLM-facing snapshot formatting. It MUST NOT be overloaded with resolver logic (see task-file scope note: "the resolver calls `page.get_by_role()` directly, not the formatted text snapshot").
- **CON-2** — `backend/engine/a11y_discovery.py` also exists and does ARIA→locator string mapping (`prune_and_map_a11y_tree`). It's not on the executor hot path and produces *strings* (`page.getByRole("button", {"name": "Foo"})`) rather than live Playwright `Locator` objects — cannot be reused as-is.
- **CON-3** — The AC parser is a **two-stage LLM pipeline** (`ac_parser.py`: BDD normalizer → JSON compiler). At compile time, there is **no live browser session** — `ac_parser_node` runs before `login_node` in the LangGraph (`systemPatterns.md` node graph). This is a hard constraint on Decision 2 Option B.
- **CON-4** — `TestPlanStep` is a Pydantic model at `schemas.py:231` and is persisted / broadcast to the frontend copilot sidebar. New fields must be optional and defaultable to preserve backward compatibility with existing runs.
- **CON-5** — FEAT-037 established the precedent that browser-mechanism resolvers live at `backend/browser/`, and the executor imports them (`from backend.browser.cv_resolver import CvFallbackResolver`).

### Non-Functional Requirements (from `productBrief.md` / precedent)

- **NFR-perf** — Resolution latency added per action MUST be ≤ 100 ms in the happy path (measured across a batch benchmark). CV fallback allows ~300 ms per invocation as precedent; a11y-first resolution is expected to be **faster** than the current CSS-heavy strategy in most cases.
- **NFR-flake** — Feature exists to reduce E2E flake. Overall run pass rate on the vpromedia suite MUST improve (or hold flat) with the flag enabled — measured by `benchmark_pipeline.py --full`.
- **NFR-obs** — Every resolution branch taken MUST be observable in structured logs (WARN on fallback, INFO on branch selection) and in the audit-trail JSON, using the existing structured-logging conventions.
- **NFR-reversible** — Feature MUST be reversible via env flag (`A11Y_RESOLVER_ENABLED`) without a code rollback.

### Existing Patterns to Respect

- **Semantic Locators First** (guiding principle) — this feature operationalizes it.
- **Multimodal Grounding** — the compiler already receives the ARIA tree (for other purposes); the feature can lean into that.
- **Failure Diary Pattern** — resolver fall-throughs count as diary entries; existing `ac_step_action_fail_count` remains the source of truth.
- **12-Factor / Config in Environment** — new toggles via `.env`, no hardcoding.
- **Browser-mechanism modules under `backend/browser/`** — FEAT-037 established this. `backend/engine/` is for state-machine nodes, orchestration, and prompts; `backend/browser/` is for Playwright-touching resolvers, snapshots, and vision utilities.

---

## Component Analysis

### Core Components

| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `A11yLocatorResolver` (new) | Three-branch locator resolution | (1) `get_by_role` if `aria_role` present; (2) fall through to existing `_resolve_locator` on failure/probe error; (3) return `(locator, resolution_path)` where `resolution_path ∈ {"a11y_direct", "selector_fallback", "selector_only_legacy"}` |
| `_resolve_locator` (existing, `executor.py:503`) | Today's per-action locator resolution | Retained verbatim; called by the resolver in branches 2 and 3 |
| AC compiler stage 2 (existing, `ac_parser.py`) | JSON-compile BDD → `TestPlan` | Extended to populate `TestPlanStep.aria_role` / `aria_name` (mechanism = one of Decision 2's options) |
| `TestPlanStep` (existing, `schemas.py:231`) | Per-step plan model | New optional fields `aria_role: str | None`, `aria_name: str | None` (default `None`) |
| ARIA snapshot source (existing) | ARIA tree ingestion | `page.accessibility.snapshot()` — `a11y_discovery.capture_a11y_snapshot` already wraps it; can be re-used by an enrichment pass |

### Component Interactions (target state)

```
  ac_parser_node (LLM: BDD → JSON compiler)
        │
        │   [Decision 2 — enrichment happens here or below]
        ▼
  TestPlan (steps carry aria_role/aria_name when discoverable)
        │
        ▼
  planner_node ──► action JSON (with strategy/role/name/…)
        │
        ▼
  executor_node.execute_action(page, action, step)
        │
        └──► A11yLocatorResolver.resolve(page, step, action)   [Decision 1 — module location]
                 ├─ branch 1: get_by_role(aria_role, name=aria_name)  → resolution_path="a11y_direct"
                 ├─ branch 2: probe fail / not visible → fall through to _resolve_locator()  → "selector_fallback"
                 └─ branch 3: aria_role is None → immediate _resolve_locator()               → "selector_only_legacy"
```

---

## Decision 1: `A11yLocatorResolver` Module Location

### Options Explored

#### Option 1A: `backend/browser/a11y_resolver.py`

- **Description**: New module under `backend/browser/`, alongside `cv_resolver.py` and `accessibility.py`. Executor imports it the same way it imports `CvFallbackResolver` today (`from backend.browser.cv_resolver import CvFallbackResolver` — see task-file).
- **Components**: `A11yLocatorResolver` class + module-level probe helper `_probe_aria_target(page, role, name) -> bool`.
- **Pros**:
  - **Exact precedent match** — FEAT-037's `cv_resolver.py` is the "closest architectural precedent" cited in the task file; the feature is literally introducing a sibling to it. The three-branch chain of `A11yLocatorResolver` mirrors the two-branch chain of `CvFallbackResolver` (resolve → mark_id/None) at the same layer of abstraction.
  - **Cohesion with `accessibility.py`** — Both modules touch the ARIA tree via Playwright; grouping them under `backend/browser/` keeps every module that calls `page.accessibility.*` in one directory. This is the natural home for future a11y-related utilities (e.g., a landmark-aware element extractor).
  - **Dependency direction is clean** — `backend/engine/` already imports from `backend/browser/` (see `executor.py` importing `cv_resolver`); no cycles.
  - **Test scaffolding is shared** — `tests/backend/browser/` layout can co-locate `test_a11y_resolver.py` and reuse the `Page` mocking patterns from `test_cv_resolver.py`.
- **Cons**:
  - Uses `TestPlanStep` (defined in `backend/engine/schemas.py`) as an input type — creates a `browser → engine` import for a schema, which is a slight layering wrinkle. Mitigated by passing a narrow `dict`/`TypedDict` (or by promoting the a11y-relevant fields into a small dataclass in `browser/`).
- **Technical Fit**: **High** — mirrors FEAT-037.
- **Complexity**: **Low** — brand-new file, small surface area.
- **Scalability**: **High** — future ARIA-aware resolvers (e.g., landmark scoping, table-cell-by-header) accumulate here cleanly.

#### Option 1B: `backend/engine/a11y_resolver.py`

- **Description**: New module under `backend/engine/`, next to `a11y_discovery.py`, `executor.py`, and other engine-layer files.
- **Components**: Same class as 1A.
- **Pros**:
  - Physically adjacent to the caller (`executor.py`) — one directory listing shows caller and callee.
  - Adjacent to `a11y_discovery.py`, which already contains engine-layer ARIA logic — arguable topical grouping.
  - No `browser → engine` import for `TestPlanStep`.
- **Cons**:
  - **Breaks the FEAT-037 precedent** — `cv_resolver` (functionally analogous) lives at `backend/browser/`. Putting the a11y resolver at `backend/engine/` would fork the convention with no upside, forcing future readers to search two directories for "resolvers."
  - **`a11y_discovery.py` is a red herring** — despite its name, it emits *locator strings*, is not on the executor hot path, and appears from `techContext.md` and grep evidence to be lightly used. Its being in `backend/engine/` is arguably an older layering choice that shouldn't be entrenched.
  - **`backend/engine/` is already crowded** — 30+ modules per `techContext.md`. Adding a browser-mechanism module here dilutes the intended split (engine = LangGraph nodes + state-machine glue; browser = Playwright plumbing).
- **Technical Fit**: **Medium** — plausible on its own terms, but explicitly counter to the established convention.
- **Complexity**: **Low** — same as 1A.
- **Scalability**: **Medium** — future a11y-mechanism modules would either accrete here (further crowding `engine/`) or split awkwardly.

#### Option 1C: Extend `backend/browser/accessibility.py` with a `resolve(...)` function

- **Description**: Add `resolve_via_a11y(page, aria_role, aria_name)` and orchestration helpers directly onto the existing accessibility module. No new file.
- **Components**: New function added to `accessibility.py`.
- **Pros**:
  - Fewest new files.
  - All ARIA logic lives in one place.
- **Cons**:
  - **Directly violates the task-file scope note**: "existing `backend/browser/accessibility.py` … Do NOT overload it — the resolver calls `page.get_by_role()` directly, not the formatted text snapshot." Product-owner intent is explicit.
  - **Mixes two very different jobs** — `accessibility.py` today produces LLM-facing *text* (`extract_accessibility_tree`, `extract_interactive_summary`); the resolver produces Playwright *`Locator` objects*. Different consumers, different return types, different failure modes.
  - **Import bloat** — every `planner_node` startup would pull the resolver dependencies just to format a tree.
- **Technical Fit**: **Low** — explicitly ruled out by the task file.
- **Complexity**: **Low** to write, **High** to maintain — a single file gathering unrelated concerns is a well-known cohesion smell.
- **Scalability**: **Low** — future ARIA utilities keep piling onto one module.

### Evaluation Matrix — Decision 1

| Criterion | 1A `backend/browser/a11y_resolver.py` | 1B `backend/engine/a11y_resolver.py` | 1C extend `accessibility.py` |
|-----------|----------------------------------------|----------------------------------------|---------------------------------|
| Precedent alignment (FEAT-037) | **High** | Medium | Low |
| Cohesion (per-module) | **High** | Medium | Low |
| Layering cleanliness | Medium (schema import) | **High** | Medium |
| Follows task-file scope note | **Yes** | **Yes** | **No** |
| Test co-location | **High** | Medium | Low |
| Future extensibility | **High** | Medium | Low |
| Implementation effort | Low | Low | Lowest |
| Reviewer surprise cost | Lowest (mirrors FEAT-037) | Medium (forks convention) | High (violates scope note) |

### Chosen: **Option 1A — `backend/browser/a11y_resolver.py`**

#### Rationale

FEAT-037 is the exact precedent — the task file names it explicitly ("Mirrors the shape of `backend/browser/cv_resolver.py`") — and Option 1A is a straight application of that precedent. The one wrinkle (importing `TestPlanStep` from `backend/engine/schemas`) is minor and can be sidestepped by having `A11yLocatorResolver.resolve(...)` take only the ARIA-relevant fields it needs (`aria_role: str | None`, `aria_name: str | None`, plus the existing `action: dict`), rather than the full `TestPlanStep` model — this also makes unit tests trivial to author.

The `backend/browser/` vs `backend/engine/` split is a real architectural axis in this codebase: `backend/engine/` is for LangGraph nodes and orchestration (`planner.py`, `executor.py`, `verifier.py`, `evaluator.py`, `recovery_router.py`), and `backend/browser/` is for the mechanisms those nodes drive (`cv_resolver.py`, `accessibility.py`, `screenshot.py`, `vision_utils.py`). The a11y resolver is unambiguously a *mechanism* — it takes a live `Page` and returns a Playwright `Locator`, with no state-machine state and no LangGraph coupling.

#### Trade-offs Accepted

- **`browser → engine` schema import (mitigated)**: We accept a narrow, one-way dependency from `backend/browser/a11y_resolver.py` on `TestPlanStep` field *shapes*. Mitigation: the resolver signature is `resolve(page, aria_role, aria_name, action) -> (locator, resolution_path)` — it accepts the primitive fields, not the model. Callers (the executor) unpack `step.aria_role` / `step.aria_name` at the call site. Zero engine-layer imports inside the resolver.
- **Two files with "a11y" prefix**: `backend/engine/a11y_discovery.py` (existing, string-emitting, off-hot-path) and `backend/browser/a11y_resolver.py` (new, `Locator`-emitting, on-hot-path). Naming disambiguation is handled by directory (`browser/` = live resolution, `engine/` = discovery/tooling). If `a11y_discovery.py` becomes dead code post-feature, a follow-up cleanup task can archive it.

#### Implementation Guidelines

1. **File**: `backend/browser/a11y_resolver.py`.
2. **Public surface**: `class A11yLocatorResolver` with one async method:
   ```python
   async def resolve(
       self,
       page: Page,
       aria_role: str | None,
       aria_name: str | None,
       action: dict[str, Any],
   ) -> tuple[Locator | None, Literal["a11y_direct", "selector_fallback", "selector_only_legacy"]]:
   ```
3. **Branch 3 (legacy)**: When `aria_role is None`, immediately call `from backend.engine.executor import _resolve_locator; return await _resolve_locator(page, action), "selector_only_legacy"` — bit-for-bit compatibility (AC-VERIFY-9).
4. **Branch 1 (a11y-first)**: `locator = page.get_by_role(aria_role, name=aria_name)`; probe with `await locator.first.is_visible(timeout=<A11Y_PROBE_TIMEOUT_MS from settings>)` inside a `try/except` that maps ANY exception to a WARN log and falls through to Branch 2 (AC-ERROR-1).
5. **Branch 2 (fallback)**: `return await _resolve_locator(page, action), "selector_fallback"`.
6. **Integration seam**: `executor.py:503` gets a wrapper — the module-level `_resolve_locator` stays, but a new `_resolve_locator_with_a11y` (or inline block) instantiates `A11yLocatorResolver()` and dispatches. Feature-flag: `settings.a11y_resolver_enabled` (default `True` after AC-VERIFY-9 passes benchmarks; `False` initially for shadow mode).
7. **Logging** (structured, per NFR-obs): every branch selection emits `logger.info("A11Y_RESOLVER_BRANCH: path=%s aria_role=%s aria_name=%r target=%r", …)`; fall-throughs emit `logger.warning("A11Y_RESOLVER_FALLBACK: reason=%s aria_role=%s aria_name=%r", …)`.
8. **Audit trail**: append `resolution_path` to the per-step `ExecutionStep` record so the reporter and analytics dashboard can compute a "% a11y-direct" rollup.
9. **Tests**: `tests/backend/browser/test_a11y_resolver.py` — mirror `test_cv_resolver.py` layout (mock `Page`, mock `Locator`, assert branch selection under each of: `aria_role=None`, `aria_role` present + probe success, `aria_role` present + probe raises, `aria_role` present + `is_visible=False`).

---

## Decision 2: AC-parser ARIA Enrichment Placement

### Options Explored

The AC parser's stage 2 (JSON compiler) is where `TestPlanStep` fields are populated (`ac_parser.py` — imports `TestPlan`/`Verification` from `schemas.py`, uses `JSON_COMPILER_PROMPT` from `prompts.py`, wraps a Bedrock call). We need to add `aria_role` / `aria_name` fields to the step **without hallucination**. There are three real options.

#### Option 2A: **In-prompt enrichment inside the JSON compiler**

Instruct the LLM (in `JSON_COMPILER_PROMPT`) to emit `aria_role`/`aria_name` **by matching `target_component` to the ARIA tree already in its context**. Add a `<live_aria_tree>` XML block to the compiler's user message (the compiler runs after login isn't guaranteed — see below).

- **Description**: One-LLM-call solution. Compiler receives (a) the BDD stanzas, (b) the current ARIA snapshot text, and (c) explicit instructions: "If — and only if — the `target_component` for a step corresponds to a role/name pair that appears verbatim in `<live_aria_tree>`, emit `aria_role` and `aria_name`. If no verbatim match, leave both `null`. Do not paraphrase names."
- **Pros**:
  - Lower latency — no extra pass.
  - Compiler already has ARIA context for other decisions (`target_element_types` selection benefits from it).
- **Cons**:
  - **Blocked by CON-3** — `ac_parser_node` runs *before* `login_node`. At compile time there is no live page and no ARIA snapshot to inject. The task's LangGraph node graph in `systemPatterns.md` is unambiguous:
    ```
    ac_parser_node → setup_role_node → login_node → planner_node ...
    ```
    The compiler would have to run on a **stale / prior-run** ARIA tree or a **synthetic** one — both violate REQ-4 ("must not be hallucinated"). A stale tree is worse than no tree: it produces confidently-wrong `aria_name` values.
  - **LLM discipline is fragile** — even with strong prompt hardening (per `systemPatterns.md` "Prompt Hardening Standards"), instructing an LLM to "emit X iff verbatim match, else null" is a well-known weak spot; LLMs paraphrase silently. Every hallucination shows up as a broken `get_by_role` locator at runtime.
  - **Couples compiler to ARIA introspection** — the compiler prompt grows longer, more brittle, and harder to audit. Prompt-audit checklist compliance gets harder.
  - **Token cost** — full ARIA snapshots run 3–8 KB per step; adding them to every AC parse balloons parser cost.
- **Technical Fit**: **Low** — the "no live page at parse time" constraint is structural.
- **Complexity**: Medium (prompt engineering + eval harness).
- **Scalability**: Low — every future ARIA-derived field would demand the same fragile prompt discipline.

#### Option 2B: **Post-compilation Python enrichment pass** (deterministic matcher)

After the compiler emits `TestPlan`, a new function `enrich_test_plan_with_aria(page, plan) -> TestPlan` walks each step, calls `page.accessibility.snapshot()`, and does a deterministic match `target_component` → `(role, name)` pairs in the tree.

- **Description**: Two-stage: (1) compiler emits `TestPlan` **without** `aria_role`/`aria_name`; (2) a Python pass, invoked **just-in-time before the planner runs each step** (or as a batch pass in `planner_node` init), populates the fields from the live ARIA tree.
- **Pros**:
  - **Deterministic** — pure code path, no LLM in the loop for the enrichment step. Zero hallucination risk.
  - **Uses the actual live page** — `page.accessibility.snapshot()` is available in the planner/executor layer (post-`login_node`), which is exactly where we need the data.
  - **Testable** — unit tests can feed synthetic ARIA trees and assert matches.
  - **Cheap** — no extra LLM tokens.
  - **Composable** — the same matcher can service `A11yLocatorResolver` at resolve time too, giving one enrichment mechanism.
- **Cons**:
  - Matching logic must be written (`target_component: "Save button"` → `role="button"` + `name="Save"`). Not trivial but tractable — `target_component` strings are already reasonably structured in existing tests.
  - Enrichment can happen **at earliest** post-login. That means `TestPlanStep.aria_role`/`aria_name` are populated *lazily* — the LangGraph node graph is unchanged, but the fields transition from `None` → populated between `login_node` and `planner_node`. This is a **state-mutation nuance** callers must respect (the planner should not persist the plan back to Jira mid-run with the enrichment already applied).
  - Adds a code path (matcher) that needs its own error handling — if match fails, `aria_role=None` (which then triggers `"selector_only_legacy"` in Decision 1 — a clean fall-through).
- **Technical Fit**: **High** — fits the LangGraph node graph and CON-3 exactly.
- **Complexity**: Medium — matcher logic + placement decision.
- **Scalability**: **High** — the matcher becomes the canonical `target_component → ARIA` translator; future ARIA-derived fields plug in beside it.

#### Option 2C: **On-demand enrichment inside `A11yLocatorResolver` itself** (lazy, per-action)

Skip populating `TestPlanStep.aria_role`/`aria_name` altogether. Instead, when the resolver runs, if the step has no `aria_role`, it snapshots the ARIA tree *itself* and tries to match `target_component` on the fly.

- **Description**: Effectively "Option 2B, but inside the resolver, executed once per action instead of once per step."
- **Pros**:
  - No new `TestPlan` fields; smaller schema churn.
  - Enrichment always uses the **freshest** ARIA tree (post-navigation, post-render).
  - Legacy resolver behavior is preserved via the same fall-through path.
- **Cons**:
  - **Duplicated work** — the ARIA snapshot is fetched per-action; a step often executes multiple actions, so the same tree gets snapshotted 3–5×.
  - **AC-VERIFY-2 says the AC parser is responsible** — "AC parser propagates `aria_role` and `aria_name`". This option puts the responsibility elsewhere, semantically violating the acceptance criterion.
  - **Frontend copilot sidebar** (`CopilotSidebar.tsx`) shows step progress; the copilot could surface the enriched `aria_role`/`aria_name` to humans reviewing the plan. This is lost if enrichment is invisible to the plan model.
  - **Hard to audit** — the resolution_path becomes opaque: was `"a11y_direct"` chosen because the parser found a match, or because the resolver did? Distinguishes matter for benchmarking.
- **Technical Fit**: Medium — works, but decouples enrichment from the plan.
- **Complexity**: Low.
- **Scalability**: Low — encourages "just do it at resolve time" for every future ARIA-derived field, punishing observability.

### Evaluation Matrix — Decision 2

| Criterion | 2A in-prompt | 2B post-compile Python pass | 2C on-demand in resolver |
|-----------|--------------|-------------------------------|---------------------------|
| Compatible with node graph (`ac_parser` runs pre-login) | **No** | **Yes** | **Yes** |
| Deterministic (no LLM hallucination) | **No** | **Yes** | **Yes** |
| Satisfies AC-VERIFY-2 ("AC parser propagates") | Partially | **Yes** | No |
| Latency added per parse | Low (~0) | Zero at parse time (moved) | Zero at parse time (moved) |
| Latency added per action | Zero | Zero (populated once per step) | **~50–150 ms** (re-snapshot per action) |
| Token cost | **High** (ARIA in every parse) | Zero | Zero |
| Testability | Low (LLM eval harness) | **High** (unit tests) | High |
| Auditability (`resolution_path` clarity) | High | **High** | Low |
| Frontend / copilot visibility of enrichment | High | **High** | **Low** |
| Reversibility (feature flag) | Medium (prompt is one entity) | **High** (skip the pass) | High |

### Chosen: **Option 2B — Post-compilation Python enrichment pass**

#### Rationale

- **Option 2A is structurally impossible** given the LangGraph node graph: at `ac_parser_node` time there is no live browser (CON-3). Injecting a stale or synthetic ARIA tree into the compiler prompt is exactly the hallucination surface REQ-4 forbids. This alone rules out 2A.
- **Option 2C** works but pushes responsibility away from the AC parser (violating AC-VERIFY-2 semantically), duplicates work, and hurts observability.
- **Option 2B** — a small, testable, deterministic Python pass invoked in `planner_node` on the first iteration post-login — cleanly slots into the node graph without changing it, keeps enrichment attributable to the plan (so the copilot sidebar and audit reports can display it), and composes with Decision 1's resolver (the resolver reads populated `aria_role`/`aria_name`; if enrichment failed to find a match, it stays `None` and the resolver takes the `"selector_only_legacy"` branch — clean fall-through, no new failure modes).

#### Trade-offs Accepted

- **Lazy-populated fields**: `TestPlanStep.aria_role` / `aria_name` are `None` at parse time and populated later. Documented in the schema field descriptions and in `systemPatterns.md`. No downstream consumer today assumes these fields exist, so backward compatibility is preserved.
- **Matcher is a new code path**: Ships with unit tests, telemetry (`aria_enrichment_hit_rate` metric), and a feature flag (`A11Y_ENRICHMENT_ENABLED`, default `True` after benchmark validation).
- **Enrichment lives adjacent to the parser** despite running post-login: the *function* is defined in `backend/engine/ac_parser.py` (or a sibling `backend/engine/ac_aria_enricher.py`) so future readers find it next to the parser; it's *invoked* from `planner_node` init. This mirrors the existing pattern of `ac_enricher.py` (`ac_parser.py` imports `enrich_ac_text` from `ac_enricher`).

#### Implementation Guidelines

1. **New module**: `backend/engine/ac_aria_enricher.py` (name mirrors existing `backend/engine/ac_enricher.py`).
2. **Public function**:
   ```python
   async def enrich_test_plan_with_aria(
       page: Page,
       plan: TestPlan,
   ) -> TestPlan:
       """Populate step.aria_role / step.aria_name for every step whose
       target_component deterministically matches an ARIA node."""
   ```
3. **Matching algorithm** (deterministic, no LLM):
   a. Snapshot ARIA tree once via `page.accessibility.snapshot()` (reuse `backend/engine/a11y_discovery.capture_a11y_snapshot`).
   b. For each `step`: intersect `step.target_element_types` (already at `schemas.py:244`) with ARIA nodes' `role`; among the survivors, compute a normalized-string similarity between `step.target_component` and each candidate node's `name` (case-fold, strip punctuation, token-Jaccard — same technique as FEAT-071's `Split-Execution Local Coordinate Resolution`).
   c. If top match score ≥ threshold (e.g., 0.7) AND second-best is materially lower (Δ ≥ 0.15) → populate `aria_role`/`aria_name`. Otherwise leave both `None`.
   d. **NEVER** paraphrase; `aria_name` is copied verbatim from the ARIA node.
4. **Invocation site**: `planner_node`, once per run, on first entry after `login_node` completes. Store enriched plan back to `VQAState.test_plan`.
5. **Schema update** (`schemas.py`):
   ```python
   aria_role: Optional[str] = Field(None, description="ARIA role for get_by_role() — populated post-login by ac_aria_enricher, NEVER hallucinated.")
   aria_name: Optional[str] = Field(None, description="ARIA accessible name — verbatim from live tree, or None.")
   ```
6. **Telemetry**: per-run counter `aria_enrichment_hit_rate` = `sum(step.aria_role is not None) / len(plan.steps)`; log at INFO after enrichment. Emit into the reporter for the analytics dashboard.
7. **Feature flag**: `settings.a11y_enrichment_enabled` (default off during shadow mode; on after AC-VERIFY-9 benchmarks confirm no regression).
8. **Tests**: `tests/backend/engine/test_ac_aria_enricher.py` — synthetic `TestPlan` + synthetic ARIA snapshot; assert (a) exact match hit, (b) fuzzy match hit, (c) ambiguous (Δ too small) → `None`, (d) no candidate role → `None`, (e) empty tree → all `None`.
9. **`ac_parser.py` unchanged** except for the new field defaults on `TestPlanStep` (which flow through Pydantic validation for free).

---

## Cross-Decision Interaction (why Q3 and Q2 belong in one doc)

- Decision 2 produces `aria_role`/`aria_name` on `TestPlanStep`; Decision 1 consumes them. If Decision 2 chose 2C (resolver-side enrichment) it would collapse both concerns into `A11yLocatorResolver`. Choosing 2B keeps them cleanly separated: **enrichment is deterministic matching (engine layer, mostly pure data-shape logic); resolution is a live probe against `page.get_by_role()` (browser layer)**. This mirrors how FEAT-037 kept `mark_id` mapping (data shape) separate from vision-LLM invocation (mechanism).
- Both decisions expose the same feature flag *pattern* (`A11Y_ENRICHMENT_ENABLED` + `A11Y_RESOLVER_ENABLED`) so operators can enable enrichment for observation (shadow mode) before flipping the resolver on. This is the reversibility NFR-reversible.

---

## Observability Architecture

The feature adds one new mechanism-module (`backend/browser/a11y_resolver.py`) and one new engine helper (`backend/engine/ac_aria_enricher.py`). Both must be observable through the project's existing structured logging + audit-trail conventions; there is **no external observability platform to add** (vQA logs to stdout consumed by Docker + emits per-run JSON reports to S3).

### Logging

- **Library**: Python `logging` module (existing conventions across `backend/`), all messages structured (key=value or key-prefixed idiom, e.g. the `CV_FALLBACK_GATE:`, `CV_FALLBACK_RESOLVE:` idiom in `cv_resolver.py`).
- **Prefixes** (new):
  - `A11Y_ENRICH:` — enrichment pass (INFO on hit, DEBUG on skip, WARN on snapshot error).
  - `A11Y_RESOLVER_BRANCH:` — branch selection (INFO).
  - `A11Y_RESOLVER_FALLBACK:` — probe failure / not visible (WARN with reason).
- **Log levels**: default `LOG_LEVEL=info` (existing env var). All new logs respect the standard.
- **PII**: none. `aria_name` values are UI labels ("Save", "Submit All"), not user data.

### Metrics (audit-trail JSON, reporter-consumed)

Added to `VQAState` and surfaced in the per-run report:

| Metric | Cardinality | Purpose |
|--------|-------------|---------|
| `aria_enrichment_hit_rate` | per run | Fraction of `TestPlanStep`s that got `aria_role` populated |
| `resolution_path_counts` | per run | Dict: `{"a11y_direct": N, "selector_fallback": N, "selector_only_legacy": N}` |
| `a11y_probe_exceptions_total` | per run | Number of times the probe raised (fell into WARN + selector fallback) |
| `a11y_resolver_latency_ms_p50/p95` | per run | Per-action resolver overhead (validates NFR-perf) |

### Configuration (env vars, per 12-Factor guiding principle)

| Variable | Purpose | Default |
|----------|---------|---------|
| `A11Y_ENRICHMENT_ENABLED` | Turn on post-compile ARIA enrichment (Decision 2) | `false` initially → `true` post-bench |
| `A11Y_RESOLVER_ENABLED` | Turn on `A11yLocatorResolver` in `executor.py` (Decision 1) | `false` initially → `true` post-bench |
| `A11Y_PROBE_TIMEOUT_MS` | `is_visible()` timeout on branch 1 | `1500` |
| `A11Y_ENRICH_MATCH_THRESHOLD` | Jaccard similarity floor for enrichment match | `0.7` |
| `A11Y_ENRICH_MATCH_MARGIN` | Δ between top and 2nd match required | `0.15` |

Two-flag shadow-mode plan:
1. Ship with both flags `false` — code merged, no behavior change.
2. Enable `A11Y_ENRICHMENT_ENABLED=true` only — populate fields, don't use them; measure `aria_enrichment_hit_rate` on benchmark runs.
3. Enable `A11Y_RESOLVER_ENABLED=true` — turn on the resolver; measure pass-rate delta vs the enrichment-only run.
4. Bake defaults to `true` after two consecutive weekly benchmarks show flake reduction with no regression.

---

## Validation Checklist

- [x] Meets all system requirements (REQ-1 through REQ-5 addressed in guidelines and cross-decision section).
- [x] Respects technical constraints (CON-1 through CON-5 — see Decision 1 Rationale for CON-1 & CON-5; Decision 2 Rationale for CON-3).
- [x] Addresses non-functional requirements (NFR-perf via `A11Y_PROBE_TIMEOUT_MS`; NFR-flake via `resolution_path_counts` benchmark; NFR-obs via structured logs; NFR-reversible via two feature flags).
- [x] Technically feasible with current stack (Playwright's `page.accessibility.snapshot()` + `page.get_by_role()` are the sole Playwright APIs added; both already used elsewhere in the codebase).
- [x] Risks identified and acceptable (see Risk Assessment).
- [x] Complies with Guiding Principles in `systemPatterns.md` (Semantic Locators First — operationalized; Multimodal Grounding — unchanged; Failure Diary Pattern — resolver fall-throughs feed it; 12-Factor — env-var flags).
- [x] Respects established patterns in `systemPatterns.md` (FEAT-037 module-location precedent, prompt-hardening for the *unchanged* compiler prompt — 2A rejected specifically because it would violate the Prompt Audit Checklist standard).
- [x] Observability architecture defined (see Observability section).
- [x] Trace context propagation across service boundaries — N/A (single-process Python service; existing per-run `run_id` correlation is retained; new logs include `run_id` when available).
- [x] Logging strategy consistent with existing `CV_FALLBACK_*` prefix idiom.
- [x] Metrics strategy follows existing per-run audit-report convention.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ARIA snapshot at `planner_node` post-login returns empty for auth-gated SPAs | Medium | Medium | Enrichment falls back to `aria_role=None` → resolver takes `"selector_only_legacy"`; degrades to current behavior. Telemetry `aria_enrichment_hit_rate` will surface this and let us tune the invocation timing (e.g., post first navigation instead of post-login). |
| Fuzzy matcher assigns wrong `aria_name` (silent hallucination-equivalent) | Low-Medium | High | Threshold + margin gates (`A11Y_ENRICH_MATCH_THRESHOLD` / `_MARGIN`); on a match, `aria_name` is copied **verbatim** from the ARIA tree — never paraphrased. Unit tests cover ambiguous cases. Shadow-mode phase measures divergence from selector-only baseline before enabling the resolver. |
| `page.get_by_role(aria_role, name=aria_name)` throws a Playwright timeout on branch 1 in an unexpected way | Medium | Low | `try/except Exception` around the probe (AC-ERROR-1); WARN log, fall through to Branch 2. Never raises to LangGraph. Mirrors `CvFallbackResolver.resolve()`'s exception hygiene. |
| Latency budget blown when ARIA snapshot is slow on huge pages | Low | Medium | Enrichment runs **once per run** (not per action), so the cost is amortized. Reuse the existing `a11y_discovery.capture_a11y_snapshot` which already has an exception guard. Add a per-invocation timing log to detect regressions. |
| Feature is enabled on a product with sparse ARIA (custom PrimeNG components without proper roles) | Medium | Low | Enrichment yields low hit rate → resolver takes `"selector_only_legacy"` for those steps → **exact today behavior**. Zero-regression by construction. |
| `A11yLocatorResolver` imports `_resolve_locator` from `executor.py`, creating a circular import risk if `executor` also imports the resolver | Low | Medium | Import `_resolve_locator` lazily inside the resolver method (`from backend.engine.executor import _resolve_locator` inside the fall-through branch). Same defensive pattern used elsewhere in the codebase (e.g., `ac_parser._broadcast_pre_parse_guidance_required` imports `routes` lazily). Alternatively, extract `_resolve_locator` to `backend/browser/legacy_resolver.py` in a follow-up refactor. |

---

## Next Steps

1. **AC-VERIFY-2 phase**: Add `aria_role` / `aria_name` optional fields to `TestPlanStep` in `schemas.py`; add `backend/engine/ac_aria_enricher.py` with the deterministic matcher; wire invocation into `planner_node`. Ship behind `A11Y_ENRICHMENT_ENABLED=false`.
2. **AC-VERIFY-3 through AC-VERIFY-6 phase**: Create `backend/browser/a11y_resolver.py` with the three-branch `resolve` method; wire into `executor.py:503` behind `A11Y_RESOLVER_ENABLED=false`.
3. **AC-VERIFY-9 verification**: Run `benchmark_pipeline.py --full` with both flags off — bit-for-bit parity confirmed. Then enable enrichment only (shadow), then enable resolver.
4. **AC-ERROR-1 verification**: Add unit tests forcing `page.get_by_role` to raise; assert WARN log + selector fallback + no exception propagates.
5. **Reporter update**: Surface `aria_enrichment_hit_rate` and `resolution_path_counts` on the per-run HTML report and analytics dashboard.

---

ARCHITECTURE CREATIVE COMPLETE
Document: memory-bank/creative/accessibility-tree-grounding-architecture.md
Decision 1: `A11yLocatorResolver` lives at `backend/browser/a11y_resolver.py` (mirrors FEAT-037 `cv_resolver.py` precedent).
Decision 2: ARIA enrichment is a **post-compilation deterministic Python pass** (`backend/engine/ac_aria_enricher.py`) invoked in `planner_node` post-login — not an in-prompt LLM concern (the compiler has no live page at parse time).

NEW_TERMS_INTRODUCED:
- `resolution_path` — the string label (`"a11y_direct" | "selector_fallback" | "selector_only_legacy"`) returned by `A11yLocatorResolver.resolve()` and appended to each `ExecutionStep` for audit.
- `aria_enrichment_hit_rate` — per-run telemetry: fraction of steps whose `aria_role` was populated by the deterministic matcher.
- `shadow-mode` (two-flag) — enable enrichment without the resolver first, so `aria_role`/`aria_name` values can be validated against a still-legacy resolution path before the resolver is turned on.
