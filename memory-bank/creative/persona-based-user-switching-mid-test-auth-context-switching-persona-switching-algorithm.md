# persona-based-user-switching-mid-test-auth-context-switching: Persona-Based User Switching — Algorithm Design

**Phase**: Creative / Algorithm
**Status**: COMPLETE
**Generated**: 2026-05-28T10:08:00-05:00

---

## Decision

**Chosen**: Option A — Two-stage resolution with cached auth state application and asyncio.Event HITL gate

The persona switch algorithm uses a deterministic two-phase approach:
1. **Resolve**: Map `target_persona` string → canonical `role_key` (or `None` for unknown)
2. **Switch**: Clear session → apply stored auth state → navigate → verify JWT

The HITL path uses an `asyncio.Event` (identical to `human_takeover_node`'s pattern), resolved by a new API endpoint. Unknown persona credentials are held in an ephemeral in-memory dict keyed by `run_id`, discarded on run completion.

---

## Options Considered

### Option A — Two-Stage Resolution with Cached Auth State ✅ CHOSEN
- Stage 1: `resolve_target_persona(target_persona, run_memory) → role_key | None`
- Stage 2: `apply_persona_switch(page, context, role_key, run_id) → SwitchResult`
- Cached path: `ensure_role_authenticated(role_key)` returns pre-validated state path → `context.add_cookies()` + `page.goto(target_url)`
- HITL path: emit event → `asyncio.Event.wait()` → receive creds → fresh form login → (optionally cache in ephemeral dict)
- **Pros**: Clean deterministic steps; maximum code reuse; HITL pattern consistent with existing; credential security guaranteed by ephemeral dict.

### Option B — Full Page.context Re-creation per switch
- Close current context; create new context from storage state; re-open page
- **Pros**: Guaranteed clean slate (no cookie/cache residue)
- **Cons**: Playwright context creation takes ~500ms overhead vs `add_cookies()` + `goto`. Also loses any pre-init scripts (toast observer) — would require re-injection. Higher complexity; context teardown risks video recording interruption.

### Option C — Navigate to `/logout` URL + re-login form fill
- Navigate to app's logout endpoint, then fill login form
- **Pros**: Uses the app's own logout mechanism (might be cleaner from app perspective)
- **Cons**: vSuite logout URL is environment-specific and may not be a dedicated route. Requires UI form fill (slow, fragile, depends on locator stability). `localStorage.clear()` + state file restore is faster and more reliable for JWT-based SPAs.

---

## Algorithm Detail

### Phase 1: Persona Resolution

```python
SENTINEL_CURRENT_USER = "current_user"  # normalized from "as yourself"

def resolve_target_persona(
    target_persona: str,
    run_memory: dict
) -> tuple[str | None, str]:
    """
    Map target_persona string → (role_key | None, method).

    Returns:
        role_key: canonical role key (e.g. "digital_director") or None if unknown
        method: "stored" | "initial_actor" | None (when unknown → will become "hitl")
    """
    # Normalize
    persona_lower = target_persona.strip().lower()

    # Sentinel: "current_user" → initial_actor
    if persona_lower == SENTINEL_CURRENT_USER:
        initial_actor = run_memory.get("initial_actor", {})
        role_key = initial_actor.get("role_key")
        if role_key:
            return role_key, "initial_actor"
        # Fallback: initial_actor not tracked (should not happen in practice)
        return None, None

    # Try ROLE_REGISTRY direct lookup by role_key
    from backend.engine.roles import ROLE_REGISTRY
    if persona_lower in ROLE_REGISTRY:
        return persona_lower, "stored"

    # Try alias resolution (fuzzy-tolerant name matching)
    resolved = resolve_role_by_name(target_persona)   # existing function
    if resolved:
        return resolved["role_key"], "stored"

    # Unknown persona → HITL required
    return None, None
```

### Phase 2: Session Replacement Algorithm

```python
async def _perform_auth_switch(
    page: Page,
    context: BrowserContext,
    role_key: str,
    target_url: str,
    run_id: str,
) -> dict:
    """
    Replace the current browser auth context with role_key's stored state.

    Returns a SwitchResult dict:
      { "success": bool, "jwt_present": bool, "duration_ms": int }
    """
    t_start = time.monotonic()

    # Step 1: Clear existing auth tokens from localStorage
    #   - Removes JWT key (profile-specific, e.g. "vc2JWT")
    #   - Clears ALL localStorage to prevent partial-state bleed
    jwt_key = get_active_profile().jwt_storage_key or "vc2JWT"
    await page.evaluate(f"""
        localStorage.removeItem('{jwt_key}');
        localStorage.clear();
    """)
    logger.info("[%s] ✓ localStorage cleared for persona switch to '%s'", run_id, role_key)

    # Step 2: Load stored auth state (from ensure_role_authenticated)
    #   - Returns path to JSON storage state file (cookies + localStorage)
    #   - Validates TTL: if state is <4h old, re-use; otherwise re-authenticates
    state_path = ensure_role_authenticated(role_key)

    # Step 3: Apply auth state to existing context
    #   - add_cookies() applies the stored cookies to the live context
    #   - localStorage injection happens on next page.goto() via storageState protocol
    import json as _json
    with open(state_path) as f:
        storage_state = _json.load(f)

    # Apply cookies
    if storage_state.get("cookies"):
        await context.add_cookies(storage_state["cookies"])

    # Step 4: Navigate to app root (applies localStorage state + triggers SPA init)
    await page.goto(target_url, wait_until="networkidle", timeout=20000)

    # Step 5: Wait for SPA hydration (identical to post-login barrier)
    await _wait_for_post_login_spa_render(page, run_id)

    # Step 6: Inject stored localStorage values (JWT etc.)
    if storage_state.get("origins"):
        for origin in storage_state["origins"]:
            if target_url in origin.get("origin", ""):
                for item in origin.get("localStorage", []):
                    await page.evaluate(
                        f"localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                    )

    # Step 7: Verify JWT present
    jwt_value = await page.evaluate(f"localStorage.getItem('{jwt_key}')")
    jwt_present = bool(jwt_value)

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "[%s] Persona switch to '%s': jwt_present=%s, duration=%dms",
        run_id, role_key, jwt_present, duration_ms
    )

    return {"success": jwt_present, "jwt_present": jwt_present, "duration_ms": duration_ms}
```

### Phase 3: HITL Credential Gate Algorithm

```python
# Module-level state (per-run):
_persona_events: dict[str, asyncio.Event] = {}        # run_id → asyncio.Event
_persona_creds: dict[str, dict[str, dict]] = {}       # run_id → {persona_name → {email, pw}}

async def _wait_for_persona_credentials(
    run_id: str,
    persona_name: str,
    broadcast_fn: Callable,
) -> dict:
    """
    Pause graph execution and wait for operator to provide credentials.

    Broadcasts HITL_PERSONA_CREDENTIALS_REQUIRED to the run's WebSocket channel.
    Returns credential dict when operator submits; raises on timeout.
    """
    event = asyncio.Event()
    _persona_events[run_id] = event

    await broadcast_fn(run_id, {
        "type": "HITL_PERSONA_CREDENTIALS_REQUIRED",
        "persona_name": persona_name,
        "message": f"Unknown persona '{persona_name}'. Please provide login credentials.",
        "run_id": run_id,
    })

    try:
        await asyncio.wait_for(event.wait(), timeout=300.0)  # 5-minute gate
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"HITL persona credential gate timed out after 300s for run '{run_id}', "
            f"persona '{persona_name}'"
        )
    finally:
        _persona_events.pop(run_id, None)

    creds = _persona_creds.get(run_id, {}).get(persona_name)
    if not creds:
        raise RuntimeError(f"Credential gate resolved but no credentials found for '{persona_name}'")
    return creds


def set_persona_credentials(run_id: str, persona_name: str, email: str, password: str) -> None:
    """
    Called by the API endpoint POST /runs/{run_id}/persona-credentials.
    Stores credentials ephemerally and unblocks the waiting graph.
    """
    if run_id not in _persona_creds:
        _persona_creds[run_id] = {}
    _persona_creds[run_id][persona_name] = {"email": email, "password": password}

    event = _persona_events.get(run_id)
    if event:
        event.set()
```

### Phase 4: HITL-Path Form Login (for unknown personas)

```python
async def _login_with_ephemeral_creds(
    page: Page,
    email: str,
    password: str,
    target_url: str,
    run_id: str,
) -> dict:
    """
    Authenticate using operator-provided credentials (HITL path).
    Does NOT use ensure_role_authenticated() — these creds are not in the role registry.
    Does NOT save auth state to disk.
    """
    # Navigate to login page
    await page.goto(target_url, wait_until="networkidle", timeout=20000)

    # Fill login form (reuse login form locators from AppProfile)
    profile = get_active_profile()
    email_sel = profile.login_form_selectors.email_input
    password_sel = profile.login_form_selectors.password_input

    await page.get_by_role("textbox", name="Email").fill(email)
    await page.get_by_role("textbox", name="Password").fill(password)
    await page.get_by_role("button", name="Login").click()

    # Wait for SPA barrier
    await _wait_for_post_login_spa_render(page, run_id)

    # Verify JWT
    jwt_key = profile.jwt_storage_key or "vc2JWT"
    jwt_value = await page.evaluate(f"localStorage.getItem('{jwt_key}')")
    return {"success": bool(jwt_value), "jwt_present": bool(jwt_value), "duration_ms": 0}
```

### Full `persona_switch_node` Algorithm

```python
async def persona_switch_node(state: VQAState) -> dict:
    run_id = state["run_id"]
    target_url = state["target_url"]
    run_memory = state.get("run_memory", {})

    # 1. Extract target_persona from current structured step
    structured_step_index = state.get("structured_step_index", 0)
    test_plan = state.get("test_plan") or {}
    steps = test_plan.get("steps", [])
    if structured_step_index >= len(steps):
        logger.error("[%s] persona_switch_node: no step at index %d", run_id, structured_step_index)
        return {"_next_node": "planner"}

    current_step = steps[structured_step_index]
    target_persona = current_step.get("target_persona", "")

    if not target_persona:
        logger.warning("[%s] PERSONA_SWITCH step has no target_persona — skipping", run_id)
        return {"_next_node": "planner"}

    from_persona = state.get("current_persona", "")
    logger.info("[%s] 🔄 PERSONA SWITCH: '%s' → '%s'", run_id, from_persona, target_persona)

    # 2. Resolve role key
    role_key, method = resolve_target_persona(target_persona, run_memory)

    # Get browser context
    from backend.browser.context import get_manager
    manager = get_manager(run_id)
    page = manager.page
    context = manager._context

    t_start = time.monotonic()

    # 3. Execute switch
    if role_key and method in ("stored", "initial_actor"):
        # Happy path: known persona
        result = await _perform_auth_switch(page, context, role_key, target_url, run_id)
        if not result["success"]:
            # JWT not present after switch — treat as HITL
            logger.warning("[%s] Auth switch succeeded structurally but JWT missing", run_id)

    else:
        # Unknown persona → HITL credential gate
        from backend.api.routes import broadcast_ws_message
        creds = await _wait_for_persona_credentials(run_id, target_persona, broadcast_ws_message)
        result = await _login_with_ephemeral_creds(
            page, creds["email"], creds["password"], target_url, run_id
        )
        role_key = target_persona  # use raw name as the "role key" for tracking
        method = "hitl"

        # Store ephemerally for potential re-use within this run
        _persona_creds.setdefault(run_id, {})[target_persona] = creds

    # 4. Update state
    duration_ms = int((time.monotonic() - t_start) * 1000)
    switch_entry = {
        "from": from_persona,
        "to": role_key,
        "persona_name": target_persona,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "method": method,
        "duration_ms": duration_ms,
    }

    logger.info(
        "[%s] ✓ Persona switch complete: %s → %s (%s, %dms)",
        run_id, from_persona, role_key, method, duration_ms
    )

    # Broadcast completion
    try:
        from backend.api.routes import broadcast_ws_message
        await broadcast_ws_message(run_id, {
            "type": "PERSONA_SWITCH_COMPLETE",
            "from": from_persona,
            "to": role_key,
            "method": method,
            "duration_ms": duration_ms,
        })
    except Exception as ws_err:
        logger.warning("[%s] WS broadcast failed (non-fatal): %s", run_id, ws_err)

    return {
        "current_persona": role_key,
        "persona_switch_history": [switch_entry],  # appended via operator.add
        "_next_node": "planner",
    }
```

---

## Persona Resolution Table

| Input String | Normalized | Resolved Role Key | Method |
|---|---|---|---|
| `"as yourself"` | `current_user` | `run_memory.initial_actor.role_key` | `initial_actor` |
| `"As Yourself"` | `current_user` | (same) | `initial_actor` |
| `"AS YOURSELF"` | `current_user` | (same) | `initial_actor` |
| `"Demo Prod dir"` | (alias lookup) | `digital_director` | `stored` |
| `"Production Director"` | (alias lookup) | `digital_director` | `stored` |
| `"digital_director"` | (direct key) | `digital_director` | `stored` |
| `"account_executive"` | (direct key) | `account_executive` | `stored` |
| `"Bob Smith"` | (no match) | `None` | → HITL |

---

## Performance Targets

| Scenario | Target | How Achieved |
|---|---|---|
| Hot-path switch (cached state) | ≤ 3s | TTL check + `add_cookies` + `goto` (~1-3s) |
| Cold-path switch (fresh login) | ≤ 15s | Form fill + JWT poll + SPA barrier |
| HITL wait (operator action) | ≤ 300s | asyncio.Event timeout |

---

## Security Properties

| Concern | Algorithm Guarantee |
|---|---|
| Credentials at INFO level | `password` field in log lines uses scrubber pattern `re.sub(r'"password":\s*"[^"]*"', '"password": "***"', msg)` — pre-compiled at module load |
| Ephemeral storage | `_persona_creds[run_id]` is a module-level dict cleared by `unregister_manager(run_id)` callback in reporter_node teardown |
| No disk write | `_login_with_ephemeral_creds()` does NOT call `ensure_role_authenticated()` or any path that writes `auth_state` JSON files |
| JWT validation | After each switch, `localStorage.getItem(jwt_key)` confirms token presence before returning to planner |

---

## AC Parser Algorithm Changes

### Stage 1 — BDD Normalizer Prompt Addition

Add to `BDD_NORMALIZER_PROMPT`:

```
PERSONA SWITCH DETECTION:
When you encounter phrases like:
  - "as yourself", "as [Name]", "as [Role]", "switch to [Name]", "log in as [Role]"
  - "now acting as [Name]", "switch user to [Name]"
  - "log out and log back in as [Name]"

Emit a dedicated BDD step:
  Then: Switch to persona: [normalized Name or "yourself"]

Do NOT merge this into a preceding navigation or action step.
The persona name should be preserved as-is from the AC text (not role-key normalized).
```

### Stage 2 — JSON Compiler Prompt Addition

Add to `JSON_COMPILER_PROMPT`:

```
PERSONA_SWITCH steps:
- step_type: "PERSONA_SWITCH"
- target_persona: "<name from BDD step, exactly as written>"
- description: "Switch to persona: <name>"

Example:
{
  "step_type": "PERSONA_SWITCH",
  "target_persona": "Demo Prod dir",
  "description": "Switch to persona: Demo Prod dir",
  "preconditions": ["User is currently logged in"],
  "verifications": []
}
```
