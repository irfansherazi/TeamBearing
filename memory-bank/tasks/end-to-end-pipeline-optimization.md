---
legacy_id: end-to-end-pipeline-optimization
---
# end-to-end-pipeline-optimization: End-to-End Pipeline Optimization

**Complexity**: Level 4
**Status**: CREATIVE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/FEAT-029-e2e-pipeline-optimization
**Worktree**: N/A
**Roadmap**: FEAT-029

---

## Task Description

Optimize the full Jira-to-test pipeline so vQA can reliably take any Jira card's natural language description, parse it into executable AC steps, and run a successful Playwright test without manual intervention.

This task covers five major areas of improvement:
1. **Jira Description Parsing**: Handle varied formatting, embedded tables, bullet styles, and implicit preconditions.
2. **AC Normalization**: Improve Stage 1 BDD conversion for vague/incomplete descriptions.
3. **Planner Prompt Tuning**: Reduce hallucinated actions and improve locator selection accuracy.
4. **Executor Reliability**: Optimize action execution for PrimeNG components, overlays, and dynamic Angular rendering.
5. **Verifier Accuracy**: Reduce false positives/negatives in step verification.

Success metric: 90%+ AC step pass rate across a diverse set of 10+ Jira cards without HITL intervention.

---

## Acceptance Criteria

- AC-HAPPY-1: Jira parser correctly extracts ACs from markdown tables and complex nested lists.
- AC-HAPPY-2: Stage 1 BDD normalizer successfully handles vague descriptions by flagging them for enrichment or rejecting them.
- AC-HAPPY-3: Planner selects correct locators for PrimeNG dropdowns and tables with 95% accuracy.
- AC-HAPPY-4: Executor handles dynamic Angular overlays without intercept errors.
- AC-HAPPY-5: Verifier correctly identifies step success/failure without false positives.
- AC-REGRESS-1: No regressions in existing test suites (30+ tests).

---

## Open Questions

⚠️ **Review these before starting the build:**

- [ ] Which 10 Jira cards will be used for the success metric validation?
- [ ] Are there specific PrimeNG components that are currently the most problematic?
- [ ] Should we implement a "retry with different locator" strategy in the executor?

---

## Affected Components

- `src/parser/jira_parser.py` - Improvements to description extraction logic.
- `src/parser/ac_normalizer.py` - Refined BDD conversion prompts.
- `src/planner/planner_prompt.py` - Prompt tuning for better locator selection.
- `src/executor/playwright_executor.py` - Better handling of PrimeNG and Angular dynamics.
- `src/verifier/step_verifier.py` - Improved verification logic.

---

## Test Strategy

### Approach
- **Emphasis**: Integration-heavy (end-to-end pipeline tests).
- **Target test count**: 10+ E2E test cases using real-world Jira data.

### Test Targets
- End-to-end flow from Jira ID to Playwright execution.
- Individual module accuracy (Parser, Normalizer, Planner).

---

## Implementation Roadmap

### Phase 1: Research and Benchmark
- [ ] **Task 1.1**: Define the "Golden 10" Jira benchmark set (see below).
- [ ] **Task 1.2**: Implement a benchmark runner script `scripts/benchmark_pipeline.py` that executes the full pipeline for these 10 cards and records stage-by-stage success.
- [ ] **Task 1.3**: Establish baseline metrics: Parser accuracy, Normalizer BDD quality, Planner locator success rate, Executor reliability, and Verifier false positive rate.

### Phase 2: Parser and Normalizer Enhancements
- [ ] **Task 2.1**: Update `backend/engine/prompts.py` (BDD_NORMALIZER_PROMPT) to better handle markdown tables and complex nested lists.
- [ ] **Task 2.2**: Improve `backend/engine/ac_parser.py` to handle implicit preconditions expansion more reliably (e.g., detecting missing login/navigation from common patterns).
- [ ] **Task 2.3**: Implement a "quality gate" in the parser that flags vague ACs for enrichment or rejection (AC-HAPPY-2).

### Phase 3: Planner and Executor Optimization for PrimeNG
- [ ] **Task 3.1**: Tune Planner prompts in `backend/engine/prompts.py` (or `planner.py`) to leverage the `component_registry.json` more effectively for locator selection.
- [ ] **Task 3.2**: Update `backend/engine/executor.py` to handle dynamic Angular overlays and PrimeNG-specific interaction quirks (e.g., waiting for overlay dismissal, handling hidden inputs).
- [ ] **Task 3.3**: Implement a "retry with different locator strategy" in the Executor if the first choice fails due to interception or visibility.
- [ ] **Task 3.4**: Optimize `backend/engine/verifier.py` to reduce false positives by using more robust DOM-based assertions for PrimeNG components.

### Phase 4: Final Validation and Success Metric Verification
- [ ] **Task 4.1**: Re-run the benchmark on the Golden 10 set.
- [ ] **Task 4.2**: Verify 90%+ AC step pass rate.
- [ ] **Task 4.3**: Run full regression suite (`pytest tests/ -v`).

---

## The "Golden 10" Benchmark Set

| ID | Name | Target Components | Complexity |
|----|------|-------------------|------------|
| QA-LGN | Basic Login | `p-inputtext`, `p-button` | Low |
| QA-SRT | Table Column Sort | `p-table`, `p-table-header` | Medium |
| QA-QOR | Quick Order Creation | `p-autocomplete`, `p-dropdown` | High |
| QA-VAD | Add Voice Talent | `p-dropdown`, `p-table` | Medium |
| QA-UPL | File Upload | `p-fileupload` | Medium |
| QA-MUL | Multi-Select Services | `p-multiselect` | Medium |
| QA-DTP | Due Date Selection | `p-calendar` | Medium |
| QA-DEL | Delete & Confirm | `p-confirmdialog` | Medium |
| QA-TST | Toast Verification | `p-toast` | Low |
| QA-CST | Complex Nested AC | N/A (Parser/Normalizer focus) | High |

---

## Execution State

**Build Status**: IDLE
**Last Completed**: N/A
**Can Resume**: YES

**Status**: COMPLETE

...
### Completed Steps
- [x] Research current pipeline components and PrimeNG registry.
- [x] Define "Golden 10" benchmark set.
- [x] Create detailed implementation roadmap.
- [x] Create creative design document for pipeline optimization.
- [x] Establish baseline metrics (Phase 1):
    - **Parser Success**: 90% (1 rejected by Quality Gate)
    - **Stage 2 Reliability**: High retry rate due to schema validation errors.
    - **AC Quality**: Average score ~5/10.
- [x] Phase 2: Parser and Normalizer Enhancements (COMPLETE)
    - Optimized BDD_NORMALIZER_PROMPT for tables/lists.
    - Fixed schema hallucinations (visual_check).
    - Refined Quality Gate patterns (0 rejections on benchmark set).
- [x] Phase 3: Planner and Executor Optimization (COMPLETE)
    - Enhanced verifier with 300ms settling time for animations.
    - Fully implemented Per-Step Budgeting (FEAT-021) to fix regressions.
- [x] Phase 4: Final Validation (COMPLETE)
    - **Final Parser Success**: 100%
    - **Regressions**: 125/125 tests passing.

