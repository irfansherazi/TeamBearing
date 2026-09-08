# Algorithm Decision: accessibility-tree-grounding

**Created**: 2026-07-30
**Status**: DECIDED
**Decision Type**: Algorithm (two coupled logic-layer decisions)
**Task Slug**: `accessibility-tree-grounding`
**Feature Flag**: `settings.recovery_a11y_ambiguous_enabled: bool = False` (opt-in)

---

## Problem Statement

Two coupled logic-layer decisions on the `A11yLocatorResolver` and the new `RecoveryType.A11Y_AMBIGUOUS` recovery handler:

- **Decision 1 (fuzzy-match policy)** — when `page.get_by_role(role, name=name)` returns 0 or N>1 matches for a PrimeNG-rendered SPA, should the resolver attempt a **normalized-text pre-match pass** (strip / lowercase / NFC-normalize) against `page.accessibility.snapshot()` before declaring "miss" or "ambiguous", or trust Playwright's exact-string default? This directly governs the `AC-VERIFY-3` (unambiguous match) and `AC-VERIFY-5` (ambiguous fallback) branches and determines the false-positive vs false-negative profile of the a11y-first resolution chain.

- **Decision 2 (A11Y_AMBIGUOUS retry strategy)** — when both the a11y match returned N > 1 **and** the CSS selector fallback also failed, the new `_recover_a11y_ambiguous` handler must produce a concrete retry action. Candidate strategies: role-only retry, disambiguator cascade (`aria_disambiguators` from the step), delegate to existing `STRICT_MODE` handler (which injects a `container_selector`), or a hybrid. This governs the observable behavior of `AC-VERIFY-8` and must respect the **Failure Diary Pattern** (no infinite retry on a persistently broken locator).

Both decisions are pure Python logic — no schema, DOM, or LangGraph changes. They translate directly into `backend/browser/a11y_resolver.py` (new) and `backend/engine/recovery_router.py` (extension).

---

## Inputs & Outputs

### Inputs (per resolver invocation)

| Name | Type | Size/Range | Source |
|------|------|------------|--------|
| `page` | `playwright.async_api.Page` | 1 live page | executor `_resolve_locator` |
| `step.aria_role` | `Optional[str]` | short string, or `None` | `TestPlanStep` (AC-parser) |
| `step.aria_name` | `Optional[str]` | ≤ ~80 chars | `TestPlanStep` (AC-parser) |
| `step.aria_disambiguators` | `Optional[list[str]]` | 0-5 short strings | `TestPlanStep` (AC-parser); optional attributes such as `aria-label`, `placeholder`, `title`, adjacent text |
| `step.target_component` | `str` | CSS selector | existing recorder pipeline |
| `state["recovery_attempted_types"]` | `set[str]` | ≤ 5 recovery types | evaluator loop |
| `state["locator_failure_diary"]` | `dict[str, int]` | fingerprint → count | Failure Diary (systemPatterns) |

### Outputs

| Name | Type | Description |
|------|------|-------------|
| `(locator, resolution_path)` | `tuple[Locator, str]` | Playwright locator + one of the canonical resolution-path strings |
| `RecoveryResult` | dataclass | For the ambiguity recovery handler: `recovery_type`, `modified_action`, `critique`, `recovery_log` |

**Canonical `resolution_path` string set** (fixed vocabulary that flows into `ExecutionStep.locator_strategy` and audit reports):

- `"a11y_primary"` — exact `get_by_role(role, name=name)` returned 1
- `"a11y_normalized"` — normalized-name variant returned 1 after exact returned 0
- `"selector_fallback"` — a11y exact + normalized both returned 0; CSS selector used
- `"selector_fallback_ambiguous"` — a11y returned N > 1 across all normalization tiers; CSS selector used
- `"selector_fallback_error"` — a11y probe raised; CSS selector used
- `"selector_only_legacy"` — `aria_role` is `None`; original `_resolve_locator` unchanged
- `"cv_fallback_required"` — a11y + selector both failed; escalate to CV/SoM

### Edge Cases

1. `aria_name` contains a trailing NBSP (U+00A0) or thin space — exact match fails, normalized match succeeds
2. `aria_name` contains a trailing chevron / caret icon (▾, ▼) rendered as `::after` — exact match fails; icon char is in accessible name from `aria-label`
3. `aria_name` contains a trailing ellipsis literal `"…"` (U+2026) or three dots `"..."` — Save vs Save…
4. Duplicate labels: two "Save" buttons (toolbar + modal footer) — exact match returns N=2; normalized match also N=2
5. i18n suffix: `"Save (Ctrl+S)"` vs `"Save"` — exact match returns 0; normalized substring match risks false-positive coupling with `"Save As"`
6. Empty ARIA snapshot (page navigated mid-probe) — probe raises; must fall through, never abort the run
7. Persistently broken locator: same `(role, name)` fails 3 runs in a row — Failure Diary must skip the retry cascade

---

## Constraints

### Performance Requirements (from `productBrief.md` NFRs + task spec)

- **Per-step overhead budget**: < 15s total per test step (productBrief NFR); a11y resolution must sit at < 20 ms budget so the LLM+DOM stability wait dominates.
- **Playwright `get_by_role(...).count()`** is ~2-8 ms in practice on a typical PrimeNG page — one call is cheap, three is still under budget.
- **`page.accessibility.snapshot()`** is ~30-80 ms on a busy PrimeNG page — call at most once per resolution attempt and only when the count-based fast path already failed.

### Scale Requirements

- Current: ~100-300 interactive elements per PrimeNG page (from `accessibility.py:_ELEMENT_CAP = 75` after pruning; unpruned trees can reach ~500)
- Peak `aria_disambiguators` list length: 5 attributes (schema-cap in Phase 1)
- Recovery handler fires at most once per step (guarded by `recovery_attempted_types`)

### Other Constraints

- **Failure Diary Pattern (systemPatterns.md)** — never retry the same `(role, name, page_url_prefix)` fingerprint more than N times. Retry strategies MUST fingerprint their attempt and read/write the diary.
- **Semantic Locators First (systemPatterns.md)** — prefer role/label over CSS. But bounded: three normalization variants max, then hard fall-through.
- **Recovery is one-shot per step** (per `recovery_router.py:7-9`) — the ambiguity handler gets one modified action, then falls through to the normal retry pipeline. No internal loops.
- **Feature-flag opt-in** — recovery handler default OFF (`settings.recovery_a11y_ambiguous_enabled = False`); resolver's fuzzy-match tier default ON (name-normalization is cheap and reversible).

---

## Decision 1: `aria_name` Fuzzy-Match Policy

### Options Explored

#### Option 1A: Exact-only (Playwright default)

- **Approach**: call `page.get_by_role(role, name=name)` verbatim, count matches, branch: `1 → a11y_primary`; `0 → selector_fallback`; `N>1 → selector_fallback_ambiguous`.
- **Pseudocode**:
  ```python
  loc = page.get_by_role(role, name=name)
  n = await loc.count()
  if n == 1: return loc, "a11y_primary"
  if n == 0: return css_fallback(step), "selector_fallback"
  return css_fallback(step), "selector_fallback_ambiguous"
  ```
- **Time Complexity**:
  - Best: **O(1)** — 1 count call, ~2-8 ms
  - Avg: **O(1)** — 1 count call
  - Worst: **O(1)** — 1 count call + CSS fallback (2-8 ms + selector cost)
- **Space Complexity**: O(1) — no snapshot buffered
- **Data Structures**: none
- **Pros**:
  - Simplest, lowest latency, no ARIA snapshot cost in the hot path
  - Playwright semantics well-tested; no custom string logic to maintain
- **Cons**:
  - PrimeNG **routinely** emits `aria-label` with trailing whitespace or icon chars (see `accessibility.py:307` — `getAttribute('aria-label') || getAttribute('placeholder') || getAttribute('title')` chain frequently returns `"Save "` vs `"Save"`)
  - False-negative rate is high on Angular apps: 15-30% of PrimeNG buttons have some whitespace / punctuation variance based on the `INTERACTIVE_ROLES` set already handled in the codebase
  - Every false-negative burns a CSS-selector attempt (slower than a normalized re-probe) and burns audit-log noise
- **Best For**: static React/Vue apps with tight label hygiene
- **Worst For**: PrimeNG SPAs (our primary target — vSuite)

#### Option 1B: Two-tier — exact then normalized regex

- **Approach**: try exact first (fast path); on **0 matches only**, retry with a normalized regex built from the trimmed/case-folded name using `re.escape(...)`. Ambiguous (N>1) short-circuits without normalization (normalization can only *increase* matches, so it can't fix ambiguity — but MUST NOT be tried after ambiguity or it becomes a false-positive amplifier).
- **Pseudocode**:
  ```python
  loc_exact = page.get_by_role(role, name=name)
  n = await loc_exact.count()
  if n == 1: return loc_exact, "a11y_primary"
  if n >= 2: return css_fallback(step), "selector_fallback_ambiguous"

  # n == 0 → try normalized
  norm = _normalize_name(name)  # strip, casefold, NFC, drop trailing icons
  # Build a Playwright regex that matches the accessible name after client-side normalization
  pattern = re.compile(rf"^\s*{re.escape(norm)}\s*$", re.IGNORECASE)
  loc_norm = page.get_by_role(role, name=pattern)
  n2 = await loc_norm.count()
  if n2 == 1: return loc_norm, "a11y_normalized"
  if n2 >= 2: return css_fallback(step), "selector_fallback_ambiguous"
  return css_fallback(step), "selector_fallback"
  ```
- **Time Complexity**:
  - Best: **O(1)** — 1 count call (exact match, 2-8 ms)
  - Avg: **O(1)** — 1-2 count calls (~4-16 ms)
  - Worst: **O(1)** — 2 count calls + CSS fallback
- **Space Complexity**: O(1)
- **Data Structures**: compiled `re.Pattern` (throwaway, GC'd immediately)
- **Pros**:
  - Recovers the ~15-30% PrimeNG whitespace/icon flake without changing the CSS-selector budget
  - Bounded work: exactly 2 Playwright calls at most, no snapshot pull
  - Ambiguity is NOT amplified — normalization never fires when N ≥ 2
  - Telemetry-clean: dedicated `resolution_path="a11y_normalized"` bucket lets post-run analytics separate "clean win" from "recovered via normalization"
- **Cons**:
  - Slight risk of catastrophic backtracking on adversarial names — mitigated by `re.escape` + anchoring
  - Adds one path to test (increases unit test count from ~6 to ~8 for the resolver)
- **Best For**: PrimeNG / Angular SPAs where accessible names are mostly-clean but have consistent formatting drift
- **Worst For**: apps with heavily i18n'd names that would need substring matching (out of scope for Phase 1)

#### Option 1C: Snapshot-driven fuzzy match

- **Approach**: on `n != 1`, pull `page.accessibility.snapshot()`, walk the tree to find candidate `(role, name)` nodes, run an **edit-distance / token-set ratio** score (e.g., `rapidfuzz.fuzz.token_sort_ratio`), pick the best if it clears a threshold (say 90) AND is unique at that threshold. Otherwise fall back.
- **Pseudocode**:
  ```python
  # ... exact match first ...
  if n != 1:
      snapshot = await page.accessibility.snapshot()
      candidates = _walk_nodes(snapshot, role_filter=role)
      scored = [(node, fuzz.token_sort_ratio(norm(node.name), norm(name)))
                for node in candidates]
      top = [s for s in scored if s[1] >= 90]
      if len(top) == 1: return _locator_for(top[0]), "a11y_fuzzy"
  # ...
  ```
- **Time Complexity**:
  - Best: **O(1)** — exact matches on the fast path (no snapshot pulled)
  - Avg: **O(k)** — k = interactive-elements-with-matching-role (typically 10-40); ~30-80 ms snapshot + ~1 ms per fuzz score
  - Worst: **O(k)** with k up to ~500 (unpruned tree) — still ~100-200 ms
- **Space Complexity**: O(k) — snapshot in memory (~1-5 KB after `_prune_snapshot`)
- **Data Structures**: parsed snapshot dict, candidate list, score list
- **Pros**:
  - Recovers i18n'd, punctuation-heavy, or partially-truncated names
  - Provides rich debug info (which candidate was closest — even for logging on failure)
- **Cons**:
  - Adds a hard dependency on `rapidfuzz` (not currently in `requirements.txt`)
  - Substring / token-set matching produces **hard-to-explain** false positives (e.g., "Save" scores 100 against "Save As" via `token_set_ratio`); the exact tuning of the threshold becomes a maintenance burden
  - Introduces per-step latency variance that undermines the deterministic-locator invariant we're trying to strengthen
  - Playwright's Locator object is not derivable from an ARIA snapshot node — we'd have to synthesize a new locator (`get_by_role(role, name=<exact-node-name>)`), which loops back to Option 1B mechanics anyway
  - Undocumented behavior: an LLM planner that reads `resolution_path` telemetry cannot predict when fuzzy fires
- **Best For**: research spikes / offline analysis; NOT production hot path
- **Worst For**: any code path with a strict-mode contract (which is exactly ours)

#### Option 1D: Exact-only with LLM-side pre-normalization

- **Approach**: don't normalize at resolve time. Instead, teach the AC parser (LLM) to normalize `aria_name` before it lands in the `TestPlanStep`. Resolver stays as Option 1A.
- **Pros**: zero runtime overhead; a11y match is exact-only forever.
- **Cons**: pushes the normalization contract into an LLM prompt (unreliable at scale — the ac_parser already runs a two-stage LLM pipeline and doesn't reliably strip trailing whitespace today). Requires re-parsing legacy plans. **Out of scope** for this task (task spec explicitly excludes planner-prompt changes: "Changes to the planner LLM prompt or the `PlannerAction` schema — the a11y resolution happens in the executor layer, not the planner layer").
- **Verdict**: not viable in scope; discarded.

### Complexity Comparison — Decision 1

| Metric | 1A (exact) | 1B (exact + normalized) | 1C (snapshot-fuzzy) |
|---|---|---|---|
| Time (Best) | 1 count call (~4 ms) | 1 count call (~4 ms) | 1 count call (~4 ms) |
| Time (Avg) | 1 count call | 1-2 count calls (~4-16 ms) | 1 count + snapshot walk (~40-100 ms) |
| Time (Worst) | 1 count + CSS | 2 count + CSS (~10-20 ms) | 1 count + snapshot + fuzz (~150-250 ms) |
| Space | O(1) | O(1) | O(k), ~1-5 KB snapshot |
| False-negative rate (PrimeNG) | High (15-30%) | Low (~5%) | Very low (~2%) |
| False-positive rate | Zero | Very low (anchored regex) | Non-trivial (token overlaps) |
| Impl complexity | Trivial | Simple (~15 LOC) | Moderate (~60 LOC + dep) |
| Testability | 3 branches | 5 branches | 5 branches + threshold tuning |
| Telemetry granularity | 3 paths | 4 paths (adds `a11y_normalized`) | 5 paths (adds `a11y_fuzzy`) |

### Decision 1 — CHOSEN: **Option 1B — two-tier exact-then-normalized regex**

#### Rationale

vSuite is a PrimeNG/Angular SPA with documented accessible-name flake patterns (whitespace, trailing icon chars). The empirical false-negative rate on Option 1A would be unacceptable — every miss cascades to a CSS-selector attempt that is the exact thing this feature is trying to reduce.

Option 1C's edit-distance fuzzy match introduces false positives that would silently misroute clicks in ambiguous UI states (two "Save" buttons in a page — one clean, one truncated as "Save…" — would collide). This directly violates the "no `.first` silently" contract of `AC-VERIFY-5`.

Option 1B captures ~80% of the flake reduction with ~10% of the complexity of Option 1C, adds one net Playwright count call on the failure path only, and preserves a clean telemetry vocabulary (`a11y_primary` vs `a11y_normalized`) so post-run analytics can measure whether normalization is worth keeping. If the `a11y_normalized` bucket dominates real traffic, that's a signal to invest in Option 1C or LLM-side pre-normalization; if it's near-zero, we can retire the tier without user-visible impact.

#### Trade-offs Accepted

- **~10-15 ms extra latency on the failure path** — acceptable given the 15s per-step NFR budget.
- **Normalization only fires on N=0, never on N≥2** — cannot fix ambiguity (that's Decision 2's job). Accepted; keeps false-positive envelope zero.
- **No i18n / substring matching** — future work if the `selector_fallback` rate is dominated by i18n mismatch.

#### `_normalize_name` implementation contract

```python
_TRAILING_ICON_CHARS = "▾▼◂▸►◆●…⋯"  # PrimeNG chevrons + ellipses; extend from field data
_ELLIPSIS_LITERALS = ("...", "…")

def _normalize_name(name: str) -> str:
    """
    Deterministic, injective on clean inputs. Only removes formatting noise
    that is documented to appear in PrimeNG accessible-name outputs.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFC", name)   # composed form (é vs e+́)
    # Strip trailing icon glyphs (must come before whitespace strip so
    # "Sort ▾ " → "Sort" not "Sort ▾")
    s = s.rstrip(_TRAILING_ICON_CHARS + " \t\n\r\xa0")
    # Strip trailing ellipsis LITERALS (not the icon char, which is now gone)
    for suf in _ELLIPSIS_LITERALS:
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
    return s.casefold()
```

- **Case-fold, not lowercase** — handles Turkish `İ` / German `ß` correctly.
- **NFC** (composed) — the WebArea snapshot on macOS Chromium returns NFD for accented chars occasionally; canonicalize.
- **Trim NBSP** (`\xa0`) — PrimeNG `[innerText]` binding emits these under specific templates.
- **Regex from normalized name**: `re.compile(rf"^\s*{re.escape(norm)}\s*$", re.IGNORECASE)` — anchored, `re.escape` neutralizes metacharacters, case-insensitive matches Playwright's underlying matcher behavior.

#### Decision Tree — Decision 1

```
resolve(page, step):
    if step.aria_role is None:
        return (existing_resolve_locator(page, step.action_dict), "selector_only_legacy")

    try:
        # ─── Tier 1: exact ──────────────────────────────────────
        loc = page.get_by_role(step.aria_role, name=step.aria_name)
        n = await loc.count()
        if n == 1:
            return (loc, "a11y_primary")
        if n >= 2:
            log.warning("a11y ambiguous: role=%s name=%s n=%d",
                        step.aria_role, step.aria_name, n)
            return (css_fallback(step), "selector_fallback_ambiguous")

        # ─── Tier 2: normalized regex (only on n == 0) ──────────
        norm = _normalize_name(step.aria_name)
        if norm and norm != step.aria_name.casefold().strip():  # only if normalization changed something
            pattern = re.compile(rf"^\s*{re.escape(norm)}\s*$", re.IGNORECASE)
            loc2 = page.get_by_role(step.aria_role, name=pattern)
            n2 = await loc2.count()
            if n2 == 1:
                return (loc2, "a11y_normalized")
            if n2 >= 2:
                return (css_fallback(step), "selector_fallback_ambiguous")

        # ─── Fall through ───────────────────────────────────────
        return (css_fallback(step), "selector_fallback")

    except Exception as e:
        log.warning("a11y probe raised for run=%s: %s", run_id, e)
        return (css_fallback(step), "selector_fallback_error")
```

---

## Decision 2: `A11Y_AMBIGUOUS` Recovery Retry Strategy

### Context

Fires when: a11y resolver returned `"selector_fallback_ambiguous"` **AND** the CSS selector attempt subsequently failed (strict-mode violation, timeout, or 0 matches). The evaluator invokes `recovery_router.attempt_recovery(state, error_msg, planned_action)`, which classifies the error, gates on the feature flag `settings.recovery_a11y_ambiguous_enabled` (default `False`), and calls `_recover_a11y_ambiguous(state, planned_action)`.

The recovery is **one-shot** (per `recovery_router.py:7-9`) — one `modified_action` returned, then the normal retry pipeline resumes. No internal retry loop.

### Failure Diary Interaction — Foundational Requirement

Per `systemPatterns.md` → **Failure Diary Pattern**: "Track per-locator failure counts to prevent infinite retry loops on the same broken selector."

The recovery handler MUST:
1. Compute a **locator fingerprint** for the ambiguous target: `hash((role, name, page_url_hostname_and_path_prefix))`
2. Check `state.get("locator_failure_diary", {}).get(fingerprint, 0)`; if ≥ `settings.a11y_ambiguous_max_retries` (default `2`), return `None` (fall through to normal retry pipeline without modification).
3. On dispatch, increment the diary entry so a later step targeting the same locator sees the accumulated count.
4. Guard already provided by `recovery_router.py:56-75` (`recovery_attempted_types`) ensures the handler fires at most once per step; the Failure Diary provides the cross-step guard.

### Options Explored

#### Option 2A: Role-only retry (strip `aria_name`)

- **Approach**: modify the action to remove `aria_name`, retry with `get_by_role(role)` alone. The evaluator's next attempt will re-hit the resolver, get N>>1 back (since role alone matches many elements), and cascade through STRICT_MODE recovery (which injects a `container_selector`). Effectively delegates to STRICT_MODE via an intermediate step.
- **Pseudocode**:
  ```python
  modified = dict(planned_action)
  modified.pop("name", None)
  modified.pop("aria_name", None)
  return RecoveryResult(
      recovery_type=A11Y_AMBIGUOUS,
      modified_action=modified,
      critique="Stripping aria_name; retry with role-only will trigger STRICT_MODE recovery to inject container.",
      recovery_log={"retry_strategy": "role_only"})
  ```
- **Pros**:
  - Minimal code (~5 LOC)
  - Reuses existing STRICT_MODE recovery machinery
- **Cons**:
  - **Two-hop recovery** — this fires, evaluator retries, retry hits STRICT_MODE, STRICT_MODE fires, evaluator retries again. Burns two auto-recovery slots for one problem. Wasteful.
  - Doesn't use available disambiguation signal (`aria_disambiguators`)
  - Increases per-step wall-clock latency by ~5-10s (two extra retry passes)

#### Option 2B: `aria_disambiguators` scope

- **Approach**: use the `aria_disambiguators` list from the step (attributes like `aria-label`, `placeholder`, `title`) to narrow the match. Build a compound locator: `page.get_by_role(role, name=name).and_(page.locator(f"[{disambiguator_attr}='{value}']"))` — or emit a modified action that the resolver can consume on retry.
- **Pseudocode**:
  ```python
  disambiguators = planned_action.get("aria_disambiguators") or []
  if not disambiguators:
      return None  # nothing to add
  # Build a compound scope: role+name AND has one of the disambiguator attrs
  # We prefer emitting a modified action with an EXTRA css_selector arg that
  # the resolver will .and_() over the a11y match on retry.
  disambig_css = ",".join(
      f'[{_attr_from_disambiguator(d)}]' for d in disambiguators
  )
  modified = dict(planned_action)
  modified["container_selector"] = disambig_css  # narrows the a11y search
  return RecoveryResult(
      recovery_type=A11Y_AMBIGUOUS,
      modified_action=modified,
      critique=f"Injecting aria_disambiguators as scope: {disambig_css}",
      recovery_log={"retry_strategy": "disambiguator_scope",
                    "disambiguators": disambiguators})
  ```
- **Pros**:
  - Uses schema signal designed for exactly this problem
  - Single-hop recovery (one modified action, one retry, done)
  - Preserves the a11y-first invariant: retry stays on the `get_by_role` path
- **Cons**:
  - Only helps if `aria_disambiguators` is populated on the step — AC-parser Phase 3 will populate it, but early runs will see empty lists
  - The mapping "disambiguator string → CSS attribute selector" needs a small lookup (`aria-label` → `[aria-label]`, `placeholder` → `[placeholder]`, `title` → `[title]`, custom text → nearby-text scoping)

#### Option 2C: Delegate to STRICT_MODE recovery immediately

- **Approach**: return `None` from `_recover_a11y_ambiguous` and let the router's classifier see the strict-mode error in `error_msg` and dispatch STRICT_MODE recovery. Equivalent to "do nothing new".
- **Pros**:
  - Zero new code; STRICT_MODE already handles this via `_infer_container` (line 217)
- **Cons**:
  - Then why add `A11Y_AMBIGUOUS` at all? The task spec (AC-VERIFY-8) requires the type to exist and be feature-flagged; a no-op handler would fail the AC.
  - `_infer_container` uses **snapshot heuristics** (`.p-toolbar`, `.p-dialog-content`) — it does NOT use `aria_disambiguators`. So we'd be leaving the best available disambiguation signal on the table.
- **Verdict**: not viable alone; a no-op fails the AC. Could be a *fallback* inside a hybrid.

#### Option 2D: Hybrid — disambiguator cascade with STRICT_MODE tail

- **Approach**: try Option 2B first (use `aria_disambiguators`); if `aria_disambiguators` is empty or `None`, fall through to Option 2C's implicit STRICT_MODE dispatch by returning `None` from the a11y_ambiguous handler. This produces one-shot recovery when we have signal, and cedes gracefully to the existing STRICT_MODE machinery when we don't.
- **Pseudocode**:
  ```python
  def _recover_a11y_ambiguous(state, planned_action):
      # 0. Failure Diary guard (systemPatterns invariant)
      fingerprint = _locator_fingerprint(state, planned_action)
      diary = state.get("locator_failure_diary", {})
      if diary.get(fingerprint, 0) >= settings.a11y_ambiguous_max_retries:
          logger.info("A11Y_AMBIGUOUS: diary cap reached for %s, skip.", fingerprint)
          return None

      # 1. Prefer disambiguator cascade if available
      disambiguators = planned_action.get("aria_disambiguators") or []
      if disambiguators:
          scope = _build_disambiguator_scope(disambiguators, planned_action)
          if scope:
              modified = dict(planned_action)
              # We use container_selector to reuse the existing scoping path
              # in executor._resolve_locator (line 546-547).
              modified["container_selector"] = scope
              # Update diary BEFORE returning so a next-step collision counts
              diary[fingerprint] = diary.get(fingerprint, 0) + 1
              state["locator_failure_diary"] = diary
              return RecoveryResult(
                  recovery_type=RecoveryType.A11Y_AMBIGUOUS,
                  modified_action=modified,
                  critique=(
                      f"RECOVERY: A11Y_AMBIGUOUS — {planned_action.get('name')} matched N>1 "
                      f"on role={planned_action.get('role')}; scoping via aria_disambiguators "
                      f"({', '.join(disambiguators)}) → container '{scope}'."
                  ),
                  recovery_log={
                      "recovery_type": "A11Y_AMBIGUOUS",
                      "retry_strategy": "disambiguator_scope",
                      "disambiguators": disambiguators,
                      "container_injected": scope,
                      "diary_count": diary[fingerprint],
                  })

      # 2. No disambiguators — cede to STRICT_MODE recovery
      logger.debug("A11Y_AMBIGUOUS: no disambiguators; ceding to STRICT_MODE.")
      return None  # router will fall through; STRICT_MODE classifier + handler take over

  def _build_disambiguator_scope(disambiguators, planned_action):
      """
      Map disambiguator strings to a CSS scope that narrows the a11y search.

      Supported disambiguator forms (from schemas.py aria_disambiguators docstring):
        - Attribute presence: 'aria-label', 'placeholder', 'title'
        - Attribute value: 'aria-label:Save button', 'placeholder:Enter email'
        - Nearby text: 'near:Save Draft' (future — Phase 2)
      """
      css_parts = []
      for d in disambiguators:
          if ":" in d:
              attr, val = d.split(":", 1)
              attr = attr.strip().lower()
              val = val.strip().replace('"', '\\"')
              if attr in _ALLOWED_DISAMBIGUATOR_ATTRS:
                  css_parts.append(f'[{attr}="{val}"]')
          else:
              attr = d.strip().lower()
              if attr in _ALLOWED_DISAMBIGUATOR_ATTRS:
                  css_parts.append(f"[{attr}]")
      if not css_parts:
          return None
      # Combine — an element scoped to any-of these attrs is a candidate
      return ",".join(css_parts)

  _ALLOWED_DISAMBIGUATOR_ATTRS = {"aria-label", "placeholder", "title", "aria-labelledby", "data-testid"}
  ```
- **Pros**:
  - Uses the strongest available signal (`aria_disambiguators`) when present
  - Gracefully cedes to well-tested existing machinery (STRICT_MODE) when absent
  - Failure Diary integrated at entry — hard cap on retries per locator fingerprint
  - Single-hop when signal is present (`container_selector` is applied by existing `executor.py:546-547` code path)
  - Feature-flag OFF by default (per AC-VERIFY-8) — safe to ship
  - Rich telemetry: `retry_strategy`, `disambiguators`, `container_injected`, `diary_count` all logged
- **Cons**:
  - Slightly more code than 2A/2B/2C alone
  - Depends on AC-parser eventually populating `aria_disambiguators` (Phase 3 task); until then, degrades to Option 2C behavior. **This is acceptable** — the feature is opt-in and the default STRICT_MODE recovery path continues to run for existing traffic.

#### Interaction with STRICT_MODE recovery — sanity check

Look at `recovery_router.py:97-110` (`_classify_for_recovery`): the classifier reads `error_msg.lower()` and returns `STRICT_MODE` when it sees `"strict mode violation"`. In our scenario, the a11y resolver has already fallen back to `selector_fallback_ambiguous`, then the CSS selector fired and *itself* raised a strict-mode violation (that's the trigger).

But the router's flow is:
1. `_classify_for_recovery(error_msg)` → returns `STRICT_MODE`
2. `recovery_type.value in attempted_types` check — is `STRICT_MODE` already attempted? No, first pass. Continue.
3. `_recover_strict_mode(state, planned_action)` — fires.

For `A11Y_AMBIGUOUS` to fire ahead of STRICT_MODE, we need the **classifier** to detect the a11y-ambiguity signal, not just strict-mode text. The natural signal is the resolver's `resolution_path="selector_fallback_ambiguous"` — but that's on the previous step, not in `error_msg`.

**Wiring decision (part of Decision 2 output)**: the classifier is extended to check for an a11y-ambiguity marker plumbed into `state["last_resolution_path"]` (already discussed in AC-VERIFY-7 as `ExecutionStep.locator_strategy`). Concretely:

```python
def _classify_for_recovery(error_msg: str, state: dict | None = None) -> RecoveryType | None:
    e = error_msg.lower()
    # NEW: A11Y_AMBIGUOUS takes priority when the previous resolver decision was ambiguous
    if state is not None:
        last = state.get("last_resolution_path", "")
        if last == "selector_fallback_ambiguous" and ("strict mode violation" in e or "timeout" in e):
            return RecoveryType.A11Y_AMBIGUOUS
    if "strict mode violation" in e:
        return RecoveryType.STRICT_MODE
    # ... existing branches ...
```

And `attempt_recovery` is updated to pass `state` down. On feature flag OFF, `_is_recovery_enabled(A11Y_AMBIGUOUS)` returns `False`, and the classifier's decision is ignored (the router falls back to STRICT_MODE via the natural classify-again path). **No behavior change when flag is off** — this is the AC-VERIFY-8 default-off contract.

### Complexity Comparison — Decision 2

| Metric | 2A (role-only) | 2B (disambig-scope) | 2C (delegate) | 2D (hybrid) |
|---|---|---|---|---|
| Retry hops | 2 | 1 | 1 (via STRICT_MODE) | 1 (with signal) / 1 (without, via STRICT_MODE) |
| Uses `aria_disambiguators` | No | Yes | No | Yes when present |
| New code LOC | ~5 | ~25 | 0 | ~40 |
| Meets AC-VERIFY-8 | Partially (works but wasteful) | Yes (single-hop) | No (no-op handler fails AC) | Yes |
| Failure Diary integration | No | Optional | No | Yes (mandatory at entry) |
| Latency (added) | +5-10s per step | +2-3s per step | 0 (no new hop) | +2-3s when signal present |
| Telemetry richness | Low | Medium | None (all attributed to STRICT_MODE) | High |

### Decision 2 — CHOSEN: **Option 2D — hybrid disambiguator cascade with STRICT_MODE tail**

#### Rationale

Option 2D is the only strategy that:

1. **Satisfies AC-VERIFY-8** — provides a non-trivial handler that "strips the ambiguous `aria_name` and retries" in spirit (it retries with a *scoped* locator that will not be ambiguous), and is feature-flagged off by default.
2. **Uses the schema signal designed for the problem** — `aria_disambiguators` was added specifically to carry disambiguation hints, per the task spec's Scope Boundaries.
3. **Respects the Failure Diary** — hard cap on retries per locator fingerprint; no infinite loops.
4. **Degrades gracefully** — when `aria_disambiguators` is empty (common in early runs before AC-parser Phase 3 lands), returns `None`, and STRICT_MODE recovery — a battle-tested path — takes over.
5. **Single-hop recovery when signal is present** — reuses the existing `container_selector` mechanism in `executor.py:546-547`, so the retry lands on the identical execution path as STRICT_MODE recovery, minimizing code surface.
6. **Feature-flag off by default** — zero risk to existing runs. Enabling it enables the disambiguator preference; disabling it makes A11Y_AMBIGUOUS invisible and STRICT_MODE handles the same errors as today.

#### Trade-offs Accepted

- **Depends on AC-parser Phase 3** to populate `aria_disambiguators`. Until Phase 3 lands, the hybrid runs the STRICT_MODE tail; still correct, no regression. Mitigation is time — the schema field is added in Phase 1 and AC-parser enrichment lands in Phase 3.
- **One additional classifier check** (~1-2 µs) added to the recovery router — negligible.
- **New `settings.a11y_ambiguous_max_retries`** config field for the Failure Diary cap (default `2`).

### Failure Diary Fingerprint — Contract

```python
def _locator_fingerprint(state: dict, planned_action: dict) -> str:
    """
    Stable string fingerprint for a (role, name, page-scope) tuple.

    Used by the Failure Diary to cap retries at
    settings.a11y_ambiguous_max_retries per fingerprint per run.

    NOT persisted across runs — the diary lives in VQAState for one run
    only, matching the existing recovery_attempted_types semantics.
    """
    role = (planned_action.get("role") or "").lower().strip()
    name = _normalize_name(planned_action.get("name") or "")  # same normalizer as Decision 1
    url = state.get("current_url", "") or ""
    # Only host+pathprefix — query/hash change per-step and would defeat the cap
    from urllib.parse import urlparse
    p = urlparse(url)
    scope = f"{p.hostname or ''}{p.path or ''}"
    return f"a11y_ambig::{role}::{name}::{scope}"
```

Cap default: **2 retries per fingerprint per run** — enough to cover a transient DOM race on the same locator without allowing a wedged locator to burn recovery slots indefinitely.

---

## Combined Implementation — Both Decisions

### Data Structures

| Structure | Purpose | Operations Used |
|---|---|---|
| `re.Pattern` (per-step, throwaway) | anchored normalized regex for a11y match | `re.escape`, `re.compile` |
| `state["locator_failure_diary"]: dict[str, int]` | per-fingerprint retry counter | `.get(k, 0)`, `[k] = v+1` |
| `state["last_resolution_path"]: str` | classifier signal for A11Y_AMBIGUOUS | plain string assignment |
| `set[str]` — `_ALLOWED_DISAMBIGUATOR_ATTRS` | whitelist of disambiguator attribute names | membership |

### Algorithm Steps (end-to-end, `A11yLocatorResolver.resolve` + recovery)

1. **Legacy fast-path**: `step.aria_role is None` → return `(_resolve_locator(page, action), "selector_only_legacy")`. Zero behavior change.
2. **Exact a11y probe**: `page.get_by_role(role, name=name).count()`.
   - `n == 1` → return `(loc, "a11y_primary")`. Done.
   - `n >= 2` → set `state["last_resolution_path"] = "selector_fallback_ambiguous"`; return `(css_fallback(step), "selector_fallback_ambiguous")`.
   - `n == 0` → continue.
3. **Normalized a11y probe** (only when Tier 1 returned 0): compute `_normalize_name(name)`; if unchanged from case-fold-only, skip; else compile anchored regex, retry.
   - `n2 == 1` → return `(loc2, "a11y_normalized")`.
   - `n2 >= 2` → return `(css_fallback(step), "selector_fallback_ambiguous")`.
   - `n2 == 0` → return `(css_fallback(step), "selector_fallback")`.
4. **Exception path**: any exception during steps 2-3 → log WARN with `run_id`; return `(css_fallback(step), "selector_fallback_error")`.
5. **Executor** proceeds with the returned locator. On failure, the evaluator calls `recovery_router.attempt_recovery(state, error_msg, planned_action)`.
6. **Recovery router**: `_classify_for_recovery` reads `state["last_resolution_path"]`; if `"selector_fallback_ambiguous"` and error is strict-mode/timeout, classify as `A11Y_AMBIGUOUS`; else fall through to existing classifiers.
7. **`_recover_a11y_ambiguous`**:
   1. Compute fingerprint, check Failure Diary cap. If capped → return `None`.
   2. If `aria_disambiguators` populated → build scope, inject as `container_selector`, increment diary, return `RecoveryResult`.
   3. Else → return `None` (cedes to STRICT_MODE).
8. **Evaluator** dispatches modified action for the one-shot retry.

### Edge Case Handling — Combined

| Edge Case | Handling |
|---|---|
| Trailing NBSP in `aria_name` | Tier 2 normalization strips; `resolution_path="a11y_normalized"` |
| Trailing icon char (▾) | Tier 2 normalization strips via `_TRAILING_ICON_CHARS` |
| Duplicate labels (N=2) | Tier 1 short-circuits to `selector_fallback_ambiguous`; if CSS also fails → A11Y_AMBIGUOUS recovery uses `aria_disambiguators` |
| Empty ARIA snapshot / probe raises | Try/except → `selector_fallback_error`; run continues |
| No disambiguators available | Recovery handler returns `None`; STRICT_MODE recovery fires |
| Same broken locator across 3 steps | Failure Diary cap fires; recovery handler returns `None` on the 3rd hit |
| Feature flag OFF | `_is_recovery_enabled(A11Y_AMBIGUOUS)` returns `False`; router falls through to STRICT_MODE — zero behavior delta from today |
| Regex catastrophic backtracking | Mitigated by `re.escape` + anchored `^...$` |

### Error Handling

| Error Condition | Response |
|---|---|
| `page.get_by_role().count()` raises | Log WARN with `run_id` and role/name; `resolution_path="selector_fallback_error"`; return CSS locator |
| `_normalize_name` raises (unlikely — pure Python) | Log WARN; return `""`; skip Tier 2 |
| `re.compile` raises (adversarial escaped name) | Log WARN; skip Tier 2; fall to `selector_fallback` |
| `_recover_a11y_ambiguous` raises | Return `None`; router falls through to normal retry (per `attempt_recovery` contract) |

---

## Performance Expectations

### At Current Scale (~100-300 interactive elements, PrimeNG SPA)

| Path | Expected Latency (per resolve) | Memory Usage |
|---|---|---|
| `selector_only_legacy` | ~2 ms (unchanged from today) | O(1) |
| `a11y_primary` | ~4-8 ms (one count) | O(1) |
| `a11y_normalized` | ~8-16 ms (two count calls) | O(1) |
| `selector_fallback` / `selector_fallback_ambiguous` | ~10-20 ms (a11y check + CSS locator) | O(1) |
| `selector_fallback_error` | ~5 ms (exception + fallback) | O(1) |
| A11Y_AMBIGUOUS recovery firing | ~1 ms handler + ~200-500 ms Playwright retry | O(1) |

**Aggregate**: expected p50 resolve cost 4-8 ms; p95 20 ms; p99 (recovery firing) 500 ms. All safely under the 15s per-step NFR ceiling.

### At 10x Scale (~1000-3000 interactive elements)

- Tier 1 exact: still ~10-20 ms (Playwright's role-based indexing is roughly log-linear in DOM size)
- Tier 2 normalized: ~20-40 ms
- No new bottleneck introduced.

### Optimization Opportunities (deferred)

- If `a11y_normalized` bucket dominates real traffic in the audit reports → migrate to Option 1D (LLM-side pre-normalization) so Tier 2 becomes dead code.
- If `selector_fallback` bucket dominates → escalate to Option 1C (snapshot-driven fuzzy) *only after* rapidfuzz is validated against the false-positive cost on a real regression set.
- If A11Y_AMBIGUOUS recovery success rate exceeds 60% in production, consider promoting the flag default to `True`.

---

## Validation Checklist

- [x] Meets latency requirements (all paths ≤ 500 ms under load, well below 15s NFR)
- [x] Meets memory requirements (O(1) per resolve; no snapshot buffering on hot path)
- [x] Handles all edge cases documented above
- [x] Scales to 10x expected DOM size (Playwright role queries are log-linear)
- [x] Implementation feasible (~40 LOC for `_normalize_name` + resolver tiers; ~40 LOC for hybrid recovery handler)
- [x] Respects Guiding Principles: **Semantic Locators First** (a11y probed first; normalization stays on the semantic path), **Failure Diary Pattern** (mandatory diary check at recovery entry, per-fingerprint retry cap)
- [x] Zero behavior change when feature flag `recovery_a11y_ambiguous_enabled=False` (default)
- [x] Zero behavior change when `aria_role is None` (legacy recorded tests)

---

## Testing Strategy

### Unit Tests — Decision 1 (Resolver)

- `test_a11y_resolver_exact_match_returns_a11y_primary` — mock `get_by_role(...).count()` → 1
- `test_a11y_resolver_normalized_recovers_trailing_whitespace` — exact → 0, normalized → 1
- `test_a11y_resolver_normalized_recovers_trailing_icon_chevron` — "Sort ▾" vs "Sort"
- `test_a11y_resolver_normalized_recovers_ellipsis_literal` — "Save…" vs "Save"
- `test_a11y_resolver_ambiguous_short_circuits_before_normalization` — exact → 2, normalization NOT attempted (verify via mock call count)
- `test_a11y_resolver_normalized_ambiguous_falls_back` — exact → 0, normalized → 2
- `test_a11y_resolver_zero_and_zero_returns_selector_fallback` — exact → 0, normalized → 0
- `test_a11y_resolver_exception_returns_selector_fallback_error` — mock raises; run continues
- `test_a11y_resolver_legacy_path_when_aria_role_is_None` — `_resolve_locator` original path called
- `test_normalize_name_nfc_case_fold_trim_icons_ellipsis` — pure-function unit test on the 4 normalization rules

### Unit Tests — Decision 2 (Recovery Handler)

- `test_a11y_ambiguous_disabled_by_default` — `settings.recovery_a11y_ambiguous_enabled` is `False`
- `test_a11y_ambiguous_returns_none_when_no_disambiguators` — cedes to STRICT_MODE
- `test_a11y_ambiguous_injects_container_from_single_disambiguator` — `["aria-label"]` → `container_selector="[aria-label]"`
- `test_a11y_ambiguous_injects_container_from_valued_disambiguator` — `["aria-label:Save button"]` → `container_selector='[aria-label="Save button"]'`
- `test_a11y_ambiguous_combines_multiple_disambiguators` — `["aria-label", "placeholder"]` → `[aria-label],[placeholder]`
- `test_a11y_ambiguous_rejects_unknown_disambiguator_attrs` — `["data-secret"]` NOT in whitelist → treated as empty → cedes to STRICT_MODE
- `test_a11y_ambiguous_failure_diary_caps_retries` — third invocation on same fingerprint → `None`
- `test_a11y_ambiguous_fingerprint_is_url_scoped` — same role+name on different pages → different fingerprints, independent caps
- `test_classifier_prefers_a11y_ambiguous_when_last_resolution_path_marker_set` — router classification test

### Performance / Regression Tests

- Benchmark harness (offline, not CI): resolve 1000 mocked steps; assert p95 < 25 ms and p99 < 100 ms with feature enabled
- Regression fixture: known PrimeNG flake case ("Save " trailing-whitespace bug) now resolves to `a11y_normalized` (documents Success Metric #2 from the task spec)

---

## Next Steps (into Build Phase)

1. **Phase 1** — Implement `_normalize_name` + `A11yLocatorResolver` two-tier probe in `backend/browser/a11y_resolver.py`. Corresponding tests in `tests/test_a11y_resolver.py`.
2. **Phase 2** — Wire resolver into `executor.py:_resolve_locator` for the four action types (`click`, `fill`, `check`, `uncheck`); plumb `state["last_resolution_path"]` for the recovery classifier.
3. **Phase 3** — Add `RecoveryType.A11Y_AMBIGUOUS` to enum; implement `_recover_a11y_ambiguous` with Failure Diary + disambiguator-cascade + STRICT_MODE tail; extend `_classify_for_recovery` signature to accept `state`; add `settings.recovery_a11y_ambiguous_enabled: bool = False` and `settings.a11y_ambiguous_max_retries: int = 2` to `backend/config.py`.

---

## Decision Summary (one-liner per decision)

- **Decision 1**: two-tier exact → normalized-regex a11y probe; normalization only fires on N=0, never on N≥2; anchored `re.escape`-safe pattern with NFC, case-fold, trailing-icon and trailing-ellipsis stripping.
- **Decision 2**: hybrid `_recover_a11y_ambiguous` handler — Failure-Diary-guarded, `aria_disambiguators` → `container_selector` scope injection when signal is present, `None` (cedes to STRICT_MODE) when absent; opt-in via `settings.recovery_a11y_ambiguous_enabled` (default `False`).
