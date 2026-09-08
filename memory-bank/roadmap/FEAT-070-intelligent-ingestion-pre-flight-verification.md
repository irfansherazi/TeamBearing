---
legacy_id: FEAT-070
version: next
linked_tasks: [intelligent-ingestion-and-pre-flight-verification, intelligent-ingestion-and-pre-flight-verification]
status: in_progress
---

  ### FEAT-070: Intelligent Ingestion & Pre-Flight Verification
- **Version**: next
- **Status**: active
- **Priority**: critical
- **Complexity**: Level 3
- **Description**: Improve acceptance criteria grading via an LLM-based enricher and auto-generate negative test scenarios.
    1. **Hybrid LLM-in-the-Loop Enricher**: If the heuristic score in `ac_quality_gate.py` is below "GOOD", route the AC to an LLM-based Jira AC Enricher (`ac_enricher.py`). The enricher queries the vector store for historical test plans, pulls context from Jira comments, and rewrites the AC to clarify missing preconditions and target states.
    2. **Negative Path Synthesis**: Have the LLM auto-generate negative test scenarios (e.g., boundary condition inputs, unauthorized role access) based on the primary Given/When/Then steps.
- **Acceptance Criteria**:
    - AC-1: Integrate `ac_quality_gate.py` with `ac_enricher.py` to route ACs with heuristic scores below "GOOD" to the LLM-based Enricher.
    - AC-2: `ac_enricher.py` queries ChromaDB vector store for historical test plans and retrieves recent issue comments from Jira.
    - AC-3: `ac_enricher.py` uses an LLM to rewrite the AC, clarifying missing preconditions and expected target states.
    - AC-4: LLM auto-generates negative test scenarios (boundary conditions, unauthorized access) and appends them to the compiled test plan.
- **Key Files**:
    - `backend/engine/ac_quality_gate.py`
    - `backend/engine/ac_enricher.py`
    - `backend/jira/client.py`
    - `backend/kb/rag.py`
- **Linked Tasks**: [intelligent-ingestion-and-pre-flight-verification](tasks/intelligent-ingestion-and-pre-flight-verification.md)
- **Branch**: feature/FEAT-070-intelligent-ingestion
- **Created**: 2026-06-02
