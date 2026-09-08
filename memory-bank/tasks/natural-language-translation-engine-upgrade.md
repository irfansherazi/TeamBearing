---
legacy_id: natural-language-translation-engine-upgrade
---
# natural-language-translation-engine-upgrade: Natural Language Translation Engine Upgrade

**Status**: COMPLETE
**Roadmap Link**: FEAT-034
**Complexity**: Level 4
**Branch**: feature/FEAT-034-natural-language-translation

## Specification

**Feature Type**: NFR/Infrastructure (Engine Upgrade)
**Creative Exploration Needed**: Yes:
- "How best to prune context (e.g. ARIA tree vs prompt history) to avoid lost-in-the-middle without losing critical task parameters?"
- "What specific structural changes are needed in `ac_parser.py` and `planner.py` to handle native ADF/Jira complex specs seamlessly?"
- "What is the optimal context management strategy (summarization vs. structured history) to minimize prompt tokens while retaining reliability for deep test sessions?"
- "How can we design a 'Failure Diary' or structured historical context that prevents the agent from retrying the same failed strategy?"
- "What's the best way to leverage the existing `ActionHistoryBuffer` (FEAT-020) to support this new context management strategy?"

### Verification Method
- **Test method**: Execute full E2E benchmark pipeline (`scripts/benchmark_pipeline.py --full`) against a diverse set of complex Jira cards (with nested lists, complex ADF structures).
- **Success metrics**: E2E parsing and execution success rate ≥ 90% on benchmark suite; prompt token count reduced by 20-30% in deep sessions; zero "amnesia" failures where the agent forgets the role or target environment.
- **Observable at**: Terminal output of `benchmark_pipeline.py` and HTML audit reports generated during runs.
- **Verification frequency**: Continuous during development, full run on-deploy.

### Acceptance Criteria

#### AC-VERIFY-1: Parser handles complex Jira ADF natively
**Priority**: MUST
**Given** a Jira ticket containing complex ADF (nested lists, bolding, code blocks, tables)
**When** `ac_parser_node` processes the ticket
**Then** the output `TestPlan` correctly reflects the multi-step test requirements without dropping context or hallunicating missing steps.

#### AC-VERIFY-2: Planner avoids lost-in-the-middle context drops
**Priority**: MUST
**Given** a test run exceeding 10 steps (deep session)
**When** the planner evaluates the next action
**Then** it retains critical constraints (e.g. current role, target URL, and task boundaries) and does not forget previous failed attempts.

#### AC-VERIFY-3: Decision loop executes faster and more deterministically
**Priority**: MUST
**Given** a standard test plan
**When** the See-Think-Act loop runs
**Then** the decision-making loop produces deterministic outcomes without falling into infinite retries due to misinterpreted context, resulting in faster average step times.

### Scope Boundaries
- **In scope**: Upgrading `ac_parser.py` to handle ADF cleanly; optimizing `planner.py` prompt assembly (context pruning/summarization); streamlining the evaluator/planner retry loop.
- **Out of scope**: Changing the underlying LLM provider from Bedrock/Claude; rewriting the Playwright executor logic entirely.
- **Dependencies**: Jira REST API response format (ADF structure), Bedrock context window limits.

### Implementation Guide Required
No — primarily verified via automated benchmark scripts.

---

## Architectural Plan

### Executive Summary
The Natural Language Translation Engine Upgrade (FEAT-034) will harden the vQA engine to robustly ingest complex, real-world Jira tickets (often formatted in Atlassian Document Format, ADF) and translate them into executable plans. Furthermore, it addresses the "lost-in-the-middle" syndrome by actively managing the planner's context window (pruning obsolete history, summarizing deep sessions) to ensure high reliability in long-running tests.

### Business Context
vQA's value proposition relies on its ability to test vSuite directly from Jira tickets without manual QA scripting. Currently, complex or vaguely formatted Jira cards can confuse the parser, and long test sessions can cause the planner LLM to forget initial constraints. This upgrade directly improves the autonomous completion rate and reduces false negatives, increasing trust in the tool across engineering and PM teams.

### Vision and Goals
- **Vision**: vQA can take any human-written Jira AC and reliably execute it without hand-holding or prompt engineering the ticket itself.
- **Goals**:
  1. 90%+ E2E success rate on complex Jira tickets.
  2. Eliminate "amnesia" failures in long tests.
  3. Faster overall test execution via a streamlined decision loop.

### Requirements
#### Functional
- Parser must correctly extract test steps from complex Jira ADF JSON.
- Planner must maintain a rolling summary or pruned history of the execution state.
- System must deterministically route actions and evaluate results.

#### Non-Functional
- **Performance**: Planner prompt size should remain within optimal limits to reduce latency and token cost.
- **Reliability**: No `GraphRecursionError` timeouts due to lost context.

### Architectural Principles
1. **Multimodal Grounding**: Ensure pruned context still contains necessary visual/structural data.
2. **Context Optimization**: Keep the LLM's attention focused on the immediate task and essential constraints (role, goal) without overwhelming it with past, irrelevant successes.

### Architecture Alternatives
- **Option A (Rolling Summarization)**: Use a separate fast LLM call (Haiku) to summarize past actions into a dense context block. *Pros*: Keeps context small. *Cons*: Added latency and cost.
- **Option B (Strict Windowing + Core State Retention)**: Retain only the last N actions but permanently pin the current goal, role, and overarching AC to the top of the prompt. *Pros*: Zero added latency, highly deterministic. *Cons*: Might lose nuanced past failures if N is too small.
- **Option C (Hybrid)**: Option B + specific tracking of failed locators (Failure Diary).

### Selected Architecture
**Option C (Hybrid)**: This builds upon the Action History Buffer (FEAT-020). We will implement strict windowing for past successes but retain a structured "Failure Diary" for past failures to prevent retry loops. The Jira parser will be enhanced with specific AST-like traversal for ADF to extract text without noise.

### Architecture Documentation
- **ac_parser.py**: Add ADF normalization functions.
- **planner.py**: Refactor prompt assembly to inject prioritized, pruned context blocks (`<core_constraints>`, `<recent_history>`, `<failure_diary>`).

### Observability Requirements
- **Logging Architecture**:
  - Library: Existing Python `logging`.
  - Configuration: Log prompt token counts (estimated) and context pruning actions (e.g., "Pruned 5 past actions from prompt").
- **Tracing Architecture**:
  - W3C Trace Context maintained across LangGraph nodes.
- **Metrics Architecture**:
  - Standard metrics: AC parsing success rate, E2E run completion time, token usage.
- **Infrastructure**: Existing S3 artifacts and HTML reporter. The HTML reporter should expose if context was summarized.

### API Requirements
- **REST API**: N/A (Internal engine changes only).
- **API Testing**: Update `scripts/benchmark_pipeline.py` with complex ADF Jira payloads to assert parsing accuracy.

### Creative Phases Required
- [x] Architecture Design (Completed in this plan)
- [x] Logic Design (Specifically for ADF parser and context pruning algorithm)

### Implementation Roadmap

#### Phase 1: ADF Parser Enhancement
- [x] Components: `backend/engine/ac_parser.py`, `backend/adapters/jira.py`
- Milestone: Parser can extract clean text from deeply nested ADF without markdown corruption.
- Verification: Benchmark script parsing tests pass on complex tickets.

#### Phase 2: Context Optimization (Anti-Amnesia)
- [x] Components: `backend/engine/planner.py`, `backend/engine/state.py`
- Milestone: Prompt assembly is refactored to use a windowed history + failure diary, preventing lost-in-the-middle issues.
- Verification: Long-running test simulation passes without losing role context.

#### Phase 3: Decision Loop Streamlining
- [x] Components: `backend/engine/evaluator.py`
- Milestone: Evaluator more aggressively cuts off unproductive paths before they bloat the planner context.
- Verification: E2E success rate ≥ 90%.

---

## Execution State

**Build Status**: IDLE
**Last Completed**: ARCHIVE
**Can Resume**: NO
**Archive Document**: memory-bank/archive/archive-natural-language-translation-engine-upgrade.md
**Reflection Document**: memory-bank/reflection/reflection-natural-language-translation-engine-upgrade.md

### Summary
- Phase 1 (ADF Parser Enhancement): COMPLETE
- Phase 2 (Context Optimization Anti-Amnesia): COMPLETE
- Phase 3 (Decision Loop Streamlining): COMPLETE
- Reflection: COMPLETE
- Archive: COMPLETE (2026-05-15T18:24:00-05:00)
