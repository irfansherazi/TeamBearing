---
legacy_id: FEAT-080
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-080: ARIA-Tree-Aware Loop Detection
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: medium
- **Complexity**: Level 2
- **Pillar**: P2 — Execution Engine Reliability
- **Gap ID**: P2-B
- **Estimated Effort**: ~4h
- **Description**: The amnesic loop detector uses only URL + element count signals, causing false circuit breaker trips on Angular SPAs where sort/highlight actions change the ARIA tree without changing URL or element count. Fix: add ARIA tree fingerprinting (SHA-256 of serialized ARIA tree) to the stagnation detection signal set. Only trigger the circuit breaker when URL, element count, AND ARIA fingerprint are all unchanged across N consecutive steps.
- **Acceptance Criteria**:
  - AC-1: Each post-action state snapshot includes an ARIA tree fingerprint (SHA-256 of the serialized accessible tree).
  - AC-2: The stagnation detector requires URL unchanged AND element count unchanged AND ARIA fingerprint unchanged across N steps before tripping.
  - AC-3: Sort and highlight actions that mutate ARIA attributes (e.g., `aria-sort`, `aria-selected`) do not trigger false circuit breaker trips.
  - AC-4: Regression test: 5 consecutive sort actions on a PrimeNG table do not trigger the circuit breaker.
- **Key Files**:
  - `backend/engine/verifier.py` — stagnation detector
  - `backend/engine/state.py` — state snapshot schema
  - `backend/browser/context.py` — ARIA tree serializer
- **Linked Tasks**: None
- **Branch**: feature/FEAT-080-aria-loop-detection
- **Created**: 2026-06-03
