---
derived_from: [accessibility-tree-grounding, fix-vsuite-profile-missing-roles]
evidence_count: 3
last_validated: 2026-07-30
---
# Learned Rules: error-handling

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **error-handling** (`backend/adapters/`, `backend/jira/`): Always provide graceful fallbacks for unknown or unsupported node types when parsing third-party ASTs or document formats (e.g. Atlassian Document Format). Preserve data (like filenames in media nodes) in the flattened text output.
  - _Source_: reflection-TASK-015 (2026-05-15)
  - _Reinforced_: 2x (TASK-046)

- **error-handling** (`backend/engine/ac_parser.py`): When implementing LLM self-correction loops, provide highly specific "repair hints" that identify the failure pattern (e.g. "transient selector detected") and suggest a concrete resolution (e.g. "use persistent wrapper class X instead"). Vague error messages lead to amnesic retries.
  - _Source_: reflection-TASK-046 (2026-05-20)
  - _Reinforced_: 0x

- **error-handling** (`backend/engine/executor.py`): Include granular UI identifiers (like `mark_id` or coordinates) in deduplication keys to uniquely identify visually-driven actions.
  - _Source_: reflection-TASK-021 (2026-05-15)
  - _Reinforced_: 1x

- **error-handling** (`backend/api/routes.py`, any framework-integrated executor): When a framework imposes a hard limit on a unit that differs from the application's safety cap unit (e.g., LangGraph node visits vs. planner iterations), scale the framework limit by the unit ratio PLUS headroom (`max_app_iterations × nodes_per_cycle + buffer`). Always catch the framework-specific termination exception and surface it as a clean application-level failure (log at WARNING, broadcast terminal message) — never let it propagate as an unhandled exception.
  - _Source_: reflection-TASK-027 (2026-05-16)
  - _Reinforced_: 1x

- **error-handling** (`backend/api/routes.py`): When classifying exception types for log-level decisions inside a broad `except Exception` handler, prefer `error_msg.lower()` string matching over `isinstance()` on framework-internal error classes. This avoids import coupling to the framework's error hierarchy and is resilient to framework version changes.
  - _Source_: reflection-TASK-027 (2026-05-16)
  - _Reinforced_: 1x

- **error-handling** (`frontend/src/types/`, `*.tsx`): When centralising environment-variable-based URL constants into a single module, grep for all consumer files that may contain local copies of the same variable — partial centralisation leaves silent shadow overrides that defeat the fix and survive code review if only the central file is inspected.
  - _Source_: reflection-TASK-032 (2026-05-19)
  - _Reinforced_: 0x

- **error-handling** (`frontend/src/components/*.tsx`, `backend/api/routes.py`): When a UI link navigates to an ephemeral backend resource (in-memory run state, failed upload result, server-restart-sensitive data), probe the endpoint with `HEAD` before rendering the link as active. Model the availability as a state machine (`"checking" → "s3" | "available" | "unavailable"`) and render a disabled `<span>` with an explanatory tooltip when `"unavailable"`. Never render a live `<a>` that leads to a known-or-likely 404 — users seeing a blank tab with a raw JSON error is always worse UX than a clearly disabled link.
  - _Source_: reflection-TASK-049 (2026-05-21)
  - _Reinforced_: 0x

- **error-handling-hints** (`backend/engine/evaluator.py`): Extract `aka get_by_role` hints from Playwright `STRICT_MODE_VIOLATION` error messages (which occur when multiple elements match a locator) and prepend them to `agent_critique`. This explicitly guides the planner to use more specific locators on the next iteration.
  - _Source_: reflection-TASK-051 (2026-05-26)
  - _Reinforced_: 1x

- **error-handling** (`backend/api/routes.py`, `backend/jira/client.py`): Map failures from critical upstream dependencies (e.g., Jira Agile API, AWS Bedrock) to HTTP 502 (Bad Gateway) instead of 500. This distinguishes environment/upstream issues from bugs in the local application logic and allows the frontend to provide specific "External Service Error" messaging.
  - _Source_: reflection-TASK-058 (2026-05-27)
  - _Reinforced_: 0x

- **filesystem-derived-count** (`backend/api/`): When an endpoint reports "N items processed" by a subprocess, derive N by post-hoc filesystem inspection after the subprocess completes — not by returning a hardcoded constant. Example: use `len(list(storage_dir.glob("storageState_*.json")))` after `generateStorageStates.mjs` runs. A hardcoded count creates a false success signal when the subprocess silently fails for a subset of items. The API contract is "N items were actually written", not "N items were attempted."
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **auth-error-messaging** (`backend/engine/auth_manager.py`, `backend/browser/`): When a login/auth flow times out waiting for a success signal (JWT, session cookie, redirect), the terminal error message must lead with the server-rendered error text (scrape visible banners: `p-message`, `p-toast`, `[role="alert"]`, `.error`, `.invalid-feedback`) — never with the client-side timeout symptom alone. The server's "Invalid credentials" is the diagnosis; the "vc2JWT not found in localStorage after 10 s" is just evidence the server rejected the login. A downstream-symptom message routes future debuggers to the wrong file.
  - _Source_: reflection-fix-vsuite-profile-missing-roles (2026-07-30)
  - _Reinforced_: 0x
