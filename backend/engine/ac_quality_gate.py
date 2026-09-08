"""
vQA — AC Quality Gate & Vague-AC Detection
=============================================
Module: backend/engine/ac_quality_gate.py

FEAT-001: Pre-parse quality scorer that evaluates raw Acceptance Criteria
text BEFORE it enters the Stage 1 BDD normalization pipeline.

The scorer is entirely rule-based (zero LLM cost) and evaluates five
quality dimensions on a 0–2 scale each (max 10 total):

    1. Specificity       — Does the AC name specific UI components?
    2. Observable Outcome — Does the AC describe a verifiable result?
    3. Actionability      — Does the AC use concrete action verbs?
    4. Precondition Clarity — Does the AC state the starting context?
    5. Scope Atomicity    — Is each AC step a single atomic action?

Quality Grades (fixed threshold):
    - GOOD  (7–10): AC is ready for the agent.
    - FAIR  (4–6):  AC will run but may cause vague-AC failures.
    - POOR  (0–3):  AC is rejected — user must refine before re-submitting.

Architecture Context
--------------------
  ac_parser_node (ac_parser.py)
      └── score_ac_quality(raw_ac)  ← called BEFORE Stage 1
              │
              ├── score ≥ 4  → proceed to Stage 1 BDD normalization
              └── score < 4  → REJECT: return quality assessment to user

Dependencies
------------
  - No external dependencies — pure Python stdlib + re

See Also
--------
  - backend/engine/ac_parser.py   — calls score_ac_quality()
  - backend/engine/validators.py  — post-parse step-level validation
  - backend/engine/reporter.py    — renders quality signals in HTML report
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ACQualityResult:
    """
    Structured quality assessment of raw Acceptance Criteria text.

    Attributes
    ----------
    raw_text : str
        The original AC text that was scored.
    overall_score : int
        Aggregate quality score (0–10).
    dimension_scores : dict[str, int]
        Per-dimension score breakdown. Keys:
        'specificity', 'observable_outcome', 'actionability',
        'precondition_clarity', 'scope_atomicity'.
    quality_grade : str
        "good" (7–10), "fair" (4–6), or "poor" (0–3).
    warnings : list[str]
        Human-readable quality issues found.
    step_scores : list[dict]
        Per-step quality breakdown for multi-step ACs.
        Each dict has 'step_text', 'score', 'warnings'.
    """

    raw_text: str
    overall_score: int = 0
    dimension_scores: dict = field(default_factory=dict)
    quality_grade: str = "poor"
    warnings: list = field(default_factory=list)
    step_scores: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for storage in VQAState."""
        return {
            "raw_text": self.raw_text[:500],  # truncate for state storage
            "overall_score": self.overall_score,
            "dimension_scores": self.dimension_scores,
            "quality_grade": self.quality_grade,
            "warnings": self.warnings,
            "step_scores": self.step_scores,
        }


# ---------------------------------------------------------------------------
# Constants — keyword lists for each dimension
# ---------------------------------------------------------------------------

# Specificity: PrimeNG component names and specific UI element patterns
_SPECIFIC_COMPONENT_PATTERNS: list[str] = [
    # PrimeNG components
    "p-select",
    "p-dropdown",
    "p-calendar",
    "p-datepicker",
    "p-autocomplete",
    "p-multiselect",
    "p-checkbox",
    "p-table",
    "p-toast",
    "p-confirmdialog",
    "p-fileupload",
    "p-overlaypanel",
    "p-dialog",
    "p-menu",
    "p-tabview",
    # Specific UI elements (with names)
    "submit all",
    "new request",
    "sort by",
    "save search",
    "compact view",
    "list view",
    "minimal view",
    "client column",
    "due date column",
    "status column",
    "action bar",
    "bulk approve",
    # CSS class / ID patterns
    "po-col-",
    "#sort-btn",
    ".sort-panel",
    ".p-select-",
]

# Generic UI references (score 1 instead of 0, but not 2)
_GENERIC_COMPONENT_PATTERNS: list[str] = [
    "the button",
    "the dropdown",
    "the table",
    "the form",
    "the modal",
    "the dialog",
    "the menu",
    "the panel",
    "the input",
    "the field",
    "the checkbox",
    "the link",
    "the page",
    "the calendar",
    "the picker",
    "a button",
    "a dropdown",
    "a table",
    "a form",
    "a modal",
    "column header",
    "the column",
    "the grid",
    "the view",
    "the screen",
    "the tab",
    "the row",
    "the item",
    "the search",
    "the header",
    "the footer",
    "the icon",
    "client",
    "spot",
    "order",
]

# Observable outcome: specific verifiable results
_SPECIFIC_OUTCOME_PATTERNS: list[str] = [
    # Toast / notification
    "toast",
    "notification",
    "success message",
    "error message",
    "toast appears",
    "toast shows",
    "toast displays",
    # URL / navigation
    "url changes",
    "url contains",
    "redirected to",
    "navigated to",
    "url shows",
    "/orders",
    "/login",
    "/dashboard",
    # Element state
    "is visible",
    "is hidden",
    "is disabled",
    "is enabled",
    "appears on",
    "disappears",
    "becomes visible",
    "is displayed",
    "is not displayed",
    "is not visible",
    # Sort direction
    "ascending",
    "descending",
    "a-z",
    "z-a",
    "sorted by",
    # Field value
    "field contains",
    "field shows",
    "value is",
    "value shows",
    "populated with",
    "filled with",
    "displays the value",
    # Count / quantity
    "count is",
    "shows 0",
    "shows 1",
    "rows are",
]

# Vague outcome words (already partially in validators.py _VAGUE_PATTERNS)
_VAGUE_OUTCOME_PATTERNS: list[str] = [
    "works correctly",
    "functions properly",
    "as expected",
    "should work",
    "is working",
    "works fine",
    "behaves correctly",
    "operates normally",
    "is functional",
    "is correct",
    "is proper",
    "is appropriate",
    "loads correctly",
    "renders correctly",
    "displays correctly",
    "updates correctly",
    "saves correctly",
]

# Actionability: specific interaction verbs
_SPECIFIC_ACTION_VERBS: list[str] = [
    "click",
    "fill",
    "type",
    "enter",
    "select",
    "choose",
    "navigate to",
    "go to",
    "open",
    "close",
    "toggle",
    "check",
    "uncheck",
    "upload",
    "download",
    "drag",
    "double-click",
    "right-click",
    "hover over",
    "press enter",
    "press tab",
    "press escape",
    "scroll to",
    "switch to",
    "log in as",
    "sign in as",
    "update",
    "save",
    "delete",
    "edit",
    "search for",
    "remove",
    "assign",
    "set",
    "pick",
    "clear",
]

# Generic verbs (score 1)
_GENERIC_ACTION_VERBS: list[str] = [
    "verify",
    "confirm",
    "check",
    "ensure",
    "validate",
    "assert",
    "test",
    "review",
    "inspect",
]

# Precondition clarity: explicit starting context
_PRECONDITION_PATTERNS: list[str] = [
    # Explicit page references
    "on the",
    "on production orders",
    "on the dashboard",
    "in compact view",
    "in list view",
    "in minimal view",
    "on the login page",
    "on the quick order",
    # Login state
    "logged in as",
    "authenticated as",
    "signed in as",
    "as account executive",
    "as producer",
    "as production",
    # State preconditions
    "after logging in",
    "after navigating",
    "after creating",
    "with the form open",
    "with the modal open",
    "given",
    "when the user is on",
]

# Implied precondition (score 1)
_IMPLIED_PRECONDITION_PATTERNS: list[str] = [
    "from the page",
    "from the view",
    "from the screen",
    "user can",
    "user should",
    "the user",
]


# ---------------------------------------------------------------------------
# Step splitter
# ---------------------------------------------------------------------------


def split_ac_into_steps(raw_ac: str) -> list[str]:
    """
    Split raw AC text into individual step strings.

    Handles common formats:
    - Numbered lists (1. ..., 2. ...)
    - Bulleted lists (- ..., * ...)
    - Given/When/Then blocks
    - Newline-separated sentences
    - Jira-style checkbox lists ([] ...)

    Returns
    -------
    list[str]
        Individual AC step strings, stripped and non-empty.
    """
    text = raw_ac.strip()
    if not text:
        return []

    # Try numbered list first (most common in Jira)
    numbered = re.split(r"\n\s*\d+[\.\)]\s*", text)
    if len(numbered) > 1:
        return [s.strip() for s in numbered if s.strip()]

    # Try bulleted list
    bulleted = re.split(r"\n\s*[-*•]\s*", text)
    if len(bulleted) > 1:
        return [s.strip() for s in bulleted if s.strip()]

    # Try Given/When/Then
    gherkin = re.split(r"\n\s*(?:Given|When|Then|And|But)\s+", text, flags=re.IGNORECASE)
    if len(gherkin) > 1:
        return [s.strip() for s in gherkin if s.strip()]

    # Try Jira checkbox format
    checkbox = re.split(r"\n\s*\[[\sx]?\]\s*", text)
    if len(checkbox) > 1:
        return [s.strip() for s in checkbox if s.strip()]

    # Fallback: split by newlines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        return lines

    # Single block — treat as one step
    return [text]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_specificity(text: str) -> tuple[int, list[str]]:
    """
    Score how specifically the AC references UI components.

    Returns
    -------
    tuple[int, list[str]]
        (score 0-2, list of warnings)
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Check for specific component references (score 2)
    for pattern in _SPECIFIC_COMPONENT_PATTERNS:
        if pattern in text_lower:
            return 2, warnings

    # Check for generic component references (score 1)
    for pattern in _GENERIC_COMPONENT_PATTERNS:
        if pattern in text_lower:
            warnings.append(
                f"Generic UI reference detected ('{pattern}'). "
                f"Name the specific component (e.g., 'p-select Sort By dropdown' "
                f"instead of 'the dropdown')."
            )
            return 1, warnings

    # No component reference at all (score 0)
    warnings.append(
        "No UI component referenced. Specify which element to interact with "
        "(e.g., 'Submit All button', 'Client column header', 'p-select dropdown')."
    )
    return 0, warnings


def _score_observable_outcome(text: str) -> tuple[int, list[str]]:
    """
    Score whether the AC describes a verifiable observable outcome.

    Returns
    -------
    tuple[int, list[str]]
        (score 0-2, list of warnings)
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Check for vague outcome patterns first (score 0 if matched)
    for pattern in _VAGUE_OUTCOME_PATTERNS:
        if pattern in text_lower:
            warnings.append(
                f"Vague outcome detected ('{pattern}'). "
                f"Replace with a specific observable: toast text, URL pattern, "
                f"element visibility, or field value."
            )
            return 0, warnings

    # Check for specific outcome patterns (score 2)
    for pattern in _SPECIFIC_OUTCOME_PATTERNS:
        if pattern in text_lower:
            return 2, warnings

    # Check if the step has ANY outcome clause
    outcome_signals = [
        "then",
        "verify",
        "should",
        "must",
        "expect",
        "assert",
        "confirm",
        "ensure",
        "validate",
        "appears",
        "shows",
        "displays",
        "contains",
        "changes",
        "updates",
        "becomes",
    ]
    has_outcome = any(signal in text_lower for signal in outcome_signals)

    if has_outcome:
        warnings.append(
            "Outcome is present but not specific enough. "
            "Add the exact expected result (e.g., 'toast shows \"Order saved\"' "
            "instead of 'verify the order is saved')."
        )
        return 1, warnings

    # No outcome at all — but this might be an action step (not a verify step)
    # Action steps without outcomes score 1 (they're valid intermediate steps)
    action_signals = ["click", "fill", "type", "select", "navigate", "open", "enter"]
    is_action = any(signal in text_lower for signal in action_signals)

    if is_action:
        # Action steps get a pass — outcome is implicit (action completes)
        return 1, warnings

    warnings.append(
        "No observable outcome described. Add what proves success: "
        "toast text, URL change, element visibility, or sort direction."
    )
    return 0, warnings


def _score_actionability(text: str) -> tuple[int, list[str]]:
    """
    Score whether the AC uses concrete, actionable verbs.

    Returns
    -------
    tuple[int, list[str]]
        (score 0-2, list of warnings)
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Check for specific action verbs (score 2)
    for verb in _SPECIFIC_ACTION_VERBS:
        if verb in text_lower:
            return 2, warnings

    # Check for generic verbs (score 1)
    for verb in _GENERIC_ACTION_VERBS:
        if verb in text_lower:
            warnings.append(
                f"Generic verb '{verb}' detected. Use a specific interaction verb (click, fill, select, navigate to)."
            )
            return 1, warnings

    # No verb at all or passive voice (score 0)
    # Check for passive patterns
    passive_patterns = [
        r"\bis\b",
        r"\bare\b",
        r"\bwas\b",
        r"\bwere\b",
        r"\bcan\b",
        r"\bshould\b",
        r"\bmust\b",
    ]
    is_passive = any(re.search(p, text_lower) for p in passive_patterns)

    if is_passive:
        warnings.append(
            "Passive or capability statement detected ('is', 'can', 'should'). "
            "Rewrite as a direct action: 'Click the Submit button' instead of "
            "'The user should be able to submit'."
        )
        return 0, warnings

    warnings.append("No action verb found. Start with a specific verb: click, fill, select, navigate to, verify.")
    return 0, warnings


def _score_precondition_clarity(text: str) -> tuple[int, list[str]]:
    """
    Score whether the AC states the starting context clearly.

    Returns
    -------
    tuple[int, list[str]]
        (score 0-2, list of warnings)
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Check for explicit precondition patterns (score 2)
    for pattern in _PRECONDITION_PATTERNS:
        if pattern in text_lower:
            return 2, warnings

    # Check for implied precondition patterns (score 1)
    for pattern in _IMPLIED_PRECONDITION_PATTERNS:
        if pattern in text_lower:
            warnings.append(
                "Precondition is implied but not explicit. "
                "State the starting context: 'On Production Orders compact view' "
                "or 'After logging in as Account Executive'."
            )
            return 1, warnings

    # No precondition context (score 0)
    warnings.append(
        "No starting context specified. Add where the user is and what state "
        "the app should be in (e.g., 'On the Production Orders page in compact view')."
    )
    return 0, warnings


def _score_scope_atomicity(text: str) -> tuple[int, list[str]]:
    """
    Score whether the AC step is a single atomic action.

    Returns
    -------
    tuple[int, list[str]]
        (score 0-2, list of warnings)
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Count action verbs in the text
    action_verbs = [
        "click",
        "fill",
        "type",
        "enter",
        "select",
        "choose",
        "navigate",
        "open",
        "close",
        "toggle",
        "check",
        "uncheck",
        "upload",
        "download",
        "verify",
        "confirm",
        "assert",
        "submit",
        "save",
        "delete",
        "edit",
        "update",
    ]

    found_verbs = [v for v in action_verbs if v in text_lower]

    # Check for "and" joining multiple actions
    if " and " in text_lower:
        parts = text_lower.split(" and ")
        verbs_per_part = [sum(1 for v in action_verbs if v in p) for p in parts]
        multi_action_parts = sum(1 for c in verbs_per_part if c > 0)

        if multi_action_parts >= 3:
            warnings.append(
                f"Compound step: {multi_action_parts} separate actions joined by 'and'. "
                f"Split into one action per step so failures can be pinpointed."
            )
            return 0, warnings
        elif multi_action_parts >= 2:
            warnings.append("Two actions joined by 'and'. Consider splitting into separate steps.")
            return 1, warnings

    # Check for semicolons or "then" joining actions
    if re.search(r";\s*\w", text) or re.search(r"\bthen\b", text_lower):
        if len(found_verbs) >= 2:
            warnings.append("Multiple actions chained with ';' or 'then'. Split into one action per step.")
            return 1, warnings

    # Single action (score 2) or very few verbs
    if len(found_verbs) <= 1:
        return 2, warnings

    # Multiple verbs but no explicit joining — likely a single complex step
    return 2, warnings


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_ac_quality(raw_ac: str) -> ACQualityResult:
    """
    Score raw Acceptance Criteria text for quality.

    This is the single public entry point for the quality gate.
    Called by ``ac_parser_node`` BEFORE Stage 1 BDD normalization.

    The scorer evaluates five dimensions on a 0–2 scale each (max 10),
    then assigns a quality grade:
        - GOOD  (7–10): AC is ready for the agent
        - FAIR  (4–6):  AC may cause vague-AC failures (warning)
        - POOR  (0–3):  AC is rejected — user must refine

    Args
    ----
    raw_ac : str
        Raw Acceptance Criteria text from Jira or user input.

    Returns
    -------
    ACQualityResult
        Structured quality assessment with scores, grade, and warnings.
    """
    result = ACQualityResult(raw_text=raw_ac)

    if not raw_ac or not raw_ac.strip():
        result.overall_score = 0
        result.quality_grade = "poor"
        result.warnings = ["Empty acceptance criteria — nothing to test."]
        result.dimension_scores = {
            "specificity": 0,
            "observable_outcome": 0,
            "actionability": 0,
            "precondition_clarity": 0,
            "scope_atomicity": 0,
        }
        return result

    # Split into individual steps
    steps = split_ac_into_steps(raw_ac)

    # Score each step individually
    all_warnings: list[str] = []
    step_results: list[dict] = []
    dimension_totals: dict[str, list[int]] = {
        "specificity": [],
        "observable_outcome": [],
        "actionability": [],
        "precondition_clarity": [],
        "scope_atomicity": [],
    }

    for step_text in steps:
        step_warnings: list[str] = []

        spec_score, spec_warn = _score_specificity(step_text)
        out_score, out_warn = _score_observable_outcome(step_text)
        act_score, act_warn = _score_actionability(step_text)
        pre_score, pre_warn = _score_precondition_clarity(step_text)
        atom_score, atom_warn = _score_scope_atomicity(step_text)

        step_warnings.extend(spec_warn)
        step_warnings.extend(out_warn)
        step_warnings.extend(act_warn)
        step_warnings.extend(pre_warn)
        step_warnings.extend(atom_warn)

        step_total = spec_score + out_score + act_score + pre_score + atom_score

        dimension_totals["specificity"].append(spec_score)
        dimension_totals["observable_outcome"].append(out_score)
        dimension_totals["actionability"].append(act_score)
        dimension_totals["precondition_clarity"].append(pre_score)
        dimension_totals["scope_atomicity"].append(atom_score)

        step_results.append(
            {
                "step_text": step_text[:200],  # truncate for storage
                "score": step_total,
                "max_score": 10,
                "warnings": step_warnings,
                "dimension_scores": {
                    "specificity": spec_score,
                    "observable_outcome": out_score,
                    "actionability": act_score,
                    "precondition_clarity": pre_score,
                    "scope_atomicity": atom_score,
                },
            }
        )

        # Prefix warnings with step context
        for w in step_warnings:
            all_warnings.append(
                f"[Step: '{step_text[:60]}...'] {w}" if len(step_text) > 60 else f"[Step: '{step_text}'] {w}"
            )

    # Compute overall score as the average across steps (rounded)
    if step_results:
        avg_score = sum(s["score"] for s in step_results) / len(step_results)
        result.overall_score = round(avg_score)
    else:
        result.overall_score = 0

    # Compute per-dimension averages
    result.dimension_scores = {
        dim: round(sum(scores) / len(scores)) if scores else 0 for dim, scores in dimension_totals.items()
    }

    # Assign quality grade
    if result.overall_score >= 7:
        result.quality_grade = "good"
    elif result.overall_score >= 4:
        result.quality_grade = "fair"
    else:
        result.quality_grade = "poor"

    # Pre-run detection: any mention of "ghost" (word boundary) on the card means
    # a GHOST_LOGIN step is needed and Admin credentials must be collected up front.
    import re as _re
    if _re.search(r'\bghost\b', raw_ac, _re.IGNORECASE):
        all_warnings.append("GHOST_CREDENTIALS_REQUIRED: Acceptance criteria contains ghost impersonation language. Pre-run Admin credentials are required to start this execution.")

    result.warnings = all_warnings
    result.step_scores = step_results

    logger.info(
        "AC Quality Gate: score=%d/10, grade=%s, steps=%d, warnings=%d",
        result.overall_score,
        result.quality_grade,
        len(step_results),
        len(all_warnings),
    )

    return result
