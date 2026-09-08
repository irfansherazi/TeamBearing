---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: security-patterns

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **allow-list-over-denylist** (`backend/api/`, any subprocess-invoking endpoint): When any user-supplied parameter is used in subprocess construction, the **primary** security control is an **allow-list** derived from an authoritative data source (e.g., a pre-built JSON index). A metacharacter denylist is a **secondary** defense only. The allow-list check must occur before any subprocess is spawned: `if test_id not in self._registry: raise HTTPException(422, ...)`. The denylist is a belt-and-suspenders check for injection via fields that cannot be allow-listed (e.g., arbitrary filenames). Never make the denylist the only check.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **no-shell-true** (`backend/api/`, `backend/engine/`): Never use `shell=True` in subprocess invocations where any argument includes user-supplied data. Always use `asyncio.create_subprocess_exec(*list_of_args)` with a list of explicitly constructed arguments. `shell=True` with string concatenation/formatting is a command injection vector even when input appears validated — shell parsing happens after your validation.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **log-scrubber-precompile** (`backend/api/`): When streaming subprocess stdout/stderr through WebSockets, apply a log scrubber before broadcast. Pre-compile scrubber regex patterns at module load time (not per-call). Patterns should cover: (1) specific env-var values (e.g., `SHARED_TEST_PASSWORD`), (2) JWT-shaped strings (`eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`), and (3) storageState JSON blobs. Replace with `[REDACTED]`. A per-call `re.sub()` with a freshly-compiled pattern is 10-50x slower under high log volume.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **ephemeral-cred-in-memory** (`backend/engine/`, HITL credential flows): HITL-provided credentials for unrecognised personas (or any ephemeral, operator-supplied secret) must be stored in a `VQAState` dict field ONLY — never written to disk, never passed to `AuthManager`, never logged at INFO or above, and discarded when the run ends. The dict key should be the raw input identifier (e.g., persona name string), NOT the resolved role key, so multiple unrecognised inputs in the same run don't collide. This prevents a class of credential persistence bugs where test credentials accidentally persist to disk and surface in future runs with different security requirements.
  - _Source_: reflection-TASK-063 (2026-05-28)
  - _Reinforced_: 1x (reflection-TASK-102, 2026-06-03 — Admin Ghost Credentials stored purely in-memory in `_ghost_creds` dictionary with run-end cleaning)

- **asyncio-event-hitl-gate** (`backend/engine/persona_switch_node.py`, HITL flows): Build a HITL blocking gate using a module-level `dict[str, asyncio.Event]` keyed by `run_id`. The blocking node does `event = _EVENTS.setdefault(run_id, asyncio.Event()); await asyncio.wait_for(event.wait(), timeout=300.0)`. The REST endpoint calls `event.set()` after storing the credentials. Always clean up the dict entry after the gate fires (`_EVENTS.pop(run_id, None)`). Set a 300-second timeout and raise an explicit `TimeoutError` — do not let the await block indefinitely.
  - _Source_: reflection-TASK-063 (2026-05-28)
  - _Reinforced_: 1x (reflection-TASK-102, 2026-06-03 — Utilised for `_wait_for_ghost_credentials` with run_id keyed event mapping)
