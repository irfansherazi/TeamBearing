# Architecture Decision: parallel-headless-suite-runner-with-pass-fail-report Parallel Headless Suite Runner

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: parallel-headless-suite-runner-with-pass-fail-report / FEAT-109

---

## Context

### System Requirements

parallel-headless-suite-runner-with-pass-fail-report introduces a **"▶ Run All Tests"** capability that enables quality assurance engineers to launch all regression tests defined in the system concurrently and view an aggregated report in real-time. This requires a high-performance, non-blocking backend orchestrator and an elegant state management layer.

### Technical Constraints

1. **Concurrency Controls**: A suite run can consist of 40+ tests. Spawning all of them at once would saturate server resources, causing CPU thrashing, memory exhaustion, and test flakiness due to resource starvation. Concurrency must be strictly limited via an asynchronous semaphore.
2. **Execution Safety**: If a single test enters an infinite loop, it could block a worker slot indefinitely. Subprocesses must have a rigid per-test timeout of **180 seconds**.
3. **State Persistence**: A suite run takes several minutes. If the user refreshes their browser, navigates away, or has a temporary network disruption, they must not lose the suite's execution status or results. The state must be preserved in-memory on the backend and queryable via ID.
4. **PID and Orphan Cleanup**: Spawning multiple async subprocesses introduces risk of orphan processes if the parent FastAPI server restarts or shuts down. All subprocess PIDs must be registered in the existing global `_playwright_pids` dictionary for automatic SIGTERM cleanup.
5. **No Visual Overhead**: Unlike single-test executions which run in headed mode for live streaming to VNC, the regression suite must execute entirely in **headless mode** to conserve memory and execution overhead.

---

## Component Analysis

### Core Components Affected

| Component | File | Change Type | Purpose / Responsibility |
|-----------|------|-------------|--------------------------|
| `playwright_routes.py` | `backend/api/playwright_routes.py` | **MODIFY** | Mount new endpoints `POST /playwright/run-all` and `GET /playwright/run-all/{suite_run_id}/report`. Implement the background suite orchestrator, semaphore concurrency controls, and subprocess timeout handling. |
| `_playwright_pids` | `backend/api/playwright_routes.py` | **MODIFY** | Track suite subprocess PIDs under custom keys (`{suite_run_id}-{test_id}`) to ensure standard lifespan teardown cleanup. |
| `SuiteResultsPanel` | `frontend/src/components/SuiteResultsPanel.tsx` | **NEW** | Render KPI metrics cards, scrollable table of all execution outcomes, and collapsible standard error details for failed test runs. |
| `PlaywrightPage` | `frontend/src/pages/PlaywrightPage.tsx` | **MODIFY** | Add "▶ Run All Tests" UI trigger button next to the config controls, handle active/completed suite state, poll report API every 1.5s, and swap view to `SuiteResultsPanel` when active/completed. |

### Component Interaction Diagram

```
[UI: PlaywrightPage] 
       │
       ├──(1) Click "▶ Run All Tests"
       ▼
[POST /api/playwright/run-all]
       │
       ├──(2) Checks _active_suite_run_id (Lock Guard: returns 429 if active)
       ├──(3) Generates suite_run_id (e.g., suite-xxxxxx) & initializes empty report state
       ├──(4) Spawns background task: asyncio.create_task(_run_all_suite_background(suite_run_id))
       ▼
[HTTP 200: { suite_run_id }] (Returns immediately to frontend)
       │
       ├───────── (Frontend begins 1.5s periodic polling GET /api/playwright/run-all/{suite_run_id}/report)
       │
       ▼
[Background Task: _run_all_suite_background]
       │
       ├──(1) Retrieves all tests from PlaywrightRegistry
       ├──(2) Configures asyncio.Semaphore(int(os.getenv("VQA_SUITE_WORKERS", 4)))
       ├──(3) Launches concurrent workers: asyncio.gather(*[_run_single_suite_test(...)])
       │
       ▼
[Subprocess Worker: _run_single_suite_test]
       │
       ├──(1) Acquires Concurrency Semaphore Slot
       ├──(2) Spawns Headless Subprocess: npx playwright test <file> --project=<browser> --headed=false
       ├──(3) Registers process.pid to _playwright_pids under key "{suite_run_id}-{test_id}"
       ├──(4) Executes with timeout: asyncio.wait_for(..., timeout=180.0)
       │         ├──► [Timeout Occurs] ──► Terminate process, set FAIL, record "TimeoutError"
       │         └──► [Exits Normal] ──► Record PASS or FAIL, duration, and stderr tail snippet (last 5 lines)
       ├──(5) Releases Concurrency Semaphore Slot
       └──(6) Atomically updates aggregate counts (passed, failed) and individual test row results in _suite_runs
```

---

## State Management Design

We will maintain state in-memory inside the `playwright_routes.py` module using standard dictionary-based structures. This is lightweight, fast, and does not introduce database dependencies.

```python
# Module-level state additions
_suite_runs: Dict[str, Any] = {}
_active_suite_run_id: Optional[str] = None
```

### Report JSON Schema
The `GET /api/playwright/run-all/{suite_run_id}/report` endpoint returns the following structured JSON payload:

```json
{
  "suite_run_id": "suite-9a2c8b",
  "status": "running",
  "started_at": "2026-06-09T14:30:15.120Z",
  "completed_at": null,
  "total": 41,
  "passed": 3,
  "failed": 1,
  "results": [
    {
      "test_id": "qa-100-script-library.test",
      "name": "QA-100: Script Library",
      "status": "PASS",
      "duration_ms": 14250.0,
      "error_snippet": null
    },
    {
      "test_id": "qa-101-client-merging.test",
      "name": "QA-101: Client Merging",
      "status": "FAIL",
      "duration_ms": 180000.0,
      "error_snippet": "TimeoutError: Execution exceeded 180 seconds"
    }
  ]
}
```

---

## Subprocess Execution & Lifecycle Design

Each test executes as an independent asyncio subprocess using `asyncio.create_subprocess_exec`.

### Environment Configuration
To run completely headlessly and utilize the pre-authenticated sessions, the subprocess environment is configured with:
- `TEST_ENV`: Set from the request's env (e.g. `test`).
- `STORAGE_DIR`: Pre-populated environment storage state folder.
- `STORAGE_STATE_PATH`: Specific storage state path if available.
- `PLAYWRIGHT_HTML_REPORT` & `PLAYWRIGHT_JSON_OUTPUT_NAME`: Unique output report locations to prevent write collisions between parallel runs.
- **No headed flag**: The `--headed` flag is omitted, or `--headed=false` is explicitly passed.

### Concurrency and Lock Implementation
The lock checks are non-blocking and fail-fast:

```python
global _active_suite_run_id
if _active_suite_run_id is not None:
    raise HTTPException(status_code=429, detail="Suite run already in progress")
```

The background worker schedules concurrent runs safely using `asyncio.Semaphore`:

```python
workers = int(os.getenv("VQA_SUITE_WORKERS", 4))
sem = asyncio.Semaphore(workers)

async def _run_with_semaphore(test_meta):
    async with sem:
        await _run_single_suite_test(suite_run_id, test_meta, env, browser)

tasks = [_run_with_semaphore(t) for t in list_of_tests]
await asyncio.gather(*tasks)
```

### Timeout and Process Cleanup
If a subprocess times out, we catch `asyncio.TimeoutError` and terminate the process explicitly:

```python
try:
    # Spawn the process
    process = await asyncio.create_subprocess_exec(...)
    _playwright_pids[f"{suite_run_id}-{test_id}"] = process.pid
    
    # Wait for completion or timeout
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180.0)
    exit_code = process.returncode
except asyncio.TimeoutError:
    # Kill the process
    try:
        process.terminate()
        await process.wait()
    except Exception:
        pass
    exit_code = -1
    stderr = b"TimeoutError: Execution exceeded 180 seconds"
finally:
    _playwright_pids.pop(f"{suite_run_id}-{test_id}", None)
```

---

## Observability and Telemetry

No `print()` or `console.log()` statements. All background steps are tracked using structured logs for easy correlation in production:

```json
{
  "timestamp": "2026-06-09T14:30:15.150Z",
  "level": "INFO",
  "traceId": "suite-9a2c8b",
  "module": "backend.api.playwright_routes",
  "message": "Starting parallel headless suite run",
  "data": {
    "total_tests": 41,
    "concurrency_limit": 4,
    "browser": "chromium",
    "environment": "test"
  }
}
```

```json
{
  "timestamp": "2026-06-09T14:31:05.452Z",
  "level": "INFO",
  "traceId": "suite-9a2c8b",
  "module": "backend.api.playwright_routes",
  "message": "Suite test execution completed",
  "data": {
    "test_id": "qa-100-script-library.test",
    "status": "PASS",
    "duration_ms": 14250.0,
    "exit_code": 0
  }
}
```
