---
legacy_id: FEAT-063
version: next
linked_tasks: []
status: complete
---

### FEAT-063: Verifier Integrity & Anti-Hallucination Guardrails
- **Version**: next
- **Status**: complete
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: The vQA verifier can mark AC steps as SATISFIED even when the underlying browser action failed or was never actually executed. This is a systemic trust and accuracy issue that corrupts accepted test memory and makes the product unreliable across all test runs. Root causes: (1) Programmatic checks evaluate stale or pre-action page state rather than confirming post-action state change; (2) The evaluator can route a failed executor action directly to the verifier, allowing a SATISFIED verdict on an action that timed out or errored; (3) There is no mechanism to distinguish 'page was already in a passing state before the action' from 'action caused the passing state'; (4) There is no human-in-the-loop feedback path to pause a live run, flag false positives, and inject corrective context into the planner mid-run. Required outcomes: executor failures must gate verifier routing; verifier must always use a fresh post-action snapshot; programmatic checks must validate state change not just state presence; a human operator feedback/retraining mechanism must exist so falsely-passed steps can be corrected before they are written to accepted test memory; optionally a cross-validator sub-agent independently reviews verdicts before they are committed as ground truth. Additionally, all dropdowns must abide by the selected theme (light or dark).
- **Linked Tasks**: None
- **Branch**: feature/FEAT-063-verifier-integrity-guardrails
- **Created**: 2026-05-31
