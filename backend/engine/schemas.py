"""
vQA — Structured Test Plan Schemas + Planner Tool Schema
==========================================================
Module: backend/engine/schemas.py

This module contains two categories of Pydantic schemas:

1. **Test Plan Schemas** (existing): Used by the AC parser to compile a
   structured ``TestPlan`` from Jira ticket acceptance criteria.

2. **Planner Tool Schema** (new): ``PlannerAction`` enforces a strict JSON
   contract for every action the Planner LLM returns. By exposing this as
   a Bedrock ``toolSpec``, the API rejects structurally invalid responses
   at the network layer — before they ever reach our Python validator.

Architecture Context
--------------------
The ``PlannerAction`` Pydantic model has three jobs:
  1. Define the JSON schema for Bedrock ``toolConfig`` (``tool_use``)
  2. Serve as the single source of truth for allowed actions and strategies
  3. Validate the LLM's response via ``model_validate()`` before execution

``PLANNER_TOOL_CONFIG`` is the dict passed verbatim to ``bedrock.converse()``
as the ``toolConfig`` kwarg.  It forces Claude to call ``plan_action`` and
structure its response according to the Pydantic schema — hallucinated field
names and missing required fields become API-level errors, not runtime bugs.

See Also
--------
  - backend/engine/planner.py — consumes PLANNER_TOOL_CONFIG and PlannerAction
  - backend/engine/ac_parser.py — consumes TestPlan / StructuredACStep
  - backend/engine/state.py — VQAState stores TestPlan as dict
"""

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# SECTION 1: Test Plan Schemas (existing — unchanged)
# ============================================================================


class Verification(BaseModel):
    """
    A single programmatic assertion to prove an AC step succeeded.

    These replace implicit LLM visual verification with deterministic,
    Playwright-executable checks.  The verifier and executor can evaluate
    these without an LLM round-trip.

    Attributes
    ----------
    type : str
        The assertion strategy. Determines how the executor verifies:
        - ``element_visible``: ``await page.locator(selector_hint).is_visible()``
        - ``element_hidden``:  ``not await page.locator(selector_hint).is_visible()``
        - ``element_state``:   check disabled/enabled/checked via DOM attributes
        - ``network_response``: intercept a network request matching url_pattern
        - ``toast_message``:    wait for ``.p-toast-message`` containing expected_text
        - ``url_check``:        match current URL against url_pattern

    selector_hint : str | None
        CSS selector or Playwright locator hint for the target element.
        Example: ``".p-toast-detail"``, ``"#submit-btn"``

    expected_text : str | None
        Text that must be present in the element or toast.
        Example: ``"Order saved successfully"``

    expected_state : str | None
        DOM state to assert. One of: ``"disabled"``, ``"enabled"``,
        ``"checked"``, ``"unchecked"``, ``"selected"``.

    url_pattern : str | None
        Substring or regex to match against the page URL or a network
        request URL.  Example: ``"/api/orders"``

    status_code : int | None
        Expected HTTP status code for ``network_response`` assertions.
        Example: ``200``
    """

    type: Literal[
        "element_visible",
        "element_hidden",
        "element_state",
        "network_response",
        "toast_message",
        "url_check",
        "table_sort",  # Programmatic aria-sort assertion on PrimeNG column headers
        "visual_check",  # Multimodal LLM check
        "local_storage_check",  # Check a key in browser localStorage
    ] = Field(..., description="The programmatic assertion type.")

    selector_hint: Optional[str] = Field(None, description="Target DOM element for the assertion.")
    expected_text: Optional[str] = Field(None, description="Text that must be present.")
    expected_state: Optional[str] = Field(None, description="e.g., 'disabled', 'enabled', 'checked'.")
    url_pattern: Optional[str] = Field(None, description="Regex or substring for network/URL checks.")
    status_code: Optional[int] = Field(None, description="Expected HTTP status code.")
    # ── table_sort fields (Bug Fix #2) ────────────────────────────────────
    # The AC parser emits these for every table_sort verification, but they
    # were previously not declared — Pydantic silently stripped them, causing
    # the verifier to always fall back to the LLM (which said NOT_YET forever).
    expected_column: Optional[str] = Field(
        None,
        description=(
            "Visible column header label for table_sort assertions. "
            "Example: 'CLIENT', 'STATUS & APPROVALS', 'Due / Days'"
        ),
    )
    expected_direction: Optional[str] = Field(
        None,
        description=("Sort direction for table_sort assertions: 'ascending' or 'descending'."),
    )

    @field_validator("selector_hint")
    @classmethod
    def reject_transient_selectors(cls, v: Optional[str]) -> Optional[str]:
        """
        Reject selector_hint values that target transient/ephemeral DOM elements.

        These elements are removed from the DOM within ~100ms of the action that
        opens them (p-menu closes on item click; overlays close on selection).
        Checking visibility on them always returns NOT_YET at verifier time.

        Raise a ValueError so the AC parser call fails early with a clear
        diagnostic rather than silently compiling a bad test plan that loops
        at runtime against every run.
        """
        if v is None:
            return v
        _FORBIDDEN_PREFIXES_AND_SUBSTRINGS = [
            "li.active",
            ".active",
            "p-menu-list",
            "p-menu-overlay",
            "sort-panel",
            "p-select-overlay",
            "p-dropdown-panel",
            "p-overlaypanel",
            "p-tieredmenu",
            "p-contextmenu",
            "p-autocomplete-panel",
        ]
        v_lower = v.lower()
        for _pat in _FORBIDDEN_PREFIXES_AND_SUBSTRINGS:
            if _pat in v_lower:
                raise ValueError(
                    f"selector_hint '{v}' targets a transient/ephemeral DOM element "
                    f"(matched pattern: '{_pat}'). These elements close before the verifier "
                    f"executes and always produce NOT_YET loops. "
                    f"Use a PERSISTENT state marker instead: "
                    f"'div.po-table-wrapper.compact' for view switching; "
                    f"'th[aria-sort]' for sort state; "
                    f"URL route segment for navigation verification."
                )
        return v


class StructuredACStep(BaseModel):
    """
    A single typed test step in the structured test plan.

    Categorizes the interaction for the planner so it can skip
    interpretation and go directly to action selection.  Each step
    includes preconditions (what must be true before execution),
    a target component identifier, and explicit verification assertions.

    Attributes
    ----------
    step_id : int
        1-based sequential step number.

    goal : str
        A concise, human-readable summary of what this step achieves.
        This string is also used to populate the legacy
        ``acceptance_criteria_steps`` list for backward compatibility.

    step_type : str
        Categorizes the interaction type.  The planner uses this to
        select the correct component registry protocol and rule set.

    preconditions : list[str]
        Required states before this step can execute.  The planner
        checks these at the start of each step and navigates/fixes
        if any are unmet.
        Examples: ``["logged_in"]``, ``["on_production_orders_page"]``

    target_component : str
        The PrimeNG component or DOM element identifier.  Cross-referenced
        against ``knowledge/component_registry.json`` for interaction
        protocols.
        Examples: ``"p-calendar"``, ``"p-autocomplete"``, ``"submit-btn"``

    verification : list[Verification]
        1–3 explicit assertions to prove the step succeeded.
        Every step MUST have at least one verification.

    fallback_strategy : str | None
        What to do if the primary target is obscured or missing.
        Example: ``"use_status_filter_dropdown"``

    max_actions : int
        Hard cap on planner actions to prevent infinite loops on
        this step.  Default 15 for standard interactions; increase
        to 20+ for complex multi-field forms or large table navigation
        requiring multiple pagination steps (FEAT-104).
    """

    step_id: int
    goal: str = Field(..., description="A concise, human-readable summary of the step.")
    step_type: Literal[
        "NAVIGATE",
        "CLICK",
        "FILL",
        "SELECT_DROPDOWN",
        "TOGGLE_CHECKBOX",
        "DATE_SELECT",
        "VERIFY_ONLY",
        "SORT_COLUMN",  # Click a sortable column header
        "VERIFY_TABLE_SORT",  # Programmatic sort assertion (Python, not LLM)
        "ACCOUNT_SWITCH",  # Mid-test role/user switch via BrowserManager.switch_actor()
        "PERSONA_SWITCH",  # Mid-test auth context switch (replaces current session)
        "GHOST_LOGIN",  # Mid-test ghost login admin impersonation
    ] = Field(..., description="Categorizes the interaction for the Planner.")
    preconditions: list[str] = Field(
        default_factory=list,
        description="Required states before execution (e.g., 'logged_in', 'on_orders_page').",
    )
    target_component: Optional[str] = Field(
        None,
        description="The specific PrimeNG component or standard DOM element identifier.",
    )
    verification: list[Verification] = Field(
        default_factory=list,
        description="1 to 3 explicit assertions to prove the step succeeded.",
    )
    fallback_strategy: Optional[str] = Field(None, description="What to do if the target is obscured or missing.")
    max_actions: int = Field(
        default=15,
        description="Hard cap on Planner actions to prevent infinite loops.",
    )
    target_element_types: list[str] = Field(
        default_factory=list,
        description=(
            "List of ARIA roles relevant to this step (e.g., ['button', 'combobox']). "
            "Used for semantic ARIA tree pruning to reduce prompt size."
        ),
    )
    input_value: Optional[str] = Field(
        None,
        description=(
            "For FILL / SELECT_DROPDOWN / DATE_SELECT steps: the exact literal value "
            "to enter, taken verbatim from the Jira ticket description. "
            "Example: 'fake@email.com', 'fake', 'Test Spot Title'. "
            "Leave None if no specific value is given in the ticket."
        ),
    )
    target_persona: Optional[str] = Field(
        None,
        description=(
            "For PERSONA_SWITCH steps: the target persona name exactly as written in the "
            "Jira AC text (e.g. 'Demo Prod dir', 'yourself', 'Demo AE'). "
            "The persona_switch_node resolves this to a role_key via ROLE_REGISTRY + ROLE_ALIASES. "
            "None for all other step types."
        ),
    )
    target_user: Optional[str] = Field(
        None,
        description=(
            "For GHOST_LOGIN steps: the target user name or email exactly as written in the "
            "Jira AC text (e.g. 'Kat Morgan Gaines'). "
            "None for all other step types."
        ),
    )
    sub_steps: list[str] = Field(
        default_factory=list,
        description=(
            "Optional ordered list of atomic sub-action descriptions for compound steps "
            "that cannot be further decomposed at the BDD level (e.g., fill+submit). "
            "When non-empty, the executor performs each sub-action sequentially and "
            "ONLY runs verification[] checks after the final sub-step completes. "
            "Empty for all standard (already atomic) steps."
        ),
    )
    post_action_wait_ms: int = Field(
        default=0,
        description=(
            "Configurable post-action wait time in milliseconds to account for "
            "Angular/PrimeNG re-renders before verification. "
            "Default 0ms."
        ),
    )

    # ------------------------------------------------------------------
    # A11y Grounding Fields (accessibility-tree-grounding feature)
    # Populated post-login by ac_aria_enricher.py — NEVER hallucinated.
    # All three fields are Optional so existing recorded tests (which
    # lack them) route to the "selector_only_legacy" path unchanged.
    # ------------------------------------------------------------------
    aria_role: Optional[str] = Field(
        None,
        description=(
            "ARIA role for get_by_role() resolution — populated post-login by "
            "ac_aria_enricher (deterministic match against live ARIA snapshot). "
            "NEVER hallucinated. None for legacy recorded tests."
        ),
    )
    aria_name: Optional[str] = Field(
        None,
        description=(
            "ARIA accessible name — verbatim from the live ARIA tree, or None. "
            "Used by A11yLocatorResolver as the name= argument to get_by_role(). "
            "None triggers the selector_only_legacy path."
        ),
    )
    aria_disambiguators: Optional[list[str]] = Field(
        None,
        description=(
            "Optional list of disambiguation hints for A11Y_AMBIGUOUS recovery. "
            "Each entry is either a bare attribute name ('aria-label', 'placeholder', 'title') "
            "or an attribute=value pair ('aria-label:Save button'). "
            "Used by the recovery router to scope an ambiguous a11y match. "
            "None or empty → A11Y_AMBIGUOUS recovery cedes to STRICT_MODE."
        ),
    )


class TestPlan(BaseModel):
    __test__ = False
    """
    The complete structured test plan compiled from a Jira ticket.

    Produced by the two-stage AC parser and stored in
    ``VQAState.test_plan`` as a dict.

    Attributes
    ----------
    test_title : str
        Human-readable title derived from the Jira ticket summary.

    global_preconditions : list[str]
        Preconditions that apply to ALL steps (e.g., the test
        environment URL, required user role).

    steps : list[StructuredACStep]
        Ordered list of typed test steps to execute.
    """

    test_title: str
    global_preconditions: list[str] = Field(default_factory=list)
    steps: list[StructuredACStep]


class MultiActorStep(BaseModel):
    """
    A single step in a multi-actor test plan.
    """

    step_index: int
    actor: str = Field(..., description="The role or persona performing this step.")
    action: str = Field(..., description="The high-level action to perform.")
    description: str = Field(..., description="Human-readable description of the step.")
    state_output: dict[str, str] = Field(
        default_factory=dict,
        description="Variables captured during this step for use in subsequent steps.",
    )


class MultiActorTestPlan(BaseModel):
    """
    A holistic test plan for scenarios involving multiple actors.
    """

    test_plan_id: str
    test_title: str
    is_multi_actor: bool = True
    actors: list[str] = Field(..., description="List of actor roles involved in the test.")
    variables: list[str] = Field(default_factory=list, description="Shared variables across actors.")
    steps: list[MultiActorStep] = Field(..., description="Sequential steps of the multi-actor test.")


# ============================================================================
# SECTION 1b: Critic Pass LLM Evaluator Schema (critic-pass-llm-evaluator)
# ============================================================================


class CriticVerdict(BaseModel):
    """
    Structured verdict from critic_node comparing AC text against compiled TestPlan.

    The critic fires between ac_parser and setup_role, re-reading the raw AC text
    and compiled TestPlan with a Haiku model to detect plan-vs-AC drift before any
    browser work begins.

    Design follows the VerifierResult pattern in verifier.py:
      - flat Literal[...] discriminator for ``verdict`` and ``reason_codes``
      - peer ``feedback_summary`` field for human-readable rationale
      (mirrors ``VerifierResult.verdict`` + ``VerifierResult.evidence``)

    See: memory-bank/creative/critic-pass-llm-evaluator-architecture.md Q1 decision.
    """

    verdict: Literal["pass", "mismatch"]
    """Overall verdict: 'pass' to proceed, 'mismatch' to trigger retry."""

    reason_codes: list[
        Literal[
            "missing_step",
            "hallucinated_ac",
            "persona_mismatch",
            "order_violation",
            "ambiguous_step",
        ]
    ] = Field(default_factory=list)
    """Zero or more reason codes classifying the mismatch type.
    Empty list when verdict='pass'."""

    feedback_summary: str = Field(
        default="",
        description=(
            "Plain-English one-paragraph description of the mismatch, "
            "quoting the AC text and the discrepant TestPlan step. "
            "Empty string when verdict='pass'."
        ),
        max_length=1500,
    )
    """Human-readable rationale. Injected into the ac_parser retry as
    critic_feedback['guidance'] when verdict='mismatch'."""

    retry_count: int = Field(default=0, ge=0, le=2)
    """Number of critic-planner cycles already consumed for this run.
    Incremented by critic_node on each mismatch before writing state.
    Range: 0–2 (max_critic_retries=2)."""

    critic_skipped: bool = Field(default=False)
    """True when the Haiku call was skipped due to API error or critic_enabled=False.
    The run continues with a synthetic pass verdict."""


# ============================================================================
# SECTION 2: Planner Tool Schema (new)
# ============================================================================


class PlannerAction(BaseModel):
    """
    Strict Pydantic schema for a single Planner LLM action.

    This model is the basis for the Bedrock ``toolSpec`` that enforces
    the LLM's output contract at the API level.  Claude is required to
    call the ``plan_action`` tool and populate these fields — it cannot
    return free-form JSON or invent field names.

    Key Design Decisions
    --------------------
    - ``strategy`` is restricted to five strategies the executor actually
      implements.  ``css_selector`` is included for table column headers,
      sort dropdowns, and vqa_id-based disambiguation.  ``xpath`` is NOT
      supported and must never be used.
    - ``role`` and ``name`` are required when ``strategy == "get_by_role"``
      via a ``model_validator``.  Missing either raises a ``ValueError``
      with a clear message that is fed back to the LLM for self-correction.
    - ``vqa_id`` is the DOM-stamp fallback for strict-mode disambiguation.
      The ``model_validator`` allows it to substitute for ``strategy``+``name``
      when the failure diary indicates strict mode violations.
    - ``reasoning`` has a max_length of 150 chars to prevent the LLM from
      writing paragraphs in the audit field (which bloats the log).

    Field Summary
    -------------
    observation : str          — What the agent sees right now (ReAct: Observe)
    thought     : str          — Why this action was chosen (ReAct: Think)
    action      : str          — The browser action to perform
    strategy    : str | None   — Playwright locator method (required for most actions)
    role        : str | None   — ARIA role (required for get_by_role)
    name        : str | None   — Element text/label (required for most strategies)
    value       : str | None   — Fill text / option / key / URL
    vqa_id      : int | None   — DOM stamp ID for strict-mode fallback
    column      : str | None   — Column header for verify_table_sort
    order       : str | None   — Sort direction for verify_table_sort
    selector    : str | None   — CSS selector for set_input_files ONLY
    reasoning   : str          — Brief audit summary (max 150 chars)
    track_actor : dict | None  — Actor tracking for multi-role tests
    """

    observation: str = Field(
        description=(
            "What you currently see on the screen — current page state, "
            "relevant elements, what has or has not changed. Max 3 sentences."
        )
    )
    thought: str = Field(
        description=(
            "Why you are choosing this specific action — your reasoning about "
            "what to do next and why it will succeed given the current state. "
            "Max 2 sentences."
        )
    )
    action: Literal[
        "click",
        "fill",
        "select_option",
        "check",
        "uncheck",
        "navigate",
        "wait",
        "verify",
        "scroll",
        "press_key",
        "set_input_files",
        "verify_table_sort",
        "recipe",
        "primeng_dropdown",  # Atomic PrimeNG dropdown/combobox selection macro
        "coordinate_action",  # Vision-mode coordinate-based click/fill
        "fill_and_submit",  # FEAT-007: Fill a field + press Enter or click submit button
        "click_and_wait",  # FEAT-007: Click an element + wait for a target to appear
        "select_and_verify",  # FEAT-007: Select dropdown option + verify the result
        "semantic_click",  # TASK-094: Local coordinate-resolved click
        "semantic_fill",   # TASK-094: Local coordinate-resolved fill
        "done",
    ] = Field(description="The browser action to perform.")

    recipe_name: Optional[str] = Field(
        default=None,
        description=(
            "Name of the YAML recipe to execute atomically. "
            "ONLY valid when action='recipe'. "
            "Example: 'p_select_column_sort'. "
            "The recipe handles all sub-steps internally — do NOT plan individual clicks."
        ),
    )
    recipe_params: Optional[dict] = Field(
        default=None,
        description=(
            "Parameter values to fill into the recipe template. "
            "ONLY valid when action='recipe'. "
            "Keys must match the parameter names declared in the recipe YAML. "
            'Example: {"col_css": "th.po-col-duedaysCol", "direction": "Ascending"}'
        ),
    )

    strategy: Optional[
        Literal[
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
            "css_selector",
            "window",
            "coordinate_action",
        ]
    ] = Field(
        default=None,
        description=(
            "Playwright locator method. Required for click/fill/check/verify "
            "when vqa_id is not provided. "
            "Use 'get_by_role' + role/name for semantic targets. "
            "Use 'get_by_text' + name for view-switching menu items (Compact, List, Minimal). "
            "Use 'css_selector' + name=CSS when targeting table headers (th.po-col-clientCol), "
            "sort dropdowns, or vqa_id attributes ([data-vqa-id='N']). "
            "NEVER use css_selector for p-menu li items — they are removed from DOM when the menu closes. "
            "xpath is NOT supported."
        ),
    )
    role: Optional[str] = Field(
        default=None,
        description=(
            "ARIA role string. REQUIRED when strategy='get_by_role'. "
            "Examples: 'button', 'textbox', 'combobox', 'tab', 'columnheader', "
            "'checkbox', 'link', 'option', 'menuitem'."
        ),
    )
    name: Optional[str] = Field(
        default=None,
        description=(
            "The element's visible text, aria-label, or placeholder. "
            "REQUIRED for all strategies except 'navigate' and 'wait'. "
            "MUST match text visible in the interactive elements list."
        ),
    )
    value: Optional[str] = Field(
        default=None,
        description=(
            "The value to fill, option to select, key to press (e.g. 'Tab', 'Enter'), or URL for navigate actions."
        ),
    )
    vqa_id: Optional[int] = Field(
        default=None,
        description=(
            "DOM stamp ID from the INTERACTIVE ELEMENTS list (e.g., #5). "
            "Use ONLY when the Failure Diary shows a STRICT_MODE error on the "
            "target name — this is the fallback for strict mode disambiguation. "
            "Do NOT use vqa_id as the primary locator on first attempt."
        ),
    )
    column: Optional[str] = Field(
        default=None,
        description=("Column header text (exact). REQUIRED for action='verify_table_sort'. Example: 'Due / Days'"),
    )
    order: Optional[Literal["ascending", "descending"]] = Field(
        default=None,
        description="Sort direction. REQUIRED for action='verify_table_sort'.",
    )
    selector: Optional[str] = Field(
        default=None,
        description=(
            "CSS selector targeting the file input. "
            "ONLY for action='set_input_files'. "
            "Standard value: \"p-fileupload input[type='file']\""
        ),
    )
    container_selector: Optional[str] = Field(
        default=None,
        description=(
            "CSS selector for a container/ancestor element. When provided, the "
            "Playwright locator is SCOPED to this ancestor before applying the "
            "strategy + name. Use this to resolve STRICT_MODE_VIOLATION errors "
            "caused by the target text appearing multiple times on the page. "
            "Example: clicking 'Client' inside the sort popover when 'Client' "
            "also appears in table rows — pass container_selector='.sort-panel' "
            "so the locator is scoped: page.locator('.sort-panel').get_by_text('Client'). "
            "Also valid for dialog/modal scoping: 'p-dialog', '.p-overlaypanel', '#sort-btn ~ *'."
        ),
    )

    # ── primeng_dropdown fields ─────────────────────────────────────────────────
    # These three fields are REQUIRED when action='primeng_dropdown'.
    # They are ignored for all other action types.
    trigger_selector: Optional[str] = Field(
        default=None,
        description=(
            "REQUIRED for action='primeng_dropdown'. "
            "CSS selector or locator text for the dropdown trigger button to click first. "
            "Example: '.po-sorting-dropdown-panel-btn', '.sort-btn', '#sort-by-button'."
        ),
    )
    target_text: Optional[str] = Field(
        default=None,
        description=(
            "REQUIRED for action='primeng_dropdown'. "
            "The EXACT visible text of the option to click inside the portal overlay. "
            "Example: 'Due Date A-Z', 'Client Name', 'Ascending'."
        ),
    )
    portal_class: Optional[str] = Field(
        default=None,
        description=(
            "REQUIRED for action='primeng_dropdown'. "
            "CSS class of the PrimeNG portal overlay that appears after the trigger click. "
            "Example: '.po-sorting-dropdown-panel', '.sort-panel', '.p-select-overlay'. "
            "The executor waits for this portal to be visible before clicking the option."
        ),
    )

    # ── Vision-mode coordinate fields ──────────────────────────────────────
    # Used by coordinate_action and vision-mode primeng_dropdown.
    # mark_id references the numbered red box in the annotated screenshot.
    mark_id: Optional[int] = Field(
        default=None,
        description=(
            "REQUIRED for action='coordinate_action'. "
            "The numbered box ID from the annotated screenshot. "
            "Each interactive element has a unique red numbered box — provide that number here. "
            "Example: 7 (to click the element inside box #7)."
        ),
    )
    text_to_fill: Optional[str] = Field(
        default=None,
        description=(
            "For action='coordinate_action' when you need to type text after clicking. "
            "The click is performed at the mark coordinates, then this text is typed. "
            "Example: 'hello@example.com'"
        ),
    )
    trigger_mark_id: Optional[int] = Field(
        default=None,
        description=(
            "For action='primeng_dropdown' in VISION MODE. "
            "The numbered box ID of the dropdown trigger button from the annotated screenshot. "
            "Used INSTEAD of trigger_selector when operating in vision_mode='som_coordinates'. "
            "The executor clicks this coordinate to open the portal, then uses DOM-based "
            "Playwright logic to select the target_text inside the portal overlay."
        ),
    )

    # ── FEAT-007: Composite action fields ───────────────────────────────────────
    # These fields support the three composite action types that combine two
    # sequential Playwright interactions into a single atomic action.
    submit_strategy: Optional[Literal["enter", "click_button"]] = Field(
        default=None,
        description=(
            "REQUIRED for action='fill_and_submit'. How to submit after filling: "
            "'enter' presses Enter key, 'click_button' clicks a submit button "
            "identified by submit_name."
        ),
    )
    submit_name: Optional[str] = Field(
        default=None,
        description=(
            "For action='fill_and_submit' when submit_strategy='click_button'. "
            "The visible text of the submit button to click after filling. "
            "Example: 'Submit', 'Save', 'Apply'."
        ),
    )
    wait_for_selector: Optional[str] = Field(
        default=None,
        description=(
            "For action='click_and_wait'. CSS selector of the element to wait for "
            "after clicking. The executor waits up to 10s for this element to become visible. "
            "Example: '.success-banner', 'app-detail-panel', '.p-dialog'."
        ),
    )
    wait_for_text: Optional[str] = Field(
        default=None,
        description=(
            "For action='click_and_wait'. Text content to wait for in the DOM after clicking. "
            "Alternative to wait_for_selector — use when the target is identified by text. "
            "Example: 'Order saved successfully', 'Details Panel'."
        ),
    )
    verify_text: Optional[str] = Field(
        default=None,
        description=(
            "For action='select_and_verify'. The expected text to verify after selecting "
            "a dropdown option. Checked against the dropdown's visible label or page content. "
            "Example: 'Ascending', 'Active', 'Demo Client'."
        ),
    )
    reasoning: str = Field(
        description="Brief audit summary of why this action was taken. Max 500 chars.",
        max_length=500,
    )
    kb_acknowledgement: str = Field(
        description=(
            "REQUIRED. Summarise what the <human_intervention_rules> block tells you to do "
            "for THIS specific step. Quote the key selector or instruction verbatim. "
            "If the block explicitly states no rules were found, write "
            "'No KB rules found for this step.' "
            "DO NOT copy-paste this description — write the actual KB content summary."
        ),
    )
    track_actor: Optional[dict] = Field(
        default=None,
        description=(
            "Only include when actively selecting/assigning a person. "
            'Format: {"role": "voicer", "name": "Demo Voice Talent"}. '
            "Valid roles: voicer, editor, producer, mixer, reviewer."
        ),
    )
    state_expectation: Optional[str] = Field(
        default=None,
        description=(
            "A brief description of the immediate visible result expected from this action "
            "(e.g. 'Modal Dialog is visible', 'URL contains /success'). Used for fast-fail validation."
        )
    )

    @model_validator(mode="after")
    def validate_action_fields(self) -> "PlannerAction":
        """
        Cross-field validation: enforce required sub-fields per action type.

        Rules:
        - Locator actions (click/fill/check/uncheck/verify/select_option)
          MUST provide either vqa_id OR (strategy + role[if get_by_role] + name).
        - verify_table_sort MUST provide column AND order.
        - set_input_files MUST provide selector AND value.
        - navigate and wait do not require strategy/name.
        - done requires no additional fields.
        """
        LOCATOR_ACTIONS = {"click", "fill", "check", "uncheck", "verify", "select_option"}

        if self.action == "semantic_click":
            if not self.target:
                raise ValueError("action='semantic_click' requires 'target' — the description of the element to click (e.g. 'Save button').")
        elif self.action == "semantic_fill":
            if not self.target:
                raise ValueError("action='semantic_fill' requires 'target' — the description of the element to fill.")
            if not self.value:
                raise ValueError("action='semantic_fill' requires 'value' — the text to fill.")

        elif self.action in LOCATOR_ACTIONS:
            # vqa_id is a valid substitute for strategy+name (strict-mode fallback)
            if not self.vqa_id:
                if not self.strategy:
                    raise ValueError(
                        f"action='{self.action}' requires either 'vqa_id' or 'strategy'. "
                        f"Provide one of: get_by_role, get_by_text, get_by_label, get_by_placeholder."
                    )
                if self.strategy == "get_by_role":
                    if not self.role:
                        raise ValueError(
                            "strategy='get_by_role' requires 'role'. "
                            "Example: role='button', role='textbox', role='combobox'."
                        )
                    if not self.name:
                        raise ValueError(
                            f"strategy='get_by_role' with role='{self.role}' requires 'name' — "
                            f"the element's visible text or aria-label. "
                            f"A nameless get_by_role resolves to every '{self.role}' on the page."
                        )
                elif self.strategy not in ("window", "coordinate_action") and not self.name:
                    raise ValueError(
                        f"strategy='{self.strategy}' requires 'name' — the element's visible text or placeholder."
                    )

        elif self.action == "verify_table_sort":
            if not self.column:
                raise ValueError(
                    "action='verify_table_sort' requires 'column' — the exact column header text (e.g., 'Due / Days')."
                )
            if not self.order:
                raise ValueError("action='verify_table_sort' requires 'order': 'ascending' or 'descending'.")

        elif self.action == "set_input_files":
            if not self.selector:
                raise ValueError(
                    "action='set_input_files' requires 'selector' — "
                    "the CSS selector for the file input element. "
                    "Standard value: \"p-fileupload input[type='file']\""
                )
            if not self.value:
                raise ValueError(
                    "action='set_input_files' requires 'value' — the filename from the available test assets list."
                )

        elif self.action == "navigate":
            if not self.value:
                raise ValueError("action='navigate' requires 'value' — the full URL to navigate to.")

        elif self.action == "primeng_dropdown":
            # In vision mode, trigger_mark_id replaces trigger_selector
            if not self.trigger_selector and self.trigger_mark_id is None:
                raise ValueError(
                    "action='primeng_dropdown' requires either 'trigger_selector' (CSS) "
                    "or 'trigger_mark_id' (vision mode box number) to identify the "
                    "dropdown trigger. Example CSS: '.sort-btn'. "
                    "Example mark_id: 14 (from annotated screenshot)."
                )
            if not self.target_text:
                raise ValueError(
                    "action='primeng_dropdown' requires 'target_text' — "
                    "the exact visible text of the option to select inside the portal. "
                    "Example: 'Due Date A-Z', 'Client Name'."
                )
            if not self.portal_class:
                raise ValueError(
                    "action='primeng_dropdown' requires 'portal_class' — "
                    "the CSS class of the PrimeNG portal overlay to wait for. "
                    "Example: '.po-sorting-dropdown-panel', '.sort-panel'."
                )

        elif self.action == "coordinate_action":
            if self.mark_id is None:
                raise ValueError(
                    "action='coordinate_action' requires 'mark_id' — "
                    "the numbered box ID from the annotated screenshot. "
                    "Look at the red numbered boxes in the screenshot and provide that number."
                )

        elif self.action == "press_key":
            if not self.value:
                raise ValueError(
                    "action='press_key' requires 'value' — the key to press (e.g., 'Tab', 'Enter', 'Escape')."
                )

        elif self.action == "recipe":
            if not self.recipe_name:
                raise ValueError(
                    "action='recipe' requires 'recipe_name' — "
                    "the name of the YAML recipe to execute (e.g., 'p_select_column_sort'). "
                    "Check knowledge/blueprints/*.yaml for available recipe names."
                )
            # recipe_params is optional — recipes with no parameters are valid

        # ── FEAT-007: Composite action cross-field validators ────────────────

        elif self.action == "fill_and_submit":
            # Requires same locator fields as fill + submit_strategy
            if not self.vqa_id:
                if not self.strategy:
                    raise ValueError(
                        "action='fill_and_submit' requires 'strategy' (or 'vqa_id'). Same locator rules as 'fill'."
                    )
                if self.strategy == "get_by_role":
                    if not self.role:
                        raise ValueError("action='fill_and_submit' with strategy='get_by_role' requires 'role'.")
                    if not self.name:
                        raise ValueError("action='fill_and_submit' with strategy='get_by_role' requires 'name'.")
                elif not self.name:
                    raise ValueError(f"action='fill_and_submit' with strategy='{self.strategy}' requires 'name'.")
            if not self.value:
                raise ValueError("action='fill_and_submit' requires 'value' — the text to fill into the field.")
            if not self.submit_strategy:
                raise ValueError(
                    "action='fill_and_submit' requires 'submit_strategy': "
                    "'enter' (press Enter after fill) or 'click_button' (click a submit button). "
                    'Example: {"submit_strategy": "enter"}'
                )
            if self.submit_strategy == "click_button" and not self.submit_name:
                raise ValueError(
                    "action='fill_and_submit' with submit_strategy='click_button' requires "
                    "'submit_name' — the visible text of the submit button. "
                    'Example: {"submit_name": "Save"}'
                )

        elif self.action == "click_and_wait":
            # Requires same locator fields as click + wait target
            if not self.vqa_id:
                if not self.strategy:
                    raise ValueError(
                        "action='click_and_wait' requires 'strategy' (or 'vqa_id'). Same locator rules as 'click'."
                    )
                if self.strategy == "get_by_role":
                    if not self.role:
                        raise ValueError("action='click_and_wait' with strategy='get_by_role' requires 'role'.")
                    if not self.name:
                        raise ValueError("action='click_and_wait' with strategy='get_by_role' requires 'name'.")
                elif not self.name:
                    raise ValueError(f"action='click_and_wait' with strategy='{self.strategy}' requires 'name'.")
            if not self.wait_for_selector and not self.wait_for_text:
                raise ValueError(
                    "action='click_and_wait' requires either 'wait_for_selector' (CSS) or "
                    "'wait_for_text' (DOM text) to know what to wait for after clicking. "
                    'Example: {"wait_for_selector": ".detail-panel"} or '
                    '{"wait_for_text": "Order saved"}'
                )

        elif self.action == "select_and_verify":
            # Requires same locator fields as select_option + verify_text
            if not self.vqa_id:
                if not self.strategy:
                    raise ValueError(
                        "action='select_and_verify' requires 'strategy' (or 'vqa_id'). "
                        "Same locator rules as 'select_option'."
                    )
                if self.strategy == "get_by_role":
                    if not self.role:
                        raise ValueError("action='select_and_verify' with strategy='get_by_role' requires 'role'.")
                    if not self.name:
                        raise ValueError("action='select_and_verify' with strategy='get_by_role' requires 'name'.")
                elif not self.name:
                    raise ValueError(f"action='select_and_verify' with strategy='{self.strategy}' requires 'name'.")
            if not self.value:
                raise ValueError("action='select_and_verify' requires 'value' — the option to select.")
            if not self.verify_text:
                raise ValueError(
                    "action='select_and_verify' requires 'verify_text' — "
                    "the expected text to verify after selection. "
                    'Example: {"verify_text": "Ascending"}'
                )

        return self

    @model_validator(mode="after")
    def block_invalid_dropdown_clicks(self) -> "PlannerAction":
        """
        Pydantic Interceptor: Block standard ``click`` actions on PrimeNG dropdown triggers.

        This validator is a programmatic guardrail that fires AFTER ``validate_action_fields``.
        It catches the most common hallucination pattern — the LLM emitting ``action=\"click\"``
        on a PrimeNG ``p-select``, ``#sort-btn``, or combobox trigger — and raises a fatal
        ``ValueError``.  Bedrock surfaces the error as a ``tool_result`` with ``status='error'``,
        which is automatically appended to the conversation and forces the LLM to retry with
        ``action='primeng_dropdown'`` instead.

        Safe-pass conditions (validator does NOT fire):
        - The action is not ``"click"`` or ``"select_option"`` on a PrimeNG target.
        - ``container_selector`` is set — this means the click is scoped INSIDE an already-open
          portal overlay (the safe option-picking pattern), which is allowed.
        - The target keyword matches a plain table column header (``th.po-col-``), a regular
          button ID, or an option list item — these are NOT dropdown triggers.

        Forbidden targets (trigger the interceptor):
        - Any name/selector mentioning ``#sort-btn``, ``sort-btn``, ``.sort-btn``
        - ``p-select``, ``.p-select``, ``.p-select-label``, ``.p-select-trigger``
        - ARIA role ``combobox`` WITHOUT a ``container_selector`` (bare combobox trigger click)
        - ``header-sort-drop-down`` (the Due/Days and Start/End p-select IDs)
        - ``Due / Days`` or ``Start / End`` as target names (the visible column text)
        - ``select`` appearing in ``name`` combined with ``get_by_role`` or ``css_selector``
          — catches ``get_by_role('button', name='Sort By Select')`` style patterns
        """
        # Only intercept click and select_option — other actions are irrelevant here
        if self.action not in ("click", "select_option"):
            return self

        # ── Safe-pass: container_selector is set ─────────────────────────────
        # If container_selector is provided, the click is scoped INSIDE an already-open
        # portal (e.g., container_selector=".sort-panel") — this is the correct option-picking
        # pattern and must NOT be blocked.
        if self.container_selector:
            return self

        # ── Build the combined target string for matching ─────────────────────
        # Aggregate all fields that could identify the target element.
        candidate_parts = [
            str(self.name or ""),
            str(self.selector or ""),
            str(self.role or ""),
            str(self.trigger_selector or ""),
        ]
        target_str = " ".join(candidate_parts).lower()

        # ── Forbidden trigger fingerprints ────────────────────────────────────
        # Each entry is a substring that identifies a PrimeNG dropdown trigger.
        # Plain table headers (th.po-col-clientCol) are NOT in this list — those
        # use standard click and are correct.
        FORBIDDEN_TRIGGER_FINGERPRINTS = [
            "#sort-btn",
            "sort-btn",
            ".sort-btn",
            "p-select",
            ".p-select",
            "p-select-label",
            ".p-select-label",
            "p-select-trigger",
            ".p-select-trigger",
            "header-sort-drop-down",  # p-select#header-sort-drop-down-duedaysCol etc.
            "due / days",  # Visible column header text for the disabled th
            "start / end",  # Visible column header text for the disabled th
            "po-sorting-dropdown-panel-btn",  # The trigger button class used in some templates
            "po-sorting-dropdown",  # Partial match for the sort panel trigger
        ]

        matched_fingerprint: str | None = None
        for fp in FORBIDDEN_TRIGGER_FINGERPRINTS:
            if fp in target_str:
                matched_fingerprint = fp
                break

        if matched_fingerprint:
            # Determine whether this is a custom sort combobox (Due/Days, Start/End) or a
            # standard PrimeNG dropdown.  Custom comboboxes use .po-sorting-dropdown-panel
            # and MUST use primeng_dropdown (atomic open+wait+select in one action).
            is_custom_sort_combobox = any(
                kw in target_str
                for kw in [
                    "header-sort-drop-down",
                    "duedayscol",
                    "startendcol",
                    "due / days",
                    "start / end",
                ]
            )
            if is_custom_sort_combobox:
                raise ValueError(
                    f"INTERCEPTOR BLOCKED: '{target_str.strip()}' is a custom sort combobox "
                    f"(matched fingerprint: '{matched_fingerprint}'). "
                    f"Do NOT use bare click on this element — use a SINGLE primeng_dropdown action "
                    f"which opens the trigger and clicks the option atomically:\n"
                    f'  {{"action": "primeng_dropdown", '
                    f'"trigger_selector": "th.po-col-duedaysCol p-select", '
                    f'"target_text": "Due Date", '
                    f'"portal_class": ".po-sorting-dropdown-panel"}}\n'
                    f"  (For Start/End use trigger_selector: 'th.po-col-startendCol p-select')"
                )
            raise ValueError(
                f"INTERCEPTOR BLOCKED: You attempted action='{self.action}' on a PrimeNG "
                f"dropdown trigger '{target_str.strip()}' (matched forbidden fingerprint: '{matched_fingerprint}'). "
                f"This causes an infinite toggle loop. "
                f"Use action='primeng_dropdown' with trigger_selector, target_text, and portal_class. "
                f'Example: {{"action": "primeng_dropdown", '
                f'"trigger_selector": "button#sort-btn", '
                f'"target_text": "Client", "portal_class": ".sort-panel"}}'
            )

        return self


# ============================================================================
# SECTION 3: Bedrock Tool Configuration (derived from PlannerAction schema)
# ============================================================================


def _build_tool_config() -> dict:
    """
    Build the Bedrock ``toolConfig`` dict from the ``PlannerAction`` schema.

    This is called once at module load time and cached as ``PLANNER_TOOL_CONFIG``.
    The schema is derived from ``PlannerAction.model_json_schema()`` so the
    tool definition always stays in sync with the Pydantic model — there is
    no manual JSON schema to maintain separately.

    The ``toolChoice`` key forces Claude to always call ``plan_action`` —
    it cannot return a plain text response or call no tools.

    Returns
    -------
    dict
        The complete ``toolConfig`` dict for ``bedrock.converse()``.
    """
    json_schema = PlannerAction.model_json_schema()

    # Bedrock toolSpec requires the schema nested under "json"
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": "plan_action",
                    "description": (
                        "Plan and return the single next browser action to execute "
                        "in order to progress the current Acceptance Criteria step. "
                        "You MUST call this tool. Do not return plain text."
                    ),
                    "inputSchema": {
                        "json": json_schema,
                    },
                }
            }
        ],
        # Force tool use: Claude MUST call plan_action in every response.
        "toolChoice": {"tool": {"name": "plan_action"}},
    }


#: Bedrock toolConfig dict — pass directly to bedrock.converse(toolConfig=...).
#: Derived from PlannerAction.model_json_schema() at import time.
PLANNER_TOOL_CONFIG: dict = _build_tool_config()


# ============================================================================
# SECTION 3: Exploration Mode Schemas (FEAT-040)
# ============================================================================


class ExplorationOutcome(TypedDict, total=False):
    """
    Structured record of one Exploration Mode episode.

    One ``ExplorationOutcome`` is produced per exploration attempt and
    accumulated in ``VQAState.exploration_outcomes`` via the ``operator.add``
    LangGraph reducer.  This allows the reporter and status API to surface
    exploration history without re-traversing the detailed_execution_log.

    Attributes
    ----------
    ac_step_index : int
        Zero-based index of the AC step that triggered exploration.

    strategy_used : str
        Name of the strategy that was executed.  One of:
        ``"scroll_to_reveal"``, ``"expand_collapsed_parent"``,
        ``"click_sibling_tab"``, ``"none"`` (Phase 1 stub).

    steps_taken : int
        Total Playwright actions dispatched during this episode.
        Bounded by ``EXPLORATION_MAX_STEPS`` from config.

    found : bool
        ``True`` if the target element was located; ``False`` otherwise.

    kb_injected : bool
        ``True`` if a KB entry was successfully written to
        ``knowledge/human_guidance.md`` after a successful exploration.
        Always ``False`` when ``found=False``.

    target_element : str
        Short human-readable name of the element being sought.
        Derived from the AC step text or agent critique.

    pathway_summary : str
        Human-readable serialisation of the discovered navigation pathway.
        Example: ``"scroll_to_bottom → element visible"``.
        Empty string when ``found=False``.

    error_message : str
        Exception or reason string when ``found=False``.
        Empty string when ``found=True``.
    """

    ac_step_index: int
    strategy_used: str
    steps_taken: int
    found: bool
    kb_injected: bool
    target_element: str
    pathway_summary: str
    error_message: str
    action_log: list[dict]  # High-fidelity actions: {type, selector, value, timestamp, delta}
    dom_snapshots: list[dict]  # Snapshots: {timestamp, aria_tree, screenshot_b64}
