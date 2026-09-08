---
name: Test Environment Isolation
globs: ["backend/engine/*.py", "backend/kb/*.py", "tests/**/*.py", "conftest.py"]
paths: ["storage/", "memory/", "tests/"]
topics: ["testing", "commit-guard", "storage-isolation", "chromadb", "selector-rag"]
priority: low
auto_generated: true
derived_from: [FEAT-118-vqa-tier3-architectural-hardening]
evidence_count: 1
last_validated: 2026-07-29
---

# Learned Rules: test-environment-isolation

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **restore-runtime-mutable-storage-before-staging** (`backend/engine/*.py`, `backend/kb/*.py`, all test files): Before staging any commit that follows a pytest run, always restore `storage/chromadb/chroma.sqlite3` (ChromaDB vector store) and `memory/selector_rag/` (selector-RAG index files: `*.pkl`, `.last_built`, `manifest.json`) to HEAD via `git checkout HEAD -- storage/chromadb/chroma.sqlite3 memory/selector_rag/`. These directories are mutated at test-import time and are NOT intended to be committed from a build session. Failing to restore causes C1 commit-guard failures (documented across 4 of 5 phases in FEAT-118, same pattern each time).
  - _Source_: reflection-FEAT-118-vqa-tier3-architectural-hardening (2026-07-29)
  - _Reinforced_: 0x

- **selector-rag-auto-rebuild-trigger** (`backend/kb/selector_registry.py`, `knowledge/selector_registry.json`): Importing `backend/kb/selector_registry.py` after modifying `knowledge/selector_registry.json` triggers a synchronous index rebuild that writes to `memory/selector_rag/*.pkl`, `.last_built`, and `manifest.json`. If your phase modifies `selector_registry.json` (e.g., seeding new registry entries), add `memory/selector_rag/` to the pre-commit restore list proactively — do not wait for the C1 guard to catch it. FEAT-118 Phase 2 evidence: 4 files required restore after adding `pvpromotions.*` entries.
  - _Source_: reflection-FEAT-118-vqa-tier3-architectural-hardening (2026-07-29)
  - _Reinforced_: 0x
