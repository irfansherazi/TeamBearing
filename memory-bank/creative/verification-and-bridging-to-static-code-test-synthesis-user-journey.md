# User Journey Design: verification-and-bridging-to-static-code Verification & Bridging to Static Code

**Created**: 2026-06-02
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: verification-and-bridging-to-static-code / FEAT-072

## Journey Overview

**Feature**: FEAT-072: Verification & Bridging to Static Code
**Primary Persona**: QA Automation Engineer, QA Lead, Platform Operator
**Journey Type**: Hybrid (Developer workflow integration with real-time UI logging)
**Orchestration Pattern**: Dashboard Run Details + Automated Git PR Pipelines + Fast-Fail Execution

### Success Statement
> A QA Automation Engineer views a successfully completed autonomous JIRA run on the vQA dashboard, clicks a button to "Synthesize Playwright Test", and within seconds, sees a fully typed, repository-compliant Playwright integration test (`.spec.ts`) generated, registered, and submitted as a GitHub Pull Request. Simultaneously, the system runs with 90% faster failure recovery because any post-action expectation mismatch triggers immediate self-healing within 1.5 seconds instead of waiting for standard 30-second Playwright timeouts.

---

## Persona Context

### Primary User: QA Automation Engineer
- **Who**: Writes and maintains the automated regression test suite.
- **Goal**: Convert successful AI exploratory runs into permanent, static Playwright regression tests to lock in quality.
- **Context**: Working on the vQA dashboard to triage runs and expand test coverage.
- **Proficiency**: Highly technical, understands Playwright, TypeScript, and Git. Requires clean, type-safe, and well-structured code.

### Secondary User: QA Lead / Platform Operator
- **Who**: Oversees product quality, test pipelines, and autonomous execution.
- **Goal**: Maximize execution speed of autonomous runs and minimize compute waste.
- **Different needs**: Wants to see clear logs explaining why an action failed and why self-healing was triggered. Requires high-throughput execution where failures are caught instantly.

---

## Journey Maps

### Entry Points
| Entry | Context | User Intent |
|-------|---------|-------------|
| "Synthesize Playwright Test" Button | On a completed successful Run Detail view | Compile the successful run action sequence into a static `.spec.ts` test. |
| "Live Run" Panel / CopilotSidebar | Active executing run | Monitor steps, see the planner's state expectations, and watch predictive fast-fail in action. |

---

### Journey 1 — AI-to-Code Test Synthesis & Git Pipeline

```
[Operator views Successful Run Detail]
  → Click "Synthesize Playwright Test" in the Actions Panel

[Backend Compiler triggers (`test_synthesis_compiler.py`)]
  1. Load action history logs (JSON macro)
  2. Invoke Bedrock LLM to compile actions to Playwright TypeScript
  3. Validate syntax of synthesized `.spec.ts` code
  4. Write test file to `playwright/tests/synthesis_run_[id].spec.ts`
  5. Register file path in `playwright/playwright_registry.json`

[Git Orchestration kicks in]
  1. Create local branch: `synthesis/run-[id]-[timestamp]`
  2. Commit synthesized test + updated registry
  3. Invoke `gh pr create` with automated title & description linking to the JIRA ticket and Run ID

[Frontend UI Updates]
  - UI displays a sliding drawer: <TestSynthesisDrawer />
  - Shows animated steps:
    1. Compiling action logs... [SUCCESS]
    2. Generating standard Playwright code... [SUCCESS]
    3. Writing & registering test... [SUCCESS]
    4. Submitting Pull Request... [SUCCESS]
  - Displays code preview of the generated `.spec.ts`
  - Displays green alert: "PR Submitted! Synthesis Branch Created."
  - Direct Link Button: "View Pull Request on GitHub (PR #412)"
```

---

### Journey 2 — Predictive Planning (See-Think-Act with Expectations)

```
[Agent begins step execution]
  → Planner (`planner.py`) receives live accessibility tree & screenshot

[Planner thinks and generates step]
  - Planner schema is updated to PlannerAction (enforcing `state_expectation`)
  - Planner outputs:
    {
      "action": "click",
      "target": "input[placeholder='Search projects']",
      "state_expectation": "The search input receives focus and the search suggestions list is visible."
    }

[Frontend Dashboard Updates]
  - CopilotSidebar renders the active step
  - Step card displays an "Expectation" section:
    "🔍 Expected Result: Search suggestions list is visible."
```

---

### Journey 3 — Fast-Fail & Predictive Verifier Short-Circuit

```
[Executor executes Click action]
  - Target clicked in Playwright browser
  - Executor waits for the page DOM to settle (e.g. 500ms debounce/network idle)

[Predictive Verifier executes check]
  - `verifier.py` checks state expectation: "Search suggestions list is visible."
  - Simple DOM check: Element matches `.search-suggestions` or text is missing.
  - EXPECTATION MISMATCH DETECTED: The list is NOT visible (e.g. search suggestions API returned error).

[Orchestrator fast-fails]
  - Instead of waiting for standard 30s Playwright timeout to find list elements,
    the verifier raises a custom `PredictiveVerificationError` within 1.5 seconds.
  - VQA Loop catches error and triggers recovery route (Self-Healing / HITL).

[Frontend UI logs & Toast Alerts]
  - Live execution sidebar shows a yellow alert:
    "⚠️ Expectation Mismatch: Expected 'Search suggestions list is visible' but DOM check failed."
  - Logging feed:
    "Predictive verification mismatch: expected suggestions list but got empty state. Short-circuiting to self-healing."
  - UI updates state instantly from EXECUTING to SELF_HEALING without a 30s delay.
```

---

## State Transitions Summary

```
+------------------+                   +--------------------+
|                  |   Planner Step    |                    |
|    PLANNING      |------------------>|     EXECUTING      |
|                  |                   |                    |
+------------------+                   +--------------------+
         ▲                                       |
         |                                       | Playwright Action
         |                                       ▼
         |                             +--------------------+
         |   Self-Healing Trigger      |                    |
         |<----------------------------|     VERIFYING      | (Predictive Check)
         |                             |                    |
         |                             +--------------------+
         |                                       |
         |                                       | Expectation Fails
         |                                       ▼
         |                             +--------------------+
         |                             |   FAST-FAILING     | (Short-circuit standard 30s
         +-----------------------------|   (1.5 seconds)    |  timeouts, jump to heal)
                                       +--------------------+
```

---

## Options Explored

### Option 1: Manual PR creation and Standard 30s Timeouts
- **Orchestration**:
  - Test synthesis outputs a raw text block in the UI; the operator must copy/paste it into an IDE, manually write to the repo, check out a branch, and open a PR.
  - Page execution relies on Playwright's default page timeouts. If an expectation isn't met, Playwright spins for 30s before throwing an error.
- **Pros**:
  - Zero backend Git integration needed.
  - No prompt updates for Planner schema.
- **Cons**:
  - Substantial friction. QA engineers must perform 6-7 manual operations.
  - Execution runs are slow when things break. Standard 30s timeout is a massive productivity bottleneck during autonomous exploration.

### Option 2: Automated Branch & PR with Predictive Fast-Fail (Chosen)
- **Orchestration**:
  - Core compiler writes directly to `playwright/tests/` and handles Git/GH CLI commands.
  - The UI provides a specialized sidebar showing PR progress and code previews.
  - Planner schemas enforce `state_expectation`. The verifier matches this expectation instantly post-action, triggering recovery in <2 seconds.
- **Pros**:
  - Frictionless test suite growth. One-click synthesis turns successful exploratory sessions into regression tests.
  - Massive speedup (95% reduction in timeout waste). Immediate feedback loop for self-healing.
- **Cons**:
  - Requires git workspace access and mocking of GH CLI for local tests.
  - Slightly more complex verification schemas in the AI loop.
- **Decision**: Chosen because it directly supports seamless pipeline automation, reducing manual work, and eliminates costly and slow failure loops.

---

## Evaluation Matrix

| Criterion | Option 1 | Option 2 |
|-----------|----------|----------|
| Developer Velocity | Low | High (seamless PR generation) |
| System Throughput | Low (30s wasted on errors) | High (instant recovery) |
| Ease of Integration | High | Medium (requires Git subprocess setup) |
| Error Visibility | Low | High (expectations printed in UI) |
| Automation Robustness | Medium | High (compiler checks syntax before writing) |

---

## Decision

**Chosen**: Option 2 - Automated Branch & PR with Predictive Fast-Fail

### Rationale
Automating the loop from exploratory AI actions to static Playwright PRs aligns perfectly with vQA's vision of an autonomous testing platform. Incorporating predictive state verification makes the agent's actions highly target-focused and fast, eliminating the slow timeouts that degrade autonomous performance.

---

## NFR / Constraints Met by This Journey

| NFR | How Addressed |
|-----|--------------|
| **PR-SPEED-1: Fast Synthesis** | Compiler generates, writes, and registers code in <5 seconds. |
| **PR-INTEGRITY-2: Auto-Registration** | Automatically updates `playwright/playwright_registry.json` to keep the testing dashboard in sync. |
| **EXEC-FAIL-1: Fast Fail** | Under 2.0s transition from click to self-healing on failure (bypassing 30s timeout). |
| **UI-CLARITY-3: Clear Expectations** | Expected result is visible in the CopilotSidebar step cards. |
