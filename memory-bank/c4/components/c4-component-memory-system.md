# C4 Component: Memory System

## Overview
The **Memory System** provides cross-run persistence and self-learning capabilities for the vQA agent. It tracks which interaction strategies work or fail in specific situations, enabling the agent to improve its performance over time through few-shot learning and pattern recognition.

## Metadata
- **Module**: `backend/memory/`
- **Primary Tech**: Python, SQLite
- **Component Type**: Service / State Store
- **Key Files**: 
    - `persistent.py`: SQLite-backed cross-run memory.
    - `pattern_store.py`: Abstraction for interaction patterns.
    - `skill_library.py`: Repository of reusable interaction skills.

## Responsibilities
- **Persistent Storage**: Maintains a SQLite database (`learned_patterns.db`) of historical interaction outcomes.
- **Pattern Learning**: Records (situation, strategy, worked/failed) tuples from live runs.
- **Few-Shot Retrieval**: Provides relevant "few-shot" examples to the Planner LLM based on step similarity.
- **KB Proposals**: Identifies frequently successful patterns that should be promoted to the permanent Knowledge Base.
- **Skill Management**: Stores and retrieves complex interaction sequences (skills) that the agent has "learned".

## Architecture: Three-Tier Memory
1. **Tier 1: Run Memory**: Ephemeral state within a single run (VQAState).
2. **Tier 2: Persistent Memory**: Cross-run SQLite store used for dynamic prompt injection.
3. **Tier 3: Knowledge Base (KB)**: Permanent interaction blueprints and blueprints (managed by the KB component).

## Interfaces
- `PersistentMemory.record(situation, strategy, worked, strategy_fix)`: Logs an interaction outcome.
- `PersistentMemory.get_few_shot_examples(step_description)`: Returns similar historical patterns for prompt injection.
- `SkillLibrary.get_skill(name)`: Retrieves a named interaction skill.

## Dependencies
- **vQA Backend Core**: Provides the run context and state.
- **Knowledge Base**: Target for promoted patterns.
- **LLM Provider**: Consumes few-shot examples in prompts.
