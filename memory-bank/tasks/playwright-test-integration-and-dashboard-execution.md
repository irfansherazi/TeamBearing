---
legacy_id: playwright-test-integration-and-dashboard-execution
---
# playwright-test-integration-and-dashboard-execution: Playwright Test Integration & Dashboard Execution

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 3
**Created**: 2026-05-27
**Roadmap Link**: FEAT-051
**Branch**: feature/FEAT-051-playwright-integration

## Context
Integrate static Playwright test execution into the vQA Dashboard. This allows users to choose between the autonomous AI Agent (standard) and pre-written static Playwright tests (Phase 1 of the Playwright library migration).

## Acceptance Criteria
- [x] **Registry**: A JSON-backed registry in `backend/storage/playwright_registry.json` tracks discovered tests.
- [x] **Node**: `playwright_executor_node` in `backend/engine/playwright_executor.py` handles subprocess execution.
- [x] **Streaming**: Subprocess output is streamed in real-time to the frontend via WebSockets using `WSTerminalLogMessage`.
- [x] **Branching**: The execution graph branches based on `execution_engine` (ai vs static).
- [x] **UI**: An "Execution Engine" toggle in the `ExecutionPanel` allows selecting between "AI Agent" and "Static Playwright".
- [x] **Library**: A `PlaywrightLibrary` component displays available tests from the registry.

## Tasks
### WI-059-001: Phase 1 — Registry & Discovery
- [x] Create `backend/playwright_tests/` directory and `demo.spec.ts`.
- [x] Implement `PlaywrightRegistry` in `backend/storage/playwright_registry.py`.
- [x] Add unit tests in `tests/test_playwright_registry.py`.

### WI-059-002: Phase 2 — Subprocess Executor & Graph Wiring
- [x] Update `VQAState` and `ExecuteRequest` schemas.
- [x] Implement `playwright_executor_node` in `backend/engine/playwright_executor.py`.
- [x] Add real-time streaming to `backend/api/routes.py` via `_broadcast_terminal_log`.
- [x] Wire conditional branching in `backend/engine/graph.py`.

### WI-059-003: Phase 3 — Frontend Integration
- [x] Create `PlaywrightLibrary` UI component.
- [x] Update `ExecutionPanel` with engine toggle and library view.
- [x] Update `useWebSocket` and `ExecutionLog` for real-time log streaming.
- [x] Verify full execution flow (Static path).

## Reflection

### What Went Well
- **Real-time Feedback**: Subprocess log streaming provides a smooth UX for long-running static tests.
- **Modular Graph**: Conditional branching in LangGraph was clean and didn't complicate the AI path.
- **Registry Simplicity**: JSON-based discovery is fast and easy to maintain for Phase 1.

### Technical Debt Identified
- **TD-036**: Need automated filesystem watcher for registry sync.
- **TD-037**: Missing context/secret injection for static tests.
- **TD-038**: Raw logs need rich parsing (screenshots/traces).
- **TD-039**: State bloat from engine-specific fields.

### Lessons Learned
- Subprocess streaming requires careful handling of line buffering to ensure real-time delivery.
- Engine-agnostic routing allows the vQA platform to evolve from "pure AI" to a hybrid "AI + Deterministic" tool.
