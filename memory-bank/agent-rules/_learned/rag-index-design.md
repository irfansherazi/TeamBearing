---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: rag-index-design

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **rag-index-design** (`backend/kb/`, `backend/engine/planner.py`): When building a RAG index for a domain with distinct document types (e.g., selectors vs. blueprints), always use separate indices per document type — a unified corpus cross-contaminates term distributions and degrades precision for both domains. Domain nouns will score against unrelated documents producing retrieval noise.
  - _Source_: reflection-TASK-030 (2026-05-18)
  - _Reinforced_: 0x

- **dense-semantic-guidance-vault** (`backend/kb/rag.py`, `backend/kb/loader.py`): Store human-written guidance or hot-patch instructions in a local persistent vector database collection (e.g. ChromaDB backed by `all-MiniLM-L6-v2`) instead of keyword-matching files. This enables semantic similarity querying that matches user intent (e.g., matching sorting actions to "List View Sorting" workflow guidelines) even when literal keywords differ. To prevent high execution latency during queries, enforce model CPU execution provider constraints on MacOS to bypass ONNX runtime CoreML thread hanging issues.
  - _Source_: reflection-TASK-094 (2026-06-02)
  - _Reinforced_: 0x

- **rag-budget-cap** (`backend/kb/selector_rag.py`): The hard-truncation suffix string appended after budget trimming (e.g., `"...RAG budget cap applied"`) must itself be counted toward `max_chars` before appending. Failing to count the suffix silently breaches the budget invariant for entries near the cap boundary and only manifests in edge cases that are invisible in happy-path tests. Always write a test that asserts `len(result) <= max_chars` with no margin.
  - _Source_: reflection-TASK-030 (2026-05-18)
  - _Reinforced_: 0x
