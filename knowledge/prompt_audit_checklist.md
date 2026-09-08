# Prompt Engineering Audit Checklist

This checklist is a development standard for all LLM system prompts in the vQA engine. All future prompt modifications must be evaluated against these criteria before merge.

## 1. Primacy & Recency (Anchoring)
- [ ] **Primacy**: Are the most critical "Golden Rules" (identity, mission, core guardrails) stated in the first 10% of the prompt?
- [ ] **Recency**: Are the most important constraints and the required output format repeated or summarized in the final 10% of the prompt?
- [ ] **Rule Duplication**: High-impact rules (e.g., "Output ONLY JSON", "NEVER invent data") should be anchored at both the START and END.

## 2. Structural Delimiters
- [ ] **XML/Markdown Delimiters**: Are instructions, context, and examples separated by clear, consistent delimiters?
  - Use `<RULES>`, `<CONTEXT>`, `<EXAMPLES>`, `<DIARY>`, `<PAGE_STATE>` tags.
- [ ] **Context Isolation**: Is dynamic data (like Jira ACs or DOM snapshots) wrapped in tags to prevent it from bleeding into instructions?

## 3. Few-Shot & Edge Cases
- [ ] **Domain Examples**: Does the prompt include 3-5 few-shot examples of *correct* behavior for domain-specific components (e.g., PrimeNG dropdowns, sorting)?
- [ ] **Failure Mode Examples**: Are there examples of how to handle known edge-case failures (e.g., "Strict Mode Violation", "Word Fusion" in Jira ADF)?

## 4. Reasoning & Chain-of-Thought (CoT)
- [ ] **Explicit Workflow**: Is there a `mandatory_reasoning_workflow` or similar section that forces the model to reason BEFORE deciding on an action?
- [ ] **Step-by-Step Instructions**: Does the reasoning workflow have numbered steps (e.g., Step 1: Anti-Loop Check, Step 2: View Detection)?

## 5. Efficiency & Attention
- [ ] **Lost-in-the-Middle Mitigation**: Is the prompt pruned of redundant or obsolete rules?
- [ ] **Focused Context**: Is the dynamic context (like history) limited to the N most recent relevant entries?

## 6. Format & Schema
- [ ] **Output Schema**: Is the required JSON/Markdown schema clearly defined with an example?
- [ ] **Constraint Enforcement**: Are there clear "FORBIDDEN" or "NEVER" rules for common hallucinations or invalid output formats?

---

## Prompt Registry

> **Enforcement Gate**: `tests/test_prompt_structure.py` is the authoritative CI enforcement gate for structural invariants.
> Run `pytest tests/test_prompt_structure.py -v` to validate all prompts against this checklist.

| Prompt Constant | File | Agent Role | GOLDEN_RULES | CRITICAL_REMINDER | XML Delimiters | CoT Workflow | Last Audited |
|----------------|------|------------|:---:|:---:|:---:|:---:|------|
| `_CORE_RULES` + `_build_system_prompt_v2()` | `backend/engine/planner.py` | Planner (multimodal action agent) | ✅ (IDENTITY slot, CRITICAL tier) | ✅ (via `JSON_OUTPUT_REMINDER`) | ✅ (`<PAGE_STATE>`, `<IDENTITY>`, `<MISSION>`, `<CURRENT_TASK>`) | ✅ (`COT_WORKFLOW` from fragments) | 2026-05-29 |
| `_VERIFIER_SYSTEM_PROMPT` | `backend/engine/verifier.py` | Verifier (screenshot + DOM judge) | ✅ (first block) | ✅ (last block) | ✅ (`<JUDGEMENT_RULES>`, `<OUTPUT_FORMAT>`) | N/A | 2026-05-29 |
| `_CLASSIFY_SYSTEM_PROMPT` | `backend/engine/supervisor.py` | Supervisor (intent classifier) | ✅ (via `prompt_fragments.GOLDEN_RULES`) | ✅ (`<CRITICAL_REMINDER>`) | ✅ (`<WORKER_TYPES>`, `<CLASSIFICATION_RULES>`) | N/A | 2026-05-29 |
| `BDD_NORMALIZER_PROMPT` | `backend/engine/prompts.py` | AC Parser (BDD normalizer) | ✅ (first block) | ✅ (last block) | ✅ (`<GOLDEN_RULES>`, `<RULES>`, `<MANDATORY_REASONING_WORKFLOW>`, `<INPUT_CONTEXT>`) | ✅ | 2026-05-29 |
| `JSON_COMPILER_PROMPT` | `backend/engine/prompts.py` | AC Parser (JSON compiler) | ✅ (first block) | ✅ (last block) | ✅ (`<GOLDEN_RULES>`, `<RULES>`, `<INPUT_CONTEXT>`) | N/A | 2026-05-29 |

### Shared Fragments (source: `backend/engine/prompt_fragments.py`)

| Fragment | Used By | Purpose |
|---------|---------|---------|
| `GOLDEN_RULES` | planner, verifier, supervisor, ac_parser | Identity + output format + DOM-over-vision contract |
| `COT_WORKFLOW` | planner | Forced chain-of-thought with ANTI-LOOP + STATE checks |
| `JSON_OUTPUT_REMINDER` | planner | Output schema recency anchor |

