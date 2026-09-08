# Architecture: RunOrchestrator + Parallel Context Pool

**Task**: execution-performance-overhaul-high-throughput-pipeline-engi / FEAT-060 — Phase 3: Horizontal Scaling & Parallelism
**Component**: `backend/engine/run_orchestrator.py` [NEW]
**Author**: vc-creative orchestrator (inline)
**Date**: 2026-05-31

---

## Decision

**Chosen**: Option A — Context Pool as LangGraph Orchestration Layer (asyncio.gather)
**Rationale**: Zero changes to `graph.py`. Minimal BrowserManager change (optional injected context). Clean separation of concerns. Feature flag isolates the new path entirely. Fully testable with mock browser contexts. Complexity is appropriate for a `PARALLEL_TICKET_POOL_SIZE=3` initial target.

---

## Component Design

### Overview

```
POST /execute-batch (routes.py)
    └── RunOrchestrator.dispatch_batch(tickets: list[str], pool_size: int)
            │
            ├── Acquires shared Playwright Browser instance (singleton)
            ├── Creates N BrowserContext objects (one per ticket slot)
            ├── asyncio.gather(
            │       _run_ticket(ticket_1, ctx_1),
            │       _run_ticket(ticket_2, ctx_2),
            │       _run_ticket(ticket_3, ctx_3)
            │   )
            │   └── Each _run_ticket:
            │           ├── Builds VQAState (unique run_id, ticket, role)
            │           ├── Injects browser context into BrowserManager
            │           ├── graph.ainvoke(state) → completes independently
            │           └── Returns individual RunResult
            └── RunReportAggregator.merge(results) → BatchRunReport
```

### Key Data Structures

```python
@dataclass
class TicketJob:
    ticket_id: str
    role: str
    run_id: str               # UUID, unique per parallel slot
    browser_context: BrowserContext  # Playwright context (isolated)

@dataclass
class RunResult:
    ticket_id: str
    run_id: str
    status: Literal["PASS", "FAIL", "ERROR"]
    ac_steps_completed: list[int]
    s3_report_url: str
    error: str | None
    duration_seconds: float

@dataclass
class BatchRunReport:
    batch_id: str
    results: list[RunResult]
    total_pass: int
    total_fail: int
    duration_seconds: float
```

### RunOrchestrator Class

```python
# backend/engine/run_orchestrator.py

class RunOrchestrator:
    """
    Manages parallel ticket execution with isolated Playwright browser contexts.

    Architecture:
    - One shared Playwright Browser instance (launched once per process)
    - N independent BrowserContext instances (one per concurrent ticket)
    - asyncio.Semaphore gates concurrent access to pool_size slots
    - Each ticket runs in its own asyncio task via asyncio.gather()

    Feature flag: PARALLEL_TICKETS_ENABLED=false → dispatch_batch falls through
    to single-ticket sequential execution (identical to existing /execute path).
    """

    def __init__(self, pool_size: int = 3):
        self._pool_size = pool_size
        self._semaphore = asyncio.Semaphore(pool_size)
        self._browser: Browser | None = None
        self._playwright: Playwright | None = None

    async def start(self) -> None:
        """Launch shared browser instance."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self) -> None:
        """Shut down browser and playwright."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def dispatch_batch(
        self,
        tickets: list[TicketJob],
        graph: CompiledStateGraph,
    ) -> BatchRunReport:
        """
        Dispatch N tickets in parallel, each in an isolated browser context.
        Respects pool_size via semaphore — excess tickets queue automatically.
        """
        tasks = [self._run_ticket(job, graph) for job in tickets]
        results: list[RunResult] = await asyncio.gather(*tasks, return_exceptions=True)
        # Handle exceptions from gather (convert to RunResult with ERROR status)
        resolved = self._resolve_results(tickets, results)
        return RunReportAggregator.merge(resolved)

    async def _run_ticket(
        self,
        job: TicketJob,
        graph: CompiledStateGraph,
    ) -> RunResult:
        """
        Run a single ticket in a semaphore-gated browser context.

        Semaphore ensures at most pool_size contexts are active simultaneously.
        BrowserContext is created fresh for each ticket (no reuse between runs)
        to guarantee zero state cross-contamination.
        """
        async with self._semaphore:
            ctx: BrowserContext = await self._browser.new_context(
                record_video_dir=f"/tmp/vqa-videos/{job.run_id}/"
            )
            try:
                initial_state = build_initial_state(job, injected_context=ctx)
                final_state: VQAState = await graph.ainvoke(initial_state)
                return RunResult(
                    ticket_id=job.ticket_id,
                    run_id=job.run_id,
                    status="PASS" if _all_steps_passed(final_state) else "FAIL",
                    ac_steps_completed=final_state.get("ac_steps_completed", []),
                    s3_report_url=final_state.get("s3_report_url", ""),
                    error=None,
                    duration_seconds=_elapsed(initial_state),
                )
            except Exception as e:
                logger.error("[%s] Ticket run failed: %s", job.run_id, e)
                return RunResult(
                    ticket_id=job.ticket_id, run_id=job.run_id,
                    status="ERROR", ac_steps_completed=[],
                    s3_report_url="", error=str(e), duration_seconds=0.0,
                )
            finally:
                await ctx.close()  # Always release context
```

### BrowserManager Change (Minimal / Surgical)

```python
# backend/browser/context.py — MODIFICATION ONLY

class BrowserManager:
    def __init__(
        self,
        run_id: str,
        injected_context: BrowserContext | None = None,  # [NEW PARAM]
    ):
        self._run_id = run_id
        self._injected_context = injected_context  # Used by RunOrchestrator

    async def start(self) -> Page:
        if self._injected_context:
            # RunOrchestrator path: use pre-created isolated context
            self._context = self._injected_context
            self._page = await self._context.new_page()
            return self._page
        else:
            # Existing path: create browser + context from scratch (unchanged)
            ...existing logic...
```

### VQAState Extension

```python
# Add to VQAState in backend/engine/state.py

# ── Parallel Execution (FEAT-060 Phase 3) ───────────────────────────
# Set by RunOrchestrator when PARALLEL_TICKETS_ENABLED=true.
# batch_id links this run to the parent BatchRunReport.
batch_id: str | None

# Parallel step groups from DependencyAnalyzer (Phase 3A)
# [[0, 2], [1], [3, 4]] = steps 0+2 parallel, then 1, then 3+4
parallel_step_groups: list[list[int]] | None

# Prefetch cache for speculative KB pre-fetch (Phase 1D)
prefetch_cache: dict  # keyed by step index
```

### Routes Integration

```python
# backend/api/routes.py — NEW ENDPOINT

@router.post("/execute-batch")
async def execute_batch(request: BatchExecuteRequest):
    if not settings.parallel_tickets_enabled:
        # Feature flag off: run sequentially
        results = [await execute_single(t) for t in request.tickets]
        return BatchRunReport(...)

    orchestrator = get_run_orchestrator()  # Process-level singleton
    batch_id = str(uuid4())
    jobs = [TicketJob(t.ticket_id, t.role, f"run-{uuid4()}", ...) for t in request.tickets]
    report = await orchestrator.dispatch_batch(jobs, build_graph())
    return report
```

### Redis Integration (when enabled)

```python
# Only activated when PARALLEL_TICKETS_ENABLED=true AND state_store=redis

# backend/storage/redis_state.py [NEW - Phase 3 only]
class RedisStateStore:
    """
    Stores BatchRunReport and per-run VQAState fragments in Redis for
    cross-process polling via GET /batch-status/{batch_id}.

    NOT required for single-process parallel execution (asyncio.gather).
    Only needed when scaling to multiple uvicorn workers or pods.
    """
```

---

## Options Explored

### Option A — Context Pool as LangGraph Orchestration Layer ✅ CHOSEN
- asyncio.gather() on N graph.ainvoke() calls
- Each gets isolated BrowserContext
- graph.py unchanged
- **Score: 17/18**

### Option B — Thread-Per-Ticket with asyncio.Queue
- Worker pool consuming from queue
- More flexible backpressure
- More complex result aggregation
- **Score: 14/18**

### Option C — RunOrchestrator Manages Browser Lifecycle Independently
- Pre-warmed context pool
- Faster cold start
- More invasive graph.py changes
- **Score: 14/18**

### Option D — Redis-Backed Distributed Orchestration
- True multi-machine scaling
- Far exceeds Phase 3 scope
- Infrastructure dependency bloat
- **Score: 7/18**

---

## Evaluation Matrix

| Criteria | Weight | Option A | Option B | Option C | Option D |
|----------|--------|----------|----------|----------|----------|
| Fits existing graph.py patterns | High | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ |
| State isolation (Critical) | Critical | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| Testability | High | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ |
| Implementation effort | Medium | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ |
| Performance (cold start) | Medium | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| Feature flag safety | High | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| **Total** | | **17** | **14** | **14** | **7** |

---

## Guiding Principle Compliance

| Principle | Compliance | Notes |
|-----------|------------|-------|
| Config in Environment | ✅ | `PARALLEL_TICKETS_ENABLED`, `PARALLEL_TICKET_POOL_SIZE` in `.env` |
| 12-Factor App | ✅ | Stateless per invocation; no shared mutable state across contexts |
| HITL as Learning Signal | ✅ | Each run's HITL writes to KB independently; no cross-contamination |
| Failure Diary Pattern | ✅ | `ac_step_failure_diary` is per-VQAState, per-run — fully isolated |

---

## Implementation Notes for Build Phase

1. **`run_orchestrator.py`**: New file. `RunOrchestrator` class with `start()`, `stop()`, `dispatch_batch()`, `_run_ticket()`.
2. **`browser/context.py`**: Add `injected_context: BrowserContext | None = None` param to `BrowserManager.__init__()` and `start()`.
3. **`engine/state.py`**: Add `batch_id`, `parallel_step_groups`, `prefetch_cache` fields.
4. **`api/routes.py`**: Add `POST /execute-batch` endpoint. Add `get_run_orchestrator()` singleton factory.
5. **`api/schemas.py`**: Add `BatchExecuteRequest`, `BatchRunReport` Pydantic models.
6. **`config.py`**: Add `parallel_tickets_enabled: bool = False` and `parallel_ticket_pool_size: int = 3`.
7. **Redis**: Add `redis`, `hiredis` to `requirements.txt`. `RedisStateStore` is conditional on `state_store=redis` setting. Not activated by default.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| State cross-contamination | Each BrowserContext is `new_context()` — completely isolated cookies, localStorage, session |
| asyncio.gather() exception propagation | Wrap each `_run_ticket` in try/except → return RunResult with ERROR status |
| Video recording in parallel | Each context gets its own `record_video_dir` keyed by `run_id` |
| WebSocket streaming per run | Each run has unique `run_id` → unique WebSocket room → no fan-out conflict |
| Resource leak on crash | `finally: await ctx.close()` in `_run_ticket` guarantees context release |

---

## Acceptance Criteria Traceability

| AC | Covered By |
|----|-----------|
| AC-HAPPY-6: 3 concurrent tickets, no cross-contamination | `_run_ticket` isolated context + VQAState per ticket |
| AC-ENTRY-1: `PARALLEL_TICKETS_ENABLED=false` → zero regression | Feature flag in routes.py falls through to sequential path |
| AC-NFR-1: ≥ 90% AC step pass rate | Isolation ensures no inter-ticket interference |
