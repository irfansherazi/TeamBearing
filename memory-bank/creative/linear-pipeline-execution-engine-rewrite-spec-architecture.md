# Architecture: linear-pipeline-execution-engine-rewrite-spec Linear Pipeline Execution Engine

**Task**: linear-pipeline-execution-engine-rewrite-spec / FEAT-105  
**Date**: 2026-06-04  
**Author**: Creative Design Agent (aligned with PE sign-off guidelines)

---

## 1. Linear Pipeline DAG Architecture

The vQA execution engine is refactored from a non-deterministic cyclic LangGraph loop into a linear, four-node Directed Acyclic Graph (DAG) executed in-memory.

```
       BDD Step
          │
          ▼
   ┌──────────────┐
   │ Generate     │ ──► Pre-run Offline LLM (Generates Playwright Spec .spec.ts)
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Validate     │ ──► Compilation (npx tsc --noEmit) & Runtime Schema Verification
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Execute      │ ──► Headless Playwright (VQA Custom Selector engine, telemetry bridging)
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Analyze      │ ──► Post-run Failure Translation (Extract stack traces back to AC steps)
   └──────────────┘
```

---

## 2. Multi-Tenancy Directory & RAG Boundaries

To ensure complete customer isolation and high performance, the execution engine enforces strict directory partition gating.

### Directory Structure:
```
tenants/
  ├── vpromedia/
  │    ├── vqa.config.json    # Tenant credentials, browser preferences, timing overrides
  │    ├── selectors.json     # Isolated locator catalog (VQA Keys to legacy strategies)
  │    └── helpers/
  │         └── SearchHelper.ts # Custom, pre-baked interaction routines
  └── tenant_b/
       ├── vqa.config.json
       ├── selectors.json
       └── helpers/
```

### Retrieval Isolation Boundaries:
1. **Selector RAG Budget**: Selector context injection is limited to the top-5 BM25 matches retrieved from `selectors.json`. This maintains a tight token envelope (<200 tokens).
2. **Context Helper Inject Fallback**: If the tenant's custom `helpers/` folder contains fewer than 10 files, the engine bypasses RAG and merges all helper functions into the prompt context to prevent fragmented/incomplete selector libraries.
3. **Hard Path Gating**: Under no circumstances can files or mappings from `tenants/tenant_b` be loaded during a `vpromedia` pipeline execution. File-system queries use the active `tenantId` to construct absolute paths, throwing a path traversal error if any directory traversal indicators (`..`) are found.

---

## 3. Distributed Telemetry & Trace Propagation

To maintain consistent observability across process boundaries, the orchestrator propagates W3C Trace Context coordinates through standard environment variables and event listeners.

```
┌──────────────────────────────────────────────┐
│        Orchestration Node (Parent)           │
│  - Generates: traceId, spanId                │
│  - Logs: structured OpenTelemetry JSON       │
└──────────────────────┬───────────────────────┘
                       │
                       │ Spawns Playwright Subprocess
                       │ Passes: VQA_TRACE_ID, VQA_SPAN_ID, VQA_TENANT_ID
                       ▼
┌──────────────────────────────────────────────┐
│         Playwright Runtime (Child)           │
│  - Executes custom vqaEngine                 │
│  - Captures selector warnings                │
│  - Logs warnings via console.warn()          │
└──────────────────────┬───────────────────────┘
                       │
                       │ Playwright page.on('console') event
                       │ Bridges browser JSON log back to parent process
                       ▼
┌──────────────────────────────────────────────┐
│        Orchestration Logger (Parent)         │
│  - Parses JSON warning logs                  │
│  - Emits normalized OpenTelemetry trace logs │
└──────────────────────────────────────────────┘
```

### Telemetry Schema (OpenTelemetry-aligned Single-Line JSON):
All logs printed to `stdout` must follow this rigid format:
```json
{
  "timestamp": "2026-06-04T15:20:00.123Z",
  "level": "INFO|WARN|ERROR",
  "node": "Generate|Validate|Execute|Analyze",
  "message": "Step description/event",
  "tenant_id": "vpromedia",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "technical_debt_metrics": { "selector": "submit_btn", "type": "legacy_css" } // Optional, for WARN level
}
```

### Trace Bridge Event Listener (in `Execute` node):
```typescript
page.on('console', msg => {
  if (msg.type() === 'warning' || msg.type() === 'error') {
    const text = msg.text();
    try {
      const parsed = JSON.parse(text);
      if (parsed.message === 'VQA_SELECTOR_FALLBACK') {
        _logEvent({
          level: 'WARN',
          node: 'Execute',
          message: 'VQA_SELECTOR_FALLBACK',
          tenant_id: tenantId,
          technical_debt_metrics: parsed.technical_debt_metrics
        });
      }
    } catch {
      // Ignore non-structured browser console statements
    }
  }
});
```

---

## 4. Dependency Injection for High-Speed Unit Testing

To guarantee unit-testing speeds **under 100ms** and remove dependencies on live LLM APIs or actual Playwright subprocesses, the `LinearPipeline` class utilizes a clean **Dependency Injection (DI)** design.

### DI Class Signature Concept:
```typescript
export interface PipelineDependencies {
  execShell: (command: string, env: Record<string, string>) => Promise<{ stdout: string; stderr: string; code: number }>;
  readJsonFile: <T>(path: string) => T;
  writeTextFile: (path: string, content: string) => void;
  llmGenerate: (prompt: string) => Promise<string>;
}

export class LinearPipeline {
  private deps: PipelineDependencies;
  private tenantId: string;
  private retryCounts = { compile: 0, execute: 0 };

  constructor(tenantId: string, deps: PipelineDependencies) {
    this.tenantId = tenantId;
    this.deps = deps;
  }

  public async run(bddStep: string): Promise<string> {
    // Pipeline DAG execution steps using this.deps
  }
}
```

### Test Strategy Benefit:
By replacing `child_process.exec` and fs modules with injectable stubs, our `tests/core/pipeline.spec.ts` unit tests can test all critical self-healing code paths:
- Mocking compilation failure on first run, success on second run (verifying compile retry success).
- Mocking double compile failures (verifying `COMPILE_FAILED` halt).
- Mocking execution collision failures on first run, success on second run (verifying collision recovery).
- Mocking double execution failures (verifying escalation to human).
All of these can run in isolated NodeJS microtasks in milliseconds.
