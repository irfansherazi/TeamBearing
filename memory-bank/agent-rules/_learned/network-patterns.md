---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: network-patterns

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **dynamic-origin-url-builder** (`backend/browser/vnc_builder.py`, `backend/api/routes.py`): When building external service URLs (like noVNC streams or external dashboard links) that must be accessed by a frontend client, avoid hardcoding `localhost` or using purely env-var based URLs if the application is deployed behind proxies or in multi-origin environments. Instead, construct the URL dynamically using the incoming request's `Host` and protocol headers (e.g., `request.base_url` or custom headers). This ensures the links are always routable from the client's perspective regardless of network topology.
  - _Source_: reflection-TASK-033 (2026-05-20)
  - _Reinforced_: 0x
