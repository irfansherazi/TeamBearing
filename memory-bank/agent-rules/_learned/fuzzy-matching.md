---
name: "Learned: Fuzzy Matching"
globs: ["backend/engine/planner.py", "knowledge/*.json", "backend/browser/vision_utils.py"]
topics: ["fuzzy-matching", "text-matching", "hallucination-reduction"]
priority: medium
evidence_count: 4
last_updated: 2026-07-30
auto_generated: true
derived_from: [accessibility-tree-grounding]
last_validated: 2026-07-30
---


# Fuzzy Matching

- Use word-level `issubset` matching (not `intersection`) when matching multi-word labels against free text to prevent false positives from common words.
- For minimal stemming in a controlled-vocabulary domain, suffix-strip (`s` removal for words > 3 chars) is sufficient — avoid NLP library dependencies on hot-path functions.
- **Split-Execution Element Target Resolution (TASK-094)**: When matching high-level semantic descriptions to interactive DOM elements, check all textual properties (such as text content, aria-label, placeholder, title, and name attribute) and compute a similarity score combining substring matching and Jaccard word token similarity to locate the best candidate.

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Word-level issubset matching | [reflection-TASK-014.md](../reflection/reflection-TASK-014.md) | 2026-05-13 |
| Minimal suffix-strip stemming | [reflection-TASK-014.md](../reflection/reflection-TASK-014.md) | 2026-05-13 |
| Jaccard & text-property fuzzy target matching | [reflection-TASK-094.md](../reflection/reflection-TASK-094.md) | 2026-06-02 |
