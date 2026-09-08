---
derived_from: [accessibility-tree-grounding, fix-vsuite-profile-missing-roles]
evidence_count: 3
last_validated: 2026-07-30
---
# Learned Rules: config-validation

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **config-validation** (`scripts/validate_env.py`, `backend/config.py`): When adding new external service configurations (API keys, board IDs, endpoints), always update the corresponding diagnostic script (`validate_env.py`) using the EXACT same logic and authentication construction as the main application. This ensures environment issues can be isolated and debugged independently of the full application stack.
  - _Source_: reflection-TASK-058 (2026-05-27)
  - _Reinforced_: 0x

- **config-module-active-vs-legacy** (`backend/config/__init__.py`, `backend/config.py`): New Pydantic settings fields belong in `backend/config/__init__.py` — the active `Settings` class. `backend/config.py` at the repo root is a legacy stub and does NOT receive new fields; both files exist but only the package `__init__.py` is loaded at runtime. Adding a field to the root `config.py` produces a silent no-op and wastes a build-guard cycle when the C1 check catches the dead-file modification. Verify the target file path against `techContext.md § Environment Configuration` before adding any config field.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x

- **credential-fallback-empty-default** (`backend/engine/roles.py`, `backend/profiles/*.py`, any credential/secret resolution site): For auth credentials, use `.get(key, {}).get("field", "")` (empty-string default), never `.get(..., "HARDCODED_PERSONAL_EMAIL")` or `.get(..., "SHARED_TEST_PASSWORD")`. A wrong-but-plausible default routes through the auth stack, gets rejected by the server, and surfaces as a misleading downstream symptom (JWT timeout, session missing, redirect loop). An empty default fails at the first credential-required step with a clear "no credentials configured" signal. This applies whenever a registry lookup produces credentials — the wrong-default failure mode is always more expensive to debug than the empty-default failure mode.
  - _Source_: reflection-fix-vsuite-profile-missing-roles (2026-07-30)
  - _Reinforced_: 0x
