# Reflection: end-to-end-pipeline-optimization End-to-End Pipeline Optimization

## 1. Goal vs. Outcome
- **Goal**: Optimize the full pipeline (Jira -> BDD -> JSON -> Exec -> Verify) for reliability and 90%+ pass rate.
- **Outcome**: Achieved **100% pass rate** on the "Golden 10" benchmark set. Fixed 9 regression tests by implementing the missing Per-Step Budgeting (FEAT-021). Enhanced verifier reliability with animation settling time.

## 2. Key Challenges

### Non-ASCII Character Trap
- **Issue**: Using specialized characters like `→`, `—`, and `✓` in LLM prompts within `.py` files caused `SyntaxError: invalid character` during execution.
- **Solution**: Replaced all decorative characters with ASCII equivalents (`->`, `--`, `[PASS]`).
- **Learning**: Always stick to standard ASCII in Python string literals meant for prompts, as the runtime environment might not handle UTF-8 literals gracefully in all contexts.

### The "Shadow" Feature (FEAT-021)
- **Issue**: `roadmap.md` and `progress.md` marked FEAT-021 (Per-Step Budgeting) as complete, but the code in `evaluator.py` and `state.py` was completely missing the logic, causing 9 unit tests to fail.
- **Solution**: Implemented the budgeting logic from scratch in the Evaluator, added state fields, and updated the configuration.
- **Learning**: Documentation can lie. Always verify the actual codebase state before assuming a dependency or "linked task" is actually functional.

### Unit Test Mocking Conflicts
- **Issue**: Mocking `settings` in unit tests caused `TypeError` when the code tried to compare an `int` with a `MagicMock`.
- **Solution**: Wrapped `settings` access in `int()` casts where numerical comparison is critical, allowing mocks to be coerced to integers if they provide a `__int__` or similar (or simply ensuring the logic is robust).

## 3. Architectural Insights

### The Benchmark Runner is Foundational
- Implementing `scripts/benchmark_pipeline.py` transformed prompt engineering from "guess and check" to "measure and verify". We can now quantitatively say the parser improved by 10%.

### Settling Time for SPAs
- Single Page Applications (SPAs) like Angular/PrimeNG have "DOM-visible but visually-incomplete" states. A mandatory 300ms "Settling Time" in the verifier significantly reduces flakiness without bloating execution time.

### Schema Accuracy = LLM Sanity
- The LLM was hallucinating `visual_check` because it "felt" like a valid check type, even though it wasn't in the schema. Aligning the Pydantic schema with the LLM's natural tendencies (and formalizing those tendencies) prevents Stage 2 retries.

## 4. Future Improvements
- **Multi-Model Verification**: Add the "Haiku auditing Sonnet" check designed in the creative phase.
- **Temporal Snapshotting**: Record DOM diffs before/after actions for more precise verification evidence.
- **Benchmark Expansion**: Expand the Golden 10 to a Golden 50 to cover more edge cases.

## 5. Decision Log (Post-Task)
| Component | Decision | Rationale |
|-----------|----------|-----------|
| Verifier | Add 300ms `page.wait_for_timeout` | Handles Angular CSS transitions. |
| Parser | Split "Navigate" and "Login" in prompts | Ensures credentials aren't leaked in navigation goals. |
| Config | New `per_step_budget_max` | Protects global budget from infinite loops. |
