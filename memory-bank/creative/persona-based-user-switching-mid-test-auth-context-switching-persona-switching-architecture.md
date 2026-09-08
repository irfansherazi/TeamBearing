# persona-based-user-switching-mid-test-auth-context-switching: Persona-Based User Switching — Architecture Design

**Phase**: Creative / Architecture
**Status**: COMPLETE
**Generated**: 2026-05-28T10:05:00-05:00

---

## Decision

**Chosen**: Option A — Dedicated `persona_switch_node` inserted in LangGraph graph with evaluator routing

A standalone LangGraph node (`backend/engine/persona_switch_node.py`) is added to the graph. The `evaluator_node` detects `PERSONA_SWITCH` steps and sets `_next_node = "persona_switch"`. After the switch completes, `_next_node = "planner"` to continue the test plan. This is fully additive — zero changes to planner, executor, or the existing ACCOUNT_SWITCH path.

---

## Options Considered

### Option A — Dedicated `persona_switch_node` + evaluator routing ✅ CHOSEN
- New node: `backend/engine/persona_switch_node.py`
- New VQAState fields: `current_persona`, `persona_switch_history`, `ephemeral_persona_creds`
- New schemas: `PERSONA_SWITCH` step type + `target_persona` field in `StructuredACStep`
- Evaluator: adds `elif step_type == "PERSONA_SWITCH": return "persona_switch"` to routing
- Graph: `add_node("persona_switch", persona_switch_node)` + edges: `evaluator → persona_switch` + `persona_switch → planner`
- HITL credential gate: new asyncio.Event per run in `persona_switch_node`; new endpoint `POST /runs/{run_id}/persona-credentials`
- **Pros**: Clean separation of concerns; pure additive; easy to test in isolation; no existing node changes
- **Cons**: New endpoint requires frontend change for HITL credential UI

### Option B — Handle in `executor_node` PERSONA_SWITCH branch
- Add `elif action["action"] == "persona_switch"` in executor's `_dispatch_action()`
- **Pros**: No graph wiring changes
- **Cons**: Executor manages browser, not auth lifecycle. Auth switching (localStorage clear + session restore) would be deeply intertwined with Playwright action dispatch. HITL pause from executor would block the executor event loop without a dedicated asyncio.Event infrastructure (the human_takeover path handles this at the graph edge level, not the executor level). Hard to test.

### Option C — Reuse `human_takeover_node` for HITL leg
- Route to `human_takeover_node` when persona is unknown; forward credential to persona_switch_node on resume
- **Pros**: Reuses existing HITL UI
- **Cons**: `human_takeover_node` is designed for stuck agents, not credential gates. State machine semantics would be muddled. The "Continue" action from takeover is not the same as "submit credential." Requires adding persona credential fields to the existing HITL payload which contaminates a stable interface.

---

## Architecture Diagram

```
                    START
                      │
              [jira_fetch_node]
              [ac_parser_node]      ◄── now emits PERSONA_SWITCH steps
              [setup_role_node]
              [login_node]          ◄── sets current_persona = role_key
                      │
                      ▼
              ┌─ [planner_node] ◄────────────────────────────────────┐
              │       │                                               │
              │       ▼                                               │
              │  [executor_node]                                      │ (resume after switch)
              │       │                                               │
              │       ▼                                               │
              │  [evaluator_node] ──── step_type == PERSONA_SWITCH? ──┤
              │       │    (normal)                                   │
              │       │                                         [persona_switch_node]
              │       │                                               │
              │  [verifier_node]                             ┌────────┤
              │       │                                      │        │
              └───────┘                              known role?   unknown role?
                                                         │                │
                                                  switch auth       emit HITL event
                                                   → planner    await credential input
                                                                   → switch auth
                                                                   → planner

              [reporter_node] ──► END
```

---

## File Changes

### [NEW] `backend/engine/persona_switch_node.py`
- `async def persona_switch_node(state: VQAState) -> dict`
- `_resolve_target_role_key(target_persona, run_memory) -> str | None`
- `_perform_switch(page, context, target_role_key, run_id) -> dict`
- `_wait_for_hitl_credentials(run_id, persona_name) -> dict` — asyncio.Event pause
- Module-level `_pending_persona_events: dict[str, asyncio.Event]`
- Module-level `_pending_persona_creds: dict[str, dict]`

### [MODIFY] `backend/engine/schemas.py`
```python
# In StructuredACStep:
step_type: Literal["NAVIGATE", "CLICK", "FILL", "VERIFY", "SELECT",
                    "WAIT", "HOVER", "PRESS_KEY", "ACCOUNT_SWITCH",
                    "PERSONA_SWITCH",  # NEW
                    "COVERAGE_GAP", "HITL", "UNKNOWN"]
target_persona: Optional[str] = None  # NEW — populated when step_type=PERSONA_SWITCH
```

### [MODIFY] `backend/engine/state.py`
```python
# New VQAState fields:
current_persona: str                    # active persona role_key; set by login_node + persona_switch_node
persona_switch_history: Annotated[list[dict], operator.add]  # append-only log of switches
ephemeral_persona_creds: dict          # {persona_name: {email, password}} — in-memory only, NOT annotated
```

### [MODIFY] `backend/engine/evaluator.py`
```python
# In route_after_evaluator() or the structured step routing block:
if step_type == "PERSONA_SWITCH":
    return "persona_switch"
```

### [MODIFY] `backend/engine/graph.py`
```python
from backend.engine.persona_switch_node import persona_switch_node

# In build_graph():
graph.add_node("persona_switch", persona_switch_node)
graph.add_edge("persona_switch", "planner")  # always returns to planner after switch
# conditional edge: evaluator → persona_switch (already handled by route_after_evaluator)
```

### [MODIFY] `backend/engine/ac_parser.py` + `backend/engine/prompts.py`
- Stage 1 BDD Normalizer prompt: add `PERSONA_SWITCH` step recognition examples
- Stage 2 JSON Compiler prompt: add `target_persona` field documentation + example
- Add `"PERSONA_SWITCH"` to the allowed step types in the compiler hint

### [MODIFY] `backend/api/routes.py`
```python
@router.post("/runs/{run_id}/persona-credentials")
async def submit_persona_credentials(run_id: str, body: PersonaCredentialsRequest):
    """Accept operator-provided credentials for unknown persona HITL gate."""
    from backend.engine.persona_switch_node import set_persona_credentials
    await set_persona_credentials(run_id, body.persona_name, body.email, body.password)
    return {"status": "accepted"}
```

### [MODIFY] `backend/engine/reporter.py`
- Render `persona_switch_history` entries as distinct steps with 🔄 icon
- Fields: from persona, to persona, timestamp, method, duration

### [MODIFY] `backend/engine/login_node` (inline in `graph.py`)
```python
# After successful login:
return_dict["current_persona"] = state["role_context"]["role_key"]
```

### [NEW] `tests/test_persona_switch_node.py`
### [NEW] `tests/test_ac_parser_persona.py`
### [NEW] `tests/test_schemas_persona.py`

---

## Data Contract

### `persona_switch_history` entry schema
```json
{
  "from":      "account_executive",
  "to":        "digital_director",
  "timestamp": "2026-05-28T16:32:15Z",
  "method":    "stored | initial_actor | hitl",
  "duration_ms": 2100
}
```

### `ephemeral_persona_creds` schema
```json
{
  "Bob the Director": {
    "email": "bob@vcreative.net",
    "password": "<scrubbed at INFO level>"
  }
}
```
> **Security**: `ephemeral_persona_creds` is NEVER serialized to disk, never passed to `AuthManager`, and is discarded when the run completes. Log scrubber regex covers email + JWT patterns to prevent accidental leakage.

### HITL WebSocket event
```json
{
  "type": "HITL_PERSONA_CREDENTIALS_REQUIRED",
  "persona_name": "Bob the Director",
  "message": "Unknown persona encountered. Provide login credentials to continue.",
  "run_id": "run-abc123"
}
```

### Credential submission endpoint
```
POST /runs/{run_id}/persona-credentials
{
  "persona_name": "Bob the Director",
  "email": "bob@vcreative.net",
  "password": "***"
}
```

---

## Integration with Existing Infrastructure

| Concern | Existing Pattern | PERSONA_SWITCH Alignment |
|---------|-----------------|--------------------------|
| Auth state files | `memory/auth_states/{role}.json` | `ensure_role_authenticated(role_key)` — existing function |
| HITL pause | `asyncio.Event` in `human_takeover_node` | Same pattern, new module-level dict keyed by run_id |
| WebSocket broadcast | `broadcast_ws_message(run_id, msg)` in routes.py | Reuse for `PERSONA_SWITCH_START` / `PERSONA_SWITCH_COMPLETE` |
| Log scrubbing | Pre-compiled regex in security-patterns | Existing scrubber covers email and JWT — no new rules needed |
| State initialization | `_init_vqa_state()` in routes.py | Add `current_persona: ""`, `persona_switch_history: []`, `ephemeral_persona_creds: {}` |

---

## Critical Architecture Decision: Single vs Multi Context

**Decision**: `persona_switch_node` operates on the **existing single BrowserContext**, not via `switch_actor()` (which creates a parallel context).

**Rationale**:
- `ACCOUNT_SWITCH` (existing) creates parallel contexts for simultaneous multi-role testing.
- `PERSONA_SWITCH` (new) replaces the current auth context entirely — single-user sequential testing.
- Method: `localStorage.clear()` + `context.add_cookies([...])` + `page.goto(target_url)` is sufficient for single-context auth replacement on vSuite (JWT-based SPA).
- No new BrowserContext is created; no existing contexts are closed.
- `BrowserManager.switch_actor()` is NOT called by `persona_switch_node`.

This is the key design decision that makes `PERSONA_SWITCH` orthogonal to `ACCOUNT_SWITCH`.

---

## NFR Architecture Support

| NFR | Architecture Guarantee |
|-----|----------------------|
| Zero credential leakage | `ephemeral_persona_creds` is a plain dict on `VQAState` (not `Annotated[..., operator.add]`) → not appended to audit log. Log scrubber intercepts WS messages before they reach the frontend. |
| ≤15s switch latency | `ensure_role_authenticated()` returns cached state path if TTL < 4h. Hot path: `add_cookies` + `goto` ≈ 1-3s. Cold path: fresh form login ≈ 10-15s. |
| Existing ACCOUNT_SWITCH unaffected | `persona_switch_node` never calls `switch_actor()` or modifies `_actor_registry`. Conditional routing in `evaluator_node` only triggers on `PERSONA_SWITCH` step_type. |
