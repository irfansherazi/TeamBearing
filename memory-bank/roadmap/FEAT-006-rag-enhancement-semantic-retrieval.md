---
legacy_id: FEAT-006
version: v1.1.0
linked_tasks: []
status: complete
---

### FEAT-006: RAG Enhancement & Semantic Retrieval
- **Version**: v1.1.0
- **Status**: complete
- **Priority**: medium
- **Complexity**: Level 3
- **Description**: The TF-IDF RAG system works well for specific, keyword-rich AC steps but degrades badly on the short, vague steps that are the whole problem we're solving. This feature improves retrieval for short/vague inputs: (1) Dynamic query expansion — for steps shorter than 20 words, expand the query with domain synonyms more aggressively; added 14 new synonym mappings for common vSuite patterns (alps, voicer, qo, campaign, etc.) with double-weight expansion for queries < 10 words. (2) KB gate logging — added logger.info() with diagnostic details (threshold, top_score, top_name) when a KB gate is OPEN but returns NO MATCH, so operators can see exactly which steps received no KB context. (3) BM25 scoring alongside TF-IDF — added BM25Okapi re-ranking over the top-10 TF-IDF results with 0.6/0.4 combined scoring; improves long-tail recall without adding LLM cost. (4) Negative keyword support — added FORBIDDEN_KEYWORDS field to KB entries that prevents retrieval when the AC step contains those words; applied to 4 high-impact entries (Login/Auth, Failed Login, Login Already Satisfied, Table Views). (5) Dynamic threshold tuning — lowered TF-IDF threshold floor from 0.10 to 0.06 for steps < 15 words to compensate for low term frequency on short queries.
- **Linked Tasks**: None
- **Branch**: feature/FEAT-006-rag-enhancement
- **Created**: 2026-05-07
- **Completed**: 2026-05-08
