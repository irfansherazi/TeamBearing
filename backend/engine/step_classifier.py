"""
vQA — AC Step Type Classifier
================================
Module: backend/engine/step_classifier.py

Classifies each Acceptance Criteria step into a semantic type that
the planner uses to select the most appropriate rules and prompts.

This is a rule-based classifier (no LLM call) — it runs in microseconds
and provides a structured signal to the planner's conditional rule
injection logic.

Step Types
----------
    NAVIGATE      — "Go to ...", "Navigate to ..."
    LOGIN         — "Log in as ...", "Authenticate as ..."
    FILL_FORM     — "Fill ...", "Type ...", "Enter ..."
    CLICK_NAV     — "Click ...<link/menu>" (navigational)
    CLICK_ACTION  — "Click ...<button/submit>" (triggers an action)
    VERIFY_TEXT   — "Verify ...", "Assert ...", "Ensure ..."
    VERIFY_RBAC   — "Verify access ...", "should not see ...", "is denied ..."
    DROPDOWN      — "Select ...", "Choose ...", "Pick ..."
    DATE_PICKER   — "Set date ...", "Due date ...", "Start date ..."
    WAIT          — "Wait for ...", "loading ..."
    COMPOUND      — Ambiguous or multi-action step (handled by general planner)

Usage
-----
    from backend.engine.step_classifier import classify_step, StepType

    step_type = classify_step("Click the Submit All button")
    # → StepType.CLICK_ACTION

See Also
--------
    - backend/engine/planner.py — consumes StepType for rule injection
"""

from enum import Enum

from backend.kb.unified_registry import unified_registry


class StepType(Enum):
    """Enumeration of AC step semantic types."""

    NAVIGATE = "navigate"
    LOGIN = "login"
    FILL_FORM = "fill_form"
    CLICK_NAV = "click_nav"
    CLICK_ACTION = "click_action"
    VERIFY_TEXT = "verify_text"
    VERIFY_RBAC = "verify_rbac"
    DROPDOWN = "dropdown"
    DATE_PICKER = "date_picker"
    WAIT = "wait"
    FILE_UPLOAD = "file_upload"  # File attach / upload / import steps
    VIEW_SWITCH = "view_switch"  # Table view density change (compact, list, minimal)
    ACCOUNT_SWITCH = "account_switch"  # Mid-test role switch via BrowserManager.switch_actor()
    COMPOUND = "compound"


# ---------------------------------------------------------------------------
# Keyword lists per type
# ---------------------------------------------------------------------------

# Trigger verbs that, combined with a role name, indicate a mid-test account switch.
# These are checked BEFORE _LOGIN_KW so "switch to production manager" → ACCOUNT_SWITCH
# rather than LOGIN.
_ACCOUNT_SWITCH_TRIGGERS = {
    "switch to ",
    "switch to the ",
    "switch account to",
    "switch user to",
    "log out and log in",
    "log out, then log in",
    "log out and sign in",
    "now as ",
    "now log in as",
    "now sign in as",
    "log in as the ",
    "log in as a ",
    "sign in as the ",
    "sign in as a ",
    "change account to",
    "switch back to ",
    "log back in as",
}

# Role name fragments that identify a canonical vSuite role.
# Used in combination with _ACCOUNT_SWITCH_TRIGGERS to detect mid-test switches.
_ROLE_NAME_KW = {
    "account executive",
    "production manager",
    "production director",
    "digital director",
    "voice talent",
    "voicer",
    "dubber",
    "producer",
    "sales manager",
    "sales assistant",
    "sales rep",
    "ae ",
    "ae,",
    " pm ",
    "pm,",
    "pm ",
    " gsm",
    "gm ",
    "gsm",
}

_LOGIN_KW = {
    "login",
    "log in",
    "sign in",
    "authenticate",
    "credentials",
    "username",
    "password",
    "switch user",
    "switch account",
    "switch back",
    "different user",
    "different account",
}
_NAVIGATE_KW = {
    "navigate to",
    "go to",
    "open url",
    "visit",
    "browse to",
    "load page",
    "direct to",
    "head to",
    "go into",
    "go back",
}
_DATE_KW = {"date", "calendar", "due date", "start date", "end date", "deadline", "scheduled", "picker"}
# Context fragments that indicate a step is NOT about picking a date but rather
# sorting/filtering by a date column — these disqualify DATE_PICKER classification.
_DATE_SORT_NEGATORS = {"column header", "sort ascending", "sort descending", "ascending", "descending", "sort by"}
_DROPDOWN_KW = {
    "select",
    "choose",
    "pick",
    "dropdown",
    "combobox",
    "option",
    "from the list",
    "opt for",
    "choose from",
    "from the dropdown",
    "from the menu",
}
_WAIT_KW = {"wait for", "loading", "spinner", "until", "appears", "should load"}
_VERIFY_KW = {
    "verify",
    "assert",
    "confirm",
    "ensure",
    "check that",
    "should",
    "visible",
    "appear",
    "see",
    "shown",
    "displayed",
    "present",
    "exist",
    "validate",
    "expect",
    "make sure",
}
_RBAC_KW = {
    "access",
    "permission",
    "role",
    "cannot",
    "denied",
    "forbidden",
    "hidden",
    "disabled",
    "should not",
    "unable to",
    "no access",
    "unauthorized",
}
_FILL_KW = {"fill", "type", "enter", "input", "write", "put", "insert", "provide", "supply", "populate", "specify"}
_FILE_UPLOAD_KW = {
    "upload",
    "attach file",
    "file upload",
    "import file",
    "add file",
    "set input files",
    "upload file",
    "attach a file",
    "upload a file",
    "upload the file",
    "attach the file",
    "drag and drop",
    "drag-and-drop",
    "add attachment",
    "attach attachment",
}
_VIEW_SWITCH_KW = {
    # Bare view-type words ("list view", "compact view") are intentionally
    # omitted here.  They appear in non-switch contexts:
    #   "Navigate to Production Orders list view" → NAVIGATE (not VIEW_SWITCH)
    #   "Click CLIENT column header...in compact view" → CLICK_NAV (not VIEW_SWITCH)
    # Only explicit switch/change/navigate-to-view phrases trigger VIEW_SWITCH.
    "switch to compact",
    "switch to list",
    "switch to standard",
    "switch to minimal",
    "change view",
    "change to compact",
    "change to list",
    "change to standard",
    "navigate to compact",
    "navigate to list",
    "navigate to minimal",
}
_CLICK_ACTION_KW = {
    "submit",
    "save",
    "confirm",
    "send",
    "create",
    "delete",
    "approve",
    "reject",
    "publish",
    "archive",
    "remove",
    "download",
    "restore",
    "dismiss",
}
_CLICK_NAV_KW = {"click", "press", "tap", "open", "expand", "collapse", "toggle"}


def classify_step(ac_step: str) -> StepType:
    """
    Classify a single AC step string into a StepType.

    Uses ordered keyword matching — more specific types are checked first
    so broad matches (like CLICK_NAV) don't swallow more specific ones.

    Args
    ----
    ac_step : str
        The raw acceptance criteria step text to classify.

    Returns
    -------
    StepType
        The best-match category for this step.

    Examples
    --------
    >>> classify_step("Log in as DemoProdDirector")
    StepType.LOGIN
    >>> classify_step("Set due date to 30 days from now")
    StepType.DATE_PICKER
    >>> classify_step("Verify the Submit All button is visible")
    StepType.VERIFY_TEXT
    >>> classify_step("Select Radio Commercial from the ad type dropdown")
    StepType.DROPDOWN
    """
    step = ac_step.lower().strip()

    # ── 0. ACCOUNT_SWITCH (before LOGIN — mid-test role switch) ──────────────
    # Requires BOTH a switch-trigger verb AND a recognisable role name so that
    # "switch to compact view" (no role name) still falls through to VIEW_SWITCH.
    if _any_in(step, _ACCOUNT_SWITCH_TRIGGERS) and _any_in(step, _ROLE_NAME_KW):
        return StepType.ACCOUNT_SWITCH

    # ── 1. LOGIN (check before NAVIGATE — login implies navigation too) ───────
    if _any_in(step, _LOGIN_KW):
        return StepType.LOGIN

    # ── 2. VIEW SWITCH (before NAVIGATE — "switch to compact view" must not become navigate) ─
    if _any_in(step, _VIEW_SWITCH_KW):
        return StepType.VIEW_SWITCH

    # ── 3. NAVIGATE ───────────────────────────────────────────────────────────
    if _any_in(step, _NAVIGATE_KW):
        return StepType.NAVIGATE

    # ── 4. DATE PICKER (check before DROPDOWN — dates have calendar widgets) ──
    # Guard: if the step is sorting/filtering BY a date column, it's a click
    # action (CLICK_NAV/CLICK_ACTION), not a date picker interaction.
    if _any_in(step, _DATE_KW) and not _any_in(step, _DATE_SORT_NEGATORS):
        return StepType.DATE_PICKER

    # ── 5. DROPDOWN ───────────────────────────────────────────────────────────
    if _any_in(step, _DROPDOWN_KW):
        return StepType.DROPDOWN

    # ── 6. WAIT ───────────────────────────────────────────────────────────────
    if _any_in(step, _WAIT_KW):
        return StepType.WAIT

    # ── 7. RBAC VERIFY (check before generic VERIFY — more specific) ──────────
    if _any_in(step, _VERIFY_KW) and _any_in(step, _RBAC_KW):
        return StepType.VERIFY_RBAC

    # ── 8. VERIFY TEXT ────────────────────────────────────────────────────────
    if _any_in(step, _VERIFY_KW):
        return StepType.VERIFY_TEXT

    # ── 9. FILL FORM ──────────────────────────────────────────────────────────
    if _any_in(step, _FILL_KW):
        return StepType.FILL_FORM

    # ── 10. FILE UPLOAD (before CLICK_ACTION — "upload" must get file-specific rules) ──
    if _any_in(step, _FILE_UPLOAD_KW):
        return StepType.FILE_UPLOAD

    # ── 11. CLICK ACTION (submit/save/create type buttons) ────────────────────
    if _any_in(step, _CLICK_ACTION_KW):
        return StepType.CLICK_ACTION

    # ── 12. CLICK NAV (generic click — lowest priority) ──────────────────────
    if _any_in(step, _CLICK_NAV_KW):
        return StepType.CLICK_NAV

    # ── 13. Fallback ─────────────────────────────────────────────────────────
    return StepType.COMPOUND


def _any_in(text: str, keywords: set[str]) -> bool:
    """Return True if any keyword appears as a substring of text."""
    return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# Rule injection helpers
# ---------------------------------------------------------------------------


def get_step_type_label(step_type: StepType) -> str:
    """Return a human-readable label for use in log messages and prompts."""
    labels = {
        StepType.LOGIN: "Authentication",
        StepType.NAVIGATE: "Navigation",
        StepType.DATE_PICKER: "Date Picker (PrimeNG)",
        StepType.DROPDOWN: "Dropdown / Select",
        StepType.WAIT: "Wait / Loading",
        StepType.VERIFY_RBAC: "RBAC Verification",
        StepType.VERIFY_TEXT: "Text/UI Verification",
        StepType.FILL_FORM: "Form Fill",
        StepType.CLICK_ACTION: "Action Button Click",
        StepType.CLICK_NAV: "Navigation Click",
        StepType.FILE_UPLOAD: "File Upload / Attach",
        StepType.VIEW_SWITCH: "Table View Switch",
        StepType.ACCOUNT_SWITCH: "Mid-Test Account Switch",
        StepType.COMPOUND: "Compound Step",
    }
    return labels.get(step_type, step_type.value)


def get_step_type_rules(step_type: StepType, ac_step_text: str = "") -> str:
    """
    Return specific rules for the given step type.

    These rules are injected into the planner system prompt as
    targeted guidance for the current step type. They are much more
    focused than the blanket rules injected for all steps.

    When ``ac_step_text`` is provided and PrimeNG components are detected
    in the step text, the component registry's ground-truth Playwright
    interaction protocols are appended to the rules. These protocols
    enforce exact selectors, wait timings, and forbidden patterns
    (e.g., fill() on p-autocomplete) that prevent the planner from
    guessing interaction strategies.

    Args
    ----
    step_type : StepType
        The classified step type.
    ac_step_text : str
        The raw AC step text (used for component detection).

    Returns
    -------
    str
        A block of rules formatted for injection into the system prompt.
        Empty string if the step type has no additional rules.
    """
    rules: dict[StepType, str] = {
        StepType.DATE_PICKER: (
            "DATE PICKER RULES (PrimeNG Calendar):\n"
            "- NEVER fill date fields directly with .fill() — Angular intercepts and rejects it\n"
            "- To open the calendar: click the calendar icon button (.p-datepicker-trigger) or the input\n"
            "- After opening: wait 500ms for the calendar panel to render\n"
            "- To select a day: click td.p-datepicker-day:not(.p-disabled)\n"
            "- After selecting a day: wait 500ms for Angular to process the value\n"
            "- To navigate months: click .p-datepicker-next\n"
        ),
        StepType.DROPDOWN: (
            "DROPDOWN / SELECT RULES:\n"
            "- PrimeNG dropdowns are NOT native <select> elements — do NOT use select_option\n"
            "- To open: click the dropdown trigger (get_by_role combobox, or .p-multiselect-trigger)\n"
            "- After opening: wait 300ms for options to render\n"
            "- To pick an option: use get_by_text(option_text) or click .p-multiselect-item\n"
            "- If the dropdown closes without selecting: the click was intercepted — use force=true\n"
            "- Client/Advertiser field autocomplete: use .type() not .fill(), wait 500ms, then click the dropdown option\n"
        ),
        StepType.VERIFY_RBAC: (
            "RBAC VERIFICATION RULES:\n"
            "- Do NOT attempt to interact with elements the role shouldn't have access to\n"
            "- Use 'verify' action with the element name to check visibility/presence\n"
            "- If the element SHOULD be hidden: verify it is NOT visible (success = element absent)\n"
            "- If the element SHOULD be visible: verify it IS visible\n"
            "- Check the role_constraints section above for this role's permission matrix\n"
        ),
        StepType.CLICK_ACTION: (
            "ACTION BUTTON RULES:\n"
            "- Buttons like 'Submit All', 'Save', 'Create' may be DISABLED until form is valid\n"
            "- If a button click fails: check if it is disabled (Angular form validation)\n"
            "- A disabled button needs ALL required fields filled before it becomes clickable\n"
            "- After a successful submit: wait for a toast notification or URL change to confirm\n"
            "- Use wait_for_response to detect silent API calls (no visible toast)\n"
        ),
        StepType.FILL_FORM: (
            "FORM FILL RULES:\n"
            "- After filling a field: Angular may debounce changes (300-500ms) — add wait if needed\n"
            "- If fill() is rejected (CVA): click the field first, then try fill() again\n"
            "- For read-only display fields: use 'verify' not 'fill'\n"
            "- Required fields (marked with *) must all be filled before Submit is enabled\n"
            "- ⚠ For p-autocomplete fields (e.g. Client): use .type() NOT .fill(). "
            "fill() is too fast and bypasses the 3-char debounce trigger.\n"
        ),
        StepType.NAVIGATE: (
            "NAVIGATION RULES:\n"
            "- Sidebar links in Angular do NOT have href= attributes — use get_by_text not a[href=...]\n"
            "- After clicking a sidebar link: wait for tbody tr to be visible (not networkidle)\n"
            "- If click is intercepted: use dispatchEvent (force=true equivalent)\n"
            "- Use the 'navigate' action only for full URL navigation (got to a new page)\n"
        ),
        StepType.FILE_UPLOAD: (
            "FILE UPLOAD RULES:\n"
            "- NEVER click a 'Browse' or 'Choose File' button — this opens a native OS dialog the agent cannot interact with\n"
            "- CORRECT method: use action='set_input_files' with strategy='css_selector' and name='p-fileupload input[type=\"file\"]' (or 'input[type=\"file\"]')\n"
            "- The selector targets the HIDDEN file input inside the PrimeNG p-fileupload component\n"
            "- For URL-based file attachment: click '#urlFileLink' (or 'URL as File' text), fill input[name='fileName'] and input[name='fileUrl'], click 'Upload File Using URL File'\n"
            "- After file upload: a file type dropdown (p-dropdown with 'Select a File Type' placeholder) will appear — click it and select the appropriate type\n"
            "- After selecting file type: click 'Save' button to persist the attachment\n"
            "- Available test assets: Final Spot 30.mp3, Client Logo.jpg, Background Music.mp3, Voice Part 1.mp3, Copy points.doc, Traffic Information File.pdf\n"
            "- Verification: check a#showFileTypeName is visible and its text matches the selected file type\n"
        ),
        StepType.VIEW_SWITCH: (
            "TABLE VIEW SWITCH RULES (compact/list/standard/minimal):\n"
            "- The view switcher is behind a Settings gear button: button#settings-btn\n"
            "- Step 1: click {'action': 'click', 'strategy': 'css_selector', 'name': 'button#settings-btn'}\n"
            "- Step 2: after the p-menu popup appears (wait 300ms), click the desired view by text:\n"
            "  - Compact view: {'action': 'click', 'strategy': 'get_by_text', 'name': 'Compact'}\n"
            "  - List/Standard view: {'action': 'click', 'strategy': 'get_by_text', 'name': 'List'}\n"
            "  - Minimal view: {'action': 'click', 'strategy': 'get_by_text', 'name': 'Minimal List'}\n"
            "- VERIFICATION: use persistent DOM class on div.po-table-wrapper (compact → .compact, list → .modern)\n"
            "  - {'action': 'verify', 'strategy': 'css_selector', 'name': 'div.po-table-wrapper.compact'}\n"
            "- DO NOT click Settings more than once without selecting a menu item in between\n"
            "- DO NOT use li#compact_listview.active for verification — the li disappears when menu closes\n"
            "- PREFERRED: use recipe action with recipe_name='compact_view_navigate' if available\n"
        ),
        StepType.ACCOUNT_SWITCH: (
            "ACCOUNT SWITCH RULES (mid-test role change):\n"
            "- This step requires NO browser interaction — the vQA graph handles the context switch automatically\n"
            "- IMMEDIATELY emit action='done' without clicking, filling, or navigating anything\n"
            "- The system will call BrowserManager.switch_actor() to instantly swap browser contexts (~50ms)\n"
            "- After this step completes, the next step will run as the new user in a fresh browser context\n"
            "- DO NOT attempt to click 'Log Out', fill the login form, or navigate to any page\n"
            "- DO NOT call any wait or verify actions — just emit done\n"
            '- Required done format: {"action": "done", "observation": "ACCOUNT_SWITCH step — no browser action needed",\n'
            '  "thought": "Emitting done; graph handles the role switch",\n'
            '  "reasoning": "ACCOUNT_SWITCH: graph-level context switch, emitting done immediately",\n'
            '  "kb_acknowledgement": "ACCOUNT_SWITCH rules: emit done immediately, no browser action"}\n'
        ),
        StepType.COMPOUND: (
            "COMPOUND STEP RULES (multi-action sequence):\n"
            "- This step requires multiple browser actions in sequence — treat it as a mini-workflow\n"
            "- DECOMPOSE the step text into individual sub-actions: identify each verb phrase separately\n"
            "- Execute ONE sub-action per planner response, then signal 'done' only when ALL sub-actions complete\n"
            "- Common compound patterns: 'Fill X and verify Y', 'Create Z then confirm', 'Navigate to A and check B'\n"
            "- If the step text contains 'and', 'then', 'then verify', treat each clause as a separate action\n"
            "- Check the KB results injected above — they may contain the exact workflow for this compound step\n"
            "- If the step involves a form: fill ALL required fields before clicking Submit\n"
            "- Use wait(300ms) between sub-actions to allow Angular change detection to stabilize\n"
        ),
    }

    base_rules = rules.get(step_type, "")

    # ── Component registry injection ──────────────────────────────────────
    # Detect PrimeNG components from the AC step text and append their
    # ground-truth interaction protocols to the rules.
    component_rules = ""
    if ac_step_text:
        detected = unified_registry.detect_components(ac_step_text)
        if detected:
            component_rules = unified_registry.get_rules_for_prompt(detected)

    if base_rules and component_rules:
        return base_rules + "\n" + component_rules
    return base_rules or component_rules


def detect_primeng_components(ac_step_text: str) -> tuple[list[str], str]:
    """
    Detect PrimeNG components in an AC step and return formatted rules.

    This is a convenience wrapper around the component registry for use
    by the planner when it needs component rules independent of step type
    classification (e.g., for compound steps or accessibility tree analysis).

    Args
    ----
    ac_step_text : str
        The current AC step text.

    Returns
    -------
    tuple[list[str], str]
        (detected_component_keys, formatted_rules_text)
        Either or both may be empty.
    """
    if not ac_step_text:
        return [], ""

    detected = unified_registry.detect_components(ac_step_text)
    if not detected:
        return [], ""

    rules = unified_registry.get_rules_for_prompt(detected)
    return detected, rules
