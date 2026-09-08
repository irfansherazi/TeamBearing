---
version: next
status: completed
priority: high
complexity: 3
linked_tasks: [accessibility-tree-grounding]
created: 2026-07-30
completed: 2026-07-30
umbrella: agentic-testing-sota-adoption-2026
---

# Accessibility Tree Grounding

Capture ARIA role + accessible name alongside the PrimeNG selector for every `target_component` the executor operates on. At execution time, the executor prefers the accessibility (a11y) tree — locating elements by `role` + `name` — and falls back to the recorded selector when the a11y match is ambiguous or absent. Reduces flakiness from DOM churn (class-name changes, template restructures) and aligns vQA's target abstraction with the one MCP-based agents natively consume.

**Scope (candidate 2 extraction from `agentic-testing-sota-adoption-2026`):**

- Selector-capture pipeline (recorder + `target_component` schema): add `aria_role`, `aria_name`, and any disambiguating a11y attributes alongside the existing selector string. Backward-compatible with existing recorded tests (missing fields → selector-only path).
- Executor grounding: introduce an a11y-first locator resolver that queries by `getByRole(role, { name })` (or engine equivalent) first, then falls back to the selector, then to the CV/SoM fallback (FEAT-037).
- Ambiguity/fallback policy: define the trigger for falling back to selector (0 matches, N > 1 matches, name mismatch beyond a fuzzy-match threshold), and log the decision path so the verifier and post-run analytics can see which path resolved.
- Verifier & recovery-router integration: the verifier's evidence should record which locator strategy succeeded; recovery-router (`recovery_router.py`) gains a11y-tree retry as a first-class recovery action (feeds candidate 8 groundwork).
- Reference: [Playwright Test Agents v1.56](https://playwright.dev/docs/test-agents) (Jan–Jul 2026 expansion), gap analysis §3.1.

**Complexity rationale**: Level 3. Requires design decisions (a11y-attribute schema, fallback trigger thresholds, verifier evidence schema) and touches multiple components (recorder, `target_component` model, executor's locator layer, verifier, recovery-router). Not system-wide (Level 4) — the executor + selector-capture pipeline is bounded; verifier/recovery-router changes are additive integration points, not architectural rewrites. Fits `/bmb:plan → /bmb:creative → /bmb:build` with likely 2–3 build phases (capture → executor → verifier/recovery integration).
