# Architecture Decision: verification-and-bridging-to-static-code Verification & Bridging to Static Code

**Created**: 2026-06-02
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: verification-and-bridging-to-static-code / FEAT-072

---

## Context

### System Requirements

verification-and-bridging-to-static-code addresses two primary architectural requirements that close the loop between autonomous visual testing and stable code-based regression testing:

1. **AI-to-Code Test Synthesis**: Automate the compilation of successful autonomous run JSON macros into standard, typed, and registered Playwright integration tests (`.spec.ts`). Ensure complete workflow isolation by creating branches and submitting GitHub Pull Requests automatically.
2. **Predictive State Verification**: Improve autonomous execution loop performance and reliability. By planning actions accompanied by immediate `state_expectation` assertions, the execution engine can detect post-action mismatches in <2 seconds and bypass standard Playwright 30s element timeouts, speeding up self-healing and takeover operations.

### Technical Constraints

- **Type Safety & Style Compliance**: Synthesized tests must use clean TypeScript, import correct Playwright structures, and conform to the project's Playwright linting and formatting rules.
- **Git Safety**: Git branch, commit, and PR creation must be managed safely, handling workspace state elegantly and mocking third-party CLI calls (`gh`) cleanly in verification tests.
- **Low-Latency Verifiers**: Predictive DOM/URL delta matching must complete in <500ms post-action, introducing negligible overhead while preventing expensive standard timeouts.
- **No Heavy Background Models**: Fast-fail checking must run directly on the Playwright page state using simple xpath/css queries or JS evaluations in python, rather than calling the LLM for every action validation.

---

## Component Analysis

### Core Components Affected

| Component | File | Change Type | Purpose / Responsibility |
|-----------|------|-------------|--------------------------|
| `TestSynthesisCompiler` | `backend/kb/test_synthesis_compiler.py` | **NEW** | Translates serialized JSON macros into Playwright `.spec.ts` files, updates `playwright/playwright_registry.json`, and orchestrates local git + GitHub CLI commands. |
| `PlannerAction` Schema | `backend/engine/schemas.py` | **MODIFY** | Updated to include `state_expectation` as an optional or required string field. |
| Planner Prompts | `backend/engine/prompts.py` | **MODIFY** | Prompts modified to provide clear system instructions and few-shot examples for outputting precise `state_expectation` assertions. |
| `VQAExecutor` | `backend/engine/executor.py` | **MODIFY** | Runs actions and invokes predictive verifications post-execution. If verification fails, immediately raises `PredictiveVerificationError`. |
| `PredictiveVerifier` | `backend/engine/verifier.py` | **NEW** | Performs rapid DOM delta and text-presence checks based on raw `state_expectation` string descriptions without slow polling. |

### Component Interaction Diagram

```
[Completed Run Event]
       │
       ▼
[TestSynthesisCompiler] ──(1) Reads Run Actions JSON Macro ──▶ [Action Log]
       │
       ├──(2) Calls Bedrock Claude 3.5 Sonnet to translate
       ▼
[Synthesized TypeScript Code]
       │
       ├──(3) Writes file to: playwright/tests/synthesis_run_[id].spec.ts
       ├──(4) Updates playwright/playwright_registry.json
       ▼
[GitHelper Subprocess] ──(5) Runs git checkout, add, commit, gh pr create ──▶ [GitHub PR]


-----------------------------------------------------------------------------------------


[Planner Node (Sonnet)] ──(1) Generates Action + State Expectation ──▶ [PlannerAction]
                                                                             │
                                                                             ▼
[VQAExecutor] ──(2) Dispatches Playwright action (click, fill, etc.) ────────┘
     │
     ▼ (Action Completes)
[PredictiveVerifier] ──(3) Evaluates page DOM against state expectation
     │
     ├──► [Expectation Met]   ──▶ Resumes normal flow
     └──► [Expectation Fails] ──▶ Raises PredictiveVerificationError ──▶ Immediate Self-Healing (<1.5s total)
```

---

## Options Explored

### Option 1: Full-VLM Visual Verification of Every Action
- **Description**: After every action, capture a screenshot and send it to the VLM (Bedrock Claude 3.5 Sonnet) alongside the `state_expectation` to determine if the expectation was met.
- **Pros**:
  - Highly robust semantic understanding. Can detect complex UI changes (e.g. "the button color turns dark blue").
- **Cons**:
  - Extremely slow (VLM calls take 1.5s - 3s).
  - Heavy token cost per run. Adds substantial cloud API overhead.
  - Defeats the purpose of a low-overhead, fast-fail check.

### Option 2: Pure Local Code-Based Compilation & Rule-Based Assertions (Chosen)
- **Description**:
  1. **Compilation**: Utilize a specialized LLM compiler prompt on completion of the run. Claude receives the exact steps, generates the typescript, and we write/register it locally.
  2. **Predictive Verification**: Planner outputs textual assertions in `state_expectation` (e.g. "Table has row 'New Project'" or "Modal is closed"). The `PredictiveVerifier` parses this string using simple heuristics (text extraction, selector detection, URL matching) and executes a rapid local evaluation in <300ms. If the assertion fails, we fast-fail.
- **Pros**:
  - Zero LLM overhead during action verification; checks are lightning fast.
  - Translates natural expectations to direct DOM audits instantly.
  - compiler runs exactly once per synthesized test, keeping token overhead minimal.
- **Cons**:
  - Text-based heuristic parsing is less expressive than visual VLM checks (mitigated by using clear prompt instructions forcing the planner to write easily verifiable expectations).

---

## Evaluation Matrix

| Criteria | Option 1 (VLM Verification) | Option 2 (Local Heuristic & LLM Compiler) |
|----------|-----------------------------|-------------------------------------------|
| Performance overhead | High (~2-3 seconds per step) | Low (<300ms per step) |
| Running cost | High (VLM call on every step) | Low (Single LLM call at synthesis end) |
| Failure recovery speed | Medium (3s validation delay) | Extremely High (<1.5s fast-fail trigger) |
| Maintenance cost | Medium | Low |
| Visual accuracy | High | Medium (focuses on DOM/Accessibility tree) |

---

## Observability Architecture

### Structured Logging
We will log all compiler actions and predictive verification operations as structured JSON messages.

```json
{
  "timestamp": "2026-06-02T10:45:21.109Z",
  "level": "INFO",
  "traceId": "run-f19b22-step-4",
  "module": "backend.engine.verifier",
  "message": "Predictive state verification",
  "data": {
    "state_expectation": "Dialogue with text 'Create Folder' is visible",
    "result": "MISMATCH",
    "elapsed_ms": 145,
    "details": "Searched DOM for text/selector containing 'Create Folder' but element was not found in accessibility tree or page text."
  }
}
```

```json
{
  "timestamp": "2026-06-02T10:48:02.554Z",
  "level": "INFO",
  "traceId": "run-f19b22-synthesis",
  "module": "backend.kb.test_synthesis_compiler",
  "message": "Test synthesized and registered successfully",
  "data": {
    "test_file": "playwright/tests/synthesis_run_f19b22.spec.ts",
    "branch_name": "synthesis/run-f19b22-1780410400",
    "pr_link": "https://github.com/vpro/vqa/pull/412"
  }
}
```

---

## Implementation Guidelines

### Phase 1: AI-to-Code Compiler & PR Orchestration
- **Compiler**: Write `backend/kb/test_synthesis_compiler.py`. Include a class `TestSynthesisCompiler` with method `compile_run(run_id: str, action_log: list[dict]) -> str`.
- **System Prompt**: Design a system prompt for Sonnet that specifies importing `@playwright/test`, setup, standard fixtures (e.g. `test("synthesis test", async ({ page }) => { ... })`), mapping standard action types (navigate ➔ `page.goto`, click ➔ `page.click`, fill ➔ `page.fill`), and adding proper type declarations.
- **Registry Update**: Append newly generated tests to `playwright/playwright_registry.json` using transactional file reading and writing.
- **Git helper**: Add a subprocess executor to handle git flows:
  ```python
  subprocess.run(["git", "checkout", "-b", f"synthesis/run-{run_id}-{timestamp}"], check=True)
  subprocess.run(["git", "add", test_path, registry_path], check=True)
  subprocess.run(["git", "commit", "-m", f"test(synthesis): generate test for run {run_id}"], check=True)
  subprocess.run(["gh", "pr", "create", "--title", f"Synthesized Test: Run {run_id}", "--body", f"Automatically generated integration test from exploratory execution run {run_id}."], check=True)
  ```
- **Mocking**: Tests must mock these subprocess calls, returning predefined strings to represent git/gh success.

### Phase 2: Planner State Expectations & Schema Updates
- **Schema**: Update `PlannerAction` Pydantic class in `backend/engine/schemas.py`:
  ```python
  class PlannerAction(BaseModel):
      action: str
      target: Optional[str] = None
      value: Optional[str] = None
      state_expectation: Optional[str] = Field(
          None,
          description="A brief description of the immediate visible result expected from this action (e.g. 'Modal Dialog is visible'). Used for fast-fail validation."
      )
  ```
- **Prompt Guides**: Edit `backend/engine/prompts.py`. Update systemic instructions to emphasize:
  - "Every action you generate MUST include a clear `state_expectation` describing the immediate DOM/URL feedback."
  - Provide 2-3 detailed examples of actions with expectations.

### Phase 3: Predictive State Verification & Fast-Fail Execution
- **Heuristic Verifier**: Create `backend/engine/verifier.py` with `PredictiveVerifier`:
  ```python
  class PredictiveVerifier:
      @staticmethod
      def verify_expectation(page, state_expectation: str) -> bool:
          # Fast checks:
          # 1. If expectation describes URL, check page.url
          # 2. Extract key noun phrases or text inside single quotes (e.g. 'Create Folder')
          # 3. Check if text is present on page via page.content() or accessibility tree
          # 4. If selector patterns are described (e.g. '#modal-id'), check element visibility.
          # Return True if check passes, False otherwise.
  ```
- **Executor Fast-Fail**: In `backend/engine/executor.py`, inside the action dispatch handler:
  ```python
  # Execute action...
  # Wait briefly for DOM to settle:
  await page.wait_for_timeout(500)
  
  if action.state_expectation:
      is_valid = PredictiveVerifier.verify_expectation(page, action.state_expectation)
      if not is_valid:
          raise PredictiveVerificationError(
              f"Predictive verification mismatch: expected '{action.state_expectation}' but post-action state check failed."
          )
  ```

---

## Validation Checklist

- [x] LLM-compiler successfully maps click/fill/navigate actions to valid TypeScript.
- [x] Synthesized `.spec.ts` files compile successfully with `tsc`.
- [x] Newly synthesized tests are registered in `playwright/playwright_registry.json`.
- [x] Git integration (checkout, commit, gh pr create) works smoothly and is mocked in pytest.
- [x] `PlannerAction` schema updated to require/support `state_expectation`.
- [x] Planner prompts guide the system to output state expectations.
- [x] PredictiveVerifier performs DOM checks in <500ms.
- [x] Mismatches in predictive expectations raise `PredictiveVerificationError` immediately, bypassing Playwright's 30s timeout and triggering recovery routes under 2 seconds.
- [x] Custom pytest suite `pytest tests/test_task_095_test_synthesis_and_prediction.py -v` passes cleanly.
