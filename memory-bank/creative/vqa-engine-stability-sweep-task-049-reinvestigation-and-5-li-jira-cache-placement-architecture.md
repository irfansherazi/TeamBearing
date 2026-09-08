# vqa-engine-stability-sweep-task-049-reinvestigation-and-5-li: Jira Cache Placement — Architecture Design

**Task**: vqa-engine-stability-sweep-task-049-reinvestigation-and-5-li — vQA Engine Stability Sweep  
**Creative Phase**: Architecture Design  
**Component**: Bug F — Jira ticket in-memory cache  
**Date**: 2026-05-22  
**Author**: Architecture Design Agent (inline)

---

## Problem Statement

The Jira REST API is called 3 independent times for the same ticket within a single user interaction:

1. **`/preview-steps` POST handler** → calls `jira_fetch_node(stub_state)` directly at route level (routes.py L645)
2. **`jira_fetch_node` inside LangGraph execution** → called again when `/execute` is dispatched for the same ticket (graph.py L109)
3. **(Potential)** The `check_ticket_credentials` endpoint also calls `fetch_ticket_context` independently (routes.py L688)

A 60-second TTL in-memory cache keyed by `ticket_id` would eliminate 2 of 3 redundant calls without changing any LangGraph state or requiring external infrastructure.

---

## Option Analysis

### Option A — Inline cache dict in `routes.py`

**Structure:**
```python
# backend/api/routes.py  (module level, near existing _run_states etc.)
import time as _time

_jira_ticket_cache: dict[str, tuple[dict, float]] = {}
_JIRA_CACHE_TTL = 60.0  # seconds

async def _cached_jira_fetch(ticket_id: str, state: VQAState) -> dict:
    now = _time.monotonic()
    cached = _jira_ticket_cache.get(ticket_id)
    if cached and (now - cached[1]) < _JIRA_CACHE_TTL:
        logger.info("[jira-cache] HIT ticket=%s", ticket_id)
        return {"jira_ticket": cached[0]}
    logger.info("[jira-cache] MISS ticket=%s", ticket_id)
    result = await jira_fetch_node(state)
    if "jira_ticket" in result:
        _jira_ticket_cache[ticket_id] = (result["jira_ticket"], now)
    return result
```

**Cache sites:**
- `preview_steps()`: replace `await jira_fetch_node(stub_state)` → `await _cached_jira_fetch(ticket_id, stub_state)`
- `jira_fetch_node` in graph.py: add a `_cached_jira_fetch`-equivalent wrapper OR patch the call in `routes.py` `_run_graph_task()` before graph execution begins

**Pros:**
- Zero new files — consistent with `_run_states`, `_ws_connections`, `_batch_registry` pattern (all module-level dicts in routes.py)
- `_time` already imported as `_time` at L139 — no new import
- Cache is co-located with the only two callers that matter (`preview_steps` + graph dispatch)
- Easiest to test: mock `_jira_ticket_cache` dict directly

**Cons:**
- `jira_fetch_node` is defined in `graph.py` — the cache wrapper in `routes.py` cannot intercept graph-internal calls if `jira_fetch_node` is invoked as a LangGraph node (it would need to be patched at the graph level or the node itself modified)
- Coupling: routes.py grows slightly, but it already has ~1350 lines

**Verdict**: Best fit for `preview-steps` → `execute` deduplication. For graph-internal call, `jira_fetch_node` itself must be modified.

---

### Option B — Shared `backend/jira/cache.py` module

**Structure:**
```python
# backend/jira/cache.py
import time
from typing import Any

_store: dict[str, tuple[dict[str, Any], float]] = {}
_TTL = 60.0

def get(ticket_id: str) -> dict[str, Any] | None:
    entry = _store.get(ticket_id)
    if entry and (time.monotonic() - entry[1]) < _TTL:
        return entry[0]
    return None

def put(ticket_id: str, ticket_data: dict[str, Any]) -> None:
    _store[ticket_id] = (ticket_data, time.monotonic())
```

`jira_fetch_node` in `graph.py` would check `cache.get(ticket_id)` before calling the negotiator.  
`preview_steps` in `routes.py` would also check `cache.get(ticket_id)` before calling `jira_fetch_node`.

**Pros:**
- Single source of truth; `jira_fetch_node` itself becomes cache-aware, intercepting ALL callers (including any future callers in the graph)
- Clear ownership: `backend/jira/` is the right package for Jira-related infrastructure
- Easy to extend TTL, add eviction, or swap to Redis later without touching routes.py or graph.py
- Testable independently of routes/graph

**Cons:**
- New file introduces a slight structural overhead for what is effectively a two-function module
- `graph.py` takes a dependency on `backend/jira/cache.py` — minor coupling but very clear

**Verdict**: Best architectural separation; cache is in the right layer. Slightly more files but cleaner.

---

### Option C — Inject cached data into LangGraph `VQAState` before graph starts

**Structure:**  
Before calling `build_graph().invoke()`, pre-populate `initial_state["jira_ticket"]` with cached data.  
`jira_fetch_node` would detect `state["jira_ticket"]` already populated (non-empty `ticket_id` + `summary`) and skip the fetch.

**Pros:**
- No new module, no dict modifications inside graph nodes
- LangGraph state is the canonical data carrier — pre-populating it is idiomatic

**Cons:**
- `jira_fetch_node` doesn't currently have a "skip if populated" guard — must be added
- Pre-populating state outside the graph means the cached data bypasses the `JiraACNegotiator` quality gate, which could mask errors on the second call (the negotiator does more than just fetch: it enforces AC quality gates and proposes a test plan back to Jira)
- Fragile: any future refactor of `make_initial_state` or `jira_fetch_node` could silently break the bypass
- Cache logic is hidden inside `_run_graph_task()` in routes.py — not obvious

**Verdict**: Rejected. Bypassing the negotiator is dangerous and the approach is too implicit.

---

## Decision

**Chosen**: **Option B — Shared `backend/jira/cache.py` module**

### Rationale

1. **Correct ownership**: Cache belongs in `backend/jira/` alongside `client.py` and `negotiator.py`. It is Jira infrastructure, not route infrastructure.
2. **Intercepts all callers**: By making `jira_fetch_node` itself cache-aware, future callers (new nodes, new routes) automatically benefit without any changes at the call site.
3. **Negotiator is preserved**: The cache stores the **result** of `negotiator.fetch_and_gate_ac()` — the full ticket context dict — not the raw Jira payload. The quality gate still runs on the first (MISS) call.
4. **Testability**: `backend/jira/cache.py` can be tested with a simple `monkeypatch` on `time.monotonic`; no need to mock routes or graph infrastructure.
5. **12-Factor compliant**: In-memory, process-scoped cache. No external state.

### Rejected options:
- Option A: `jira_fetch_node` still not intercepted without modifying graph.py — defeats the purpose
- Option C: Bypasses quality gate; too implicit

---

## Implementation Specification

### New File: `backend/jira/cache.py`

```python
"""
Jira Ticket In-Memory Cache
============================
Short-lived in-process cache for Jira ticket context data.

Motivation
----------
The /preview-steps and /execute flows both call jira_fetch_node for the same
ticket within seconds of each other, causing redundant Jira REST API calls.
A 60-second TTL cache eliminates 2 of 3 round-trips without requiring Redis
or any external infrastructure.

Design Notes
------------
- Cache is process-scoped (dict). Not shared across workers.
- Key: normalized ticket_id (uppercase, stripped)
- Value: (ticket_context_dict, monotonic_timestamp)
- TTL: 60 seconds (configurable via _JIRA_CACHE_TTL)
- No explicit eviction: stale entries are overwritten on next MISS.
  Memory footprint is bounded by the number of unique tickets fetched
  within a 60s window — effectively O(1) for typical single-operator use.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_JIRA_CACHE_TTL: float = 60.0
_store: dict[str, tuple[dict[str, Any], float]] = {}


def get(ticket_id: str) -> dict[str, Any] | None:
    """Return cached ticket context if present and within TTL, else None."""
    entry = _store.get(ticket_id)
    if entry is None:
        logger.info("[jira-cache] MISS ticket=%s (not found)", ticket_id)
        return None
    ticket_data, ts = entry
    age = time.monotonic() - ts
    if age > _JIRA_CACHE_TTL:
        logger.info("[jira-cache] MISS ticket=%s (expired %.1fs ago)", ticket_id, age - _JIRA_CACHE_TTL)
        return None
    logger.info("[jira-cache] HIT ticket=%s (age=%.1fs)", ticket_id, age)
    return ticket_data


def put(ticket_id: str, ticket_data: dict[str, Any]) -> None:
    """Store ticket context in cache with current timestamp."""
    _store[ticket_id] = (ticket_data, time.monotonic())
    logger.debug("[jira-cache] STORED ticket=%s", ticket_id)


def clear() -> None:
    """Clear all cache entries. Intended for testing only."""
    _store.clear()
```

### Modify: `backend/engine/graph.py` — `jira_fetch_node`

```python
# At top of file (with other jira imports)
from backend.jira import cache as jira_cache

async def jira_fetch_node(state: VQAState) -> dict:
    ticket_id: str = state["jira_ticket"]["ticket_id"]
    run_id: str = state["run_id"]

    # --- Cache check ---
    cached = jira_cache.get(ticket_id)
    if cached is not None:
        logger.info("[%s] [jira-cache] Using cached ticket for %s", run_id, ticket_id)
        return {"jira_ticket": cached}
    # --- End cache check ---

    logger.info("[%s] Fetching Jira ticket: %s", run_id, ticket_id)
    from backend.jira.negotiator import JiraACNegotiator
    negotiator = JiraACNegotiator(ticket_id, run_id)
    ticket_context, quality_result = await negotiator.fetch_and_gate_ac()
    
    # ... (rest of existing logic unchanged) ...
    
    # Store in cache on success
    if ticket_context:
        jira_cache.put(ticket_id, ticket_context)

    return {"jira_ticket": ticket_context}
```

**Note**: With this change, `preview_steps` in `routes.py` does NOT need modification — it already calls `jira_fetch_node`, which is now cache-aware.

---

## Architectural Compliance Check

| Constraint | Status |
|------------|--------|
| No new LangGraph nodes | ✅ — cache is a module, not a node |
| 12-Factor: stateless processes | ✅ — in-memory, process-scoped |
| No Redis/external infra | ✅ — plain Python dict |
| Negotiator quality gate preserved | ✅ — cache stores negotiator output |
| Existing patterns match | ✅ — `backend/jira/` already has `client.py`, `negotiator.py` |
| Testable without integration | ✅ — `monkeypatch` on `time.monotonic` |

---

## Test Targets

| Test | Assertion |
|------|-----------|
| `test_jira_cache_hit_on_second_call` | Second call to `jira_fetch_node` with same ticket within TTL returns cached data; fetch function NOT called |
| `test_jira_cache_miss_after_expiry` | Call after 60s TTL re-fetches |
| `test_jira_cache_logs_hit_miss` | `[jira-cache] HIT` / `[jira-cache] MISS` logged at INFO |
| `test_preview_steps_uses_cache` | `preview_steps` + `jira_fetch_node` sequence only calls negotiator once |
