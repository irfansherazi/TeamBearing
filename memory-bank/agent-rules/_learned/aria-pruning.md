---
name: Intent-Driven ARIA Pruning
globs: ["backend/browser/accessibility.py", "backend/engine/planner.py"]
paths: ["backend/browser/", "backend/engine/"]
topics: ["accessibility-tree", "token-optimization", "web-automation"]
priority: medium
auto_generated: true
evidence_count: 2
last_reinforced: 2026-06-02
source_tasks: ["TASK-007", "TASK-094"]
derived_from: []
last_validated: 2026-07-22
---


# Intent-Driven ARIA Pruning

Optimize LLM context by filtering the ARIA accessibility tree based on current task intent, viewport visibility, and structural relevance.

## Context
Enterprise web applications often have dense UIs (tables with 50+ rows, complex sidebars) that exceed LLM context windows or cause high token costs. Semantic pruning reduces noise while preserving critical interaction context.

## Guidelines

1. **Multi-Stage Filtering**:
   - **Stage 1 (Structural)**: Prune hidden elements and elements outside the browser viewport. Use `getBoundingClientRect()` in JavaScript for reliable viewport detection.
   - **Stage 2 (Semantic)**: Filter elements by ARIA role based on the current step's goal (e.g., if the goal is "Fill form", prioritize `textbox` and `button`).
   - **Stage 3 (Safety)**: Always retain a core set of "safety roles" (`ALWAYS_KEEP_ROLES`) for global navigation and feedback (e.g., `dialog`, `alert`, `navigation`, `tab`).

2. **State Propagation**:
   - Store `target_element_types` in the global state machine (e.g., `VQAState`).
   - Populate these types during the requirements parsing phase (AC Parser).
   - Update these types dynamically as the agent advances through different test steps.

3. **Fallback Strategy**:
   - If `target_element_types` is empty or missing, fall back to structural pruning (viewport only) or no pruning to avoid blocking execution.

4. **Consistency**:
   - Ensure the interactive summary format is consistent across different pruning strategies to maintain LLM parsing reliability.

5. **Bottom-Up AST Parsing & Serialization (TASK-094)**:
   - Parse indented accessibility tree snapshots into a node-hierarchy tree.
   - Recursively evaluate nodes bottom-up: keep nodes representing interactive elements, safety landmarks, or the anchor WebArea.
   - For all other structural nodes, keep them if and only if they have at least one kept descendant (preserving the nesting chain).
   - Serialize only marked nodes back into indented tree layout to prune layout boilerplate and achieve a character count reduction of ≥40%.
