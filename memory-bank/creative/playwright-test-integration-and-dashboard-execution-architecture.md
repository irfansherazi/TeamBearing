# playwright-test-integration-and-dashboard-execution: Playwright Test Integration Architecture

## Overview
This document outlines the architectural changes required to integrate static Playwright tests into the vQA engine.

## 1. State Schema Updates (`VQAState`)
To support static execution, the `VQAState` will be extended with:
- `execution_engine`: `Literal["ai", "static"]` (defaults to `"ai"`)
- `playwright_test_id`: `str | None` (ID of the selected static test)
- `static_execution_log`: `list[str]` (Captured stdout from the Playwright process)

## 2. Playwright Registry (`backend/storage/playwright_registry.py`)
A new service to manage the library of static tests.
- **Storage**: `backend/storage/playwright_registry.json`
- **Schema**:
  ```json
  {
    "tests": [
      {
        "id": "login-qo-001",
        "name": "Login & Quick Order",
        "description": "Standard AE login and QO creation",
        "file_path": "backend/playwright_tests/login_qo.spec.ts",
        "tags": ["vsuite", "ae", "smoke"]
      }
    ]
  }
  ```
- **Capabilities**:
  - `list_tests()`: Returns all registered tests.
  - `get_test(test_id)`: Returns metadata for a specific test.
  - `sync_registry()`: Scans `backend/playwright_tests/` and updates the JSON.

## 3. Playwright Executor Node (`backend/engine/playwright_executor.py`)
A new LangGraph node responsible for running the static test.
- **Process Management**: Uses `asyncio.create_subprocess_exec` to run `npx playwright test`.
- **Environment**: Sets `DISPLAY=:1` to ensure the test runs in the Xvfb display visible via VNC.
- **Log Streaming**: 
  - Captures stdout/stderr line-by-line.
  - Wraps each line in a `WSTerminalMessage` and broadcasts to the `run_id` room.
  - Appends to `state["static_execution_log"]`.
- **Completion**: Updates `state["success"]` based on the process exit code.

## 4. Graph Topology Updates
The `StateGraph` in `backend/engine/graph.py` will be modified:

```python
# Before
login -> replay_check -> planner

# After
login -> execution_router
execution_router -> playwright_executor (if execution_engine == "static")
execution_router -> replay_check (if execution_engine == "ai")
playwright_executor -> reporter
```

## 5. File Retrieval Mechanism
A script `scripts/sync_playwright_tests.py` will be created to:
- Clone/pull the `vsuitePlatform` repository.
- Copy relevant `.spec.ts` files to `backend/playwright_tests/`.
- Register them in `playwright_registry.json`.

## 6. Real-time Log Streaming
We will introduce a new WebSocket message type `WSTerminalMessage` to distinguish between structured agent logs and raw terminal output.
```typescript
interface WSTerminalMessage {
  type: 'terminal';
  run_id: string;
  payload: {
    line: string;
    stream: 'stdout' | 'stderr';
  };
}
```
