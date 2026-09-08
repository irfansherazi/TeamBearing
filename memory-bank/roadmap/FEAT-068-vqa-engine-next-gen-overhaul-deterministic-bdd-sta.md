---
legacy_id: FEAT-068
version: next
linked_tasks: []
status: planned
---

  ### FEAT-068: vQA Engine Next-Gen Overhaul — Deterministic BDD, State Blackboard & Angular Integration
- **Version**: next
- **Status**: planning
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: A multi-layered architectural upgrade to the vQA engine to ensure 100% reliability on complex multi-actor and state-dependent tests.
    1. **Layer 1: The Pre-Flight BDD Compiler (Reasoning)**: Compiles a deterministic blueprint before the browser opens. Scans for keywords like "isolation" or "sharing" to expand Jira cards into Multi-Actor TestPlans (e.g., [SWITCH_ACTOR: User B]). Successful plans are saved in a TestPlan Vault (ChromaDB RAG) for future retrieval.
    2. **Layer 2: The Omniscient Blackboard (State)**: A persistent, cross-session Global Fact Store that tracks shared entities (e.g., folder names) across logouts and actor switches. Includes Visual Snapshot Diffs for structural comparison before/after mutations and a Dynamic Actor Registry for credential mapping.
    3. **Layer 3: The Angular Bridge (Execution)**: Injects JS payload (`__ngContext__`) to read component state directly (e.g., `p-dropdown` open, form invalid). Includes a Fail-Fast Circuit Breaker that aborts in <800ms if elements are missing, and Native Engine Macros (95KB of PrimeNG rules) to handle precise interaction sequences with 100% reliability.
    4. **Layer 4: The "Smarter Every Run" Feedback Loop**: Level up after every run. If a new UI pattern is hit, use Exploration Mode; then extract the "Winning Sequence" as a Native Tool Macro. Subsequent runs on similar tickets fetch and execute the proven blueprint deterministically.
- **Acceptance Criteria**:
    - Jira cards with "sharing" or "isolation" are automatically expanded into Multi-Actor TestPlans.
    - Global Fact Store correctly tracks and retrieves facts (e.g., `shared_folder_name`) across actor switches.
    - Angular state injection allows reading internal component properties (e.g., `p-dropdown` open status).
    - Fail-fast probes abort missing element actions in <800ms with `DOM_ABSENT` diagnosis.
    - PrimeNG interactions use backend macros instead of raw LLM reasoning.
    - Successful exploration runs are automatically converted into and stored as deterministic macros.
- **Key Files**:
    - `backend/engine/ac_parser.py` (BDD Compiler)
    - `backend/engine/state.py` (Blackboard)
    - `backend/browser/injection.js` (Angular Bridge)
    - `backend/engine/executor.py` (Native Macros)
    - `backend/kb/rag.py` (TestPlan Vault)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-068-engine-overhaul
- **Created**: 2026-06-01
