"""
vQA — Failure Classifier (FEAT-013)
======================================
Module: backend/engine/failure_classifier.py

Classifies executor error messages into structured categories so the
evaluator can apply different retry strategies per failure type instead
of using a flat retry counter.

Failure Categories
------------------
    TRANSIENT   — Network timeout, spinner delay, flaky timing.
                  Fix: auto-retry with forced wait (2s).

    SELECTOR    — Wrong locator, strict mode violation, element not found.
                  Fix: try alternative locator strategy.

    LOGIC       — Wrong page state, prerequisite not met, unexpected dialog.
                  Fix: backtrack to prerequisite or navigate to correct page.

    VALIDATION  — Action pre-validation failure (empty role, missing name).
                  Fix: let the planner re-plan with corrected parameters.

    UNKNOWN     — Unclassifiable error.
                  Fix: default retry, then HITL escalation.

Usage
-----
    from backend.engine.failure_classifier import classify_failure, FailureCategory

    category = classify_failure(error_message)
    if category == FailureCategory.TRANSIENT:
        # auto-retry with wait
    elif category == FailureCategory.SELECTOR:
        # try alternative locator

Dependencies
------------
  - ``backend/engine/evaluator.py`` — uses this to route retry logic
"""

import re
from enum import Enum


class FailureCategory(str, Enum):
    """Structured failure categories for intelligent retry routing."""

    TRANSIENT = "TRANSIENT"
    SELECTOR = "SELECTOR"
    LOGIC = "LOGIC"
    VALIDATION = "VALIDATION"
    UNKNOWN = "UNKNOWN"


# ── Pattern matchers per category ─────────────────────────────────────────
# Order matters: first match wins. More specific patterns should come first.

_TRANSIENT_PATTERNS: list[tuple[re.Pattern, FailureCategory]] = [
    # Network/timing failures
    (re.compile(r"timeout\s+\d+ms\s+exceeded", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"net::ERR_", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"navigation.*timeout", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"waiting for.*selector.*timeout", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"frame was detached", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"execution context was destroyed", re.I), FailureCategory.TRANSIENT),
    (re.compile(r"page\.wait_for", re.I), FailureCategory.TRANSIENT),
    # Selector/locator failures
    (re.compile(r"strict.?mode.?violation", re.I), FailureCategory.SELECTOR),
    (re.compile(r"STRICT_MODE_VIOLATION", re.I), FailureCategory.SELECTOR),
    (re.compile(r"locator.*resolved to.*elements", re.I), FailureCategory.SELECTOR),
    (re.compile(r"no element.*matches.*selector", re.I), FailureCategory.SELECTOR),
    (re.compile(r"Element is not (an |a )?<?(input|button|textbox)", re.I), FailureCategory.SELECTOR),
    (re.compile(r"element is not.*visible", re.I), FailureCategory.SELECTOR),
    (re.compile(r"element is outside.*viewport", re.I), FailureCategory.SELECTOR),
    (re.compile(r"waiting for locator", re.I), FailureCategory.SELECTOR),
    # Logic/state failures
    (re.compile(r"expected.*URL|unexpected.*page|wrong.*page", re.I), FailureCategory.LOGIC),
    (re.compile(r"prerequisite|precondition", re.I), FailureCategory.LOGIC),
    (re.compile(r"already (in|on|at).*state", re.I), FailureCategory.LOGIC),
    (re.compile(r"dialog|modal.*unexpected", re.I), FailureCategory.LOGIC),
    (re.compile(r"login.*required|session.*expired", re.I), FailureCategory.LOGIC),
    (re.compile(r"IDEMPOTENCY", re.I), FailureCategory.LOGIC),
    (re.compile(r"URL_MISMATCH", re.I), FailureCategory.LOGIC),
    # Validation failures (executor pre-checks)
    (re.compile(r"ActionValidationError", re.I), FailureCategory.VALIDATION),
    (re.compile(r"VALIDATION_BLOCKED", re.I), FailureCategory.VALIDATION),
    (re.compile(r"FORBIDDEN.*get_by_role", re.I), FailureCategory.VALIDATION),
    (re.compile(r"requires a non-empty", re.I), FailureCategory.VALIDATION),
    (re.compile(r"HARD_BLOCK", re.I), FailureCategory.VALIDATION),
]


def classify_failure(error_message: str) -> FailureCategory:
    """
    Classify an error message into a structured failure category.

    Scans the error message against known patterns in priority order.
    Returns FailureCategory.UNKNOWN if no pattern matches.

    Args
    ----
    error_message : str
        The raw error message from the executor or verifier.

    Returns
    -------
    FailureCategory
        The classified failure type.

    Examples
    --------
    >>> classify_failure("Timeout 15000ms exceeded")
    FailureCategory.TRANSIENT

    >>> classify_failure("STRICT_MODE_VIOLATION: locator matched 3 elements")
    FailureCategory.SELECTOR

    >>> classify_failure("ActionValidationError: empty role in get_by_role")
    FailureCategory.VALIDATION
    """
    if not error_message:
        return FailureCategory.UNKNOWN

    for pattern, category in _TRANSIENT_PATTERNS:
        if pattern.search(error_message):
            return category

    return FailureCategory.UNKNOWN


def get_retry_hint(category: FailureCategory) -> str:
    """
    Get a human-readable retry strategy hint for injection into the
    planner's agent_critique field.

    This hint tells the planner HOW to adjust its approach based on
    what kind of failure occurred, enabling more targeted self-healing.

    Args
    ----
    category : FailureCategory
        The classified failure type.

    Returns
    -------
    str
        Strategy hint for the planner.
    """
    hints = {
        FailureCategory.TRANSIENT: (
            "TRANSIENT FAILURE — The element likely exists but wasn't ready. "
            "Strategy: Add a 2-second wait before retrying the exact same action. "
            "Do NOT change the locator strategy — the timing was the issue, not the selector."
        ),
        FailureCategory.SELECTOR: (
            "SELECTOR FAILURE — The locator did not match the expected element. "
            "Strategy: Try an ALTERNATIVE locator strategy. If you used get_by_role, "
            "try get_by_text or css_selector. Check the INTERACTIVE ELEMENTS list for "
            "the correct element identifier. If strict mode, use container_selector to scope."
        ),
        FailureCategory.LOGIC: (
            "LOGIC FAILURE — The page is in an unexpected state. "
            "Strategy: Check if a prerequisite step was missed. Verify the current URL "
            "matches the expected page. If a dialog/modal is blocking, dismiss it first. "
            "Do NOT retry the same action — fix the page state first."
        ),
        FailureCategory.VALIDATION: (
            "VALIDATION FAILURE — The action JSON was malformed. "
            "Strategy: Review the error message and fix the action parameters. "
            "Common issues: empty 'role' in get_by_role, missing 'name', wrong action type."
        ),
        FailureCategory.UNKNOWN: (
            "UNKNOWN FAILURE — Could not classify the error. "
            "Strategy: Review the error message carefully and try a different approach."
        ),
    }
    return hints.get(category, hints[FailureCategory.UNKNOWN])
