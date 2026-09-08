---
legacy_id: FEAT-074
version: next
linked_tasks: []
status: planned
---

  ### FEAT-074: Failure Signature Clustering & Auto-Reporting
- **Version**: next
- **Status**: planning
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Post-run analysis engine to automatically cluster pipeline failures and generate Jira Bug cards.
    1. **Failure Signature Clustering**: Run an LLM over batch results to cluster failures by visual similarity of screenshots, stack traces, and active DOM states. Consolidate 100 failures into 2-3 logical bugs, saving developer triage time.
    2. **Auto-Jira Bug Generation**: Automatically draft a detailed Jira Bug card, attach reproduction steps, and link a visual delta screenshot and Playwright video whenever a test fails due to a verified product regression.
- **Acceptance Criteria**:
    - AC-1: Build a post-run Failure Signature Clustering engine that parses test failure artifacts (stack traces, active DOM states, screenshot paths).
    - AC-2: Consolidate multiple runs and run an LLM-based clustering algorithm to group failures by semantic root causes.
    - AC-3: Automatically format and draft rich Jira Bug cards for each clustered failure, including reproduction steps, visual deltas, and video links.
- **Key Files**:
    - `backend/jira/client.py`
    - `backend/api/routes.py`
    - `scripts/failure_clustering.py` (New file)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-074-failure-clustering
- **Created**: 2026-06-02
