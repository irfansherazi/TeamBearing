---
legacy_id: FEAT-116
version: next
linked_tasks: [vqa-tier1-executor-recovery]
status: completed
---

### FEAT-116: vQA Tier 1 — Executor Recovery Hardening (Contest-class Failures)
- **Version**: next
- **Status**: completed
- **Priority**: critical
- **Complexity**: Level 3
- **Description**: Ship the four highest-ROI executor fixes surfaced by the 2026-07-27 QA-358 failure analysis. Together these reclaim ~10–15 seconds per strict-mode failure, restore the RAG debugger to a working state (currently silently broken by a missing package), and re-enable HITL-derived guidance retrieval (currently broken by mis-tuned HNSW parameters). The Contest-dropdown failure pattern — where the LLM plans `get_by_text("Contest")` against 41 pre-rendered but hidden matches inside a closed `<p-select>` and then loops through DOM strict-mode violations, CV fallback failures, and HITL amnesia — becomes an auto-recoverable actionable error instead of a run-terminating loop.

  Implementation is phased:
  1. **Component-Aware Precondition Check (T1-a)** — Add `_is_target_in_open_container(page, target_text)` to the executor. Before dispatching any text-target click, query for known "closed" containers: `p-select-overlay:not(.p-select-overlay-open)`, `p-dropdown-panel[aria-hidden="true"]`, native `<select>`, `p-autocomplete[aria-expanded="false"]`. If the target text is inside a closed container, return `error_message="TARGET_INSIDE_CLOSED_CONTAINER: open <trigger_selector> first"` with the concrete trigger selector — turning a stack trace into an actionable next step for the planner.
  2. **Kill the `.first + scroll_into_view` Fallback When Total Dominates Visible (T1-b)** — In the 0-visible strict-mode branch (`executor.py:986-1040`), skip the `scroll_into_view_if_needed` attempt entirely when `total_count > 5`. That fallback is almost always futile against Angular's pre-rendered false matches and burns 3s per attempt. Instead, surface `STRICT_MODE_AMBIGUOUS` immediately with a strategy-switch hint ("use `container_selector` + `get_by_role='option'`"). Reclaims ~10s per failure.
  3. **Fix RAG Debugger LlamaIndex Dependency (T1-c)** — Replace the LlamaIndex query engine in `backend/engine/rag_debugger.py` with a direct Chroma retrieval call. Since the code already uses `response_mode="no_text"` and Bedrock embeddings, LlamaIndex adds only overhead — and its OpenAI-LLM extra requirement has silently broken the debugger in every session captured today. Estimated ~40 lines removed. The debugger regains its semantic KB context and can produce grounded fix recommendations again.
  4. **Fix HumanGuidanceVault HNSW Parameters (T1-d)** — Recreate the Chroma collection for `human_guidance.md` with `metadata={"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}` — the current defaults (M=16, ef=10) throw `Cannot return the results in a contigious 2D array. Probably ef or M is too small` at every query with the current 500+ vectors. Add a one-shot migration script that re-embeds `human_guidance.md` on startup so prior HITL guidance is retrievable again.

- **Acceptance Criteria**:
    - AC-1: When a planner emits `click get_by_text("Contest")` against a page where the `<p-select>` PRF Category dropdown is closed, the executor returns `TARGET_INSIDE_CLOSED_CONTAINER` with the exact `trigger_selector` for the closed container — not a strict-mode stack trace.
    - AC-2: For strict-mode violations with `total_count > 5` and `visible_count == 0`, the executor returns `STRICT_MODE_AMBIGUOUS` (with a strategy hint) within 500ms, without attempting `scroll_into_view_if_needed`. Total wall-clock savings per such failure ≥ 8 seconds.
    - AC-3: `backend.engine.rag_debugger.query_knowledge_base(error_log)` returns a formatted, non-empty result for a known-similar error log against the current index, with no `llama-index-llms-openai` package requirement in `backend/requirements.txt`.
    - AC-4: A call to `KBLoader.query_workflows()` that would exercise the HumanGuidanceVault semantic search path (product=vpromotions, step contains "Contest") returns matches successfully — no `Cannot return the results in a contigious 2D array` error is logged, and prior HITL guidance for QA-358 is retrievable.
    - AC-5: Regression: existing green tests in `backend/engine/test_*.py` continue to pass. New unit tests cover each of the four fixes (component-aware precondition, strict-mode short-circuit, RAG direct-Chroma path, HNSW-tuned collection).
    - AC-6: On a fresh run of QA-358 against vpromotions QA env, the AC step "Select Contest from PRF Category dropdown" either (a) auto-recovers via T1-a's actionable error → planner opens the trigger → succeeds, or (b) still escalates but does so in < 30 seconds instead of ~225s.

- **Key Files**:
    - `backend/engine/executor.py` — T1-a helper + T1-b strict-mode branch rewrite (lines 962-1040)
    - `backend/engine/rag_debugger.py` — T1-c: replace LlamaIndex query engine with direct Chroma retrieval (~40 lines removed)
    - `backend/kb/loader.py` — T1-d: HNSW config on collection creation, one-shot migration path
    - `backend/kb/rag.py` — T1-d: HNSW metadata on `hnsw:space` calls at lines 54, 143
    - `backend/requirements.txt` — remove any lingering `llama-index-*` deps not needed after T1-c
    - `scripts/migrate_human_guidance_vault.py` (New) — re-embed `human_guidance.md` with corrected HNSW params on startup
    - `backend/engine/test_executor_component_gate.py` (New) — unit tests for T1-a
    - `backend/engine/test_executor_strict_mode.py` (New / extend) — unit tests for T1-b
    - `backend/engine/test_rag_debugger.py` (New / extend) — unit tests for T1-c
    - `backend/kb/test_human_guidance_vault.py` (New / extend) — unit tests for T1-d
- **Linked Tasks**: vqa-tier1-executor-recovery
- **Branch**: feature/FEAT-116-vqa-tier1-executor-recovery
- **Created**: 2026-07-28
