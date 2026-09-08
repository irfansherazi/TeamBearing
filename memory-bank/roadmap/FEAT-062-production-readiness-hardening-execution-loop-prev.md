---
legacy_id: FEAT-062
version: next
linked_tasks: [production-readiness-hardening-and-execution-loop-prevention]
status: in_progress
---

### FEAT-062: Production Readiness Hardening & Execution Loop Prevention
- **Version**: next
- **Status**: in_progress
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: Address the critical reliability bottlenecks preventing vQA from being production-ready, as identified via live log analysis. The agent is currently susceptible to "amnesic loops" (burning the full `max_actions` budget on repetitive, unproductive actions) and crashes during critical rescue operations (Human Takeover). This feature implements four hardening pillars:

    **Pillar 1 — Semantic Progress Detection & Detour Routing**
    Implement an advanced circuit breaker in the evaluator. If the agent detects 3 consecutive actions resulting in `URL_UNCHANGED` AND `DOM_STABLE` (e.g., repeatedly scrolling a panel without finding a button), it must recognize it is in an "Amnesic Loop." Instead of burning the `max_actions` budget on the same strategy, it must trigger a "Detour Strategy" (e.g., page refresh, or navigating back to a known-safe anchor state) to reset the UI context. This goes beyond the existing identical-action circuit breaker by detecting _semantic stagnation_ — different actions, same null outcome.

    **Pillar 2 — Vision/DOM Dual-Verification for CV Fallback**
    Enhance the Computer Vision (Set-of-Marks) fallback verification. Currently, when the SoM fallback executes a coordinate-based `page.mouse.click(x, y)`, it only checks for DOM state changes to confirm success. If the target is a Canvas element or an obfuscated SPA component, the DOM does not change — causing the agent to falsely flag the click as failed and retry indefinitely. Verification for CV clicks must be upgraded to include **visual delta checks** (pre/post-action screenshot diffing) so that a rendered change on canvas or a visual state transition is recognized as a successful action even when the DOM tree is unchanged.

    **Pillar 3 — Human Takeover Crash Resolution**
    Fix the critical `TypeError` in `human_takeover.py` where `_broadcast_human_takeover()` is called with an unexpected `novnc_url` keyword argument. This bug currently causes a **hard crash of the entire run** instead of a graceful handover to the human operator via the interactive noVNC iframe. The fix must ensure the WebSocket broadcast signature matches its call-sites, handle the `novnc_url` field correctly, and include a smoke test to prevent regression.

    **Pillar 4 — Playwright Lifecycle & Zombie Process Mitigation**
    Fix the race condition causing `Unexpected browser.close() error: unable to perform operation on <WriteUnixTransport closed=True>` during the graph's shutdown sequence. The root cause is a double-close or premature-close path in the Playwright browser lifecycle management. The fix must implement an idempotent, order-safe teardown sequence that: (a) checks transport liveness before issuing `browser.close()`; (b) catches and swallows the `WriteUnixTransport` error if the transport is already closed; (c) ensures video recording `.webm` artifacts are finalized and flushed before context disposal so no orphaned video files are left in production environments.

- **Success Metrics**:
    - Zero instances of the agent burning the full `max_actions` budget on redundant actions (Amnesic Loop circuit breaker fires ≥ 95% of stagnation events)
    - 100% success rate on graceful WebSocket handovers during Human Takeover escalation (zero `TypeError` crashes)
    - Zero orphaned Playwright processes or `.webm` video leaks on run shutdown
    - CV fallback false-failure rate reduced to < 5% on Canvas/obfuscated SPA targets (dual-verification: DOM + visual delta)
- **Pillars**:
    - **Pillar 1**: Semantic Progress Detection & Detour Routing (evaluator circuit breaker + detour strategy dispatcher)
    - **Pillar 2**: Vision/DOM Dual-Verification for CV Fallback (screenshot diffing in SoM verifier)
    - **Pillar 3**: Human Takeover Crash Resolution (`human_takeover.py` `TypeError` fix + WebSocket signature alignment)
    - **Pillar 4**: Playwright Lifecycle & Zombie Process Mitigation (idempotent teardown + video artifact finalization)
- **Linked Tasks**: production-readiness-hardening-and-execution-loop-prevention
- **Branch**: feature/FEAT-062-production-readiness-hardening
