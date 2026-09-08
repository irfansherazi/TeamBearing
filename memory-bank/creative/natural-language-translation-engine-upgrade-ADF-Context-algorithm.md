# Algorithm: ADF Parser and Context Pruning

## Decision
**Chosen**: Option 1 — Recursive ADF Extraction + Sliding Window with Failure Diary
**Rationale**: This hybrid approach (Option C from the architectural plan) ensures zero added LLM latency for parsing and pruning. By keeping only the last 5 actions verbatim and persistently pinning a structured list of failed actions (the Failure Diary), we prevent both the "lost-in-the-middle" syndrome and infinite retry loops. Recursive AST traversal of ADF is robust, handles nested structures cleanly, and converts JSON bloat into readable markdown without relying on an LLM.

## Algorithm Design

### 1. ADF Parser (in `ac_parser.py` / `jira.py`)
```python
def extract_adf_text(node: dict) -> str:
    """Recursively parses Atlassian Document Format (ADF) into Markdown."""
    if not isinstance(node, dict):
        return str(node)
    
    node_type = node.get("type")
    content = node.get("content", [])
    
    if node_type == "text":
        text = node.get("text", "")
        # Apply marks (e.g., bold, code)
        for mark in node.get("marks", []):
            if mark["type"] == "strong": text = f"**{text}**"
            elif mark["type"] == "code": text = f"`{text}`"
        return text
        
    extracted = [extract_adf_text(child) for child in content]
    
    if node_type == "paragraph":
        return " ".join(extracted) + "\n\n"
    elif node_type == "bulletList":
        return "\n" + "".join(extracted) + "\n"
    elif node_type == "listItem":
        return f"- {' '.join(extracted).strip()}\n"
    
    return "".join(extracted)
```

### 2. Context Pruning & Failure Diary (in `planner.py` & `state.py`)
- **State Augmentation**: Add `failure_diary: list[dict]` to `VQAState`.
- **Evaluator Updates**: When `evaluator.py` detects a failure (e.g., locator not found, strict mode error), it appends `{ "action": action_dict, "error": error_msg, "step_index": idx }` to `failure_diary`.
- **Planner Prompt Assembly**:
  - Filter `action_history` to the last `N` (e.g., 5) items (`<recent_history>`).
  - Read `failure_diary`. Deduplicate and inject into a `<failure_diary>` block in the prompt.
  - Pin the current AC step and role constraints at the top (`<core_constraints>`).

## Complexity Analysis
- **Time Complexity**: 
  - ADF Parsing: O(N) where N is the number of nodes in the ADF JSON tree.
  - Context Pruning: O(M) where M is the number of actions in the history buffer (very small).
- **Space Complexity**: O(N) for the extracted ADF string; O(K) for the Failure Diary (bounded by the max error retries).

## Options Explored

### Option 1: Recursive ADF Extraction + Sliding Window with Failure Diary
- **Algorithm**: AST-like traversal for ADF; sliding window for recent history; explicit list for failed attempts.
- **Time**: O(N) traversal, O(1) LLM latency.
- **Space**: O(N) memory.
- **Pros**: Highly deterministic, no extra LLM cost, keeps context small and focused.
- **Cons**: Requires custom ADF parsing logic.

### Option 2: LLM-Based Summarization
- **Algorithm**: Send raw ADF to a smaller LLM to extract text. Send action history to an LLM every 5 steps to generate a summary.
- **Time**: O(1) local execution, but adds ~1-2 seconds of network latency for LLM calls.
- **Space**: O(1) local memory.
- **Pros**: Very simple to implement locally; handles edge cases natively.
- **Cons**: High latency, increased token costs, risk of LLM hallucinatory summarization losing critical details.

### Option 3: Strict Pruning (No Failure Tracking)
- **Algorithm**: Regex strip brackets for ADF. Drop all actions older than 3 steps.
- **Time**: O(N) regex, O(1) pruning.
- **Space**: O(N) local.
- **Pros**: Simplest implementation.
- **Cons**: Regex fails on nested JSON; dropping history completely leads to the agent retrying the same failed locator in an infinite loop.

## Evaluation Matrix

| Criteria | Weight | Option 1 (Hybrid) | Option 2 (LLM Sum) | Option 3 (Strict) |
|----------|--------|-------------------|--------------------|-------------------|
| Correctness | Critical | 5 | 4 | 2 |
| Time complexity | High | 5 | 2 | 5 |
| Space complexity | Medium | 4 | 4 | 4 |
| Implementation simplicity | Medium | 3 | 4 | 5 |
| Testability | Medium | 5 | 2 | 3 |
| Scalability | Context-dependent | 5 | 3 | 5 |

Option 1 is the clear winner, maximizing reliability and performance while minimizing LLM dependencies.
