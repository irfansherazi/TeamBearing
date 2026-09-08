# persona-based-user-switching-mid-test-auth-context-switching: Persona-Based User Switching — User Journey Design

**Phase**: Creative / User Journey
**Status**: COMPLETE
**Generated**: 2026-05-28T10:00:00-05:00

---

## Decision

**Chosen**: Option A — Transparent In-Flow Switching with Dedicated HITL Credential Gate

The persona switch is invisible to the executing AC step sequence: the `persona_switch_node` intercepts between steps, performs the full auth replacement, navigates to the app root, and returns control to the planner node. The operator only sees a distinct 🔄 entry in the live log stream and in the final audit report. For unknown personas, a blocking HITL modal collects credentials before resuming.

---

## Options Considered

### Option A — Transparent In-Flow Switching with Dedicated HITL Credential Gate ✅ CHOSEN
- The test run's outer loop is unchanged. The evaluator emits `_next_node = "persona_switch"` when it encounters a `PERSONA_SWITCH` step.
- `persona_switch_node` handles everything: clear localStorage, navigate to app root, re-authenticate, wait for JWT, navigate to `target_url`.
- If credentials are unknown → HITL pause using the same `asyncio.Event` mechanism already in `human_takeover_node`.
- After the switch, `_next_node = "planner"` and the next AC step runs under the new identity.
- **Pros**: Zero changes to planner/executor; switch is a single atomic node; HITL escalation is consistent with existing patterns.
- **Cons**: The HITL panel needs a new credential-input UI variant (adds Phase 4 scope).

### Option B — Executor-Side Auth Swap
- The executor detects `PERSONA_SWITCH` step type and performs the swap inline.
- **Pros**: Fewer graph changes.
- **Cons**: Executor would need browser session teardown/restart logic it doesn't currently own. Mixes concerns. Harder to test.

### Option C — New Outer Loop Role-Cycle
- Treat persona switches as mini role-cycles: exit the inner planner loop, call `setup_role_node`, then re-enter login.
- **Pros**: Reuses all existing auth code.
- **Cons**: `setup_role_node` pops from `role_queue`; that queue is managed by the outer role loop and cannot be mid-run injected without refactoring. Persona switches are NOT the same as sequential role runs.

---

## User Journey Maps

### Journey 1 — Happy Path: Known Persona with Stored Credentials

```
[AC Parser output]
  Step 3: PERSONA_SWITCH → target_persona = "digital_director"
  Step 4: NAVIGATE → /production-orders
  Step 5: VERIFY → table visible

[Evaluator processes Step 3]
  evaluator_node: structured_step.step_type == "PERSONA_SWITCH"
  → _next_node = "persona_switch"

[persona_switch_node executes]
  1. Log: "🔄 Switching persona: account_executive → digital_director"
  2. emit WebSocket: { type: "PERSONA_SWITCH_START", from: "account_executive", to: "digital_director" }
  3. page.evaluate("localStorage.removeItem('vc2JWT')")
  4. page.evaluate("localStorage.clear()")
  5. state_path = ensure_role_authenticated("digital_director")   # uses cached auth state if TTL-valid
  6. context.add_cookies([...])   # apply stored session from state_path
  7. page.goto(target_url)        # navigate to app root under new identity
  8. wait_for_post_login_spa_render(page, run_id)
  9. Verify JWT present in localStorage (poll, max 5s)
  10. Update VQAState:
       current_persona = "digital_director"
       persona_switch_history += { from, to, timestamp, method: "stored" }
  11. emit WebSocket: { type: "PERSONA_SWITCH_COMPLETE", ... }
  12. _next_node = "planner"

[planner_node] executes Step 4 under "digital_director" identity
```

### Journey 2 — "As Yourself" Sentinel

```
[AC Parser output]
  Step 7: PERSONA_SWITCH → target_persona = "current_user"  (normalized from "as yourself")

[persona_switch_node]
  initial_actor = state["run_memory"]["initial_actor"]
  → email = initial_actor["email"], role_key = initial_actor["role_key"]
  → use initial_actor credentials directly (not role registry)
  → method = "initial_actor"
  → switch history records: { from: "digital_director", to: initial_actor["role_key"], method: "initial_actor" }
```

### Journey 3 — Unknown Persona → HITL Credential Gate

```
[AC Parser output]
  Step 5: PERSONA_SWITCH → target_persona = "Bob the Director"
  (resolve_role_by_name("Bob the Director") → None)

[persona_switch_node]
  1. emit HITL_PERSONA_CREDENTIALS_REQUIRED:
     {
       persona_name: "Bob the Director",
       message: "Unknown persona. Please provide login credentials.",
       fields: ["email", "password", "save_for_future"]
     }
  2. asyncio.Event.wait()  ← pauses graph

[Operator sees blocking modal]
  ┌─────────────────────────────────────────────────────┐
  │  🔄 Unknown Persona: "Bob the Director"             │
  │  Please provide credentials to continue.            │
  │                                                     │
  │  Email: [_____________________________]             │
  │  Password: [_____________________________]          │
  │  ☐ Save for future runs (this session only)         │
  │                                                     │
  │  [Continue]   [Skip Step]                           │
  └─────────────────────────────────────────────────────┘

[POST /runs/{run_id}/persona-credentials] with { email, password }
  → backend sets ephemeral_persona_creds["Bob the Director"] = { email, password }
  → event.set()  ← resumes graph

[persona_switch_node resumes]
  4. Use ephemeral_persona_creds to authenticate
  5. method = "hitl"
  6. Credentials NOT stored to disk — in-memory only for this run
```

### Journey 4 — Multi-Switch (Chained Persona Switches)

```
Step 2: PERSONA_SWITCH → "digital_director"
  switch: account_executive → digital_director  ✓

Step 4: PERSONA_SWITCH → "producer"
  switch: digital_director → producer  ✓

Step 6: PERSONA_SWITCH → "current_user"
  switch: producer → account_executive (initial_actor)  ✓

persona_switch_history = [
  { from: "account_executive", to: "digital_director", timestamp: T1, method: "stored" },
  { from: "digital_director", to: "producer", timestamp: T2, method: "stored" },
  { from: "producer", to: "account_executive", timestamp: T3, method: "initial_actor" },
]

Each switch: localStorage cleared → new auth state applied → navigate to target_url
→ ZERO bleed-through between sessions  ✓
```

### Journey 5 — Audit Report View

```
[HTML Report — Step 3 of 8]
  ┌────────────────────────────────────────────────────────┐
  │ 🔄  PERSONA SWITCH                          Step 3/8  │
  │ From: Account Executive (demo-ae@vcreative.net)        │
  │ To:   Digital Director  (demo-dd@vcreative.net)        │
  │ At:   10:32:15 UTC                                      │
  │ Method: stored                                          │
  │ Duration: 2.1s                                          │
  └────────────────────────────────────────────────────────┘
```

---

## State Transitions Summary

```
login_node
  → VQAState.current_persona = role_context.role_key
  → VQAState.run_memory.initial_actor = { email, role_key, role_name }

evaluator_node (on PERSONA_SWITCH step)
  → _next_node = "persona_switch"

persona_switch_node (success)
  → current_persona = target_role_key
  → persona_switch_history += { from, to, timestamp, method }
  → _next_node = "planner"

persona_switch_node (HITL)
  → WAITING_FOR_PERSONA_CREDENTIALS
  → (on resume) current_persona = target_role_key, method = "hitl"
  → _next_node = "planner"
```

---

## NFR / Constraints Met by This Journey

| NFR | How Addressed |
|-----|--------------|
| AC-NFR-1: Zero credential leakage | HITL creds stored in `ephemeral_persona_creds` (in-memory, not logged) |
| AC-NFR-2: ≤15s switch latency | Cached auth state re-use → ~1-3s; cold login → ~10-15s |
| AC-NFR-3: ACCOUNT_SWITCH unaffected | `persona_switch_node` is additive; `switch_actor()` path unchanged |
| AC-HAPPY-4: No bleed-through | localStorage.clear() + new context state applied per switch |

---

## Open Questions Resolved

1. **Does persona_switch_node need its own WebSocket message types?** → Yes. Two new types: `PERSONA_SWITCH_START` and `PERSONA_SWITCH_COMPLETE`. Reuses existing WS broadcast infrastructure in `routes.py`.

2. **What does the agent do after the switch?** → Navigates to `target_url` (app root). The next AC step is responsible for navigating to the relevant page. This keeps the switch atomic and simple.

3. **How does the HITL credential gate differ from existing `human_takeover_node`?** → It uses the same `asyncio.Event` pause pattern but a new endpoint (`POST /runs/{run_id}/persona-credentials`) and a new frontend modal variant. The existing HITL node is NOT reused — the persona credential gate is self-contained within `persona_switch_node`.
