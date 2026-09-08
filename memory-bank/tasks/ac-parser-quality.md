---
legacy_id: ac-parser-quality
---
# ac-parser-quality: AC Parser Quality

**Complexity**: Level 3
**Status**: BUILD
**Roadmap**: FEAT-114
**Branch**: feature/FEAT-114-ac-parser-quality
**Worktree**: /Users/joshschauer/Documents/vProMedia/vQA/.worktrees/FEAT-114

## Task Description

Upgrade the AC parser across four dimensions:

1. **Model Upgrade** — Move the parser LLM from `claude-haiku-4-5` to `claude-sonnet-4` via a dedicated `bedrock_model_id_parser` config field, keeping the planner/verifier/evaluator on Haiku.

2. **Prompt Improvements** — Add `<REASONING>` blocks to `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` (extended-thinking guidance), and rewrite schema field descriptions in plain English.

3. **Instructor Migration** — Replace Stage 2's LangChain `ainvoke` + `json.loads` + `_repair_json` loop with `instructor` over raw `boto3` for deterministic, schema-validated JSON output with zero-repair retries.

4. **Golden 10 Benchmark Extension** — Add `expected_fields` to each Golden 10 fixture and write `tests/test_benchmark_ac_parser.py` to validate compiled JSON field correctness (step types, verification types, step counts).

5. **LangGraph HITL `interrupt_before`** — Wire `interrupt_before=["executor"]` into `build_graph()` when `ENABLE_HITL_BEFORE_EXECUTOR=True`, with a `POST /run/{run_id}/resume-executor` endpoint for approval.

## Specification

**Feature Type**: Infrastructure / Quality — backend pipeline improvement visible through parse accuracy.
**Primary Persona**: QA Lead / Automation Engineer — wants test plans that accurately reflect complex Jira cards without manual cleanup.
**Creative Exploration Needed**: No — design decisions resolved in implementation plan.

### Scope

- **In scope**: `backend/config.py`, `backend/llm/provider.py`, `backend/engine/prompts.py`, `backend/engine/ac_parser.py`, `backend/requirements.txt`, `tests/benchmarks/golden_10_data.json`, `tests/test_benchmark_ac_parser.py` (NEW), `backend/engine/graph.py`, `backend/api/routes.py`
- **Out of scope**: Frontend UI changes; planner/verifier/evaluator model changes; new Jira API calls

### Acceptance Criteria

#### Phase 1: Model + Prompts
- **AC-1**: `settings.bedrock_model_id_parser` defaults to `"us.anthropic.claude-sonnet-4-20250514-v1:0"`.
- **AC-2**: `get_llm("parser")` uses `bedrock_model_id_parser`, not `bedrock_model_id`.
- **AC-3**: `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` contain a `<REASONING>` XML block.
- **AC-4**: `JSON_COMPILER_PROMPT` OUTPUT_FORMAT fields have plain-English descriptions.
- **AC-5**: All existing AC parser tests pass unchanged.

#### Phase 2: Instructor Migration
- **AC-6**: Stage 2 (`_stage_2_compile`) uses `instructor` client — no `json.loads` or `_repair_json` calls.
- **AC-7**: `instructor>=1.3.0` added to `backend/requirements.txt`.
- **AC-8**: All existing AC parser tests pass with the new implementation.

#### Phase 3: Benchmark Extension
- **AC-9**: Each of the 10 Golden 10 fixtures has an `expected_fields` object with `min_steps`, `required_step_types`, `required_verification_types`, and `test_title_contains` keys.
- **AC-10**: `tests/test_benchmark_ac_parser.py` contains ≥8 tests validating compiled TestPlan fields against `expected_fields`.
- **AC-11**: All new benchmark tests pass under `pytest tests/test_benchmark_ac_parser.py -v`.

#### Phase 4: HITL Interrupt
- **AC-12**: `settings.enable_hitl_before_executor` exists and defaults to `False`.
- **AC-13**: When `True`, `build_graph()` compiles with `interrupt_before=["executor"]`.
- **AC-14**: `POST /run/{run_id}/resume-executor` endpoint exists and resumes the graph.
- **AC-15**: When flag is `False`, graph behavior is identical to current (no regression).

## Test Strategy

### Approach
- **Emphasis**: Unit tests with mocked LLM; no live Bedrock calls.
- **Target test count**: 8 new tests (Phase 3 benchmark) + 2 new tests (Phase 4 interrupt config); existing ~40 AC parser tests serve as regression baseline.

### File Organization
- **New test files**: `tests/test_benchmark_ac_parser.py`
- **Modified test data**: `tests/benchmarks/golden_10_data.json`
- **Extend existing**: none — existing AC parser tests are sufficient regression coverage

## Implementation Roadmap

- [ ] Phase 1: Model upgrade (`bedrock_model_id_parser` config + `get_llm("parser")` routing) + prompt improvements (`<REASONING>` blocks, plain-English schema)
- [ ] Phase 2: Instructor migration — `_stage_2_compile()` rewrite + `instructor>=1.3.0` dependency
- [ ] Phase 3: Golden 10 benchmark extension — `expected_fields` + `test_benchmark_ac_parser.py`
- [ ] Phase 4: LangGraph `interrupt_before=["executor"]` + `enable_hitl_before_executor` flag + resume endpoint

## Creative Phases

None required — design resolved in planning.

---

## Execution State

**Build Status**: RUNNING
**Phase Being Built**: Phase 1 — Model upgrade + prompt improvements
**Phase Number**: 1 of 4
**Is Multi-Phase**: YES
**Build Started**: 2026-07-15
**Current Build Step**:
  Step: Step 1 - Read Task Context
  Status: COMPLETE
  Started: 2026-07-15
