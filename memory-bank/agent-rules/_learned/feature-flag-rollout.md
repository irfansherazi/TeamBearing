---
name: Feature Flag Rollout Patterns
globs: ["backend/config/**", "backend/engine/**", "backend/session/**"]
topics: ["feature-flags", "rollout", "shadow-mode", "kill-switch", "capacity-staging"]
priority: low
auto_generated: true
derived_from: [accessibility-tree-grounding, per-user-session-isolation]
evidence_count: 2
last_validated: 2026-08-07
---

# Learned Rules: feature-flag-rollout

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **independent-flags-for-shadow-mode** (`backend/config/__init__.py`, `backend/engine/`): For executor-layer changes that modify locator strategy or planning behavior, use INDEPENDENT feature flags — one for enrichment (data-generation), one for resolution (data-consumption), and one per recovery type. Independent flags allow the enrichment pass to run in shadow mode (populate fields, observe telemetry) before the resolution path is activated, and let recovery actions be enabled per-type without unlocking the full new codepath. All new flags default False for zero-blast-radius rollout.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x

- **legacy-path-bit-for-bit** (`backend/engine/executor.py`): When adding an alternative resolution/handling path behind a flag, the flag-off path MUST be bit-for-bit identical to pre-change behavior — verified by a dedicated backward-compat AC test (e.g., `aria_role=None → selector_only_legacy`). This is the safety net that lets you merge zero-behavior-change PRs and roll out via flag flips post-merge, rather than gating the merge on the new codepath being production-ready.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x

- **three-stage-capacity-rollout-requires-restart-docs** (`backend/config/__init__.py`, `backend/session/`, container-hosted apps): When shipping a capacity-bounded feature behind a kill switch, a three-stage rollout (off → N=1 → N=capacity_target) is sound ONLY when the container-restart requirement for each stage transition is explicitly documented in both (a) the task file's rollout section AND (b) the operational runbook. Flag flip alone does not communicate that a slot-count change requires a container restart (e.g., `MAX_CONCURRENT_SESSIONS` bumps `docker/supervisord.conf` templating on entrypoint render, which only runs at container start). Include a per-stage checklist: `SESSION_ISOLATION_ENABLED` value, `MAX_CONCURRENT_SESSIONS` value, whether a restart is required, expected verify window, and the specific AC that gates promotion (e.g., "AC-HAPPY-5 Golden 10 must pass before Stage 1 → 2"). `per-user-session-isolation` evidence: Stage 1 (flag off) → Stage 2 (flag on, N=1) → Stage 3 (N=4→8), each requires an ECS task restart for the supervisord.conf template re-render. Without restart docs, an operator flipping the flag alone would see partial isolation and misdiagnose it as a code bug.
  - _Source_: reflection-per-user-session-isolation (2026-08-07)
  - _Reinforced_: 0x
