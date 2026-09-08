---
legacy_id: FEAT-071
version: next
linked_tasks: [see-think-act-loop-optimization, see-think-act-loop-optimization]
status: complete
---

  ### FEAT-071: See-Think-Act Loop Optimization
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Optimize the core reasoning loop via semantic retrieval, DOM pruning, and hybrid vision split-execution.
    1. **Dense Semantic Embeddings**: Replace TF-IDF with a local, lightweight vector model (e.g., `all-MiniLM-L6-v2`) in `backend/kb/rag.py` to fetch relevant guides from `human_guidance.md` based on user intent rather than literal matches.
    2. **Semantic DOM Culling**: Filter out non-interactive layout nodes and structural boilerplate from the ARIA tree before feeding it to the `planner.py` context window, reducing token usage by 40–60%.
    3. **VLM/Local Model Split-Execution**: Use the VLM (Claude Sonnet) only to output high-level semantic targets (e.g., "Click the Save Button"). Use a localized, lightweight object-detection vision model (e.g., a YOLO network trained on web elements) to calculate the exact coordinate bounds on the local canvas.
- **Acceptance Criteria**:
    - AC-1: Integrate local semantic embeddings (`all-MiniLM-L6-v2`) in `backend/kb/rag.py` to replace TF-IDF matching for `human_guidance.md`.
    - AC-2: Implement a Semantic DOM Culler in `backend/engine/planner.py` that filters non-interactive layout nodes and boilerplate from the ARIA tree, reducing token consumption by ≥40%.
    - AC-3: Implement a Split-Execution paradigm where Claude Sonnet outputs high-level semantic targets (e.g., "Click Save") and a local object-detection model resolves the exact canvas coordinates.
- **Key Files**:
    - `backend/kb/rag.py`
    - `backend/engine/planner.py`
    - `backend/browser/context.py`
    - `backend/engine/executor.py`
- **Linked Tasks**: [see-think-act-loop-optimization](tasks/see-think-act-loop-optimization.md)
- **Branch**: feature/FEAT-071-loop-optimization
- **Created**: 2026-06-02
- **Completed**: 2026-06-02
