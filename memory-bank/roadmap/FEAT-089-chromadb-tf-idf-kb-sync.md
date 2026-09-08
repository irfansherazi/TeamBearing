---
legacy_id: FEAT-089
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-089: ChromaDB & TF-IDF KB Sync
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Pillar**: P4 — Knowledge Base / Domain Context
- **Gap ID**: P4-B
- **Estimated Effort**: ~4h
- **Description**: ChromaDB `HumanGuidanceVault` and the TF-IDF KB are out of sync — `persist_user_guidance()` writes to the flat file only, never indexing into ChromaDB. The pre-flight query only uses TF-IDF. Fix: update `persist_user_guidance()` to dual-write (flat file + ChromaDB) and update the pre-flight KB query to use ChromaDB semantic search with TF-IDF fallback.
- **Acceptance Criteria**:
  - AC-1: `persist_user_guidance()` writes the guidance entry to both `human_guidance.md` and the ChromaDB `HumanGuidanceVault` collection.
  - AC-2: The pre-flight KB query uses ChromaDB semantic search as the primary retrieval path.
  - AC-3: When ChromaDB is unavailable, the system falls back to TF-IDF with a WARN log.
  - AC-4: Integration test: write a guidance entry, query via pre-flight search, verify it is returned by ChromaDB (not just TF-IDF).
- **Key Files**:
  - `backend/kb/rag.py` — `persist_user_guidance()`, pre-flight query
  - `backend/kb/chroma_store.py` (or equivalent ChromaDB client)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-089-chromadb-tfidf-sync
- **Created**: 2026-06-03
