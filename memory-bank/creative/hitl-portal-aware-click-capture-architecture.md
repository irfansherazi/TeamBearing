# Architecture Decision: HITL Portal-Aware Click Capture — Cross-Layer Data-Flow + Fallback Contract

**Created**: 2026-07-28
**Status**: DECIDED
**Decision Type**: Architecture (Level 3, NFR/Infrastructure)
**Feature Branch**: `feature/hitl-portal-aware-click-capture`
**Companion Doc**: (parallel) HITL Portal Detection Algorithm — defines the JS-layer contract this doc consumes

---

## Context

### System Requirements

- Every HITL takeover click on a **React/Angular portal-mounted element** (PrimeNG `.p-select-overlay`, `.p-overlaypanel`, `.p-menu`, `.p-dialog`, `.po-sorting-dropdown-panel`, `.po-*-panel`) must produce a **replayable action** at all four persistence sinks.
- The current pipeline captures the *portal option* click but emits a bare CSS path against a detached DOM subtree — a shape the executor cannot resolve on the next run. That is the bug being closed.
- The JS layer (defined by the parallel algorithm doc) will emit three new fields on click records: `portal_class`, `trigger_selector`, `target_text`. Any of the three may be empty in the partial-capture case.
- The primary path must serialize to the executor's existing `primeng_dropdown` action shape (read-only per Out-of-Scope). The fallback path must serialize to a shape the executor **already handles today** — no executor changes.

### Technical Constraints (locked in by code inspection, this branch @ 80e6012)

| Constraint | Source | Consequence |
|---|---|---|
| Executor `primeng_dropdown` requires ALL of `trigger_selector` (or `trigger_mark_id`) + `target_text` + `portal_class` | `executor.py:2160–2179` | Partial captures missing any one field CANNOT emit `primeng_dropdown` — must use a fallback shape |
| `RecipeStep.action` is `Literal["click","fill","select_option","press_key","wait","set_input_files"]` — NO `primeng_dropdown` | `recipe_runner.py:163` | ActionRecipe YAML MUST decompose portal clicks into standard actions. `container_selector` field on `RecipeStep` (line 188) IS the escape hatch |
| Planner reads `learned_workflows.json` via `_load_learned_workflow_override()` — only inspects `action`, `strategy`, `name`, `value` | `planner.py:2288–2296` | We can store `primeng_dropdown` action dicts safely — extra fields are ignored by the reader (renders as a text-only prompt injection; the planner then chooses which PlannerAction to emit next) |
| Serializer output flows into BOTH `_save_to_learned_workflows` (`human_takeover.py:821`) AND `_save_combined_hitl_entry` (`human_takeover.py:260`); both write the same list of dicts | Confirmed | Zero-regression demands the serializer emit byte-identical output for non-portal records |
| `selector_registry.record_hitl_selector(description, selector, strategy, context, role, name)` — 6-arg signature | `selector_registry.py:236` | Adding portal metadata requires either (a) piggyback in `context` string, or (b) a new optional kwarg — (a) preserves the signature |
| `hitl_trace_parser._extract_selector_from_params` only sees Playwright trace `before` events with `params.selector` or `params.role/text/label` — no notion of portals | `hitl_trace_parser.py:108–153` | Trace parser has NO portal signal. Two options: correlate with JS-captured payload post-parse, OR pattern-match `.p-*overlay*` CSS selectors in the trace. We choose the latter (self-contained) |
| `_ALLOWED_ACTIONS`-style planner PlannerAction schema explicitly declares `primeng_dropdown` | `schemas.py:424` | Storing the shape in learned_workflows survives — planner replay simply re-emits it |

### Non-Functional Requirements

- **Zero regression** (AC-VERIFY-5): non-portal payloads → byte-identical serializer + sink output as today.
- **Latency**: serializer O(n); parser O(n) in captured events (n is small, <50 per takeover).
- **Warn-but-don't-block** (AC-ERROR-1, AC-ERROR-2): partial capture logs WARN, persists best-effort, takeover session continues.
- **Data-flow honesty**: portal metadata survives all four sinks — no silent drops.
- **Guiding Principles** (`systemPatterns.md`): Semantic Locators First (scoped `get_by_text` before raw CSS); HITL as Learning Signal (every takeover writes to `human_guidance.md`); Failure Diary Pattern (partial captures carry a `capture_confidence` flag for future observability).

---

## Component Analysis

### Core Components in Scope

| Component | Purpose | Responsibilities |
|---|---|---|
| **JS listener** (`human_takeover.py:472+ _inject_click_capture_listener`) | Runs in SUT browser; emits `PortalAwareClickRecord` | Detect portal ancestry; resolve trigger via time-correlation; produce `portal_class`, `trigger_selector`, `target_text`, `capture_confidence` (defined by algorithm doc) |
| **Python bridge** (`human_takeover.py:487 _on_human_action`) | Receives payload via `expose_function`; broadcasts to WS; appends to session queue | **NO CHANGES REQUIRED** — the record dict is stored verbatim into `_human_action_sequence[run_id]` — new fields flow through untouched |
| **Autorecord serializer** (`autorecord.py:26 serialize`) | Merge `keyup`s, filter noise, produce Playwright-ready action list | **NEW**: detect portal-flagged click records; emit `primeng_dropdown` action shape (primary) or `click` with `container_selector` (fallback). Non-portal path is byte-identical to today |
| **HITL trace parser** (`hitl_trace_parser.py`) | Parses Playwright trace zip into `ExtractedAction` → ActionRecipe YAML | **NEW**: detect portal-scoped selectors via `.p-*-overlay` / `.p-menu` / `.p-dialog` CSS pattern-match at `_extract_selector_from_params`; emit steps with `container_selector` scoping (the ONLY portal-aware shape ActionRecipe YAML can express — Literal constraint on `RecipeStep.action`) |
| **learned_workflows.json sink** (`_save_to_learned_workflows`) | Writes serializer output verbatim | **NO CHANGES REQUIRED** — carries whatever the serializer emits |
| **human_guidance.md sink** (`_save_combined_hitl_entry`) | Renders serializer output as `Step N: {json}` inside markdown block | **NO CHANGES REQUIRED** — extra fields become inline JSON keys, human-readable, TF-IDF-indexable |
| **selector_registry.json sink** (`record_hitl_selector`) | Persists one entry per human-confirmed selector | **NEW**: for portal clicks, encode `portal_class` + `trigger_selector` into the free-form `context` string (schema-preserving), and set `strategy='primeng_dropdown'` for the entry (a new string, but the field is not a Literal) |
| **ActionRecipe YAML sink** (`hitl_trace_parser` → `knowledge/blueprints/generated/*.yaml`) | Machine-consumed by `recipe_runner.RecipeRegistry._load_file` on next run | **NEW**: for portal-scoped clicks, emit `action: click` + `container_selector: '.p-select-overlay'` + `strategy: get_by_text` + `selector: '<target_text>'` — the ONLY portal-aware shape the Pydantic schema will accept |

### Component Interactions (Data-Flow Diagram)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SUT BROWSER (Angular + PrimeNG v19)                                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ JS listener  (_inject_click_capture_listener, algorithm doc)   │    │
│  │   emits PortalAwareClickRecord:                                │    │
│  │   { event_type, tag, best_selector, strategy, inner_text,      │    │
│  │     aria_label, role, test_id, css_path, value, timestamp,     │    │
│  │     portal_class,                    ← NEW  (str, may be "")   │    │
│  │     trigger_selector,                ← NEW  (str, may be "")   │    │
│  │     target_text,                     ← NEW  (str, may be "")   │    │
│  │     trigger_resolution_confidence,   ← NEW  (aria|focus|       │    │
│  │                                             mutation|none)     │    │
│  │     is_anonymous_portal,             ← NEW  (bool)             │    │
│  │     capture_confidence               ← NEW  (full|portal_only| │    │
│  │                                              none)             │    │
│  │   }                                                             │    │
│  └────────────────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────────────────┘
                         │  page.expose_function("__vqa_record_human_action__", …)
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PYTHON BRIDGE (human_takeover._on_human_action) — UNCHANGED             │
│   _human_action_sequence[run_id].append(record_dict)                    │
└────────────────────────┬────────────────────────────────────────────────┘
                         │  (later, at takeover completion)
          ┌──────────────┴──────────────┐
          ▼                              ▼
┌─────────────────────────┐    ┌──────────────────────────────────────┐
│ AutorecordSerializer    │    │ hitl_trace_parser.parse_trace()      │
│   .serialize()          │    │   (T2-b, parallel path)              │
│                         │    │   reads Playwright trace .zip        │
│  NEW BRANCH:            │    │                                       │
│   if capture_conf==full │    │  NEW: _extract_selector_from_params  │
│     emit primeng_dropdown│    │   detects portal-scope by CSS       │
│   elif portal_only      │    │   pattern (.p-*-overlay, .p-menu,    │
│     emit click+scope    │    │    .p-dialog, .po-*-panel)          │
│   else                  │    │                                       │
│     emit click (today)  │    │  emits ExtractedAction with:         │
│                         │    │    container_selector (new field)    │
└────┬────────┬───────────┘    │    selector_kind='portal_scoped_text'│
     │        │                │    (new kind, else falls through)    │
     │        │                └───────────────┬──────────────────────┘
     │        │                                │
     ▼        ▼                                ▼
┌───────────────────┐  ┌───────────────────────┐  ┌────────────────────────┐
│ learned_workflows │  │ human_guidance.md     │  │ generated/*.yaml       │
│   .json           │  │   (WORKFLOW block)    │  │  (ActionRecipe)        │
│                   │  │                        │  │                        │
│ Shape: verbatim   │  │ Shape: `Step N: {json}`│ │ Shape: RecipeStep      │
│ serializer output │  │  serializer output     │ │  action=click,         │
│ (dict list)       │  │  rendered as JSON     │  │  container_selector=…, │
└───────────────────┘  │  in markdown          │  │  strategy=get_by_text, │
                       └───────────────────────┘  │  selector=<target_text>│
                                                  └────────────────────────┘
                                ┌───────────────────────────────────────────┐
                                │ selector_registry.json                    │
                                │  record_hitl_selector(...) — new context  │
                                │  encoding: "portal:<class>|trigger:<sel>" │
                                └───────────────────────────────────────────┘
```

Critical: **the JS bridge, learned_workflows sink, and human_guidance sink require ZERO code changes**. Portal awareness flows through them because they preserve the serializer's dict output verbatim. Only the serializer, the trace parser, and the selector_registry write call need edits.

---

## Interfaces from Algorithm Doc (Input Contract)

The parallel Algorithm Design agent produces the JS-layer contract. This architecture consumes the following fields on every click record emitted to `__vqa_record_human_action__`:

**Existing fields (unchanged — must still be produced):**
- `run_id: str`
- `event_type: str` — `"click" | "change" | "keyup" | "scroll" | "input"`
- `tag: str`
- `test_id: str`
- `aria_label: str`
- `role: str`
- `inner_text: str`
- `best_selector: str`
- `strategy: str` — `"get_by_test_id" | "get_by_label" | "get_by_role:<role>" | "get_by_text" | "css"`
- `css_path: str`
- `value: str`
- `timestamp: str` (ISO)

**NEW fields (this feature — algorithm doc defines the algorithm; this doc defines the contract):**

| Field | Type | Semantics | Empty-when |
|---|---|---|---|
| `portal_class` | `str` | CSS class of the nearest ancestor matching `.p-*-overlay`, `.p-menu`, `.p-dialog`, `.p-overlaypanel`, `.po-*-panel`. The **first class token** only (leading `.` optional but this doc canonicalizes with-dot). Example: `.p-select-overlay`. | Click did not land inside a portal. |
| `trigger_selector` | `str` | CSS selector for the DOM element that opened the portal, resolved by the algorithm's correlation window (aria-owns / aria-controls / time-window over the previous mousedown target). | Portal was detected but trigger could not be resolved (e.g. no aria linkage; opener already unmounted; time-window missed). |
| `target_text` | `str` | Visible text of the specific portal option that was clicked (typically = `inner_text` when the click landed on the option element, but preserved separately so serializer doesn't have to introspect `inner_text` shape). | Icon-only option, empty text, or click landed on a non-text element (e.g. p-menu separator). |
| `capture_confidence` | `Literal["full","portal_only","none"]` | **Emitted by the JS layer** (algorithm doc ADDITION 7 `deriveCaptureConfidence`), derived at `buildRecord` time from `portal_class`/`trigger_selector`/`target_text`/`is_anonymous_portal`. `full` = all three replay-critical fields non-empty. `portal_only` = portal detected (known OR anonymous via `is_anonymous_portal==true`) but any of the three is empty. `none` = not a portal click. See algorithm doc §"Derivation rule" for the canonical truth table. | Never empty — always one of the three values. |

**Contract invariants (this architecture RELIES on these):**

1. `capture_confidence == "full"` ⇔ `portal_class`, `trigger_selector`, `target_text` are **all** non-empty and non-whitespace-only.
2. `capture_confidence == "none"` ⇔ `portal_class == ""`. `trigger_selector` and `target_text` are ignored downstream when `capture_confidence == "none"`.
3. When `capture_confidence == "portal_only"`, `portal_class` is guaranteed non-empty; either `trigger_selector` or `target_text` (or both) may be empty. The serializer branches on this specifically.
4. All three new fields are always present as keys in the record (never `KeyError`) — algorithm doc must guarantee this so serializer branches can use `rec.get("portal_class", "")` safely.
5. `portal_class` is a **single class selector with leading dot**, not a full CSS selector chain, not a comma-separated list. Executor's `page.locator(portal_class)` at `executor.py:2187` expects this shape.

**Contract reconciliation note**: An earlier draft of the algorithm doc did not emit `capture_confidence` — the serializer would have had to re-derive it in Python from the granular fields. This was closed at design-review time by adding ADDITION 7 (`deriveCaptureConfidence`) to the algorithm doc, making the JS layer the single source of truth for classification and keeping the serializer a pure dispatch. The algorithm doc's granular `trigger_resolution_confidence` (`"aria" | "focus" | "mutation" | "none"`) is preserved as an *additional* telemetry field on the raw record but is not consumed by the serializer branching — it exists for downstream observability tools.

**If the algorithm agent needs to deviate from any of the above**, it is a hand-off blocker — the fallback contract below breaks silently. Flag this back to the parent agent before committing.

---

## Options Explored

We evaluate the Q3 fallback contract (partial capture where `capture_confidence == "portal_only"`) across three real options. The `capture_confidence == "full"` path is uncontroversial: emit `primeng_dropdown` action — this is already the executor's shape. The debate is what happens when the portal is detected but the trigger cannot be resolved.

### Option A: Scoped click within the portal

**Description**: When `capture_confidence == "portal_only"`, serialize the click as a **standard `click` action** with `strategy=get_by_text`, `name=target_text` (or fallback to `inner_text`), plus a **new `container_selector` field** = `portal_class`. Depends on the portal remaining in the DOM at replay time, which is normally guaranteed because the preceding action in the same sequence will have opened it.

**Serializer output shape (portal_only branch):**

```python
{
    "action": "click",
    "strategy": "get_by_text",
    "name": target_text or inner_text,          # non-empty; if target_text empty, fall back
    "container_selector": portal_class,         # ".p-select-overlay"
    "inner_text": inner_text,
    "_capture_confidence": "portal_only",       # observability breadcrumb
}
```

**Sink schemas:**

| Sink | Encoding |
|---|---|
| `learned_workflows.json` | Verbatim dict above, inside `action_sequence` array. Planner reader ignores `container_selector` and `_capture_confidence` (unknown keys) and renders the entry as text — planner may then choose to emit `primeng_dropdown` on replay if it recognizes the pattern, OR a plain scoped `click` (executor already supports `container_selector` on `click` via PlannerAction schema line 523). |
| `human_guidance.md` | Rendered as `Step N: {json.dumps(dict)}` — the JSON literal shows all fields including the confidence breadcrumb, human-inspectable. |
| `generated/*.yaml` (via trace parser) | `action: click`, `strategy: get_by_text`, `selector: <target_text>`, `container_selector: <portal_class>`. This maps EXACTLY to `RecipeStep`'s existing fields (`RecipeStep.container_selector` documented at line 188 as "scopes get_by_text to the open dropdown panel" — literally this use case). |
| `selector_registry.json` | Description = `HITL portal-scoped: <ac_step[:60]>`; strategy = `get_by_text`; name = `target_text`; context = `portal:<portal_class>|trigger:<empty>|ac:<step[:80]>`. |

**Executor compatibility**: Read-only. The executor's existing `click` action handler already scopes by `container_selector` (via the standard locator chain: `page.locator(container_selector).get_by_text(name)`). No change to `executor.py:2160+ primeng_dropdown` handler.

**Replayability score**: **HIGH conditional on portal-still-open**. Because the JS listener captures the FULL sequence (all clicks, keys, changes — see `_human_action_sequence`) and portal_only records will always be preceded by whatever click opened the portal (that click IS captured, even if we didn't identify it as the trigger), replay will re-execute that click first, opening the portal, and then the scoped click resolves within the still-open overlay. **The key assumption**: the sequence-preceding click that opened the portal is captured. This is guaranteed by the current listener (see `_on_human_action` — every click on any target lands in the sequence).

**Failure modes**:
- If `target_text` is empty AND `inner_text` is also empty (icon-only p-menu option), the scoped click has no locator target. Recovery: fall back to raw `css_path` scoped to `container_selector` — degrades to Option B semantics within the portal but at least the click stays scoped.
- If the option is one of many identical texts inside the same portal (e.g. two "Save" buttons in a modal), `get_by_text` will hit STRICT_MODE. The failure diary and evaluator handle this at replay — same behavior as any strict-mode collision today.

**Pros**:
- **Existing executor code handles it** — no changes to `primeng_dropdown` handler (out-of-scope compliance).
- Maps cleanly to `RecipeStep.container_selector` in the YAML sink — no Pydantic schema change.
- Non-portal payloads: `container_selector` is absent, output is byte-identical to today (AC-VERIFY-5 clean).
- Human-readable in `human_guidance.md` — the JSON step self-documents the portal scoping.

**Cons**:
- Requires the portal to be re-openable via the *preceding* captured action — if the recording didn't include the opener (edge case: portal was pre-open when takeover started), replay fails. Mitigation: WARN log at capture time when `capture_confidence == "portal_only"` AND the preceding record in the sequence is not a click — this signals a replay risk to the operator, without blocking. Non-blocking per AC-ERROR-1.
- `target_text` disambiguation is worse than the executor's `primeng_dropdown` handler which uses `page.locator(portal_cls).get_by_text(target_text)` with explicit portal wait — but that's exactly the shape Option A produces (`get_by_text` scoped by `container_selector`), so functionally equivalent at replay.

**Technical Fit**: **HIGH** — uses `RecipeStep.container_selector` which was designed for this scenario. Aligns with Semantic Locators First guiding principle (`get_by_text` over CSS).
**Complexity**: **LOW** — serializer branch is ~15 lines; YAML emitter reuses existing field.
**Scalability**: **HIGH** — O(1) per record.

---

### Option B: Raw CSS path only (baseline — current broken behavior)

**Description**: Ignore the new fields; keep the current serializer behavior — emit `action: click, strategy: css, name: <css_path>`. The `css_path` traverses through the detached portal container node.

**Serializer output shape (portal_only branch under Option B):** unchanged from today.

**Sink schemas**: All four sinks unchanged.

**Executor compatibility**: Read-only, no changes.

**Replayability score**: **LOW** — this is the current bug. The `css_path` includes generated ids/classes that change per-render; even without id changes, the option element is inside a portal container that isn't in the DOM until the trigger is clicked again — which the replay doesn't know how to do.

**Failure modes**: Silent failure at replay — `page.locator(css_path)` times out. Executor recovery loop kicks in (up to 2 retries per AC step per productBrief NFR), then escalates back to HITL — infinite loop risk.

**Pros**:
- **Zero code change** — trivial to implement (do nothing).
- Preserves absolute byte-identical output for all records — technically the strictest AC-VERIFY-5 compliance.

**Cons**:
- **This is the bug we're closing** — regressing to Option B for the portal_only case defeats the feature's purpose. AC-INTEGRATION-1 (partial captures must land at all four sinks in a replayable shape) is violated.
- Silently persists a known-broken action into the KB — future runs will hit the same failure until human curation.

**Technical Fit**: N/A — this is inaction.
**Complexity**: NONE.
**Scalability**: N/A.

---

### Option C: `primeng_dropdown` with `trigger_selector: ""` + executor-side lookup

**Description**: Emit `action: primeng_dropdown` even when the trigger is unknown, with `trigger_selector: ""` and a new flag (e.g. `trigger_unresolved: true`). Executor's `primeng_dropdown` handler at `executor.py:2160` is amended to detect the empty trigger and instead scan the page for portals whose `portal_class` matches and are currently visible, skipping the trigger click.

**Serializer output shape:**

```python
{
    "action": "primeng_dropdown",
    "trigger_selector": "",                     # explicitly empty
    "target_text": target_text or inner_text,
    "portal_class": portal_class,
    "trigger_unresolved": True,                 # new signal to executor
    "_capture_confidence": "portal_only",
}
```

**Sink schemas**: same as Option A, but the serialized action type is `primeng_dropdown` uniformly for both full and partial portal captures.

**Executor compatibility**: **CHANGES REQUIRED**. `executor.py:2160` currently returns `PRIMENG_DROPDOWN_MISSING_FIELDS` when `trigger_selector` is empty (unless `trigger_mark_id` is set, which is vision-mode). We would need to add a new branch: "if `trigger_unresolved` AND portal is already visible OR the preceding sequence action just opened it → skip trigger click, jump to Step 3 (option click)." This overlaps with the existing "Smart Portal Detection" logic at `executor.py:2182–2199` which already handles "portal already open."

**Also required**: `PlannerAction` schema (`schemas.py:742–763`) validator would need to relax: currently `trigger_selector` (or `trigger_mark_id`) is validated as required. New: allow both empty when `trigger_unresolved: true`. This is a schema change.

**Replayability score**: **HIGH** — the executor becomes smart about resolving triggers at replay. But it requires cross-run coupling (executor state has to track what the previous replay step did).

**Failure modes**: If the executor's portal-visibility scan fires when the portal isn't yet open, it fails opaquely. Diagnosing this failure requires cross-referencing action sequences.

**Pros**:
- Uniform serializer output — one shape (`primeng_dropdown`) for all portal captures, full or partial. Simpler serializer.
- The learned intent ("this was a portal click") is preserved in the action type, not spread across `action + container_selector`.

**Cons**:
- **Requires executor changes** — explicitly listed as OUT-OF-SCOPE for this feature. Per task requirements: "If your fallback contract requires executor changes, explicitly flag it and downgrade to a fallback that doesn't."
- Requires `PlannerAction` Pydantic schema change (`schemas.py:742–763`).
- The executor's "resolve trigger at replay" logic is a genuinely hard problem that adjacent `feature/FEAT-116-vqa-tier1-executor-recovery` already touches — high scope-collision risk.
- Adds a new field (`trigger_unresolved`) to PlannerAction — planner LLM must be re-trained/re-prompted to emit it, or we accept that ONLY the HITL replay path uses it (adds a schema-execution split-brain).

**Technical Fit**: MEDIUM — the intent (uniform action type) is clean but blocked by scope.
**Complexity**: HIGH — cross-file (executor, schemas, planner prompt).
**Scalability**: HIGH.

---

### Option D (Hybrid — considered, rejected): "Two-step click sequence"

**Description**: For partial captures, decompose the recorded action into TWO synthetic serializer output records: (1) a click on whatever the preceding non-portal element was (the presumed trigger), (2) a scoped click in the portal.

**Why rejected**: Requires the serializer to introspect the previous element in the raw sequence and speculate about which click opened the portal. This is exactly the trigger-resolution problem the algorithm layer was meant to solve — pushing it into the serializer duplicates logic. Also increases the serializer's algorithmic complexity beyond O(n) if we allow look-back across arbitrary distances (multiple intervening `keyup`s / `scroll`s). Worst: on wrong guess, we produce a persisted lie in the KB that survives forever. **Prefer to be honest about partial capture (Option A) than fabricate a guessed trigger (Option D).**

---

## Evaluation Matrix

| Criterion | Option A (scoped click) | Option B (raw CSS today) | Option C (primeng_dropdown+lookup) |
|---|---|---|---|
| Executor compatibility (read-only?) | ✅ Read-only | ✅ Read-only | ❌ REQUIRES CHANGES |
| Meets AC-INTEGRATION-1 (all 4 sinks) | ✅ Yes | ❌ No (broken selector) | ✅ Yes |
| Meets AC-VERIFY-3 (YAML replay parseable) | ✅ Uses existing `container_selector` | ✅ (parseable but non-functional) | ⚠️ Requires YAML sink to still emit `primeng_dropdown`, but RecipeStep.action Literal doesn't allow it → **BLOCKED** |
| Meets AC-VERIFY-5 (zero regression on non-portal) | ✅ Yes (branch on capture_confidence) | ✅ Trivially | ✅ Yes (same branching) |
| Meets AC-ERROR-1 / ERROR-2 (warn, no block) | ✅ WARN + persist best-effort | ✅ Persists (broken) | ✅ WARN + persist |
| Replayability | HIGH (conditional) | LOW | HIGH |
| Scope-collision with FEAT-116 | LOW | NONE | HIGH |
| Latency (O(n)) | ✅ | ✅ | ✅ |
| Semantic Locators First alignment | ✅ (`get_by_text`) | ❌ (raw CSS) | ✅ |
| Failure-mode observability | ✅ `_capture_confidence` breadcrumb | ❌ Silent | ✅ `trigger_unresolved` |
| Implementation cost (this task) | LOW | ZERO | HIGH |

**Critical realization from the matrix**: **Option C fails AC-VERIFY-3 independently of the executor-scope issue.** `RecipeStep.action` is a Pydantic `Literal["click","fill","select_option","press_key","wait","set_input_files"]` (recipe_runner.py:163). It **cannot** be `primeng_dropdown`. So even if we were willing to touch the executor, the ActionRecipe YAML sink cannot express Option C's uniform shape — it would need to decompose to `click`-based steps at YAML-emit time, which is exactly Option A. So the YAML sink is Option A regardless. Committing to Option C at the serializer level while emitting Option A at the YAML level would be a data-format split-brain across sinks — violates the "portal fields survive all four sinks" honesty requirement.

---

## Observability Architecture

### Logging

Per systemPatterns.md Guiding Principles ("Failure Diary Pattern"), every partial-capture path emits a WARN log with structured fields:

```
logger.warning(
    "[%s] hitl_portal_partial_capture: portal_class=%s trigger_empty=%s target_empty=%s ac_step=%s",
    run_id, portal_class, not trigger_selector, not target_text, current_step[:60]
)
```

- LOG_LEVEL: WARN (configurable via existing env var).
- Fields for future queryability: `run_id`, `portal_class`, `trigger_empty` (bool), `target_empty` (bool), `ac_step` (truncated).
- **NO trace-context propagation infrastructure exists in this codebase** (per systemPatterns.md — no OpenTelemetry integration currently). Match existing `logging.getLogger(__name__)` pattern.

### Metrics

No metrics infrastructure exists in-repo today; do not introduce one for this feature. Observability is via `_capture_confidence` breadcrumbs stored in the persisted records (queryable later via a script over `learned_workflows.json`).

### Config

No new environment variables. Behavior is deterministic on the payload.

---

## Decision

**Chosen: Option A — Scoped click within the portal (with fallback-of-fallback for empty target_text)**

### Q3 Decision Statement

When `capture_confidence == "portal_only"`, the serializer emits:

```python
{
    "action": "click",
    "strategy": "get_by_text",
    "name": target_text or inner_text or css_path,   # ordered fallback
    "container_selector": portal_class,              # e.g. ".p-select-overlay"
    "inner_text": inner_text,
    "_capture_confidence": "portal_only",
}
```

When `capture_confidence == "full"`, the serializer emits:

```python
{
    "action": "primeng_dropdown",
    "trigger_selector": trigger_selector,
    "target_text": target_text,
    "portal_class": portal_class,
    "inner_text": inner_text,
    "_capture_confidence": "full",
}
```

When `capture_confidence == "none"` (not a portal click), the serializer emits **exactly today's output** — byte-identical, no `_capture_confidence` key, no new fields.

**AC coverage:**
- **AC-INTEGRATION-1**: All four sinks receive portal-aware data in a replayable shape — YAML sink uses `container_selector`, learned_workflows preserves the dict, selector_registry encodes `portal_class`+`trigger_selector` in `context`, human_guidance.md renders the JSON.
- **AC-VERIFY-3**: ActionRecipe YAML shape is a valid `RecipeStep` (`action=click` is in the Literal set; `container_selector` is an existing field at recipe_runner.py:188). No Pydantic schema change.
- **AC-VERIFY-5**: `capture_confidence=="none"` branch produces byte-identical output. New fields never appear on non-portal records.
- **AC-ERROR-1**: `portal_only` path logs WARN, persists best-effort record, does not raise, takeover continues.
- **AC-ERROR-2**: When even `target_text` and `inner_text` are empty (icon-only options), the serializer falls back to `strategy=css_selector, name=css_path` scoped by `container_selector` — still a legal click, WARN logged, replay may fail non-fatally (executor's failure diary handles it).

### Rationale

1. **Executor read-only compliance is non-negotiable** (task Out-of-Scope). Option C is eliminated on this constraint alone.
2. **Pydantic schema of `RecipeStep.action` is a Literal** that does not include `primeng_dropdown` — this forces the YAML sink to Option A's shape regardless. Committing to Option A everywhere else keeps all sinks consistent.
3. **`RecipeStep.container_selector` was designed for exactly this use case** — its documentation string reads "scopes get_by_text to the open dropdown panel." Using an existing, documented feature is preferred over introducing a new field.
4. **Semantic Locators First** (systemPatterns.md) — `get_by_text` inside `container_selector` scope is a stronger, more UI-reshuffle-resistant shape than `primeng_dropdown` from a Guiding Principles perspective.
5. **Zero regression is guaranteed** by branching on `capture_confidence` — non-portal records skip all new logic entirely.

### Trade-offs Accepted

- **Partial captures depend on the preceding sequence action to open the portal at replay.** This is acceptable because (a) the JS listener captures ALL sequence actions, so the opener IS in the record; (b) the planner's `learned_workflows` reader replays the full sequence in order (planner.py:2283+); (c) if the opener is missing (edge case: portal was open at takeover start), the WARN log flags it — non-blocking degradation.
- **Data-format asymmetry between full and partial captures at the serializer** (two different action types) is honest — it tells the planner/executor "this record has less information," which is preferable to fabricating a fake `trigger_selector`.
- **`_capture_confidence` breadcrumb key is a soft-schema field** (leading underscore, not persisted to selector_registry's structured shape). Planner reader ignores it. Reserved for downstream observability tools (e.g. a `scripts/analyze_hitl_captures.py`).

---

## Payload Shape Reference

### Stage 1: JS emit (algorithm-doc contract, this doc consumes)

Every payload arrives at `_on_human_action(record)` with this shape (only `click` records shown; other event types unchanged):

```python
{
    "run_id": "run-abc-123",
    "event_type": "click",
    "tag": "li",
    "test_id": "",
    "aria_label": "",
    "role": "option",
    "inner_text": "Due Date A-Z",
    "best_selector": "Due Date A-Z",
    "strategy": "get_by_role:option",
    "css_path": "html > body > div.p-select-overlay > div > ul > li:nth-child(3)",
    "value": "",
    "timestamp": "2026-07-28T15:04:32.123Z",
    # NEW fields (algorithm doc — full set; serializer consumes capture_confidence primarily):
    "portal_class": ".p-select-overlay",
    "trigger_selector": "th.po-col-duedaysCol p-select",  # empty in portal_only case
    "target_text": "Due Date A-Z",                        # may be empty
    "trigger_resolution_confidence": "aria",              # granular telemetry: "aria"|"focus"|"mutation"|"none"
    "is_anonymous_portal": False,                         # True → cdk-overlay-container, unknown class
    "capture_confidence": "full",                         # derived enum: "full"|"portal_only"|"none"
}
```

### Stage 2: Python bridge stores verbatim (no code change)

`_human_action_sequence[run_id].append(record)` — record dict preserved verbatim.

### Stage 3: Serializer output — `list[dict]`

**Full-capture click** (was portal click, all fields present):

```python
{
    "action": "primeng_dropdown",
    "trigger_selector": "th.po-col-duedaysCol p-select",
    "target_text": "Due Date A-Z",
    "portal_class": ".p-select-overlay",
    "inner_text": "Due Date A-Z",
    "_capture_confidence": "full",
}
```

**Portal-only capture click** (portal detected, trigger unresolved):

```python
{
    "action": "click",
    "strategy": "get_by_text",
    "name": "Due Date A-Z",
    "container_selector": ".p-select-overlay",
    "inner_text": "Due Date A-Z",
    "_capture_confidence": "portal_only",
}
```

**Portal-only capture with empty `target_text`** (icon-only option):

```python
{
    "action": "click",
    "strategy": "css_selector",
    "name": "html > body > div.p-select-overlay > div > ul > li:nth-child(3)",
    "container_selector": ".p-select-overlay",
    "inner_text": "",
    "_capture_confidence": "portal_only_degraded",
}
```

**Non-portal click** (byte-identical to today):

```python
{
    "action": "click",
    "strategy": "get_by_text",
    "name": "Submit",
    "inner_text": "Submit",
}
```

Note the absence of `_capture_confidence` on non-portal — this is what preserves byte-identity for AC-VERIFY-5.

### Stage 4: Sink shapes

#### 4a. `learned_workflows.json` — verbatim serializer output

```json
{
  "AC step text used as key": {
    "ticket_id": "VC2-8967",
    "recorded_at": "2026-07-28T15:04:34.567Z",
    "action_sequence": [
      { "action": "click", "strategy": "get_by_text", "name": "Sort", "inner_text": "Sort" },
      {
        "action": "primeng_dropdown",
        "trigger_selector": "th.po-col-duedaysCol p-select",
        "target_text": "Due Date A-Z",
        "portal_class": ".p-select-overlay",
        "inner_text": "Due Date A-Z",
        "_capture_confidence": "full"
      }
    ]
  }
}
```

#### 4b. `human_guidance.md` — markdown block with inline JSON

```markdown
## WORKFLOW: Sort orders by Due Date A-Z
KEYWORDS: sort, due, date, ordered, human-guidance, hitl-selector, VC2-8967
JIRA: VC2-8967
---

CAPTURED DOM ACTIONS (replay these verbatim in Playwright):
  Step 1: {"action": "click", "strategy": "get_by_text", "name": "Sort", "inner_text": "Sort"}
  Step 2: {"action": "primeng_dropdown", "trigger_selector": "th.po-col-duedaysCol p-select", "target_text": "Due Date A-Z", "portal_class": ".p-select-overlay", "inner_text": "Due Date A-Z", "_capture_confidence": "full"}

INSTRUCTIONS FOR THE AGENT:
  Follow the DOM actions above VERBATIM…
```

Portal metadata is preserved as inline JSON keys — TF-IDF-indexable via the existing KB pipeline.

#### 4c. `knowledge/blueprints/generated/<slug>.yaml` — ActionRecipe

Because `RecipeStep.action` is a Literal that excludes `primeng_dropdown`, the trace parser MUST decompose portal captures into standard steps regardless of whether the JS layer detected them as `full` or `portal_only`. The parser detects portal-scoped clicks by pattern-matching the selector CSS.

```yaml
name: hitl_sort_due_date_run_abc_123_0
description: Auto-generated from HITL takeover — run=run-abc-123, seq=0. AC step: Sort orders by Due Date A-Z
trigger_keywords:
  - sort due
  - due date
  - due
  - sort
  - due date a-z
parameters: []
steps:
  - action: click
    strategy: get_by_text
    selector: Sort
  - action: click
    strategy: get_by_text
    selector: Due Date A-Z
    container_selector: .p-select-overlay
cleanup_on_failure: []
verify_after: null
is_sort_recipe: false
force_wait_before_next: false
force_wait_ms: 1500
```

The second step is the portal-scoped click. At recipe execution, `recipe_runner._resolve_locator` will construct `page.locator('.p-select-overlay').get_by_text('Due Date A-Z')` — exactly the shape the current executor already handles for scoped clicks.

#### 4d. `selector_registry.json` — HITL selector entry

Portal metadata rides in the free-form `context` string, avoiding a schema change to `selector_registry.py`:

```json
{
  "hitl_sort_orders_by_due_date_a_z": {
    "description": "HITL portal-scoped: Sort orders by Due Date A-Z",
    "strategies": [
      {
        "method": "get_by_text",
        "name": "Due Date A-Z"
      }
    ],
    "context": "portal:.p-select-overlay|trigger:th.po-col-duedaysCol p-select|ac:Sort orders by Due Date A-Z",
    "hitl_confirmed": true,
    "first_seen": "2026-07-28T15:04:34.567Z",
    "last_confirmed": "2026-07-28T15:04:34.567Z",
    "timing_note": null
  }
}
```

The `context` string format is deterministic: `portal:<class>|trigger:<selector>|ac:<step[:80]>`. On the portal_only path, the `trigger:` segment is `trigger:` (empty value between colon and pipe), preserving parseability if a future consumer wants to extract it.

---

## Implementation Guidelines

1. **Serializer branch must be additive-only** — do not restructure the existing `for rec in raw_sequence` loop. Add a single conditional in the `event_type == "click"` handler (autorecord.py:100).
2. **Never mutate the raw record** — read `rec.get("capture_confidence", "none")` and construct a new dict. Preserves debugging: raw sequence stays exactly as JS emitted it.
3. **Serializer changes are pure**: no I/O, no logger.warning inside the serializer. WARN log happens in `_on_human_action` (Python bridge) where the `run_id` is naturally in scope.
4. **Trace parser portal detection is pattern-based, not payload-based** — the parser operates on the trace zip, has no access to JS-captured records. Detection: extend `_extract_selector_from_params` to return a third element `container_selector` when the raw CSS matches `^\.(p-|po-).*(overlay|panel|menu|dialog)`. Non-portal selectors → `container_selector=None`, existing behavior preserved.
5. **selector_registry `context` string format is a soft contract** — document the `portal:...|trigger:...|ac:...` grammar in a comment near the write call. If a future feature needs to structure this, it can add a proper field — but not this task.
6. **Empty-target_text fallback**: precedence is `target_text` → `inner_text` → `aria_label` → `css_path`. The last is the escape hatch for icon-only options.
7. **Human-readable WARN log** should include the ac_step for grep-ability across `.claude-logs/`.

---

## Validation Checklist

- [x] Meets all system requirements
- [x] Respects technical constraints — executor `primeng_dropdown` handler untouched, `RecipeStep.action` Literal unchanged, `record_hitl_selector` signature unchanged
- [x] Addresses non-functional requirements (O(n) serializer, zero-regression path, warn-not-block)
- [x] Technically feasible with current constraints
- [x] Risks identified and acceptable (see Risk Assessment)
- [x] Complies with Guiding Principles in systemPatterns.md (Semantic Locators First, HITL as Learning Signal, Failure Diary Pattern via `_capture_confidence` breadcrumb)
- [x] Respects established patterns — reuses `RecipeStep.container_selector` which was designed for this
- [x] Observability approach documented (WARN log with structured fields; breadcrumb key in persisted records)
- [x] Portal metadata survives all four sinks with concrete encodings shown above
- [x] Latency O(n) in serializer and trace parser — no portal-match sweeps
- [ ] E2E replay test exercises portal_only → learned_workflows → planner → executor cycle (Phase 3 build task)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Algorithm doc emits `portal_class` without leading dot (bare class name) — executor `page.locator(portal_class)` at executor.py:2187 misinterprets | MEDIUM | HIGH (silent replay failure) | Serializer normalizes: if `portal_class` doesn't start with `.`, prepend it. Comment references this contract. Flag to algorithm agent. |
| `capture_confidence` field renamed or dropped by future algorithm-doc edit | LOW | MEDIUM | Reconciled at design review — algorithm doc ADDITION 7 now emits this field canonically. Serializer defaults to `rec.get("capture_confidence", "none")` as belt-and-suspenders: missing field → non-portal branch → byte-identical output. Fails-safe. |
| Portal opens/closes between full-capture and partial-capture inside a single takeover (mixed sequence) | MEDIUM | LOW | Each click record is independently serialized. Mixed sequences are safe — the two paths never conflict per-record. |
| Trace parser's CSS pattern for portal detection misses vendor-namespaced portals (`.custom-overlay` for a non-PrimeNG lib) | LOW | LOW | The `portal_class` CSS pattern is a whitelist starting with `.p-` or `.po-` (PrimeNG + vProMedia vendor). Explicitly document the whitelist — future contributors can extend it. |
| Adjacent branch `feature/FEAT-085-hitl-js-action-capture-navigation-race-fix` reshapes `_inject_click_capture_listener` | HIGH | MEDIUM | Merge conflict, not correctness — the algorithm doc's contract is at the payload level, not the JS injection code. Coordination via PR review. |
| `feature/FEAT-042-rag-selector-skill-library` changes `record_hitl_selector` signature | MEDIUM | LOW | Current design piggybacks in `context` string (existing arg) — signature stays 6-arg. If FEAT-042 adds a new required kwarg, adapt. |
| `_capture_confidence` breadcrumb leaks into planner prompt (planner reads dict fields) | LOW | LOW | planner.py:2288–2296 only reads `action`, `strategy`, `name`, `value` — extra keys silently ignored. Verified by reading. |
| YAML sink `container_selector` field on a `click` step is ignored by an older `recipe_runner` version | NONE | HIGH | RecipeStep.container_selector exists in current code (recipe_runner.py:188). Branch is at 80e6012 which includes it. No older-version compat concern for this branch. |

---

## Handoff to Build

### Phase 1: Serializer extension (`backend/engine/autorecord.py`)

**Change 1**: Add a helper `_maybe_portal_serialize(rec: dict) -> dict | None` above `serialize`. Returns a portal-aware dict if `rec.get("capture_confidence") in ("full", "portal_only")` and `rec.get("event_type") == "click"`; else `None`.

**Sketch**:
```python
# Whitelist of portal_class prefixes we recognize.
_PORTAL_CLASS_PREFIXES = (".p-", ".po-")

def _normalize_portal_class(portal_class: str) -> str:
    """Ensure leading dot; used to guard against algorithm agent contract drift."""
    if portal_class and not portal_class.startswith("."):
        return "." + portal_class
    return portal_class

def _maybe_portal_serialize(rec: dict) -> dict | None:
    confidence = rec.get("capture_confidence", "none")
    if confidence == "none":
        return None
    if rec.get("event_type") != "click":
        return None

    portal_class = _normalize_portal_class(rec.get("portal_class", ""))
    if not portal_class or not portal_class.startswith(_PORTAL_CLASS_PREFIXES):
        return None  # defensive: unknown portal shape → fall back to standard click serialization

    if confidence == "full":
        return {
            "action": "primeng_dropdown",
            "trigger_selector": rec.get("trigger_selector", ""),
            "target_text": rec.get("target_text", ""),
            "portal_class": portal_class,
            "inner_text": rec.get("inner_text", ""),
            "_capture_confidence": "full",
        }

    # portal_only
    target = (
        rec.get("target_text", "")
        or rec.get("inner_text", "")
        or rec.get("aria_label", "")
    )
    if target:
        return {
            "action": "click",
            "strategy": "get_by_text",
            "name": target,
            "container_selector": portal_class,
            "inner_text": rec.get("inner_text", ""),
            "_capture_confidence": "portal_only",
        }

    # portal_only_degraded — no text; use css_path scoped
    return {
        "action": "click",
        "strategy": "css_selector",
        "name": rec.get("css_path", ""),
        "container_selector": portal_class,
        "inner_text": "",
        "_capture_confidence": "portal_only_degraded",
    }
```

**Change 2**: In `AutorecordSerializer.serialize`, in the `event_type == "click"` branch (line ~100), insert BEFORE the existing `clean_actions.append(...)`:

```python
if event_type == "click":
    flush_typing()
    portal_action = _maybe_portal_serialize(rec)
    if portal_action is not None:
        clean_actions.append(portal_action)
    else:
        clean_actions.append({
            "action": "click",
            "strategy": rec.get("strategy", "get_by_text"),
            "name": rec.get("best_selector", ""),
            "inner_text": rec.get("inner_text", ""),
        })
    continue
```

**Change 3**: `_post_process` — the existing "skip redundant focus click before fill" heuristic (autorecord.py:144) MUST NOT apply to `primeng_dropdown` actions (they don't have a `name` field in the same sense — they have `trigger_selector`). Add guard:

```python
if act["action"] == "click" and next_act["action"] == "fill" and act.get("name") == next_act.get("name"):
    continue  # unchanged
```
The existing `act.get("name")` returns None for `primeng_dropdown` records; `next_act.get("name")` returns whatever the fill name is — they don't match, so this guard already deflects correctly. Verified by inspection. **No change needed to _post_process.**

**RED tests** (Phase 1 TDD entry point):
- `test_serialize_non_portal_click_byte_identical` — assert non-portal click produces exactly today's dict (AC-VERIFY-5)
- `test_serialize_full_portal_capture_emits_primeng_dropdown` — assert all three portal fields land in output
- `test_serialize_portal_only_uses_container_selector` — assert `action=click, container_selector=<portal_class>`
- `test_serialize_portal_only_empty_target_falls_back_to_css_path`
- `test_normalize_portal_class_prepends_dot`
- `test_unrecognized_portal_class_prefix_falls_through_to_standard_click`

### Phase 2: Trace parser portal detection (`backend/engine/hitl_trace_parser.py`)

**Change 1**: Extend `_extract_selector_from_params` signature to return a 3-tuple `(selector, kind, container_selector)`:

```python
_PORTAL_CSS_RE = re.compile(r"(\.(?:p-|po-)[a-z0-9-]*(?:overlay|panel|menu|dialog))")

def _extract_selector_from_params(params: dict) -> tuple[str, str, str | None]:
    # existing logic returns (selector_str, kind_str)
    # after that logic, before returning:
    container_selector: str | None = None
    raw = params.get("selector", "") or ""
    if raw:
        m = _PORTAL_CSS_RE.search(raw)
        if m:
            container_selector = m.group(1)
            # Also strip the portal prefix from the selector so get_by_text
            # doesn't include it (executor scoping does the ancestor match)
            # This is best-effort — if the split is ambiguous, leave as-is.
    return selector, kind, container_selector
```

**Change 2**: Add `container_selector` field to `ExtractedAction` dataclass (line 76). Default `None`.

**Change 3**: Update `_extract_actions_from_ndjson` to unpack the 3-tuple and pass container_selector into `ExtractedAction`.

**Change 4**: Update `_actions_to_recipe_steps` (line 329) to emit `container_selector` on the step dict when non-None. Reuses existing `RecipeStep.container_selector` field — no Pydantic schema change.

**RED tests**:
- `test_extract_selector_detects_portal_prefix` — feed CSS containing `.p-select-overlay ...`, assert `container_selector=".p-select-overlay"`
- `test_extract_selector_non_portal_returns_none_container` — feed vanilla CSS, assert `container_selector is None`
- `test_actions_to_recipe_steps_emits_container_selector` — full round-trip through the parser produces a YAML step with the scoped shape
- `test_generated_yaml_parseable_by_recipe_registry` — write emitted YAML, load via `RecipeRegistry._load_file`, assert `_load_file` doesn't error and step has expected fields

### Phase 3: Selector registry context encoding (`backend/engine/human_takeover.py`)

**Change**: At the `_sel_reg.record_hitl_selector(...)` call site (`human_takeover.py:1408`), enrich the `context` argument when the captured_click has portal fields:

```python
_portal_class = captured_click.get("portal_class", "")
_trigger = captured_click.get("trigger_selector", "")
_confidence = captured_click.get("capture_confidence", "none")

if _confidence in ("full", "portal_only") and _portal_class:
    _sel_context = f"portal:{_portal_class}|trigger:{_trigger}|ac:{current_step[:80]}"
    _sel_strategy = "get_by_text"  # portal-scoped semantic locator
    _sel_name = captured_click.get("target_text") or inner_text or aria_label or ""
else:
    _sel_context = f"AC step: {current_step[:100]}"   # unchanged from today
    _sel_strategy = _hitl_strategy                     # unchanged
    _sel_name = _hitl_name                             # unchanged

_sel_reg.record_hitl_selector(
    description=f"HITL: {current_step[:70]}",
    selector=selector,
    strategy=_sel_strategy,
    context=_sel_context,
    role=_hitl_role,
    name=_sel_name,
)
```

**RED tests**:
- `test_selector_registry_portal_click_encodes_context_grammar` — mock `record_hitl_selector`, assert `context` matches `portal:.p-select-overlay|trigger:...|ac:...`
- `test_selector_registry_non_portal_click_context_unchanged` — assert today's `AC step: ...` format on non-portal path (AC-VERIFY-5)

### Phase 4: WARN log for partial captures (`backend/engine/human_takeover.py`)

**Change**: In `_on_human_action` (line 487–520), after the existing `logger.info` at line 514, add:

```python
if action_record.get("capture_confidence") == "portal_only":
    logger.warning(
        "[%s] hitl_portal_partial_capture: portal_class=%s trigger_empty=%s target_empty=%s",
        rid,
        action_record.get("portal_class", ""),
        not action_record.get("trigger_selector", ""),
        not action_record.get("target_text", ""),
    )
```

**RED tests**:
- `test_on_human_action_partial_capture_emits_warn` — caplog assertion on WARN level with `hitl_portal_partial_capture` marker

### File-Change Summary (for Phase-1 kickoff)

| File | Lines Touched (approx.) | Nature |
|---|---|---|
| `backend/engine/autorecord.py` | +40, ~10 modified | Add `_maybe_portal_serialize`, `_normalize_portal_class`; extend click branch |
| `backend/engine/hitl_trace_parser.py` | +15, ~15 modified | Add portal CSS regex; extend selector extractor return type; propagate `container_selector` into RecipeStep dict |
| `backend/engine/human_takeover.py` | +25 modified | Enrich `record_hitl_selector(context=...)` call; add WARN log in bridge |
| `tests/backend/test_autorecord_portal.py` | NEW file, +150 | Full serializer branch coverage |
| `tests/backend/test_hitl_trace_parser_portal.py` | NEW file, +80 | Trace parser portal detection |
| `tests/backend/test_human_takeover_portal.py` | NEW file, +60 | Bridge WARN log + selector_registry integration |

**Total code delta**: ~90 lines production + ~290 lines tests. No new dependencies, no new modules, no Pydantic schema changes.

---

## NEW_TERMS_INTRODUCED

- **`capture_confidence`** — Payload-level enum from the algorithm layer indicating how completely a portal click was resolved. Values: `full`, `portal_only`, `none`. Introduced by the parallel algorithm doc; this doc consumes it as-is.
- **`_capture_confidence`** (leading underscore) — Persisted breadcrumb key on serializer output records for downstream observability. Values: `full`, `portal_only`, `portal_only_degraded`. The `_degraded` suffix indicates the further fallback for empty-text portal_only records.
- **`portal_only_degraded`** — Sub-mode of `portal_only` where even `target_text`/`inner_text`/`aria_label` are empty. Serializer falls to CSS-path-scoped click. Log-visible so operators can identify and curate.
- **`context` grammar** on `selector_registry.json` entries: `portal:<class>|trigger:<selector>|ac:<step[:80]>` — soft contract, documented in the write-call comment. Not a Pydantic-validated schema.
- **Portal whitelist**: `(.p-, .po-)` — CSS class prefixes recognized as PrimeNG/vProMedia portal containers. Anywhere else in the codebase using this pattern should reference this doc.

None of these terms need to be added to `memory-bank/c4/c4-glossary.md` (which does not exist yet on `main`) — but if a future task introduces the glossary, `capture_confidence` and `portal_class` are the two most valuable terms to canonicalize.
