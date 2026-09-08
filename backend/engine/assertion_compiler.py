"""
backend/engine/assertion_compiler.py
=======================================
TASK-080-P2B: Playwright-Native Assertion Bypass for FEAT-060.

Parses AC step text and generates a sequence of Playwright-executable
assertions. When ALL compiled assertions pass, the LLM verifier is skipped —
reducing unnecessary multimodal LLM calls on deterministic verification steps.

Patterns compiled:
  - element_visible   — "verify X is visible" / "verify X appears"
  - contains_text     — "verify page contains 'X'" / "verify 'X' is displayed"
  - url_check         — "verify URL contains 'X'"
  - value_check       — "verify field value is 'X'"
  - count_check       — "verify N items are shown"

Target: bypass LLM on ≥ 40% of AC steps (AC-HAPPY-3).

Feature flag: NATIVE_ASSERTION_ENABLED (default true)
  When false: compile() always returns [], make_bypass_decision() always
  returns should_bypass=False (pre-FEAT-060 behavior preserved exactly).

Design: See TASK-080 Specification Item 5.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CompiledAssertion:
    """
    A single compiled Playwright-style assertion extracted from AC step text.

    Attributes:
        assertion_type: One of 'element_visible', 'contains_text', 'url_check',
                        'value_check', 'count_check'.
        expected_value: The text, URL fragment, count, or value to assert.
        selector_hint:  Optional CSS selector to scope element checks.
        description:    Human-readable description for audit logs.
    """

    assertion_type: str
    expected_value: str | int | None = None
    selector_hint: str = ""
    description: str = ""


@dataclass
class AssertionResult:
    """
    Result of executing a single CompiledAssertion.

    Attributes:
        passed:         True if the assertion passed, False otherwise.
        evidence:       Description of what was observed.
        assertion_type: The assertion type that produced this result.
    """

    passed: bool
    evidence: str = ""
    assertion_type: str = ""


@dataclass
class BypassDecision:
    """
    Decision on whether to bypass the LLM verifier.

    Attributes:
        should_bypass: True if all assertions passed and LLM can be skipped.
        evidence:      Combined evidence string from all assertions.
        bypass_count:  Number of assertions that passed.
    """

    should_bypass: bool = False
    evidence: str = ""
    bypass_count: int = 0


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Compiled regex patterns for AC step text → assertion type mapping.
# Each pattern is a tuple of (compiled_regex, assertion_type, capture_group).
#
# Design notes:
# - All patterns are case-insensitive.
# - Patterns extract the expected value from a named or positional group.
# - Ordering matters: more specific patterns first (URL before generic text).

_PATTERNS: list[tuple[re.Pattern, str, str | None]] = [
    # URL check: "verify URL contains '/path'" or "verify the URL is '/path'"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:the\s+)?url\s+"
            r"(?:contains?|includes?|has|is|equals?)\s+['\"]?([^'\"]+)['\"]?",
            re.IGNORECASE,
        ),
        "url_check",
        None,  # group 1
    ),
    # Count check: "verify 3 items are displayed" / "verify there are 5 rows"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:there\s+are\s+)?(\d+)\s+"
            r"(?:item|row|record|result|entr|order|ticket)s?\s+"
            r"(?:are\s+)?(?:displayed?|shown?|visible|present|listed?)",
            re.IGNORECASE,
        ),
        "count_check",
        None,  # group 1 = count
    ),
    # Title/field equals check: "verify page title is 'X'" / "verify heading is 'X'"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:the\s+)?(?:page\s+)?"
            r"(?:title|heading|label|text|caption|name|value|content)\s+"
            r"(?:is|equals?|reads?)\s+['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "contains_text",
        None,
    ),
    # Text visible: "verify 'Success' is displayed" / "verify page shows 'X'"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:the\s+)?(?:page\s+)?"
            r"(?:displays?|shows?|contains?|includes?|has)\s+['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "contains_text",
        None,  # group 1
    ),
    # Text appears: "verify 'Success' message appears" / "'Error' appears on page"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?['\"]([^'\"]+)['\"]"
            r"\s+(?:message\s+)?(?:appears?|shows?|is\s+(?:visible|displayed|shown|present))",
            re.IGNORECASE,
        ),
        "contains_text",
        None,
    ),
    # Value check: "verify the Name field value is 'X'" / "field contains 'X'"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:the\s+)?[\w\s]+?"
            r"(?:field|input|textbox|value)\s+"
            r"(?:value\s+)?(?:is|equals?|contains?)\s+['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        "value_check",
        None,
    ),
    # Element visible: "verify the Submit button is visible" / "verify X appears"
    (
        re.compile(
            r"(?:verify|confirm|ensure|check)\s+(?:that\s+)?(?:the\s+)?([\w\s]+?)"
            r"(?:button|link|tab|menu|icon|label|heading|section|panel|dialog|modal)?"
            r"\s+(?:is\s+)?(?:visible|present|displayed?|shown?|appear)",
            re.IGNORECASE,
        ),
        "element_visible",
        None,
    ),
]

# Semantic/visual patterns that cannot be programmatically compiled.
# If any of these appear in the AC step, we do NOT attempt compilation.
_VISUAL_KEYWORDS = frozenset(
    [
        "looks correct",
        "looks like",
        "looks good",
        "appears correct",
        "appears to be",
        "visually",
        "layout",
        "color",
        "colour",
        "style",
        "screenshot",
        "image",
        "icon looks",
        "professional",
        "well-formatted",
        "properly formatted",
    ]
)


# ---------------------------------------------------------------------------
# AssertionCompiler
# ---------------------------------------------------------------------------


class AssertionCompiler:
    """
    Compile AC step text into Playwright-executable assertion sequences.

    When ALL compiled assertions pass (evaluated at runtime against the live
    Playwright page), the LLM verifier is skipped entirely — eliminating one
    multimodal LLM round-trip per deterministic verification step.

    This class handles ONLY compilation (text → assertion specs). The actual
    Playwright execution is delegated to the verifier_node or a dedicated
    assertion runner that calls page.locator(...) etc.

    Args:
        enabled: When False, compile() always returns [] and
                 make_bypass_decision() always returns should_bypass=False.
                 Equivalent to pre-FEAT-060 behavior.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, ac_step: str) -> list[CompiledAssertion]:
        """
        Parse AC step text and return a list of compiled assertions.

        If the feature flag is disabled, always returns [].
        If the AC step contains semantic/visual keywords, returns [].
        If no patterns match, returns [].

        Args:
            ac_step: The AC step text to compile. May be empty.

        Returns:
            List of CompiledAssertion objects. Empty list = LLM must verify.
        """
        if not self.enabled:
            return []

        step = (ac_step or "").strip()
        if not step:
            return []

        step_lower = step.lower()

        # Guard: semantic/visual checks cannot be compiled programmatically
        for kw in _VISUAL_KEYWORDS:
            if kw in step_lower:
                logger.debug(
                    "assertion_compiler: visual keyword '%s' detected — skipping compilation",
                    kw,
                )
                return []

        assertions: list[CompiledAssertion] = []

        for pattern, assertion_type, _group in _PATTERNS:
            match = pattern.search(step)
            if not match:
                continue

            try:
                captured = match.group(1).strip() if match.lastindex else ""
            except IndexError:
                captured = ""

            # For count_check, convert to int
            if assertion_type == "count_check":
                try:
                    expected: str | int | None = int(captured)
                except (ValueError, TypeError):
                    expected = captured
            else:
                expected = captured or None

            assertion = CompiledAssertion(
                assertion_type=assertion_type,
                expected_value=expected,
                selector_hint="",
                description=f"{assertion_type}({expected!r}) from: {step[:60]}",
            )
            assertions.append(assertion)

            logger.debug(
                "assertion_compiler: compiled %s(expected=%r) from step=%.60s",
                assertion_type,
                expected,
                step,
            )

            # Only compile the first matching pattern per step to avoid
            # over-constraining the assertion sequence.
            # Exception: url_check and contains_text can coexist.
            if assertion_type not in ("url_check",) and len(assertions) >= 1:
                break

        return assertions

    def make_bypass_decision(
        self,
        results: list[AssertionResult],
        all_passed: bool,
    ) -> BypassDecision:
        """
        Decide whether to bypass the LLM verifier based on assertion results.

        Bypass rules:
        - If feature flag disabled → always should_bypass=False
        - If no assertions ran (empty results) → should_bypass=False
          (can't prove anything without running assertions)
        - If all assertions passed (all_passed=True) AND results is non-empty
          → should_bypass=True

        Args:
            results:    List of AssertionResult from executing compiled assertions.
            all_passed: True if all assertions returned passed=True.

        Returns:
            BypassDecision with should_bypass and evidence fields.
        """
        if not self.enabled:
            return BypassDecision(
                should_bypass=False,
                evidence="assertion_compiler: disabled (NATIVE_ASSERTION_ENABLED=false)",
                bypass_count=0,
            )

        if not results:
            return BypassDecision(
                should_bypass=False,
                evidence="assertion_compiler: no assertions compiled — LLM required",
                bypass_count=0,
            )

        passed_count = sum(1 for r in results if r.passed)
        evidence_parts = [r.evidence for r in results if r.evidence]
        combined_evidence = " | ".join(evidence_parts) if evidence_parts else "assertions ran"

        if all_passed and passed_count == len(results):
            logger.info(
                "assertion_compiler: bypass approved — %d/%d assertions passed: %s",
                passed_count,
                len(results),
                combined_evidence[:120],
            )
            return BypassDecision(
                should_bypass=True,
                evidence=f"Native assertions PASSED ({passed_count}/{len(results)}): {combined_evidence}",
                bypass_count=passed_count,
            )

        logger.debug(
            "assertion_compiler: bypass denied — %d/%d assertions passed",
            passed_count,
            len(results),
        )
        return BypassDecision(
            should_bypass=False,
            evidence=f"Native assertions FAILED ({passed_count}/{len(results)}): {combined_evidence}",
            bypass_count=passed_count,
        )


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------


def get_assertion_compiler() -> AssertionCompiler:
    """
    Return the singleton AssertionCompiler, respecting the feature flag.

    Import pattern::

        from backend.engine.assertion_compiler import get_assertion_compiler
        compiler = get_assertion_compiler()

    This is intentionally NOT a module-level singleton to keep tests simple
    (tests can construct AssertionCompiler directly with custom settings).
    """
    return AssertionCompiler(
        enabled=getattr(settings, "native_assertion_enabled", True),
    )
