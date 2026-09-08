---
name: Cross-Component Integration-Wiring Review After Auto-Build
globs: ["backend/api/routes.py", "backend/engine/*.py", "frontend/src/components/**/*.tsx"]
paths: ["backend/", "frontend/src/"]
topics: ["integration", "cross-component", "auto-build", "level-4", "verification", "ac-entry"]
priority: low
auto_generated: true
derived_from: [per-user-session-isolation]
evidence_count: 1
last_validated: 2026-08-07
---

# Learned Rules: integration-wiring

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **cross-component-integration-review-before-build-complete** (Level 4 multi-phase tasks under `/bmb:auto-build`): After `/bmb:auto-build` completes the last implementation phase of a Level 4 feature — and BEFORE marking BUILD_COMPLETE — perform an explicit cross-component integration review. For each new manager/writer/hook the feature introduces, walk every AC-ENTRY acceptance criterion and verify the code path from the entry point actually reaches the new component. Auto-build's phase-isolated agents naturally optimize per-phase quality; they systematically under-catch integration wiring (routes that don't call the new manager, KB writers that bypass a new lock helper, frontend components that read from a legacy prop instead of a new context hook). Codify the review as a checklist: (1) list every new class/function introduced across phases, (2) for each AC-ENTRY, name the entry-point file:line, (3) confirm the entry point actually invokes each new class/function OR document why not. `per-user-session-isolation` evidence: BUILD_COMPLETE was marked with 4 wiring gaps — `execute_single` didn't call `SessionManager.add_active_run_id()`, `execute_batch` didn't enforce the session cookie, `human_takeover.py` KB writers bypassed `KBWriter`, `LiveBrowser`/`TakeoverPanel` read `novnc_url` from run-status prop instead of `useSession()`. All four were correct implementations in isolation — pure integration-wiring misses. Closed same-day in commit `9b14e83` but should have been caught before the BUILD_COMPLETE marker.
  - _Source_: reflection-per-user-session-isolation (2026-08-07)
  - _Reinforced_: 0x
