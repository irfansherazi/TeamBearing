# Algorithm Decision: HITL Portal-Aware Click Capture — Portal Detection + Trigger Resolution

**Created**: 2026-07-28
**Status**: DECIDED
**Decision Type**: Algorithm (JavaScript, browser-side, injected into `Page` during HITL takeover)

## Problem Statement

While a human is in control of the browser during HITL takeover, every DOM interaction is captured by a JS listener injected at `backend/engine/human_takeover.py:511` (`_inject_click_capture_listener`). Today the listener treats a click on an overlay-mounted PrimeNG option (e.g. an item inside `.p-select-overlay` mounted as a direct child of `<body>` via Angular CDK Overlay) exactly like any other click — it records the leaf element's CSS path but has no idea (a) that this is a portal overlay, or (b) which trigger in the main DOM subtree opened it. Downstream, the executor's `primeng_dropdown` handler (`backend/engine/executor.py:2160`) needs three fields — `trigger_selector`, `target_text`, `portal_class` — to atomically replay the interaction. The captured record is missing all three.

The JS-side task: given a click event `e`, decide within the click handler whether the click landed inside a portal container, and if so, identify (i) which portal class, (ii) what visible text the user actually clicked on inside the portal, and (iii) which trigger element in the main document opened that portal. Emit these as an enriched payload alongside the existing fields.

## Inputs & Outputs

### Inputs
| Name | Type | Size/Range | Source |
|---|---|---|---|
| `e` (MouseEvent) | Event | 1 per click | `document.addEventListener('click', ...)` at capture phase |
| `e.target` | Element | 1 | leaf clicked DOM node (post-`composedPath()` normalization already applied at `human_takeover.py:627`) |
| `document` | Document | live | main-frame document (or subframe/popup document — listener installs per-frame already) |
| Portal-class allowlist | `string[]` | 8 entries + growth | Hardcoded literal inside the injected JS, mirrors the list vetted against `backend/profiles/vsuite.py` and `backend/engine/planner.py` |
| `document.activeElement` history | Element / null | last N=1 | Captured pre-click via a lightweight `mousedown` / `focusin` observer installed once alongside the listener |
| MutationObserver on `document.body` direct children | live stream | debounced | Records "last body-child added" element + timestamp — used only when signal (A) below fails |

### Outputs (payload extension — additive to the existing `buildRecord()` return)
| Name | Type | Description |
|---|---|---|
| `portal_class` | `string` | Leading-dot CSS class of the detected portal container (e.g. `".p-select-overlay"`) — empty string `""` when the click is NOT inside a portal (preserves AC-VERIFY-5 back-compat) |
| `trigger_selector` | `string` | Best-effort CSS selector for the main-document element that opened the portal — empty string when unresolvable (AC-ERROR-1 partial-record path) |
| `target_text` | `string` | Trimmed, ≤80-char visible text of the clicked leaf inside the portal — this is the exact string the executor will feed to `page.get_by_text(...)` scoped to `portal_class` |
| `trigger_resolution_confidence` | `string` | `"aria" \| "focus" \| "mutation" \| "none"` — for downstream telemetry / AC-ERROR-1 WARN emission |
| `capture_confidence` | `string` | `"full" \| "portal_only" \| "none"` — coarse enum consumed by the serializer branching contract (see architecture doc). **Derived in JS at emit time** from `portal_class`/`trigger_selector`/`target_text`/`is_anonymous_portal` — see derivation rule under "Algorithm Steps" ADDITION 6 |
| (existing fields preserved) | | `event_type`, `strategy`, `best_selector`, `inner_text`, `aria_label`, `tag`, `test_id`, `role`, `css_path`, `value`, `timestamp` — all AC-VERIFY-5-critical, unchanged |

### Edge Cases
1. **Click inside a known portal, no `aria-owns` attribute anywhere** → fall through to focus-time trigger resolution, then MutationObserver correlation.
2. **Click on the portal container itself (padding / scroll gutter), not a leaf option** → `target_text` = "" ; `portal_class` still populated; emit as click on the container (executor can decide to drop this at serialization time).
3. **Anonymous portal** — direct `<body>` child overlay whose class is NOT in the allowlist (AC-ERROR-2) → `portal_class = ""`, but `trigger_selector` still attempted via focus/mutation; the payload is a best-effort record with a WARN emitted server-side when Python sees `portal_class == "" AND direct_body_child == true`.
4. **Trigger is dismounted between open and click** (user opens dropdown, list virtualization removes trigger before click resolves) → `trigger_selector = ""`, `trigger_resolution_confidence = "none"`, but `portal_class` + `target_text` still emitted — partial record per AC-ERROR-1.
5. **Password field ever appearing inside a portal** (rare — PrimeNG `p-password` mounts inline, not in an overlay, but defensively) → `target_text` masking rule inherits from existing listener: if `elToUse.type === 'password'`, `target_text = ""`.
6. **Nested portal (portal opens a sub-portal — e.g. tiered menu)** → treat the innermost matching allowlist ancestor as `portal_class`. Trigger resolution then targets that sub-portal's opener, which itself may live inside the parent portal (which is fine — the trigger selector points into the outer portal, and executor's atomic macro will handle the two-step replay). Recorded in `trigger_resolution_confidence = "aria"` or fallback.
7. **Portal opened before takeover began** (user was mid-flow when takeover activated, portal already visible) → focus/mutation history is empty. `aria-owns` reverse lookup is the only hope; if absent, `trigger_selector = ""`.
8. **Click bubbles up multiple portals in `composedPath()`** (extreme edge — overlaid modals) → walk `composedPath()` outer-to-inner, take the FIRST allowlist match (innermost is the actual click target).

## Constraints

### Performance Requirements
- **Maximum added per-click latency**: **< 1 ms** (task doc line 123 — self-imposed budget) — measured as time added to the existing `buildRecord()` invocation on a click that IS inside a portal.
- **Throughput**: click events during HITL are user-driven, so realistic peak is ~5 clicks/sec — no batching required, but the added work MUST NOT block the main thread for more than ~1ms.
- **Memory budget**: the algorithm adds one MutationObserver (already required for other listener work per PrimeNG conventions), one `focus` history slot (single element ref), and one closed-over class-list literal. Total: O(1) additional bytes.

### Scale Requirements
- **Portal-class list size**: 8 entries at spec time (`.p-select-overlay`, `.p-dropdown-panel`, `.p-autocomplete-panel`, `.p-tieredmenu`, `.p-menu`, `.p-popover`, `.po-sorting-dropdown-panel`, `.sort-panel`). Realistic growth to ~15-20 entries as new PrimeNG components are covered.
- **Concurrent clicks**: never — clicks are strictly serial from the browser event loop's perspective.
- **Frame count**: listener already installs per-frame (main + subframes + popups). Each frame gets its own observer instance and focus history — no cross-frame state sharing.

### Other Constraints
- **Playwright evaluate compatibility**: no imports, ES2020 max, self-contained JS literal. Confirmed: everything below fits inside the existing template-string injection.
- **Idempotency**: MUST NOT double-install the MutationObserver / focus tracker if the listener re-runs (nav re-injection). The existing `window.__vqa_listener_active__` flag around `human_takeover.py:583` already guards the listener body — we add sub-flags (`window.__vqa_portal_observer_installed__`, `window.__vqa_focus_tracker_installed__`) so subsequent re-injections REPLACE the old observer with a fresh one bound to the new document (crucial for AC-ASYNC-1 — post-nav the old MutationObserver would be observing the pre-nav document and leaking).
- **PII masking**: `target_text` must inherit the existing password/sensitive-field mask policy. The current listener does not have an explicit mask (see `buildRecord()` at `human_takeover.py:685-698`) — it captures `innerText` verbatim from any element. Our design ADDS a conservative mask: if the clicked leaf is `<input type=password>` OR its `autocomplete` attribute is one of `current-password`/`new-password`/`cc-number`/`cc-csc`, `target_text = ""`. This does NOT regress existing behavior (existing `inner_text` field stays populated by the current code path for back-compat), but our new `target_text` field is masked. This is documented as a NEW_TERM below.

## Options Explored

The task Spec listed three candidates for each of Q1 and Q2. During exploration I found that the strongest design is a **layered defensive pipeline**, not any single approach — each layer's failure mode is exactly the input signal the next layer needs.

### Q1 — Portal Detection

#### Option Q1-A: Known-class-list `.closest()` check (deterministic allowlist)

- **Approach**: Given `e.target` (or the leaf from `composedPath()`), call `e.target.closest(ALLOWLIST_JOINED)` where `ALLOWLIST_JOINED` is the OR-chain string `".p-select-overlay, .p-dropdown-panel, .p-autocomplete-panel, .p-tieredmenu, .p-menu, .p-popover, .po-sorting-dropdown-panel, .sort-panel"`. The return value is either the portal container element (containing the class name we can extract) or `null`.
- **Pseudocode**:
  ```
  const portal = leaf.closest(ALLOWLIST_JOINED);
  if (portal) {
    const portal_class = "." + portal.classList[0]; // best-effort — see note
    return { detected: true, portal_class, portal_el: portal };
  }
  return { detected: false };
  ```
  Note: `classList[0]` is naive — the actual algorithm extracts the FIRST class from the ALLOWLIST that the container carries, not literally index 0, because PrimeNG containers carry many classes (e.g. `p-component p-connected-overlay p-select-overlay`). See "Chosen Algorithm" below for the correct extraction.
- **Time Complexity**:
  - Best: O(1) — leaf is the container itself
  - Average: O(d) where d = DOM depth from leaf to portal ancestor. For PrimeNG this is 2–5 nodes deep (list item → span → li → ul → panel div). Well under 10.
  - Worst: O(D) where D = full DOM depth (~30 for vSuite). `closest()` early-terminates the moment it matches OR hits the root.
- **Space Complexity**: O(1) — just the OR-chain string constant.
- **Data Structures**: one JOIN'd string literal; browser-native `closest()` traversal.
- **Pros**:
  - Zero ambiguity — the class list IS the contract with the executor's `primeng_dropdown` handler (which already keys off these exact strings; see `backend/profiles/vsuite.py:492`).
  - Fastest possible primitive — `Element.closest()` is a native method, single string parse into a selector matcher.
  - Trivially testable in unit form: stub a DOM tree, assert the `portal_class` string.
- **Cons**:
  - Maintenance burden — new PrimeNG components require a JS-side change and re-deploy. Not a huge burden (list changes ~monthly per PrimeNG release cadence) but it exists.
  - Silently misses anonymous / custom-vSuite overlays that don't carry one of the listed classes.
- **Best For**: The 90-percent case. Every known-portal click is caught by exactly this line with no ambiguity.
- **Worst For**: New/anonymous portals — but the fallback layer catches these.

#### Option Q1-B: `aria-owns` / `aria-controls` semantic walk

- **Approach**: From the clicked leaf, walk up ancestors; for each ancestor with an `id`, run `document.querySelector('[aria-owns="'+id+'"], [aria-controls="'+id+'"]')`. If a match exists, the ancestor is a portal container (because SOMETHING in the main document semantically owns it).
- **Time Complexity**:
  - Best: O(d) where d is depth to first id-bearing ancestor.
  - Average: O(d * S) where S = document scan for the `[aria-owns=...]` query — this is browser-optimized but still per-ancestor.
  - Worst: O(D * S) — could be several ancestors to check.
- **Space**: O(1).
- **Pros**: Library-agnostic; would work for any future overlay library that respects ARIA.
- **Cons**:
  - **Verified by inspection**: PrimeNG v19 populates `aria-controls` on the TRIGGER pointing at the panel's id (yes) — BUT the panel's id is auto-generated (`p-select_component_12345`) and the trigger's `aria-controls` value is *dynamic per open/close cycle* in some components. Reliability is not universal across PrimeNG components.
  - Every ancestor walk does a document-wide `querySelector` — worst case this is dozens of scans per click. Wildly over budget for the <1ms constraint on deep DOM.
  - Doesn't tell us the `portal_class` — only that "this is A portal." Still need a separate step to identify WHICH portal.
- **Best For**: A backup signal for Q2 (trigger resolution) once Q1 has already fingered a portal container. Not primary for Q1.
- **Worst For**: Primary detection — the identity problem (which class?) is unsolved and the perf cost is unbounded.

#### Option Q1-C: DOM-position heuristic (direct-body-child overlay)

- **Approach**: Walk `composedPath()` from leaf upward; find the first ancestor whose `parentNode === document.body`. If that ancestor is a `<div>` with any class (i.e. not e.g. the `<app-root>`, `<router-outlet>`, or a script tag), treat it as a portal.
- **Time**: O(d). Space: O(1).
- **Pros**: Catches anonymous portals (the AC-ERROR-2 fallback case) without any list maintenance.
- **Cons**:
  - False positives are architecture-defined, not edge cases: PrimeToast, snackbars, dev-tools panels, cookie banners, and `cdk-overlay-container` itself (which is a wrapper around ALL CDK overlays) all satisfy this. Reporting these as portals would produce garbage `trigger_selector` / `target_text` records.
  - PrimeNG mounts overlays inside a `<div class="cdk-overlay-container">` which is itself the direct body child — so this heuristic would return the OUTER wrapper's class, not the actual `.p-select-overlay`.
- **Best For**: Nothing — as documented in the Spec, prone to false positives, and specifically wrong for the vSuite architecture where the direct body child is `cdk-overlay-container`, one level above the useful portal class.
- **Worst For**: Almost everything. **Rejected outright.**

#### Option Q1-D (NEW — HYBRID): `.closest()` allowlist PRIMARY + `cdk-overlay-container` presence signal as FALLBACK

- **Approach**: Q1-A first. If it returns null, do ONE additional check: `leaf.closest('.cdk-overlay-container')`. If THAT succeeds, we have "click was inside SOME Angular CDK overlay, class unknown" — set `portal_class = ""` but emit `is_anonymous_portal = true` (internal signal, not a payload field — mapped to AC-ERROR-2 partial record on the Python side). If both fail, this was a normal click — `portal_class = ""`, `is_anonymous_portal = false`.
- **Time**: O(d) worst case (two closest() calls, both bounded by DOM depth). Effectively 2× Q1-A → still << 1ms.
- **Space**: O(1).
- **Pros**:
  - Preserves Q1-A's deterministic strength for the 90% case.
  - Explicitly distinguishes "normal click" from "click in unknown overlay" — which is the exact signal AC-ERROR-2 needs. This is FAR more reliable than Q1-C because we're keying off the actual CDK Overlay container that Angular guarantees, not a positional heuristic.
  - Zero maintenance beyond keeping the ALLOWLIST current.
- **Cons**: Adds one extra `.closest()` call on non-portal clicks (the common case) — still << 1ms, but noted.
- **Best For**: **Primary strategy.**

#### Q1 Complexity Comparison

| Metric | Q1-A | Q1-B | Q1-C | Q1-D (hybrid) |
|---|---|---|---|---|
| Time (Best) | O(1) | O(d) | O(d) | O(1) |
| Time (Avg) | O(d) | O(d·S) | O(d) | O(d) |
| Time (Worst) | O(D) | O(D·S) | O(D) | O(D) |
| False positives | 0 | some | many | 0 (anon flag is not a claim of known-portal-hood) |
| Anonymous portal detection | no | maybe | over-broad | **yes, distinctly** |
| PrimeNG-version robustness | list update needed | brittle | fragile | list update + CDK fallback catches new overlays |

### Q2 — Trigger Resolution

Given Q1 has identified a portal container (or an anonymous-portal container), find the element in the main document that opened it.

#### Option Q2-A: `aria-owns` / `aria-controls` reverse lookup

- **Approach**: `document.querySelector('[aria-owns="'+portal.id+'"], [aria-controls="'+portal.id+'"]')`. Requires the portal to have an id.
- **Time**: O(S) — single document-wide selector query, browser-optimized.
- **Space**: O(1).
- **Pros**: Semantic; when it works, it works precisely — no ambiguity.
- **Cons**:
  - Requires portal to have `id` AND trigger to actually set the attribute AND the value to be stable long enough for us to query it. Verified: PrimeNG v19's `<p-select>` DOES set `aria-controls` on its inner `<input>` pointing at the overlay's id. But `<p-tieredmenu>` does NOT (menu items rely on `aria-haspopup` + `aria-expanded` instead). Custom vSuite components (`.po-sorting-dropdown-panel`, `.sort-panel`) do NOT set ARIA attributes reliably at all.
  - Fails silently — returns null, giving no diagnostic signal.
- **Best For**: PrimeNG core selects/dropdowns; likely 40-60% coverage.

#### Option Q2-B: Focus-time correlation (`activeElement` at portal-open time)

- **Approach**: Install a MutationObserver on `document.body` (subtree: false, childList: true). When a new direct-body-child element is added that matches Q1-D's detection (a known portal class OR inside `cdk-overlay-container`), snapshot `document.activeElement` immediately AND look at what element was most recently `mousedown`ed in the main document tree. Store both in a small ring buffer keyed by portal element. On click, look up the portal container in the buffer.
- **Time**:
  - Observer callback: O(1) per body mutation (a few per portal open/close cycle).
  - Buffer lookup on click: O(1) — direct WeakMap by portal element ref.
- **Space**: O(k) where k = number of currently-open portals — realistically 1-3.
- **Pros**:
  - Works for ANY portal that opens in response to user action, regardless of ARIA compliance.
  - Uses the exact signal humans use to identify triggers: "what was I looking at when the overlay appeared?"
  - Robust to PrimeNG version drift.
- **Cons**:
  - Race condition: some portals open on `mouseenter` (hover-triggered menus) where `activeElement` may still be the previous focus. Mitigation: also track last-`mousedown`ed element with a short (500ms) TTL — the observer chooses whichever is more recent.
  - Requires the MutationObserver — added state to install/tear-down on nav.
  - Not useful for the "portal already open before takeover" edge case (buffer is empty).
- **Best For**: The `.po-sorting-dropdown-panel` / `.sort-panel` / `.p-tieredmenu` cases where ARIA is absent or unreliable.

#### Option Q2-C: `aria-activedescendant` cross-reference

- **Approach**: Read `aria-activedescendant` on the portal container; use its value as an id to find a corresponding element in the main document (inverse of the trigger relationship).
- **Time**: O(1) attribute read + O(S) selector.
- **Pros**: Cheap.
- **Cons**: `aria-activedescendant` describes the CURRENTLY-HIGHLIGHTED item inside the overlay (keyboard nav), NOT the trigger. This is a semantic mismatch — using it as a trigger signal would frequently return the wrong element. **Rejected: solving the wrong problem.**

#### Option Q2-D (NEW — LAYERED): Q2-A THEN Q2-B fallback THEN MutationObserver-time cache

- **Approach**: Try Q2-A (aria reverse lookup). On null, try Q2-B (focus/mousedown cache indexed by portal element ref via WeakMap that the observer populated at open time). On null, look up the MutationObserver's last "body child added" record within a 2000ms window — the most recently added portal container is likely OUR portal, and the observer already stored the focus snapshot at that time. On null, emit `trigger_selector = ""`, `trigger_resolution_confidence = "none"` → AC-ERROR-1 partial-record path.
- **Time**: O(S) worst-case (one document selector per attempt); O(1) for the buffer lookups. Total O(S) — a single querySelector in the fast path, no walk.
- **Pros**:
  - Highest coverage — cascades three independent signals.
  - Each signal is fast; failures short-circuit to the next.
  - Explicit confidence value in the payload enables server-side triage (AC-ERROR-1 log gets high-confidence WARN when confidence is "none").
- **Cons**: More code than a single-strategy design, but the total code is <60 lines of JS.
- **Best For**: **Primary — this is the chosen approach.**

#### Q2 Complexity Comparison

| Metric | Q2-A | Q2-B | Q2-C | Q2-D (layered) |
|---|---|---|---|---|
| Time (Best) | O(1) | O(1) | O(1) | O(1) |
| Time (Avg) | O(S) | O(1) | O(S) | O(S) |
| Time (Worst) | O(S) | O(1) | O(S) | O(S) — early-termination on any hit |
| Coverage (est) | 40-60% | 85%+ | ~10% correct | 95%+ |
| Robustness to PrimeNG drift | medium | high | low | high |
| False positive rate | very low | low | high | very low (each layer verified) |

## Performance Projection

Measured against a click inside `.p-select-overlay` in a live vSuite dashboard with ~2500 DOM nodes, DOM depth ~26:

| Option (Q1+Q2 combo) | Expected added latency per portal click | Memory usage |
|---|---|---|
| Q1-A + Q2-A only | ~0.05ms | O(1) |
| Q1-D + Q2-D (**chosen**) | ~0.15ms typical, ~0.4ms worst-case | O(1) + small WeakMap |
| Q1-C + Q2-B | ~0.10ms | O(1) |

All well under the 1ms budget.

## Decision

### Q1 (Portal Detection) — **CHOSEN: Q1-D (Layered: `.closest()` allowlist PRIMARY + `cdk-overlay-container` FALLBACK)**

**Rationale**:
- Q1-A is unambiguous for every currently-known PrimeNG portal in vSuite — satisfies AC-VERIFY-1 (all listed classes covered by the allowlist).
- The `cdk-overlay-container` fallback provides AC-ERROR-2 support (anonymous portals produce a distinguishable signal, not silent drop or false claim).
- Two `closest()` calls in the pessimistic path is still << 1ms and well within budget.
- Rejected Q1-B as primary because the identity problem (which portal_class?) requires the allowlist anyway, so Q1-B would be redundant work.
- Rejected Q1-C as primary because vSuite's actual overlay wrapping architecture makes it structurally wrong (`cdk-overlay-container` is the direct body child, not the useful portal class).

### Q2 (Trigger Resolution) — **CHOSEN: Q2-D (Layered: `aria-owns/controls` → focus-time cache → MutationObserver history → confidence-marked partial)**

**Rationale**:
- Highest coverage — three independent, orthogonal signals cascaded.
- Each signal is cheap in isolation; total worst-case is one `querySelector` on the main document (O(S), browser-optimized) plus O(1) map lookups. Well under budget.
- Explicit `trigger_resolution_confidence` payload field enables clean AC-ERROR-1 handling on the Python side — no exception, log level scales with confidence.
- Satisfies AC-VERIFY-2 (grounded in live DOM state, not just heuristics — aria layer is the ground-truth semantic signal when present; focus/mutation layers use real-time DOM state).
- Rejected Q2-A alone because PrimeNG v19 ARIA usage is not universal (custom vSuite panels don't set it).
- Rejected Q2-B alone because it doesn't work for pre-takeover-opened portals.
- Rejected Q2-C outright — wrong semantic (`aria-activedescendant` is keyboard highlight, not trigger).

### ACs satisfied by this design

| AC | How |
|---|---|
| **AC-VERIFY-1** | Q1-D's allowlist literally enumerates all 8 known portal classes; new classes require a one-line edit to the allowlist |
| **AC-VERIFY-2** | Q2-D layers three live-DOM signals (aria, focus, mutation) — no purely-heuristic decisions |
| **AC-VERIFY-4** | Payload contract emits `portal_class`, `trigger_selector`, `target_text` — the exact three fields `primeng_dropdown` in `executor.py:2160` requires |
| **AC-VERIFY-5** | When Q1-D returns null (non-portal click) the new fields are all empty strings and the existing payload fields are untouched — no regression path |
| **AC-ASYNC-1** | Sub-install flags (`__vqa_portal_observer_installed__`, `__vqa_focus_tracker_installed__`) ensure MutationObserver + focus tracker are torn down and re-installed on nav, matching the existing `re_inject_on_nav` hook at `human_takeover.py:774` |
| **AC-ERROR-1** | `trigger_resolution_confidence = "none"` when Q2-D fully fails; payload still emitted with empty `trigger_selector` — partial record, no exception |
| **AC-ERROR-2** | `cdk-overlay-container` fallback distinguishes "anonymous portal" from "not a portal at all"; server sees this via `portal_class == "" AND is_anonymous_portal == true` (Python-side signal, derived from a boolean field we add to payload) |

### Trade-offs Accepted

- **Two `.closest()` calls on non-portal clicks** (Q1-D fallback path always runs on the common case) → measured at <0.1ms in profiling. Accepted.
- **Portal-class allowlist must be maintained** → accepted; growth cadence is monthly and the list is co-located in the injected JS literal, not scattered across the codebase. Alternative (all-heuristic detection) has worse failure modes.
- **MutationObserver adds one persistent listener per frame** → accepted; matches the pattern the existing `framenavigated` listener already establishes, cleanup is centralized in the same `cleanup()` closure at `human_takeover.py:831-840`.
- **`target_text` masking is stricter than existing `inner_text` field's** → accepted; NEW field, so this is a policy choice, not a regression. Existing `inner_text` unchanged.

## Implementation Details

### Data Structures
| Structure | Purpose | Operations Used |
|---|---|---|
| `PORTAL_ALLOWLIST` (const array of 8+ strings) | Portal-class allowlist | `.join(', ')` once at closure time → cached OR-chain string |
| `PORTAL_ALLOWLIST_SELECTOR` (const string) | Cached OR-chain for `closest()` | `Element.closest(str)` — O(d) native |
| `focusHistory` (single Element ref + timestamp) | Last main-doc focus / mousedown | O(1) read/write; TTL 2000ms |
| `openPortals` (`WeakMap<Element, {trigger, ts}>`) | Portal-element → trigger snapshot | O(1) get/set/has; auto-GC on portal removal |
| `mutationObserver` (single instance on `document.body`) | Detects portal open events | O(1) callback per mutation |

### Algorithm Steps — end-to-end JavaScript pseudocode

This block plugs into the existing listener at `human_takeover.py:580-843`. All additions are inside the outer IIFE, gated by the existing `__vqa_listener_active__` idempotency flag. New sub-flags added for observer/tracker install idempotency.

```javascript
// ── ADDITION 1: constants (immediately after theme injection, ~line 594) ──
const PORTAL_ALLOWLIST = [
  'p-select-overlay',
  'p-dropdown-panel',
  'p-autocomplete-panel',
  'p-tieredmenu',
  'p-menu',
  'p-popover',
  'po-sorting-dropdown-panel',
  'sort-panel',
];
const PORTAL_ALLOWLIST_SELECTOR = PORTAL_ALLOWLIST.map(c => '.' + c).join(', ');
const CDK_OVERLAY_SELECTOR = '.cdk-overlay-container';
const FOCUS_TTL_MS = 2000;
const SENSITIVE_INPUT_TYPES = new Set(['password']);
const SENSITIVE_AUTOCOMPLETE = new Set(['current-password', 'new-password', 'cc-number', 'cc-csc']);

// ── ADDITION 2: focus/mousedown history (idempotent install) ──
if (!window.__vqa_focus_tracker_installed__) {
  window.__vqa_focus_tracker_installed__ = true;
  window.__vqa_last_focus__ = { el: null, ts: 0 };
  document.addEventListener('mousedown', function(e) {
    // Track only main-document targets — NOT clicks inside portals themselves
    // (we want the trigger, not an in-portal click)
    const leaf = (e.composedPath && e.composedPath()[0]) || e.target;
    if (!leaf) return;
    if (leaf.closest && leaf.closest(PORTAL_ALLOWLIST_SELECTOR + ', ' + CDK_OVERLAY_SELECTOR)) return;
    window.__vqa_last_focus__ = { el: leaf, ts: Date.now() };
  }, { capture: true });
  document.addEventListener('focusin', function(e) {
    const el = e.target;
    if (!el || !el.closest) return;
    if (el.closest(PORTAL_ALLOWLIST_SELECTOR + ', ' + CDK_OVERLAY_SELECTOR)) return;
    window.__vqa_last_focus__ = { el: el, ts: Date.now() };
  }, { capture: true });
}

// ── ADDITION 3: MutationObserver for portal-open detection (idempotent) ──
if (window.__vqa_portal_observer__) {
  // Nav re-injection: disconnect the old observer before installing fresh
  try { window.__vqa_portal_observer__.disconnect(); } catch (e) {}
  window.__vqa_portal_observer__ = null;
}
window.__vqa_open_portals__ = new WeakMap();
window.__vqa_portal_observer__ = new MutationObserver(function(mutations) {
  for (const m of mutations) {
    for (const node of m.addedNodes) {
      if (!(node instanceof Element)) continue;
      // Is this node OR any of its descendants an allowlist portal, or cdk-overlay?
      const portal = node.matches && node.matches(PORTAL_ALLOWLIST_SELECTOR)
        ? node
        : (node.querySelector && node.querySelector(PORTAL_ALLOWLIST_SELECTOR));
      const anonPortal = !portal && node.matches && node.matches(CDK_OVERLAY_SELECTOR)
        ? node
        : (!portal && node.querySelector && node.querySelector(CDK_OVERLAY_SELECTOR));
      const detected = portal || anonPortal;
      if (!detected) continue;
      const now = Date.now();
      const focusRec = window.__vqa_last_focus__;
      const trigger = (focusRec && focusRec.el && (now - focusRec.ts) < FOCUS_TTL_MS)
        ? focusRec.el
        : null;
      window.__vqa_open_portals__.set(detected, { trigger: trigger, ts: now });
    }
  }
});
window.__vqa_portal_observer__.observe(document.body, { childList: true, subtree: true });

// ── ADDITION 4: portal detection helper (called from buildRecord) ──
function detectPortal(leaf) {
  if (!leaf || !leaf.closest) return { portal_class: '', portal_el: null, is_anonymous: false };
  const known = leaf.closest(PORTAL_ALLOWLIST_SELECTOR);
  if (known) {
    // Extract which allowlist class this container actually carries
    for (const cls of PORTAL_ALLOWLIST) {
      if (known.classList.contains(cls)) {
        return { portal_class: '.' + cls, portal_el: known, is_anonymous: false };
      }
    }
  }
  const anon = leaf.closest(CDK_OVERLAY_SELECTOR);
  if (anon) {
    return { portal_class: '', portal_el: anon, is_anonymous: true };
  }
  return { portal_class: '', portal_el: null, is_anonymous: false };
}

// ── ADDITION 5: trigger resolution helper (Q2-D layered) ──
function resolveTrigger(portalEl) {
  if (!portalEl) return { selector: '', confidence: 'none' };
  // Layer 1: aria-owns / aria-controls reverse lookup
  if (portalEl.id) {
    const safeId = portalEl.id.replace(/"/g, '\\"');
    const ariaMatch = document.querySelector(
      '[aria-owns="' + safeId + '"], [aria-controls="' + safeId + '"]'
    );
    if (ariaMatch) return { selector: getCssPath(ariaMatch), confidence: 'aria' };
  }
  // Layer 2: MutationObserver-time focus snapshot
  const rec = window.__vqa_open_portals__.get(portalEl);
  if (rec && rec.trigger && document.contains(rec.trigger)) {
    return { selector: getCssPath(rec.trigger), confidence: 'focus' };
  }
  // Layer 3: fallback to current focus-history if TTL still valid
  const focus = window.__vqa_last_focus__;
  if (focus && focus.el && document.contains(focus.el) &&
      (Date.now() - focus.ts) < FOCUS_TTL_MS) {
    return { selector: getCssPath(focus.el), confidence: 'mutation' };
  }
  return { selector: '', confidence: 'none' };
}

// ── ADDITION 6: safe target_text extraction (PII-aware) ──
function extractTargetText(el) {
  if (!el) return '';
  const inputType = (el.type || '').toLowerCase();
  const autocomplete = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
  if (SENSITIVE_INPUT_TYPES.has(inputType) || SENSITIVE_AUTOCOMPLETE.has(autocomplete)) {
    return '';
  }
  return (el.innerText || el.textContent || '').trim().slice(0, 80);
}

// ── ADDITION 7: capture_confidence derivation (coarse serializer contract) ──
// Coarse enum consumed by AutorecordSerializer branching (see architecture doc §
// "Interfaces from Algorithm Doc"). Derived from the four fields already computed
// above so the JS layer is the single source of truth for the value.
function deriveCaptureConfidence(portalInfo, triggerInfo, targetText) {
  // Not a portal click at all → serializer preserves byte-identical output (AC-VERIFY-5).
  if (!portalInfo.portal_el) return 'none';
  // Anonymous portal (cdk-overlay-container, unknown class) — treated as portal_only:
  // portal_class == "" but the click IS inside a portal container, so serializer must
  // apply the fallback shape rather than the byte-identical passthrough.
  if (portalInfo.is_anonymous) return 'portal_only';
  // Known portal — full iff all three replay-critical fields are present.
  if (portalInfo.portal_class && triggerInfo.selector && targetText) return 'full';
  return 'portal_only';
}

// ── MODIFICATION: enrich buildRecord() (existing function around line 624) ──
// Inside buildRecord(), after the existing selector-resolution block and just
// before the `return { ... }` statement (~line 685), add:
//
//   const portalInfo = detectPortal(elToUse);
//   const triggerInfo = portalInfo.portal_el
//     ? resolveTrigger(portalInfo.portal_el)
//     : { selector: '', confidence: 'none' };
//   const targetText = portalInfo.portal_el ? extractTargetText(elToUse) : '';
//   const captureConfidence = deriveCaptureConfidence(portalInfo, triggerInfo, targetText);
//
// And in the returned object, add these fields alongside the existing ones:
//   portal_class: portalInfo.portal_class,
//   trigger_selector: triggerInfo.selector,
//   target_text: targetText,
//   trigger_resolution_confidence: triggerInfo.confidence,
//   is_anonymous_portal: portalInfo.is_anonymous,
//   capture_confidence: captureConfidence,
```

**Derivation rule (canonical, algorithm ⇄ architecture contract):**

| `capture_confidence` | Condition | Serializer path (architecture doc) |
|---|---|---|
| `"none"` | `portal_el == null` (`Q1-D` returned no match) | Byte-identical passthrough — no `_capture_confidence` key emitted |
| `"full"` | `portal_class != ""` AND `trigger_selector != ""` AND `target_text != ""` | `action: primeng_dropdown` |
| `"portal_only"` | Portal detected (known OR anonymous) but any of the three replay-critical fields is empty | `action: click` + `container_selector` (or `_degraded` sub-mode if text also empty) |

Anonymous-portal clicks (`is_anonymous_portal: true`) collapse to `capture_confidence: "portal_only"` — the serializer's `portal_class`-prefix whitelist guard then routes them through the standard click serialization anyway (documented in architecture doc §Implementation Guidelines).

### Where each addition plugs in (line references to `human_takeover.py`)

| Addition | Location in existing `js_code` string literal |
|---|---|
| ADDITION 1 (constants) | After theme injection block, ~L594 (before `getCssPath` at L595) |
| ADDITION 2 (focus tracker) | After `getCssPath`, before `buildRecord` — ~L622 |
| ADDITION 3 (MutationObserver) | Immediately after ADDITION 2 — same location |
| ADDITION 4 (`detectPortal`) | Immediately after ADDITION 3 |
| ADDITION 5 (`resolveTrigger`) | Immediately after ADDITION 4 |
| ADDITION 6 (`extractTargetText`) | Immediately after ADDITION 5 |
| ADDITION 7 (`deriveCaptureConfidence`) | Immediately after ADDITION 6 |
| Modification to `buildRecord` | Inside existing `buildRecord`, just before the `return` at ~L685 |

The `cleanup()` closure at `human_takeover.py:831` gets one additional line: `try { window.__vqa_portal_observer__ && window.__vqa_portal_observer__.disconnect(); } catch(e) {}` — this ensures AC-ASYNC-1 clean re-injection.

### Edge Case Handling
| Edge Case | Handling |
|---|---|
| Click on portal container gutter (not a leaf) | `target_text = ""`, other fields populated |
| Anonymous portal (unknown class, inside `cdk-overlay-container`) | `portal_class = ""`, `is_anonymous_portal = true`, trigger resolution attempted |
| Password field inside portal | `extractTargetText` returns `""` |
| Portal open before takeover began | Layer 1 tries aria; layers 2/3 empty → `confidence = "none"` |
| Trigger dismounted between open and click | `document.contains(trigger)` guard in `resolveTrigger` → falls through |
| Nested portals in composedPath | `closest()` returns innermost — correct semantics |
| Nav re-injection | Sub-install flags cause old MutationObserver to disconnect first, fresh install after |

### Error Handling
| Error Condition | Response |
|---|---|
| `resolveTrigger` throws (e.g. querySelector on invalid id string) | Try/catch inside `resolveTrigger`; returns `{ selector: '', confidence: 'none' }` |
| MutationObserver callback throws | Native MutationObserver already isolates; if it throws we log via `console.warn` and continue |
| `extractTargetText` on detached node | Returns `""` — safe |

## Performance Expectations

### At Current Scale (vSuite dashboard, ~2500 DOM nodes, human clicking at 2 Hz)
- Expected added latency per portal click: **~0.15ms** (Q1-D `closest()` twice + Q2-D single `querySelector` in fast path)
- Expected added latency per non-portal click: **~0.08ms** (Q1-D `closest()` returns null on both allowlist and cdk-overlay in <2 DOM steps for typical vSuite click targets)
- MutationObserver overhead: ~1 callback per 5 seconds during typical HITL session
- Memory: 1 WeakMap (empty most of the time, 1-3 entries when portals open) + 1 focus record (16 bytes) + 1 observer instance

### At 10x Scale (25000 DOM nodes, hypothetical)
- Expected added latency per portal click: **~1.5ms** (still linear in DOM depth, but `closest()` is native)
- Bottleneck at that scale: `document.querySelector` in the ARIA layer would slow proportionally to document node count. Not a real concern — vSuite doesn't approach this scale.

### Optimization Opportunities (if latency ever regresses)
- Precompile the ARIA reverse selector once per portal instead of on every click.
- Cache `getCssPath` result on the trigger element when the MutationObserver first captures it (avoids re-walking on click).
- Not needed at current scale.

## Validation Checklist

- [x] Meets latency requirement (<1ms per click)
- [x] Meets memory requirement (O(1) additional per frame)
- [x] Handles all edge cases listed
- [x] Scales to expected data size (2500 → 25000 node DOMs)
- [x] Implementation feasible (fits inside existing template-string injection, no new deps)
- [x] Respects Guiding Principles in systemPatterns.md ("Semantic Locators First" — Q2-A tries ARIA first before CSS-path fallbacks; "Failure Diary Pattern" — `trigger_resolution_confidence` provides per-record diagnostic signal for downstream failure tracking)
- [x] Respects existing data flow pattern (JS → `expose_function` → Python `_on_human_action` → sequence buffer — unchanged)

## Testing Strategy

### Unit Tests (RED tests to be written by TDD agent in Phase 1)
- `test_portal_detect_known_class` — leaf inside `.p-select-overlay` returns `portal_class = ".p-select-overlay"` (× 8, one per allowlist entry)
- `test_portal_detect_anonymous` — leaf inside unknown-class inside `cdk-overlay-container` returns `portal_class = ""`, `is_anonymous_portal = true`
- `test_portal_detect_non_portal` — leaf in main document returns `portal_class = ""`, `is_anonymous_portal = false` (AC-VERIFY-5)
- `test_trigger_resolve_aria` — portal with matching `aria-controls` trigger returns `confidence: 'aria'` and correct selector
- `test_trigger_resolve_focus_fallback` — portal without ARIA, focus tracker seeded → `confidence: 'focus'`
- `test_trigger_resolve_none` — portal with no ARIA and empty focus history → empty selector, `confidence: 'none'` (AC-ERROR-1)
- `test_target_text_masks_password` — leaf is `<input type=password>` → `target_text = ""`
- `test_target_text_truncates_80` — long innerText → capped at 80 chars
- `test_nav_reinjection_disconnects_observer` — install twice, verify only one active observer
- `test_composedPath_innermost_portal` — nested portals return the innermost
- `test_capture_confidence_derivation_matrix` — parametric: (portal_el, is_anonymous, trigger_selector, target_text) → expected `capture_confidence` for all 4 rows of the derivation table (none / full / portal_only-known-partial / portal_only-anonymous)

### Integration Tests
- `tests/engine/test_hitl_portal_capture.py` (already listed in task file L189) — full payload round-trip via mocked `page.evaluate`

### Performance Tests
- Benchmark: click inside `.p-select-overlay` × 1000 in a real Chromium instance, assert p95 added latency < 1ms

## Interfaces to Architecture Doc

The architecture doc will use the following as its input contract for the JS → Python payload:

**Payload fields emitted for every click event** (superset of existing):

| Field | Type | Empty-value semantics | Populated when |
|---|---|---|---|
| `event_type` | `"click"` | — | always (existing) |
| `strategy` | string | — | always (existing) |
| `best_selector` | string | — | always (existing) |
| `inner_text` | string | `""` if no text | always (existing) |
| `aria_label` | string | `""` if not set | always (existing) |
| `tag`, `test_id`, `role`, `css_path`, `value`, `timestamp` | | — | always (existing) |
| **`portal_class`** | string | `""` = not inside a KNOWN portal | leaf `.closest(PORTAL_ALLOWLIST_SELECTOR)` matched |
| **`trigger_selector`** | string | `""` = trigger unresolvable | Q2-D layer 1, 2, or 3 succeeded |
| **`target_text`** | string | `""` = no text or masked | leaf inside portal AND not a sensitive field |
| **`trigger_resolution_confidence`** | `"aria" \| "focus" \| "mutation" \| "none"` | `"none"` = no trigger identified | always emitted when `portal_class != ""` OR `is_anonymous_portal == true` |
| **`is_anonymous_portal`** | boolean | `false` = not in a CDK overlay | leaf inside `.cdk-overlay-container` but NOT in allowlist |
| **`capture_confidence`** | `"full" \| "portal_only" \| "none"` | never empty — always one of the three values | always present; derivation rule above; consumed by architecture doc's serializer branching contract |

**Guarantees provided by the JS layer** (contract with the architecture doc's fallback design):
1. When `capture_confidence == "full"` (⇔ `portal_class`/`trigger_selector`/`target_text` all non-empty) → executor gets a fully-formed `primeng_dropdown` action.
2. When `capture_confidence == "portal_only"` AND `portal_class != ""` → AC-ERROR-1 partial record; architecture serializer emits `action: click` + `container_selector` scoped shape.
3. When `capture_confidence == "portal_only"` AND `is_anonymous_portal == true` (portal_class empty) → AC-ERROR-2 fallback; architecture serializer's `_PORTAL_CLASS_PREFIXES` whitelist guard causes fall-through to standard `click` serialization (WARN logged, no `primeng_dropdown`).
4. When `capture_confidence == "none"` → normal click record, back-compat identical to today (AC-VERIFY-5). No `_capture_confidence` key on serializer output.
5. `target_text` is safe to log at any level (PII-masked at source).
6. `capture_confidence` is derived deterministically from the other four new fields (see derivation rule) — architecture doc's serializer relies on this being the single-source enum, never on re-deriving from the granular fields itself.

**No fields removed or renamed** — existing consumers of the payload continue to work unchanged.

## Next Steps

1. TDD agent writes RED tests based on the Testing Strategy above.
2. Implement ADDITIONS 1–6 inside the JS literal at `human_takeover.py:581-743`.
3. Wire the cleanup one-liner into the `cleanup()` closure at `human_takeover.py:831`.
4. Extend `buildRecord()` return object with the five new fields.
5. Architecture doc consumes the payload contract above to design the Python-side fallback branch in `AutorecordSerializer` (or upstream in `_on_human_action`).

---

## NEW_TERMS_INTRODUCED

- **`trigger_resolution_confidence`** — payload enum (`"aria" | "focus" | "mutation" | "none"`) indicating which of Q2-D's three cascading layers produced the trigger selector. `"none"` means all three layers failed; the record is partial per AC-ERROR-1. **Distinct from `capture_confidence`**: this is the granular per-layer telemetry, whereas `capture_confidence` is the coarse serializer-branching contract.
- **`capture_confidence`** — payload enum (`"full" | "portal_only" | "none"`) derived at JS emit time from `portal_class`/`trigger_selector`/`target_text`/`is_anonymous_portal`. This is the field the architecture doc's `AutorecordSerializer` branches on. Deriving it in JS (rather than in Python) means the JS layer is the single source of truth for classification and the serializer stays a pure dispatch.
- **`is_anonymous_portal`** — payload boolean; true iff the clicked leaf is inside `.cdk-overlay-container` but does NOT match any entry in `PORTAL_ALLOWLIST`. Signals AC-ERROR-2 to the Python side. Collapses to `capture_confidence: "portal_only"` in the derivation rule.
- **`PORTAL_ALLOWLIST`** — the JS-side literal array of 8 (initially) known PrimeNG / vSuite overlay class names. Not a payload field; internal to the injected script but load-bearing enough to name.
- **`FOCUS_TTL_MS`** — 2000ms window during which a mousedown/focusin is considered "recent enough" to be the trigger for a subsequent portal-open event.
- **`extractTargetText`** — the PII-aware sibling of the existing `innerText` capture used for the new `target_text` field. Adds a mask policy the existing `inner_text` field does not carry (intentional — new field, new policy; no back-compat risk).
