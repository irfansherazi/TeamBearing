---
version: next
status: completed
priority: high
complexity: 3
linked_tasks: [vqa-pinned-testplans]
created: 2026-08-18
completed: 2026-08-18
---

# vQA Pinned TestPlans for Deterministic Fail→Pass

Add an explicit **pinned TestPlan** primitive to vQA so the `/vc` pipeline's red→green transition is a byte-identical replay, not two independent LLM parses. This is **Lock B** for the `/vc:diagnose → /vc:testwrite → /vc:fix → /vc:testrun` chain.

**Blocking issue.** The current pipeline authors a `TestPlan` from Jira AC via multiple LLM stages at `temperature=0.0`. `T=0` on Bedrock is not bit-exact deterministic, and the content-hash disk cache that would otherwise pin the parse can evict/invalidate between the red run (`two-test.vcreative.net`) and the green run (`test.vcreative.net`) hours or days later. Without pinning, "the test failed then passed" is not a proof — the plan itself could have shifted.

**Mechanism (additive only — every existing caller behaves identically without the new fields):**

1. `POST /preview-steps` accepts inline `acceptance_criteria`, authors the TestPlan from that text, persists it under an opaque `plan_id`, returns the id.
2. `POST /execute` accepts `plan_id`; when present, `ac_parser_node` short-circuits at the top and injects the pinned plan **verbatim** — no LLM, no cache, no re-parse.
3. Missing / expired `plan_id` errors **loudly** (404 / 410). Never a silent fall-back to re-parse — that would resurrect the exact non-determinism this mechanism removes.

**Scope (~5 existing files + 2 new + 2 test files):**

- NEW `backend/engine/pinned_plans.py` — TTL-scoped on-disk store (`storage/pinned_plans/<plan_id>.json`), 14-day TTL, lazy-prune-on-read + startup prune.
- `backend/config/__init__.py` — new `pinned_plan_ttl_days` setting.
- `backend/api/schemas.py` — `ExecuteRequest.plan_id`, new `PreviewStepsRequest` (POST variant), `PreviewStepsResponse.plan_id`.
- `backend/engine/state.py` — `pinned_plan: dict`, `pinned_plan_id: str` fields + defaults in `make_initial_state()`.
- `backend/engine/ac_parser.py` — short-circuit at top of `ac_parser_node` when `state["pinned_plan"]` is set.
- `backend/api/routes.py` — new `POST /preview-steps` handler; `execute_single` resolves `plan_id` and injects into state, raises 400 on `plan_id` + `override_steps` (mutex), 404 on miss, 410 on expiry.
- `backend/api/app.py` — startup hook calls `pinned_plans.prune_expired()`.
- NEW `tests/test_pinned_plans.py` — unit tests for the store (save/load/expiry/prune).
- NEW `tests/test_execute_plan_id.py` — integration test; **load-bearing assertion**: `_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` when `state["pinned_plan"]` is set. Also covers 404 / 410 / mutex-400.

**Non-goals / hard constraints:**

- **Never silent-fallback.** Missing/expired `plan_id` MUST 404/410. Do not add "if not found, re-parse" for any reason — the whole determinism guarantee hinges on loud misses.
- **TTL is in DAYS.** Default 14. The red→green window is measured in business days, not seconds.
- **Storage persistence.** `storage/pinned_plans/` must survive container restarts/deploys — if the deploy is stateless-container, this requires a volume mount.
- **OpenAPI regen on merge.** The `/vc` plugin will preflight `/openapi.json` to detect support; the spec must reflect the new fields.
- Suggested branch: `feature/vqa-pinned-plans`.

**Source-of-truth plan doc:** [`docs/todo/pinned-plans-PR.md`](../../docs/todo/pinned-plans-PR.md) — carries the full diffs, tests, and implementer notes verbatim. That doc says "Do not implement from the plugin session" — this roadmap entry exists to schedule the work for a proper `/bmb:plan` + `/bmb:build` cycle owned by vQA.

**Complexity rationale**: Level 3 — multi-component (API + engine + config + state + tests), one design decision (pinned-plan primitive vs. reusing the content-hash cache, resolved in the plan doc), no system-wide architectural change and no phased rollout needed. Not Level 4 (additive only, no cross-cutting refactor). Not Level 2 (design decision + coordinated changes across 5 files require a plan + review).
