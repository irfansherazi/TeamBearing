# User Journey Design: linear-pipeline-execution-engine-rewrite-spec Linear Pipeline Execution Engine

**Created**: 2026-06-04
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: linear-pipeline-execution-engine-rewrite-spec / FEAT-105

## Journey Overview

**Feature**: FEAT-105: Linear Pipeline Execution Engine Rewrite
**Primary Persona**: QA Automation Engineer, QA Lead, Platform Operator
**Journey Type**: Technical Pipeline Execution & Observability
**Orchestration Pattern**: Offline Pre-Generation, Validation Gate, Stateless Selection, Trace Logging

### Success Statement
> A QA Automation Engineer initiates a pipeline run for a tenant BDD step. They witness a deterministic, sequential progression through Generation, Compilation-Gate Validation, Headless Execution, and Trace Analysis. If any compile-time or strict-mode errors arise, the system seamlessly applies exactly one self-healing auto-correction cycle. If execution contains legacy selectors, they are warned via clean, structured OpenTelemetry JSON logs, and any final failure is translated directly back into human-readable BDD-level feedback.

---

## Persona Context

### Primary User: QA Automation Engineer / QA Lead
- **Who**: Writes and reviews test scenarios, maintains tenant configurations, and analyzes test automation results.
- **Goal**: Deterministic test runs that do not suffer from non-deterministic LLM real-time loops. Wants highly readable failure logs and clear technical-debt warning indicators.
- **Context**: Integrates vQA runs in continuous integration or manually triggers runs via CLI/orchestration scripts.

### Secondary User: Platform Operator
- **Who**: Monitors system health and tracks selector tagging debt across different tenant portals.
- **Goal**: Aggregate telemetry log outputs to identify standard selector fallbacks (`VQA_SELECTOR_FALLBACK`) and prioritize page element tagging tasks.

---

## Journey Maps

### Entry Points
| Entry | Context | User Intent |
|-------|---------|-------------|
| CLI Command | Running `./backend/cli.py run-step <bdd_step_text> --tenant vpromedia` | Trigger linear pipeline for a specific BDD test card. |
| CI Pipeline Run | Triggered automatically on commit or scheduled suite runs | Execute the 50-card benchmark corpus and output structured JSON telemetry. |

---

### Journey 1 — Clean Happy-Path Pipeline Run

```
[QA Automation Engineer runs a step]
  → Invokes execution engine with tenant `vpromedia` and AC step: "Given I open the Search sidebar and search for order"
  
[Generate Node]
  → Retrieves top-5 semantically relevant selector mappings from `tenants/vpromedia/selectors.json` using BM25
  → LLM processes selector list + context helpers + AC step offline
  → Outputs `vpromedia_temp_spec.spec.ts` containing Playwright test code utilizing `page.locator('vqa=search_input')`
  
[Validate Node]
  → Run `npx tsc --noEmit` on the generated file
  → Compilation succeeds (exit code 0)
  → Read spec content, parse `vqa=` selector keys, and verify they exist in `selectors.json`
  → Schema check succeeds. Validate Node completes.
  
[Execute Node]
  → Executed in headless Playwright with injected `vqaEngine` script
  → Custom engine intercepts `vqa=search_input`, maps it to `data-vqa-id="search_input"`, and resolves element instantly
  → Runs with zero errors or collisions
  
[Analyze Node]
  → Since execution was successful, Analyze Node is bypassed (or logs success summary)
  → Outputs clean, single-line OpenTelemetry JSON log:
    {"timestamp": "...", "level": "INFO", "node": "Pipeline", "message": "Pipeline run successful", "tenant_id": "vpromedia"}
```

---

### Journey 2 — Compile Failure with Self-Healing Recovery

```
[Generate Node produces a spec containing a syntax/type error]
  → Example: LLM outputs an incorrect locator parameter: `await page.click(true)` instead of string
  
[Validate Node first compile run]
  → Runs `npx tsc --noEmit` on spec
  → Compilation fails: "Argument of type 'boolean' is not assignable to parameter of type 'string'..."
  
[Self-Healing triggered]
  → Under compilation retry limit (retryCount is 0, incremented to 1)
  → Formulates prompt containing compiler error and sends back to Generate Node
  
[Generate Node regeneration]
  → Re-generates corrected code: `await page.click('vqa=submit_btn')`
  
[Validate Node second compile run]
  → Runs `npx tsc --noEmit` on regenerated spec
  → Compilation succeeds (exit code 0)
  → Pipeline proceeds to Execute Node
```

---

### Journey 3 — Execution Strict-Mode Collision Recovery

```
[Playwright runs spec in Execute Node]
  → Generated spec calls: `await page.locator('vqa=edit_btn').click()`
  
[Execution Collision occurs]
  → Custom vqaEngine identifies multiple elements matching `data-vqa-id="edit_btn"` on screen
  → Playwright throws a strict-mode exception: "strict mode violation: locator('vqa=edit_btn') resolved to 3 elements"
  
[Auto-Regeneration triggered]
  → Under execution collision retry limit (executeRetryCount is 0, incremented to 1)
  → Parser extracts the collision details and targets the parent element in the trace context
  → Sends correction prompt: "Strict mode violation: locator('vqa=edit_btn') matched 3 elements. Use parent filtering to scope your element."
  
[Generate Node parent scoping]
  → Re-generates spec using scoped locator:
    `await page.locator('tr').filter({ hasText: 'Order #1001' }).locator('vqa=edit_btn').click()`
    
[Re-Execution proceeds]
  → Regenerated spec is compiled and successfully executed
  → Target element clicked without further collision; run completes with SUCCESS
```

---

### Journey 4 — Hard Failure Translation

```
[Validate Node fails compilation TWICE, or Execute Node fails TWICE]
  → The self-healing loop limit is reached (2 consecutive failures)
  
[Halt execution & Failure analysis]
  → Execution is aborted immediately
  → System retrieves Playwright trace logs, stdout error traces, and active `selectors.json`
  → Passes them to the offline Secondary Analyze LLM
  
[Operator views output]
  → System prints a clear BDD-level human-readable failure translation to stdout as JSON:
    {
      "timestamp": "...",
      "level": "ERROR",
      "node": "Analyze",
      "tenant_id": "vpromedia",
      "message": "SCENARIO FAILURE: Failed to click the edit button in the search table.",
      "failure_analysis": {
        "failed_step": "When I click edit button for Order #1001",
        "root_cause": "The edit button was completely obscured by a loading spinner (.p-progress-spinner) which did not disappear within the 5000ms timeout.",
        "remediation_proposals": [
          "Increase the wait timeout before clicking `edit_btn`",
          "Add an explicit wait helper: `await SearchHelper.waitForLoaderToDisappear(page)`"
        ]
      }
    }
```
