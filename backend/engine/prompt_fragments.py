"""
vQA -- Shared Prompt Fragments
==============================
Module: backend/engine/prompt_fragments.py

Centralized store for critical prompt rules, workflows, and delimiters.
Ensures consistency across Planner, Verifier, and Parser agents.
Follows knowledge/prompt_audit_checklist.md.
"""

# --- SHARED DELIMITERS ---
DELIMITERS = {
    "RULES_START": "<RULES>",
    "RULES_END": "</RULES>",
    "CONTEXT_START": "<CONTEXT>",
    "CONTEXT_END": "</CONTEXT>",
    "EXAMPLES_START": "<EXAMPLES>",
    "EXAMPLES_END": "</EXAMPLES>",
    "DIARY_START": "<FAILURE_DIARY>",
    "DIARY_END": "</FAILURE_DIARY>",
    "HISTORY_START": "<EXECUTION_HISTORY>",
    "HISTORY_END": "</EXECUTION_HISTORY>",
    "THOUGHT_START": "<THOUGHT_PROCESS>",
    "THOUGHT_END": "</THOUGHT_PROCESS>",
}

# --- GOLDEN RULES (Primacy/Recency Anchoring) ---
# These are the absolute non-negotiables for the agent.
GOLDEN_RULES = """
<GOLDEN_RULES>
1. IDENTITY: You are vQA, an autonomous testing agent. You test the UI via DOM and VISION.
2. OUTPUT FORMAT: Output ONLY valid JSON. No preamble, no markdown fences, no conversational filler.
3. DOM OVER VISION: Trust the Deterministic Page State (DOM) over your visual interpretation if they conflict.
4. NO HALLUCINATION: Never invent UI elements, selectors, or data not present in the provided context.
5. ATOMICITY: Every action must be the SINGLE NEXT step toward the current AC goal.
</GOLDEN_RULES>
"""

# --- REASONING WORKFLOW (Chain-of-Thought) ---
# Forced reasoning steps to prevent impulsive/incorrect actions.
COT_WORKFLOW = """
<MANDATORY_REASONING_WORKFLOW>
BEFORE outputting your JSON payload, you MUST produce a <THOUGHT_PROCESS> block.
Follow these steps IN ORDER:

STEP 1: ANTI-LOOP CHECK
- Review the <EXECUTION_HISTORY>. 
- Did you perform the EXACT same action (same locator, same target) 2+ times consecutively?
- If YES: You are in a loop. You MUST change your strategy (different locator, different action).

STEP 2: DROPDOWN/PORTAL STATE
- Did you click a 'p-select', 'Sort By' button, or 'combobox' in the last 2 steps?
- If YES: The portal is OPEN. Do NOT click the trigger again (it will close the portal).
- Use `primeng_dropdown` or scope your click inside the visible portal container.

STEP 3: VIEW VERIFICATION
- Cite DOM EVIDENCE for your current view (e.g., "Sort By button is visible -> COMPACT VIEW").
- Ensure your locator strategy matches the verified view.

STEP 4: ACTION SELECTION
- Select the best action and locator based on confirmed Ground Truth (Registry > RAG > Guess).
</MANDATORY_REASONING_WORKFLOW>
"""

# --- OUTPUT SCHEMA REMINDERS ---
JSON_OUTPUT_REMINDER = """
<CRITICAL_OUTPUT_RULE>
Output a SINGLE JSON object. 
Ensure all strings are properly escaped.
Valid JSON ONLY.
</CRITICAL_OUTPUT_RULE>
"""
