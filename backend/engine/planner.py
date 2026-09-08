"""
vQA — Multimodal Planner Node
===============================
Module: backend/engine/planner.py

Implements the **SEE-THINK** phase of the see-think-act loop.

This node:
  1. Captures a screenshot and accessibility tree from the live browser
  2. Builds a multimodal prompt with the current AC step, role constraints,
     execution history, and the visual/structural signals
  3. Sends the prompt to Claude 3.5 Sonnet via AWS Bedrock
  4. Parses the LLM's response into a structured JSON action

The JSON action is written to ``VQAState.planned_action`` and consumed
by ``executor_node`` in the next graph step.

Architecture Context
--------------------
The planner is the "brain" of vQA.  It receives dual-grounded context
(screenshot + ARIA tree) so Claude can reason both visually and
structurally about the page.  The system prompt is personalised per-role
using constraints from ``roles.py``.

Prompt Structure
----------------
The message payload sent to Bedrock looks like::

    [system]
        You are vQA, an autonomous web testing agent.
        CURRENT GOAL: {AC step text}
        ROLE CONSTRAINTS: {role constraints}
        ACTION HISTORY: {execution log summary}
        SELF-HEAL CONTEXT: {last error, if retrying}

    [user - multimodal]
        [image] base64 screenshot of current page
        [text]  accessibility tree (ARIA roles + names)
        [text]  "Decide the single next action..."

    [assistant response]
        {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": "Submit All",
            "reasoning": "The form is complete. Submit All is enabled."
        }

LLM Response Format
--------------------
The planner expects Claude to return a JSON object with these fields:

    action : str
        One of: "click", "fill", "select_option", "check", "uncheck",
        "navigate", "wait", "verify", "scroll", "press_key", "done"

    strategy : str
        Playwright locator strategy: "get_by_role", "get_by_text",
        "get_by_label", "get_by_placeholder"

    role : str (optional)
        ARIA role for get_by_role (e.g. "button", "textbox", "link")

    name : str
        Element name / text / label to locate

    value : str (optional)
        Text to type for "fill" actions, option to select, key to press

    reasoning : str
        Why the LLM chose this action — displayed in the audit report

Dependencies
------------
  - ``langchain-aws``   — ChatBedrockConverse for Claude invocation
  - ``backend/browser/`` — screenshot + a11y extraction
  - ``backend/engine/roles.py`` — role constraint injection
  - ``backend/config.py`` — Bedrock model ID and region

See Also
--------
  - ``backend/engine/executor.py``   — consumes planned_action
  - ``backend/engine/evaluator.py``  — evaluates action result
  - ``backend/engine/graph.py``      — wires planner into the StateGraph
"""

import asyncio
import json
import logging
import re
import threading
from pathlib import Path as _Path
from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from backend.browser.accessibility import extract_accessibility_tree, extract_interactive_summary
from backend.browser.context import get_manager
from backend.browser.screenshot import capture_screenshot_b64
from backend.engine.culler import semantic_dom_cull
from backend.engine.state_tracker import get_tracker

# BUG-001 fix: logger must be defined BEFORE the try/except blocks below
# that reference it in their except clauses at module load time.
logger = logging.getLogger(__name__)

try:
    from backend.browser.set_of_marks import (
        capture_set_of_marks as _capture_som,
    )
    from backend.browser.set_of_marks import (
        format_som_prompt_block as _format_som_block,
    )
    from backend.browser.set_of_marks import (
        should_activate_som as _should_activate_som,
    )

    _SOM_AVAILABLE = True
except ImportError:
    _SOM_AVAILABLE = False
    logger.warning("set_of_marks module not found — SoM mode disabled")

# ── Vision-Language Model (VLM) coordinate-based SoM ────────────────────────
try:
    from backend.browser.vision_utils import (
        draw_marks_and_snapshot as _draw_marks_and_snapshot,
    )
    from backend.browser.vision_utils import (
        format_vision_mark_summary as _format_vision_mark_summary,
    )

    _VISION_AVAILABLE = True
except ImportError:
    _VISION_AVAILABLE = False
    logger.warning("vision_utils module not found — vision coordinate mode disabled")
from backend.config import settings
from backend.engine.metrics import RunMetrics
from backend.engine.roles import get_planning_constraints_prompt
from backend.engine.state import VQAState
from backend.engine.step_classifier import (
    StepType,
    classify_step,
    detect_primeng_components,
    get_step_type_label,
    get_step_type_rules,
)
from backend.engine.registry_first_gate import RegistryFirstGate  # T3-b FEAT-118
from backend.engine.validators import validate_planned_action
from backend.kb.loader import kb
from backend.kb.playwright_rag import playwright_rag
from backend.kb.selector_registry import selector_registry

try:
    from backend.kb.selector_rag import selector_rag  # FEAT-042: RAG-driven retrieval
except Exception:  # pragma: no cover
    selector_rag = None  # type: ignore
from backend.kb.unified_registry import unified_registry as _unified_registry

try:
    from backend.memory.skill_library import skill_library as _skill_library
except Exception:  # pragma: no cover
    _skill_library = None  # type: ignore
from backend.engine.recipe_runner import recipe_registry
from backend.kb.test_matcher import test_matcher
from backend.memory.persistent import persistent_memory

# Note: logger is defined earlier in this file (before optional import blocks)

# Lazy import: ASSET_INVENTORY is imported at first use to avoid
# circular import issues at module load time.
_ASSET_INVENTORY_CACHE: list[str] | None = None

# ---------------------------------------------------------------------------
# Per-call RAG result caches — keyed by query text, cleared when KB reloads.
# Eliminates redundant TF-IDF + file-read work on self-heal retries of the
# same AC step (retry 2, 3 ... all query the same step text as retry 1).
# ---------------------------------------------------------------------------
import time as _time_mod

_HG_FILE_CACHE: dict[str, str] = {}  # file_path → raw text
_HG_FILE_MTIME: dict[str, float] = {}  # file_path → mtime at last read
_HG_RESULT_CACHE: dict[str, str] = {}  # (step, ticket_id) → parsed result, 60 s TTL
_HG_RESULT_CACHE_TS: dict[str, float] = {}
_HG_RESULT_CACHE_TTL: float = 60.0  # seconds

_PW_RAG_CACHE: dict[str, str] = {}  # step_text → playwright_rag result
_SEL_REG_CACHE: dict[str, str] = {}  # step_text → selector_registry result (fallback)
_SEL_RAG_CACHE: dict[str, str] = {}  # step_text → selector_rag result (FEAT-042)
_SKILL_CACHE: dict[str, str] = {}  # step_text → skill_library result

# FEAT-042 Phase 4: per-call RAG telemetry accumulator.
# The prompt-builder functions (_build_system_prompt, _build_system_prompt_v2)
# append one dict per injection site call here. planner_node_inner harvests
# it and includes it in the returned rag_selector_stats partial state update.
# Cleared at the start of each planner_node call.
_RAG_TELEMETRY: list[dict] = []


def clear_rag_caches() -> None:
    """
    BUG-002 fix: Clear all module-level RAG result caches.

    Must be called at the start of each run to prevent stale results from
    a previous run contaminating the current one. The caches are keyed by
    (step_text, ticket_id) and step_text respectively — if two runs test
    the same ticket, the second run could receive cached results from the
    first run's KB state (which may have been mutated by HITL learning).
    """
    _HG_FILE_CACHE.clear()
    _HG_FILE_MTIME.clear()
    _HG_RESULT_CACHE.clear()
    _HG_RESULT_CACHE_TS.clear()
    _PW_RAG_CACHE.clear()
    _SEL_REG_CACHE.clear()
    _SEL_RAG_CACHE.clear()  # FEAT-042: clear RAG-driven selector cache
    _SKILL_CACHE.clear()
    _RAG_TELEMETRY.clear()  # FEAT-042 Phase 4: clear per-run telemetry accumulator
    logger.debug("RAG caches cleared for new run")


# ---------------------------------------------------------------------------
# FEAT-042 Phase 4: Auto-rebuild trigger at module load
# ---------------------------------------------------------------------------
# Checks if the selector RAG index is stale on every module load and fires
# a background rebuild if needed. Non-blocking — does not delay module import
# or first planner call. Implements AC-LIFECYCLE-1 (auto-rebuild on KB update).
# ---------------------------------------------------------------------------


def _check_and_rebuild_selector_rag_if_stale() -> None:
    """
    Trigger a background SelectorRAG rebuild if the index is stale.

    Called once at module load time.  Uses rebuild_in_background() so that
    the main thread is never blocked — the rebuild runs in a daemon thread
    and completes before the next planner call (index build ≤30s per AC-INDEX-1).
    """
    if selector_rag is not None:
        try:
            selector_rag.rebuild_in_background()
            logger.debug("FEAT-042: SelectorRAG stale-check dispatched (background)")
        except Exception as _e:  # pragma: no cover
            logger.warning("FEAT-042: SelectorRAG background rebuild check failed: %s", _e)


# Fire at module import time (non-blocking — daemon thread)
_check_and_rebuild_selector_rag_if_stale()


# ---------------------------------------------------------------------------
# Dropdown Registry — Proactive Option Injection (TASK-013)
# ---------------------------------------------------------------------------

_DROPDOWN_REGISTRY_LOCK = threading.Lock()
_DROPDOWN_REGISTRY: dict[str, list[str]] | None = None


def _load_dropdown_registry() -> dict[str, list[str]]:
    """
    Load the dropdown registry from knowledge/dropdown_registry.json.
    """
    global _DROPDOWN_REGISTRY
    if _DROPDOWN_REGISTRY is None:
        with _DROPDOWN_REGISTRY_LOCK:
            if _DROPDOWN_REGISTRY is None:
                try:
                    root = _Path(__file__).parent.parent.parent
                    path = root / "knowledge" / "dropdown_registry.json"
                    with open(path, "r") as f:
                        _DROPDOWN_REGISTRY = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load dropdown registry: {e}")
                    _DROPDOWN_REGISTRY = {}

    return _DROPDOWN_REGISTRY


# Eagerly load registry at module import time (AC-CODE-4)
_load_dropdown_registry()


def _get_matching_options(step_text: str, state: VQAState | None = None) -> str:
    """
    Scan the AC step text AND the accessibility tree for known dropdown labels
    and return a formatted string of valid options for the prompt (TASK-013).
    """
    registry = _load_dropdown_registry()
    matches = {}

    # Pre-tokenize the step text for keyword matching (AC-CODE-1 moved import to top)
    step_words = set(re.findall(r"[a-z]{2,}", step_text.lower()))

    def _is_match(label: str, text_words: set[str], full_text: str) -> bool:
        label_lower = label.lower()
        # 1. Direct substring match (highest confidence)
        if label_lower in full_text.lower():
            return True
        # 2. Word overlap match (e.g., "Ad Type" matches "select an ad type")
        label_words = set(re.findall(r"[a-z]{2,}", label_lower))
        if label_words and label_words.issubset(text_words):
            return True
        # 3. Stem-normalized word overlap (TASK-014 Phase 3.2)
        #    Handles plural/singular: "accounts" matches "account",
        #    "service" matches "services". Simple suffix strip — no
        #    external NLP dependency needed for this domain.
        if label_words:

            def _stem(w: str) -> str:
                """
                Minimal English stemmer: strip trailing 's' (>3 chars).
                Note: This is imprecise (e.g. 'status' -> 'statu', 'services' -> 'service')
                but sufficient for matching domain dropdown labels without adding NLTK (AC-CODE-3).
                """
                if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
                    return w[:-1]
                return w

            stemmed_label = {_stem(w) for w in label_words}
            stemmed_text = {_stem(w) for w in text_words}
            if stemmed_label and stemmed_label.issubset(stemmed_text):
                return True
        # 4. Concatenated word detection (TASK-014 Phase 3.2)
        #    Checks if all label words appear joined in the full text,
        #    e.g., "adtype" in step matches "Ad Type" label.
        if len(label_words) >= 2:
            concat = "".join(sorted(label_words))  # canonical order
            full_lower = full_text.lower()
            # Simplification (AC-CODE-2): Explicit checks for 2-word labels avoiding O(n^2)
            words_list = list(label_words)
            if len(words_list) == 2:
                if words_list[0] + words_list[1] in full_lower or words_list[1] + words_list[0] in full_lower:
                    return True
            # For 3+ word labels, just check the sorted concatenation
            elif len(words_list) > 2 and concat in full_lower:
                return True
        return False

    # 1. Scan the AC step text
    for label, options in registry.items():
        if _is_match(label, step_words, step_text):
            matches[label] = options

    # 2. Scan the Accessibility Tree (TASK-013)
    if state and state.get("current_accessibility_tree"):
        tree = state["current_accessibility_tree"].lower()
        tree_words = set(re.findall(r"[a-z]{2,}", tree))
        for label, options in registry.items():
            if _is_match(label, tree_words, tree):
                matches[label] = options

    # 3. Scan Transient Page Text (to catch labels in modals/toasts)
    if state and state.get("transient_page_text"):
        transient = state["transient_page_text"].lower()
        transient_words = set(re.findall(r"[a-z]{2,}", transient))
        for label, options in registry.items():
            if _is_match(label, transient_words, transient):
                matches[label] = options

    if not matches:
        return ""

    formatted_matches = []
    for label, options in matches.items():
        options_str = ", ".join(f'"{o}"' for o in options)
        formatted_matches.append(f"  • {label}: [{options_str}]")

    return (
        "\n<injected_options>\n"
        "VALID DROPDOWN OPTIONS (proactive injection):\n"
        "The following options are valid for the dropdowns mentioned in your goal.\n"
        "USE these exact values for 'select_option' or 'primeng_dropdown' actions:\n"
        + "\n".join(formatted_matches)
        + "\n</injected_options>\n"
    )


def _get_metrics_for_run(run_id: str):
    """Get the RunMetrics instance for a run (lazy import to avoid circular deps)."""
    try:
        from backend.engine.metrics import get_run_metrics

        return get_run_metrics(run_id)
    except Exception:
        return None


def _get_asset_filenames() -> list[str]:
    """Return the list of available test asset filenames."""
    global _ASSET_INVENTORY_CACHE
    if _ASSET_INVENTORY_CACHE is None:
        try:
            from backend.engine.executor import ASSET_INVENTORY

            _ASSET_INVENTORY_CACHE = list(ASSET_INVENTORY.keys())
        except ImportError:
            _ASSET_INVENTORY_CACHE = []
    return _ASSET_INVENTORY_CACHE


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Conditional rule categories
# ---------------------------------------------------------------------------
# Instead of dumping all 14 rules into every prompt (causing attention dilution),
# rules are categorized and only injected when the current AC step matches.
# This cuts the system prompt from ~240 static lines to ~60-80 context-appropriate lines.

# Core rules — ALWAYS injected (format, selectors, basic interaction)
_CORE_RULES = """\
1. Return ONLY a valid JSON object — no markdown, no explanation outside JSON.
   The JSON MUST include "observation" and "thought" keys for your reasoning process,
   in addition to the "action" and other locator fields.

2. CONCISENESS RULE: Your "reasoning" string MUST be fewer than 100 characters.
   Be extremely brief. NEVER write paragraphs in reasoning. Wrong: "I can see the
   page has loaded and the form is now visible with all required fields..."
   Correct: "Form visible — filling email field."

3. IDEMPOTENCY RULE: Before navigating or opening a panel/modal, CHECK THE SCREEN.
   If the target panel, modal, section, or page information is ALREADY visible
   on the current screenshot or accessibility tree, DO NOT click anything to
   open it again. Immediately return {{"action": "done", "reasoning": "Already visible"}}.
   Applies to: spot detail panels, order panels, modals, login state, page loads.

4. LOCATOR STRATEGY — Match the element type to the correct Playwright method:
   a) BUTTONS     → get_by_role("button", name="...")
   b) TEXT INPUTS → get_by_role("textbox", name="...") or get_by_label
   c) LINKS in lists/tables → ⚠️ get_by_text ONLY. NEVER get_by_role(link) for
      table rows — Angular does not expose link ARIA roles on these.
   d) DROPDOWNS   → get_by_role("combobox") or get_by_label
   e) TABS        → get_by_role("tab", name="...")
   f) CHECKBOXES  → get_by_role("checkbox", name="...")
   g) ANY OTHER   → get_by_text

5. Prefer exact name matches visible on screen. Never guess names not in the a11y tree.
6. For text inputs, use "fill" action with the value in the "value" field.
7. For dropdowns, use "select_option" or click the dropdown then click the option.
8. If the current AC step appears ALREADY SATISFIED, return {{"action": "done", "reasoning": "..."}}.
9. NEVER make up selectors — only use roles and names visible in the accessibility tree.
10. BUTTON RULE — NEVER use get_by_role('button') WITHOUT a name. ALWAYS provide visible text.
11. STRICT MODE — If a name appears multiple times, use get_by_role with a specific role.
    When you get a strict mode violation, make your locator MORE SPECIFIC:
    - Add exact role: get_by_role("button", name="exact text")
    - Use a parent chain: page.locator(".specific-panel").get_by_text("Submit")
    - NEVER use generic get_by_text for common words ("Save", "Cancel", "Notes")
12. SCROLL RULE — NEVER use "scroll" to find items in tables or lists. vSuite tables use PAGINATION
    (next/prev page buttons at the bottom). Use click on the next-page ">" button instead.

13. **NEGATIVE TESTING RULE** — If an Acceptance Criterion requires entering INVALID data,
    wrong credentials, or verifying an ERROR STATE, your goal is to TRIGGER that error — not fix it.
    DO NOT attempt to "correct" bad data, re-enter valid credentials, or force a successful outcome.
    Follow the AC strictly and expect the failure/error response.
    Example: AC says "enter invalid password and verify error message" → enter the invalid password,
    then return done. Do NOT then enter the correct password.

14. **DROPDOWN TOGGLE GUARD** — CRITICAL, read your <action_history> BEFORE planning:
    After you click a combobox, p-select, or dropdown trigger, IT IS NOW OPEN.
    If the previous action in <action_history> was a click on a dropdown/combobox/p-select,
    your IMMEDIATE next action MUST be to click an option INSIDE the opened panel.
    DO NOT click the dropdown trigger again — that would CLOSE the menu and create
    an infinite open/close toggle loop.
    Signals that the dropdown is open: .p-dropdown-panel, .p-listbox, .p-overlay-content,
    .po-sorting-dropdown-panel, or .p-select-overlay is visible in the element tree.
    If you see any of those selectors in the tree → DO NOT re-click the trigger,
    click a list item (li, .p-select-option, get_by_text('<option label>')) instead.

15. **P-SELECT / COMPOUND COLUMN RECIPE DISABLE** — ZERO EXCEPTIONS:
    DO NOT emit action="recipe" for any interaction that involves a PrimeNG
    p-select dropdown (e.g. p-select#header-sort-drop-down-duedaysCol or
    p-select#header-sort-drop-down-startendCol).
    For compound-column sorts (Due/Days, Start/End) you MUST use native atomic
    Playwright click actions following RULE 2 in TABLE SORTING RULES:
      Step 1 — click  → css_selector → "p-select#header-sort-drop-down-duedaysCol"
      Step 2 — wait   → 500
      Step 3 — click  → css_selector → ".po-sorting-dropdown-panel li:has(.pi-sort-up)"
    Using a recipe for p-select interactions is FORBIDDEN until the recipe engine
    is updated to handle PrimeNG v19 overlay portals.

16. **ANTI-LOOP CIRCUIT BREAKER (CRITICAL)**:
    If your last 3 attempts at the SAME GOAL have resulted in a loop (no visual
    state change despite successful mechanical actions), you MUST:
    a) STOP repeating the same locator strategy.
    b) Switch from semantic (get_by_role) to structural (vqa_id / css_selector).
    c) Or emit a 'wait' action (1500ms) to let the UI stabilize.
    d) If you are absolutely stuck, emit 'done' with reasoning explaining the blockage.

17. **SELECTOR INTEGRITY (FEAT-066)** — MANDATORY FOR ALL ACTIONS:
    a) BAN DYNAMIC IDs: NEVER use framework-generated dynamic IDs in CSS selectors or IDs.
       Specifically, matching patterns like `ui-tabpanel-\\d+` or `p-overlay-\\d+` is FORBIDDEN.
    b) BAN DEEP-DOM CHAINS: NEVER use fragile nested element chains like `div:nth-child(3) > span:nth-child(1)`.
    c) PRIORITIZE SEMANTIC SELECTORS: Use `getByRole`, `getByText`, or `getByLabel` exclusively.
    d) USE TESTING ATTRIBUTES: If a semantic role is ambiguous, check the accessibility tree
       for attributes starting with `vqa_` (e.g. `vqa_id="submit-btn"`). These are stable
       and intended for your use.

18. **PREDICTIVE STATE VERIFICATION (MANDATORY)**:
    You MUST provide a clear, concise 'state_expectation' field with every action.
    This field must describe the immediate visible or DOM result that you expect
    to see on screen once the action completes.
    Examples:
    - Click 'Login' button -> "URL contains /dashboard" or "Username is visible"
    - Click 'Create Folder' trigger -> "Dialog 'Create Folder' is visible"
    - Fill 'Project Name' -> "Input field has value 'Project Name'"
    Used for immediate fast-fail verification bypassing slow timeouts.

═══════════════════════════════════════════════════════════════
⚡ RECIPE MANDATE — HIGHEST PRIORITY RULE:
═══════════════════════════════════════════════════════════════
If a ⚡ ACTION RECIPES AVAILABLE block appears in this prompt:
  • You MUST emit action="recipe" with recipe_name and recipe_params.
  • Planning individual clicks (click, get_by_role, get_by_text) for that
    component is FORBIDDEN.
  • The recipe handles ALL sub-steps internally — do NOT plan the open AND
    close separately.
  • supply recipe_params as shown in the recipe's example JSON exactly.
    REPLACE <param_name> placeholders with the actual values from the AC step.
  • DO NOT use action="click" or action="fill" for interactions that have a recipe.
  • If you have already tried a recipe and it failed, emit it AGAIN with
    CORRECTED recipe_params. Do not silently fall back to individual clicks.

⛔ RECIPE EXCEPTION — p-select DROPDOWNS (ZERO EXCEPTIONS):
  NEVER use action="recipe" for p-select, p-dropdown, or any compound-column
  sort dropdown (e.g. p-select#header-sort-drop-down-duedaysCol).
  These must ALWAYS use native atomic click actions (see TABLE SORTING RULES).
═══════════════════════════════════════════════════════════════
⛔ CRITICAL GRID RULE — ZERO EXCEPTIONS:
═══════════════════════════════════════════════════════════════
When interacting with a p-table (Production Orders, MyBox, Voice Requests, or ANY grid/table):
  • DO NOT use the 'scroll' action. EVER. Tables use PrimeNG virtual pagination.
    Scrolling will NOT reveal more rows — it just moves the viewport.
  • If a DATA ROW (client, order) is NOT visible on the current page:
    CLICK the Next Page button: {{"action": "click", "strategy": "get_by_role", "role": "button", "name": "Next Page"}}
  • COLUMN HEADERS (th elements like CLIENT, Due/Days, Start/End) are ALWAYS
    visible in the header row — they do NOT paginate. NEVER click Next Page
    to find a column header. Use the correct selector from the KB knowledge.
  • If the Next Page button is disabled, you have reached the last page.
    Check if a status filter or search input can narrow the results.
  • The pagination buttons are at the BOTTOM of the table (< 1 2 3 ... >).
═══════════════════════════════════════════════════════════════
"""

# Login-specific rules — injected when step mentions login/credentials/email/password
_LOGIN_RULES = """\
LOGIN RULES:
STEP 1 — CHECK IF ALREADY LOGGED IN (do this FIRST, before trying to fill fields):
  If ANY of these are true, you are ALREADY logged in — return done IMMEDIATELY:
  - A username appears in the top-right corner (e.g. "Demo Account Executive")
  - The URL is NOT /login or /auth — you can see dashboard content
  - Interactive elements include "MyBox", "Production Orders", "New Request +"
  - The screenshot shows the vProMedia dashboard, NOT a login form
  In this case: {{"action": "done", "reasoning": "Already logged in as [visible name]."}}

STEP 2 — ONLY if you are on the login page (URL ends in /login, Email/Password fields visible):
  - The login form uses PLACEHOLDER-based labels, NOT aria-labels.
    ALWAYS use get_by_placeholder for login fields:
      Email:    {{"action":"fill","strategy":"get_by_placeholder","name":"Email","value":"..."}}
      Password: {{"action":"fill","strategy":"get_by_placeholder","name":"Password","value":"..."}}
    get_by_label('Email') and get_by_role('textbox', name='Email') WILL FAIL.
"""

# Logout-specific rules — injected when step mentions logout/switch/sign out
_LOGOUT_RULES = """\
LOGOUT / ROLE-SWITCH RULES:
- NEVER click 'Logout' directly. The Logout link is HIDDEN inside a user dropdown.
  You MUST open the dropdown FIRST by clicking the username button in the top-right:
    Step A: {{"action":"click","strategy":"get_by_role","role":"button","name":"<current username>"}}
    Step B: {{"action":"click","strategy":"get_by_text","name":"Logout"}}
- Do NOT use get_by_text('<username>') — strict mode violation (multiple matches).
- Do NOT click Logout before opening the dropdown — it is not visible.

MULTI-ROLE TEST HANDLING (when AC says "log in as <role>" or "navigate to login page as <role>"):
- If you are CURRENTLY LOGGED IN as a DIFFERENT user than the AC requires:
    1. You MUST log out first (Step A + Step B above).
    2. After logout, the login page will appear. THEN fill email and password for the new role.
- If you are already on the login page AND already logged out: proceed directly to fill email.
- NEVER emit "done" for a login step if you are already logged in as the WRONG user.
  Check the username or account indicator shown in the UI. If it does not match the required role, LOG OUT first.
- The AC will explicitly say which role/user to log in as — use the credentials for that role exactly.
"""

# Table/click rules — injected when step mentions click/open/client/row/table/order/find/spot/producing
_TABLE_CLICK_RULES = """\
TABLE / LIST NAVIGATION RULES (vProMedia Angular):

READING THE PAGE CONTEXT:
The "VISIBLE PAGE TEXT" section below shows you:
  - TABLE COLUMNS — the column headers
  - ROW — each visible row's cell content (client, title, status, etc.)
  - TABLE SUMMARY — how many rows are on this page AND which statuses exist
  - PAGINATION — current page number and whether Next/Prev buttons are enabled
USE THIS DATA to make smart decisions about what to do next.

FINDING ITEMS BY STATUS (decision tree):
1. Read the TABLE SUMMARY line — it tells you exactly which statuses are on this page
   Example: "TABLE SUMMARY: 3 rows visible. Statuses found: Needs Scheduling (2), Needs Dubbing (1)."
2. If the status you need (e.g. "Needs Producing") IS listed → find the matching ROW → click its CLIENT NAME
3. If the status you need is NOT listed AND PAGINATION shows "Next: ENABLED" → click Next Page to check the next page
4. If the status you need is NOT listed AND PAGINATION shows "Next: disabled" → you've checked all pages.
   Consider: is the status filter set correctly? Does the current view show the right data?
5. NEVER use "scroll" to find more rows — tables use PrimeNG pagination, scroll won't help.

TABLE CLICK STRATEGY:
- Clicking a client name, spot name, or any row in MyBox / Production Orders:
  ALWAYS use get_by_text. Example: {{"action":"click","strategy":"get_by_text","name":"Zombieland"}}
- NEVER use get_by_role("link") for table rows — Angular doesn't expose ARIA link roles.
- Status badges (Needs Producing, Needs Writing) are DISPLAY-ONLY text — not clickable buttons.
  To OPEN a spot, click the CLIENT NAME or SPOT NAME in that row, not the status text.

PAGINATION:
- To go to the next page: {{"action":"click","strategy":"get_by_role","role":"button","name":"Next Page"}}
- Or click the ">" arrow at the bottom of the table
"""

# Status/dropdown rules — injected when step mentions status/dropdown/change/select
_STATUS_RULES = """\
STATUS / DROPDOWN RULES:
- Status badges in list views are READ-ONLY display labels, not buttons.
  NEVER use get_by_role("button", name="Needs Producing") — it will always timeout.
- To CHANGE a spot's status: first OPEN the order (click client name), then
  use the status dropdown inside: {{"action":"select_option","role":"combobox","name":"Status","value":"New Value"}}
- ⛔ VERBATIM ONLY CONSTRAINT: ONLY select options that appear verbatim in the ARIA tree or DOM snapshot (under <page_state>).
  If the dropdown options are not visible in the ARIA tree (e.g., lazy-loaded), do NOT guess. Instead, click the dropdown trigger to open it and return 'done' to trigger a re-snapshot, then select the option in the next step.
"""

# Voice request workflow rules — injected when step mentions voice/add voice/prod notes/needs producing
_VOICE_WORKFLOW_RULES = """\
═══════════════════════════════════════════════════════════════
vProMedia VOICE-REQUEST & PRODUCTION-NOTES WORKFLOW RULES:
═══════════════════════════════════════════════════════════════

⚠️  CRITICAL — DO NOT OPEN/CLICK INTO THE SPOT.
    All production and voice-request actions happen DIRECTLY IN THE LIST VIEW.
    There is NO need to navigate into the spot detail page.

HOW THE PRODUCTION ORDERS LIST WORKS:
- Each row in the Production Orders list shows a spot.
- The "Status & Approvals" column shows the status text, e.g. "Needs Producing".
- The "Files" column on the same row contains inline action links:
    • "Add Prod Notes"  — adds production notes to that spot
    • "Add Voice"       — opens the Add Voice panel for that spot
  These links are visible WITHOUT clicking into the spot.

FINDING A "NEEDS PRODUCING" SPOT:
1. Look at the visible rows in the list.
2. Find a row where the status column contains "Needs Producing".
3. You do NOT need to click the client name or open the spot — stay on the list view.
4. If no row shows "Needs Producing" status, use the status filter dropdown to
   change the view to "Needs Producing" (the filter combobox near the top of the list).

ADDING PRODUCTION NOTES (inline, no spot navigation required):
1. On the row that shows "Needs Producing", look in the Files column.
2. Click "Add Prod Notes" directly in that row — this opens an inline notes panel.
3. Do NOT click the client name first.

ADDING A VOICE REQUEST (inline, no spot navigation required):
1. On the row that shows "Needs Producing", look in the Files column.
2. The Files column may be off-screen to the RIGHT. If the SoM mark for "Add Voice"
   has a negative or near-zero Y coordinate, the element is outside the viewport —
   scroll the table RIGHT or use get_by_text('Add Voice').first instead of coordinate click.
3. Click "Add Voice" directly in that row — use get_by_text('Add Voice').first.
   NEVER use coordinate_action for "Add Voice" if its Y coordinate is <= 0.
4. Do NOT click the client name or navigate into the spot.
5. CORRECT selector: get_by_text('Add Voice') with .first to avoid strict-mode.

VERIFYING A FORM OR PANEL IS OPEN:
- Use the LLM verifier (visual_check) to confirm a modal/sidebar opened, OR
- Use element_visible with the container's Angular component tag (e.g. "app-my-form").
  If you do not know the exact selector, use the LLM verifier — it can see the screenshot.
- Never guess a CSS class like ".voice-request-form" — rely on what the DOM inspector shows.

AFTER CLICKING "ADD VOICE" — EXACT FORM FIELDS IN THE SIDEBAR:
The Add Voice sidebar is a FORM. You MUST fill ALL required fields before clicking ADD PART
or the form will not save (it may show validation errors or silently do nothing).

REQUIRED FIELDS (must be filled — form blocks submission without them):
  1. "Select Talent Pool"  (REQUIRED) — combobox. Click it, then click the pool name.
  2. "Select Talent"       (REQUIRED) — combobox. Appears after selecting a pool. Click it, then click the talent name.
  3. "Notes"              (REQUIRED) — textbox. Must contain text. Fill with any descriptive notes.
  4. "Due Date"           (REQUIRED) — date input. Must be set. Click it and select or type a date.

OPTIONAL FIELDS:
  - None currently known.

❌ THERE IS NO "Part" OR "Part 1" FIELD. Do not try get_by_role(textbox, name='Part') — it does not exist.
❌ Do not try get_by_label('Part') — it does not exist.
❌ The "Voice Parts" heading text is NOT a field — it is a section title (a <div class="subtitle">).

CORRECT SEQUENCE for Add Voice (complete all steps before clicking ADD PART):
  Step A: click  → get_by_role(combobox, name='Select Talent Pool')
  Step B: click  → get_by_text('<pool name>')               (e.g. 'Demo Voice Pool')
  Step C: click  → get_by_role(combobox, name='Select Talent')
  Step D: click  → get_by_text('<talent name>')              (e.g. 'Demo Voice Talent')
  Step E: click  → get_by_role(textbox, name='Notes')        (focus the field first)
  Step F: fill   → get_by_role(textbox, name='Notes')  value='Test voice notes'
  Step G: click  → get_by_role(textbox, name='Due Date')     (focus the date field)
  Step H: fill   → get_by_role(textbox, name='Due Date')  value='<date in MM/DD/YYYY>'
            OR press_key 'Tab' to auto-fill / accept today's date
  Step I: click  → get_by_role(button, name='ADD PART')

AFTER CLICKING "ADD PART":
- If successful: the sidebar closes and the Files column shows the voicer name with "(waiting)".
- If validation fails: the form stays open with red border/error on the missing field.
  → Identify the highlighted field, fill it, then click ADD PART again.
- Do NOT click ADD PART more than once in the same state — fill missing fields first.

═══════════════════════════════════════════════════════════════
DOMAIN KNOWLEDGE — BLOG NOTES & COMMENTS:
═══════════════════════════════════════════════════════════════
⚠️ 'Blog notes' and 'Comments' are located at the BOTTOM of a spot's details
   panel or in a dedicated 'Voice Request Blog' section. They are NOT found by
   clicking voice talent names or navigating to a separate page.
⚠️ If asked to verify blog notes, scroll to the BOTTOM of the details panel.
⚠️ Do NOT repeatedly click voice talent names to find them — that will NOT
   reveal the blog/comment section.
⚠️ The blog/comment section appears BELOW the voice parts list in the panel.
═══════════════════════════════════════════════════════════════
"""

# Navigation rules — injected when step mentions navigate/url/go to/already on
_NAVIGATION_RULES = """\
NAVIGATION RULES:
- When the AC step says "navigate to the testing URL" and you are ALREADY on the target
  URL ({target_url}), return {{"action": "done", "reasoning": "Already on target URL"}}.
- ONLY use the navigate action with the EXACT URL: {target_url} — NEVER invent URLs.
- WAIT VALUE: When using wait, pass a plain integer (ms): {{"action": "wait", "value": 2000}}
"""

# localStorage / sessionStorage rules — injected when step mentions JWT, token, localStorage
_LOCAL_STORAGE_RULES = """\
═══════════════════════════════════════════════════════════════
⛔ localStorage / sessionStorage RULE — ZERO EXCEPTIONS:
═══════════════════════════════════════════════════════════════
Browser storage keys (vc2JWT, authToken, sessionId, etc.) are NEVER visible
in the DOM. You CANNOT verify them with:
  - verify + get_by_text('vc2JWT')       ← WRONG, will always fail
  - verify + get_by_role(..., name=...) ← WRONG
  - click or fill on a storage key      ← WRONG

The ONLY correct action for a localStorage assertion is:
  {{"action": "done", "reasoning": "localStorage.getItem('vc2JWT') was evaluated programmatically by the verifier. No DOM interaction needed."}}

The verifier will automatically call localStorage.getItem() via JavaScript.
Your job is ONLY to emit "done" with reasoning that explains what the expected
state is (absent or present). Never attempt a DOM-based locator for storage keys.
═══════════════════════════════════════════════════════════════
"""

# File upload rules — injected when step mentions upload/file/browse/attach
_FILE_UPLOAD_RULES = """\
═══════════════════════════════════════════════════════════════
⛔ FILE UPLOADS RULE — ZERO EXCEPTIONS:
═══════════════════════════════════════════════════════════════
NEVER use the 'click' action on a 'Browse', 'Upload', or 'Choose File' button.
This opens a native OS file dialog that Playwright CANNOT interact with.
You MUST use the set_input_files action targeting the underlying <input type="file"> element.

Correct usage:
  {{"action": "set_input_files", "selector": "p-fileupload input[type='file']", "value": "Client Logo.jpg"}}
  {{"action": "set_input_files", "selector": "input[type='file']", "value": "Voice Part 1.mp3"}}

After upload: wait 1000ms, then select File Type from the p-dropdown if required.

Available test files: {asset_list}
═══════════════════════════════════════════════════════════════
"""

# Table sort rules — injected when step mentions sort/ascending/descending/oldest/newest
_TABLE_SORT_RULES = """\
═══════════════════════════════════════════════════════════════
⛔ TABLE SORTING RULES — vSuite Production Orders (ZERO EXCEPTIONS)
═══════════════════════════════════════════════════════════════

── RULE 0: Which view am I in? ─────────────────────────────────
BEFORE sorting, check whether you are in List view or Compact view:
  • List view:    columns are clickable <th> elements (or dropdown inside <th>)
  • Compact view: column <th> are NOT clickable — use the sort-btn popover ONLY
  How to detect: If button#sort-btn is visible → Compact view. Otherwise → List view.

── RULE 1: List View — Standard th columns ─────────────────────
Columns CLIENT and STATUS/TASKS have a clickable <th>.
Click selector:  css_selector → "th.po-col-clientCol"   (for CLIENT)
                 css_selector → "th.po-col-statusCol"   (for STATUS/TASKS)
Do NOT use get_by_text('CLIENT') — it matches a hidden span and ALWAYS times out.

── RULE 2: List View — Dropdown columns (Due/Days and Start/End) ─
⚠ CRITICAL: Due Date, Days, Start Date, End Date, Submitted On are INSIDE
  a PrimeNG p-select dropdown — they are DISABLED to direct th clicks.
  You CANNOT sort them by clicking the th element.
  ALWAYS use a SINGLE primeng_dropdown action — this is atomic (open + wait +
  click in one step) and avoids the race condition where the panel closes
  between separate click actions.

  For Due/Days column:
    {{"action": "primeng_dropdown",
      "trigger_selector": "th.po-col-duedaysCol p-select",
      "target_text": "Due Date",
      "portal_class": ".po-sorting-dropdown-panel"}}

  For Start/End column:
    {{"action": "primeng_dropdown",
      "trigger_selector": "th.po-col-startendCol p-select",
      "target_text": "Start",
      "portal_class": ".po-sorting-dropdown-panel"}}

  Valid target_text values for Due/Days panel:
    "Due Date"    → sort by due date
    "Days"        → sort by days elapsed
    "Submitted On" → sort by submission date

  Valid target_text values for Start/End panel:
    ⚠ "Start"    → sort by start date  (NOT "Start Date" — the option label is just "Start")
    ⚠ "End"      → sort by end date    (NOT "End Date"   — the option label is just "End")

  Direction: calling primeng_dropdown with the SAME target_text AGAIN toggles
  ascending ↔ descending — one primeng_dropdown call = one direction toggle.
  DO NOT split into separate click steps — the panel will close between them.

── RULE 3: Compact View Navigation ──────────────────────────────
⚠ ALWAYS use the recipe for view switching (handles verification automatically):
  recipe: compact_view_navigate
  params: {{"view_label": "Compact", "view_css_class": "compact"}}
  (or "List"/"modern", "Minimal"/"minimal" for other views)

Manual fallback (only if recipe dispatch unavailable):
  Step 1 — Click the Settings button (opens a p-menu popup):
    {{"action": "click", "strategy": "css_selector", "name": "button#settings-btn"}}
  Step 2 — Click the view name using get_by_text (NEVER css_selector li#compact_listview):
    {{"action": "click", "strategy": "get_by_text", "name": "Compact"}}
  ⚠ NEVER click Settings button more than ONCE per attempt.
     If the popup is already open, click the menu item directly (get_by_text).

VERIFICATION — use persistent div class (li#...active is WRONG — menu closes immediately):
  Compact active: selector_hint: "div.po-table-wrapper.compact"
  List active:    selector_hint: "div.po-table-wrapper.modern"
  Minimal active: selector_hint: "div.po-table-wrapper.minimal"


── RULE 4: Compact View Sort ────────────────────────────────────
In Compact view, use the sort-btn popover (NOT column headers):
  ALWAYS use a single primeng_dropdown action — the .sort-panel closes between separate
  click steps just like the list view panels.  portal_class is ".sort-panel" (NOT
  ".po-sorting-dropdown-panel" — that is only for list view column header dropdowns).

  {{"action": "primeng_dropdown",
    "trigger_selector": "button#sort-btn",
    "target_text": "Client",
    "portal_class": ".sort-panel"}}

  ⚠ OPTION TEXT MAP (exact labels inside .sort-panel — do NOT guess):
    AC "CLIENT"            → target_text: "Client"
    AC "Title"             → target_text: "Title"
    AC "Status"            → target_text: "Status"
    AC "Due Date" / "Days" → target_text: "Due / Days"   ⚠ NOT "Due Date"
    AC "Submitted On"      → target_text: "Submit Date"

  ⚠ "Due / Days" has a space before the slash — target_text must be EXACT: "Due / Days"
  Clicking an already-active sort item TOGGLES direction (ascending ↔ descending).

── RULE 5: Verification (all views) ─────────────────────────────
NEVER use a standard 'verify' action to check if a table is sorted.
Use the verify_table_sort action instead:
  {{"action": "verify_table_sort", "column": "<column_name>", "order": "ascending"}}
This action reads and compares actual DOM cell values in Python — not the LLM.
═══════════════════════════════════════════════════════════════
"""

# Rule category → (trigger keywords, rule text)
_RULE_CATEGORIES: list[tuple[list[str], str]] = [
    (["login", "sign in", "log in", "credentials", "email field", "password field"], _LOGIN_RULES),
    (
        [
            "logout",
            "log out",
            "sign out",
            "switch account",
            "switch to",
            "switch user",
            "switch back",
            "login page as",
            "navigate to login page as",
            "different role",
            "different user",
            "log in as",
            "as a different",
        ],
        _LOGOUT_RULES,
    ),
    (
        [
            "click",
            "open",
            "client",
            "row",
            "table",
            "order",
            "spot",
            "mybox",
            "my box",
            "find",
            "producing",
            "dubbing",
            "writing",
            "scheduling",
            "status",
            "pagination",
            "page",
        ],
        _TABLE_CLICK_RULES,
    ),
    (["status", "dropdown", "change status", "select", "needs producing", "needs dubbing"], _STATUS_RULES),
    (["navigate", "url", "go to", "already on", "testing url", "target url"], _NAVIGATION_RULES),
    # Voice workflow — fires for any AC step in the voice-request test suite
    (
        [
            "add voice",
            "prod notes",
            "production notes",
            "needs producing",
            "voice request",
            "voice part",
            "blog comment",
            "files column",
            "voice requests folder",
        ],
        _VOICE_WORKFLOW_RULES,
    ),
    # File upload — fires for any step involving file operations
    (
        ["upload", "attach", "file", "browse", "choose file", "drag", "drop", "dropzone", "import file"],
        _FILE_UPLOAD_RULES,
    ),
    # Table sort — fires for any step that involves sorting a column
    (
        [
            "sort",
            "ascending",
            "descending",
            "oldest",
            "newest",
            "order by",
            "sorted",
            "alphabetical",
            "a to z",
            "z to a",
            "due date",
            "due / days",
            "column header",
            "verify sort",
            "verify_table_sort",
        ],
        _TABLE_SORT_RULES,
    ),
    # localStorage — fires for any step involving tokens, JWT, or browser storage
    (
        [
            "jwt",
            "token",
            "localstorage",
            "local storage",
            "sessionstorage",
            "session storage",
            "authenticated",
            "not authenticated",
            "no token",
            "no jwt",
            "vc2jwt",
        ],
        _LOCAL_STORAGE_RULES,
    ),
]


def _select_rules(ac_step_text: str, target_url: str) -> str:
    """
    Select and assemble rules relevant to the current AC step.

    Only injects rule categories whose trigger keywords appear in
    the step text. Core rules are always included.

    Budget: Capped at 8,000 chars. When over budget, lowest-priority
    rule categories (last appended) are safely dropped.

    Args
    ----
    ac_step_text : str
        The current AC step being executed.
    target_url : str
        The target URL (injected into navigation rules).

    Returns
    -------
    str
        Combined rules text.
    """
    step_lower = ac_step_text.lower()

    # Always include core rules
    sections = [_CORE_RULES]

    # Conditionally include category-specific rules based on keyword matching
    for keywords, rule_text in _RULE_CATEGORIES:
        if any(kw in step_lower for kw in keywords):
            # Handle _FILE_UPLOAD_RULES which needs asset list formatting
            if "{asset_list}" in rule_text:
                asset_filenames = _get_asset_filenames()
                asset_list = ", ".join(asset_filenames) if asset_filenames else "(none loaded)"
                sections.append(
                    rule_text.format(
                        target_url=target_url,
                        asset_list=asset_list,
                    )
                )
            else:
                sections.append(rule_text.format(target_url=target_url))

    # ── Step classifier rules: targeted per-type guidance ─────────────────
    # The classifier is faster and more precise than pure keyword matching.
    # Its rules are injected AFTER the keyword-matched rules (same priority).
    # Pass the AC step text so the component registry can detect PrimeNG
    # components and inject their ground-truth Playwright interaction protocols.
    step_type = classify_step(ac_step_text)
    classifier_rules = get_step_type_rules(step_type, ac_step_text)
    if classifier_rules:
        label = get_step_type_label(step_type)
        sections.append(f"\n── Step Type: {label} — Specific rules for this action type:\n{classifier_rules}")

    # ── Standalone component detection for compound/generic steps ──────────
    # If the step classifier returned COMPOUND (no specific type matched),
    # still check for PrimeNG component mentions and inject their rules.
    if step_type == StepType.COMPOUND:
        _, standalone_component_rules = detect_primeng_components(ac_step_text)
        if standalone_component_rules:
            sections.append(standalone_component_rules)

    # ── Phase 5: Unified Registry supplement ──────────────────────────────
    if _unified_registry.is_loaded:
        unified_keys = _unified_registry.detect_components(ac_step_text)
        if unified_keys:
            unified_rules = _unified_registry.get_rules_for_prompt(unified_keys)
            if unified_rules:
                sections.append(unified_rules)

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# System prompt template (optimized for primacy/recency bias)
# ---------------------------------------------------------------------------
# Structure:
#   TOP (Primacy):    Identity, mission context, guardrails, locator rules
#   MIDDLE:           RAG/KB context, execution history, selector hints
#   BOTTOM (Recency): Reasoning workflow, AC step, schema rule, human guidance
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE: str = """\
{global_human_guidance}<identity>
You are vQA, an autonomous web testing agent. You are testing {app_identity}.
You can SEE the current page via a screenshot and an interactive element tree.
You MUST use the `plan_action` tool to execute the SINGLE NEXT browser action.
</identity>

<mission>
  <target_url>{target_url}</target_url>
  <credentials>{credential_context}</credentials>
  <jira_ticket>{jira_ticket_id}</jira_ticket>
</mission>

<instruction_priority>
Follow in this exact order (0 = highest priority):
  0. GROUND-TRUTH TEST    — human-written Playwright test for THIS ticket (follow EXACTLY)
  1. FORBIDDEN LOCATORS   — hard block, NO exceptions whatsoever
  2. FAILURE DIARY        — You just failed. Read this and MUST try a different approach.
  3. HUMAN GUIDANCE       — authoritative override (see bottom of this prompt)
  4. SELECTOR REGISTRY    — ground-truth confirmed locators (USE THESE FIRST)
  5. LEARNED PATTERNS     — proven fixes discovered during this run
  6. PAST RUN EXAMPLES    — patterns from previous runs (few-shot)
  7. KNOWLEDGE BASE       — vSuite domain workflow instructions
  8. ROLE CONSTRAINTS     — apply when no higher-priority rule applies
If a higher-priority instruction contradicts a lower one, ALWAYS follow the higher.
</instruction_priority>

<role_constraints>
{role_constraints}
</role_constraints>

<rules>
{contextual_rules}

<locator_strategy>
1. PRIMARY: Prefer semantic locators (`get_by_role` + `name`, or `get_by_text`).
2. DISAMBIGUATION: If the Failure Diary reports a "Strict Mode Violation",
   switch to `css_selector` using the exact `vqa_id` from the element tree.
   Example: {{"action": "click", "strategy": "css_selector", "name": "[data-vqa-id='42']"}}
3. FALLBACK ORDER (for clicks): get_by_role -> get_by_text -> css_selector
   Never use get_by_role('button') without a `name`.
4. ⛔ CRITICAL CSS BAN — The following WILL FAIL. Never use them:
   - Playwright pseudo-classes: `:has()`, `:has-text()`, `:is()`, `:not(:has(...))`
   - PrimeNG icon classes as locators: `.pi-sort-up`, `.pi-sort-down`, `.pi-angle-down`
5. ⛔ PORTAL SCOPING DEFENSE — For PrimeNG dropdowns, comboboxes, and sort menus:
   USE `primeng_dropdown` action (PREFERRED — handles the full click sequence atomically).
   NEVER click the trigger again if the portal is already visible — this CLOSES the menu.
6. STATE PERSISTENCE: Before switching views, verify you are NOT already in the target view.
7. SELECTOR INTEGRITY (FEAT-066) — MANDATORY:
   a) BAN DYNAMIC IDs: NEVER use framework-generated dynamic IDs (e.g. matching `ui-tabpanel-\\d+`).
   b) BAN DEEP-DOM CHAINS: NEVER use fragile nested element chains (e.g. `div:nth-child(3) > span`).
   c) USE TESTING ATTRIBUTES: If semantic role is ambiguous, check for `vqa_id` attributes.
</locator_strategy>

<available_actions>
- primeng_dropdown — ⭐ PREFERRED for PrimeNG dropdowns/combobox/sort. Requires: trigger_selector, target_text, portal_class.
- click / fill / select_option / check / uncheck — Standard form interactions (⚠ DO NOT use click for PrimeNG dropdowns)
- navigate / wait / verify / scroll / press_key
- set_input_files — Upload (selector=CSS of input[type=file], value=filename)
- verify_table_sort — Programmatic sort check (column, order="ascending"|"descending")
- recipe — Execute atomic component recipe by name
- coordinate_action — VISION: click at mark's (x,y). Params: mark_id, optional text_to_fill
- done — Current AC step is already satisfied
</available_actions>

<batching_rule>
Return a JSON ARRAY to batch sequential synchronous actions together.
Batch ALL form fills and their final submit click in ONE response.
Stop batching and return a single action only when you need to:
  - Wait for a page navigation or modal with unknown timing
  - Verify a UI state change before proceeding
The observation and thought fields only need to appear in the FIRST item of the array.
</batching_rule>

<persona_tracking_rule>
When you assign ANY user to a task (e.g., selecting a voice talent), include:
  "track_actor": {{"role": "voicer", "name": "Demo Voice Talent"}}
Valid roles: voicer, editor, producer, mixer, reviewer.
Only include when actively selecting/assigning a person.
</persona_tracking_rule>

<few_shot_examples>
Example 1: Ad Type Selection (custom dropdown — NOT combobox)
  click get_by_role('button', name='') inside '#qo-form-panel'
  then click get_by_label('Radio Commercial')

Example 2: Client Autocomplete (type partial -> wait -> click option)
  fill get_by_role('searchbox', name='Client ') value='Bob'
  click get_by_role('option', name="Bob's Burgers")

Example 3: File Upload (NEVER click Browse)
  {{"action": "set_input_files", "selector": "p-fileupload input[type='file']", "value": "Client Logo.jpg"}}

Example 4: Sorting a Standard Column
  {{"action": "click", "strategy": "css_selector", "name": "th.po-col-clientCol"}}
  {{"action": "wait", "value": 1000}}
  {{"action": "verify_table_sort", "column": "CLIENT", "order": "ascending"}}

Example 5: Strict Mode — use vqa_id
  # Failure diary: "Strict mode violation: get_by_text('Save') matched 3 elements"
  # Element tree: [vqa_id=17] button "Save" (main footer)
  {{"action": "click", "strategy": "css_selector", "name": "[data-vqa-id='17']"}}

Example 6: PrimeNG Dropdown (Sort By, p-select, combobox) — ALWAYS use primeng_dropdown
  # ❌ WRONG — panel closes between separate clicks (race condition):
  #   {{"action": "click", "strategy": "css_selector", "name": "th.po-col-duedaysCol p-select"}}
  #   {{"action": "click", "strategy": "get_by_text", "name": "Due Date", ...}}
  #
  # ✅ CORRECT — Compact View Sort By button (portal_class is .sort-panel, NOT .po-sorting-dropdown-panel):
  {{"action": "primeng_dropdown",
    "trigger_selector": "button#sort-btn",
    "target_text": "Due Date",
    "portal_class": ".sort-panel",
    "reasoning": "Compact View: Sort By button opens .sort-panel — use primeng_dropdown"}}

  # ✅ CORRECT — List View Due/Days column header (portal_class is .po-sorting-dropdown-panel):
  {{"action": "primeng_dropdown",
    "trigger_selector": "th.po-col-duedaysCol p-select",
    "target_text": "Due Date",
    "portal_class": ".po-sorting-dropdown-panel",
    "reasoning": "atomic compound-column sort — calling again toggles asc/desc"}}

  # ✅ CORRECT — List View Start/End column (⚠ options are "Start"/"End", NOT "Start Date"/"End Date"):
  {{"action": "primeng_dropdown",
    "trigger_selector": "th.po-col-startendCol p-select",
    "target_text": "Start",
    "portal_class": ".po-sorting-dropdown-panel",
    "reasoning": "Start/End column — option label is 'Start', NOT 'Start Date'"}}
</few_shot_examples>
</rules>


<context>
{global_run_context}{ground_truth_tests}{failure_diary}{past_actions}{forbidden_locators}{self_heal_context}{skill_hints}{selector_hints}{playwright_context}{long_term_memory}{persistent_memory}<execution_history>
{action_history}</execution_history>
{kb_context}{user_guidance}
</context>

<mandatory_reasoning_workflow>
BEFORE outputting your plan_action JSON, you MUST produce a <thought_process> block.
This block is NON-NEGOTIABLE. An action submitted without it will be treated as invalid.

The thought_process must follow these three steps IN ORDER:

<CRITICAL_REFLECTION_RULES>
1. Look at your Execution History. Have you interacted with a 'combobox' or 'Select'
   button or 'Sort By' button in the last 2 steps?
2. If YES, the dropdown portal is currently open on the screen.
3. DO NOT click the trigger button again. If you click the trigger again, you will
   CLOSE the menu and FAIL. This is a hard rule with zero exceptions.
4. Your immediate next action MUST be to interact with the options inside the portal
   (e.g., using container_selector) OR to use the `primeng_dropdown` macro action,
   which handles the full trigger→wait→select sequence atomically and safely.
5. If you are unsure whether the portal is open, emit a `wait` action (500ms) and
   then re-observe before clicking anything.
6. CHEVRON RULE: If you are using coordinate_action or primeng_dropdown in Vision Mode
   to open a dropdown menu (especially in column headers like Due/Days), DO NOT select
   the mark ID in the center of the text. You MUST select the mark ID that is positioned
   over the downward arrow/chevron icon on the far right of the element. The center of
   a p-select element contains only the label text — clicking it does NOT open the menu.
</CRITICAL_REFLECTION_RULES>

{human_execution_override}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — ANTI-LOOP CHECK (apply CRITICAL_REFLECTION_RULES above first)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Review the last 3 entries in the Action History / Execution Log.

Ask yourself:
  A) "Did I just click a combobox, p-select, Sort By button, or dropdown trigger?"
     → If YES: The portal IS OPEN. Do NOT click the trigger again. Use primeng_dropdown
       or scope a get_by_text click inside the container_selector of the portal.
  B) "Have I performed the EXACT same action (same locator, same target)
     2 or more times consecutively WITHOUT the Acceptance Criteria advancing?"

IF either A or B is YES → You are in a loop. You MUST NOT retry that action.
  Required response: Name the repeated action, then output a RESET action.
  Valid reset actions: use primeng_dropdown atomically, scope with container_selector,
  press Escape to close the portal, or take a screenshot-only verify to re-observe.

IF NO → Proceed to Step 2.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — PRE-FLIGHT STATE VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Look at the current DOM / screenshot. Determine which UI view you are in.

YOU CANNOT ASSUME A VIEW. You must cite DOM EVIDENCE:

  LIST VIEW evidence    → visible column headers (CLIENT, STATUS, DUE / DAYS, etc.)
                          AND no "Sort By" button (`button#sort-btn`) visible.

  COMPACT VIEW evidence → a "Sort By" button (`button#sort-btn`) is visible above
                          the table AND there are no column headers.

State your verdict explicitly:
  "I am in LIST VIEW because I can see column headers and no Sort By button."
  OR
  "I am in COMPACT VIEW because the Sort By button is visible and there are no column headers."

IF the Human Guidance says "start in listview" AND you are in Compact View:
  → Your IMMEDIATE next action MUST be to switch to List View using the view toggle.
  → Do NOT execute any sorting or other AC step until the prerequisite is met.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — RULE APPLICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Apply Human Guidance rules ONLY for your CURRENTLY VERIFIED view.

  IF IN LIST VIEW:
    → Click column headers directly to sort.
    → For compound columns (Due / Days, Submitted On): click the header,
      wait for the dropdown portal, then click the sub-option INSIDE
      the VISIBLE portal panel (scoped to `.p-dropdown-panel:visible`).
    → DO NOT use the "Sort By" button — it does not exist in List View.

  IF IN COMPACT VIEW:
    → Click `button#sort-btn` to open the Sort By dropdown.
    → Select the desired option from the dropdown panel.
    → DO NOT click column headers — they do not exist in Compact View.
    → DO NOT click `get_by_role("combobox")` to sort — this only toggles
      the header open/closed and creates an infinite loop.

Example correct thought_process:
<thought_process>
Anti-Loop Check: Step 4 clicked "Sort By" dropdown, Step 5 clicked "Sort By" again.
I am looping. Breaking out — will not repeat this action.
Pre-Flight State Verification: DOM shows a "Sort By" button (button#sort-btn) visible,
no column headers present. I am definitively in COMPACT VIEW.
Rule Application: Human guidance says "start in List View". Prerequisite is FAILING.
Immediate action: Find the view toggle (cog/settings icon) and switch to List View
before attempting any sort step.
</thought_process>
</mandatory_reasoning_workflow>

<current_task>
  <current_step number="{ac_step_number}" total="{ac_steps_total}">{current_ac_step}</current_step>
</current_task>

<CRITICAL_SCHEMA_RULE>
You MUST include the `kb_acknowledgement` field in your JSON payload.
Summarize the active rules from `<human_intervention_rules>` or `<UI_RULES>` that apply.
If no KB rules apply, write: "No KB rules for this step."
Omitting this field causes a fatal system crash.
</CRITICAL_SCHEMA_RULE>

<critical_guidance>
The following section contains HUMAN-VERIFIED rules for this exact ticket and step.
This is the FINAL section you read before generating your action — it has the
highest practical weight due to recency. You MUST acknowledge it in kb_acknowledgement.

<human_intervention_rules>
{human_intervention_rules}
</human_intervention_rules>

BEFORE you call plan_action, write your kb_acknowledgement:
  - If human_intervention_rules contains concrete instructions: quote the key
    selector or action verbatim and state you will follow it.
  - If it says "No specific KB rules found": write "No KB rules for this step."
  - The kb_acknowledgement field is REQUIRED. Bedrock will reject your response
    if it is missing.
</critical_guidance>
"""

# ---------------------------------------------------------------------------
# Sort/navigation-specific override block — injected only for relevant step types
# (CLICK_ACTION, DROPDOWN, NAVIGATE, COMPOUND). Saves ~425 tokens per call on
# login, fill-form, verify, and wait steps where this block is irrelevant.
# ---------------------------------------------------------------------------
_SORT_EXECUTION_OVERRIDE: str = (
    "<HUMAN_EXECUTION_OVERRIDE>\n"
    "⚠️ These rules override ALL other strategies. Failure to follow them will cause blocked actions.\n\n"
    "1. COMPOUND COLUMN SORT — USE primeng_dropdown (ATOMIC, NO RACE CONDITION):\n"
    '   For "Due / Days" and "Start / End" column headers, ALWAYS use a single primeng_dropdown.\n'
    "   Due/Days portal options (exact label text — do NOT guess):\n"
    '     "Due Date", "Days", "Submitted On"\n'
    '   Start/End portal options — ⚠ SHORT NAMES, NOT full "Date" suffix:\n'
    '     "Start"  (NOT "Start Date")   "End"  (NOT "End Date")\n'
    "   Examples:\n"
    '     {"action": "primeng_dropdown",\n'
    '       "trigger_selector": "th.po-col-duedaysCol p-select",\n'
    '       "target_text": "Due Date",\n'
    '       "portal_class": ".po-sorting-dropdown-panel"}\n'
    '     {"action": "primeng_dropdown",\n'
    '       "trigger_selector": "th.po-col-startendCol p-select",\n'
    '       "target_text": "Start",\n'
    '       "portal_class": ".po-sorting-dropdown-panel"}\n'
    "   Calling primeng_dropdown with the same target_text AGAIN toggles ascending ↔ descending.\n"
    "   DO NOT split into Step 1 (click trigger) + Step 2 (click option) — they will race.\n\n"
    "2. VIEW STATE SYNCHRONIZATION:\n"
    "   - If in List View: sort using column header dropdowns only (via primeng_dropdown for\n"
    "     compound columns, css_selector click for CLIENT and STATUS columns).\n"
    '   - If in Compact View: do NOT use column headers. Use the "Sort by" dropdown exclusively.\n'
    "   Always verify which view you are in before interacting with sort controls.\n\n"
    "3. OVERLAY MANAGEMENT:\n"
    "   Before clicking any sorting dropdown, verify the search panel overlay is closed.\n"
    "   If it is blocking the UI, dismiss it first (click outside or press Escape).\n\n"
    "4. SELF-CORRECTION PROTOCOL:\n"
    "   If a step fails, DO NOT loop the same action. Re-read these rules, reassess the DOM,\n"
    "   and use coordinate_action if your CSS selectors are failing.\n"
    "</HUMAN_EXECUTION_OVERRIDE>\n"
)

_SORT_STEP_TYPES = {
    "click_action",
    "click_nav",
    "dropdown",
    "navigate",
    "compound",
    "date_picker",
    "view_switch",  # View switch steps use the settings gear/dropdown override rules
}


def _build_hitl_override_block(state: VQAState) -> str:
    """
    Format the structured HITL override into a high-priority prompt block.
    Called when a human operator has just completed a step manually.
    """
    override = state.get("hitl_override")
    if not override:
        return ""

    explanation = override.get("explanation", "")
    actions = override.get("action_sequence", [])
    ac_step = override.get("ac_step", "previous step")

    block = [
        "═" * 63,
        "🚨 HUMAN OPERATOR OVERRIDE (PRIORITY 1)",
        f"The previous AC step ('{ac_step}') was completed by a human operator.",
    ]

    if explanation:
        block.append(f"OPERATOR EXPLANATION:\n{explanation}")

    if actions:
        block.append("CAPTURED HUMAN ACTIONS (from last step):")
        for i, act in enumerate(actions, 1):
            # Clean up action for prompt readability
            prompt_act = {k: v for k, v in act.items() if k not in ("timestamp", "screenshot")}
            block.append(f"  {i}. {json.dumps(prompt_act)}")

    block.append("TRUST the current page state and continue with the NEXT AC step.")
    block.append("═" * 63)

    return "\n".join(block) + "\n\n"


# ---------------------------------------------------------------------------
# CV Vision Diagnostic Fragment (FEAT-117 / T2-c)
# ---------------------------------------------------------------------------


def _build_cv_diagnostic_fragment(state: VQAState | dict) -> str:
    """
    Build a recovery prompt fragment when CV vision returned mark_id=None.

    Reads ``cv_vision_diagnostic`` from state (populated by executor's
    ``_build_cv_vision_diagnostic`` helper) and returns a human-readable
    paragraph that the planner node prepends to its system prompt so the
    LLM understands WHY vision failed and what to try next.

    Returns an empty string when ``cv_vision_diagnostic`` is absent or None
    — no spurious injections on normal (non-CV-miss) turns.

    Called from the planner node before assembling the system prompt.  The
    fragment is prepended after the SoM block (lower priority than SoM) but
    before the main system prompt body.

    Parameters
    ----------
    state : VQAState | dict
        The current LangGraph state dict.

    Returns
    -------
    str
        Multi-line diagnostic + recovery-options block, or "" if no diagnostic.
    """
    diag = state.get("cv_vision_diagnostic")
    if not diag:
        return ""

    target_text = diag.get("target_text", "the target element")
    n_marks = diag.get("n_marks", 0)
    options = diag.get("options", ["open_container", "scroll", "synonyms"])

    # Build human-readable option list from canonical option codes
    _option_labels = {
        "open_container": "(a) open a parent container first (e.g. click the dropdown trigger before selecting the option)",
        "scroll": "(b) scroll the page — the element may be outside the current viewport",
        "synonyms": "(c) try synonyms — the target text may be a paraphrase of the visible label",
    }
    option_lines = [_option_labels.get(opt, f"({opt})") for opt in options]

    lines = [
        "━" * 60,
        "CV VISION DIAGNOSTIC — element not found by vision",
        f"Vision saw {n_marks} mark(s) on the page; none matched '{target_text}'.",
        "Before retrying, consider one of these recovery strategies:",
        *option_lines,
        "Do NOT repeat the same strategy (get_by_text / get_by_role) that",
        "already failed for this AC step. Choose a different approach.",
        "━" * 60,
    ]
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Prompt Section Formatting
# ---------------------------------------------------------------------------


def _build_action_history(state: VQAState, max_recent: int = 8) -> str:
    """
    Build an action history block with consecutive-repeat loop detection.

    Shows the last N steps AND injects a hard INFINITE LOOP escalation
    directive whenever the same (action, locator) pair appears consecutively
    at the tail of the log — preventing the LLM from repeating the same
    failing action indefinitely.

    Args
    ----
    state : VQAState
        Current graph state.
    max_recent : int
        Maximum number of recent steps to include.
    """
    log = state.get("detailed_execution_log", [])
    if not log:
        return "ACTION HISTORY: No actions taken yet."

    # ─── Consecutive repeat detector ────────────────────────────────────────
    # Walk backwards through the log counting how many consecutive tail
    # entries have the same (action_type, locator_value) fingerprint.
    # This is strategy-agnostic: get_by_text('vProMedia') === css_selector('vProMedia')
    # would NOT match (different strategy), but repeated exact pairs DO match.
    def _step_fingerprint(step: dict) -> str:
        return f"{step.get('action_type', '')}|{step.get('locator_value', '')}"

    tail_fp = _step_fingerprint(log[-1]) if log else ""
    repeat_count = 0
    for step in reversed(log):
        if _step_fingerprint(step) == tail_fp and tail_fp:
            repeat_count += 1
        else:
            break

    # Take the most recent N entries for display
    recent = log[-max_recent:]

    sep = "═" * 63
    lines = [f"\n{sep}\nACTION HISTORY (last {len(recent)} of {len(log)} total steps):", sep]
    for step in recent:
        status = "✓" if step.get("success") else "✗"
        action = step.get("action_type", "?")
        locator = step.get("locator_value", "?")
        error = step.get("error_message", "")
        line = f"  {status} Step {step.get('step_index', '?')}: {action} → '{locator}'"
        if error:
            line += f" [ERR: {error[:100]}]"
        lines.append(line)

    if len(log) > max_recent:
        lines.insert(2, f"  ... ({len(log) - max_recent} earlier steps not shown)")

    # ─── Hard escalation block ───────────────────────────────────────────────
    # Fires on 2+ consecutive identical actions — below threshold is normal retry.
    _REPEAT_THRESHOLD = 2
    if repeat_count >= _REPEAT_THRESHOLD and tail_fp:
        _repeated_action, _repeated_locator = tail_fp.split("|", 1)
        lines.append("")
        lines.append("┌" + "─" * 61 + "┐")
        lines.append(f"│ ⚠  INFINITE LOOP DETECTED — {repeat_count} consecutive identical actions  │")
        lines.append("├" + "─" * 61 + "┤")
        lines.append(f"│  Action: {_repeated_action:<50} │")
        lines.append(f"│  Target: '{_repeated_locator[:49]:<49}' │")
        lines.append("├" + "─" * 61 + "┤")
        lines.append("│  MANDATORY RULES:                                             │")
        lines.append("│  1. This action is COMPLETELY FORBIDDEN on the next step.     │")
        lines.append("│  2. DO NOT use this locator again in any form.                │")
        lines.append("│  3. You MUST take a STRUCTURALLY DIFFERENT approach:          │")
        lines.append("│     a. Navigate to a different page section first.            │")
        lines.append("│     b. Try a completely different locator strategy.           │")
        lines.append("│     c. If the step is already done → emit 'done'.            │")
        lines.append("│     d. If stuck → emit 'wait' then screenshot before acting. │")
        lines.append("└" + "─" * 61 + "┘")

    return "\n".join(lines) + "\n"  # Wrapped in <execution_history> tags by the prompt template


def _build_self_heal_context(state: VQAState) -> str:
    """
    Build tiered healing directives for self-healing retries.

    Forces systematic escalation across 3 tiers instead of letting the LLM
    freely choose its recovery (which often produces the same selector in
    different clothes):
      Tier 1 (retry=1) — Change locator strategy / scope the search
      Tier 2 (retry=2) — Add a timing wait then retry same locator
      Tier 3 (retry=3) — Full logic re-evaluation; stop all variations

    Shown when retry_count > 0 OR agent_critique is set (critique persists
    across retry resets while the agent remains on the same AC step).

    Args
    ----
    state : VQAState
        Current graph state with retry context.

    Returns
    -------
    str
        Tiered self-heal block, or empty string if not retrying.
    """
    last_error = state.get("last_error", "")
    critique = state.get("agent_critique", "")
    retry_count = state.get("retry_count", 0)

    if retry_count == 0 and not critique:
        return ""

    max_retries = state.get("max_retries", 3)
    header = [
        "═══════════════════════════════════════════════════════════════",
        f"⚠ SELF-HEAL MODE — Retry {retry_count}/{max_retries}",
        "═══════════════════════════════════════════════════════════════",
    ]

    if last_error:
        header.append(f"Last error: {last_error[:200]}")
    if critique:
        header.append(f"Evaluator feedback: {critique[:300]}")

    # ── Tiered healing directive (escalates with retry_count) ──────────────
    if retry_count == 1:
        # Detect off-screen STRICT_MODE_VIOLATION for a more specific hint
        _is_off_screen_strict = last_error and "STRICT_MODE_VIOLATION" in last_error and "0 visible" in last_error
        if _is_off_screen_strict:
            tier = [
                "",
                "🔧 HEALING TIER 1 — Element is off-screen (0 visible in STRICT_MODE):",
                "  • The locator matched elements but NONE are visible — they are scrolled off-screen.",
                "  • The executor already tried scroll_into_view_if_needed and it failed.",
                "  • REQUIRED next action: use 'evaluate' to scroll the container:",
                '    {"action": "evaluate", "expression": "document.querySelector(\'[selector]\').scrollIntoView({block:\'center\',inline:\'center\'})"}',
                "  • OR use 'evaluate' to scroll the page/table RIGHT:",
                '    {"action": "evaluate", "expression": "window.scrollBy(500, 0)"}',
                "  • After scrolling, retry the click with get_by_text + use_first: true.",
                "  • DO NOT repeat the same get_by_text click — it already failed 0-visible.",
            ]
        else:
            tier = [
                "",
                "🔧 HEALING TIER 1 — Change locator specificity:",
                "  • DO NOT repeat the exact same locator that just failed.",
                "  • If you used get_by_role → try get_by_text instead.",
                "  • If get_by_text matched too many → add container_selector to scope it.",
                "  • If you used css_selector → try get_by_role + role/name.",
                "  • If STRICT_MODE: add container_selector or use vqa_id from the element list.",
                "  • Check you are targeting the correct ancestor container for PrimeNG overlays",
                "    (p-dialog, p-dropdown-panel, p-menu-list are appended to <body>, not the trigger).",
            ]
    elif retry_count == 2:
        tier = [
            "",
            "⏱ HEALING TIER 2 — Add timing before retry:",
            "  • Two locator attempts have failed. The element may exist but not yet be interactive.",
            '  • REQUIRED: emit {"action": "wait", "value": "1500"} as your NEXT action.',
            "  • After the wait, retry the same goal using a DIFFERENT locator strategy.",
            "  • If a spinner/overlay is present → wait for it to disappear before acting.",
            "  • If the element requires scrolling into view → add a scroll action first.",
        ]
    else:  # retry_count >= 3
        tier = [
            "",
            "🧠 HEALING TIER 3 — Full logic re-evaluation:",
            "  • THREE attempts have failed. Stop trying variations of the same action.",
            "  • REQUIRED: Reconsider the approach entirely:",
            "    1. Is this AC step achievable from the CURRENT page state?",
            "    2. Is a prerequisite step missing (wrong page, modal not open, etc.)?",
            "    3. Does the screenshot show the step is ALREADY satisfied? → emit done.",
            "    4. Is the Jira step ambiguous or impossible in this environment? → emit done.",
            "  • DO NOT emit the same action type with the same target for a 4th time.",
        ]

    return "\n".join(header + tier)


def _build_legacy_code_prohibition(state: VQAState) -> str:
    """
    Inject a hard prohibition block when the Jira ticket description contains
    raw Playwright/JS code snippets (e.g., codegen output).

    These snippets must be treated as a Behavioral Diagram showing INTENT only.
    The agent is forbidden from copying their CSS selectors or element IDs
    because codegen locators break on every Angular build.

    Returns an empty string when no code-like content is detected (zero prompt
    bloat for clean tickets).

    Args
    ----
    state : VQAState
        Current graph state (reads jira_ticket.description).

    Returns
    -------
    str
        Prohibition block, or empty string if no code detected.
    """
    description = state.get("jira_ticket", {}).get("description", "")
    if not description:
        return ""

    # Detect raw Playwright / JS code patterns
    code_signals = [
        "await page.",
        "page.locator(",
        "page.click(",
        "page.fill(",
        "page.goto(",
        "getByRole(",
        "getByText(",
        "getByLabel(",
        "expect(page",
        ".click()",
        ".fill(",
        "codegen",
    ]
    has_code = any(sig in description for sig in code_signals)
    if not has_code:
        return ""

    return (
        "═══════════════════════════════════════════════════════════════\n"
        "⛔ JIRA CODE SNIPPETS DETECTED — READ-ONLY BEHAVIORAL DIAGRAM:\n"
        "═══════════════════════════════════════════════════════════════\n"
        "The Jira description contains raw Playwright/JS code (codegen output).\n"
        "You are FORBIDDEN from copying locators, CSS selectors, or element IDs\n"
        "from these snippets. They are brittle and break on every Angular build.\n"
        "TREAT THEM AS INTENT DIAGRAMS ONLY — re-derive every locator using:\n"
        "  get_by_role > get_by_text > get_by_label > vqa_id > css_selector\n"
        "═══════════════════════════════════════════════════════════════\n"
    )


def _build_overlay_location_rule(state: VQAState) -> str:
    """
    Inject the PrimeNG body-append overlay location rule when the current
    AC step or failure diary indicates interaction with overlay components.

    PrimeNG appends overlay panels to <body> (not the triggering component)
    to avoid overflow:hidden clipping. Searching inside a container will
    find nothing. This rule is injected when relevant to avoid the locator
    failure mode where the planner tries container_selector on overlay panels.

    Returns empty string when no overlay interaction is expected (zero bloat).

    Args
    ----
    state : VQAState
        Current graph state (reads ac_step, failure diary, jira description).

    Returns
    -------
    str
        Overlay location rule block, or empty string if not applicable.
    """
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    current_step = ac_steps[ac_index] if ac_index < len(ac_steps) else ""
    diary = state.get("ac_step_failure_diary", [])

    # Trigger on overlay-related vocabulary in the current step or diary errors
    _OVERLAY_TRIGGERS = [
        "dropdown",
        "select",
        "modal",
        "dialog",
        "overlay",
        "popup",
        "popover",
        "menu",
        "settings",
        "filter",
        "sort",
        "calendar",
        "date",
        "autocomplete",
        "p-dialog",
        "p-dropdown",
        "p-menu",
        "p-overlaypanel",
        "p-select",
        "p-calendar",
        "p-autocomplete",
    ]
    step_lower = current_step.lower()
    diary_errors = " ".join(e.get("error", "") for e in diary).lower()
    combined = step_lower + " " + diary_errors

    if not any(t in combined for t in _OVERLAY_TRIGGERS):
        return ""

    return (
        "═══════════════════════════════════════════════════════════════\n"
        "🔍 PRIMENG OVERLAY LOCATION RULE (overlay panels live in <body>):\n"
        "═══════════════════════════════════════════════════════════════\n"
        "PrimeNG appends overlay panels to <body>, NOT inside the trigger element.\n"
        "These elements will NEVER be found inside a container_selector:\n"
        "  p-dropdown-panel, p-select-overlay, p-menu-list, p-overlaypanel,\n"
        "  p-dialog, p-autocomplete-panel, p-tieredmenu, cdk-overlay-container\n"
        "\n"
        "CORRECT approach for overlay ITEMS (options, menu items, dialog buttons):\n"
        "  • strategy='get_by_role', role='option'|'menuitem'|'button'|'dialog'\n"
        "    name='[exact item text]' — Playwright auto-scopes to body overlays.\n"
        "  • strategy='get_by_text', name='[item text]' — also works for body-overlays.\n"
        "  \u2022 strategy='css_selector', name='.p-dropdown-item:has-text(\"...\")' \\n"
        "    (no container_selector — top-level body-scoped search).\n"
        "\n"
        "WRONG approach (will always fail with TIMEOUT):\n"
        "  • container_selector='p-dropdown' + strategy='get_by_text' ← overlay not inside\n"
        "  • container_selector='.po-table-wrapper' + name='menu item' ← wrong scope\n"
        "═══════════════════════════════════════════════════════════════\n"
    )


def _build_forbidden_locators(state: VQAState) -> str:
    """
    Build a HARD BLOCK section listing locators that have repeatedly failed
    on the current AC step and must not be retried.

    Returns an empty string if no locators have met the threshold.
    """
    fail_counts: dict = state.get("ac_step_fail_counts", {})
    blocked = [(k, v) for k, v in fail_counts.items() if v >= 2]
    if not blocked:
        return ""

    lines = [
        "═══════════════════════════════════════════════════════════════",
        "⛔ FORBIDDEN LOCATORS (failed 2+ times this AC step — DO NOT USE):",
        "═══════════════════════════════════════════════════════════════",
    ]
    for locator_key, count in sorted(blocked, key=lambda x: -x[1]):
        # ── Content-level block (strategy-agnostic): __content__:{name} ──────
        # Written by evaluator when STRICT_MODE VIOLATION returns 0 visible.
        # Means ALL strategies targeting this text are exhausted — must scope.
        if locator_key.startswith("__content__:"):
            blocked_text = locator_key.split(":", 1)[1]
            lines.append(
                f"  ⛔ CONTENT-LEVEL BLOCK ({count}x): '{blocked_text}' has 0 visible matches — "
                f"every locator strategy targeting this text is FORBIDDEN."
            )
            lines.append(
                f"    → MANDATORY: Use container_selector to scope to a visible parent "
                f"(e.g. 'container_selector': '.p-dropdown-items-wrapper') "
                f"OR use the vqa_id from the INTERACTIVE ELEMENTS list for exact targeting. "
                f"Do NOT use get_by_text, get_by_role, or css_selector for '{blocked_text}' without scoping."
            )
            continue
        # ── Standard locator block: strategy:role:name ────────────────────────
        if locator_key.startswith("__"):
            continue  # internal tracking key — skip
        parts = locator_key.split(":", 2)  # strategy:role:name
        if len(parts) == 3:
            strategy, role, name = parts
            lines.append(f"  ✗ BLOCKED ({count}x): strategy='{strategy}' role='{role}' name='{name}'")
            if name:
                lines.append(f'    → Try instead: {{"strategy": "get_by_text", "name": "{name}"}}')
        else:
            lines.append(f"  ✗ BLOCKED ({count}x): {locator_key}")
    lines.append("")
    return "\n".join(lines)


def _build_failure_diary(state: VQAState) -> str:
    """
    Build a structured failure diary for the planner prompt.

    Replaces the old single-string ``agent_critique`` approach with a
    chronological, structured log of every failed action attempt on the
    current AC step.  Each entry shows:

      - Which locator was tried (strategy + role + name)
      - The exact classified error (STRICT_MODE, TIMEOUT, NOT_VISIBLE, etc.)
      - A targeted recovery suggestion specific to that error type

    This gives the LLM everything it needs to avoid repeating the same
    failing approaches.  The block is ONLY shown when the diary is non-empty
    (i.e., at least one action has already failed on the current AC step).

    Special Pattern Analysis
    ------------------------
    When the diary shows 2+ STRICT_MODE failures on the same name, we inject
    an explicit directive to use ``vqa_id`` — the DOM-stamp fallback — because
    semantic locators have proven ambiguous for this element.

    Args
    ----
    state : VQAState
        Current graph state with ``ac_step_failure_diary``.

    Returns
    -------
    str
        Formatted failure diary block, or empty string if no failures yet.
    """
    diary: list[dict] = state.get("ac_step_failure_diary", [])
    if not diary:
        return ""

    # ── Prompt size guard: cap diary at 5 most-recent entries ────────────────
    # Each entry is ~300 chars. Without a cap, a stuck AC step with 20+ retries
    # produces 6,000+ chars of diary alone. The last 5 entries capture the most
    # actionable recent failures; earlier entries are summarised in the header.
    _MAX_DIARY_ENTRIES = 5
    total_attempts = len(diary)
    if total_attempts > _MAX_DIARY_ENTRIES:
        diary = diary[-_MAX_DIARY_ENTRIES:]  # keep the most recent only

    ac_index = state.get("ac_step_index", 0)
    lines = [
        "═══════════════════════════════════════════════════════════════",
        f"⚠ FAILURE DIARY — AC Step {ac_index + 1} "
        + (
            f"(showing last {_MAX_DIARY_ENTRIES} of {total_attempts} attempts):"
            if total_attempts > _MAX_DIARY_ENTRIES
            else f"(complete history of {total_attempts} failed attempt(s)):"
        ),
        "═══════════════════════════════════════════════════════════════",
        "These approaches have ALREADY BEEN TRIED and FAILED on this step.",
        "You MUST choose an approach NOT listed below.",
        "⚡ MANDATORY: You MUST apply the most recent '⚡ MANDATORY NEXT ACTION' exactly.",
        "   Ignoring it and trying a slight variation will be blocked.",
        "",
    ]

    for entry in diary:
        attempt = entry.get("attempt", "?")
        action = entry.get("action", "?")
        locator = entry.get("locator", "?")
        error = entry.get("error", "?")
        suggestion = entry.get("suggestion", "")
        lines.append(f"  Attempt {attempt}: [{action}] {locator}")
        lines.append(f"    ✗ Error: {error}")
        if suggestion:
            lines.append(f"    ⚡ MANDATORY NEXT ACTION: {suggestion}")
        lines.append("")

    # ── Pattern analysis: detect repeated failure types and inject directives ──
    error_types = [e.get("error", "").split("(")[0].strip() for e in diary]
    failed_names = [e.get("locator", "").split(":")[-1] for e in diary]

    # STRICT_MODE: 2+ failures on the same name → force vqa_id
    strict_mode_failures = sum(1 for t in error_types if "STRICT_MODE" in t)
    if strict_mode_failures >= 2:
        # Find the most-repeated failing name to make the directive specific
        from collections import Counter

        most_common_name = Counter(failed_names).most_common(1)[0][0] if failed_names else ""
        lines.append(
            f"⛔ STRICT_MODE PATTERN DETECTED ({strict_mode_failures} times): "
            f"Semantic locators are ambiguous for '{most_common_name}'. "
            f"You MUST use 'vqa_id' from the stamped element list below. "
            f"Do NOT use strategy + name for this element."
        )
        lines.append("")

    # TIMEOUT: 2+ failures → warn about possible hidden prerequisite
    timeout_failures = sum(1 for t in error_types if "TIMEOUT" in t)
    if timeout_failures >= 2:
        lines.append(
            f"⛔ TIMEOUT PATTERN DETECTED ({timeout_failures} times): "
            f"The target element is not loading. Check: "
            f"(1) Is a spinner still present? "
            f"(2) Does a parent section need to be opened first? "
            f"(3) Are you on the correct page / tab?"
        )
        lines.append("")

    return "\n".join(lines)


def _build_session_context_block(state: VQAState | dict, page_state: Any) -> str:
    """
    Build a ``<session_context>`` XML block with current URL, heading, and history.

    This block grounds the planner in the browser's current navigation state,
    preventing redundant navigation to the page it's already on.

    Controlled by ``settings.enable_session_navigation_context``.
    """
    from backend.config import settings

    if not settings.enable_session_navigation_context:
        return ""

    # page_state is the PageState object from state_tracker.py
    # Prefer deterministic URL from tracker over graph state
    url = getattr(page_state, "current_url", "") if page_state else ""
    if not url:
        url = state.get("current_page_url", "")

    history = state.get("navigation_history", [])
    heading = getattr(page_state, "page_heading", "") if page_state else ""

    lines = [
        "<session_context>",
        f"  <current_url>{url}</current_url>",
        f"  <page_heading>{heading}</page_heading>",
        "  <navigation_history>",
    ]
    for item in history:
        lines.append(f"    <nav>{item}</nav>")
    lines.append("  </navigation_history>")
    lines.append("</session_context>")

    return "\n".join(lines)


def _build_past_actions_block(state: VQAState) -> str:
    """
    Build a ``<past_actions>`` XML block from the rolling action history buffer.

    The action history buffer contains the last 5 failed actions, maintained
    by the evaluator via append-then-slice (FIFO).  This function renders them
    into an XML block that the planner consumes to avoid repeating ineffective
    strategies.

    When the buffer is empty, returns an empty string (no XML tags emitted).

    Args
    ----
    state : VQAState | dict
        Current graph state with ``action_history_buffer``.

    Returns
    -------
    str
        ``<past_actions>...</past_actions>`` XML block, or ``""`` if buffer
        is empty or missing.
    """
    buffer: list[dict] = state.get("action_history_buffer", [])
    if not buffer:
        return ""

    lines = [
        "<past_actions>",
        "The following actions have been tried and FAILED. "
        "You MUST NEVER repeat the same (action + strategy + target) combination.",
    ]
    for entry in buffer:
        action = entry.get("action", "?")
        strategy = entry.get("strategy", "?")
        target = entry.get("target", "?")
        error_type = entry.get("error_type", "?")
        iteration = entry.get("iteration", "?")
        lines.append(f"  - iteration {iteration}: {action} via {strategy} on '{target}' → {error_type}")
    lines.append("NEVER repeat any of the above (action + strategy + target) combinations.")
    lines.append("</past_actions>")
    return "\n".join(lines)


def _build_long_term_memory(state: VQAState) -> str:
    """
    Build a learning section from accumulated long_term_memory.

    These are observations the evaluator has written about the application
    behavior that should inform future decisions.
    """
    mem: list[str] = state.get("long_term_memory", [])
    if not mem:
        return ""

    lines = [
        "═══════════════════════════════════════════════════════════════",
        "📚 LEARNED PATTERNS (from this run — USE these to avoid past mistakes):",
        "═══════════════════════════════════════════════════════════════",
    ]
    # Show most recent 8 observations to avoid token bloat
    for obs in mem[-8:]:
        lines.append(f"  • {obs}")
    lines.append("")
    return "\n".join(lines)


def _build_persistent_memory_context(state: VQAState) -> str:
    """
    Build few-shot examples from persistent cross-run memory.

    Queries the persistent memory store for:
    1. Past action patterns relevant to the current AC step
    2. Learned credentials (e.g. "Demo Voice Talent → email: X") surfaced
       whenever the current step mentions role-switching or login.
    """
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    current_step = ac_steps[ac_index] if ac_index < len(ac_steps) else ""

    base = persistent_memory.get_few_shot_examples(current_step)

    # Inject learned credentials when the step involves account switching / login
    CRED_KEYWORDS = ("switch", "log in", "login", "account", "sign in", "different user", "different role")
    if any(kw in current_step.lower() for kw in CRED_KEYWORDS):
        cred_examples = persistent_memory.get_few_shot_examples("login as")
        if cred_examples:
            cred_block = (
                "\n\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                "LEARNED CREDENTIALS (from previous human-assisted runs):\n"
                "Use these exact emails when this AC step requires switching accounts.\n"
                "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
                f"{cred_examples}\n"
            )
            return (base or "") + cred_block

    return base


def _query_human_guidance_direct(
    current_step: str,
    ticket_id: str = "",
) -> str:
    """
    Directly scan knowledge/human_guidance.md for relevant HITL entries, with
    ticket-ID-aware exact-match boosting.

    The file is read at most once per 60 seconds (mtime-based cache). Per-query
    results are also cached by (step, ticket_id) key for the same TTL to eliminate
    repeated regex parsing on self-heal retries of the same AC step.

    Returns: raw concatenated content string (no box-drawing headers -- caller wraps in
    <human_intervention_rules> XML tags via the system prompt template).
    Returns empty string if nothing matches.
    """
    import re as _re
    from pathlib import Path as _Path

    guidance_path_str = str(_Path(__file__).parent.parent.parent / "knowledge" / "human_guidance.md")
    guidance_file = _Path(guidance_path_str)

    if not guidance_file.exists():
        return ""

    # ── mtime-based file cache ──────────────────────────────────────────────
    try:
        current_mtime = guidance_file.stat().st_mtime
    except OSError:
        return ""

    if _HG_FILE_MTIME.get(guidance_path_str) != current_mtime:
        try:
            _HG_FILE_CACHE[guidance_path_str] = guidance_file.read_text(encoding="utf-8")
            _HG_FILE_MTIME[guidance_path_str] = current_mtime
            # Invalidate result cache when file changes
            _HG_RESULT_CACHE.clear()
            _HG_RESULT_CACHE_TS.clear()
        except OSError:
            return ""

    text = _HG_FILE_CACHE.get(guidance_path_str, "")
    if not text.strip():
        return ""

    # ── per-query result cache (TTL-based) ─────────────────────────────────
    result_key = f"{ticket_id}::{current_step}"
    now = _time_mod.monotonic()
    if result_key in _HG_RESULT_CACHE and now - _HG_RESULT_CACHE_TS.get(result_key, 0) < _HG_RESULT_CACHE_TTL:
        return _HG_RESULT_CACHE[result_key]

    step_tokens = set(_re.findall(r"[a-zA-Z]{3,}", current_step.lower()))
    ticket_id_norm = ticket_id.strip().upper() if ticket_id else ""

    matches: list[tuple[int, str, str]] = []  # (score, label, content)
    guaranteed: list[tuple[str, str]] = []  # ticket-ID exact hits

    # A. ## WORKFLOW: blocks (HITL writeback format)
    wf_sections = _re.split(r"^## WORKFLOW:", text, flags=_re.MULTILINE)
    for section in wf_sections[1:]:
        lines_sec = section.strip().split("\n")
        if not lines_sec:
            continue
        name = lines_sec[0].strip()

        keywords: list[str] = []
        body_start = 1
        for i, line in enumerate(lines_sec[1:], 1):
            stripped = line.strip()
            if stripped.startswith("KEYWORDS:"):
                keywords = [k.strip().lower() for k in stripped.removeprefix("KEYWORDS:").split(",")]
            elif stripped == "---":
                body_start = i + 1
                break

        instructions = "\n".join(lines_sec[body_start:]).strip()
        if not instructions:
            continue

        if ticket_id_norm and ticket_id_norm in name.upper():
            guaranteed.append((f"[WORKFLOW: {name}]", instructions))
            continue

        META_KEYWORDS = {"human-guidance", "user-instruction", "hitl_explanation", "user_guidance"}
        domain_keywords = set(keywords) - META_KEYWORDS
        if not domain_keywords:
            continue

        VIEW_QUALIFIERS: set[str] = {
            "compact",
            "list",
            "calendar",
            "grid",
            "kanban",
            "modern",
            "thumbnail",
            "table",
            "folder",
            "search",
            "filter",
            "batch",
            "detail",
            "preview",
            "modal",
            "dialog",
            "sidebar",
            "overlay",
        }
        entry_qualifiers = VIEW_QUALIFIERS & set(_re.findall(r"[a-zA-Z]+", name.lower()))
        if entry_qualifiers:
            step_qualifiers = VIEW_QUALIFIERS & set(_re.findall(r"[a-zA-Z]+", current_step.lower()))
            if not (entry_qualifiers & step_qualifiers):
                continue

        overlap = len(step_tokens & domain_keywords)
        name_tokens = set(_re.findall(r"[a-zA-Z]{3,}", name.lower()))
        name_overlap = len(step_tokens & name_tokens)
        total_overlap = overlap + name_overlap
        if total_overlap >= 3:
            matches.append((total_overlap, f"[WORKFLOW: {name}]", instructions))

    # B. Plain ## heading blocks (from POST /teach endpoint)
    teach_sections = _re.split(r"^## (?!WORKFLOW:)", text, flags=_re.MULTILINE)
    for section in teach_sections[1:]:
        lines_sec = section.strip().split("\n")
        if not lines_sec:
            continue
        heading = lines_sec[0].strip().rstrip("#").strip()
        body = "\n".join(lines_sec[1:]).strip()
        if not body:
            continue

        if ticket_id_norm and ticket_id_norm in heading.upper():
            guaranteed.append((f"[Teach: {heading}]", body))
            continue

        heading_tokens = set(_re.findall(r"[a-zA-Z]{3,}", heading.lower()))
        if len(step_tokens & heading_tokens) >= 2:
            matches.append((len(step_tokens & heading_tokens), f"[Teach: {heading}]", body))

    # Merge: guaranteed first, then top-2 keyword matches
    sections_out: list[str] = []
    for label, content in guaranteed:
        capped = content[:1500] + ("\n... [truncated]" if len(content) > 1500 else "")
        sections_out.append(f"{label}\n{capped}")

    matches.sort(key=lambda x: -x[0])
    for _, label, content in matches[:2]:
        capped = content[:1500] + ("\n... [truncated]" if len(content) > 1500 else "")
        sections_out.append(f"{label}\n{capped}")

    if not sections_out:
        _HG_RESULT_CACHE[result_key] = ""
        _HG_RESULT_CACHE_TS[result_key] = now
        return ""

    logger.info(
        "[human_guidance_direct] %d KB doc(s) for ticket='%s' step='%s'",
        len(sections_out),
        ticket_id_norm or "?",
        current_step[:60],
    )
    result = "\n\n---\n\n".join(sections_out)
    _HG_RESULT_CACHE[result_key] = result
    _HG_RESULT_CACHE_TS[result_key] = now
    return result


def _load_learned_workflow_override(ac_step: str) -> str:
    """
    Check learned_workflows.json for a human-recorded sequence matching the
    current AC step.  If found, returns a CRITICAL system prompt injection
    that forces the LLM to replay the exact human sequence.

    Returns empty string if no match.
    """
    import json as _json
    from pathlib import Path as _Path

    wf_file = _Path(__file__).parent.parent.parent / "knowledge" / "blueprints" / "learned_workflows.json"
    if not wf_file.exists():
        return ""

    try:
        data = _json.loads(wf_file.read_text(encoding="utf-8"))
    except Exception:
        return ""

    # Exact match first
    entry = data.get(ac_step)
    if entry is None:
        # Fuzzy: check if any stored key is a substring of the current step or vice-versa
        step_lower = ac_step.lower()
        for stored_key, stored_entry in data.items():
            if stored_key.lower() in step_lower or step_lower in stored_key.lower():
                entry = stored_entry
                break

    if not entry:
        return ""

    sequence = entry.get("action_sequence", [])
    if not sequence:
        return ""

    seq_lines = []
    for i, act in enumerate(sequence, 1):
        action = act.get("action", "?")
        name = act.get("name") or act.get("inner_text", "")
        value = act.get("value", "")
        strategy = act.get("strategy", "get_by_text")
        line = f"  Step {i}: action={action!r}, strategy={strategy!r}, name={name!r}"
        if value:
            line += f", value={value!r}"
        seq_lines.append(line)

    recorded_at = entry.get("recorded_at", "(unknown time)")
    ticket_id = entry.get("ticket_id", "")

    return (
        "\n".join(
            [
                "╔══════════════════════════════════════════════════════════════╗",
                "║  ⭐ CRITICAL: HUMAN-RECORDED SEQUENCE — HIGHEST PRIORITY     ║",
                "╚══════════════════════════════════════════════════════════════╝",
                f"A human previously solved this EXACT AC step (recorded {recorded_at}, ticket {ticket_id}).",
                "You MUST output the actions in this EXACT sequence. Do NOT deviate.",
                f"AC Step matched: {ac_step[:120]!r}",
                "Human-recorded action sequence:",
                *seq_lines,
                "══════════════════════════════════════════════════════════════",
                "Output the JSON for the NEXT action in this sequence that has NOT yet been executed.",
                "Check your action history to determine which step you are on.",
                "══════════════════════════════════════════════════════════════",
            ]
        )
        + "\n\n"
    )


def _build_system_prompt(state: VQAState) -> str:
    """
    Assemble the complete system prompt from the current state.

    Key improvement over previous version:
    - Rules are conditionally injected based on the current AC step content.
    - Only relevant rules are included, cutting the prompt from ~4-6K to ~1.5-2.5K tokens.
    - Persistent memory few-shot examples are injected when available.

    Args
    ----
    state : VQAState
        Current graph state.

    Returns
    -------
    str
        The fully populated system prompt string.
    """
    # Current AC step
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    ac_total = len(ac_steps)
    current_step = ac_steps[ac_index] if ac_index < ac_total else "ALL STEPS COMPLETE"

    # Target URL and credential context
    target_url = state.get("target_url", "https://two-test.vcreative.net")
    cred_status = state.get("jira_ticket", {}).get("credential_status", "none")
    ticket_email = state.get("jira_ticket", {}).get("override_login_email", "")
    injected_email = state.get("injected_login_email", "")
    injected_password = state.get("injected_login_password", "")
    effective_email = injected_email or ticket_email
    role_email = state.get("role_context", {}).get("login_email", "")
    role_password = state.get("role_context", {}).get("login_password", "")

    # Prefer user-supplied credentials (ghost admin or override) over role/KB
    # credentials. When the user has typed credentials into the pre-run prompt
    # they MUST take priority — the shared/KB password is fallback only.
    _run_id = state.get("run_id", "")
    _ghost_email, _ghost_password = "", ""
    if _run_id:
        try:
            from backend.engine.persona_switch_node import _ghost_creds as _gc
            _gc_entry = _gc.get(_run_id) or {}
            _ghost_email = _gc_entry.get("email") or ""
            _ghost_password = _gc_entry.get("password") or ""
        except Exception:
            pass
    effective_login_email = _ghost_email or injected_email or role_email
    effective_login_password = _ghost_password or injected_password or role_password
    _cred_source = (
        "user-supplied (ghost admin)" if _ghost_password
        else "user-supplied (override)" if injected_password
        else "role/KB"
    )
    if cred_status == "complete" and effective_email:
        credential_context = (
            f"Using ticket credentials [{_cred_source}] — "
            f"email: {effective_login_email} / password: {effective_login_password}"
        )
    elif cred_status == "partial":
        credential_context = (
            f"Partial credentials from ticket [{_cred_source}] "
            f"(email: {effective_login_email or 'email missing'} / password: {effective_login_password})"
        )
    else:
        credential_context = (
            f"Using {_cred_source} credentials — "
            f"email: {effective_login_email} / password: {effective_login_password}"
        )

    # Role constraints
    role_key = state["role_context"].get("role_key", "")
    role_constraints = ""
    if role_key:
        try:
            role_constraints = get_planning_constraints_prompt(role_key)
        except KeyError:
            role_constraints = "(no role constraints loaded)"

    # Contextual rules — only inject rules relevant to current AC step
    contextual_rules = _select_rules(current_step, target_url)

    # Degrade-mode warning — if AC parsing fell back to legacy flat parser,
    # prepend a warning so the LLM reasons more carefully about step intent.
    _parse_quality = state.get("parse_quality", "ok")
    if _parse_quality == "degraded":
        _pq_reason = state.get("parse_quality_reason", "unknown error")
        contextual_rules = (
            "⚠️ AC PARSE QUALITY: DEGRADED — The structured AC parser failed and the system "
            f"fell back to a basic string-list parser (reason: {_pq_reason[:150]}). "
            "No typed step data or programmatic assertions are available. "
            "Reason more carefully about the intent of each AC step. "
            "If a step is ambiguous, decompose it into sub-actions and execute them in order.\n\n"
        ) + contextual_rules

    # Sort/navigation override — only inject when step involves clicking, dropdowns, or view changes
    _step_type = classify_step(current_step)
    human_execution_override = _SORT_EXECUTION_OVERRIDE if _step_type.value in _SORT_STEP_TYPES else ""

    # ── Ground-truth test matching — highest priority context ─────────
    # If the QA team has a human-written Playwright test for this exact
    # ticket, inject it at priority 0. This is the definitive reference.
    ticket_id = state["jira_ticket"].get("ticket_id", "")
    matched_tests = test_matcher.get_matching_tests(ticket_id)
    ground_truth_str = test_matcher.format_for_prompt(matched_tests)

    # KB lookup — find relevant vSuite workflow instructions for this AC step.
    # Hot-reload first: if a human takeover just appended to vSuite-actions.md,
    # the new entry will be picked up immediately without a server restart.
    kb.reload_if_updated()

    # ── DYNAMIC RAG PRUNING (Enhancement 3) ────────────────────────────
    # Instead of loading the full 416KB corpus on every tick, we use a
    # keyword relevance filter that gates whether KB is queried at all.
    # The TF-IDF index (loader.py) already limits to max_results=1 and
    # caps articles at 3,000 chars, but the real win is avoiding the
    # query entirely for steps that have no domain overlap — this
    # eliminates low-confidence noise matches that dilute LLM attention.
    #
    # Categories:
    #   SORT/TABLE   — sort, column, filter, ascending, descending, header, view
    #   NAVIGATION   — navigate, compact, list, calendar, view, switch, toggle
    #   UPLOAD/FILE  — upload, file, attach, browse, drag, drop, input
    #   FORM/INPUT   — fill, enter, type, input, field, text, dropdown, select
    #   ORDER/FLOW   — order, quick, submit, approve, status, draft, campaign
    #   AUTH/LOGIN   — login, sign, credentials, password, email, auth
    #
    # If the AC step matches NONE of these categories, we skip the KB
    # query entirely — the step is likely a simple verification or wait
    # that doesn't benefit from workflow instructions.
    _ac_lower = current_step.lower()
    _KB_RELEVANCE_GATES: dict[str, list[str]] = {
        "sort_table": ["sort", "column", "filter", "ascending", "descending", "header", "table", "search"],
        "navigation": ["navigate", "compact", "list", "calendar", "view", "switch", "toggle", "cog", "settings"],
        "upload_file": ["upload", "file", "attach", "browse", "drag", "drop", "audio", "asset"],
        "form_input": [
            "fill",
            "enter",
            "type",
            "input",
            "field",
            "dropdown",
            "select",
            "combobox",
            "checkbox",
            "radio",
        ],
        "order_flow": ["order", "quick", "submit", "approve", "status", "draft", "campaign", "production", "spot"],
        "auth_login": ["login", "sign", "credential", "password", "email", "auth", "logout"],
    }
    _kb_gate_matched = any(any(kw in _ac_lower for kw in keywords) for keywords in _KB_RELEVANCE_GATES.values())

    # Product context — pass through so retrieval is scoped to the active
    # product's KB (e.g. knowledge/vpromotions/*.md) when known.
    _active_product_kb = state.get("active_product") or state.get("product_slug") or state.get("product") or None

    if _kb_gate_matched:
        # Use synonym expansion so short steps ("Sort by Due Date") match broader
        # KB articles that use domain vocabulary ("compound column", "p-select").
        kb_context_str = kb.query_with_expansion(current_step, product=_active_product_kb)
        logger.debug(
            "[planner] KB gate OPEN for step '%s' (product=%s) → %d chars retrieved",
            current_step[:50],
            _active_product_kb or "<global>",
            len(kb_context_str),
        )
    else:
        kb_context_str = ""
        logger.info(
            "[planner] KB gate CLOSED — step '%s' has no domain keyword overlap, skipping RAG query",
            current_step[:60],
        )

    # Failure-specific KB query — only when this step has already failed once.
    # Enriches the query with the actual error message to surface entries that
    # the plain step text wouldn't match (e.g. "Timeout" → TABLE SORTING RULES).
    retry_count = state.get("retry_count", 0)
    last_error = state.get("last_error", "").strip()
    if retry_count >= 1 and last_error:
        last_action_log = state.get("detailed_execution_log", [])
        last_action_desc = ""
        if last_action_log:
            last = last_action_log[-1]
            last_action_desc = f"{last.get('action_type', '')} {last.get('locator_value', '')}"
        failure_kb_str = kb.query_for_failure(
            ac_step=current_step,
            error_message=last_error,
            last_action=last_action_desc,
        )
        if failure_kb_str:
            # ── FIX: REPLACE not PREPEND ───────────────────────────────────
            # Previously stacked 3 full articles (failure×2 + regular×1),
            # totalling up to 38,916 chars from KB alone on a single retry.
            # On retry the failure-specific guidance is more relevant than the
            # general step guidance — use it exclusively to stay under budget.
            kb_context_str = failure_kb_str

    # Global run context — pre-loaded themes + component gotchas from preflight.
    # Built once by ac_parser_node (via preflight.py) before the agentic loop.
    # Injected on EVERY iteration — gives the agent domain knowledge from
    # Attempt 0 without waiting for a failure.
    raw_global_ctx = state.get("global_run_context", "").strip()
    global_run_context_str = raw_global_ctx + "\n\n" if raw_global_ctx else ""

    # ── Deterministic Page State (from PageStateTracker) ───────────────────
    # This is the ground-truth view/overlay/sort state from the executor's
    # post-action DOM inspection.  Injected at the top of the <context> block.
    page_state_block = state.get("page_state_snapshot", "").strip()

    # REC 2 — Block LLM from copying raw codegen locators from Jira description
    legacy_prohibition_str = _build_legacy_code_prohibition(state)

    # REC 3 — PrimeNG body-append overlay location rule (conditional on step content)
    overlay_rule_str = _build_overlay_location_rule(state)

    # Selector RAG — RAG-driven retrieval (FEAT-042), falls back to keyword-only
    _rag_t0 = _time_mod.monotonic()
    if selector_rag is not None:
        if current_step not in _SEL_RAG_CACHE:
            try:
                _SEL_RAG_CACHE[current_step] = selector_rag.query(current_step)
            except Exception as _rag_err:
                logger.warning("Selector RAG query error (non-fatal): %s", _rag_err)
                # Fallback: keyword-only selector_registry
                if current_step not in _SEL_REG_CACHE:
                    _SEL_REG_CACHE[current_step] = selector_registry.query(current_step)
                _SEL_RAG_CACHE[current_step] = _SEL_REG_CACHE[current_step]
        selector_hints = _SEL_RAG_CACHE[current_step]
    else:
        # FEAT-042 unavailable — fall back to existing keyword-only matching
        logger.warning("Selector RAG unavailable — falling back to keyword match")
        if current_step not in _SEL_REG_CACHE:
            _SEL_REG_CACHE[current_step] = selector_registry.query(current_step)
        selector_hints = _SEL_REG_CACHE[current_step]
    # FEAT-042 Phase 4: capture retrieval telemetry for reporter stats section
    _rag_latency_ms = (_time_mod.monotonic() - _rag_t0) * 1000
    _rag_chars = len(selector_hints) if selector_hints else 0
    # Count distinct selector blocks by splitting on the section header
    _rag_entries = selector_hints.count("\n  [") if selector_hints else 0
    _RAG_TELEMETRY.append(
        {
            "step_id": f"iter-{state.get('planner_iteration', 0)}-v1",
            "entries_retrieved": _rag_entries,
            "chars_injected": _rag_chars,
            "retrieval_latency_ms": round(_rag_latency_ms, 2),
        }
    )

    # Skill Library — proven sequences (cached per step)
    skill_hints = ""
    if _skill_library:
        if current_step not in _SKILL_CACHE:
            try:
                _SKILL_CACHE[current_step] = _skill_library.query(current_step)
            except Exception as _sk_err:
                logger.debug("Skill library query error (non-fatal): %s", _sk_err)
                _SKILL_CACHE[current_step] = ""
        skill_hints = _SKILL_CACHE[current_step]

    # Playwright RAG — retrieve verified test code snippets (cached per step)
    if current_step not in _PW_RAG_CACHE:
        _PW_RAG_CACHE[current_step] = playwright_rag.query(current_step)
    playwright_context_str = _PW_RAG_CACHE[current_step]

    # Persistent memory — few-shot examples from past runs
    persistent_memory_str = _build_persistent_memory_context(state)

    # ── RAG Diagnostic Logging ────────────────────────────────────────────
    _run_id = state.get("run_id", "?")
    _ac_idx = state.get("ac_step_index", 0)

    def _rag_summary(label: str, content: str) -> None:
        if content and content.strip():
            logger.debug(
                "[%s] RAG[%d] %-20s %4d chars | %s",
                _run_id,
                _ac_idx + 1,
                label + ":",
                len(content),
                content.strip()[:120].replace("\n", " "),
            )
        else:
            logger.debug(
                "[%s] RAG[%d] %-20s EMPTY",
                _run_id,
                _ac_idx + 1,
                label + ":",
            )

    _rag_summary("kb_context", kb_context_str)
    _rag_summary("selector_hints", selector_hints)
    _rag_summary("skill_hints", skill_hints)
    _rag_summary("playwright_rag", playwright_context_str)
    _rag_summary("persistent_mem", persistent_memory_str)
    _rag_summary("human_guidance", state.get("_human_guidance_raw_", ""))

    # User guidance: ALREADY injected in <GLOBAL_HUMAN_GUIDANCE> (top/primacy)
    # and in <critical_guidance> (bottom/recency). Injecting a 3rd copy in the
    # middle <context> block wastes ~2656 chars with zero attention benefit.
    user_guidance_str = ""

    # ── Extract input_value from test_plan for the current step ──────────────
    # If the AC parser captured an explicit fill value (e.g., 'fake@email.com')
    # from the Jira ticket description, inject it as a MANDATORY INPUT VALUE
    # block so the planner types exactly that value — no inference needed.
    input_value_block = ""
    test_plan = state.get("test_plan")
    if test_plan and ac_index < ac_total:
        steps = test_plan.get("steps", [])
        if ac_index < len(steps):
            step_input_value = steps[ac_index].get("input_value")
            step_type = steps[ac_index].get("step_type", "")
            if step_input_value and step_type in ("FILL", "SELECT_DROPDOWN", "DATE_SELECT"):
                _iv_sep = "═" * 63
                if step_type == "SELECT_DROPDOWN":
                    input_value_block = (
                        "\n"
                        + _iv_sep
                        + "\n"
                        + "⛔ MANDATORY TARGET VALUE (Priority 1 — overrides all other context):\n"
                        + f'This dropdown step requires you to select EXACTLY: "{step_input_value}"\n'
                        + "DO NOT use any other value. DO NOT use action='fill' — this is a DROPDOWN.\n"
                        + "Use primeng_dropdown (preferred) or select_option with target_text set to this exact value.\n"
                        + _iv_sep
                        + "\n"
                    )
                else:
                    input_value_block = (
                        "\n"
                        + _iv_sep
                        + "\n"
                        + "⛔ MANDATORY INPUT VALUE (Priority 1 — overrides all other context):\n"
                        + f'This step requires you to enter EXACTLY this value: "{step_input_value}"\n'
                        + "DO NOT use any other value. DO NOT modify or paraphrase it.\n"
                        + "Use action='fill' with value set to this exact string.\n"
                        + _iv_sep
                        + "\n"
                    )
            elif step_type == "GHOST_LOGIN":
                # Ghost-login step handoff: ghost_login_node has already
                # authenticated as admin and landed on the product URL. Tell
                # the planner what to do with the ghost panel — describe the
                # goal semantically, no selectors, so the DOM/vision loop
                # handles product-specific UI variations.
                step_target_user = (steps[ac_index].get("target_user") or "").strip()
                _iv_sep = "═" * 63
                _target_line = (
                    f'Target user to impersonate: "{step_target_user}".'
                    if step_target_user
                    else "Target user not specified — pick a user in the visible list whose role matches the AC step (e.g. Program Director)."
                )
                input_value_block = (
                    "\n"
                    + _iv_sep
                    + "\n"
                    + "⛔ GHOST LOGIN HANDOFF (Priority 1 — admin session is already established):\n"
                    + _target_line + "\n"
                    + "Locate the 'Ghost In As' impersonation control in the top navigation "
                    + "(placeholder text 'Select Person...'). Open it, type the target user's name "
                    + "into the filter, and click the matching option. Verify success by observing "
                    + "the top-right user identity change to the target user.\n"
                    + "Do NOT navigate to a /login page. Do NOT retype admin credentials.\n"
                    + _iv_sep
                    + "\n"
                )

    # ── Recipe matching — inject ⚡ RECIPE block for matched components ——
    # Check the loaded YAML blueprints against the current AC step.
    # Only matched recipes are injected (zero bloat for unmatched steps).
    # Hot-reload is triggered automatically by recipe_registry.match().
    matched_recipes = recipe_registry.match(current_step)
    recipe_block_str = recipe_registry.format_for_prompt(matched_recipes)
    if matched_recipes:
        logger.debug(
            "[planner] Recipe match for step '%s': %s",
            current_step[:60],
            [r.name for r in matched_recipes],
        )

    # ── Phase 0: Direct Human Guidance KB scan ────────────────────────────────
    # Query with ticket_id for exact-match boosting AND keyword-overlap fallback.
    # Returns raw content — will be wrapped in <human_intervention_rules> XML below.
    human_guidance_raw = _query_human_guidance_direct(current_step, ticket_id=ticket_id)

    # ── Phase 0b: user_guidance injection into critical_guidance ─────────────
    # When the operator typed context in the "Context for AI" field before
    # starting the run, that text is in state["user_guidance"].  It is run-wide
    # global guidance (e.g. "start in List View, use column headers for sorting").
    # PROBLEM: Appending it to the <context> block (12+ other strings above it)
    # means the LLM's attention is diluted — it is effectively ignored.
    # FIX: Prepend it to human_intervention_rules so it enters the highest-weight
    # <critical_guidance> zone — same priority as HITL takeover explanations.
    user_guidance_raw = state.get("user_guidance", "").strip()
    if user_guidance_raw:
        # The full operator context is already in the GLOBAL_HUMAN_GUIDANCE block
        # at the top of the prompt (primacy zone). Here we add a short reference
        # in the recency zone so the LLM is reminded it exists without doubling tokens.
        pre_run_context_block = (
            "⭐ OPERATOR PRE-RUN CONTEXT applies here — see GLOBAL_HUMAN_GUIDANCE block at top of prompt.\n\n"
        )
        if human_guidance_raw:
            human_guidance_raw = pre_run_context_block + human_guidance_raw
        else:
            human_guidance_raw = pre_run_context_block

    human_intervention_rules = (
        human_guidance_raw if human_guidance_raw else "No specific KB rules found for this ticket and step."
    )

    # ── RAW KB RETRIEVAL GUARDRAIL ──────────────────────────────────────
    # P0 fix: log the EXACT retrieved human guidance at INFO level so it is
    # visible in production output (DEBUG is filtered by default). If empty,
    # the sentinel string tells the operator no KB data was found.
    _run_id_for_log = state.get("run_id", "?")
    if human_guidance_raw and human_guidance_raw.strip():
        logger.info(
            "[%s] RAW KB RETRIEVAL (ticket='%s', step='%s'):\n%s",
            _run_id_for_log,
            ticket_id,
            current_step[:60],
            human_guidance_raw[:600],
        )
    else:
        logger.info(
            "[%s] RAW KB RETRIEVAL: [EMPTY — No KB data found for ticket='%s', step='%s']",
            _run_id_for_log,
            ticket_id,
            current_step[:60],
        )

    # ── GLOBAL_HUMAN_GUIDANCE block ───────────────────────────────────────────
    # user_guidance_raw is the run-wide operator context typed before launch
    # (e.g. "Start in List View, use column headers for sorting").
    # It is ALSO merged into human_intervention_rules below for the critical_guidance
    # zone, but we ADDITIONALLY inject it as the very FIRST text the LLM reads in
    # a dedicated <GLOBAL_HUMAN_GUIDANCE> block so it survives budget trimming
    # (cascading trim drops <execution_history> first, then <UI_RULES> — NOT this block).
    # When no guidance is provided, the placeholder is an empty string (zero tokens).
    if user_guidance_raw:
        global_human_guidance_block = (
            "<GLOBAL_HUMAN_GUIDANCE>\n"
            "⚠️ CRITICAL PRE-FLIGHT DIRECTIVE — Read this BEFORE the AC step below:\n"
            "The operator provided the following global instructions for this entire run.\n"
            "These rules apply on EVERY step and override your default behaviour.\n\n"
            "If the guidance requires a specific starting state (e.g. 'start in list view'),\n"
            "you MUST inspect the current DOM/screenshot to verify you are in that state.\n"
            "If you are NOT in the required state, your IMMEDIATE next action MUST be to\n"
            "navigate to that state (via a recipe or direct click), regardless of what the\n"
            "current AC step says. Do NOT attempt the AC step until the prerequisite is met.\n\n"
            f"{user_guidance_raw}\n"
            "</GLOBAL_HUMAN_GUIDANCE>\n\n"
        )
    else:
        global_human_guidance_block = ""

    # MIGRATION: identity from the active AppProfile.
    try:
        from backend.profiles import get_active_profile as _gap_planner

        _app_identity = _gap_planner().identity_prompt
    except Exception:
        _app_identity = "a web application called vProMedia/vSuite by executing Acceptance Criteria from a Jira ticket"

    # Reduce history depth for step types where the agent only needs recent context.
    # CLICK_NAV / VIEW_SWITCH steps (sort clicks, column sorts) are repetitive and
    # sequential — the last 4 actions contain all relevant context.  8 items is
    # overkill and inflates token count for nothing on a 26-step sort test.
    _COMPACT_HISTORY_TYPES = {StepType.CLICK_NAV, StepType.VIEW_SWITCH, StepType.VERIFY_TEXT}
    _hist_max = 4 if _step_type in _COMPACT_HISTORY_TYPES else 8
    _action_history_str = _build_action_history(state, max_recent=_hist_max)
    _failure_diary_str = _build_failure_diary(state)
    _long_term_memory_str = _build_long_term_memory(state)

    # ── FEAT-009: Cross-run learned corrections ──────────────────────
    # Query the pattern store for known selector corrections that match
    # the current AC step. These are injected right after the failure
    # diary (high-attention zone) so the LLM avoids known-bad selectors.
    _learned_corrections_str = ""
    try:
        from backend.memory.pattern_store import get_patterns_for_step

        _learned_corrections_str = get_patterns_for_step(current_step)
    except Exception:
        pass  # Pattern store not available — proceed without

    # Append learned corrections to failure diary for injection
    if _learned_corrections_str:
        _failure_diary_str = (
            _failure_diary_str + "\n\n" + _learned_corrections_str
            if _failure_diary_str.strip()
            else _learned_corrections_str
        )

    # ── FEAT-020: past_actions XML block (inject right after failure diary) ────
    _past_actions_str = _build_past_actions_block(state)

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        global_human_guidance=global_human_guidance_block,
        app_identity=_app_identity,
        target_url=target_url,
        credential_context=credential_context,
        jira_ticket_id=ticket_id or "(unknown)",
        ac_step_number=ac_index + 1,
        ac_steps_total=ac_total,
        current_ac_step=current_step,
        human_intervention_rules=human_intervention_rules,
        role_constraints=role_constraints,
        contextual_rules=contextual_rules,
        human_execution_override=human_execution_override,
        global_run_context=global_run_context_str,
        ground_truth_tests=ground_truth_str,
        failure_diary=_failure_diary_str,
        past_actions=_past_actions_str,
        forbidden_locators=_build_forbidden_locators(state),
        self_heal_context=_build_self_heal_context(state),
        skill_hints=skill_hints,
        selector_hints=selector_hints,
        playwright_context=playwright_context_str,
        long_term_memory=_long_term_memory_str,
        persistent_memory=persistent_memory_str,
        action_history=_action_history_str,
        kb_context=(f"<UI_RULES>\n{kb_context_str}\n</UI_RULES>\n" if kb_context_str.strip() else ""),
        user_guidance=user_guidance_str,
    )

    # ── Prompt Section Size Diagnostics ─────────────────────────────────────
    _sections_diag = {
        "global_guidance": len(global_human_guidance_block),
        "rules": len(contextual_rules),
        "run_ctx": len(global_run_context_str),
        "gt_tests": len(ground_truth_str),
        "kb": len(kb_context_str),
        "history": len(_action_history_str),
        "ltm": len(_long_term_memory_str),
        "persist_mem": len(persistent_memory_str),
        "skills": len(skill_hints),
        "selectors": len(selector_hints),
        "pw_rag": len(playwright_context_str),
        "human_rules": len(human_intervention_rules),
    }
    _diag_str = " | ".join(f"{k}={v}" for k, v in _sections_diag.items() if v > 0)
    logger.info(
        "[%s] Prompt sections (chars): %s | TOTAL=%d",
        state.get("run_id", "?"),
        _diag_str,
        len(prompt),
    )

    # ── Phase 1 Hardening: Inject PageStateTracker at the top of prompt ──────
    # This deterministic DOM-derived block overrides the LLM's visual inference
    # of the current view, open overlays, and sort state.  It is placed at the
    # highest attention position (very start of the prompt) so the LLM reads
    # it first and trusts it unconditionally.
    if page_state_block:
        _sep = "\u2550" * 63
        _page_state_directive = (
            _sep
            + "\n"
            + "\u26a0\ufe0f DETERMINISTIC PAGE STATE (ground-truth from DOM inspection):\n"
            + "TRUST these values over your visual interpretation of the screenshot.\n"
            + "If <page_state> says view=compact, you ARE in compact view \u2014 do NOT navigate there.\n"
            + "If <open_overlays> shows an overlay, it IS open \u2014 do NOT click the trigger again.\n"
            + _sep
            + "\n"
            + f"{page_state_block}\n"
            + _sep
            + "\n\n"
        )
        prompt = _page_state_directive + prompt

    # ── FEAT-028: Inject Session Navigation Context (URL, Heading, History) ──
    _run_id_tracker = state.get("run_id", "?")
    _tracker = get_tracker(_run_id_tracker)
    session_ctx_block = _build_session_context_block(state, _tracker.state if _tracker else None)
    if session_ctx_block:
        prompt = session_ctx_block + "\n\n" + prompt

    if human_guidance_raw:
        if user_guidance_raw:
            logger.info(
                "[%s] PRE-RUN user_guidance ELEVATED to critical_guidance zone (%d chars) — ticket='%s' step='%s'",
                state.get("run_id", "?"),
                len(user_guidance_raw),
                ticket_id,
                current_step[:60],
            )
        else:
            logger.info(
                "[%s] Human KB injected inside <human_intervention_rules> for ticket='%s' step='%s'",
                state.get("run_id", "?"),
                ticket_id,
                current_step[:60],
            )

    # Prepend recipe block immediately after the opening of the prompt
    # so it appears in the highest-attention zone (near the AC step goal)
    # rather than buried at the end.
    if recipe_block_str:
        # ── Suppress recipe block after 2+ failures ───────────────────────────
        # After 2 failures, the recipe demonstrably hasn't solved the problem.
        # Prepending the full YAML (up to 12,709 chars) drowns out the failure
        # diary and causes Claude to repeat the same failed recipe. When suppressed,
        # a 1-line reminder informs the planner the recipe exists without bloating.
        _recipe_fail_count = state.get("ac_step_fail_counts", {}).get(
            matched_recipes[0].name if matched_recipes else "", 0
        )
        _step_total_fails = len(state.get("ac_step_failure_diary", []))

        if _step_total_fails >= 2 and _recipe_fail_count >= 1:
            recipe_names = ", ".join(r.name for r in matched_recipes) if matched_recipes else "recipe"
            suppressed_note = (
                f"[Recipe '{recipe_names}' is available but suppressed after "
                f"{_step_total_fails} failures — plan from scratch using the failure diary above.]"
            )
            prompt = suppressed_note + "\n\n" + prompt
            logger.info(
                "[planner] Recipe block suppressed after %d failures — 1-line reminder injected",
                _step_total_fails,
            )
        else:
            # Hard cap: even if not suppressed, cap recipe block at 4,000 chars.
            # Recipes can be up to 12,709 chars — anything beyond the first 4k
            # is parameter documentation the agent doesn't need on Attempt 0.
            _MAX_RECIPE_CHARS = 4000
            if len(recipe_block_str) > _MAX_RECIPE_CHARS:
                recipe_block_str = (
                    recipe_block_str[:_MAX_RECIPE_CHARS]
                    + "\n... [recipe block capped at 4,000 chars — emit the recipe JSON shown above]"
                )
            prompt = recipe_block_str + "\n\n" + prompt

    # -- Phase 1: Learned Workflow Override ----------------------------------------
    # Check learned_workflows.json for a human-recorded sequence matching the
    # current AC step. If found, prepend BEFORE everything to give it top priority.
    learned_override = _load_learned_workflow_override(current_step)
    if learned_override:
        logger.info(
            "[%s] Injecting learned workflow override for AC step '%s'",
            state.get("run_id", "?"),
            current_step[:60],
        )
        prompt = learned_override + prompt

    # human_intervention_rules are embedded in the system prompt template via
    # the {human_intervention_rules} placeholder -- no separate prepend needed.

    # ── input_value hard-constraint injection ──────────────────────────────
    # Prepend MANDATORY INPUT VALUE block immediately after the learned override
    # so it's the first thing the LLM reads for FILL steps.
    if input_value_block:
        run_id_for_log = state.get("run_id", "?")
        logger.info(
            "[%s] Injecting MANDATORY INPUT VALUE for AC step %d: '%s'",
            run_id_for_log,
            ac_index + 1,
            steps[ac_index].get("input_value", "?")[:80],
        )
        prompt = input_value_block + prompt

    # REC 2 & REC 3 — Inject prohibition and overlay rule blocks when applicable.
    # These are prepended so they appear in the highest-attention zone.
    if legacy_prohibition_str:
        prompt = legacy_prohibition_str + "\n\n" + prompt
    if overlay_rule_str:
        prompt = overlay_rule_str + "\n\n" + prompt

    # Append transient observation if available (captured immediately post-click)
    transient = state.get("transient_page_text", "").strip()
    if transient:
        prompt += (
            "\n\n═══════════════════════════════════════════════════════════════\n"
            "⚡ TRANSIENT OBSERVATION (captured immediately after the last action):\n"
            "This text was read from the page right after the previous click/keypress.\n"
            "Use it to verify notifications, toasters, alerts, and banners that may\n"
            "already be gone from the live page by the time you see the screenshot.\n"
            "═══════════════════════════════════════════════════════════════\n"
            f"{transient}\n"
            "═══════════════════════════════════════════════════════════════\n"
        )

    return prompt


def _build_system_prompt_v2(state: VQAState) -> str:
    """
    Budget-controlled system prompt builder (Phase 1 optimization).

    Uses PromptBudget to:
      - Enforce a hard token ceiling (default 8000 tokens)
      - Drop lowest-priority sections first when over budget
      - Order sections by slot position (primacy/recency aware)
      - Log dropped sections for observability

    The v2 builder reuses ALL existing helper functions — it only changes
    how sections are assembled, not what they contain.
    """
    from backend.engine.prompt_budget import PromptBudget, Slot, Tier
    from backend.engine.prompt_fragments import (
        COT_WORKFLOW,
        GOLDEN_RULES,
        JSON_OUTPUT_REMINDER,
    )

    run_id = state.get("run_id", "?")
    max_tokens = settings.prompt_budget_max_tokens
    budget = PromptBudget(max_tokens=max_tokens)

    # ── Gather all the same data as v1 ────────────────────────────────────
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    ac_total = len(ac_steps)
    current_step = ac_steps[ac_index] if ac_index < ac_total else "ALL STEPS COMPLETE"
    target_url = state.get("target_url", "https://two-test.vcreative.net")
    ticket_id = state["jira_ticket"].get("ticket_id", "")
    _step_type = classify_step(current_step)

    # Credentials
    cred_status = state.get("jira_ticket", {}).get("credential_status", "none")
    ticket_email = state.get("jira_ticket", {}).get("override_login_email", "")
    injected_email = state.get("injected_login_email", "")
    injected_password = state.get("injected_login_password", "")
    effective_email = injected_email or ticket_email
    role_email = state.get("role_context", {}).get("login_email", "")
    role_password = state.get("role_context", {}).get("login_password", "")

    # Prefer user-supplied credentials (ghost admin or override) over role/KB.
    # When the operator typed credentials into the pre-run prompt they MUST
    # take priority — the shared/KB password is fallback only.
    _run_id = state.get("run_id", "")
    _ghost_email, _ghost_password = "", ""
    if _run_id:
        try:
            from backend.engine.persona_switch_node import _ghost_creds as _gc
            _gc_entry = _gc.get(_run_id) or {}
            _ghost_email = _gc_entry.get("email") or ""
            _ghost_password = _gc_entry.get("password") or ""
        except Exception:
            pass
    effective_login_email = _ghost_email or injected_email or role_email
    effective_login_password = _ghost_password or injected_password or role_password
    _cred_source = (
        "user-supplied (ghost admin)" if _ghost_password
        else "user-supplied (override)" if injected_password
        else "role/KB"
    )
    if cred_status == "complete" and effective_email:
        credential_context = (
            f"Using ticket credentials [{_cred_source}] — "
            f"email: {effective_login_email} / password: {effective_login_password}"
        )
    elif cred_status == "partial":
        credential_context = (
            f"Partial credentials from ticket [{_cred_source}] "
            f"(email: {effective_login_email or 'email missing'} / password: {effective_login_password})"
        )
    else:
        credential_context = (
            f"Using {_cred_source} credentials — "
            f"email: {effective_login_email} / password: {effective_login_password}"
        )

    # App identity
    try:
        from backend.profiles import get_active_profile as _gap

        _app_identity = _gap().identity_prompt
    except Exception:
        _app_identity = "a web application called vProMedia/vSuite"

    # Role constraints
    role_key = state["role_context"].get("role_key", "")
    role_constraints = ""
    if role_key:
        try:
            role_constraints = get_planning_constraints_prompt(role_key)
        except KeyError:
            role_constraints = "(no role constraints loaded)"

    # ── SLOT 0: Deterministic Page State ──────────────────────────────────
    page_state_block = state.get("page_state_snapshot", "").strip()
    if page_state_block:
        _sep = "═" * 63
        budget.add(
            "page_state",
            Tier.CRITICAL,
            (
                f"{_sep}\n"
                "⚠️ DETERMINISTIC PAGE STATE (ground-truth from DOM inspection):\n"
                "TRUST these values over your visual interpretation of the screenshot.\n"
                f"{_sep}\n<PAGE_STATE>\n{page_state_block}\n</PAGE_STATE>\n{_sep}\n"
            ),
            slot=Slot.PAGE_STATE,
        )

    # ── SLOT 1: Session Navigation Context (FEAT-028) ───────────────────
    _tracker = get_tracker(run_id)
    session_ctx_block = _build_session_context_block(state, _tracker.state if _tracker else None)
    if session_ctx_block:
        budget.add("session_context", Tier.GUIDANCE, session_ctx_block, slot=Slot.SESSION_CONTEXT, max_chars=1000)

    # ── SLOT 2: Identity + Mission ────────────────────────────────────────
    budget.add(
        "identity",
        Tier.CRITICAL,
        (
            f"{GOLDEN_RULES}\n"
            "<IDENTITY>\n"
            f"You are vQA, an autonomous web testing agent testing {_app_identity}.\n"
            "You can SEE the current page via a screenshot and an interactive element tree.\n"
            "You MUST use the `plan_action` tool to execute the SINGLE NEXT browser action.\n"
            "</IDENTITY>\n\n"
            "<MISSION>\n"
            f"  <TARGET_URL>{target_url}</TARGET_URL>\n"
            f"  <CREDENTIALS>{credential_context}</CREDENTIALS>\n"
            f"  <JIRA_TICKET>{ticket_id or '(unknown)'}</JIRA_TICKET>\n"
            "</MISSION>"
        ),
        slot=Slot.IDENTITY,
    )

    # ── SLOT 4: Current AC Step (★ PRIMACY ZONE) ─────────────────────────
    # T2-e: evictable=False — the planner MUST always know the current AC step.
    budget.add(
        "current_task",
        Tier.CRITICAL,
        (
            "<CURRENT_TASK>\n"
            f'  <CURRENT_STEP number="{ac_index + 1}" total="{ac_total}">'
            f"{current_step}</CURRENT_STEP>\n"
            "</CURRENT_TASK>"
        ),
        slot=Slot.CURRENT_TASK,
        evictable=False,
    )

    # ── SLOT 5: Mandatory Input Value ────────────────────────────────────
    input_value_block = ""
    test_plan = state.get("test_plan")
    if test_plan and ac_index < ac_total:
        steps = test_plan.get("steps", [])
        if ac_index < len(steps):
            step_input_value = steps[ac_index].get("input_value")
            step_type_str = steps[ac_index].get("step_type", "")
            if step_input_value and step_type_str in ("FILL", "SELECT_DROPDOWN", "DATE_SELECT"):
                _iv_sep = "═" * 63
                if step_type_str == "SELECT_DROPDOWN":
                    input_value_block = (
                        f"\n{_iv_sep}\n"
                        f'⛔ MANDATORY TARGET VALUE: Select EXACTLY: "{step_input_value}"\n'
                        f"Use primeng_dropdown or select_option — NOT fill.\n{_iv_sep}\n"
                    )
                else:
                    input_value_block = (
                        f"\n{_iv_sep}\n"
                        f'⛔ MANDATORY INPUT VALUE: Enter EXACTLY: "{step_input_value}"\n'
                        f"Use action='fill' with this exact string.\n{_iv_sep}\n"
                    )
            elif step_type_str == "GHOST_LOGIN":
                step_target_user = (steps[ac_index].get("target_user") or "").strip()
                _iv_sep = "═" * 63
                _target_line = (
                    f'Target user to impersonate: "{step_target_user}".'
                    if step_target_user
                    else "Target user not specified — pick a user in the visible list whose role matches the AC step."
                )
                input_value_block = (
                    f"\n{_iv_sep}\n"
                    "⛔ GHOST LOGIN HANDOFF (admin session already established):\n"
                    f"{_target_line}\n"
                    "Open the 'Ghost In As' control in the top nav ('Select Person...'), "
                    "type the target user's name into the filter, and click the matching option. "
                    "Verify by observing the top-right user identity change. "
                    "Do NOT navigate to /login. Do NOT retype admin credentials.\n"
                    f"{_iv_sep}\n"
                )
    if input_value_block:
        budget.add("input_value", Tier.CRITICAL, input_value_block, slot=Slot.INPUT_VALUE)

    # ── SLOT 6: Proactive Dropdown Options (TASK-013) ────────────────────
    _injected_options = _get_matching_options(current_step, state)
    if _injected_options:
        budget.add("dropdown_options", Tier.RULES, _injected_options, slot=Slot.DROPDOWN_OPTIONS)

    # ── SLOT 8: Failure Diary + Forbidden Locators ───────────────────────
    _failure_diary_str = _build_failure_diary(state)
    if _failure_diary_str:
        budget.add("failure_diary", Tier.ACTIVE, _failure_diary_str, slot=Slot.ACTIVE_CONSTRAINTS, max_chars=3000)

    _forbidden = _build_forbidden_locators(state)
    if _forbidden:
        budget.add("forbidden_locators", Tier.ACTIVE, _forbidden, slot=Slot.ACTIVE_CONSTRAINTS)

    _self_heal = _build_self_heal_context(state)
    if _self_heal:
        budget.add("self_heal", Tier.ACTIVE, _self_heal, slot=Slot.ACTIVE_CONSTRAINTS, max_chars=1500)

    # ── FEAT-020: Past Actions XML block ─────────────────────────────────
    _past_actions_str = _build_past_actions_block(state)
    if _past_actions_str:
        budget.add("past_actions", Tier.ACTIVE, _past_actions_str, slot=Slot.ACTIVE_CONSTRAINTS, max_chars=2000)

    # ── SLOT 10: Learned Workflow Override ────────────────────────────────
    learned_override = _load_learned_workflow_override(current_step)
    if learned_override:
        budget.add("learned_workflow", Tier.GUIDANCE, learned_override, slot=Slot.LEARNED_WORKFLOW, max_chars=3000)

    # ── SLOT 12: Recipe Block ────────────────────────────────────────────
    matched_recipes = recipe_registry.match(current_step)
    recipe_block_str = recipe_registry.format_for_prompt(matched_recipes)
    if recipe_block_str:
        _step_total_fails = len(state.get("ac_step_failure_diary", []))
        _recipe_fail_count = state.get("ac_step_fail_counts", {}).get(
            matched_recipes[0].name if matched_recipes else "", 0
        )
        if _step_total_fails >= 2 and _recipe_fail_count >= 1:
            recipe_names = ", ".join(r.name for r in matched_recipes)
            recipe_block_str = (
                f"[Recipe '{recipe_names}' available but suppressed after "
                f"{_step_total_fails} failures — plan from scratch.]"
            )
        budget.add("recipe_block", Tier.GUIDANCE, recipe_block_str, slot=Slot.RECIPE_BLOCK, max_chars=4000)

    # ── SLOT 14: Global Human Guidance ───────────────────────────────────
    user_guidance_raw = state.get("user_guidance", "").strip()
    if user_guidance_raw:
        budget.add(
            "global_guidance",
            Tier.GUIDANCE,
            (
                "<GLOBAL_HUMAN_GUIDANCE>\n"
                "⚠️ CRITICAL PRE-FLIGHT DIRECTIVE — applies on EVERY step:\n"
                f"{user_guidance_raw}\n"
                "</GLOBAL_HUMAN_GUIDANCE>"
            ),
            slot=Slot.GLOBAL_GUIDANCE,
            max_chars=2000,
        )

    # ── SLOT 16: Instruction Priority ────────────────────────────────────
    budget.add(
        "instruction_priority",
        Tier.RULES,
        (
            "<instruction_priority>\n"
            "Follow in this exact order (0 = highest priority):\n"
            "  0. GROUND-TRUTH TEST    — human-written Playwright test (follow EXACTLY)\n"
            "  1. FORBIDDEN LOCATORS   — hard block, NO exceptions\n"
            "  2. FAILURE DIARY        — MUST try a different approach\n"
            "  3. HUMAN GUIDANCE       — authoritative override\n"
            "  4. SELECTOR REGISTRY    — ground-truth confirmed locators\n"
            "  5. KNOWLEDGE BASE       — vSuite domain workflow instructions\n"
            "  6. ROLE CONSTRAINTS     — apply when no higher-priority rule applies\n"
            "If a higher-priority instruction contradicts a lower one, follow the higher.\n"
            "</instruction_priority>"
        ),
        slot=Slot.INSTRUCTION_PRIORITY,
    )

    # ── SLOT 18: Role Constraints ────────────────────────────────────────
    if role_constraints:
        budget.add(
            "role_constraints",
            Tier.RULES,
            (f"<role_constraints>\n{role_constraints}\n</role_constraints>"),
            slot=Slot.ROLE_CONSTRAINTS,
            max_chars=2000,
        )

    # ── SLOT 20: Contextual Rules ────────────────────────────────────────
    contextual_rules = _select_rules(current_step, target_url)
    _parse_quality = state.get("parse_quality", "ok")
    if _parse_quality == "degraded":
        _pq_reason = state.get("parse_quality_reason", "unknown")
        contextual_rules = (
            f"⚠️ AC PARSE QUALITY: DEGRADED ({_pq_reason[:100]}). Reason carefully about step intent.\n\n"
        ) + contextual_rules

    legacy_prohibition = _build_legacy_code_prohibition(state)
    overlay_rule = _build_overlay_location_rule(state)
    rules_combined = contextual_rules
    if legacy_prohibition:
        rules_combined = legacy_prohibition + "\n" + rules_combined
    if overlay_rule:
        rules_combined = overlay_rule + "\n" + rules_combined

    budget.add(
        "contextual_rules",
        Tier.RULES,
        (f"<rules>\n{rules_combined}\n</rules>"),
        slot=Slot.CONTEXTUAL_RULES,
        max_chars=6000,
    )

    # ── SLOT 22: Locator Strategy (static) ───────────────────────────────
    budget.add(
        "locator_strategy",
        Tier.RULES,
        (
            "<locator_strategy>\n"
            "1. PRIMARY: Prefer semantic locators (get_by_role + name, or get_by_text).\n"
            "2. DISAMBIGUATION: On Strict Mode Violation → use css_selector with vqa_id.\n"
            "3. FALLBACK: get_by_role → get_by_text → css_selector\n"
            "4. ⛔ CSS BAN: :has(), :has-text(), :is(), :not(:has()) WILL FAIL.\n"
            "5. ⛔ PORTAL SCOPING: Use primeng_dropdown (preferred). Never re-click open trigger.\n"
            "</locator_strategy>"
        ),
        slot=Slot.LOCATOR_STRATEGY,
    )

    # ── SLOT 24: Available Actions (compact) ─────────────────────────────
    budget.add(
        "available_actions",
        Tier.RULES,
        (
            "<available_actions>\n"
            "primeng_dropdown | click | fill | select_option | check | uncheck\n"
            "navigate | wait | verify | scroll | press_key | set_input_files\n"
            "verify_table_sort | recipe | coordinate_action | done\n"
            "</available_actions>"
        ),
        slot=Slot.AVAILABLE_ACTIONS,
    )

    # ── SLOT 26: Few-Shot Examples (static, low priority) ────────────────
    budget.add(
        "few_shot_examples",
        Tier.STATIC,
        (
            "<few_shot_examples>\n"
            'Strict Mode → use vqa_id: {"action":"click","strategy":"css_selector","name":"[data-vqa-id=\'17\']"}\n'
            'Dropdown sort: {"action":"primeng_dropdown","trigger_selector":"th.po-col-duedaysCol p-select",'
            '"target_text":"Due Date","portal_class":".po-sorting-dropdown-panel"}\n'
            'File upload: {"action":"set_input_files","selector":"input[type=\'file\']","value":"Client Logo.jpg"}\n'
            "</few_shot_examples>"
        ),
        slot=Slot.FEW_SHOT_EXAMPLES,
    )

    # ── SLOT 28: Ground-Truth Tests ──────────────────────────────────────
    matched_tests = test_matcher.get_matching_tests(ticket_id)
    ground_truth_str = test_matcher.format_for_prompt(matched_tests)
    if ground_truth_str:
        budget.add("ground_truth_tests", Tier.GUIDANCE, ground_truth_str, slot=Slot.GROUND_TRUTH_TESTS, max_chars=3000)

    # ── SLOT 30: Global Run Context ──────────────────────────────────────
    raw_global_ctx = state.get("global_run_context", "").strip()
    if raw_global_ctx:
        budget.add("global_run_context", Tier.AMBIENT, raw_global_ctx, slot=Slot.GLOBAL_RUN_CONTEXT, max_chars=2000)

    # ── SLOT 32: RAG Context (KB + selectors + skills + playwright) ──────
    # Dynamic RAG pruning — same gating logic as v1
    kb.reload_if_updated()
    _ac_lower = current_step.lower()
    _KB_RELEVANCE_GATES: dict[str, list[str]] = {
        "sort_table": ["sort", "column", "filter", "ascending", "descending", "header", "table", "search"],
        "navigation": ["navigate", "compact", "list", "calendar", "view", "switch", "toggle", "cog", "settings"],
        "upload_file": ["upload", "file", "attach", "browse", "drag", "drop", "audio", "asset"],
        "form_input": ["fill", "enter", "type", "input", "field", "dropdown", "select", "combobox"],
        "order_flow": ["order", "quick", "submit", "approve", "status", "draft", "campaign", "production", "spot"],
        "auth_login": ["login", "sign", "credential", "password", "email", "auth", "logout"],
    }
    _kb_gate_matched = any(any(kw in _ac_lower for kw in keywords) for keywords in _KB_RELEVANCE_GATES.values())

    # Product context — same as SLOT 5 call site above.
    _active_product_kb_v2 = state.get("active_product") or state.get("product_slug") or state.get("product") or None

    if _kb_gate_matched:
        kb_context_str = kb.query_with_expansion(current_step, product=_active_product_kb_v2)
    else:
        kb_context_str = ""

    # Failure-specific KB (replace, don't stack)
    retry_count = state.get("retry_count", 0)
    last_error = state.get("last_error", "").strip()
    if retry_count >= 1 and last_error:
        last_action_log = state.get("detailed_execution_log", [])
        last_action_desc = ""
        if last_action_log:
            last = last_action_log[-1]
            last_action_desc = f"{last.get('action_type', '')} {last.get('locator_value', '')}"
        failure_kb = kb.query_for_failure(ac_step=current_step, error_message=last_error, last_action=last_action_desc)
        if failure_kb:
            kb_context_str = failure_kb

    if kb_context_str.strip():
        budget.add(
            "kb_context", Tier.RAG, f"<UI_RULES>\n{kb_context_str}\n</UI_RULES>", slot=Slot.RAG_CONTEXT, max_chars=3000
        )

    # Selector hints — FEAT-042: RAG-driven retrieval replaces keyword-only query
    _rag2_t0 = _time_mod.monotonic()
    if selector_rag is not None:
        if current_step not in _SEL_RAG_CACHE:
            try:
                _SEL_RAG_CACHE[current_step] = selector_rag.query(current_step)
            except Exception as _rag_err:
                logger.warning("Selector RAG query error (non-fatal): %s", _rag_err)
                if current_step not in _SEL_REG_CACHE:
                    _SEL_REG_CACHE[current_step] = selector_registry.query(current_step)
                _SEL_RAG_CACHE[current_step] = _SEL_REG_CACHE[current_step]
        selector_hints = _SEL_RAG_CACHE[current_step]
    else:
        logger.warning("Selector RAG unavailable — falling back to keyword match")
        if current_step not in _SEL_REG_CACHE:
            _SEL_REG_CACHE[current_step] = selector_registry.query(current_step)
        selector_hints = _SEL_REG_CACHE[current_step]
    # FEAT-042 Phase 4: capture retrieval telemetry (second injection site)
    _rag2_latency_ms = (_time_mod.monotonic() - _rag2_t0) * 1000
    _rag2_chars = len(selector_hints) if selector_hints else 0
    _rag2_entries = selector_hints.count("\n  [") if selector_hints else 0
    _RAG_TELEMETRY.append(
        {
            "step_id": f"iter-{state.get('planner_iteration', 0)}-v2",
            "entries_retrieved": _rag2_entries,
            "chars_injected": _rag2_chars,
            "retrieval_latency_ms": round(_rag2_latency_ms, 2),
        }
    )
    if selector_hints:
        # T2-e: evictable=False — interactive element context (selector hints)
        # must survive budget pressure so the planner can locate UI targets.
        budget.add("selector_hints", Tier.RAG, selector_hints, slot=Slot.RAG_CONTEXT, max_chars=1500, evictable=False)

    # Skill hints
    skill_hints = ""
    if _skill_library:
        if current_step not in _SKILL_CACHE:
            try:
                _SKILL_CACHE[current_step] = _skill_library.query(current_step)
            except Exception:
                _SKILL_CACHE[current_step] = ""
        skill_hints = _SKILL_CACHE[current_step]
    if skill_hints:
        # T2-e: evictable=False — skill hints guide step-type execution;
        # losing them under budget pressure degrades action quality.
        budget.add("skill_hints", Tier.RAG, skill_hints, slot=Slot.RAG_CONTEXT, max_chars=1500, evictable=False)

    # Playwright RAG
    if current_step not in _PW_RAG_CACHE:
        _PW_RAG_CACHE[current_step] = playwright_rag.query(current_step)
    pw_context = _PW_RAG_CACHE[current_step]
    if pw_context:
        budget.add("playwright_rag", Tier.RAG, pw_context, slot=Slot.RAG_CONTEXT, max_chars=1500)

    # ── SLOT 34: Action History ──────────────────────────────────────────
    # TASK-015 Bug 5 fix: Use Tier.HISTORY (not Tier.ACTIVE) so that
    # execution history is dropped BEFORE domain context (Tier.RAG) when
    # budget is tight.  This preserves the KB/domain knowledge the planner
    # needs to avoid repeating mistakes, while trimming older history entries
    # that are less critical for correct action planning.
    _COMPACT_HISTORY_TYPES = {StepType.CLICK_NAV, StepType.VIEW_SWITCH, StepType.VERIFY_TEXT}
    _hist_max = 4 if _step_type in _COMPACT_HISTORY_TYPES else 8
    _action_history = _build_action_history(state, max_recent=_hist_max)
    budget.add(
        "execution_history",
        Tier.HISTORY,
        f"<execution_history>\n{_action_history}\n</execution_history>",
        slot=Slot.EXECUTION_HISTORY,
        max_chars=3000,
    )

    # ── SLOT 36: Memory (long-term + persistent) ─────────────────────────
    _ltm = _build_long_term_memory(state)
    if _ltm:
        budget.add("long_term_memory", Tier.AMBIENT, _ltm, slot=Slot.MEMORY, max_chars=1500)

    persistent_mem = _build_persistent_memory_context(state)
    if persistent_mem:
        budget.add("persistent_memory", Tier.AMBIENT, persistent_mem, slot=Slot.MEMORY, max_chars=1500)

    # ── SLOT 50: Reasoning Workflow ──────────────────────────────────────
    # Only inject the full sort-specific reasoning for relevant step types;
    # otherwise use a compact version
    _SORT_TYPES = {"click_action", "click_nav", "dropdown", "navigate", "compound", "date_picker", "view_switch"}
    human_execution_override = ""
    if _step_type.value in _SORT_TYPES:
        human_execution_override = f"\n<SORT_RULES>\n{_SORT_EXECUTION_OVERRIDE}\n</SORT_RULES>"

    # T2-e: evictable=False — the planner's thinking framework must survive
    # budget pressure; losing it is worse than losing retry noise.
    budget.add(
        "reasoning_workflow",
        Tier.STATIC,
        COT_WORKFLOW.replace("</MANDATORY_REASONING_WORKFLOW>", f"{human_execution_override}\n</MANDATORY_REASONING_WORKFLOW>"),
        slot=Slot.REASONING_WORKFLOW,
        evictable=False,
    )

    # ── SLOT 52: Schema Rule ─────────────────────────────────────────────
    budget.add(
        "schema_rule",
        Tier.CRITICAL,
        (
            "<CRITICAL_SCHEMA_RULE>\n"
            "You MUST include `kb_acknowledgement` in your JSON payload.\n"
            "Summarize active rules from human_intervention_rules or UI_RULES.\n"
            'If none apply: "No KB rules for this step."\n'
            "</CRITICAL_SCHEMA_RULE>"
        ),
        slot=Slot.SCHEMA_RULE,
    )

    # ── SLOT 54: Critical Guidance (RECENCY ZONE) ────────────────────────
    human_guidance_raw = _query_human_guidance_direct(current_step, ticket_id=ticket_id)
    if user_guidance_raw:
        pre_run_ref = "⭐ OPERATOR PRE-RUN CONTEXT applies — see GLOBAL_HUMAN_GUIDANCE above.\n\n"
        human_guidance_raw = pre_run_ref + (human_guidance_raw or "")

    human_intervention = (
        human_guidance_raw if human_guidance_raw else "No specific KB rules found for this ticket and step."
    )
    budget.add(
        "critical_guidance",
        Tier.GUIDANCE,
        (
            "<CRITICAL_GUIDANCE>\n"
            "HUMAN-VERIFIED rules for this ticket and step (highest practical weight):\n"
            f"<HUMAN_INTERVENTION_RULES>\n{human_intervention}\n</HUMAN_INTERVENTION_RULES>\n"
            "</CRITICAL_GUIDANCE>"
        ),
        slot=Slot.CRITICAL_GUIDANCE,
        max_chars=3000,
    )

    # ── SLOT 56: Transient Observation ───────────────────────────────────
    transient = state.get("transient_page_text", "").strip()
    if transient:
        budget.add(
            "transient_obs",
            Tier.ACTIVE,
            (
                "═" * 63 + "\n"
                "⚡ TRANSIENT OBSERVATION (captured immediately after last action):\n"
                f"<TRANSIENT_OBS>\n{transient}\n</TRANSIENT_OBS>\n" + "═" * 63
            ),
            slot=Slot.TRANSIENT_OBS,
            max_chars=1500,
        )

    # ── SLOT 60: Final Reminder (Anchoring) ──────────────────────────────
    budget.add(
        "final_reminder",
        Tier.CRITICAL,
        GOLDEN_RULES + "\n" + JSON_OUTPUT_REMINDER,
        slot=Slot.FINAL_REMINDER,
    )

    # ── Assemble with budget enforcement ─────────────────────────────────
    prompt, included, dropped = budget.assemble(run_id=run_id)

    # Log diagnostics
    logger.info(
        "[%s] PromptBudget v2: %d sections (%d tokens), dropped=%s",
        run_id,
        len(included),
        len(prompt) // 4,
        dropped if dropped else "none",
    )

    # Emit metrics if available
    metrics = _get_metrics_for_run(run_id)
    if metrics:
        try:
            metrics.record_prompt_budget(
                total_tokens=len(prompt) // 4,
                included_sections=included,
                dropped_sections=dropped,
            )
        except Exception:
            pass  # metrics are best-effort

    return prompt


def _dispatch_build_system_prompt(state: VQAState) -> str:
    """
    Dispatch to v1 or v2 system prompt builder based on settings.

    When ``settings.prompt_budget_enabled`` is True, uses the budget-controlled
    v2 builder. Otherwise falls back to the legacy v1 builder.
    """
    if settings.prompt_budget_enabled:
        return _build_system_prompt_v2(state)
    return _build_system_prompt(state)


# ---------------------------------------------------------------------------
# Pre-Snapshot Stability Gate
# ---------------------------------------------------------------------------


async def _wait_for_page_stability(page, timeout_ms: int = 10000) -> dict:
    """
    Wait for known blocking page states to resolve BEFORE capturing the
    screenshot that the LLM will reason about.

    Design Constraints
    ------------------
    - Does NOT use ``networkidle`` — vSuite has background polling that
      keeps the network permanently non-idle, causing perpetual timeouts.
    - Only waits for KNOWN, explicitly-named PrimeNG/vSuite blocking elements.
    - If no blocking elements are found, returns immediately (zero added latency).
    - Each spinner/modal check is wrapped in try/except — a failed selector
      lookup never crashes the planner.

    Blocking Elements Checked
    -------------------------
    1. PrimeNG data table loading overlay (.p-datatable-loading-overlay)
    2. vCreative loading icon (.vcreative-icon.loading)
    3. Generic loading overlay (.loading-overlay)
    4. PrimeNG block UI (.p-blockui) — used during save/submit operations
    5. Angular CDK overlay backdrop (.cdk-overlay-backdrop) — modals
    6. PrimeNG dialog mask (.p-dialog-mask) — p-dialog open state

    Returns
    -------
    dict
        Observation dict injected into the planner prompt as a context note:
        {
            "spinner_cleared": bool,   — True if a spinner was found and waited out
            "modal_detected": bool,    — True if a modal overlay is currently open
            "wait_ms": int,            — total milliseconds spent waiting
        }
    """
    import time as _time

    start = _time.monotonic()
    result = {"spinner_cleared": False, "modal_detected": False, "wait_ms": 0}

    # ── Stage 1: Known spinner/loading selectors — wait for detach ────────
    # These BLOCK the agent from interacting with the page correctly.
    # We wait up to timeout_ms for them to detach before snapping the screenshot.
    VSUITE_SPINNER_SELECTORS = [
        ".p-datatable-loading-overlay",  # PrimeNG table loading
        ".vcreative-icon.loading",  # vCreative custom spinner
        ".loading-overlay",  # Generic overlay
        ".p-blockui",  # PrimeNG block UI (save/submit)
        ".p-blockui-document",  # Full-page block
    ]

    for sel in VSUITE_SPINNER_SELECTORS:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            if count > 0:
                is_visible = await loc.first.is_visible()
                if is_visible:
                    logger.info(
                        "[planner-gate] Spinner detected: '%s' — waiting for detach (timeout=%dms)",
                        sel,
                        timeout_ms,
                    )
                    await page.wait_for_selector(sel, state="detached", timeout=timeout_ms)
                    result["spinner_cleared"] = True
                    logger.info("[planner-gate] Spinner '%s' cleared", sel)
        except Exception as e:
            # Timeout or selector error — log at DEBUG level and continue
            # (a stuck spinner will cause the LLM to see it in the screenshot)
            logger.debug("[planner-gate] Spinner wait failed for '%s': %s", sel, str(e)[:80])

    # ── Stage 2: Modal/overlay detection — informational only ─────────────
    # We do NOT wait for modals to close — the LLM should interact WITH them.
    # We just note their presence so the prompt can warn the LLM.
    MODAL_SELECTORS = [
        ".p-dialog-mask",  # PrimeNG dialog backdrop
        ".p-sidebar-mask",  # PrimeNG sidebar backdrop
        ".cdk-overlay-backdrop",  # Angular CDK (material dialogs, overlays)
        "p-confirmdialog",  # PrimeNG confirm dialog component
    ]

    for sel in MODAL_SELECTORS:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            if count > 0 and await loc.first.is_visible():
                result["modal_detected"] = True
                logger.info("[planner-gate] Modal/overlay detected: '%s'", sel)
                break
        except Exception:
            pass

    result["wait_ms"] = int((_time.monotonic() - start) * 1000)
    return result


# ---------------------------------------------------------------------------
# Bedrock Tool Calling Client
# ---------------------------------------------------------------------------


async def _invoke_planner_with_tools(
    system_prompt: str,
    user_content: list[dict],
    is_retry: bool = False,
    retry_count: int = 0,
    is_verifier_rejected: bool = False,
    run_metrics: "RunMetrics | None" = None,
) -> dict:
    """
    Call Claude via the Bedrock ``converse`` API with ``tool_use`` enforcement.

    This replaces the ``ChatBedrockConverse`` + ``_parse_llm_response`` pipeline
    for the primary planning call.  Key differences from the old approach:

    - ``toolConfig`` with ``toolChoice={"tool": {"name": "plan_action"}}`` forces
      Claude to ALWAYS call the ``plan_action`` tool — it cannot return free-form
      text or omit required fields.
    - The response is validated by ``PlannerAction.model_validate()`` (Pydantic).
      Cross-field rules (e.g., ``get_by_role`` requires ``role`` + ``name``) are
      enforced at the schema level, not in downstream Python validators.
    - On validation failure, a brief error message is appended to ``messages``
      and the call is retried up to ``MAX_TOOL_RETRIES`` times.
    - Falls back to the legacy ``ChatBedrockConverse`` path if the tool call
      response is structurally unexpected (e.g., Bedrock API version mismatch).

    Auto-Escalation
    ---------------
    When ``retry_count >= settings.auto_escalate_threshold`` (and threshold > 0),
    the model is automatically upgraded from Haiku to Sonnet for more capable
    reasoning on complex self-heal retries.

    Args
    ----
    system_prompt : str
        The assembled system prompt string.
    user_content : list[dict]
        Multimodal user message content (image + text blocks).
    is_retry : bool
        When True, uses temperature=0.2 to introduce variance.
    retry_count : int
        Current retry count for the AC step.  Used for auto-escalation.
    is_verifier_rejected : bool
        True if recovering from a VERIFIER_REJECTED state.

    Returns
    -------
    dict
        The validated action dict (from ``PlannerAction.model_dump()``) ready
        to be stored as ``planned_action`` in ``VQAState``.

    Raises
    ------
    RuntimeError
        If the tool call response is malformed after all retries.
    """
    import boto3

    from backend.engine.schemas import PLANNER_TOOL_CONFIG, PlannerAction

    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_bedrock_region)

    temperature = 0.2 if is_retry else 0.0
    MAX_TOOL_RETRIES = 2

    # ── FEAT-060-P1A: ModelRouter — three-tier action-aware routing ────
    # Replaces the manual escalation-only check. Routes deterministic
    # actions (click, fill, navigate) to Haiku (Tier 1) and planning/
    # disambiguation actions to Sonnet (Tier 2). Preserves the existing
    # auto-escalation behavior when model_router_enabled=False.
    from backend.engine.model_router import get_model_router

    _router = get_model_router()
    # action_type is only available after the Bedrock call — for pre-call
    # routing we use the retry_count signal. is_retry → minimum Tier 2.
    model_id = _router.get_model_id(
        action_type="verify" if is_retry else "click",
        confidence_score=1.0,
        retry_count=retry_count,
        is_verifier_rejected=is_verifier_rejected,
    )
    use_heavy = model_id == settings.bedrock_model_id_heavy

    # ── FEAT-060-P2A: Prompt Caching — static system prompt cachePoint ─
    # Split the system prompt into a cached static block (tool schemas,
    # global rules) and a plain dynamic block. When disabled, falls back
    # to the original single-block format (pre-FEAT-060 behavior).
    from backend.engine.prompt_cache import get_prompt_cache_builder

    _cache_builder = get_prompt_cache_builder()
    # The full assembled system_prompt is treated as static for caching
    # purposes — it changes per AC step but rarely between consecutive
    # turns on the same step. The Bedrock cache TTL (5 min default) covers
    # the typical planner retry window.
    _system_blocks = _cache_builder.to_bedrock_system(
        static_content=system_prompt,
        dynamic_content="",
    )

    # Build the messages list in Bedrock converse format
    messages: list[dict] = [
        {
            "role": "user",
            "content": user_content,
        }
    ]

    for attempt in range(1 + MAX_TOOL_RETRIES):
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock.converse(
                    modelId=model_id,
                    system=_system_blocks,
                    messages=messages,
                    toolConfig=PLANNER_TOOL_CONFIG,
                    inferenceConfig={
                        "maxTokens": 1024,
                        "temperature": temperature,
                    },
                ),
            )

            # Extract the tool_use block from the response
            output_message = response["output"]["message"]
            tool_input = None
            for block in output_message.get("content", []):
                if block.get("toolUse", {}).get("name") == "plan_action":
                    tool_input = block["toolUse"]["input"]
                    break

            if tool_input is None:
                raise ValueError(
                    f"Claude did not call plan_action tool (attempt {attempt + 1}). "
                    f"Response content: {output_message.get('content', [])[:3]}"
                )

            # Validate with Pydantic — raises ValueError with field-specific messages
            action = PlannerAction.model_validate(tool_input)
            logger.debug(
                "[planner] Tool calling succeeded (attempt %d): action=%s",
                attempt + 1,
                action.action,
            )

            # ── Phase 4A: Record LLM metrics ─────────────────────
            if run_metrics is not None:
                try:
                    usage = response.get("usage", {})
                    latency = response.get("metrics", {}).get("latencyMs", 0)
                    run_metrics.record_llm_call(
                        purpose="planner",
                        model_id=model_id,
                        input_tokens=usage.get("inputTokens", 0),
                        output_tokens=usage.get("outputTokens", 0),
                        latency_ms=latency,
                        was_escalation=use_heavy,
                    )
                except Exception:
                    pass  # Best-effort — never fail the planner

            return action.model_dump()

        except Exception as e:
            error_str = str(e)
            logger.warning(
                "[planner] Tool call attempt %d failed: %s",
                attempt + 1,
                error_str[:200],
            )

            if attempt < MAX_TOOL_RETRIES:
                # Bedrock requires that every tool_use block in an assistant message
                # is immediately followed by a tool_result block in the next user
                # message.  Failing to do this causes:
                #   "tool_use ids were found without tool_result blocks"
                # Build a proper tool_result user message from the failed attempt.
                assistant_content = (
                    output_message.get("content", []) if "output_message" in locals() else [{"text": "(no response)"}]
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                # Build the tool_result content for any toolUse blocks present
                tool_result_content = []
                for blk in assistant_content:
                    tool_use_blk = blk.get("toolUse", {})
                    if tool_use_blk.get("toolUseId"):
                        tool_result_content.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_blk["toolUseId"],
                                    "content": [{"text": f"Error: {error_str[:200]}. Please try again."}],
                                    "status": "error",
                                }
                            }
                        )
                if not tool_result_content:
                    # No tool_use blocks — just append a plain correction message
                    tool_result_content = [
                        {
                            "text": (
                                f"\n\n⚠ TOOL CALL ERROR (attempt {attempt + 1}):\n{error_str[:300]}\n\n"
                                "Please fix the error and call plan_action again with a corrected response."
                            )
                        }
                    ]
                messages.append(
                    {
                        "role": "user",
                        "content": tool_result_content,
                    }
                )
            else:
                raise RuntimeError(f"Planner tool call failed after {MAX_TOOL_RETRIES + 1} attempts: {error_str}")

    # Should never reach here
    raise RuntimeError("Unexpected exit from _invoke_planner_with_tools retry loop")


# ---------------------------------------------------------------------------
# LLM client (legacy fallback — auto-escalation aware)
# ---------------------------------------------------------------------------


def _get_llm(
    is_retry: bool = False,
    retry_count: int = 0,
    is_verifier_rejected: bool = False,
) -> ChatBedrockConverse:
    """
    Create an LLM client for the planner.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Supports auto-escalation from Haiku to Sonnet when ``retry_count``
    crosses ``settings.auto_escalate_threshold`` or on verifier rejection (FEAT-066).

    Args
    ----
    is_retry : bool
        When True (self-heal retry, fail_count >= 2), uses temperature=0.2
        to introduce variance in the planner's action selection.
    retry_count : int
        Current retry count for the AC step.
    is_verifier_rejected : bool
        True if recovering from a VERIFIER_REJECTED state.

    Returns
    -------
    ChatBedrockConverse
        A LangChain chat model configured with the Bedrock model ID
        and region from settings.
    """
    temperature = 0.2 if is_retry else 0.0
    from backend.engine.model_router import get_model_router
    from backend.llm import get_llm

    _router = get_model_router()
    # For legacy fallback path, we use the same Tier 1 vs Tier 2 logic
    model_id = _router.get_model_id(
        action_type="verify" if is_retry else "click",
        confidence_score=1.0,
        retry_count=retry_count,
        is_verifier_rejected=is_verifier_rejected,
    )
    use_heavy = model_id == settings.bedrock_model_id_heavy

    if use_heavy:
        logger.info(
            "AUTO-ESCALATION (fallback path): retry_count=%d, verifier_rejected=%s — switching to heavy model",
            retry_count,
            is_verifier_rejected,
        )
    return get_llm("planner", heavy=use_heavy, temperature=temperature, max_tokens=1024)


def _parse_llm_response(raw_text: str) -> tuple[dict[str, Any], str, str]:
    """
    Parse the LLM's raw text response into action dict + ReAct fields.

    Handles three formats:
      1. Single JSON object: {"action": "click", ...} — standard single action
      2. JSON array: [{"action": "fill", ...}, {"action": "click", ...}]
         — BATCHED actions; returns a _batch sentinel dict
      3. Legacy format (no observation/thought) — backwards compat

    Returns
    -------
    tuple[dict[str, Any], str, str]
        (action_dict, observation, thought)
        For batched responses, action_dict["_batch"] is the list of actions.

    Raises
    ------
    ValueError
        If the response cannot be parsed as valid JSON.
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    def _extract_react(item: dict) -> tuple[str, str]:
        """Pop observation/thought from a single action dict."""
        obs = item.pop("observation", "") or ""
        tht = item.pop("thought", "") or ""
        return str(obs)[:300], str(tht)[:300]

    def _handle_parsed(parsed):
        """Normalise a parsed JSON value to (action_dict, obs, thought)."""
        if isinstance(parsed, list):
            if not parsed:
                raise ValueError("LLM returned an empty JSON array")
            # Extract ReAct fields from first item; they're shared for the batch
            first = parsed[0] if isinstance(parsed[0], dict) else {}
            obs, tht = _extract_react(first)
            # Build a sentinel dict that the planner_node unwraps into planned_actions
            batch_dict = {"_batch": parsed}
            return batch_dict, obs, tht
        if isinstance(parsed, dict):
            obs, tht = _extract_react(parsed)
            return parsed, obs, tht
        raise ValueError(f"Expected JSON object or array, got {type(parsed).__name__}")

    # ── Strategy 1: direct parse ──────────────────────────────────────
    try:
        parsed = json.loads(text)
        return _handle_parsed(parsed)
    except json.JSONDecodeError:
        pass

    # ── Strategy 2: extract JSON from surrounding text ────────────────
    import re

    # Try array first, then object (array is less common but important now)
    array_match = re.search(r"\[[\s\S]*?\]", text, re.DOTALL)
    obj_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)

    for match in filter(None, [array_match, obj_match]):
        try:
            parsed = json.loads(match.group())
            return _handle_parsed(parsed)
        except (json.JSONDecodeError, ValueError):
            continue

    # ── Strategy 3: JSON auto-repair (truncated output) ──────────────
    repaired = _repair_truncated_json(text)
    if repaired != text:
        try:
            parsed = json.loads(repaired)
            result = _handle_parsed(parsed)
            logger.warning("LLM JSON was truncated and auto-repaired. Consider increasing max_tokens if this recurs.")
            return result
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError(f"Failed to parse LLM response as JSON. Raw response: {raw_text[:300]}")


def _repair_truncated_json(text: str) -> str:
    """
    Auto-close truncated JSON produced when the LLM hits its max_token limit.

    Handles the most common truncation pattern: the JSON object is cut off
    mid-string or mid-field, leaving unclosed brackets/braces and unterminated
    string literals.  Applies minimal surgery:
      1. Strip trailing partial key/value (anything after last complete ":" + value pair)
      2. Auto-close open string literals
      3. Auto-close open arrays and objects in reverse order

    Returns the repaired string, or the original if repair is impossible.
    """
    text = text.strip()
    if not text:
        return text

    # Track open bracket/brace depth
    depth: list[str] = []
    in_string = False
    escaped = False
    last_value_end = 0  # position after last complete value

    i = 0
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif in_string:
            if ch == '"':
                in_string = False
                last_value_end = i + 1
        else:
            if ch == '"':
                in_string = True
            elif ch in ("{", "["):
                depth.append(ch)
            elif ch in ("}", "]"):
                if depth:
                    depth.pop()
                last_value_end = i + 1
        i += 1

    # If still in a string, close it
    result = text[:last_value_end] if last_value_end < len(text) else text
    if in_string:
        result += '"'

    # Close any unclosed brackets/objects
    for opener in reversed(depth):
        result += "}" if opener == "{" else "]"

    return result


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def planner_node(state: VQAState) -> dict:
    """
    LangGraph node: SEE-THINK phase of the see-think-act loop.

    This function is registered as a node in the StateGraph.  It:

    1. Retrieves the active Playwright page from the browser manager
    2. Captures a fresh screenshot (base64 PNG)
    3. Extracts the accessibility tree (ARIA roles + names)
    4. Builds a multimodal prompt with AC step + role constraints
    5. Calls Claude 3.5 Sonnet via Bedrock
    6. Parses the JSON action from Claude's response
    7. Returns the partial state update

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update containing:
        - ``planned_action``: the JSON action dict from Claude
        - ``current_screenshot_b64``: the latest screenshot
        - ``current_accessibility_tree``: the latest a11y tree
        - ``planner_iteration``: incremented by 1

    Note: ReAct observation and thought fields are parsed from the LLM
    response inside _planner_node_inner and passed to the executor.

    Raises
    ------
    ValueError
        If Claude's response cannot be parsed as a valid JSON action.

    KeyError
        If no BrowserManager is registered for the current run_id.
    """
    run_id = state["run_id"]
    iteration = state.get("planner_iteration", 0) + 1

    # BUG-002 fix: clear stale RAG caches at the start of each new run
    if iteration == 1:
        clear_rag_caches()

    logger.info(
        "[%s] Planner iteration %d — AC step %d/%d",
        run_id,
        iteration,
        state.get("ac_step_index", 0) + 1,
        len(state["jira_ticket"].get("acceptance_criteria_steps", [])),
    )

    # ── Top-level TargetClosedError boundary ────────────────────────────────────
    # planner_node touches: screenshot, a11y tree, page.evaluate (text snapshot),
    # extract_interactive_summary, _wait_for_page_stability.
    # ALL of these raise playwright.TargetClosedError when the page is gone.
    # Rather than individually guarding 10+ call sites, catch at the node boundary
    # and re-raise as a RuntimeError whose message matches the keywords in the
    # _execute_run._is_page_closed detector (“browser has been closed”).
    # This converts the 200-line LangGraph “During task with name 'planner'”
    # trace into a single clean WARNING log line.
    try:
        return await _planner_node_inner(state, run_id, iteration)
    except Exception as _top_err:
        _top_msg = str(_top_err).lower()
        _PAGE_CLOSED_KEYWORDS = (
            "target closed",
            "targetclosederror",
            "target page",
            "browser has been closed",
            "context was destroyed",
            "page is closed",
        )
        if any(kw in _top_msg for kw in _PAGE_CLOSED_KEYWORDS):
            raise RuntimeError(
                f"[{run_id}] Browser page closed during planning — run was cancelled or browser shut down. "
                f"Routing to reporter for partial results."
            ) from None  # suppress original TargetClosedError traceback
        raise  # re-raise genuine unexpected errors unchanged


async def _planner_node_inner(state: VQAState, run_id: str, iteration: int) -> dict:
    """
    Internal implementation of planner_node, extracted so the outer
    function can apply a clean top-level TargetClosedError boundary.
    Contains the full SEE-THINK logic (screenshot, a11y, LLM call, etc.).
    """
    # ── Step 1: Get the live browser page ──────────────────────────────
    manager = get_manager(run_id)
    page = manager.page
    if page is None:
        raise RuntimeError(f"[{run_id}] Browser page is None — session may have closed")

    # ── Guard: page.is_closed() ────────────────────────────────────────
    # A cancelled run or user-closed browser leaves manager.page non-None
    # but the underlying Playwright target closed. Without this check the
    # code falls into asyncio.gather(screenshot, a11y) which raises
    # TargetClosedError and crashes the LangGraph task with a 200-line trace.
    try:
        if page.is_closed():
            raise RuntimeError(
                f"[{run_id}] Browser page is closed — run was cancelled or browser shut down. "
                f"Routing to reporter for partial results."
            )
    except RuntimeError:
        raise  # re-raise our own RuntimeError
    except Exception as _page_probe_err:
        raise RuntimeError(
            f"[{run_id}] Could not probe page state ({_page_probe_err}) — assuming closed, routing to reporter."
        ) from _page_probe_err

    # ── Step 2 + 3: SEE — capture screenshot and a11y tree in parallel ──
    # Capturing the viewport screenshot and extracting the accessibility
    # tree are independent async I/O operations; running them concurrently
    # saves ~300-400ms per planner call.
    #
    # For 'done' actions the page hasn't changed — reuse the cached
    # screenshot to skip an unnecessary capture round-trip.
    action_type = state.get("planned_action", {}).get("action", "")

    # ── Pre-Snapshot Stability Gate ───────────────────────────────────
    # Wait for known blocking page states (PrimeNG spinners, blockUI) to
    # resolve BEFORE capturing the screenshot the LLM will reason about.
    # This prevents the "agent tries to click through a spinner" failure mode.
    # Does NOT use networkidle — vSuite has background polling that keeps
    # the network permanently busy.
    try:
        stability_obs = await _wait_for_page_stability(page)
    except Exception as _stab_err:
        _stab_msg = str(_stab_err).lower()
        if any(kw in _stab_msg for kw in ("target closed", "browser has been closed", "context was destroyed")):
            raise RuntimeError(
                f"[{run_id}] Page closed during stability gate — run was cancelled or browser shut down."
            ) from _stab_err
        stability_obs = {"wait_ms": 0, "spinner_cleared": False, "modal_detected": False}

    if stability_obs["wait_ms"] > 50:
        logger.info(
            "[%s] Stability gate: spinner_cleared=%s, modal=%s, waited=%dms",
            run_id,
            stability_obs["spinner_cleared"],
            stability_obs["modal_detected"],
            stability_obs["wait_ms"],
        )

    # ── First-Iteration Hydration Re-Check ────────────────────────────
    # FIX: On iteration 1, the SPA dashboard may have passed the login_node
    # SPA barrier (router-outlet siblings exist) but the actual interactive
    # content (nav bar, table rows, action buttons) hasn't rendered yet.
    # The a11y tree then returns only 3-5 generic elements and the LLM
    # hallucinates being on the login page, planning fill→Email on an
    # already-authenticated dashboard.
    #
    # Wait for the interactive element count to exceed 15 (a loaded
    # vSuite dashboard always has nav + sidebar + table = 50+ elements).
    # This costs ~1-2s on a slow machine but eliminates the login
    # hallucination entirely.
    if iteration == 1:
        try:
            await page.wait_for_function(
                """
                () => {
                    const els = document.querySelectorAll(
                        'button:not([disabled]), a[href], input:not([disabled]), '
                        + '[role="button"], [role="link"], [role="menuitem"]'
                    );
                    return els.length > 15;
                }
                """,
                timeout=8000,
            )
            logger.info(
                "[%s] First-iteration hydration check passed (>15 interactive elements)",
                run_id,
            )
        except Exception:
            logger.warning(
                "[%s] First-iteration hydration check timed out — "
                "page may have fewer interactive elements than expected",
                run_id,
            )

        # Phase 3 (accessibility-tree-grounding): ARIA enrichment of TestPlanStep
        # fields from the live ARIA snapshot.  Runs once on first planner entry
        # (post-login, post-hydration) when settings.a11y_enrichment_enabled=True.
        # No-op when disabled — zero behavior change for existing runs.
        if settings.a11y_enrichment_enabled:
            _test_plan = state.get("test_plan")
            if _test_plan and page is not None:
                try:
                    from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria
                    await enrich_test_plan_with_aria(page, _test_plan, run_id=run_id)
                    logger.debug("[%s] ac_aria_enricher: first-entry enrichment complete.", run_id)
                except Exception as _enrich_exc:
                    # Enrichment failure is non-fatal — log and continue.
                    logger.warning(
                        "[%s] ac_aria_enricher: enrichment raised %s — proceeding without ARIA enrichment.",
                        run_id,
                        str(_enrich_exc)[:120],
                    )

    try:
        if action_type == "done" and state.get("current_screenshot_b64"):
            screenshot_b64 = state["current_screenshot_b64"]
            a11y_tree = await extract_accessibility_tree(page)
        else:
            # Viewport-only for LLM (faster, fewer tokens, same visual context
            # for login/form flows that fit in one screen). Full-page capture
            # is handled separately by the background S3 upload in executor.
            screenshot_b64, a11y_tree = await asyncio.gather(
                capture_screenshot_b64(page, full_page=False),
                extract_accessibility_tree(page),
            )

        if a11y_tree:
            original_chars = len(a11y_tree)
            a11y_tree = semantic_dom_cull(a11y_tree)
            culled_chars = len(a11y_tree)
            reduction = (original_chars - culled_chars) / original_chars if original_chars > 0 else 0
            logger.info(
                "[%s] Semantic DOM Culling: pruned ARIA tree from %d to %d chars (%.1f%% reduction)",
                run_id,
                original_chars,
                culled_chars,
                reduction * 100,
            )
    except Exception as _snap_err:
        _snap_msg = str(_snap_err).lower()
        if any(kw in _snap_msg for kw in ("target closed", "browser has been closed", "context was destroyed")):
            raise RuntimeError(
                f"[{run_id}] Page closed during screenshot/a11y capture — run was cancelled."
            ) from _snap_err
        raise  # unexpected — propagate normally

    # FEAT-066: Determine if we are recovering from a verifier rejection
    # (The verifier node sets _verifier_verdict="not_yet" on rejection)
    _verifier_verdict = state.get("_verifier_verdict", "")
    is_verifier_rejected = _verifier_verdict == "not_yet"

    # ── Vision-mode coordinate branch ───────────────────────────────────
    # When vision_mode == "som_coordinates", the planner uses an annotated
    # JPEG screenshot with numbered bounding boxes instead of the DOM/a11y tree.
    # The LLM picks a mark_id and the executor clicks at those coordinates.
    #
    # This branch replaces:
    #   - DOM culling (irrelevant — we don’t send DOM text)
    #   - Interactive element summary (the screenshot IS the element list)
    #   - Legacy SoM escalation (vision SoM is always active in this mode)
    _vision_mode = state.get("vision_mode", "dom")
    if _vision_mode == "som_coordinates" and _VISION_AVAILABLE:
        try:
            logger.info("[%s] Vision mode active — drawing marks and capturing annotated screenshot", run_id)
            _vision_screenshot, _vision_mark_map = await _draw_marks_and_snapshot(page)

            if _vision_mark_map:
                screenshot_b64 = _vision_screenshot
                _vision_summary = _format_vision_mark_summary(_vision_mark_map)

                # Build system prompt (same function, but we’ll prepend the vision block)
                system_prompt = _dispatch_build_system_prompt(state)
                # Append SoM map AFTER the system prompt (recency zone)
                # so the LLM reads element IDs last, right before generating output.
                system_prompt = system_prompt + "\n" + _vision_summary

                # Build user_content with annotated JPEG only — no DOM text
                import base64 as _base64

                _vision_bytes = _base64.b64decode(_vision_screenshot)

                stability_note = ""
                if stability_obs.get("spinner_cleared"):
                    stability_note += (
                        "\n⚠ NOTE: A loading spinner was present and has just cleared. "
                        "The page shown below is fresh — act on it directly.\n"
                    )
                if stability_obs.get("modal_detected"):
                    stability_note += (
                        "\n⚠ NOTE: A modal dialog or overlay is currently visible. "
                        "You must interact WITH the modal — elements behind it are blocked.\n"
                    )

                user_content = [
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": _vision_bytes},
                        },
                    },
                    {
                        "text": (
                            "The screenshot above shows the current page with numbered red boxes "
                            "on interactive elements. Each box has a mark_id number.\n\n"
                            'To click an element, use: {"action": "coordinate_action", "mark_id": N}\n'
                            'To fill an input, use: {"action": "coordinate_action", "mark_id": N, '
                            '"text_to_fill": "your text"}\n'
                            'For PrimeNG dropdowns, use: {"action": "primeng_dropdown", '
                            '"trigger_mark_id": N, "target_text": "option text", '
                            '"portal_class": ".class"}\n\n'
                            f"{stability_note}"
                            "Call the plan_action tool with the SINGLE NEXT action to take."
                        ),
                    },
                ]

                # Apply prompt budget guard — VISION MODE uses a higher budget
                # because Claude 3.5 Sonnet handles 200k tokens (~800k chars).
                # The SoM element map, coordinate data, and Jira context are ALL
                # essential for intelligent action selection. The old 50k cap was
                # deleting <som_element_map> via Hard Splice, causing the agent to
                # click random elements. 300k is a safety ceiling, not an expected target.
                import re as _re_budget

                _VISION_PROMPT_BUDGET = 300_000
                if len(system_prompt) > _VISION_PROMPT_BUDGET:
                    logger.warning(
                        "[%s] Vision prompt exceeds %dk safety ceiling (%d chars) — cascading trim",
                        run_id,
                        _VISION_PROMPT_BUDGET // 1000,
                        len(system_prompt),
                    )
                    system_prompt = _re_budget.sub(
                        r"<UI_RULES>.*?</UI_RULES>",
                        "<UI_RULES>RAG dropped to save tokens.</UI_RULES>",
                        system_prompt,
                        flags=_re_budget.DOTALL,
                    )
                    if len(system_prompt) > _VISION_PROMPT_BUDGET:
                        system_prompt = _re_budget.sub(
                            r"<execution_history>.*?</execution_history>",
                            "<execution_history>History truncated.</execution_history>",
                            system_prompt,
                            flags=_re_budget.DOTALL,
                        )

                logger.info(
                    "[%s] Vision mode: %d marks, %d-char system prompt, JPEG screenshot",
                    run_id,
                    len(_vision_mark_map),
                    len(system_prompt),
                )

                # ── Prompt logging to disk for research ──────────────────────
                try:
                    import pathlib as _pl

                    _prompt_dir = _pl.Path(__file__).resolve().parent.parent.parent / ".logs" / "prompts"
                    _prompt_dir.mkdir(parents=True, exist_ok=True)
                    _iter = state.get("planner_iteration", 0)
                    _ac = state.get("ac_step_index", 0) + 1
                    _fname = f"{run_id}_iter{_iter}_ac{_ac}_vision.txt"
                    _prompt_path = _prompt_dir / _fname
                    with open(_prompt_path, "w", encoding="utf-8", errors="replace") as _f:
                        _f.write(system_prompt)
                        _f.flush()
                    logger.info(
                        "[%s] Prompt logged to .logs/prompts/%s (%d bytes)",
                        run_id,
                        _fname,
                        len(system_prompt),
                    )
                except Exception as _pe:
                    logger.warning("[%s] Prompt log failed: %s", run_id, _pe)

                # Call Claude
                retry_count = state.get("retry_count", 0)
                is_retry = retry_count >= 2
                planned_action = {}
                llm_obs = ""
                llm_thought = ""

                try:
                    planned_action = await _invoke_planner_with_tools(
                        system_prompt=system_prompt,
                        user_content=user_content,
                        is_retry=is_retry,
                        retry_count=retry_count,
                        is_verifier_rejected=is_verifier_rejected,
                        run_metrics=_get_metrics_for_run(run_id),
                    )
                    llm_obs = planned_action.pop("observation", "") or ""
                    llm_thought = planned_action.pop("thought", "") or ""
                except Exception as e:
                    logger.error(
                        "[%s] Vision mode tool calling failed: %s — falling back to legacy",
                        run_id,
                        str(e)[:200],
                    )
                    planned_action = {
                        "action": "wait",
                        "value": "1000",
                        "reasoning": f"Vision LLM unavailable: {str(e)[:80]}",
                    }

                if planned_action is None:
                    planned_action = {
                        "action": "wait",
                        "value": "2000",
                        "reasoning": "planned_action was None after vision LLM call.",
                    }

                logger.info(
                    "[%s] Vision planned action: %s → mark_id=%s",
                    run_id,
                    planned_action.get("action", "?"),
                    planned_action.get("mark_id", "n/a"),
                )

                # Track actor if present
                run_memory_update = {}
                track_actor = planned_action.pop("track_actor", None)
                if track_actor and isinstance(track_actor, dict):
                    actor_role = track_actor.get("role", "")
                    actor_name = track_actor.get("name", "")
                    if actor_role and actor_name:
                        run_memory_update = {"dynamic_actors": {actor_role: actor_name}}

                return {
                    "planned_action": planned_action,
                    "current_screenshot_b64": screenshot_b64,
                    "current_accessibility_tree": a11y_tree,
                    "planner_iteration": iteration,
                    "run_memory": run_memory_update,
                    "som_element_map": {},
                    "mark_coordinate_map": _vision_mark_map,
                    "hitl_override": None,  # Clear after use
                }
            else:
                logger.warning(
                    "[%s] Vision mode: no interactive elements found — falling back to DOM mode",
                    run_id,
                )
        except Exception as _vision_err:
            logger.warning(
                "[%s] Vision mode failed (non-fatal): %s — falling back to DOM mode",
                run_id,
                str(_vision_err)[:200],
            )

    # ── Step 3b: Set-of-Marks escalation (healing tier 3 / loop detected) ──
    # When the agent is stuck (retry >= 3 or ac_step_action_fail >= 3),
    # annotate the page with numbered boxes so the LLM picks elements
    # by box number instead of hallucinating CSS selectors.
    # SoM is ~200ms overhead — only activate when normal strategies fail.
    _som_map: dict = {}
    _som_block: str = ""
    if _SOM_AVAILABLE and _should_activate_som(state):
        try:
            logger.info(
                "[%s] Activating Set-of-Marks (retry=%d, fail_count=%d)",
                run_id,
                state.get("retry_count", 0),
                state.get("ac_step_action_fail_count", 0),
            )
            _som_screenshot, _som_map = await _capture_som(page)
            # Only replace the screenshot if we got actual element data
            if _som_map:
                screenshot_b64 = _som_screenshot
                _som_block = _format_som_block(_som_map)
                logger.info("[%s] SoM: %d elements annotated", run_id, len(_som_map))
        except Exception as _som_err:
            logger.warning("[%s] SoM capture failed (non-fatal): %s", run_id, _som_err)

    # ── Step 4: THINK — build the multimodal prompt ───────────────────
    system_prompt: str = _dispatch_build_system_prompt(state)

    # ── T3-b: Registry-First Gate prompt-time injection (CQ-B1 hybrid) ──
    # Inject a <registry_hits> block when a registry entry exists for the
    # current AC step. This steers the LLM to use the correct strategy on
    # the first pass, reducing wasted Bedrock invocations.
    _rfg_product = state.get("active_product") or state.get("product_slug") or state.get("product") or ""
    _rfg_step_text = ""
    try:
        _rfg_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
        _rfg_idx = state.get("ac_step_index", -1)
        if _rfg_idx >= 0 and _rfg_idx < len(_rfg_steps):
            _rfg_step_text = _rfg_steps[_rfg_idx].get("step", "")
    except Exception:
        pass
    if _rfg_product and _rfg_step_text:
        _rfg_block = RegistryFirstGate.build_prompt_block(_rfg_step_text, _rfg_product)
        if _rfg_block:
            system_prompt = _rfg_block + "\n" + system_prompt
            logger.debug("[%s] RegistryFirstGate: <registry_hits> block injected", run_id)

    # Prepend HITL override block if present — highest priority context
    hitl_override_block = _build_hitl_override_block(state)
    if hitl_override_block:
        system_prompt = hitl_override_block + system_prompt
        logger.info("[%s] HITL override block injected into prompt", run_id)

    # Prepend SoM block at the TOP of the prompt — highest priority context.
    if _som_block:
        system_prompt = _som_block + "\n" + system_prompt

    # ── T2-c: Inject CV vision diagnostic fragment when mark_id=None on prior turn ──
    # When the executor stored cv_vision_diagnostic in state (vision saw N marks but
    # none matched the target), prepend the recovery fragment so the planner does not
    # blindly retry the same failed strategy.  Priority: after SoM, before main body.
    _cv_diag_fragment = _build_cv_diagnostic_fragment(state)
    if _cv_diag_fragment:
        system_prompt = _cv_diag_fragment + system_prompt
        logger.info("[%s] CV vision diagnostic fragment injected into prompt", run_id)

    # ── DOM Culling: multi-pass aggressive pruning BEFORE the a11y snapshot ─────
    # Pass 1 — suppress excess tbody rows (PrimeNG List View tables with 90+ rows
    #           explode the a11y tree past the 50k-char prompt budget).
    # Pass 2 — hide all SVG/path/img elements (LLMs don't need vector coords).
    # Pass 3 — hide PrimeNG off-screen portals and elements already display:none.
    # Pass 4 — hide excess Compact View spot cards beyond the first 4.
    # Pass 5 — orphaned PrimeNG portal purge: when a dropdown fails, PrimeNG
    #           leaves stale overlay portals in the DOM; keep only the last one.
    # Pass 6 — Angular/PrimeNG attribute scrub: strip ng-reflect-*, data-pc-*,
    #           and inline style attributes from VISIBLE elements. Also truncate
    #           leaf-node innerText > 300 chars. These attributes add thousands
    #           of chars to the a11y snapshot without helping the LLM locate.
    #   • <thead> is NEVER touched — column headers remain clickable for sorting.
    #   • Suppression is visual-layer-only; Playwright can still target hidden
    #     rows/cards/portals when explicitly addressed.
    #   • We record total culled elements for the debug log.
    #   • Wrapped in try/except — a JS error must never crash the planner turn.
    _DOM_CULL_ROWS_KEPT = 5  # Keep first N rows per tbody visible to the a11y tree
    _DOM_CULL_CARDS_KEPT = 4  # Keep first N Compact View cards
    try:
        _culled_count: int = await page.evaluate(f"""() => {{
            let culled = 0;

            // ── Pass 1: Suppress excess tbody rows ───────────────────────────
            document.querySelectorAll('tbody').forEach(tbody => {{
                const rows = tbody.querySelectorAll('tr');
                rows.forEach((row, index) => {{
                    if (index >= {_DOM_CULL_ROWS_KEPT}) {{
                        row.style.display = 'none';
                        culled++;
                    }}
                }});
            }});

            // ── Pass 2: Hide SVGs, paths, and images ─────────────────────────
            // LLMs don't need vector coordinates to click buttons. Stripping
            // PrimeNG icon SVGs drastically reduces a11y snapshot noise.
            document.querySelectorAll('svg, path, img').forEach(el => {{
                el.style.display = 'none';
                culled++;
            }});

            // ── Pass 3: Hide PrimeNG off-screen portals & hidden overlays ───
            // p-connected-overlay-hidden: closed portal panels still in DOM.
            // .p-hidden: PrimeNG utility class for visually-hidden elements.
            // Guard: never touch <body> or <html> — just portal/overlay nodes.
            // ⚠ SAFETY: NEVER hide an element that has .p-connected-overlay-visible.
            document.querySelectorAll(
                '.p-connected-overlay-hidden, .p-hidden'
            ).forEach(el => {{
                if (el.tagName !== 'BODY' && el.tagName !== 'HTML' && !el.classList.contains('p-connected-overlay-visible')) {{
                    el.style.display = 'none';
                    culled++;
                }}
            }});

            // ── Pass 4: Suppress excess Compact View spot cards ──────────────
            // #compact-card-list renders 90+ heavy cards that have no <tbody>
            // and therefore bypass Pass 1 entirely. Hide direct children (spot
            // cards) beyond the first {_DOM_CULL_CARDS_KEPT} to keep the a11y
            // tree lean. .compact-view-wrapper is the fallback selector.
            const compactList = document.querySelector('#compact-card-list, .compact-view-wrapper');
            if (compactList) {{
                Array.from(compactList.children).forEach((card, index) => {{
                    if (index >= {_DOM_CULL_CARDS_KEPT}) {{
                        card.style.display = 'none';
                        culled++;
                    }}
                }});
            }}

            // ── Pass 5: Orphaned PrimeNG portal purge ─────────────────────
            // When a dropdown interaction fails, PrimeNG leaves stale overlay
            // portals in the DOM. Only the LAST portal is likely to be the
            // currently open one; hide all earlier ones to eliminate bloat.
            // Guard: only runs when more than 1 portal is found (no-op otherwise).
            const portals = document.querySelectorAll(
                '.p-select-overlay, .po-sorting-dropdown-panel, .p-popover, .p-connected-overlay-visible, .p-datepicker-panel'
            );
            if (portals.length > 1) {{
                for (let i = 0; i < portals.length - 1; i++) {{
                    portals[i].style.display = 'none';
                    culled++;
                }}
            }}

            // ── Pass 6: Angular/PrimeNG attribute scrub ──────────────────────
            // Angular debug attributes (ng-reflect-*) and PrimeNG component
            // metadata attributes (data-pc-*) add thousands of chars to the
            // a11y snapshot without providing any locator value to the LLM.
            //
            // ⚠ SAFETY RULES — do NOT remove:
            //   • style=""  — PrimeNG uses inline style to control visibility,
            //     positioning, and display of overlays, portals, and buttons.
            //     Removing style causes UI elements to disappear from the page.
            //   • innerText — Angular components re-render when innerText is
            //     mutated via JS, destroying button labels and component state.
            //
            // Only ng-reflect-* and data-pc-* are safe to strip; they are
            // Angular change-detection debug data and PrimeNG component
            // metadata — purely informational, no visual side-effects.
            let attrsCulled = 0;
            document.querySelectorAll('*').forEach(el => {{
                if (el.style.display === 'none') return;  // skip already-hidden
                const toRemove = [];
                for (const attr of el.attributes) {{
                    if (
                        attr.name.startsWith('ng-reflect-') ||
                        attr.name.startsWith('data-pc-')
                    ) {{
                        toRemove.push(attr.name);
                    }}
                }}
                for (const name of toRemove) {{
                    el.removeAttribute(name);
                    attrsCulled++;
                }}
            }});
            culled += attrsCulled;

            return culled;
        }}""")
        if _culled_count > 0:
            logger.info(
                "[%s] DOM Culling (6-pass): suppressed %d elements/attributes total "
                "(tbody rows + SVGs + hidden portals + compact cards + orphaned portals + Angular attrs) "
                "to prevent a11y tree explosion.",
                run_id,
                _culled_count,
            )
        else:
            logger.debug(
                "[%s] DOM Culling: no elements culled (table has <= %d rows, "
                "<= %d compact cards, no SVGs/portals/Angular-attrs).",
                run_id,
                _DOM_CULL_ROWS_KEPT,
                _DOM_CULL_CARDS_KEPT,
            )
    except Exception as _cull_err:
        logger.warning("[%s] DOM Culling script failed (non-fatal): %s", run_id, _cull_err)

    # ── Step 3: Build compact interactive-element summary for the LLM ──
    # extract_interactive_summary() returns only the interactive elements
    # (buttons, links, inputs, etc.) in a compact, LLM-readable format.
    # This replaces the old MAX_A11Y_CHARS=3000 hard chop on the full tree
    # which silently cut off table rows on complex pages like Production Orders.
    #
    # The full a11y tree is still captured (in extract_accessibility_tree above)
    # for audit purposes but is NOT sent to the LLM.
    # NOTE: DOM Culling above runs first — the snapshot reflects the pruned DOM.
    target_roles = state.get("target_element_types", [])
    interactive_summary = await extract_interactive_summary(
        page,
        target_element_types=target_roles,
    )

    # ── Step 3b: Extract visible page text for context ────────────────
    # The interactive summary only lists buttons/links/inputs. To help the
    # planner understand table content (status values, column text, pagination),
    # we also extract a compact snapshot of visible text on the page.
    page_text_snapshot = ""
    try:
        page_text_snapshot = await page.evaluate("""() => {
            const results = [];

            // 1. Table headers (PrimeNG p-table or standard <th>)
            const headers = document.querySelectorAll(
                'th, .p-datatable-thead th, .mat-header-cell'
            );
            const headerTexts = [];
            for (const h of headers) {
                const t = (h.innerText || '').trim();
                if (t && t.length < 40) headerTexts.push(t);
            }
            if (headerTexts.length > 0) {
                results.push('TABLE COLUMNS: ' + headerTexts.join(' | '));
            }

            // 2. Table rows — show compact cell text for each visible row
            const rows = document.querySelectorAll(
                '.p-datatable-tbody tr, tbody tr'
            );
            let rowCount = 0;
            const statusCounts = {};
            for (const row of rows) {
                if (rowCount >= 15) break;
                const cells = row.querySelectorAll('td');
                const cellTexts = [];
                for (const cell of cells) {
                    const text = (cell.innerText || '').trim().substring(0, 50);
                    if (text) cellTexts.push(text);
                }
                if (cellTexts.length > 0) {
                    results.push('  ROW: ' + cellTexts.join(' | '));
                    rowCount++;
                    // Track status values for summary
                    const rowText = cellTexts.join(' ');
                    const statuses = ['Needs Producing', 'Needs Scheduling', 'Needs Dubbing',
                                      'Needs Mixing', 'Needs Writing', 'Complete', 'Cancelled',
                                      'Needs Approval', 'Ready to Air', 'In Progress'];
                    for (const s of statuses) {
                        if (rowText.includes(s)) {
                            statusCounts[s] = (statusCounts[s] || 0) + 1;
                        }
                    }
                }
            }

            // 3. Summary line — helps the LLM reason about what's on this page
            if (rowCount > 0) {
                const statusParts = Object.entries(statusCounts)
                    .map(([k, v]) => k + ' (' + v + ')')
                    .join(', ');
                const summary = 'TABLE SUMMARY: ' + rowCount + ' rows visible on this page. '
                    + (statusParts ? 'Statuses found: ' + statusParts + '.' : 'No known statuses detected.');
                results.push(summary);
            }

            // 4. Pagination state — which buttons are available
            const nextBtn = document.querySelector('.p-paginator-next, button[aria-label="Next Page"]');
            const prevBtn = document.querySelector('.p-paginator-prev, button[aria-label="Previous Page"]');
            const pageButtons = document.querySelectorAll('.p-paginator-page');
            const activePageBtn = document.querySelector('.p-paginator-page.p-highlight, .p-paginator-page[aria-current="page"]');

            if (nextBtn || prevBtn || pageButtons.length > 0) {
                const nextEnabled = nextBtn && !nextBtn.disabled;
                const prevEnabled = prevBtn && !prevBtn.disabled;
                const currentPage = activePageBtn ? activePageBtn.innerText.trim() : '?';
                const totalPages = pageButtons.length || '?';
                results.push(
                    'PAGINATION: Page ' + currentPage + ' of ' + totalPages
                    + ' | Next: ' + (nextEnabled ? 'ENABLED' : 'disabled')
                    + ' | Prev: ' + (prevEnabled ? 'ENABLED' : 'disabled')
                );
            }

            // Fallback: Angular Material paginator
            const matPaginator = document.querySelector(
                '.mat-paginator-range-label, .mat-mdc-paginator-range-label'
            );
            if (matPaginator) {
                results.push('PAGINATION: ' + matPaginator.innerText.trim());
            }

            return results.join('\\n');
        }""")
    except Exception as e:
        logger.debug("Page text snapshot extraction failed: %s", str(e))

    if page_text_snapshot:
        logger.info("[%s] Page text snapshot (%d chars): %s", run_id, len(page_text_snapshot), page_text_snapshot[:200])
    else:
        logger.info("[%s] Page text snapshot: (empty — no table content detected)", run_id)

    # Build context text
    context_parts = [interactive_summary]
    if page_text_snapshot:
        context_parts.append(f"\nVISIBLE PAGE TEXT (status badges, table content, pagination):\n{page_text_snapshot}")

    # ── Bedrock converse API content format (raw boto3 converse) ───────────
    # CRITICAL: _invoke_planner_with_tools() passes user_content directly to
    # the Bedrock converse API via boto3 (NOT through LangChain). The raw
    # Bedrock converse API uses a different content block format from LangChain:
    #
    #   ❌ WRONG (LangChain format):  {"type": "image", "source": {...}}
    #   ✔ CORRECT (Bedrock format):  {"image": {"format": "png", "source": {...}}}
    #
    # Using the LangChain format caused a tagged-union validation error on every
    # tool call, silently falling back to the legacy LLM path, leaving the
    # Pydantic schema completely unenforced. Bug Fix #1.
    import base64 as _base64  # noqa: PLC0415

    screenshot_bytes = _base64.b64decode(screenshot_b64)

    # Inject stability gate observations so the LLM is aware of page state
    stability_note = ""
    if stability_obs.get("spinner_cleared"):
        stability_note += (
            "\n⚠ NOTE: A loading spinner was present and has just cleared. "
            "The page shown below is fresh — act on it directly.\n"
        )
    if stability_obs.get("modal_detected"):
        stability_note += (
            "\n⚠ NOTE: A modal dialog or overlay is currently visible. "
            "You must interact WITH the modal — elements behind it are blocked.\n"
        )

    user_content: list[dict] = [
        {
            "image": {
                "format": "png",
                "source": {"bytes": screenshot_bytes},
            },
        },
        {
            "text": (
                f"{chr(10).join(context_parts)}\n\n"
                f"Note: The list above shows ALL interactive elements on the page. "
                f"Elements visible in the list but not in the screenshot may be below the fold — they are still valid targets.\n"
                f"{stability_note}\n"
                f"Call the plan_action tool with the SINGLE NEXT action to take."
            ),
        },
    ]

    # ── Step 5+6: THINK — call Claude via Bedrock tool calling ────────
    # _invoke_planner_with_tools() uses the Bedrock converse API with
    # toolConfig to force Claude to return a valid PlannerAction — no
    # free-form JSON, no missing required fields.
    retry_count: int = state.get("retry_count", 0)
    is_retry = retry_count >= 2

    # ── Global prompt budget guard (cascading regex strategy) ────────────────
    # Safety ceiling for tool-call (DOM) mode.  Claude 3.5 Sonnet handles
    # 200k tokens (~800k chars).  The DOM path includes the full interactive
    # elements tree as TEXT in user_content, which can reach 80-90k chars.
    # Old 50k cap was triggering Hard Splice that deleted the element tree
    # and Jira context, making the agent click random elements.
    #
    # 150k gives headroom for: ~18k template + ~10k KB/RAG + ~5k human guidance
    # + ~5k action history + ~60k interactive elements + ~40k selector/playwright
    # = ~138k typical worst case.  Cascading trim only fires as a safety net.
    #
    # Cascade order (drop first → drop last):
    #   Stage 0 — <available_options> in <page_state> (overlay item lists)
    #   Stage 1 — <execution_history> (transient per-iteration action log)
    #   Stage 2 — <UI_RULES>   (RAG KB context — preserved over history)
    #   Stage 3 — DOM truncation / hard splice (never crash)
    import re as _re_budget  # noqa: PLC0415

    _PROMPT_BUDGET = 150_000
    if len(system_prompt) > _PROMPT_BUDGET:
        overage = len(system_prompt) - _PROMPT_BUDGET

        # ── Stage 0: Trim overlay option lists from <page_state> ──────────
        # The <available_options> lists inside <page_state> can add 500-2000
        # chars per overlay but are lowest priority — the overlay type and
        # selector are sufficient for the planner to scope its actions.
        system_prompt = _re_budget.sub(
            r"<available_options>.*?</available_options>",
            "<available_options>Options trimmed for budget.</available_options>",
            system_prompt,
            flags=_re_budget.DOTALL,
        )
        if len(system_prompt) <= _PROMPT_BUDGET:
            logger.info(
                "[%s] Stage 0 trim resolved budget — trimmed overlay options (%d chars now)",
                run_id,
                len(system_prompt),
            )

    if len(system_prompt) > _PROMPT_BUDGET:
        overage = len(system_prompt) - _PROMPT_BUDGET
        logger.warning(
            "[%s] ⚠ PROMPT BUDGET EXCEEDED: %d chars (limit %d, overage %d). "
            "Starting cascading trim — Stage 1: dropping <execution_history> first.",
            run_id,
            len(system_prompt),
            _PROMPT_BUDGET,
            overage,
        )

        # ── Stage 1: Trim <execution_history> block (action log) ─────────────
        # TASK-015 Bug 5 fix: Drop history BEFORE domain context (<UI_RULES>).
        # The planner needs domain knowledge (KB, selectors, RAG) more than
        # transient action history — dropping history first preserves the
        # context needed to avoid repeating mistakes.
        system_prompt = _re_budget.sub(
            r"<execution_history>.*?</execution_history>",
            "<execution_history>History truncated to preserve domain context.</execution_history>",
            system_prompt,
            flags=_re_budget.DOTALL,
        )
        logger.warning(
            "[%s] Stage 1 trim complete (execution_history) — new prompt size: %d chars",
            run_id,
            len(system_prompt),
        )

        # ── Stage 2: Trim <UI_RULES> block (RAG KB context) ─────────────────
        # Only reached if history trimming wasn't enough.  Domain context is
        # higher value than history but lower than AC step and human guidance.
        if len(system_prompt) > _PROMPT_BUDGET:
            overage2 = len(system_prompt) - _PROMPT_BUDGET
            logger.warning(
                "[%s] ⚠ STILL over budget after Stage 1 (%d chars, overage %d). "
                "Stage 2: dropping <UI_RULES> RAG context.",
                run_id,
                len(system_prompt),
                overage2,
            )
            system_prompt = _re_budget.sub(
                r"<UI_RULES>.*?</UI_RULES>",
                "<UI_RULES>RAG dropped to save tokens.</UI_RULES>",
                system_prompt,
                flags=_re_budget.DOTALL,
            )
            logger.warning(
                "[%s] Stage 2 trim complete (UI_RULES) — new prompt size: %d chars",
                run_id,
                len(system_prompt),
            )

        # ── Stage 3: Graceful DOM truncation — NEVER raise, NEVER crash ─────
        # The INTERACTIVE ELEMENTS block lives in user_content (the text block
        # sent alongside the screenshot), not in system_prompt.  Before we
        # resort to any hard slice of the system prompt, truncate the DOM text
        # from user_content so the AC step and Human Guidance are never lost.
        #
        # Tier A — surgically truncate the INTERACTIVE ELEMENTS block in
        #           context_parts so it fits within budget.
        # Tier B — last-resort hard splice: keep the first 25k (instructions +
        #           identity + rules) and the last 24k (AC step + guidance tail).
        #           This is ugly but it never raises — the run always continues.
        if len(system_prompt) > _PROMPT_BUDGET:
            overage3 = len(system_prompt) - _PROMPT_BUDGET
            logger.warning(
                "[%s] ⚠ STILL over budget after Stage 1+2 (%d chars, overage %d). "
                "Stage 3: surgically truncating INTERACTIVE ELEMENTS block in user_content.",
                run_id,
                len(system_prompt),
                overage3,
            )

            # Tier A: truncate the interactive_summary segment inside context_parts.
            # interactive_summary is always the first element of context_parts.
            _elem_block: str = context_parts[0] if context_parts else ""
            if len(_elem_block) > overage3 + 500:
                _keep = max(500, len(_elem_block) - overage3 - 1000)
                context_parts[0] = _elem_block[:_keep] + "\n...[INTERACTIVE ELEMENTS TRUNCATED TO FIT BUDGET]\n"
                # Rebuild user_content text with the truncated summary
                _new_context_text = (
                    f"{chr(10).join(context_parts)}\n\n"
                    f"Note: The list above shows ALL interactive elements on the page. "
                    f"Elements visible in the list but not in the screenshot may be below the fold — they are still valid targets.\n"
                    f"{stability_note}\n"
                    f"Call the plan_action tool with the SINGLE NEXT action to take."
                )
                # Patch the text block in user_content in-place (index 1 = text block)
                if len(user_content) > 1 and "text" in user_content[1]:
                    user_content[1]["text"] = _new_context_text
                logger.warning(
                    "[%s] Stage 3 Tier A: truncated INTERACTIVE ELEMENTS block from %d → %d chars. "
                    "New system_prompt size: %d chars.",
                    run_id,
                    len(_elem_block),
                    len(context_parts[0]),
                    len(system_prompt),
                )
            else:
                # Tier B: nothing big enough to trim in user_content — hard-splice
                # system_prompt itself, preserving head (identity/rules) + tail (AC step).
                _head = system_prompt[:25000]
                _tail = system_prompt[-24000:]
                system_prompt = _head + "\n\n...[MIDDLE TRUNCATED TO FIT BUDGET]...\n\n" + _tail
                logger.warning(
                    "[%s] Stage 3 Tier B (hard splice): system_prompt trimmed to %d chars. "
                    "Head=25k, Tail=24k preserved. Run continues.",
                    run_id,
                    len(system_prompt),
                )

    logger.info("[%s] Calling Claude (tool calling) with %d-char system prompt", run_id, len(system_prompt))

    # ── Prompt logging to disk for research ──────────────────────────────
    try:
        import pathlib as _pl

        _prompt_dir = _pl.Path(__file__).resolve().parent.parent.parent / ".logs" / "prompts"
        _prompt_dir.mkdir(parents=True, exist_ok=True)
        _iter = state.get("planner_iteration", 0)
        _ac = state.get("ac_step_index", 0) + 1
        _fname = f"{run_id}_iter{_iter}_ac{_ac}_dom.txt"
        _prompt_path = _prompt_dir / _fname
        with open(_prompt_path, "w", encoding="utf-8", errors="replace") as _f:
            _f.write(system_prompt)
            _f.flush()
        logger.info(
            "[%s] Prompt logged to .logs/prompts/%s (%d bytes)",
            run_id,
            _fname,
            len(system_prompt),
        )
    except Exception as _pe:
        logger.warning("[%s] Prompt log failed: %s", run_id, _pe)

    llm_obs = ""
    llm_thought = ""
    planned_action: dict = {}

    try:
        planned_action = await _invoke_planner_with_tools(
            system_prompt=system_prompt,
            user_content=user_content,
            is_retry=is_retry,
            retry_count=retry_count,
            is_verifier_rejected=is_verifier_rejected,
            run_metrics=_get_metrics_for_run(run_id),
        )
        llm_obs = planned_action.pop("observation", "") or ""
        llm_thought = planned_action.pop("thought", "") or ""
        logger.debug("[%s] Tool call result: %s", run_id, str(planned_action)[:200])
    except Exception as e:
        # Tool calling failed (Bedrock error, Pydantic error after retries, etc.)
        # Fall back to legacy ChatBedrockConverse path so the run doesn't crash.
        logger.error(
            "[%s] Tool calling failed after retries: %s — falling back to legacy LLM path",
            run_id,
            str(e)[:200],
        )
        try:
            llm = _get_llm(is_retry=is_retry, retry_count=retry_count, is_verifier_rejected=is_verifier_rejected)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
            response = await llm.ainvoke(messages)
            planned_action, llm_obs, llm_thought = _parse_llm_response(response.content)
        except Exception as fallback_err:
            logger.error("[%s] Fallback LLM path also failed: %s", run_id, str(fallback_err)[:200])
            planned_action = {
                "action": "wait",
                "value": "1000",
                "reasoning": f"LLM unavailable — both tool calling and fallback failed: {str(e)[:80]}",
            }

    # Validate the planned action (applies to both tool calling and fallback paths)
    validation_errors = validate_planned_action(planned_action, state)
    if validation_errors:
        logger.warning(
            "[%s] Post-tool-call validation errors (non-fatal): %s",
            run_id,
            "; ".join(validation_errors),
        )
        # Don't override - the Pydantic schema already validated the core fields.
        # validate_planned_action may enforce additional vQA-specific business rules.

    # ── FIX 4: Force set_input_files for upload/attach AC steps ────────
    # If the AC step requires a file upload but the LLM returned a click
    # action (likely trying to click Browse/Upload), override the action
    # to set_input_files.  This is a HARD PYTHON CONSTRAINT on the LLM
    # output — even if the prompt rules fail, this catch-all fires.
    ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
    ac_idx = state.get("ac_step_index", 0)
    current_ac = ac_steps[ac_idx] if ac_idx < len(ac_steps) else ""
    current_ac_lower = current_ac.lower()

    _UPLOAD_STEP_KEYWORDS = [
        "attach",
        "upload",
        "file upload",
        "drag and drop",
        "add file",
        "import file",
        "browse for file",
    ]
    step_is_upload = any(kw in current_ac_lower for kw in _UPLOAD_STEP_KEYWORDS)

    if step_is_upload and planned_action.get("action") == "click":
        target_name = planned_action.get("name", "").lower()
        # Only intercept clicks that are clearly targeting file UI elements
        _FILE_UI_KEYWORDS = [
            "browse",
            "upload",
            "choose",
            "attach",
            "file",
            "select file",
            "add file",
            "import",
        ]
        if any(kw in target_name for kw in _FILE_UI_KEYWORDS):
            asset_filenames = _get_asset_filenames()
            logger.warning(
                "[%s] FIX 4: AC step requires upload but LLM planned click('%s') — forcing set_input_files override",
                run_id,
                planned_action.get("name", ""),
            )
            planned_action = {
                "action": "set_input_files",
                "selector": "p-fileupload input[type='file']",
                "value": asset_filenames[0] if asset_filenames else "",
                "reasoning": (
                    f"FORCED_OVERRIDE: AC step requires file upload. "
                    f"LLM tried to click '{planned_action.get('name', '')}' which would "
                    f"trigger native OS file dialog. Overridden to set_input_files. "
                    f"Available files: {asset_filenames[:5]}"
                ),
            }

    # ── FIX 5: Column-header click loop breaker (QA-321 fix) ───────────
    # The LLM fell into a 30+ step loop clicking 'Due / Days' repeatedly
    # because it could not mathematically verify the sort order.
    #
    # This blocker counts consecutive clicks on ANY columnheader in the
    # recent action history.  If the same column is clicked 3+ times with
    # NO verify_table_sort in between, the NEXT click on that header is
    # hard-blocked and replaced with a verify_table_sort action.

    # Guard: planned_action can be None in rare edge cases (e.g., Bedrock API
    # returning an empty response after all retries fail).  Crash: line 1951
    # `planned_action.get("role", "").lower()` raises AttributeError when None.
    if planned_action is None:
        logger.error(
            "[%s] FIX 5 GUARD: planned_action is None — skipping loop-breaker, returning wait action to avoid crash.",
            run_id,
        )
        planned_action = {
            "action": "wait",
            "value": "2000",
            "reasoning": "planned_action was None after all LLM retries — waiting to recover.",
        }

    if planned_action.get("action") == "click" and (
        (planned_action.get("role") or "").lower() == "columnheader"
        or planned_action.get("strategy", "") == "get_by_role"
        and planned_action.get("name", "")
        and "sort" in current_ac_lower
    ):
        col_clicked = planned_action.get("name", "").strip()
        action_history_log = state.get("detailed_execution_log", [])

        # Count consecutive clicks on THIS SAME column header (look back up to 10 steps)
        recent_col_clicks = 0
        found_verify = False
        for past_step in reversed(action_history_log[-10:]):
            past_action = past_step.get("action_type", "")
            past_name = past_step.get("name", "") or past_step.get("value", "")
            if past_action == "verify_table_sort":
                found_verify = True
                break
            if past_action == "click" and col_clicked and col_clicked.lower() in str(past_name).lower():
                recent_col_clicks += 1
            elif past_action == "click":
                break  # Different element clicked — stop counting

        if recent_col_clicks >= 2 and not found_verify:
            logger.warning(
                "[%s] FIX 5: Column-header click LOOP DETECTED — '%s' clicked %d times "
                "with no verify_table_sort. Forcing verify_table_sort to break the loop.",
                run_id,
                col_clicked,
                recent_col_clicks,
            )
            planned_action = {
                "action": "verify_table_sort",
                "column": col_clicked,
                "order": "ascending",
                "reasoning": (
                    f"LOOP_BLOCKED: columnheader '{col_clicked}' clicked {recent_col_clicks}x "
                    f"without verifying. Running programmatic sort check now."
                ),
            }
            (
                f"FIX 5 OVERRIDE: Blocked {recent_col_clicks + 1}th consecutive click on "
                f"'{col_clicked}'. Forced verify_table_sort to break QA-321 infinite loop."
            )

    # ── FIX 6: Settings-button infinite loop breaker ─────────────────────
    # The agent repeatedly clicks `button#settings-btn` (the gear icon that opens
    # a p-menu popup) without ever selecting the 'Compact' menu item from it.
    # This was originally injecting li#compact_listview a which is WRONG because
    # the p-menu removes all li elements from the DOM after it closes.
    # Fix: use get_by_text("Compact") which matches regardless of DOM structure.
    if planned_action.get("action") == "click" and (
        "settings" in (planned_action.get("name") or "").lower()
        or "settings-btn" in (planned_action.get("name") or "").lower()
        or planned_action.get("name") == "Settings"
    ):
        settings_click_count = 0
        action_history_log = state.get("detailed_execution_log", [])
        for past_step in reversed(action_history_log[-15:]):
            past_name = (past_step.get("name") or past_step.get("value") or "").lower()
            if past_step.get("action_type") == "click" and "settings" in past_name:
                settings_click_count += 1
            else:
                break  # Stop as soon as we see a non-Settings click

        if settings_click_count >= 2 and "compact" in current_ac_lower:
            # Determine which view to switch to from the current AC step
            target_view = "Compact"
            if "minimal" in current_ac_lower:
                target_view = "Minimal"
            elif "list" in current_ac_lower and "compact" not in current_ac_lower:
                target_view = "List"
            logger.warning(
                "[%s] FIX 6: Settings-button LOOP DETECTED — clicked %d times without "
                "switching to %s view. Forcing get_by_text click on menu item.",
                run_id,
                settings_click_count,
                target_view,
            )
            planned_action = {
                "action": "click",
                "strategy": "get_by_text",
                "name": target_view,
                "reasoning": (
                    f"FIX6_LOOP_BREAK: Settings clicked {settings_click_count}x without "
                    f"{target_view} being selected. Using get_by_text (li#compact_listview a "
                    f"is WRONG — p-menu removes li elements on close). Clicking menu item text."
                ),
            }
            (
                f"FIX 6 OVERRIDE: Blocked {settings_click_count + 1}th consecutive Settings click. "
                f"Forcing get_by_text('{target_view}') — li#compact_listview a is ephemeral (removed on menu close)."
            )

    # ── Step 6b: Context-aware scroll interceptor ──────────────────────
    # The LLM sometimes plans "scroll" when it can't find an item on screen.
    # But vSuite tables use PrimeNG pagination — scrolling won't reveal more rows.
    #
    # This interceptor is SMART about when to intervene:
    #   - If the agent is looking for a table row (AC step says "find", "status", etc.)
    #     AND there's a table with pagination → replace scroll with Next Page
    #   - If there are 3+ consecutive scrolls → hard block (infinite loop detection)
    #   - Otherwise, allow the scroll (e.g., scrolling within a detail panel)
    if planned_action.get("action") == "scroll":
        has_table = False
        has_paginator = False
        try:
            has_table = await page.evaluate(
                """() => !!document.querySelector('.p-datatable, .p-datatable-tbody, p-table')"""
            )
            has_paginator = await page.evaluate(
                """() => {
                    const next = document.querySelector('.p-paginator-next, button[aria-label="Next Page"]');
                    return !!(next && !next.disabled);
                }"""
            )
        except Exception:
            pass

        # Count consecutive scrolls
        action_history = state.get("detailed_execution_log", [])
        consecutive_scrolls = 0
        for step in reversed(action_history):
            if step.get("action_type") == "scroll":
                consecutive_scrolls += 1
            else:
                break

        # Check if the AC step is about finding/locating something in a table
        ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
        ac_index = state.get("ac_step_index", 0)
        ac_text = ac_steps[ac_index].lower() if ac_index < len(ac_steps) else ""
        is_search_step = any(
            kw in ac_text
            for kw in [
                "find",
                "needs producing",
                "needs scheduling",
                "needs dubbing",
                "needs mixing",
                "needs writing",
                "status",
                "locate",
                "look for",
                "spot with",
                "order with",
            ]
        )

        # Also check the LLM's reasoning for clues it's searching in a table
        reasoning = (planned_action.get("reasoning", "") + " " + planned_action.get("thought", "")).lower()
        is_table_search = any(
            kw in reasoning
            for kw in [
                "table",
                "pagination",
                "more rows",
                "more spots",
                "more jobs",
                "more items",
                "next page",
                "find",
                "status",
                "producing",
            ]
        )

        if has_table and has_paginator and (is_search_step or is_table_search or consecutive_scrolls >= 1):
            logger.warning(
                "[%s] SCROLL → PAGINATE — table + paginator detected, AC step is searching. "
                "Replacing scroll with 'click Next Page' (scrolls: %d)",
                run_id,
                consecutive_scrolls,
            )
            planned_action = {
                "action": "click",
                "strategy": "get_by_role",
                "role": "button",
                "name": "Next Page",
                "reasoning": (
                    "INTERCEPTED: The current page doesn't have the item you're looking for. "
                    "vSuite tables use PrimeNG pagination — scrolling won't show more rows. "
                    "Clicking 'Next Page' to check the next page of results."
                ),
            }
        elif consecutive_scrolls >= 3:
            # Hard cap — never allow 4+ consecutive scrolls regardless of context.
            # Instead of a useless 'wait', surface the table_search tool.
            logger.warning(
                "[%s] SCROLL BLOCKED — %d consecutive scrolls (hard cap). "
                "Directing agent to table_search or pagination.",
                run_id,
                consecutive_scrolls,
            )
            planned_action = {
                "action": "wait",
                "value": "1000",
                "reasoning": (
                    f"SCROLL HARD-BLOCKED: {consecutive_scrolls} consecutive scrolls. "
                    f"Scrolling is NOT finding new content — vSuite tables use "
                    f"PrimeNG pagination. You MUST use table_search to filter "
                    f"the table, or click pagination buttons (Next Page / >) "
                    f"to navigate to more rows. NEVER scroll again."
                ),
            }

    # ── T3-b: Registry-First Gate (FEAT-118 Phase 2) ─────────────────────
    # Intercept the LLM-emitted action BEFORE writing to VQAState.
    # On a registry hit → rewrite strategy/role/name deterministically.
    # On a miss → emit registry_enrichment_needed telemetry (no action change).
    # Single call site: all LLM paths converge here (CQ-B1 design decision).
    _active_product = state.get("active_product") or state.get("product_slug") or state.get("product") or ""
    _ac_step_text = ""
    _ac_step_idx = state.get("ac_step_index", -1)
    try:
        _ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
        if _ac_step_idx >= 0 and _ac_step_idx < len(_ac_steps):
            _ac_step_text = _ac_steps[_ac_step_idx].get("step", "")
    except Exception:
        pass
    if _active_product and _ac_step_text:
        planned_action = RegistryFirstGate.check(
            planned_action=planned_action,
            ac_step_text=_ac_step_text,
            product_slug=_active_product,
            run_id=run_id,
            ac_step_index=_ac_step_idx,
        )

    logger.info(
        "[%s] Planned action: %s → %s (strategy=%s)",
        run_id,
        planned_action.get("action", "?"),
        planned_action.get("name", planned_action.get("value", "?")),
        planned_action.get("strategy", "n/a"),
    )

    # ── Track actor assignments from LLM response ─────────────────────
    run_memory_update = {}
    track_actor = planned_action.pop("track_actor", None)
    if track_actor and isinstance(track_actor, dict):
        actor_role = track_actor.get("role", "")
        actor_name = track_actor.get("name", "")
        if actor_role and actor_name:
            run_memory_update = {"dynamic_actors": {actor_role: actor_name}}
            logger.info(
                "[%s] Tracked dynamic actor: %s → '%s'",
                run_id,
                actor_role,
                actor_name,
            )

    # ── Step 7: Return partial state update ───────────────────────────
    # FEAT-042 Phase 4: snapshot telemetry before returning.
    # _RAG_TELEMETRY is a module-level accumulator cleared at run start (iteration==1).
    # operator.add reducer in VQAState accumulates entries across all planner calls.
    _rag_stats_snapshot = list(_RAG_TELEMETRY)

    return {
        "planned_action": planned_action,
        "current_screenshot_b64": screenshot_b64,
        "current_accessibility_tree": a11y_tree,
        "planner_iteration": iteration,
        "run_memory": run_memory_update,
        # SoM element map — {} if SoM was not activated this iteration.
        # The executor reads this to resolve box_id actions.
        "som_element_map": _som_map,
        # RAG retrieval telemetry (FEAT-042 Phase 4) — accumulated via operator.add
        "rag_selector_stats": _rag_stats_snapshot,
        "hitl_override": None,  # Clear after use
    }
