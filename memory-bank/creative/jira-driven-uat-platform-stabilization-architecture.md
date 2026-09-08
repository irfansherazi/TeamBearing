# Architecture: jira-driven-uat-platform-stabilization Jira-Driven UAT Platform Stabilization

**Task**: jira-driven-uat-platform-stabilization / FEAT-106  
**Date**: 2026-06-05  
**Author**: Creative Design Agent

---

## 1. Modular Stabilization Architecture

The stabilization initiative brings structural rigor and modularity to the linear pipeline execution engine developed in `linear-pipeline-execution-engine-rewrite-spec`. It eliminates brittle selector assumptions, introduces high-accuracy UI stagnation checks, and bridges critical data paths.

```
                                  ┌────────────────────────┐
                                  │   vQA Linear Runner    │
                                  └───────────┬────────────┘
                                              │
                    ┌─────────────────────────┼────────────────────────┐
                    ▼                         ▼                        ▼
       ┌────────────────────────┐  ┌────────────────────┐  ┌───────────────────────┐
       │     ui_delta.py        │  │   a11y_discovery   │  │   self_healing        │
       │  (4-Signal Stagnation) │  │  (Dynamic Locators)│  │    (Timing/Cat 6)     │
       └────────────────────────┘  └────────────────────┘  └───────────────────────┘
```

---

## 2. Component Blueprint Specifications

### A. Authentication State Regeneration & Path Mapping
* **Auth Storage Location**: `playwright/storage/vpromedia_auth.json`
* **Cookie Integrity Guard**: The orchestrator checks cookie expiration before loading. If expired, it triggers an automated login flow using administrative credentials stored in `backend/secrets.py` (and `.env` overrides).
* **Strict Selector Overwrite**: The `login-password-input` is mapped as a tenant selector inside `tenants/vpromedia/selectors.json` to resolve strict-mode collisions.
  ```json
  {
    "vpromedia": {
      "login-username-input": "input#username",
      "login-password-input": "input[type='password'][name='password']"
    }
  }
  ```

### B. AC Parser Route & Linear Pipeline Integration
* **Data Flow**: When a linear pipeline run is initiated via the API (`POST /runs`):
  1. The API route loads the Jira ticket content.
  2. If the Jira ticket does not already contain structured steps in `card["expected_steps"]`, the engine calls `ac_parser.py` (via `_stage_1_normalize` + `_stage_2_compile`).
  3. The compiled steps are persisted to the in-memory run state registry before starting `_execute_linear_run()`.
* **AC Parser Signature Hook**:
  ```python
  from backend.engine.ac_parser import ACParser

  def integrate_ac_parser(card: dict) -> list:
      if not card.get("expected_steps"):
          parser = ACParser()
          raw_ac = card.get("acceptance_criteria", "")
          steps = parser.compile(parser.normalize(raw_ac))
          card["expected_steps"] = steps
      return card["expected_steps"]
  ```

### C. Run State Registry & Jira Posting Integration
* **Failure Analysis Payload Schema**:
  ```json
  {
    "failure_analysis": {
      "failed_step": "When I enter an invalid coupon code",
      "stack_trace": "Error: Timeout after 5000ms waiting for selector...",
      "classification": "TIMING",
      "reproduction_script": "npx playwright test tests/reproduce_run_123.spec.ts",
      "suggested_fix": "Add explicit waitForSelector or increase transition delay to 10s"
    }
  }
  ```
* **Post-to-Jira Endpoint**: `POST /runs/{run_id}/post-to-jira`
  * Reads the completed execution record from `_run_states` or the state DB.
  * Extends the classic JIRA comment posting with the beautifully structured `failure_analysis` payload to ensure clear developer action items are attached directly to the bug ticket.

### D. Multi-Signal Stagnant UI Detection (`ui_delta.py`)
* To avoid high false-positive rates of simple DOM counting, `ui_delta.py` computes an accurate, weighted coefficient across **4 primary signals**:
  1. **URL Location**: Has the active address or hash routing changed?
  2. **Active Element Count**: Have elements been added or removed from the viewport tree?
  3. **ARIA Accessibility Snapshot**: Has the semantic screen reader tree changed structure?
  4. **Overlay Markers**: Are blocking overlays, loading spinners, or modal dialogs present?
* **Integration**: The `verifier.py` invokes `compute_ui_delta` before and after each instruction block to verify target page progression.

### E. Dynamic A11y Discovery & Code Generation (`a11y_discovery.py`)
* Rather than maintaining thousands of brittle CSS selectors in `selectors.json`, the generator node uses **accessibility-first locator injection**:
  1. The `Execute` node captures the accessibility tree snapshot of the viewport:
     ```python
     snapshot = await page.accessibility.snapshot()
     ```
  2. The snapshot is pruned of noise (whitespace, non-interactive static container nodes).
  3. Interactive components are identified (e.g., `role="button"`, `name="Submit"`) and mapped to `page.getByRole(...)` Playwright commands.
  4. The pruned tree is injected into the LLM context, ensuring the LLM generates 100% correct semantic locators on dynamic SPAs (such as PrimeNG or Angular).

### F. A11y-Powered Self-Healing Engine
* **Category 2 (Timing)**:
  * Catch block intercepts Playwright timeouts.
  * Evaluates state of current loading indicators and network idle conditions.
  * Retries with incremental delay (up to 3 times).
* **Category 6 (Interaction Change / Element Shift)**:
  * Catch block intercepts "element not clickable" or "target obscured" errors.
  * Re-triggers an immediate A11y Tree snapshot of the current viewport.
  * Compares original intended element roles against current screen options to find alternative matching targets (fuzzy role matching).
  * Automatically rewrites the step execution target inline and retries.

---

## 3. Reliability Metrics & Performance Gates

### Telemetry Propagation & Distributed Trace Logs
We adhere strictly to the trace logs standard established in linear-pipeline-execution-engine-rewrite-spec:
* Every telemetry log must print in single-line JSON format on standard output (`stdout`).
* Trace IDs are propagated through standard headers (`VQA_TRACE_ID`, `VQA_SPAN_ID`) across process boundaries.

```json
{
  "timestamp": "2026-06-05T10:35:00.123Z",
  "level": "INFO",
  "node": "Execute",
  "message": "Dynamic A11y Discovery captured 72 interactive elements in 420ms",
  "tenant_id": "vpromedia",
  "trace_id": "8fa32c3577b34da6a3ce929d0e0e4745",
  "span_id": "11f067aa0ba902b8"
}
```
