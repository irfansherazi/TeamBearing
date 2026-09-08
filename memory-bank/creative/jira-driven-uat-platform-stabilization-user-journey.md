# User Journey: jira-driven-uat-platform-stabilization Jira-Driven UAT Platform Stabilization

**Task**: jira-driven-uat-platform-stabilization / FEAT-106  
**Date**: 2026-06-05  
**Author**: Creative Design Agent

---

## 1. Overview of the Converged User Journey

The stabilization of the Jira-Driven UAT Platform converges the automated, headless linear execution pipeline with a seamless user-facing triage and acceptance testing experience. Instead of treating vQA as an opaque "black-box" LLM-loop, this converged platform provides a highly visual, predictable, and deterministic environment where QA Engineers can execute, triage, and post results directly to Jira.

```
                  ┌──────────────────────────────┐
                  │   1. Intake & Ingestion     │
                  │   - Load JIRA Ticket         │
                  │   - Normalize & Parse AC     │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │ 2. Pre-Flight & A11y Audit   │
                  │   - Boot Session (Auth Fix)  │
                  │   - Capture A11y Snapshot    │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │ 3. Execute & Auto-Healing    │
                  │   - Generate/Run Playwright  │
                  │   - Multi-Signal Stagnation  │
                  │   - Cat 2/6 Self-Healing     │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │    4. Triage & Jira Post     │
                  │   - Inspect Run Failure      │
                  │   - Edit/Fix in Browser      │
                  │   - Post Triage to JIRA      │
                  └──────────────────────────────┘
```

---

## 2. Step-by-Step Persona Experience (The QA Engineer)

### Step 1: Intake & Ingestion
* **Action**: The QA Engineer logs into the vQA Dashboard, enters a JIRA Ticket Key (e.g., `QA-170`), and clicks "Ingest".
* **System Response**:
  1. The platform pulls the ticket description and comments from JIRA.
  2. The **AC Parser** runs, automatically normalizing and compiling raw AC text into a structured list of validation steps.
  3. The platform displays the parsed steps and AC Quality check score from the **FAIR Quality Gate** (visible in logs/UI).
* **Value**: Complete transparency on what the system intends to test before a single browser instruction runs.

### Step 2: Pre-Flight & A11y Audit
* **Action**: The user triggers the Run.
* **System Response**:
  1. The orchestrator boots a headless Playwright instance using a **secure, regenerated authentication state** (preventing expired session redirects).
  2. Before executing any generated spec, the engine captures a full **Accessibility (A11y) Tree Snapshot** of the application landing page.
  3. The A11y Tree is parsed into high-fidelity, role-based contextual metadata (e.g., `button "Log In"`, `textbox "Password"`).
* **Value**: Resolves the classic "strict-mode element collision" bug (e.g., `input[type='password']` matching multiple hidden or background elements) by targeting elements exclusively through their visible, semantic roles.

### Step 3: Execution & Self-Healing
* **Action**: The user monitors the execution log in real-time via the VQA Sidebar.
* **System Response**:
  1. **Generative Phase**: The LLM compiles the parsed BDD steps into a Playwright executable spec, enriched by the dynamic A11y Tree roles (using `page.getByRole(...)` rather than fragile CSS classes).
  2. **Stagnation Check**: During each step interaction, the **Multi-Signal Stagnant UI Detection** monitors the DOM. If a click does not alter the URL, element count, ARIA snapshot, or overlay markers, it is instantly flagged as stagnant.
  3. **Self-Healing Active**: If a step fails, the self-healing bridge classifies the failure:
     * **Category 2 (Timing/Timeout)**: The runner detects a loader spinner or delayed API response, applies an intelligent waiting state, and retries.
     * **Category 6 (Interaction Change)**: The runner detects a selector target movement, leverages the A11y Tree snapshot to resolve the new locator, and successfully retries.
  4. Telemetry traces (traceId, spanId) are printed in single-line JSON format directly to the execution logger.
* **Value**: Continuous execution. Up to 3 automatic retries keep the pipeline running instead of crashing on minor UI timing hiccups.

### Step 4: Triage & Jira Posting
* **Action**: If a run fails after exhausted self-healing, the user navigates to the **Triage Panel** to review.
* **System Response**:
  1. The Triage Panel displays a detailed post-run **Failure Analysis** (linking the failed lines of code directly to specific BDD AC steps).
  2. The user can interact with the live VNC frame, correct a state manually (or apply a localized override), and click **Post to Jira**.
  3. Clicking "Post to Jira" invokes `POST /run/{run_id}/post-to-jira`. This writes a beautifully formatted BDD report back to the JIRA ticket comments, complete with the Failure Analysis, execution status, and a direct URL to the triage snapshot.
* **Value**: Closes the loop. Results are automatically synced back to JIRA, keeping product owners, managers, and developer teams fully informed without manual copy-pasting.

---

## 3. High-Fidelity Convergence: /vc-uat and Linear Pipeline

The convergence of `/vc-uat` (browser acceptance testing framework) and the Linear Pipeline is characterized by standardizing the execution pipeline around a unified model.

### Convergence Points:
1. **Runner Unified Configuration**: Both systems now pull browser configuration, tenant preferences, and timeout limits from the unified `tenants/vpromedia/vqa.config.json`.
2. **Deterministic Fallbacks**: Both `/vc-uat` and the Linear Pipeline utilize the same `ui_delta.py` utility to verify action effectiveness, removing divergent delta logic.
3. **Trace Alignment**: Any run triggered via `/vc-uat` or the Web UI carries identical tracing metadata headers, allowing developers to query logs in Datadog or local files using a single `trace_id`.
