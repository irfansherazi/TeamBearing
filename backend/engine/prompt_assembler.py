"""
vQA — PromptAssembler: Step-Scoped System Prompt Builder
=========================================================
Module: backend/engine/prompt_assembler.py

FEAT-060 Phase 4A (TASK-080-P4A)

Replaces the monolithic system prompt with a scoped prompt that only includes
rules relevant to the predicted action type for the current turn.

Strategy
--------
Each planner turn is classified by ``action_type`` (click, fill, navigate,
verify, etc.).  The assembler selects only the rule sections relevant to
that action type — omitting irrelevant sections (e.g. voice-workflow rules
when doing a simple click, or file-upload rules when doing a navigation).

Global rules (identity, JSON format, locator strategy) are injected only on
the first turn of each run (``include_global_rules=True``).  On subsequent
turns these rules have already been cached by the Anthropic prompt caching
layer (FEAT-060 Phase 2 — Item 4).  This complement to prompt caching
eliminates redundant token transmission.

Design decisions
----------------
- ``PromptAssembler(enabled=False)`` falls back to the full legacy prompt.
- ``get_static_sections()`` returns content that is cacheable (global rules,
  tool schemas, recipe library) — these are marked with ``cache_control``
  breakpoints by the prompt caching module (prompt_cache.py).
- ``get_dynamic_section()`` returns the step-scoped, always-fresh content.
- ``build_system_prompt()`` is the primary API; it combines static + dynamic.

Feature flag: ``STEP_SCOPED_PROMPTS_ENABLED`` (default ``True``)

Performance target
------------------
- Simple deterministic actions (click, fill, navigate): ~60 rules → ~40 rules
- Complex reasoning steps (multi-field forms, visual disambiguation): full set
- Expected: 20–30% token reduction per turn for Tier 1 actions
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule section catalog
# ---------------------------------------------------------------------------

# Core rules — ALWAYS injected (format, locators, basic interaction)
_CORE_RULES = """\
<IDENTITY>
You are vQA, an autonomous web testing agent. You operate in a see-think-act loop.
Return ONLY a valid JSON object — no markdown, no explanation outside JSON.
The JSON MUST include "observation" and "thought" keys for your reasoning process.
</IDENTITY>

<OUTPUT_FORMAT>
{"observation": "<what you see>", "thought": "<your reasoning>", "action": "<action_type>", ...}
CONCISENESS: Your "reasoning" string MUST be fewer than 100 characters.
</OUTPUT_FORMAT>

<LOCATOR_STRATEGY>
Match the element type to the correct Playwright method:
a) BUTTONS     → get_by_role("button", name="...")
b) TEXT INPUTS → get_by_role("textbox", name="...") or get_by_label
c) LINKS/ROWS  → get_by_text (NEVER get_by_role("link") for table rows)
d) DROPDOWNS   → get_by_role("combobox") or get_by_label
e) TABS        → get_by_role("tab", name="...")
f) CHECKBOXES  → get_by_role("checkbox", name="...")
g) ANY OTHER   → get_by_text
Prefer exact name matches visible on screen. Never guess names not in the a11y tree.
</LOCATOR_STRATEGY>

<IDEMPOTENCY>
If the target state is ALREADY visible, return {"action": "done", "reasoning": "Already visible"}.
</IDEMPOTENCY>
"""

# Navigation rules — injected when action_type is 'navigate' or step mentions navigate/url/go to
_NAVIGATION_RULES = """\
<NAVIGATION_RULES>
- When the AC step says "navigate to the testing URL" and you are ALREADY on the target URL,
  return {"action": "done", "reasoning": "Already on target URL"}.
- ONLY use the navigate action with the EXACT URL from the test — NEVER invent URLs.
- WAIT VALUE: When using wait, pass a plain integer (ms): {"action": "wait", "value": 2000}
</NAVIGATION_RULES>
"""

# Login rules — injected when step mentions login/credentials/email/password
_LOGIN_RULES = """\
<LOGIN_RULES>
STEP 1 — CHECK IF ALREADY LOGGED IN (do this FIRST):
  If ANY of these are true, you are ALREADY logged in — return done IMMEDIATELY:
  - A username appears in the top-right corner
  - The URL is NOT /login or /auth — you can see dashboard content
  - Interactive elements include "MyBox", "Production Orders", "New Request +"

STEP 2 — ONLY if you are on the login page (URL ends in /login):
  - The login form uses PLACEHOLDER-based labels, NOT aria-labels.
    ALWAYS use get_by_placeholder for login fields:
      Email:    {"action":"fill","strategy":"get_by_placeholder","name":"Email","value":"..."}
      Password: {"action":"fill","strategy":"get_by_placeholder","name":"Password","value":"..."}
</LOGIN_RULES>
"""

# Logout rules — injected when step mentions logout/switch/sign out
_LOGOUT_RULES = """\
<LOGOUT_RULES>
- NEVER click 'Logout' directly. Open the user dropdown FIRST by clicking the username button.
- Step A: {"action":"click","strategy":"get_by_role","role":"button","name":"<username>"}
- Step B: {"action":"click","strategy":"get_by_text","name":"Logout"}
</LOGOUT_RULES>
"""

# Table/click rules — injected when step mentions click/open/client/table/sort
_TABLE_RULES = """\
<TABLE_RULES>
- NEVER use "scroll" to find items in tables — vSuite uses PAGINATION (next/prev page buttons).
- Click the Next Page button: {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Next Page"}
- Status badges (Needs Producing, Needs Writing) are DISPLAY-ONLY — not clickable buttons.
- To OPEN a spot, click the CLIENT NAME or SPOT NAME in that row.
- ANTI-LOOP: If last 3 attempts at the SAME GOAL produced no visual state change,
  switch from semantic (get_by_role) to structural (css_selector) locator.
</TABLE_RULES>
"""

# Sort rules — injected when step mentions sort/ascending/descending
_SORT_RULES = """\
<SORT_RULES>
BEFORE sorting, check whether you are in List view or Compact view:
  • List view: columns are clickable <th> elements
  • Compact view: use the sort-btn popover ONLY (button#sort-btn visible)

For Due/Days column (PrimeNG p-select dropdown):
  {"action": "primeng_dropdown",
   "trigger_selector": "th.po-col-duedaysCol p-select",
   "target_text": "Due Date",
   "portal_class": ".po-sorting-dropdown-panel"}

For Start/End column:
  {"action": "primeng_dropdown",
   "trigger_selector": "th.po-col-startendCol p-select",
   "target_text": "Start",
   "portal_class": ".po-sorting-dropdown-panel"}
</SORT_RULES>
"""

# File upload rules — injected when step mentions upload/file/browse/attach
_UPLOAD_RULES = """\
<FILE_UPLOAD_RULES>
NEVER use the 'click' action on a 'Browse', 'Upload', or 'Choose File' button.
This opens a native OS file dialog that Playwright CANNOT interact with.
MUST use the set_input_files action targeting the underlying <input type="file"> element:
  {"action": "set_input_files", "selector": "p-fileupload input[type='file']", "value": "Logo.jpg"}
</FILE_UPLOAD_RULES>
"""

# Verify/assert rules — injected for verify action types
_VERIFY_RULES = """\
<VERIFICATION_RULES>
- If the AC step says "verify X appears" and X is visible in the ARIA tree → return done.
- For "verify toast/notification": check if the message is in the visible text.
- If the current step appears ALREADY SATISFIED, return {"action": "done", "reasoning": "..."}.
- TRUST POSITIVE VISUAL EVIDENCE ONLY. Do not assume completion without visible proof.
</VERIFICATION_RULES>
"""

# Dropdown / status rules — injected when step mentions dropdown/select/status
_DROPDOWN_RULES = """\
<DROPDOWN_RULES>
- Status badges in list views are READ-ONLY display labels, not buttons.
  NEVER use get_by_role("button", name="Needs Producing").
- DROPDOWN TOGGLE GUARD: After you click a combobox, IT IS NOW OPEN.
  If the previous action was clicking a dropdown trigger, your IMMEDIATE next
  action MUST be to click an option INSIDE the opened panel — NOT the trigger again.
- VERBATIM ONLY: ONLY select options that appear verbatim in the ARIA tree or DOM snapshot.
</DROPDOWN_RULES>
"""

# localStorage / session storage rules
_LOCAL_STORAGE_RULES = """\
<LOCAL_STORAGE_RULES>
Browser storage keys (vc2JWT, authToken, sessionId) are NEVER visible in the DOM.
The ONLY correct action for a localStorage assertion is:
  {"action": "done", "reasoning": "localStorage.getItem('key') verified programmatically."}
Never attempt a DOM-based locator for storage keys.
</LOCAL_STORAGE_RULES>
"""

# Recipe mandate — injected when recipe library is available
_RECIPE_MANDATE = """\
<RECIPE_MANDATE>
If a ⚡ ACTION RECIPES AVAILABLE block appears in this prompt:
  • You MUST emit action="recipe" with recipe_name and recipe_params.
  • Planning individual clicks for that component is FORBIDDEN.
  • Supply recipe_params as shown in the recipe's example JSON exactly.
</RECIPE_MANDATE>
"""

# ---------------------------------------------------------------------------
# Action type → rule sections mapping
# ---------------------------------------------------------------------------

_ALWAYS_RULES = [_CORE_RULES]

_ACTION_TYPE_RULES: dict[str, list[str]] = {
    "navigate": [_NAVIGATION_RULES],
    "click": [_TABLE_RULES, _DROPDOWN_RULES],
    "fill": [_LOGIN_RULES],
    "select_option": [_DROPDOWN_RULES],
    "verify": [_VERIFY_RULES],
    "done": [_VERIFY_RULES],
    "set_input_files": [_UPLOAD_RULES],
    "wait": [],
    "scroll": [_TABLE_RULES],
    "press_key": [],
    "check": [],
    "uncheck": [],
    "primeng_dropdown": [_DROPDOWN_RULES],
    "recipe": [_RECIPE_MANDATE],
}

# Keyword → rule injection (scans AC step text)
_KEYWORD_RULES: list[tuple[list[str], list[str]]] = [
    # keywords, rule sections
    (["login", "log in", "sign in", "email", "password", "credential"], [_LOGIN_RULES]),
    (["logout", "log out", "sign out", "switch user", "role"], [_LOGOUT_RULES]),
    (["upload", "file", "browse", "attach", "mp3", "jpg", "wav"], [_UPLOAD_RULES]),
    (["sort", "ascending", "descending", "due date", "start date"], [_SORT_RULES]),
    (["table", "row", "client", "spot", "production order", "mybox", "next page"], [_TABLE_RULES]),
    (["status", "dropdown", "select", "combobox", "choose"], [_DROPDOWN_RULES]),
    (["verify", "assert", "check", "confirm", "ensure", "visible"], [_VERIFY_RULES]),
    (["localstorage", "jwt", "token", "sessionstorage"], [_LOCAL_STORAGE_RULES]),
    (["navigate", "url", "go to", "open", "page"], [_NAVIGATION_RULES]),
]


# ---------------------------------------------------------------------------
# PromptAssembler
# ---------------------------------------------------------------------------


class PromptAssembler:
    """
    Builds step-scoped system prompts for the planner.

    Parameters
    ----------
    enabled : bool
        When False, ``build_system_prompt()`` falls back to returning only
        the core rules (full prompt mode for callers that manage it externally).
        Default: True (reads from settings at call time).
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        # Cache the static sections once per instance
        self._static_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        ac_step: str,
        action_type: Optional[str],
        turn: int,
        target_url: str = "",
        include_global_rules: bool = True,
    ) -> str:
        """
        Build a step-scoped system prompt for the planner.

        Parameters
        ----------
        ac_step : str
            The current Acceptance Criteria step text.
        action_type : str | None
            Predicted action type (e.g. "click", "fill", "navigate").
            If None, all rules are included (full-context mode).
        turn : int
            Current planner iteration within the run. Used to decide
            whether to include global rules (turn == 0) or omit them.
        target_url : str
            Testing target URL — injected into navigation rules.
        include_global_rules : bool
            Whether to include global/core rules. Default True.

        Returns
        -------
        str
            The assembled system prompt string.
        """
        try:
            from backend.config import settings as _settings
            enabled = self._enabled and _settings.step_scoped_prompts_enabled
        except Exception:
            enabled = self._enabled

        if not enabled:
            # Fallback: just core rules
            return _CORE_RULES.strip()

        sections: list[str] = []

        # 1. Global/core rules (always on first turn, optional on later turns)
        if include_global_rules:
            sections.extend(_ALWAYS_RULES)

        # 2. Action-type scoped rules
        if action_type is None:
            # Include everything
            all_rule_sets: set[str] = set()
            for rule_list in _ACTION_TYPE_RULES.values():
                all_rule_sets.update(rule_list)
            sections.extend(list(all_rule_sets))
        else:
            action_key = action_type.lower().strip()
            type_rules = _ACTION_TYPE_RULES.get(action_key, [])
            sections.extend(type_rules)

        # 3. Keyword-based rules from AC step text
        step_lower = ac_step.lower()
        keyword_injected: set[str] = set()
        for keywords, rules in _KEYWORD_RULES:
            if any(kw in step_lower for kw in keywords):
                for rule in rules:
                    if rule not in keyword_injected and rule not in sections:
                        sections.append(rule)
                        keyword_injected.add(rule)

        # 4. Recipe mandate if available
        if _RECIPE_MANDATE not in sections:
            sections.append(_RECIPE_MANDATE)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for s in sections:
            if s not in seen:
                seen.add(s)
                deduped.append(s)

        prompt = "\n\n".join(s.strip() for s in deduped if s.strip())

        # Replace target URL placeholder if present
        if target_url:
            prompt = prompt.replace("{target_url}", target_url)

        logger.debug(
            "PromptAssembler: action_type=%s turn=%d sections=%d chars=%d",
            action_type,
            turn,
            len(deduped),
            len(prompt),
        )

        return prompt

    def get_static_sections(self) -> str:
        """
        Return the static (cacheable) sections of the system prompt.

        These sections do not change between turns and can be annotated
        with Anthropic prompt caching ``cache_control`` breakpoints to
        eliminate redundant input token cost on turns 2+.

        Returns
        -------
        str
            Static prompt sections (global rules, recipe mandate).
            Empty string if no static content is configured.
        """
        if self._static_cache is None:
            static_parts = [_CORE_RULES, _RECIPE_MANDATE]
            self._static_cache = "\n\n".join(p.strip() for p in static_parts if p.strip())
        return self._static_cache

    def get_dynamic_section(
        self,
        ac_step: str,
        action_type: Optional[str],
        target_url: str = "",
    ) -> str:
        """
        Return the dynamic (non-cacheable) section for the current step.

        This is the per-turn content that changes with each AC step.
        The assembler builds it from action-type scoped and keyword-injected rules.

        Parameters
        ----------
        ac_step : str
            The current AC step text.
        action_type : str | None
            Predicted action type.
        target_url : str
            Testing target URL — injected into navigation rules.

        Returns
        -------
        str
            Dynamic prompt sections for this specific step.
        """
        sections: list[str] = []

        # Action-type scoped rules
        if action_type is not None:
            action_key = action_type.lower().strip()
            type_rules = _ACTION_TYPE_RULES.get(action_key, [])
            sections.extend(type_rules)

        # Keyword-based rules
        step_lower = ac_step.lower()
        seen: set[str] = set(sections)
        for keywords, rules in _KEYWORD_RULES:
            if any(kw in step_lower for kw in keywords):
                for rule in rules:
                    if rule not in seen:
                        sections.append(rule)
                        seen.add(rule)

        result = "\n\n".join(s.strip() for s in sections if s.strip())
        if target_url:
            result = result.replace("{target_url}", target_url)
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_assembler: Optional[PromptAssembler] = None


def get_prompt_assembler() -> PromptAssembler:
    """
    Return the process-level singleton PromptAssembler.

    Creates the instance on first call.  Reads the ``step_scoped_prompts_enabled``
    feature flag from settings at instantiation time.

    Returns
    -------
    PromptAssembler
        The singleton instance.
    """
    global _default_assembler
    if _default_assembler is None:
        try:
            from backend.config import settings
            _default_assembler = PromptAssembler(enabled=settings.step_scoped_prompts_enabled)
        except Exception:
            _default_assembler = PromptAssembler(enabled=True)
    return _default_assembler
