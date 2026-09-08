---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: kb-injection

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **kb-injection-dedup-first** (`backend/engine/`, `knowledge/`): Any feature that writes to a runtime knowledge file must implement deduplication as a **co-primary concern in the same phase as injection** — not as a follow-up. Build the dedup check before building the write path. Dedup key should be based on semantic content (e.g., `TRIGGER_CONDITION` text) rather than content hash, to remain stable across whitespace changes and minor formatting differences.
  - _Source_: reflection-TASK-029 (2026-05-18)
  - _Reinforced_: 0x

- **kb-injection-schema-required-fields** (`knowledge/human_guidance.md`, `backend/engine/exploration_runner.py`): Injected KB entries must always include: `TITLE`, `KEYWORDS`, `TRIGGER_CONDITION`, `NAVIGATION_PATHWAY`, `GUIDANCE`, `SOURCE` (with value identifying the injecting component, e.g., `exploration_auto`), `CONFIDENCE` (float 0–1), and `CREATED` (ISO timestamp). The `SOURCE` tag and `CONFIDENCE` field enable human curation prioritization and filtering during `make kb-human-sync` review.
  - _Source_: reflection-TASK-029 (2026-05-18)
  - _Reinforced_: 0x

- **kb-injection-success-only** (`backend/engine/exploration_runner.py`): Only inject KB entries on confirmed `found=True` outcomes. Never inject on partial success, timeout-with-progress, or speculative findings. A false-positive KB entry is more damaging than a missed injection because it trains future RAG retrieval toward incorrect pathways.
  - _Source_: reflection-TASK-029 (2026-05-18)
  - _Reinforced_: 0x

- **hitl-as-training-signal** (`backend/engine/human_takeover.py`): Human intervention during manual takeover is the highest-quality ground truth. Always automate the capture and serialization of these actions into the permanent Knowledge Base (`learned_workflows.json`, `human_guidance.md`) to ensure the agent never asks for human help for the same specific UI state twice.
  - _Source_: reflection-TASK-033 (2026-05-20)
  - _Reinforced_: 0x
