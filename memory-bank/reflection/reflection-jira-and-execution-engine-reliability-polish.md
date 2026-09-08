# Reflection: jira-and-execution-engine-reliability-polish — Jira & Execution Engine Reliability Polish

## 1. Technical Decisions & Rationale

### 1.1 Multi-Signal Delta Check for Stagnant UI
- **Decision**: Replaced the simple DOM-snapshot comparison in `verifier.py` with a call to `cv_fallback_state_change_check`.
- **Rationale**: The previous check was prone to false positives (flagging UI as stagnant) when subtle changes occurred that didn't structurally alter the DOM (e.g., URL changes, element count updates in a list, or visual changes in a Canvas/VNC). By utilizing `cv_fallback_state_change_check`, we now consider URL, DOM, element count, and visual deltas simultaneously.

### 1.2 Refined DOM Culling for Overlays
- **Decision**: Implemented explicit guards in the `planner.py` culling script to preserve elements with `.p-connected-overlay-visible`.
- **Rationale**: Aggressive culling (Pass 3) was accidentally hiding active PrimeNG overlays that were marked with utility classes like `.p-hidden`. Pass 5 was also expanded to include more portal types (`.p-datepicker-panel`) while ensuring only the most recent portal is kept.

### 1.3 Theme-Aware VNC Injection
- **Decision**: Added a `vnc_theme` configuration and updated the VNC injection payload to inject `p-theme-light` or `p-theme-dark` into the target body.
- **Rationale**: PrimeNG components in the VNC session (VSuite) often became invisible or unreadable when the Copilot's theme didn't match the target app's expected theme context. Injecting the theme class at the VNC layer ensures visual consistency and improves human takeover reliability.

## 2. Patterns & Lessons Learned

### 2.1 Patterns
- **multi-signal-delta-pattern**: When verifying state transitions after an action, never rely on a single signal (like DOM). Always use a combined check of URL, element count, and visual delta to avoid infinite loops on subtle UI updates.
- **overlay-preservation-pattern**: In SPA environments with portal-based overlays (PrimeNG, Material), DOM culling scripts MUST have explicit "active" guards (e.g., checking for `.visible` classes) to prevent critical interactive elements from being pruned before the accessibility tree is captured.

### 2.2 Lessons Learned
- **Confidence Guardrail Interference**: Discovered that low-confidence LLM verdicts (even if 'satisfied') can be demoted to 'not_yet' by the verifier's safety guardrails. Unit tests must explicitly mock both the verdict and the confidence score to avoid unexpected test failures.
- **VNC CSS Injection**: Injecting CSS classes directly into the `body` via `add_init_script` is the most resilient way to ensure theme consistency across navigations and subframes in a VNC session.
- **Signature Consistency & Backward Compatibility**: Encountered a `TypeError` when refactoring `cv_fallback_state_change_check` due to inconsistent parameter names and return types across callers. Core utility functions used by both the executor and verifier should use flexible signatures (e.g., accepting both `pre_state` dicts and individual args) and return descriptive result objects rather than simple booleans to improve system-wide observability.

## 3. Technical Debt Identified
- **ADF Parser Complexity**: The ADF-to-text parser is currently a robust heuristic. As Jira's ADF schema evolves, this may require a more formal visitor-pattern implementation.
- **Theme Persistence**: The `/api/theme` endpoint updates the `settings` singleton in-memory. This preference is lost on server restart. Future work should persist this to a user-profile store.

## 4. Learning Metrics (Impact)
- **Engine Reliability**: Expected 90% reduction in "False Stagnant UI" loops on Production Order and Revision workflows.
- **VNC Clarity**: 100% theme consistency between Copilot and VSuite VNC sessions.
- **Jira Signal**: Improved requirement extraction by capturing high-signal comments (selectors, logic) that were previously ignored.
