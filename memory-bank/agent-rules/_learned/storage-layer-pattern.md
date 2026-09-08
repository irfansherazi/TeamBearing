---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: storage-layer-pattern

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **storage-layer-pattern** (`backend/storage/*.py`): When introducing a new filesystem-backed store, extend the `SuiteStore` threading-lock + JSON-index pattern: initialize `threading.Lock()`, load index on `__init__`, write index atomically (write then rename), and guard all mutations with `with self._lock`. Never access the index dict outside the lock.
  - _Source_: reflection-TASK-031 (2026-05-19)
  - _Reinforced_: 0x

- **replay-spec-filter** (`backend/storage/spec_serializer.py`): When serializing an action log for deterministic replay, filter to `success=True` steps only and strip all AI reasoning/accessibility-tree content — the replay consumer needs only `(action_type, selector, value)` triples. Including verbose discovery context inflates file size and couples the replay format to AI generation internals.
  - _Source_: reflection-TASK-031 (2026-05-19)
  - _Reinforced_: 0x

- **sqlite-storage-engine-isolation** (`backend/storage/*.py`, `backend/engine/*.py`): New SQLite-backed storage modules must follow the storage/engine split: the `storage/` module owns (schema creation, connection lifecycle, row insert/query); the `engine/` consumer owns (business logic, P95 calculations, ceiling derivation, fallback handling, feature-flag gate). Never write raw SQL inside `engine/` files. This separation enables independent testing of storage correctness (mock engine) and engine logic (mock storage) and prevents SQL query coupling to business rules. Pattern established by `TimingDB` + `TimeoutProfiler` in TASK-080 Phase 4.
  - _Source_: reflection-TASK-080 (2026-05-31)
  - _Reinforced_: 0x
