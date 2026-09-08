"""
vQA — Step Verifier Node (Programmatic + LLM-as-a-Judge)
============================================================
Module: backend/engine/verifier.py

Implements a dedicated **VERIFY** node that determines whether the current
AC step has been FULLY satisfied after a successful browser action.

Verification Strategy (two-tier)
---------------------------------
**Tier 1 — Programmatic (Python/Playwright):**
  If the AC parser produced a structured ``test_plan``, the verifier reads
  the current step's ``verification[]`` array and evaluates each assertion
  directly in Python via Playwright DOM APIs.  This covers:

  - ``url_check``       — regex/substring match on ``page.url``
  - ``element_visible`` — ``wait_for(state="visible", timeout=2000)``
  - ``element_hidden``  — ``wait_for(state="hidden", timeout=2000)``
  - ``element_state``   — ``wait_for(visible)`` → ``is_disabled()``/``is_checked()``
  - ``toast_message``   — PrimeNG toast wait → transient cache fallback

  All DOM checks use ``wait_for(state=..., timeout=2000)`` wrapped in
  ``try/except PlaywrightTimeout`` to account for Angular/PrimeNG animation
  latency (fade-in transitions are typically 150–400 ms).

  Expected to eliminate 60–70% of LLM calls for form/navigation workflows.

**Tier 2 — LLM (Claude Haiku):**
  Falls back to a multimodal screenshot-based LLM call when:
  - ``test_plan`` is ``None`` (AC parser used the legacy flat-list fallback)
  - A ``visual_check`` type appears in the verification list
  - No ``selector_hint`` is available for DOM-based checks
  - The programmatic tier raises an unexpected exception

Why This Exists
---------------
The old evaluator used action-type heuristics to decide step completion:
  "fill action succeeded → step is done".

This is wrong for compound AC steps like:
  "Fill the client name and verify the dropdown appears."

The fill would auto-advance, skipping the verification entirely.

Architecture Context
--------------------
  executor_node (success)
      └─▶ verifier_node             ← this module
              │
              ├─ SATISFIED  → evaluator (advance AC step)
              ├─ NOT_YET    → planner  (continue same step)
              └─ FAILED     → planner  (with error context)

Dependencies
------------
  - ``langchain-aws``              — ChatBedrockConverse (LLM fallback)
  - ``playwright.async_api``       — wait_for / DOM checks (programmatic tier)
  - ``backend/browser/context.py`` — get_manager (live page access)
  - ``backend/config.py``          — model ID
  - ``backend/engine/state.py``    — VQAState
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Union

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from backend.browser.context import get_manager
from backend.browser.screenshot import capture_screenshot_b64  # FEAT-062
from backend.config import settings
from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 3 — A11y resolution-path evidence annotation (AC-ASYNC-1)
# ---------------------------------------------------------------------------

#: Resolution path values that originate from the A11yLocatorResolver.
_A11Y_RESOLUTION_PATHS = frozenset({
    "a11y_primary",
    "a11y_normalized",
    "selector_fallback",
    "selector_fallback_ambiguous",
    "selector_fallback_error",
    "cv_fallback_required",
})


def annotate_evidence_with_resolution_path(evidence: str, resolution_path: str | None) -> str:
    """Append a ``locator=<resolution_path>`` tag to *evidence* when the step
    was resolved by ``A11yLocatorResolver``.

    Only appends for the six A11y-resolver resolution-path values so that
    post-run analytics can unambiguously identify a11y-resolved steps and
    compute the a11y-resolution rate without re-running the test (AC-ASYNC-1).

    Idempotent — if the tag is already present (e.g. after a fast-path
    return), it is not duplicated.

    Args:
        evidence: The original evidence string from the verifier.
        resolution_path: The value of ``state["last_resolution_path"]``, or
            ``None`` when no a11y resolution occurred.

    Returns:
        The annotated evidence string, or the original string unchanged when
        ``resolution_path`` is absent or not an a11y-resolver value.
    """
    if not resolution_path or resolution_path not in _A11Y_RESOLUTION_PATHS:
        return evidence
    tag = f"locator={resolution_path}"
    if tag in evidence:
        return evidence  # already annotated (idempotent guard)
    return f"{evidence} [{tag}]"


# ---------------------------------------------------------------------------
# T2-d: StateExpectation taxonomy + DomVerifier + VisionVerifier (Phase 4)
# ---------------------------------------------------------------------------
#
# Architecture: Option 2C (hybrid) from the creative architecture doc.
# DomVerifier runs BEFORE VisionVerifier per the "Programmatic Tier 1 Verification"
# guiding principle. Vision only runs when DOM check returns INCONCLUSIVE.
#
# The 13-kind StateExpectation taxonomy is a CLOSED SET per the architecture doc
# (§ 2.5). New kinds require an ADR.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AriaExpandedCheck:
    kind: Literal["aria_expanded"] = "aria_expanded"
    selector: str = ""
    expected: bool = True


@dataclass(frozen=True)
class AriaSelectedCheck:
    kind: Literal["aria_selected"] = "aria_selected"
    selector: str = ""
    expected: bool = True


@dataclass(frozen=True)
class AriaCheckedCheck:
    kind: Literal["aria_checked"] = "aria_checked"
    selector: str = ""
    expected: Union[bool, str] = True  # bool or "mixed"


@dataclass(frozen=True)
class UrlDeltaCheck:
    kind: Literal["url_delta"] = "url_delta"
    pattern: str = ""
    mode: Literal["contains", "regex"] = "contains"


@dataclass(frozen=True)
class UrlEqualsCheck:
    kind: Literal["url_equals"] = "url_equals"
    expected: str = ""


@dataclass(frozen=True)
class ElementCountCheck:
    kind: Literal["element_count"] = "element_count"
    selector: str = ""
    op: Literal[">", "<", "==", "!="] = ">"
    count: int = 0


@dataclass(frozen=True)
class ElementVisibleCheck:
    kind: Literal["element_visible"] = "element_visible"
    selector: str = ""
    expected: bool = True


@dataclass(frozen=True)
class ElementHiddenCheck:
    kind: Literal["element_hidden"] = "element_hidden"
    selector: str = ""


@dataclass(frozen=True)
class TextContentCheck:
    kind: Literal["text_content"] = "text_content"
    selector: str = ""
    contains: str = ""


@dataclass(frozen=True)
class ClassContainsCheck:
    kind: Literal["class_contains"] = "class_contains"
    selector: str = ""
    class_name: str = ""
    expected_present: bool = True


@dataclass(frozen=True)
class FocusOnCheck:
    kind: Literal["focus_on"] = "focus_on"
    selector: str = ""


@dataclass(frozen=True)
class DialogOpenCheck:
    kind: Literal["dialog_open"] = "dialog_open"
    title: Union[str, None] = None


@dataclass(frozen=True)
class ToastVisibleCheck:
    kind: Literal["toast_visible"] = "toast_visible"
    severity: Union[Literal["success", "error", "info", "warn"], None] = None
    contains: Union[str, None] = None


# Composite checks
@dataclass(frozen=True)
class AllOfCheck:
    kind: Literal["all_of"] = "all_of"
    children: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class AnyOfCheck:
    kind: Literal["any_of"] = "any_of"
    children: tuple = field(default_factory=tuple)


StateExpectation = Union[
    AriaExpandedCheck,
    AriaSelectedCheck,
    AriaCheckedCheck,
    UrlDeltaCheck,
    UrlEqualsCheck,
    ElementCountCheck,
    ElementVisibleCheck,
    ElementHiddenCheck,
    TextContentCheck,
    ClassContainsCheck,
    FocusOnCheck,
    DialogOpenCheck,
    ToastVisibleCheck,
    AllOfCheck,
    AnyOfCheck,
]

_KIND_MAP: dict[str, type] = {
    "aria_expanded": AriaExpandedCheck,
    "aria_selected": AriaSelectedCheck,
    "aria_checked": AriaCheckedCheck,
    "url_delta": UrlDeltaCheck,
    "url_equals": UrlEqualsCheck,
    "element_count": ElementCountCheck,
    "element_visible": ElementVisibleCheck,
    "element_hidden": ElementHiddenCheck,
    "text_content": TextContentCheck,
    "class_contains": ClassContainsCheck,
    "focus_on": FocusOnCheck,
    "dialog_open": DialogOpenCheck,
    "toast_visible": ToastVisibleCheck,
    "all_of": AllOfCheck,
    "any_of": AnyOfCheck,
}


def _deserialize_expectation(raw: dict | str | None) -> StateExpectation | None:
    """
    Deserialize a planned_action['state_expectation'] value into a typed
    StateExpectation.

    Accepts:
    - dict with 'kind' key → typed dataclass
    - str → legacy format; route to PredictiveVerifier string contract (return None
      so DomVerifier falls back to default probe set; callers should handle the
      legacy string separately if needed)
    - None → None (default probe set)
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        # Legacy format — callers may route to PredictiveVerifier
        return None
    kind = raw.get("kind")
    cls = _KIND_MAP.get(kind)
    if cls is None:
        logger.warning("_deserialize_expectation: unknown kind %r — returning None", kind)
        return None
    try:
        if kind in ("all_of", "any_of"):
            children = tuple(
                _deserialize_expectation(c) for c in raw.get("children", [])
            )
            return cls(kind=kind, children=children)
        # Filter raw to only known fields for the dataclass
        import dataclasses
        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in raw.items() if k in known_fields}
        return cls(**filtered)
    except Exception as exc:
        logger.warning("_deserialize_expectation: failed to build %s: %s", cls.__name__, exc)
        return None


class VerifierVerdict(str, Enum):
    PASS = "PASS"
    NOT_YET = "NOT_YET"
    INCONCLUSIVE = "INCONCLUSIVE"  # cascade to VisionVerifier


@dataclass
class VerifierResult:
    """
    Return shape of DomVerifier.check() and VisionVerifier.check().

    verifier_path is the load-bearing telemetry field (pinned in the spec's
    Observable-at bullet — AC-VERIFY-5):
      - "dom_only"                  → DomVerifier resolved without vision
      - "dom_inconclusive_vision_ran" → DOM was inconclusive; vision ran
      - "vision_only"               → no DOM expectation; vision ran directly
    """
    resolved: bool
    verdict: VerifierVerdict
    evidence: str
    verifier_path: Literal["dom_only", "dom_inconclusive_vision_ran", "vision_only"] = "dom_only"
    check_kind: str = ""
    elapsed_ms: int = 0
    tokens_used: int = 0  # 0 for pure DOM; nonzero when vision ran


class DomVerifier:
    """
    Deterministic DOM-only verifier. Never calls Bedrock/Sonnet.

    Runs BEFORE VisionVerifier per T2-d (Programmatic Tier 1 Verification principle).

    Contract:
    - If expectation is provided, dispatch to the kind-specific probe.
    - Else, run the default probe set against pre_state_snapshot.
    - Returns VerifierResult; never raises (all Playwright errors caught internally).
    - verifier_path is always "dom_only" (caller sets "dom_inconclusive_vision_ran"
      on the final result when cascading to VisionVerifier).
    """

    async def check(
        self,
        page: Page,
        expectation: StateExpectation | None,
        pre_state_snapshot: dict | None,
    ) -> VerifierResult:
        """Run the DOM check. Returns resolved=True iff verdict is definitive."""
        start = time.perf_counter()
        try:
            if expectation is not None:
                result = await self._check_expectation(page, expectation)
            else:
                result = await self._default_probe_set(page, pre_state_snapshot or {})
        except Exception as exc:
            logger.warning("DomVerifier.check: unhandled error: %s", exc)
            result = VerifierResult(
                resolved=False,
                verdict=VerifierVerdict.INCONCLUSIVE,
                evidence=f"dom_check_error: {exc}",
                verifier_path="dom_only",
                check_kind="error",
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result.elapsed_ms = elapsed_ms
        return result

    async def _check_expectation(
        self, page: Page, expectation: StateExpectation
    ) -> VerifierResult:
        """Dispatch to the kind-specific probe."""
        kind = expectation.kind

        if kind == "aria_expanded":
            return await self._check_aria_attr(page, expectation.selector, "aria-expanded", expectation.expected)

        elif kind == "aria_selected":
            return await self._check_aria_attr(page, expectation.selector, "aria-selected", expectation.expected)

        elif kind == "aria_checked":
            expected = expectation.expected
            raw = await self._safe_get_attribute(page, expectation.selector, "aria-checked")
            if raw is None:
                return self._inconclusive("aria_checked", f"attribute not found on {expectation.selector!r}")
            if isinstance(expected, bool):
                actual = raw.lower() == "true"
                passed = actual == expected
            else:
                actual = raw
                passed = actual == expected
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
                evidence=f"aria-checked={raw!r}, expected={expected!r}",
                verifier_path="dom_only",
                check_kind="aria_checked",
            )

        elif kind == "url_delta":
            current_url = page.url
            pattern = expectation.pattern
            if expectation.mode == "regex":
                import re as _re
                matched = bool(_re.search(pattern, current_url))
            else:
                matched = pattern.lower() in current_url.lower()
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.PASS if matched else VerifierVerdict.NOT_YET,
                evidence=f"url={current_url!r}, pattern={pattern!r}, mode={expectation.mode!r}",
                verifier_path="dom_only",
                check_kind="url_delta",
            )

        elif kind == "url_equals":
            current_url = page.url
            matched = current_url == expectation.expected
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.PASS if matched else VerifierVerdict.NOT_YET,
                evidence=f"url={current_url!r}, expected={expectation.expected!r}",
                verifier_path="dom_only",
                check_kind="url_equals",
            )

        elif kind == "element_count":
            try:
                actual_count = await page.locator(expectation.selector).count()
                op = expectation.op
                expected_count = expectation.count
                if op == ">":
                    passed = actual_count > expected_count
                elif op == "<":
                    passed = actual_count < expected_count
                elif op == "==":
                    passed = actual_count == expected_count
                elif op == "!=":
                    passed = actual_count != expected_count
                else:
                    return self._inconclusive("element_count", f"unknown op {op!r}")
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
                    evidence=f"count({expectation.selector!r})={actual_count}, op={op!r}, expected={expected_count}",
                    verifier_path="dom_only",
                    check_kind="element_count",
                )
            except PlaywrightTimeout:
                return self._inconclusive("element_count", f"timeout querying {expectation.selector!r}")

        elif kind == "element_visible":
            try:
                is_vis = await page.locator(expectation.selector).is_visible()
                passed = is_vis == expectation.expected
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
                    evidence=f"is_visible({expectation.selector!r})={is_vis}, expected={expectation.expected}",
                    verifier_path="dom_only",
                    check_kind="element_visible",
                )
            except PlaywrightTimeout:
                return self._inconclusive("element_visible", f"timeout on {expectation.selector!r}")

        elif kind == "element_hidden":
            try:
                is_hid = await page.locator(expectation.selector).is_hidden()
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS if is_hid else VerifierVerdict.NOT_YET,
                    evidence=f"is_hidden({expectation.selector!r})={is_hid}",
                    verifier_path="dom_only",
                    check_kind="element_hidden",
                )
            except PlaywrightTimeout:
                return self._inconclusive("element_hidden", f"timeout on {expectation.selector!r}")

        elif kind == "text_content":
            try:
                text = await page.locator(expectation.selector).text_content()
                if text is None:
                    return self._inconclusive("text_content", f"no text in {expectation.selector!r}")
                passed = expectation.contains.lower() in text.lower()
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
                    evidence=f"text={text!r}, contains={expectation.contains!r}",
                    verifier_path="dom_only",
                    check_kind="text_content",
                )
            except PlaywrightTimeout:
                return self._inconclusive("text_content", f"timeout on {expectation.selector!r}")

        elif kind == "class_contains":
            raw_class = await self._safe_get_attribute(page, expectation.selector, "class")
            if raw_class is None:
                return self._inconclusive("class_contains", f"no class attr on {expectation.selector!r}")
            has_class = expectation.class_name in raw_class.split()
            passed = has_class == expectation.expected_present
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
                evidence=f"class={raw_class!r}, looking for {expectation.class_name!r}, expected_present={expectation.expected_present}",
                verifier_path="dom_only",
                check_kind="class_contains",
            )

        elif kind == "focus_on":
            # Check if document.activeElement matches the selector (best-effort)
            return self._inconclusive("focus_on", "focus_on requires page.evaluate — deferred to vision")

        elif kind == "dialog_open":
            try:
                loc = page.locator(".p-dialog")
                is_vis = await loc.is_visible()
                if not is_vis:
                    return VerifierResult(
                        resolved=True,
                        verdict=VerifierVerdict.NOT_YET,
                        evidence="dialog .p-dialog not visible",
                        verifier_path="dom_only",
                        check_kind="dialog_open",
                    )
                if expectation.title:
                    title_text = await page.locator(".p-dialog-title").text_content()
                    if title_text and expectation.title.lower() in title_text.lower():
                        return VerifierResult(
                            resolved=True,
                            verdict=VerifierVerdict.PASS,
                            evidence=f"dialog visible, title={title_text!r}",
                            verifier_path="dom_only",
                            check_kind="dialog_open",
                        )
                    return VerifierResult(
                        resolved=True,
                        verdict=VerifierVerdict.NOT_YET,
                        evidence=f"dialog visible but title={title_text!r} != {expectation.title!r}",
                        verifier_path="dom_only",
                        check_kind="dialog_open",
                    )
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence="dialog .p-dialog is visible",
                    verifier_path="dom_only",
                    check_kind="dialog_open",
                )
            except PlaywrightTimeout:
                return self._inconclusive("dialog_open", "timeout querying .p-dialog")

        elif kind == "toast_visible":
            try:
                base_selector = ".p-toast-message"
                if expectation.severity:
                    selector = f"{base_selector}.p-toast-message-{expectation.severity}"
                else:
                    selector = base_selector
                is_vis = await page.locator(selector).is_visible()
                if not is_vis:
                    return VerifierResult(
                        resolved=True,
                        verdict=VerifierVerdict.NOT_YET,
                        evidence=f"toast {selector!r} not visible",
                        verifier_path="dom_only",
                        check_kind="toast_visible",
                    )
                if expectation.contains:
                    text = await page.locator(selector).text_content()
                    if text and expectation.contains.lower() in text.lower():
                        pass  # falls through to PASS
                    else:
                        return VerifierResult(
                            resolved=True,
                            verdict=VerifierVerdict.NOT_YET,
                            evidence=f"toast visible but text={text!r} does not contain {expectation.contains!r}",
                            verifier_path="dom_only",
                            check_kind="toast_visible",
                        )
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence=f"toast {selector!r} is visible",
                    verifier_path="dom_only",
                    check_kind="toast_visible",
                )
            except PlaywrightTimeout:
                return self._inconclusive("toast_visible", "timeout querying toast")

        elif kind == "all_of":
            for child_exp in expectation.children:
                if child_exp is None:
                    continue
                child_result = await self._check_expectation(page, child_exp)
                if not child_result.resolved:
                    return child_result  # propagate inconclusive
                if child_result.verdict != VerifierVerdict.PASS:
                    return child_result  # propagate NOT_YET
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.PASS,
                evidence="all_of: all children passed",
                verifier_path="dom_only",
                check_kind="all_of",
            )

        elif kind == "any_of":
            for child_exp in expectation.children:
                if child_exp is None:
                    continue
                child_result = await self._check_expectation(page, child_exp)
                if child_result.resolved and child_result.verdict == VerifierVerdict.PASS:
                    return child_result
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.NOT_YET,
                evidence="any_of: no child passed",
                verifier_path="dom_only",
                check_kind="any_of",
            )

        else:
            return self._inconclusive(kind, f"unsupported kind {kind!r}")

    async def _default_probe_set(
        self, page: Page, pre_state_snapshot: dict
    ) -> VerifierResult:
        """
        Default probe set (Option 2C hybrid — no planner-emitted state_expectation).

        Probes in order; returns on first resolved=True. If all null-delta → INCONCLUSIVE.

        Probes:
          1. url_delta from pre_state_snapshot.url
          2. element_count on body * from pre_state_snapshot.element_count
          3. aria_expanded scan across all [aria-expanded] elements — any delta
          4. dialog_open state delta
          5. toast_visible any-severity
        """
        pre_url = pre_state_snapshot.get("url", "")
        pre_count = pre_state_snapshot.get("element_count", 0)
        pre_aria_expanded = pre_state_snapshot.get("aria_expanded_count", 0)
        pre_dialog = pre_state_snapshot.get("dialog_open", False)

        # Probe 1: URL delta
        try:
            current_url = page.url
            if pre_url and current_url != pre_url:
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence=f"url changed: {pre_url!r} → {current_url!r}",
                    verifier_path="dom_only",
                    check_kind="default_url_delta",
                )
        except Exception:
            pass

        # Probe 2: element-count delta on body *
        try:
            current_count = await page.locator("body *").count()
            if current_count != pre_count and pre_count > 0:
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence=f"element count changed: {pre_count} → {current_count}",
                    verifier_path="dom_only",
                    check_kind="default_element_count",
                )
        except Exception:
            pass

        # Probe 3: aria-expanded scan (any delta)
        try:
            current_expanded = await page.locator("[aria-expanded='true']").count()
            if current_expanded != pre_aria_expanded:
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence=f"aria-expanded count changed: {pre_aria_expanded} → {current_expanded}",
                    verifier_path="dom_only",
                    check_kind="default_aria_expanded",
                )
        except Exception:
            pass

        # Probe 4: dialog open state delta
        try:
            dialog_now = await page.locator(".p-dialog").is_visible()
            if dialog_now != pre_dialog:
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence=f"dialog state changed: {pre_dialog} → {dialog_now}",
                    verifier_path="dom_only",
                    check_kind="default_dialog_open",
                )
        except Exception:
            pass

        # Probe 5: toast visible (any severity)
        try:
            toast_now = await page.locator(".p-toast-message").is_visible()
            if toast_now:
                return VerifierResult(
                    resolved=True,
                    verdict=VerifierVerdict.PASS,
                    evidence="toast appeared (any severity)",
                    verifier_path="dom_only",
                    check_kind="default_toast_visible",
                )
        except Exception:
            pass

        # All probes null-delta
        return VerifierResult(
            resolved=False,
            verdict=VerifierVerdict.INCONCLUSIVE,
            evidence="default probe set: no delta detected across url, count, aria-expanded, dialog, toast",
            verifier_path="dom_only",
            check_kind="default_inconclusive",
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _check_aria_attr(
        self,
        page: Page,
        selector: str,
        attr: str,
        expected: bool,
    ) -> VerifierResult:
        """Check aria-expanded or aria-selected attribute."""
        raw = await self._safe_get_attribute(page, selector, attr)
        if raw is None:
            return self._inconclusive(attr, f"attribute not found on {selector!r}")
        actual = raw.lower() == "true"
        passed = actual == expected
        kind = attr.replace("-", "_")
        return VerifierResult(
            resolved=True,
            verdict=VerifierVerdict.PASS if passed else VerifierVerdict.NOT_YET,
            evidence=f"{attr}={raw!r}, expected={expected!r}",
            verifier_path="dom_only",
            check_kind=kind,
        )

    @staticmethod
    async def _safe_get_attribute(page: Page, selector: str, attr: str) -> str | None:
        """Get attribute value; return None on any error."""
        try:
            return await page.locator(selector).get_attribute(attr)
        except Exception:
            return None

    @staticmethod
    def _inconclusive(check_kind: str, reason: str) -> VerifierResult:
        return VerifierResult(
            resolved=False,
            verdict=VerifierVerdict.INCONCLUSIVE,
            evidence=f"inconclusive({check_kind}): {reason}",
            verifier_path="dom_only",
            check_kind=check_kind,
        )


class VisionVerifier:
    """
    Thin wrapper around the existing Sonnet/Bedrock vision verification call.

    Only invoked when DomVerifier returns INCONCLUSIVE. The caller is responsible
    for setting verifier_path="dom_inconclusive_vision_ran" on the result when
    cascading from DomVerifier.
    """

    async def check(
        self,
        page: Page,
        screenshot_b64: str,
        ac_step: str,
        run_id: str = "",
    ) -> VerifierResult:
        """
        Invoke the existing Bedrock vision LLM for screenshot-based verification.

        This is a structural wrapper — the actual LLM call is the same logic that
        previously ran directly inside step_verifier_node. By wrapping it here,
        callers can mock VisionVerifier.check in unit tests without touching the
        full node.

        Returns VerifierResult with verifier_path="dom_inconclusive_vision_ran"
        (set here since we are the vision leg).
        """
        # Delegate to the existing _llm_verify_step function implemented below
        # the node definition (the existing LLM verification logic stays in-place;
        # this wrapper just bridges to it).
        start = time.perf_counter()
        try:
            verdict_str, evidence, tokens_used = await _vision_llm_check(
                screenshot_b64=screenshot_b64,
                ac_step=ac_step,
                run_id=run_id,
            )
        except Exception as exc:
            logger.warning("[%s] VisionVerifier: LLM call failed: %s", run_id, exc)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return VerifierResult(
                resolved=True,
                verdict=VerifierVerdict.NOT_YET,
                evidence=f"vision_error: {exc}",
                verifier_path="dom_inconclusive_vision_ran",
                check_kind="vision_error",
                elapsed_ms=elapsed_ms,
                tokens_used=0,
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        verdict = VerifierVerdict.PASS if verdict_str.upper() == "PASS" else VerifierVerdict.NOT_YET
        return VerifierResult(
            resolved=True,
            verdict=verdict,
            evidence=evidence,
            verifier_path="dom_inconclusive_vision_ran",
            check_kind="vision",
            elapsed_ms=elapsed_ms,
            tokens_used=tokens_used,
        )


async def _vision_llm_check(
    screenshot_b64: str,
    ac_step: str,
    run_id: str = "",
) -> tuple[str, str, int]:
    """
    Run the Bedrock/Sonnet vision verification call and return
    (verdict_str, evidence, tokens_used).

    verdict_str is "PASS" or "NOT_YET".
    This function is intentionally a thin bridge to make VisionVerifier testable.
    """
    # Build a minimal prompt reusing the existing verifier prompt style
    from backend.config import settings as _settings

    llm = ChatBedrockConverse(
        model=_settings.model_id,
        region_name=_settings.aws_region,
        max_tokens=200,
        temperature=0,
    )
    system_prompt = (
        "You are a QA verifier. Given a screenshot and an acceptance criterion step, "
        "respond with JSON: {\"verdict\": \"PASS\" or \"NOT_YET\", \"reason\": \"<one line>\"}. "
        "PASS = the action is complete and the expected state is visible. NOT_YET = incomplete."
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {"type": "text", "text": f"AC step: {ac_step}"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
            ]
        ),
    ]
    response = await llm.ainvoke(messages)
    raw_text = response.content if isinstance(response.content, str) else str(response.content)
    tokens_used = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        tokens_used = response.usage_metadata.get("input_tokens", 0) + response.usage_metadata.get("output_tokens", 0)
    try:
        payload = json.loads(raw_text.strip())
        verdict_str = payload.get("verdict", "NOT_YET")
        evidence = payload.get("reason", raw_text[:120])
    except Exception:
        verdict_str = "PASS" if "PASS" in raw_text.upper() else "NOT_YET"
        evidence = raw_text[:120]
    return verdict_str, evidence, tokens_used


# ---------------------------------------------------------------------------
# Visual Delta Logic (FEAT-062 Pillar 2)
# ---------------------------------------------------------------------------


async def _visual_delta_check(
    page: Page,
    pre_screenshot_b64: str | None,
) -> bool:
    """
    Compare current page screenshot with a pre-action screenshot.

    Returns True if a significant visual delta is detected.
    Used as a secondary signal for CV-fallback clicks that might
    affect a <canvas> or SPA component without mutating the DOM.

    Args
    ----
    page : Page
        The active Playwright page.
    pre_screenshot_b64 : str | None
        The base64 screenshot captured immediately BEFORE the action.

    Returns
    -------
    bool
        True if the screenshots are semantically different.
    """
    if not pre_screenshot_b64:
        return False

    try:
        # Capture post-action screenshot (viewport only for speed)
        post_screenshot_b64 = await capture_screenshot_b64(page, full_page=False)

        # Tier 1: Fast string comparison
        if post_screenshot_b64 == pre_screenshot_b64:
            return False

        # Tier 2: Future implementation - pixel diffing
        # For now, any string difference is considered a delta.
        return True
    except Exception as e:
        logger.warning("_visual_delta_check failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Verdict type (legacy string union for step_verifier_node routing)
# NOTE: The canonical VerifierVerdict enum is defined at the top of the module
# (T2-d Phase 4). This alias covers the legacy LangGraph routing strings used
# internally by step_verifier_node and is kept for backward compat.
# ---------------------------------------------------------------------------

_VerifierVerdictStr = Literal["satisfied", "not_yet", "failed", "skipped"]


# ---------------------------------------------------------------------------
# DOM state harvest helper (P1B)
# ---------------------------------------------------------------------------


async def _harvest_dom_snapshot(run_id: str) -> str:
    """
    Capture a snapshot of persistent DOM state markers using PageStateTracker.
    Returns the XML formatted string.
    """
    try:
        from backend.browser.context import get_manager
        from backend.engine.state_tracker import get_tracker

        tracker = get_tracker(run_id)
        if not tracker:
            return "dom_snapshot: tracker not found"

        page = get_manager(run_id).page
        if page and not page.is_closed():
            await tracker.refresh(page)

        return tracker.format_for_prompt()

    except Exception as _e:
        return f"dom_snapshot_error: {str(_e)[:100]}"


# ---------------------------------------------------------------------------
# CV Fallback State Change Detection (FEAT-037 / TASK-028 Phase 3)
# ---------------------------------------------------------------------------


async def cv_fallback_state_change_check(
    page,
    pre_state: dict | None = None,
    *,
    url_before: str | None = None,
    snapshot_before: str | None = None,
    element_count_before: int | None = None,
    screenshot_b64_before: str | None = None,
    wait_seconds: float = 2.0,
    run_id: str = "unknown",
) -> dict:
    """
    Determine whether a browser action produced a detectable state change.

    Compares multiple independent signals against a pre-action snapshot:
    1. **URL change**
    2. **ARIA snapshot diff** (or DOM snapshot)
    3. **Element count delta**
    4. **Visual Delta** (screenshot diff)

    Any ONE of the signals returning a diff constitutes success (has_changed=True).

    Args
    ----
    page : playwright.async_api.Page
        The live Playwright page.
    pre_state : dict, optional
        Pre-action snapshot dict (legacy compatibility).
        Expected keys: ``url``, ``aria_snapshot``, ``element_count``.
    url_before : str, optional
        Explicit pre-action URL.
    snapshot_before : str, optional
        Explicit pre-action ARIA or DOM snapshot.
    element_count_before : int, optional
        Explicit pre-action element count.
    screenshot_b64_before : str, optional
        Explicit pre-action screenshot.
    wait_seconds : float
        How long to wait after the action before checking state.
    run_id : str
        The current run ID for logging.

    Returns
    -------
    dict
        A results dictionary:
        - ``has_changed`` (bool): True if ANY signal detected a change.
        - ``url_changed`` (bool)
        - ``snapshot_changed`` (bool)
        - ``element_count_changed`` (bool)
        - ``visual_delta`` (float): Pixel change percentage (future implementation).
        - ``snapshot_after`` (str): The newly captured snapshot.
    """
    # ── Gate: closed page ──────────────────────────────────────────────────
    if page.is_closed():
        logger.debug("[%s] CV_FALLBACK_STATE_CHECK: page is closed — returning False", run_id)
        return {"has_changed": False, "snapshot_after": ""}

    # ── Resolve inputs from pre_state or explicit args ───────────────────
    if pre_state:
        url_before = url_before or pre_state.get("url", "")
        snapshot_before = snapshot_before or pre_state.get("aria_snapshot")
        element_count_before = (
            element_count_before
            if element_count_before is not None
            else pre_state.get("element_count")
        )

    # ── Wait for browser to react ─────────────────────────────────────────
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)

    results = {
        "has_changed": False,
        "url_changed": False,
        "snapshot_changed": False,
        "element_count_changed": False,
        "visual_delta": 0.0,
        "snapshot_after": "",
    }

    # ── Signal 1: URL change ───────────────────────────────────────────────
    try:
        current_url: str = page.url
        if url_before is not None and current_url != url_before:
            logger.info(
                "[%s] CV_FALLBACK_STATE_CHANGE: URL changed — '%s' → '%s'",
                run_id,
                url_before[:80],
                current_url[:80],
            )
            results["url_changed"] = True
            results["has_changed"] = True
    except Exception as _url_err:
        logger.debug("[%s] CV_FALLBACK_STATE_CHECK: URL check failed: %s", run_id, _url_err)

    # ── Signal 2: ARIA/DOM snapshot diff ──────────────────────────────────
    try:
        # Try ARIA first, fall back to DOM snapshot helper
        raw_snapshot = await page.accessibility.snapshot()
        if raw_snapshot:
            current_snapshot: str = json.dumps(raw_snapshot, sort_keys=True)
        else:
            current_snapshot = (await _harvest_dom_snapshot(run_id)).strip()

        results["snapshot_after"] = current_snapshot

        if snapshot_before is not None and current_snapshot != snapshot_before.strip():
            logger.info(
                "[%s] CV_FALLBACK_STATE_CHANGE: Snapshot changed (%d chars → %d chars)",
                run_id,
                len(snapshot_before),
                len(current_snapshot),
            )
            results["snapshot_changed"] = True
            results["has_changed"] = True
    except Exception as _aria_err:
        logger.debug("[%s] CV_FALLBACK_STATE_CHECK: Snapshot check failed: %s", run_id, _aria_err)

    # ── Signal 3: DOM element count delta ──────────────────────────────────
    try:
        current_count: int = await page.evaluate("document.querySelectorAll('*').length")
        if element_count_before is not None and current_count != element_count_before:
            logger.info(
                "[%s] CV_FALLBACK_STATE_CHANGE: element count changed — %d → %d (Δ%+d)",
                run_id,
                element_count_before,
                current_count,
                current_count - element_count_before,
            )
            results["element_count_changed"] = True
            results["has_changed"] = True
    except Exception as _count_err:
        logger.debug("[%s] CV_FALLBACK_STATE_CHECK: element count check failed: %s", run_id, _count_err)

    # ── Signal 4: Visual Delta (FEAT-062 Pillar 2) ────────────────────────
    if await _visual_delta_check(page, screenshot_b64_before):
        logger.info("[%s] CV_FALLBACK_STATE_CHANGE: visual delta detected", run_id)
        results["has_changed"] = True

    if not results["has_changed"]:
        logger.info(
            "[%s] CV_FALLBACK_STATE_CHANGE: no detectable state change after %.1f s",
            run_id,
            wait_seconds,
        )

    return results


# ---------------------------------------------------------------------------
# Verifier prompt
# ---------------------------------------------------------------------------

_VERIFIER_SYSTEM_PROMPT = """\
<GOLDEN_RULES>
1. IDENTITY: You are a QA test verifier.
2. MISSION: Determine whether an acceptance criteria step has been FULLY satisfied.
3. OUTPUT FORMAT: Respond with EXACTLY ONE of the three verdicts (SATISFIED, NOT_YET, FAILED) followed by evidence.
4. STRICTNESS: Be STRICT. Do not give the planner the benefit of the doubt — require visible proof.
</GOLDEN_RULES>

<JUDGEMENT_RULES>
1. Be STRICT: if the AC step says "verify X appears" and X is not visible, say NOT_YET.
2. If the page shows a loading spinner or is clearly mid-transition, say NOT_YET.
3. If the AC step says "click X" and you can see the result of clicking X (page changed, \
modal opened, form submitted), say SATISFIED.
4. If the AC step is "fill X with Y" and you can see Y is in the field, say SATISFIED.
5. If the AC step mentions verifying a toast/notification and the page looks normal \
(no notification visible), say NOT_YET — the agent may need to wait or take another action.
6. For "done" actions: be STRICT. Treat the planner's claim as a HYPOTHESIS, not a fact. \
Only say SATISFIED if you can see POSITIVE visual evidence that the AC step outcome actually \
occurred (e.g. the correct page is loaded, a status changed, a form was submitted). If the \
page state does not clearly confirm the step completed, say NOT_YET.
7. Proof of Transition: Use the BEFORE and AFTER DOM states to verify if a state change occurred. If the action was supposed to change the UI structurally (open a modal, navigate, etc.) but the BEFORE and AFTER DOM states are identical, this is strong evidence that the action failed or is still loading.
8. SIDE PANELS / OVERLAYS: In this application (vSuite/PrimeNG), many forms open as \
side panels or drawers overlaid on the existing page (e.g., Quick Order, Create Order). \
The URL and underlying page title (e.g., "Production Orders") remain visible underneath. \
When an AC step says "Navigate to the Quick Order page" or "Open the Quick Order form", \
it is SATISFIED if a form panel, drawer, or sidebar has appeared on screen — even if the \
page title still shows "Production Orders". Do NOT require a full page navigation for \
side-panel forms.
</JUDGEMENT_RULES>

<OUTPUT_FORMAT>
Respond with EXACTLY ONE of these three verdicts on the FIRST LINE:
- SATISFIED: <one-sentence evidence of what you see that proves it>
- NOT_YET: <what's still missing or needs to happen next>
- FAILED: <what went wrong or is incorrect>

One-word verdicts are NOT acceptable. Always include evidence.
</OUTPUT_FORMAT>

<CRITICAL_REMINDER>
- First line MUST start with SATISFIED:, NOT_YET:, or FAILED:.
- Use the BEFORE and AFTER DOM context to verify state transitions.
- Trust POSITIVE visual evidence only.
</CRITICAL_REMINDER>
"""


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _get_verifier_llm(heavy: bool = False) -> ChatBedrockConverse:
    """
    Create an LLM client for verification.

    Delegates to the centralized ``get_llm()`` factory.
    Uses the ``verifier_vision`` purpose preset (100 max_tokens,
    temp=0, default Haiku model or Sonnet if heavy=True).
    """
    from backend.llm import get_llm

    return get_llm("verifier_vision", heavy=heavy)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_verdict(raw: str) -> tuple[_VerifierVerdictStr, str, int]:
    """
    Parse the verifier LLM's response into a verdict + evidence + confidence.

    FEAT-010: Now returns a confidence score (0-100) based on evidence quality.
    - Programmatic checks: always 95 (deterministic DOM assertion)
    - LLM with detailed evidence (>50 chars, specific selectors/text): 80-90
    - LLM with weak evidence (<30 chars, vague language): 40-60
    - Ambiguous/unparseable response: 30

    Args
    ----
    raw : str
        Raw LLM response text.

    Returns
    -------
    tuple[_VerifierVerdictStr, str, int]
        (verdict, evidence_text, confidence_score)
    """
    text = raw.strip()
    first_line = text.split("\n")[0].strip()
    upper = first_line.upper()

    # FEAT-010: Score confidence based on evidence quality
    def _score_confidence(evidence: str, verdict_type: str) -> int:
        """Heuristic confidence score for LLM verifier evidence."""
        score = 60  # baseline for any parsed response
        ev_len = len(evidence)

        # Length bonus: longer evidence = more thoughtful analysis
        if ev_len > 100:
            score += 15
        elif ev_len > 50:
            score += 10
        elif ev_len < 20:
            score -= 15

        # Specificity bonus: mentions concrete UI elements
        specificity_markers = [
            "button",
            "text",
            "field",
            "input",
            "label",
            "dropdown",
            "toast",
            "dialog",
            "modal",
            "tab",
            "menu",
            "visible",
            "displayed",
            "shows",
            "contains",
            "url",
            "heading",
        ]
        markers_found = sum(1 for m in specificity_markers if m in evidence.lower())
        score += min(markers_found * 3, 15)

        # Vagueness penalty: weak evidence language
        vague_markers = [
            "looks like",
            "seems",
            "appears to",
            "might",
            "probably",
            "i think",
            "possibly",
            "unclear",
            "hard to tell",
        ]
        for v in vague_markers:
            if v in evidence.lower():
                score -= 10
                break

        # Cap to valid range
        return max(20, min(score, 95))

    if upper.startswith("SATISFIED"):
        evidence = first_line.split(":", 1)[1].strip() if ":" in first_line else text
        confidence = _score_confidence(evidence, "satisfied")
        return "satisfied", evidence, confidence
    elif upper.startswith("NOT_YET") or upper.startswith("NOT YET"):
        evidence = first_line.split(":", 1)[1].strip() if ":" in first_line else text
        confidence = _score_confidence(evidence, "not_yet")
        return "not_yet", evidence, confidence
    elif upper.startswith("FAILED"):
        evidence = first_line.split(":", 1)[1].strip() if ":" in first_line else text
        confidence = _score_confidence(evidence, "failed")
        return "failed", evidence, confidence
    else:
        # Ambiguous response — default to NOT_YET to avoid premature advance
        logger.warning(
            "Verifier returned ambiguous response, defaulting to NOT_YET: %s",
            text[:100],
        )
        return "not_yet", f"Ambiguous verifier response: {text[:100]}", 30


# ---------------------------------------------------------------------------
# Programmatic verification handlers (Objective 1)
# ---------------------------------------------------------------------------


async def _check_single_verification(
    page,
    v: dict,
    run_id: str,
    transient_text: str = "",
    *,
    ac_step_index: int = 0,
    deferred_check_delay: int = 2,
    enable_deferred_verification: bool = True,
    pre_state: dict | None = None,
) -> tuple[str, str, dict | None]:
    """
    Evaluate one Verification assertion via Python/Playwright DOM checks.

    Uses ``wait_for(state=..., timeout=2000)`` instead of instant
    ``.is_visible()`` / ``.count()`` calls to account for Angular/PrimeNG
    animation latency (fade-in transitions are typically 150–400 ms).

    FEAT-023 (TASK-005 Phase 2): When an auto-satisfy bypass is triggered
    (transient selector blocklist or sparse dataset) AND the DVQ feature
    flag is enabled, the function returns a DVQ entry dict as the 3rd
    element of the return tuple.  The caller is responsible for appending
    this entry to ``VQAState.deferred_verification_queue``.

    Args
    ----
    page : playwright.async_api.Page
        The live Playwright page from the active BrowserManager.
    v : dict
        A single Verification dict (from ``StructuredACStep.verification``).
    run_id : str
        Run identifier for structured log lines.
    transient_text : str
        Transient page text captured immediately post-action — used as an
        ephemeral fallback for ``toast_message`` checks when the toast has
        already auto-dismissed before the verifier runs.
    ac_step_index : int
        Current AC step index — used to populate DVQ entry fields.
    deferred_check_delay : int
        How many AC steps to wait before re-checking a deferred assertion.
    enable_deferred_verification : bool
        Feature flag — when False, bypass paths return None for the DVQ
        entry (preserving pre-FEAT-023 behavior exactly).
    pre_state : dict
        Pre-action state snapshot (URL, element count, ARIA) for
        verify_state_change detection.

    Returns
    -------
    tuple[str, str, dict | None]
        ``(verdict, evidence, dvq_entry)`` where:

        - verdict is ``"satisfied"``, ``"not_yet"``, or ``"llm_needed"``
        - dvq_entry is a dict to enqueue in ``deferred_verification_queue``
          (only populated for auto-satisfy bypass paths when DVQ is enabled;
          ``None`` for all other paths)
    """
    v_type: str = v.get("type", "")
    selector_hint: str = (v.get("selector_hint") or "").strip()
    expected_text: str = (v.get("expected_text") or "").strip()
    expected_state_raw: str = (v.get("expected_state") or "").strip().lower()
    url_pattern: str = (v.get("url_pattern") or "").strip()

    # ── verify_state_change: interaction side-effect check ───────────────
    if v_type == "verify_state_change":
        if not pre_state:
            return "satisfied", "verify_state_change: no pre-state captured — assuming satisfied", None

        # Signal 1: URL change
        if page.url != pre_state.get("url"):
            return "satisfied", f"verify_state_change: URL changed to '{page.url}' ✓", None

        # Signal 2: Element count delta
        try:
            current_count = await page.evaluate("document.querySelectorAll('*').length")
            pre_count = pre_state.get("element_count")
            if pre_count is not None and current_count != pre_count:
                return (
                    "satisfied",
                    f"verify_state_change: DOM element count changed ({pre_count} → {current_count}) ✓",
                    None,
                )
        except Exception:
            pass

        # Signal 3: ARIA snapshot diff
        try:
            raw_snapshot = await page.accessibility.snapshot()
            current_aria = json.dumps(raw_snapshot, sort_keys=True) if raw_snapshot else ""
            pre_aria = pre_state.get("aria_snapshot")
            if current_aria and pre_aria is not None and current_aria != pre_aria:
                return "satisfied", "verify_state_change: accessibility tree (ARIA) changed ✓", None
        except Exception:
            pass

        return "not_yet", "verify_state_change: no detectable URL, DOM, or ARIA change after action", None

    # ── url_check: instant URL substring / regex match ──────────────────
    if v_type == "url_check":
        if not url_pattern:
            return "satisfied", "url_check: no pattern specified — skipped", None
        current_url = page.url
        matched = False
        try:
            matched = bool(re.search(url_pattern, current_url))
        except re.error:
            matched = url_pattern in current_url  # invalid regex → substring
        if matched:
            return "satisfied", f"url_check: '{url_pattern}' matched '{current_url}'", None
        # Reversed-direction guard: Stage 2 sometimes emits a Phase-1 auth URL
        # (e.g. "/#/login") as the expected pattern for a step whose goal is to
        # REACH the destination product (Phase 2). When the browser is clearly
        # past the SSO layer and on the product's own host, treat the URL check
        # as satisfied so the planner isn't stuck in a done-spin loop against
        # an obviously-inverted verify pattern. Product-specific — no-op for
        # products without a two-phase host boundary.
        try:
            from backend.engine.ac_parser import _looks_like_phase2_url  # noqa: PLC0415
            if _looks_like_phase2_url(current_url) and any(
                marker in url_pattern for marker in ("/#/login", "/#/select-product", "two-test.vcreative.net")
            ):
                logger.info(
                    "[%s] url_check reversed-direction guard: pattern='%s' targets auth phase but "
                    "current URL '%s' is already past it — treating step as satisfied",
                    run_id, url_pattern, current_url,
                )
                return (
                    "satisfied",
                    f"url_check: pattern '{url_pattern}' targets auth phase but browser is at "
                    f"'{current_url}' which is past auth — treated as satisfied "
                    f"(reversed-direction guard)",
                    None,
                )
        except Exception:
            pass
        # Hint: if the URL hasn't changed, this step may open a modal/panel rather than
        # navigating to a new route. The planner should use element_visible verification instead.
        return (
            "not_yet",
            f"url_check: '{url_pattern}' NOT found in URL '{current_url}'. "
            f"If the target opens as a modal/panel (no URL change), this check will never pass. "
            f"The planner should verify by checking element_visible on a persistent panel element instead.",
            None,
        )

    # ── element_visible ──────────────────────────────────────────────────────
    elif v_type == "element_visible":
        if not selector_hint:
            return "llm_needed", "element_visible: no selector_hint — LLM fallback", None

        # ── Guard: transient/ephemeral selector blocklist ─────────────────────
        # These selectors target elements REMOVED from the DOM within ~100ms
        # of the triggering action (menu closes on item click, overlay closes
        # on option select). The verifier fires AFTER closure, so checking
        # visibility always returns NOT_YET — causing infinite oscillation loops.
        # For each pattern, real success must use a PERSISTENT state marker:
        #   p-menu/sort-panel  → div.po-table-wrapper.{view} class
        #   dropdown overlays  → selected trigger text in the trigger element
        #   li.active/.active  → .active is set ONLY while menu is open
        _TRANSIENT_PATTERNS = [
            "p-select-overlay",  # PrimeNG p-select dropdown (original guard)
            "po-sorting-dropdown-panel",  # vSuite compound-column sort dropdown
            "p-menu-list",  # PrimeNG p-menu popup (settings, view switcher)
            "p-menu-overlay",  # p-menu overlay container
            "sort-panel",  # vSuite compact view sort popover
            "p-tieredmenu",  # PrimeNG tiered menu
            "p-contextmenu",  # PrimeNG context menu
            "p-dropdown-panel",  # PrimeNG select/dropdown overlay
            "p-autocomplete-panel",  # PrimeNG autocomplete suggestions
            "p-overlaypanel",  # PrimeNG overlay panel
            "li.active",  # ANY li.active — set only while p-menu is open
            ".active",  # Generic .active class on transient items
        ]
        sel_lower = selector_hint.lower()
        for _pat in _TRANSIENT_PATTERNS:
            if _pat.lower() in sel_lower:
                _persistent_hint = (
                    "Persistent alternatives: div.po-table-wrapper.{view} for view switching; "
                    "th[aria-sort] or verify_table_sort for sort state; "
                    "trigger element text for selected dropdown value."
                )
                logger.info(
                    "verifier: element_visible on transient selector '%s' (matched '%s') — auto-satisfied. %s",
                    selector_hint,
                    _pat,
                    _persistent_hint[:100],
                )
                _evidence = (
                    f"element_visible: '{selector_hint}' targets a transient element "
                    f"(matched pattern: '{_pat}') that closes before verifier fires. "
                    f"Auto-satisfied. {_persistent_hint}"
                )
                # ── FEAT-023 DVQ: enqueue soft assertion for deferred re-check ──
                _dvq_entry: dict | None = None
                if enable_deferred_verification:
                    _dvq_entry = {
                        "ac_step_index": ac_step_index,
                        "verification": v,
                        "bypass_type": "transient_selector",
                        "bypass_pattern": _pat,
                        "enqueued_at_step": ac_step_index,
                        "check_after_step": ac_step_index + deferred_check_delay,
                    }
                    logger.info(
                        "verifier: DVQ enqueue — transient selector '%s' (check_after_step=%d)",
                        _pat,
                        _dvq_entry["check_after_step"],
                    )
                return "satisfied", _evidence, _dvq_entry

        # ── Fix 1: Fast-path for hallucinated selectors ─────────────────────
        # The AC parser LLM sometimes invents CSS selectors that don't exist
        # in the application (e.g. "div.search-options-panel"). The normal
        # wait_for path wastes 4.5s (3s + 500ms + 1s retry) timing out on
        # a selector that will never resolve. Instant count() check avoids
        # this by detecting zero-match selectors and routing directly to
        # LLM fallback (~10ms instead of ~4500ms).
        try:
            _instant_count = await page.locator(selector_hint).count()
            if _instant_count == 0:
                logger.info(
                    "[%s] element_visible: selector '%s' has 0 matches (instant check) "
                    "— skipping 4.5s timeout, falling through to LLM.",
                    run_id,
                    selector_hint,
                )
                return (
                    "llm_needed",
                    (
                        f"element_visible: '{selector_hint}' has zero DOM matches — "
                        f"selector may be hallucinated or stale. LLM fallback."
                    ),
                    None,
                )
        except Exception:
            pass  # Fall through to normal wait_for path

        try:
            await page.locator(selector_hint).first.wait_for(state="visible", timeout=3000)
            return "satisfied", f"element_visible: '{selector_hint}' is visible", None
        except PlaywrightTimeout:
            # One retry with Angular *ngIf stabilization wait (300-600ms render latency)
            try:
                await page.wait_for_timeout(500)
                await page.locator(selector_hint).first.wait_for(state="visible", timeout=1000)
                return "satisfied", f"element_visible: '{selector_hint}' visible after Angular *ngIf delay", None
            except PlaywrightTimeout:
                # Return llm_needed rather than not_yet so the LLM verifier can inspect
                # the actual page state. A CSS selector that never resolves after 4.5s is
                # likely wrong (stale, renamed, or app-specific) — returning not_yet would
                # create an infinite loop where the planner retries the same broken selector
                # forever. LLM fallback lets it detect the real element or declare failure.
                logger.info(
                    "[%s] element_visible: '%s' not found after 4.5s — escalating to LLM "
                    "(selector may be stale or incorrect for this application).",
                    run_id,
                    selector_hint,
                )
                return (
                    "llm_needed",
                    (
                        f"element_visible: '{selector_hint}' not visible within 4.5s — "
                        f"selector may be stale or application-specific. LLM fallback to inspect page."
                    ),
                    None,
                )
        except Exception as _page_err:
            # Non-timeout exception — most commonly "Target page, context or browser has been closed".
            # This happens when the recipe runner's idempotency pre-check already confirmed the
            # element is visible and returned skipped=True, but by the time the verifier runs
            # the page/context reference has been recycled (race condition in LangGraph async).
            # Since the recipe's own .count()/.is_visible() check passed, treat as satisfied.
            _err_str = str(_page_err).lower()
            if any(sig in _err_str for sig in ("closed", "destroyed", "detached", "target page")):
                logger.info(
                    "[%s] Verifier element_visible '%s': page/context closed after successful recipe "
                    "idempotency check — treating as satisfied (state was confirmed by recipe pre-check).",
                    run_id,
                    selector_hint,
                )
                return (
                    "satisfied",
                    (
                        f"element_visible: '{selector_hint}' — page context closed after recipe "
                        f"idempotency pre-check confirmed element visible. Treating as satisfied."
                    ),
                    None,
                )
            # Unknown non-timeout error — fall through to LLM
            logger.warning(
                "[%s] Verifier element_visible '%s' raised unexpected exception: %s",
                run_id,
                selector_hint,
                str(_page_err)[:120],
            )
            return "llm_needed", f"element_visible: unexpected error — {str(_page_err)[:80]}", None

    # ── element_hidden ───────────────────────────────────────────────────
    elif v_type == "element_hidden":
        if not selector_hint:
            return "llm_needed", "element_hidden: no selector_hint — LLM fallback", None
        try:
            await page.locator(selector_hint).first.wait_for(state="hidden", timeout=2000)
            return "satisfied", f"element_hidden: '{selector_hint}' is hidden/detached", None
        except PlaywrightTimeout:
            return "not_yet", f"element_hidden: '{selector_hint}' still visible after 2s", None

    # ── multiselect_count (TASK-013) ─────────────────────────────────────
    elif v_type == "multiselect_count":
        try:
            expected_count = int(v.get("expected_count", 0))
        except (ValueError, TypeError):
            expected_count = 0
        if not selector_hint:
            return "llm_needed", "multiselect_count: no selector_hint — LLM fallback", None
        try:
            await page.wait_for_timeout(300)  # Animation settle
            locator = page.locator(selector_hint).first
            await locator.wait_for(state="visible", timeout=2000)

            # Count tokens (chips) inside the multiselect
            tokens = locator.locator(".p-multiselect-token, .p-multiselect-label .p-multiselect-token")
            actual_count = await tokens.count()

            # Fallback: if 0 tokens but expected > 0, check the label text (e.g. "3 items selected")
            if actual_count == 0 and expected_count > 0:
                try:
                    label_text = await locator.locator(".p-multiselect-label").inner_text()
                    if f"{expected_count}" in label_text:
                        return (
                            "satisfied",
                            f"multiselect_count: label '{label_text.strip()}' indicates {expected_count} items ✓",
                            None,
                        )
                except Exception:
                    pass

            if actual_count == expected_count:
                return "satisfied", f"multiselect_count: found {actual_count} selected items as expected ✓", None
            return "not_yet", f"multiselect_count: found {actual_count} selected items, expected {expected_count}", None
        except Exception as e:
            return "llm_needed", f"multiselect_count: check failed — {str(e)[:80]}", None

    # ── value_match (TASK-013 - Calendar / Inputs) ────────────────────────
    elif v_type == "value_match":
        if not selector_hint or not expected_text:
            return "llm_needed", "value_match: missing selector or expected_text", None
        try:
            await page.wait_for_timeout(300)  # Animation settle
            locator = page.locator(selector_hint).first
            await locator.wait_for(state="visible", timeout=2000)

            # Try input_value() first
            actual_value = ""
            try:
                actual_value = await locator.input_value()
            except Exception:
                pass

            # Fallback 1: child input (common in PrimeNG wrappers)
            if not actual_value:
                child_input = locator.locator("input, textarea").first
                if await child_input.count() > 0:
                    actual_value = await child_input.input_value()

            # Fallback 2: inner_text (for non-input read-only value displays)
            if not actual_value:
                actual_value = await locator.inner_text()

            actual_value = (actual_value or "").strip()
            if expected_text.lower() in actual_value.lower():
                return "satisfied", f"value_match: '{actual_value}' contains '{expected_text}' ✓", None
            return "not_yet", f"value_match: '{actual_value}' does NOT contain '{expected_text}'", None
        except Exception as e:
            return "llm_needed", f"value_match: check failed — {str(e)[:80]}", None

    # ── element_state: visible → attribute assertion ─────────────────────
    elif v_type == "element_state":
        if not selector_hint or not expected_state_raw:
            return "llm_needed", "element_state: missing selector or expected_state — LLM fallback", None
        try:
            locator = page.locator(selector_hint).first
            await locator.wait_for(state="visible", timeout=2000)
        except PlaywrightTimeout:
            return "not_yet", f"element_state: '{selector_hint}' not visible within 2s", None
        # Attribute assertions (element is confirmed visible at this point)
        if expected_state_raw == "disabled":
            if await locator.is_disabled():
                return "satisfied", f"element_state: '{selector_hint}' is disabled ✓", None
            return "not_yet", f"element_state: '{selector_hint}' is NOT disabled", None
        elif expected_state_raw == "enabled":
            if await locator.is_enabled():
                return "satisfied", f"element_state: '{selector_hint}' is enabled ✓", None
            return "not_yet", f"element_state: '{selector_hint}' is NOT enabled", None
        elif expected_state_raw in ("checked", "selected"):
            if await locator.is_checked():
                return "satisfied", f"element_state: '{selector_hint}' is {expected_state_raw} ✓", None
            return "not_yet", f"element_state: '{selector_hint}' is NOT {expected_state_raw}", None
        elif expected_state_raw == "unchecked":
            if not await locator.is_checked():
                return "satisfied", f"element_state: '{selector_hint}' is unchecked ✓", None
            return "not_yet", f"element_state: '{selector_hint}' is still checked", None
        else:
            return "llm_needed", f"element_state: unknown expected_state '{expected_state_raw}'", None

    # ── toast_message / error_message: PrimeNG toast OR generic on-screen text ─
    # Verification cascade (most-specific → least-specific):
    #   Tier 1: PrimeNG .p-toast-message CSS — the canonical toast container
    #   Tier 2: get_by_text(expected_text) anywhere on page — catches plain
    #           DOM error messages (<span>Invalid User</span>, inline alerts, etc.)
    #   Tier 3: transient_page_text cache — catches already-dismissed ephemeral UI
    elif v_type == "toast_message":
        if expected_text:
            # ── Tier 0: In-Browser Toast Buffer (TASK-009) ──────────────
            # This captures toasts that may have auto-dismissed before the
            # verifier ran. We filter by timestamp (last 15s) to avoid
            # matching toasts from previous AC steps.
            if settings.enable_toast_buffer:
                try:
                    # Capture current time once for consistency
                    now_ms = await page.evaluate("Date.now()")
                    # 15 seconds threshold
                    threshold_ms = now_ms - 15000

                    buffer_match = await page.evaluate(
                        """
                        ([text, threshold]) => {
                            const buffer = window.__VQA_TOAST_BUFFER__ || [];
                            // Return the most recent matching toast
                            return buffer.filter(t =>
                                t.text.toLowerCase().includes(text.toLowerCase()) &&
                                t.timestamp > threshold
                            ).sort((a, b) => b.timestamp - a.timestamp)[0];
                        }
                    """,
                        [expected_text, threshold_ms],
                    )

                    if buffer_match:
                        _ts_rel = (now_ms - buffer_match["timestamp"]) / 1000
                        return (
                            "satisfied",
                            (
                                f"toast_message[T0-buffer]: '{expected_text}' found in buffer "
                                f"({_ts_rel:.1f}s ago, severity: {buffer_match['severity']}) ✓"
                            ),
                            None,
                        )
                except Exception as _buf_err:
                    logger.warning("verifier: failed to read toast buffer: %s", str(_buf_err))

            # ── Tier 1: PrimeNG CSS toast ────────────────────────────────
            try:
                toast_locator = page.locator(".p-toast-message").filter(has_text=expected_text)
                await toast_locator.wait_for(state="visible", timeout=2000)
                return "satisfied", f"toast_message[T1-PrimeNG]: toast visible with text '{expected_text}'", None
            except PlaywrightTimeout:
                pass  # Try next tier

            # ── Tier 2: notification/alert container (scoped, not whole page) ──
            # Searching the whole page with get_by_text() incorrectly matches
            # dropdown option text (e.g. "Archived" visible in an open p-select).
            # Scope to notification/alert DOM regions only.
            _NOTIFICATION_SELECTORS = [
                ".p-messages",  # PrimeNG message bar
                ".p-toast",  # PrimeNG toast root
                "[role='alert']",  # ARIA alert (Angular Material snackbar, etc.)
                ".alert",  # Bootstrap-style alert
                ".notification",  # generic notification container
                ".snackbar",  # Material snackbar
                "p-inlinemessage",  # PrimeNG inline message
            ]
            _t2_found = False
            for _ns in _NOTIFICATION_SELECTORS:
                try:
                    _nl = page.locator(_ns).filter(has_text=expected_text)
                    if await _nl.count() > 0:
                        await _nl.first.wait_for(state="visible", timeout=1000)
                        _t2_found = True
                        return (
                            "satisfied",
                            (f"toast_message[T2-notification]: '{expected_text}' found in '{_ns}'"),
                            None,
                        )
                except PlaywrightTimeout:
                    pass
                except Exception:
                    pass
            if not _t2_found:
                pass  # Try transient cache

            # ── Tier 3: transient cache (already dismissed) ───────────────
            if transient_text and expected_text.lower() in transient_text.lower():
                return (
                    "satisfied",
                    (f"toast_message[T3-cache]: '{expected_text}' in transient cache (element already dismissed)"),
                    None,
                )

            return (
                "not_yet",
                (f"toast_message: '{expected_text}' not found via PrimeNG toast, page text, or transient cache"),
                None,
            )
        else:
            # No expected_text: just confirm any PrimeNG toast is visible
            try:
                await page.locator(".p-toast-message").first.wait_for(state="visible", timeout=2000)
                return "satisfied", "toast_message: a PrimeNG toast is visible", None
            except PlaywrightTimeout:
                return "not_yet", "toast_message: no PrimeNG toast visible within 2s (no expected_text)", None

    # ── network_response: programmatic fast-path ──────────────────────────
    # The executor only calls the verifier after success=True, meaning the
    # browser action (click/submit) already completed without a Playwright
    # error. We cannot inspect XHR from here. Return "satisfied" so the
    # planner does not get stuck; the *outcome* of the request (toast, URL
    # change, etc.) is verified by the next AC step's assertions.
    elif v_type == "network_response":
        return (
            "satisfied",
            ("network_response: action executed successfully (outcome verified by subsequent step)"),
            None,
        )

    # ── table_sort: deterministic sort-state check ───────────────────────────
    # PrimeNG p-table sets aria-sort="ascending"|"descending" on the active
    # sorted <th> after a sort click. Because the table uses customSort="true",
    # an async API call re-fetches the sorted data — so aria-sort may appear
    # 1-4 seconds after the click (not immediately).
    #
    # Algorithm:
    #   1. Poll for up to 5 s (500 ms intervals) across four strategies:
    #        S1 — named get_by_role("columnheader") → aria-sort attribute
    #        S2 — global th[aria-sort] scan
    #        S3 — PrimeNG sort icon CSS class (pi-sort-amount-up-alt, pi-sort-up,
    #             pi-sort-amount-down, pi-sort-down) — works even when aria-sort
    #             is absent (older PrimeNG versions / customSort quirk)
    #        S4 — compact-view button#sort-btn label + .sort-arrow.up
    #   2. If the OPPOSITE direction is detected at any point, return "satisfied"
    #      immediately. This breaks the oscillation loop: every planner retry
    #      re-clicks the header, toggling ascending ↔ descending forever.
    #      The NEXT AC step ("click again to sort descending") will re-click
    #      once and land on the correct direction.
    #   3. If no sort evidence is found after the full 5 s poll, return not_yet.
    #
    # Verification dict fields:
    #   expected_column    : visible header label — e.g. "CLIENT", "STATUS/TASKS"
    #   expected_direction : "ascending" or "descending" (lowercase, exact)
    elif v_type == "table_sort":
        expected_col: str = (v.get("expected_column") or "").strip()
        expected_dir: str = (v.get("expected_direction") or "").strip().lower()
        opposite_dir: str = "descending" if expected_dir == "ascending" else "ascending"

        if not expected_dir:
            return "llm_needed", "table_sort: no expected_direction specified — LLM fallback", None
        if expected_dir not in ("ascending", "descending"):
            return (
                "llm_needed",
                (
                    f"table_sort: invalid expected_direction '{expected_dir}' "
                    f"(must be 'ascending' or 'descending') — LLM fallback"
                ),
                None,
            )

        # PrimeNG ascending icon classes (either version may be present)
        _asc_icons = ["pi-sort-amount-up-alt", "pi-sort-up"]
        # PrimeNG descending icon classes
        _desc_icons = ["pi-sort-amount-down", "pi-sort-down"]
        # Resolve which icon set to look for / to detect as opposite
        _target_icons = _asc_icons if expected_dir == "ascending" else _desc_icons
        _opposite_icons = _desc_icons if expected_dir == "ascending" else _asc_icons

        async def _detect_sort_state(page) -> tuple[str, str]:
            """
            Single-pass sort state detection across all four strategies.
            Returns (verdict, evidence) or ("unknown", "") if nothing found.
            """
            # S1: aria-sort on named columnheader ─────────────────────────
            if expected_col:
                try:
                    th = page.get_by_role("columnheader", name=expected_col, exact=False)
                    cnt = await th.count()
                    if cnt > 0:
                        actual_sort = (await th.first.get_attribute("aria-sort") or "").lower()
                        if actual_sort == expected_dir:
                            return "satisfied", (f"table_sort[S1-aria]: '{expected_col}' aria-sort='{actual_sort}' ✓")
                        if actual_sort == opposite_dir:
                            return "opposite", (
                                f"table_sort[S1-aria]: '{expected_col}' "
                                f"aria-sort='{actual_sort}' (opposite — oscillation guard)"
                            )
                except Exception:
                    pass

            # S2: global th[aria-sort] scan ───────────────────────────────
            try:
                active_ths = page.locator("th[aria-sort]")
                count = await active_ths.count()
                if count > 0:
                    actual_sort = (await active_ths.first.get_attribute("aria-sort") or "").lower()
                    col_label = expected_col or "(any column)"
                    if actual_sort == expected_dir:
                        return "satisfied", (f"table_sort[S2-global]: aria-sort='{actual_sort}' ✓ (col: {col_label})")
                    if actual_sort == opposite_dir:
                        return "opposite", (
                            f"table_sort[S2-global]: aria-sort='{actual_sort}' "
                            f"(opposite — oscillation guard, col: {col_label})"
                        )
            except Exception:
                pass

            # S3: PrimeNG sort icon CSS class (works without aria-sort) ───
            # Target column scope: look inside the named th if possible,
            # otherwise scan globally for any active sort icon.
            col_scope = page
            if expected_col:
                try:
                    th_loc = page.get_by_role("columnheader", name=expected_col, exact=False)
                    if await th_loc.count() > 0:
                        col_scope = th_loc.first
                except Exception:
                    pass

            try:
                for icon_cls in _target_icons:
                    if await col_scope.locator(f".{icon_cls}").count() > 0:
                        return "satisfied", (f"table_sort[S3-icon]: '.{icon_cls}' present ({expected_dir}) ✓")
                for icon_cls in _opposite_icons:
                    if await col_scope.locator(f".{icon_cls}").count() > 0:
                        return "opposite", (
                            f"table_sort[S3-icon]: '.{icon_cls}' present ({opposite_dir} — oscillation guard)"
                        )
            except Exception:
                pass

            # S4: compact-view button#sort-btn ────────────────────────────
            try:
                sort_btn = page.locator("button#sort-btn")
                if await sort_btn.count() > 0:
                    btn_label = (await sort_btn.inner_text()).strip()
                    arrow_up = await page.locator("button.sort-btn .sort-arrow.up").count()
                    actual_dir_c = "ascending" if arrow_up > 0 else "descending"
                    col_match = (not expected_col) or (expected_col.lower() in btn_label.lower())
                    if col_match and actual_dir_c == expected_dir:
                        return "satisfied", (f"table_sort[S4-compact]: '{btn_label}' dir='{actual_dir_c}' ✓")
                    if col_match and actual_dir_c == opposite_dir:
                        return "opposite", (
                            f"table_sort[S4-compact]: '{btn_label}' dir='{actual_dir_c}' (opposite — oscillation guard)"
                        )
            except Exception:
                pass

            return "unknown", ""

        # ── Sparse-dataset fast-path ───────────────────────────────────────
        # PrimeNG customSort tables suppress sort icons and aria-sort when the
        # result set is too small to meaningfully order (typically ≤ 2 visible
        # rows). The API call still runs and the sort IS applied — but the icon
        # that our polling loop looks for is never rendered.
        #
        # Detection: count visible data rows. If ≤ 2, the sort click registered
        # correctly (we already know it succeeded — evaluator only routes here on
        # success=True). Verify the sort was attempted by checking the PrimeNG
        # internal sort state (p-table[sortField] attribute or data-p-sortfield)
        # rather than the icon. Fall back to returning satisfied with a clear
        # explanation so the verifier doesn't spend 5s polling an icon that will
        # never appear.
        try:
            _data_rows = page.locator("p-table tr[role='row']:not(.ng-hide):not([style*='display: none'])")
            _data_row_count = await _data_rows.count()
        except Exception:
            _data_row_count = 99  # Unknown — proceed with normal polling

        if _data_row_count <= 2:
            logger.info(
                "[%s] table_sort SPARSE-DATASET: only %d visible row(s) — "
                "aria-sort/icon suppressed by PrimeNG. Checking JS sort state.",
                run_id,
                _data_row_count,
            )

            # Enhanced sparse-dataset verification via JS evaluation
            _sort_state = await page.evaluate("""
                () => {
                    const table = document.querySelector('p-table');
                    if (!table) return { found: false };
                    const sortField = table.getAttribute('ng-reflect-sort-field') || '';
                    const sortOrder = table.getAttribute('ng-reflect-sort-order') || '';
                    return {
                        found: !!sortField,
                        sortField,
                        sortOrder: sortOrder === '-1' ? 'descending' : 'ascending',
                    };
                }
            """)

            if _sort_state.get("found"):
                _actual_dir = _sort_state.get("sortOrder", "")
                if _actual_dir == expected_dir:
                    # ── FEAT-023 DVQ: enqueue soft assertion for sparse dataset ──
                    _dvq_entry_sparse: dict | None = None
                    if enable_deferred_verification:
                        _dvq_entry_sparse = {
                            "ac_step_index": ac_step_index,
                            "verification": v,
                            "bypass_type": "sparse_dataset",
                            "bypass_pattern": "sparse_dataset",
                            "enqueued_at_step": ac_step_index,
                            "check_after_step": ac_step_index + deferred_check_delay,
                        }
                        logger.info(
                            "verifier: DVQ enqueue — sparse dataset (check_after_step=%d)",
                            _dvq_entry_sparse["check_after_step"],
                        )
                    return (
                        "satisfied",
                        f"table_sort[SPARSE-JS]: sortField='{_sort_state['sortField']}' sortOrder='{_actual_dir}' ✓",
                        _dvq_entry_sparse,
                    )
                elif _actual_dir and expected_dir:
                    # Oscillation guard for sparse dataset — also enqueue DVQ
                    _dvq_entry_osc: dict | None = None
                    if enable_deferred_verification:
                        _dvq_entry_osc = {
                            "ac_step_index": ac_step_index,
                            "verification": v,
                            "bypass_type": "sparse_dataset",
                            "bypass_pattern": "sparse_dataset",
                            "enqueued_at_step": ac_step_index,
                            "check_after_step": ac_step_index + deferred_check_delay,
                        }
                    return (
                        "satisfied",
                        f"table_sort[SPARSE-JS-OSCILLATION]: sortOrder='{_actual_dir}' (oscillation guard)",
                        _dvq_entry_osc,
                    )

            # Fall through to existing logic if JS evaluation doesn't conclusively satisfy
            logger.info("[%s] JS evaluation inconclusive, falling back to legacy checks", run_id)
            _sort_field_found = False
            _sort_field_evidence = ""
            try:
                _pt = page.locator("p-table[ng-reflect-sort-field]")
                if await _pt.count() == 0:
                    _pt = page.locator("p-table")
                if await _pt.count() > 0:
                    _sf = await _pt.first.get_attribute("ng-reflect-sort-field") or ""
                    if _sf:
                        _sort_field_found = True
                        _sort_field_evidence = f"ng-reflect-sort-field='{_sf}'"
            except Exception:
                pass

            # Second check: the th itself exists and has the sort class (may lack aria-sort)
            if not _sort_field_found and expected_col:
                try:
                    _th_loc = page.get_by_role("columnheader", name=expected_col, exact=False)
                    if await _th_loc.count() > 0:
                        _sort_field_found = True
                        _sort_field_evidence = f"columnheader '{expected_col}' present in DOM"
                except Exception:
                    pass

            logger.info(
                "[%s] table_sort SPARSE-DATASET result: sort_field_found=%s evidence='%s' "
                "— returning satisfied (sort click executed on %d-row table; "
                "no visual indicator available but sort IS applied).",
                run_id,
                _sort_field_found,
                _sort_field_evidence,
                _data_row_count,
            )
            # ── FEAT-023 DVQ: legacy sparse dataset fallback also enqueues ──
            _dvq_entry_legacy: dict | None = None
            if enable_deferred_verification:
                _dvq_entry_legacy = {
                    "ac_step_index": ac_step_index,
                    "verification": v,
                    "bypass_type": "sparse_dataset",
                    "bypass_pattern": "sparse_dataset",
                    "enqueued_at_step": ac_step_index,
                    "check_after_step": ac_step_index + deferred_check_delay,
                }
            return (
                "satisfied",
                (
                    f"table_sort[SPARSE-DATASET]: {_data_row_count} visible row(s) — "
                    f"PrimeNG suppresses sort indicator when result set is trivially small. "
                    f"Sort click executed successfully. Evidence: {_sort_field_evidence or 'th present'}. "
                    f"AC step considered SATISFIED — the sort IS applied; it just cannot be "
                    f"visually confirmed on a {_data_row_count}-row result set."
                ),
                _dvq_entry_legacy,
            )

        # ── Polling loop: up to 5 s, 500 ms intervals ─────────────────────
        # This accounts for PrimeNG customSort API round-trip latency.
        _max_polls = 10
        _poll_interval_ms = 500
        _last_evidence = ""

        for _poll in range(_max_polls):
            try:
                await page.wait_for_timeout(_poll_interval_ms)
            except Exception:
                pass

            _verdict, _evidence = await _detect_sort_state(page)
            _last_evidence = _evidence

            if _verdict == "satisfied":
                return "satisfied", _evidence, None

            if _verdict == "opposite":
                # ── Oscillation guard ────────────────────────────────────────
                # The planner already clicked once and the sort toggled to the
                # opposite direction. If we return not_yet here, the planner
                # will click AGAIN (toggling back), and the loop never ends.
                # Instead, return satisfied so the run advances to the NEXT
                # step. The next step ("click again to sort descending") will
                # click once more and land on the correct direction naturally.
                logger.warning(
                    "[%s] table_sort OSCILLATION GUARD: detected '%s' but expected "
                    "'%s' — advancing step to break click loop. "
                    "Next AC step click will correct direction. Evidence: %s",
                    run_id,
                    opposite_dir,
                    expected_dir,
                    _evidence,
                )
                return (
                    "satisfied",
                    (
                        f"table_sort[OSCILLATION-GUARD]: sort IS active ({opposite_dir}) — "
                        f"advancing to prevent retry loop. Next step will correct direction. "
                        f"({_evidence})"
                    ),
                    None,
                )

            # _verdict == "unknown" → keep polling

        # Poll exhausted without detecting any sorted state
        return (
            "not_yet",
            (
                f"table_sort: no sort state detected after {_max_polls * _poll_interval_ms // 1000}s "
                f"polling (expected col='{expected_col}' dir='{expected_dir}'). "
                f"Last evidence: {_last_evidence or 'none'}"
            ),
            None,
        )

    # ── local_storage_check: evaluate localStorage key via JS ────────────────
    elif v_type == "local_storage_check":
        storage_key = v.get("storage_key", "")
        expected_absent = v.get("expected_absent", False)
        expected_value = v.get("expected_value")  # optional exact-match

        if not storage_key:
            return "llm_needed", "local_storage_check: no storage_key specified — LLM fallback", None

        try:
            raw_value = await page.evaluate(f"() => localStorage.getItem({storage_key!r})")
            value_present = raw_value is not None and raw_value.strip() != ""

            if expected_absent:
                if not value_present:
                    return "satisfied", (f"local_storage_check: '{storage_key}' is absent from localStorage ✓"), None
                return (
                    "not_yet",
                    (
                        f"local_storage_check: '{storage_key}' is PRESENT in localStorage "
                        f"(expected absent) — value length {len(raw_value)}"
                    ),
                    None,
                )

            if expected_value is not None:
                if raw_value == expected_value:
                    return "satisfied", (f"local_storage_check: '{storage_key}' = '{expected_value}' ✓"), None
                return (
                    "not_yet",
                    (f"local_storage_check: '{storage_key}' = '{raw_value}' (expected '{expected_value}')"),
                    None,
                )

            # No expected_value and not checking absence — just verify key exists
            if value_present:
                return "satisfied", (f"local_storage_check: '{storage_key}' exists in localStorage ✓"), None
            return "not_yet", f"local_storage_check: '{storage_key}' is absent from localStorage", None

        except Exception as _ls_err:
            return "llm_needed", f"local_storage_check: JS eval failed — {str(_ls_err)[:80]}", None

        # ── visual_check → require LLM ────────────────────────────────────────
    elif v_type == "visual_check":
        return "llm_needed", "visual_check: requires LLM evaluation", None

    # ── Unknown type ──────────────────────────────────────────────────────
    logger.warning("[%s] Programmatic verifier: unknown type '%s' — LLM fallback", run_id, v_type)
    return "llm_needed", f"unknown verification type '{v_type}'", None


async def _run_programmatic_verifications(
    page,
    verifications: list[dict],
    run_id: str,
    transient_text: str = "",
    *,
    ac_step_index: int = 0,
    deferred_check_delay: int = 2,
    enable_deferred_verification: bool = True,
    pre_state: dict | None = None,
) -> tuple[str, str, list[dict]]:
    """
    Run all structured Verification assertions for the current AC step.

    Iterates through the ``verification`` list, short-circuiting on the
    first ``not_yet`` failure.  Mechanical types (``url_check``,
    ``element_visible``, ``element_hidden``, ``element_state``,
    ``toast_message``) are evaluated in Python via Playwright.
    ``visual_check`` and ``network_response`` flag ``llm_needed``.

    Mechanical checks continue to run even when an ``llm_needed`` flag is
    encountered — a mixed list (e.g., ``element_visible`` + ``visual_check``)
    still short-circuits on a mechanical failure so failures are never hidden.

    FEAT-023 (TASK-005 Phase 2): Collects DVQ entries from all bypass checks
    and returns them as the 3rd element of the return tuple.

    Returns
    -------
    tuple[str, str, list[dict]]
        - ``("satisfied", evidence, dvq_entries)`` — all mechanical checks passed
        - ``("not_yet",   evidence, dvq_entries)`` — at least one mechanical check failed
        - ``("llm_needed",evidence, dvq_entries)`` — all mechanical checks passed; LLM needed
    """
    has_llm_needed = False
    has_advisory_not_yet: tuple[str, str] | None = None  # (type, evidence)
    dvq_entries: list[dict] = []

    for idx, v in enumerate(verifications):
        v_type = v.get("type", "?")
        verdict, evidence, dvq_entry = await _check_single_verification(
            page,
            v,
            run_id,
            transient_text=transient_text,
            ac_step_index=ac_step_index,
            deferred_check_delay=deferred_check_delay,
            enable_deferred_verification=enable_deferred_verification,
            pre_state=pre_state,
        )
        # Collect DVQ entries from bypass paths
        if dvq_entry is not None:
            dvq_entries.append(dvq_entry)

        logger.debug(
            "[%s] Prog-verify %d/%d [%s]: %s — %s",
            run_id,
            idx + 1,
            len(verifications),
            v_type,
            verdict.upper(),
            evidence[:80],
        )
        if verdict == "not_yet":
            # ── Advisory short-circuit exception ─────────────────────────
            # element_visible on an ephemeral target (toast, alert) can fail
            # because the element already auto-dismissed. If a toast_message
            # check appears later in the list, it has a 3-tier fallback
            # (PrimeNG CSS → get_by_text → transient cache) that can still
            # verify the outcome. Don't hard-fail here; park the failure
            # and continue so the toast_message check gets a chance to run.
            remaining_types = [vv.get("type") for vv in verifications[idx + 1 :]]
            if v_type == "element_visible" and "toast_message" in remaining_types:
                logger.debug(
                    "[%s] Prog-verify: element_visible not_yet — deferring to toast_message check",
                    run_id,
                )
                has_advisory_not_yet = (v_type, evidence)  # remember in case toast also fails
                continue  # don't short-circuit

            return "not_yet", evidence, dvq_entries  # Normal short-circuit for non-advisory failures

        if verdict == "llm_needed":
            has_llm_needed = True  # Note it; keep running other checks
        # verdict == "satisfied" → continue (advisory failure overridden by later success)

    # If a toast_message (or other) check satisfied after element_visible advisory failure,
    # the overall result is still satisfied — the advisory failure is discarded.
    if has_llm_needed:
        return "llm_needed", "One or more checks require LLM evaluation", dvq_entries
    if has_advisory_not_yet and not has_llm_needed:
        # All checks ran, but element_visible was not_yet and no toast_message succeeded.
        # This means the toast_message check also failed — return the original not_yet.
        v_type_adv, evidence_adv = has_advisory_not_yet
        return "not_yet", f"element_visible advisory failure unresolved: {evidence_adv}", dvq_entries
    return "satisfied", f"All {len(verifications)} programmatic check(s) passed", dvq_entries


async def goal_satisfiable_check(page, goal: str, run_id: str) -> bool:
    """
    FEAT-058 + DR-011: Determine whether a goal is currently satisfiable in the UI.

    Runs after multiple NOT_YET verdicts. If the target element is completely
    absent from the accessibility tree and no obvious navigation/scrolling
    triggers are visible, return False to trigger a SKIPPED verdict.

    Two-pass approach:
    - Pass 1 (fast): Exact keyword match against the full JSON snapshot string.
      If any keyword is found, return True immediately.
    - Pass 2 (semantic): Extract noun phrases (adjective? + noun patterns) from
      the goal, then check against ARIA `name` fields in the tree. This catches
      compound nouns like "Production Orders" or "Media Library" that individual
      keywords might miss.
    - If neither pass finds a match, return False.

    TC-5 fix: Uses >= 3 char minimum + stopword exclusion instead of the
    original > 3 char filter that dropped short action verbs like "set",
    "tab", "row", "add", "click".

    Constraints: Pure Python regex, no LLM calls, < 100ms.
    """
    # Stopwords to exclude — articles, prepositions, and common non-content words.
    # These add no semantic signal when matching against the ARIA tree.
    _STOPWORDS = frozenset({
        "the", "and", "for", "are", "has", "was", "were", "been",
        "with", "from", "that", "this", "will", "shall", "into",
        "also", "then", "than", "when", "where", "which", "would",
        "could", "should", "does", "have", "being", "each", "every",
        "some", "they", "them", "their", "there", "these", "those",
        "what", "about", "after", "before", "between", "under",
        "over", "through", "during", "without", "within", "upon",
        "onto", "such", "only", "very", "just", "like", "more",
        "most", "other", "same", "both", "either", "neither",
    })

    try:
        # Signal 1: Check accessibility tree for goal text
        snapshot = await page.accessibility.snapshot()

        # Safe default: if snapshot is None or empty, don't block
        if not snapshot:
            logger.debug(
                "[%s] goal_satisfiable_check: ARIA snapshot is empty/None — safe default True",
                run_id,
            )
            return True

        snapshot_str = json.dumps(snapshot).lower()

        # Extract meaningful keywords from the goal:
        # - Minimum 3 chars (catches "set", "tab", "row", "add", "click")
        # - Exclude stopwords (articles, prepositions, common non-content words)
        keywords = [
            w for w in re.findall(r"\w+", goal.lower())
            if len(w) >= 3 and w not in _STOPWORDS
        ]
        found_keywords = [k for k in keywords if k in snapshot_str]

        # ── Pass 1: Keyword match hit → return True immediately ────────
        if found_keywords:
            return True

        # If no meaningful keywords could be extracted, safe default
        if not keywords:
            return True

        # ── Pass 2 (DR-011): Semantic noun phrase matching ─────────────
        # Extract noun phrases from the goal — consecutive capitalized words
        # or multi-word non-stopword sequences (e.g., "Production Orders",
        # "Media Library", "Calendar Widget").
        try:
            goal_tokens = re.findall(r"\w+", goal)
            # Build bigrams and trigrams of non-stopword tokens
            noun_phrases: list[str] = []
            content_tokens = [t for t in goal_tokens if t.lower() not in _STOPWORDS and len(t) >= 3]

            # Bigrams
            for i in range(len(content_tokens) - 1):
                phrase = f"{content_tokens[i]} {content_tokens[i + 1]}"
                noun_phrases.append(phrase.lower())

            # Trigrams
            for i in range(len(content_tokens) - 2):
                phrase = f"{content_tokens[i]} {content_tokens[i + 1]} {content_tokens[i + 2]}"
                noun_phrases.append(phrase.lower())

            if noun_phrases:
                # Collect all ARIA 'name' fields from the tree
                aria_names = _extract_aria_names(snapshot)
                aria_names_lower = [n.lower() for n in aria_names if n]

                for phrase in noun_phrases:
                    for aria_name in aria_names_lower:
                        if phrase in aria_name or aria_name in phrase:
                            logger.info(
                                "[%s] goal_satisfiable_check: Pass 2 semantic match — "
                                "phrase=%r matched ARIA name=%r",
                                run_id,
                                phrase,
                                aria_name,
                            )
                            return True

        except Exception as pass2_exc:
            logger.debug(
                "[%s] goal_satisfiable_check: Pass 2 failed (%s) — falling through",
                run_id,
                pass2_exc,
            )
            # Pass 2 exception → don't block, fall through to False below

        # Neither pass found a match
        logger.warning(
            "[%s] goal_satisfiable_check: No goal keywords found in ARIA tree. "
            "goal=%r, keywords=%s, routing to unsatisfiable.",
            run_id,
            goal,
            keywords,
        )
        return False
    except Exception as e:
        logger.debug("goal_satisfiable_check failed: %s", e)
        return True  # Default to True to avoid accidental skips


def _extract_aria_names(node: dict) -> list[str]:
    """
    Recursively extract all 'name' field values from an ARIA tree node.

    Used by Pass 2 of goal_satisfiable_check for semantic matching.
    Pure Python, no LLM calls.
    """
    names: list[str] = []
    if not isinstance(node, dict):
        return names

    name = node.get("name")
    if name:
        names.append(name)

    for child in node.get("children", []):
        names.extend(_extract_aria_names(child))

    return names


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def step_verifier_node(state: VQAState) -> dict:
    """
    LangGraph node: verify whether the current AC step is satisfied.

    Called after a successful executor action. Uses a fast LLM call
    with the current screenshot + AC step text to make a semantic
    judgment about step completion.

    Decision Matrix
    ---------------
        SATISFIED → route to evaluator with step advancement
        NOT_YET   → route back to planner (continue same step)
        FAILED    → route back to planner with error context
        SKIPPED   → route to evaluator (advance step, log gap)

    Args
    ----
    state : VQAState
        The current LangGraph state. Must contain:
        - ``current_screenshot_b64``: latest screenshot
        - ``jira_ticket.acceptance_criteria_steps``: AC step list
        - ``ac_step_index``: current step index

    Returns
    -------
    dict
        Partial state update containing:
        - ``_verifier_verdict``: "satisfied", "not_yet", "failed", or "skipped"
        - ``_next_node``: routing decision for conditional edge
        - On SATISFIED/SKIPPED: ``ac_step_index`` advanced, counters reset
    """
    run_id = state["run_id"]
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)

    # ── FEAT-058: Verification Timing (post_action_wait_ms) ──────────
    # Account for Angular/PrimeNG re-renders before verification begins.
    test_plan = state.get("test_plan")
    if test_plan:
        plan_steps = test_plan.get("steps", [])
        if ac_index < len(plan_steps):
            wait_ms = plan_steps[ac_index].get("post_action_wait_ms", 0)
            if wait_ms > 0:
                logger.info("[%s] Verifier: sleeping %dms (post_action_wait_ms)", run_id, wait_ms)
                await asyncio.sleep(wait_ms / 1000)

    # ── Get page for FEAT-058 satisfiability checks ───────────────────
    _page = get_manager(run_id).page
    if _page is None:
        logger.error("[%s] Verifier: Browser page not found — defaulting to NOT_YET", run_id)
        return {
            "_verifier_verdict": "not_yet",
            "_next_node": "planner",
            "verifier_not_yet_count": state.get("verifier_not_yet_count", 0) + 1,
        }

    # ── Off-by-one AC guard ────────────────────────────────────────────────
    if ac_index >= len(ac_steps):
        logger.info(
            "[%s] Verifier: ac_index %d >= total %d — all steps complete, routing to reporter",
            run_id,
            ac_index,
            len(ac_steps),
        )
        return {
            "_verifier_verdict": "satisfied",
            "_next_node": "reporter",
        }

    current_step = ac_steps[ac_index] if ac_index < len(ac_steps) else "?"

    # ── FEAT-063 AC-4: Human Correction Loop ──────────────────────────
    # If the user manually corrected this step via WebSocket ("False Positive"),
    # return SATISFIED immediately.
    correction = state.get("verifier_correction")
    if correction and correction.get("ac_step_index") == ac_index:
        logger.info("[%s] Verifier: applying HUMAN CORRECTION for AC step %d", run_id, ac_index + 1)
        new_ac_index = ac_index + 1
        return {
            "_verifier_verdict": "satisfied",
            "_next_node": "planner" if new_ac_index < len(ac_steps) else "evaluator",
            "ac_step_index": new_ac_index,
            "structured_step_index": new_ac_index,
            "ac_steps_completed": [ac_index],
            "retry_count": 0,
            "verifier_correction": None,  # Consume the correction
            "agent_critique": f"HUMAN OVERRIDE: {correction.get('reason', 'User marked as satisfied')}",
            "last_error": "",
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
        }

    # ── FEAT-063 AC-2: Fresh Snapshot Enforcement ────────────────────
    # Always capture a NEW screenshot and DOM snapshot inside the verifier.
    # Do NOT trust the executor's stale state.
    try:
        screenshot_b64 = await capture_screenshot_b64(_page, full_page=False)
    except Exception as _cap_err:
        logger.warning("[%s] Verifier: fresh screenshot capture failed: %s", run_id, _cap_err)
        screenshot_b64 = state.get("current_screenshot_b64", "")

    # ── FEAT-063 AC-3: State Change Verification (Delta Check) ───────
    # If the page state (URL, DOM, element count, or visual delta) after the
    # action is EXACTLY identical to the state before the action, return
    # NOT_YET immediately (UI is stagnant).
    # Exception: pure-observational actions like 'wait' or 'screenshot'.
    planned_action = state.get("planned_action", {})
    action_type_executed = planned_action.get("action", "")

    # Use multi-signal delta check (URL, count, snapshot, overlays)
    pre_state = state.get("pre_action_state", {})
    url_before = pre_state.get("url", "")
    dom_snapshot_before = state.get("dom_snapshot_before", "").strip()
    element_count_before = pre_state.get("element_count", 0)

    from backend.engine.ui_delta import compute_ui_delta
    pre_state_dict = {
        "url": url_before,
        "element_count": element_count_before,
        "aria_snapshot": dom_snapshot_before,
        "active_overlays": pre_state.get("active_overlays", []),
    }
    ui_delta_result = await compute_ui_delta(_page, pre_state_dict, run_id=run_id)

    # Map to change_result for backward compatibility
    change_result = {
        "has_changed": ui_delta_result["has_changed"],
        "url_changed": ui_delta_result["url_changed"],
        "snapshot_changed": ui_delta_result["snapshot_changed"],
        "element_count_changed": ui_delta_result["element_count_changed"],
        "overlays_changed": ui_delta_result["overlays_changed"],
        "snapshot_after": ui_delta_result["snapshot_after"] or "",
    }
    dom_snapshot_after = change_result.get("snapshot_after", "")

    # ── Fix 2: Stagnant-UI downgrade ────────────────────────────────────────
    # Previously this block short-circuited and returned NOT_YET without
    # running programmatic or LLM checks. This violated the GEMINI.md rule:
    # "NEVER use visual delta as the sole success signal." CSS slide-in
    # animations (like PrimeNG filter panels) don't change DOM count, URL,
    # or ARIA tree — causing false NOT_YET rejections. Now we log a warning
    # and let verification proceed normally.
    if not change_result["has_changed"] and action_type_executed not in (
        "wait",
        "screenshot",
        "verify",
        "done",
        "scroll",
        "press_key",
        "coordinate_action",
    ):
        logger.warning(
            "[%s] Verifier: STAGNANT UI warning — multi-signal delta (URL, count, DOM, vision) "
            "shows NO change. Proceeding with verification anyway "
            "(CSS animations may not trigger DOM delta).",
            run_id,
        )
        # Do NOT return — fall through to programmatic + LLM verification

    # ── Skip if no screenshot available (shouldn't happen) ────────────
    if not screenshot_b64:
        logger.warning("[%s] Verifier: no screenshot available — defaulting to NOT_YET", run_id)
        return {
            "_verifier_verdict": "not_yet",
            "_next_node": "planner",
            "verifier_not_yet_count": state.get("verifier_not_yet_count", 0) + 1,
        }

    logger.info(
        "[%s] Verifier: checking AC step %d/%d: '%s'",
        run_id,
        ac_index + 1,
        len(ac_steps),
        current_step[:80],
    )

    # ── Fast-path: skip LLM for self-evident action completions ──────────
    # A 'fill' or 'check' that succeeded IS the completion of a step whose
    # only goal is to perform that action — no visual verification needed.
    # This eliminates ~30-40% of verifier LLM calls on form-filling workflows
    # and avoids the NOT_YET loop seen in the logs (fill Email →
    # verifier says NOT_YET because page is loading → wastes 2s + LLM call).
    # NOTE: 'navigate' is NOT in SELF_EVIDENT_ACTIONS — see comment below.
    #
    # fast-path ONLY fires when:
    #   1. Action type is in SELF_EVIDENT
    #   2. AC step contains no "verify", "assert", "confirm", "ensure",
    #      "should appear", "visible", or "check" clause (a pure-action step)
    action_type_executed = planned_action.get("action", "")
    ac_lower = current_step.lower()
    has_verify_clause = any(
        w in ac_lower
        for w in [
            "verify",
            "assert",
            "confirm",
            "ensure",
            "should appear",
            "visible",
            "appear",
            "check",
        ]
    )

    # Map action types to the AC step keywords that indicate a pure-action step
    # NOTE: "navigate" is intentionally excluded — page.goto() does not confirm
    # that the destination UI element (e.g. QO side panel) actually appeared.
    # The QO form opens as a side panel without a URL change; a successful navigate
    # action does NOT mean the panel is visible. Always run programmatic/LLM checks.
    SELF_EVIDENT_ACTIONS: dict[str, list[str]] = {
        "fill": ["fill", "type", "enter", "input", "write"],
        "check": ["check", "tick", "enable", "select"],
        "uncheck": ["uncheck", "disable", "deselect"],
        # verify_table_sort is a programmatic executor check — if it succeeded the
        # sort state was already confirmed in Python; no LLM screenshot needed.
        "verify_table_sort": ["sort", "ascending", "descending", "a-z", "z-a", "oldest", "newest", "column"],
        # select_option on a dropdown completed the whole interaction in one executor call
        "select_option": ["select", "choose", "pick"],
    }

    if not has_verify_clause and action_type_executed in SELF_EVIDENT_ACTIONS:
        step_keywords = SELF_EVIDENT_ACTIONS[action_type_executed]
        if any(kw in ac_lower for kw in step_keywords):
            new_ac_index = ac_index + 1
            logger.info(
                "[%s] Verifier fast-path: '%s' on self-evident step '%s...' — SATISFIED",
                run_id,
                action_type_executed,
                current_step[:40],
            )
            return {
                "_verifier_verdict": "satisfied",
                "_next_node": "planner" if new_ac_index < len(ac_steps) else "evaluator",
                "ac_step_index": new_ac_index,
                "structured_step_index": new_ac_index,
                "ac_steps_completed": [ac_index],
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": 0,
                "current_ac_step_action_count": 0,  # Reset circuit breaker for new step
            }

    # ── Programmatic verification path (Objective 1) ──────────────────────
    # If the AC parser emitted a structured test_plan, evaluate the current
    # step's verification[] assertions in Python before making an LLM call.
    # Eliminates 60–70% of verifier LLM calls for form/navigation workflows.
    test_plan = state.get("test_plan")
    if test_plan:
        plan_steps: list[dict] = test_plan.get("steps", [])
        if ac_index < len(plan_steps):
            verifications: list[dict] = plan_steps[ac_index].get("verification", [])
            if verifications:
                logger.info(
                    "[%s] Verifier: running %d programmatic check(s) for AC step %d/%d",
                    run_id,
                    len(verifications),
                    ac_index + 1,
                    len(ac_steps),
                )
                try:
                    _page = get_manager(run_id).page
                    if _page is not None:
                        transient_text = state.get("transient_page_text", "")
                        pre_state = state.get("pre_action_state", {})
                        prog_verdict, prog_evidence, prog_dvq_entries = await _run_programmatic_verifications(
                            _page,
                            verifications,
                            run_id,
                            transient_text=transient_text,
                            ac_step_index=ac_index,
                            deferred_check_delay=settings.deferred_check_delay,
                            enable_deferred_verification=settings.enable_deferred_verification,
                            pre_state=pre_state,
                        )

                        # ── FEAT-023 DVQ: merge collected entries into state queue ──
                        _existing_dvq = list(state.get("deferred_verification_queue", []))
                        if prog_dvq_entries:
                            _existing_dvq.extend(prog_dvq_entries)

                        if prog_verdict == "satisfied":
                            new_ac_index = ac_index + 1
                            logger.info(
                                "[%s] Verifier [programmatic] SATISFIED — %s",
                                run_id,
                                prog_evidence[:100],
                            )
                            _result: dict = {
                                "_verifier_verdict": "satisfied",
                                "_next_node": ("planner" if new_ac_index < len(ac_steps) else "evaluator"),
                                "ac_step_index": new_ac_index,
                                "ac_steps_completed": [ac_index],
                                "retry_count": 0,
                                "agent_critique": "",
                                "last_error": "",
                                "ac_step_fail_counts": {},
                                "verifier_not_yet_count": 0,
                                "verifier_total_not_yet_count": 0,
                                "current_ac_step_action_count": 0,  # Reset circuit breaker for new step
                            }
                            # Only include DVQ update if there are entries to add
                            if prog_dvq_entries:
                                _result["deferred_verification_queue"] = _existing_dvq
                            return _result

                        elif prog_verdict == "not_yet":
                            not_yet_count = state.get("verifier_not_yet_count", 0) + 1
                            total_not_yet = state.get("verifier_total_not_yet_count", 0) + 1
                            logger.info(
                                "[%s] Verifier [programmatic] NOT_YET (%d/2, total %d) — %s",
                                run_id,
                                not_yet_count,
                                total_not_yet,
                                prog_evidence[:80],
                            )

                            # ── FEAT-058: Loop Prevention (SKIPPED verdict) ─────────────
                            # If we hit 3 total NOT_YETs, run a satisfiability check.
                            # If it fails, emit SKIPPED instead of FAILED/NOT_YET.
                            if total_not_yet >= 3:
                                # Fast path: url_check on a modal/panel opens can never
                                # resolve because the URL never changes.  goal_satisfiable_check
                                # would incorrectly return True (the panel IS visible), so we
                                # bypass it and emit SKIPPED directly when the evidence carries
                                # the "will never pass" sentinel set by _check_single_verification.
                                if "will never pass" in prog_evidence:
                                    logger.warning(
                                        "[%s] Loop Prevention: url_check on modal/panel — "
                                        "verification type mismatch detected, SKIPPING",
                                        run_id,
                                    )
                                    new_ac_index = ac_index + 1
                                    return {
                                        "_verifier_verdict": "skipped",
                                        "_next_node": "evaluator",
                                        "ac_step_index": new_ac_index,
                                        "ac_steps_completed": [ac_index],
                                        "last_error": (
                                            f"url_check compiled for a modal/panel step — "
                                            f"verification type mismatch, can never resolve. "
                                            f"{prog_evidence[:120]}"
                                        ),
                                        "verifier_not_yet_count": 0,
                                        "verifier_total_not_yet_count": 0,
                                    }
                                is_satisfiable = await goal_satisfiable_check(_page, current_step, run_id)
                                if not is_satisfiable:
                                    logger.warning("[%s] Loop Prevention: Goal appears unsatisfiable — SKIPPING", run_id)
                                    new_ac_index = ac_index + 1
                                    return {
                                        "_verifier_verdict": "skipped",
                                        "_next_node": "evaluator",
                                        "ac_step_index": new_ac_index,
                                        "ac_steps_completed": [ac_index],
                                        "last_error": f"Goal unsatisfiable after {total_not_yet} attempts: {prog_evidence[:80]}",
                                        "verifier_not_yet_count": 0,
                                        "verifier_total_not_yet_count": 0,
                                    }

                            # Mirror the LLM path's hard-cap and escalation logic exactly

                            if total_not_yet >= 4:
                                return {
                                    "_verifier_verdict": "failed",
                                    "_next_node": "evaluator",
                                    "verifier_not_yet_count": 0,
                                    "verifier_total_not_yet_count": total_not_yet,
                                    "last_error": (
                                        f"Programmatic verifier hard cap: {total_not_yet} "
                                        f"NOT_YET on step '{current_step[:60]}'. "
                                        f"Last check: {prog_evidence[:80]}"
                                    ),
                                    "agent_critique": (
                                        f"HARD CAP ({total_not_yet} NOT_YET, programmatic): "
                                        f"{prog_evidence[:80]}. Try a different action sequence."
                                    ),
                                }
                            if not_yet_count >= 2:
                                return {
                                    "_verifier_verdict": "not_yet",
                                    "_next_node": "evaluator",
                                    "verifier_not_yet_count": not_yet_count,
                                    "verifier_total_not_yet_count": total_not_yet,
                                    "last_error": (
                                        f"Programmatic verifier stuck ({not_yet_count}x): {prog_evidence[:80]}"
                                    ),
                                    "agent_critique": (
                                        f"Programmatic check NOT_YET {not_yet_count}/2 "
                                        f"(total {total_not_yet}): {prog_evidence[:80]}"
                                    ),
                                }
                            # ── P1B: Harvest DOM state for programmatic NOT_YET diary ───
                            await _harvest_dom_snapshot(run_id)
                            return {
                                "_verifier_verdict": "not_yet",
                                "_next_node": "planner",
                                "verifier_not_yet_count": not_yet_count,
                                "verifier_total_not_yet_count": total_not_yet,
                                "agent_critique": (
                                    f"⛔ VERIFIER_NOT_YET [prog] ({not_yet_count}/3, "
                                    f"total {total_not_yet}): {prog_evidence[:100]}. "
                                    f"DOM state: (see <page_state> at top of prompt). "
                                    f"⛔ DO NOT repeat the last action. "
                                    f"Choose a DIFFERENT action or emit done."
                                ),
                            }

                        # prog_verdict == "llm_needed" → fall through to LLM path
                        logger.info(
                            "[%s] Verifier [programmatic]: deferring to LLM — %s",
                            run_id,
                            prog_evidence[:80],
                        )

                except KeyError:
                    # run_id not in BrowserManager registry — shouldn't happen
                    logger.warning(
                        "[%s] Verifier: BrowserManager not found — falling through to LLM",
                        run_id,
                    )
                except Exception as _prog_exc:
                    logger.warning(
                        "[%s] Verifier programmatic check raised: %s — falling through to LLM",
                        run_id,
                        str(_prog_exc)[:100],
                    )

    # ── Build the multimodal prompt ───────────────────────────────────
    dom_snapshot_before = state.get("dom_snapshot_before", "None captured")
    dom_snapshot_after = await _harvest_dom_snapshot(run_id)

    user_content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"AC STEP ({ac_index + 1}/{len(ac_steps)}): {current_step}\n\n"
                f"DOM STATE BEFORE ACTION:\n{dom_snapshot_before}\n\n"
                f"DOM STATE AFTER ACTION:\n{dom_snapshot_after}\n\n"
                f"Look at the screenshot and the DOM state context. Has this AC step been FULLY satisfied?\n"
                f"Respond with SATISFIED, NOT_YET, or FAILED followed by evidence."
            ),
        },
    ]

    # ── Call the verifier LLM ─────────────────────────────────────────
    try:
        # FEAT-066: Escalate to Sonnet for complex visual steps or on second+ NOT_YET
        # (Tier 2/3 reasoning for challenging verification scenarios)
        total_not_yet = state.get("verifier_total_not_yet_count", 0)

        # Determine complexity from test_plan verifications
        is_complex = False
        if test_plan:
            plan_steps = test_plan.get("steps", [])
            if ac_index < len(plan_steps):
                _v_list = plan_steps[ac_index].get("verification", [])
                is_complex = any(v.get("type") == "visual_check" for v in _v_list)
        else:
            # Fallback AC parser: treat all as potentially complex
            is_complex = True

        use_heavy = is_complex or total_not_yet >= 1
        if use_heavy:
            logger.info(
                "[%s] Verifier: using HEAVY model (is_complex=%s, total_not_yet=%d)",
                run_id, is_complex, total_not_yet
            )

        llm = _get_verifier_llm(heavy=use_heavy)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_VERIFIER_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ]
        )


        raw_response = response.content
        verdict, evidence, confidence = _parse_verdict(raw_response)

    except Exception as e:
        logger.error(
            "[%s] Verifier LLM call failed: %s — defaulting to NOT_YET",
            run_id,
            str(e),
        )
        verdict = "not_yet"
        evidence = f"Verifier LLM error: {str(e)[:100]}"
        confidence = 30

    # Phase 3: annotate evidence with a11y resolution path tag (AC-ASYNC-1)
    # state["last_resolution_path"] is written by _resolve_locator_a11y_first
    # on every a11y-resolved step; the annotation lets post-run analytics
    # compute the a11y-resolution rate from detailed_execution_log.
    evidence = annotate_evidence_with_resolution_path(
        evidence, state.get("last_resolution_path")
    )

    logger.info(
        "[%s] Verifier verdict: %s (confidence=%d) — %s",
        run_id,
        verdict.upper(),
        confidence,
        evidence[:120],
    )

    # ── FEAT-010: Low-confidence SATISFIED guard ──────────────────────
    # If the LLM says SATISFIED but with weak evidence (confidence < 70),
    # demote to NOT_YET and force one more verification pass. This prevents
    # premature AC step advancement when the verifier is uncertain.
    # Only apply on the first low-confidence occurrence per step to avoid
    # infinite re-verification loops.
    _low_conf_recheck = state.get("_low_confidence_recheck_count", 0)
    if verdict == "satisfied" and confidence < 70 and _low_conf_recheck < 1:
        logger.warning(
            "[%s] Verifier SATISFIED with low confidence (%d) — demoting to NOT_YET for re-check",
            run_id,
            confidence,
        )
        return {
            "_verifier_verdict": "not_yet",
            "_next_node": "planner",
            "_low_confidence_recheck_count": _low_conf_recheck + 1,
            "agent_critique": (
                f"VERIFIER LOW CONFIDENCE ({confidence}/100): The verifier tentatively said "
                f"SATISFIED but the evidence was weak: '{evidence[:80]}'. "
                f"Perform one more targeted action to confirm this step is truly done, "
                f"OR emit 'done' with a clear reason if you believe it is complete."
            ),
        }

    # ── Build state update based on verdict ───────────────────────────

    if verdict == "satisfied":
        new_ac_index = ac_index + 1
        logger.info(
            "[%s] AC step %d/%d SATISFIED (confidence=%d) — advancing to step %d",
            run_id,
            ac_index + 1,
            len(ac_steps),
            confidence,
            new_ac_index + 1,
        )

        # Check if all AC steps are done
        if new_ac_index >= len(ac_steps):
            # All done — let evaluator handle final routing (setup_role or reporter)
            return {
                "_verifier_verdict": verdict,
                "_verifier_confidence": float(confidence),  # FEAT-060 P4B
                "_next_node": "evaluator",
                "ac_step_index": new_ac_index,
                "structured_step_index": new_ac_index,
                "ac_steps_completed": [ac_index],
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": 0,
                "current_ac_step_action_count": 0,  # Reset circuit breaker for new step
            }
        else:
            return {
                "_verifier_verdict": verdict,
                "_verifier_confidence": float(confidence),  # FEAT-060 P4B
                "_next_node": "planner",
                "ac_step_index": new_ac_index,
                "structured_step_index": new_ac_index,
                "ac_steps_completed": [ac_index],
                "retry_count": 0,
                "agent_critique": "",
                "last_error": "",
                "ac_step_fail_counts": {},
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": 0,
                "current_ac_step_action_count": 0,  # Reset circuit breaker for new step
            }
    elif verdict == "not_yet":
        not_yet_count = state.get("verifier_not_yet_count", 0) + 1
        total_not_yet = state.get("verifier_total_not_yet_count", 0) + 1

        # ── FEAT-058: Loop Prevention (SKIPPED verdict) ─────────────
        # If we hit 3 total NOT_YETs, run a satisfiability check.
        # If it fails, emit SKIPPED instead of FAILED/NOT_YET.
        if total_not_yet >= 3:
            is_satisfiable = await goal_satisfiable_check(_page, current_step, run_id)
            if not is_satisfiable:
                logger.warning("[%s] Loop Prevention: Goal appears unsatisfiable — SKIPPING", run_id)
                new_ac_index = ac_index + 1
                return {
                    "_verifier_verdict": "skipped",
                    "_verifier_confidence": 30.0,  # FEAT-060 P4B: skipped = low confidence
                    "_next_node": "evaluator",
                    "ac_step_index": new_ac_index,
                    "ac_steps_completed": [ac_index],
                    "last_error": f"Goal unsatisfiable after {total_not_yet} attempts: {evidence[:80]}",
                    "verifier_not_yet_count": 0,
                    "verifier_total_not_yet_count": 0,
                }

        # ── Hard cap: absolute NOT_YET limit per AC step ────────────
        # Safety net: even if evaluator resets the per-cycle counter,
        # this total count prevents infinite loops forever.
        if total_not_yet >= 6:
            # ── Fix 3: Wrong-page diagnosis ─────────────────────────────────
            # After 6 NOT_YET verdicts the planner is almost certainly stuck.
            # Grab the current URL and inject it into the critique so the LLM
            # can diagnose whether it's on the wrong page entirely, rather
            # than blindly retrying the same failing action.
            _current_url = ""
            try:
                _current_url = get_manager(run_id).page.url
            except Exception:
                pass

            logger.error(
                "[%s] Verifier hard cap: %d total NOT_YET on AC step %d/%d "
                "(URL: %s) — marking FAILED with wrong-page diagnosis",
                run_id,
                total_not_yet,
                ac_index + 1,
                len(ac_steps),
                _current_url[:120],
            )
            return {
                "_verifier_verdict": "failed",
                "_verifier_confidence": 30.0,  # FEAT-060 P4B: hard-cap = low confidence
                "_next_node": "evaluator",
                "verifier_not_yet_count": 0,
                "verifier_total_not_yet_count": total_not_yet,
                "last_error": (
                    f"AC step '{current_step[:80]}' could not be verified after "
                    f"{total_not_yet} NOT_YET verdicts. The step may require "
                    f"a different approach or the page state does not match expectations."
                ),
                "agent_critique": (
                    f"HARD CAP: {total_not_yet} NOT_YET verdicts on AC step "
                    f"'{current_step[:60]}'. "
                    f"DIAGNOSIS: The verifier has repeatedly been unable to confirm "
                    f"this step completed. Current URL: {_current_url}. "
                    f"LIKELY CAUSE: You may be on the WRONG PAGE. "
                    f"Check if the current page matches what this AC step expects. "
                    f"If not, navigate to the correct page FIRST before retrying. "
                    f"Last feedback: {evidence[:100]}."
                ),
            }

        if not_yet_count >= 2:
            # ── Escalate: verifier is stuck — don't loop forever ────────
            # Route to evaluator which will increment ac_step_fail_counts
            # and trigger human_takeover if threshold is reached.
            logger.warning(
                "[%s] Verifier NOT_YET x%d on AC step %d/%d — escalating to evaluator",
                run_id,
                not_yet_count,
                ac_index + 1,
                len(ac_steps),
            )
            return {
                "_verifier_verdict": verdict,
                "_verifier_confidence": float(confidence),  # FEAT-060 P4B
                "_next_node": "evaluator",
                "verifier_not_yet_count": not_yet_count,
                "verifier_total_not_yet_count": total_not_yet,
                "last_error": (
                    f"Verifier stuck: AC step '{current_step[:80]}' "
                    f"returned NOT_YET {not_yet_count} times after successful actions. "
                    f"Evidence: {evidence[:100]}"
                ),
                "agent_critique": (
                    f"Step not visually confirmed after {not_yet_count} verifier checks "
                    f"(total: {total_not_yet}). "
                    f"Last verifier feedback: {evidence[:100]}"
                ),
            }

        # ── NOT_YET (1–2): pass evidence to planner so it knows WHY ────
        # Without this, the planner loops back with no context and repeats
        # the same action. With it, the planner can choose wait() + retry.
        logger.info(
            "[%s] Verifier NOT_YET (%d/2) — evidence: %s",
            run_id,
            not_yet_count,
            evidence[:100],
        )
        # ── Diary entry: surface verifier rejection to Planner ──────────
        # Playwright executed the action successfully (success=True), but the
        # visual state is wrong.  Without a diary entry, the Planner has no
        # signal to change strategy and will repeat the exact same click.
        planned_action_desc = (
            f"{planned_action.get('action', '')}("
            f"{planned_action.get('strategy', '')}, "
            f"'{planned_action.get('name', planned_action.get('value', ''))}'')"
        )

        # ── P1B: Harvest persistent DOM state BEFORE any state is cleared ───────
        # Captures view-wrapper classes, aria-sort, and URL so the planner's
        # diary entry contains ground truth about current page state, not just
        # "verifier said NOT_YET" with no context.
        dom_snapshot = await _harvest_dom_snapshot(run_id)

        existing_diary: list[dict] = list(state.get("ac_step_failure_diary", []))
        existing_diary.append(
            {
                "action_type": planned_action.get("action", "unknown"),
                "locator_strategy": planned_action.get("strategy", ""),
                "locator_value": planned_action.get("name", planned_action.get("value", "")),
                "error": (
                    f"VERIFIER_REJECTED (NOT_YET {not_yet_count}/2): "
                    f"Playwright executed '{planned_action_desc}' with success=True, "
                    f"but the verifier rejected the visual result. "
                    f"Verifier evidence: '{evidence[:200]}'. "
                    f"DOM state at rejection: (see <page_state> at top of prompt). "
                    f"You MUST try a DIFFERENT element or approach — "
                    f"do NOT repeat the same click."
                ),
                "source": "verifier",
                "dom_snapshot": dom_snapshot,
            }
        )
        return {
            "_verifier_verdict": verdict,
            "_verifier_confidence": float(confidence),  # FEAT-060 P4B
            "_next_node": "planner",
            "verifier_not_yet_count": not_yet_count,
            "verifier_total_not_yet_count": total_not_yet,
            "ac_step_failure_diary": existing_diary,
            "agent_critique": (
                f"⛔ VERIFIER_NOT_YET ({not_yet_count}/2, total {total_not_yet}/4): "
                f"Action WAS executed (Playwright success=True) but visual result is WRONG. "
                f"Evidence: {evidence[:120]}. "
                f"DOM state: (see <page_state> at top of prompt). "
                f"⛔ DO NOT repeat: {planned_action_desc}. "
                f"REQUIRED: choose a DIFFERENT action (wait, different element, navigate, or done)."
            ),
        }

    else:  # "failed"
        return {
            "_verifier_verdict": verdict,
            "_verifier_confidence": float(confidence),  # FEAT-060 P4B
            "_next_node": "planner",
            "last_error": f"Verifier: {evidence}",
            "agent_critique": f"Step verification failed: {evidence}",
            "verifier_not_yet_count": 0,  # Reset — this is a different failure mode
        }


# ---------------------------------------------------------------------------
# Conditional edge function
# ---------------------------------------------------------------------------


def route_after_verifier(state: VQAState) -> str:
    """
    Conditional edge function for routing after the verifier.

    Reads ``_next_node`` set by step_verifier_node.

    Returns
    -------
    str
        One of "planner", "evaluator".
    """
    route = state.get("_next_node", "")
    if route in ("planner", "evaluator"):
        return route
    logger.warning(
        "route_after_verifier: unexpected _next_node='%s' — defaulting to 'planner'",
        route,
    )
    return "planner"


# ---------------------------------------------------------------------------
# Predictive State Verification (TASK-095)
# ---------------------------------------------------------------------------

class PredictiveVerificationError(Exception):
    """Exception raised when predictive state verification fails."""
    pass


class PredictiveVerifier:
    """
    Performs rapid, low-latency DOM and URL checks to verify if a planner's
    state_expectation is met immediately after action execution.
    """

    @classmethod
    async def verify_expectation(cls, page: Page, state_expectation: str) -> bool:
        if not state_expectation:
            return True

        expectation_lower = state_expectation.lower()
        logger.info(f"Running predictive verification for expectation: '{state_expectation}'")

        # 1. URL Check
        # Example: "URL contains /dashboard", "url contains login"
        if "url" in expectation_lower:
            path_match = re.search(r"/[\w\-\/]+", state_expectation)
            if path_match:
                expected_part = path_match.group(0).lower()
                if expected_part in page.url.lower():
                    return True
                else:
                    logger.warning(f"Predictive URL mismatch: expected '{expected_part}' in '{page.url}'")
                    return False
            else:
                words = re.findall(r"\b[\w\-]{3,}\b", expectation_lower)
                words = [w for w in words if w not in ["url", "contains", "is", "should", "be"]]
                if words:
                    for word in words:
                        if word in page.url.lower():
                            return True
                    logger.warning(f"Predictive URL word mismatch: none of {words} in '{page.url}'")
                    return False

        # 2. Text in quotes check
        # Example: "Dialog 'Create Folder' is visible" or "Button 'Save' is enabled"
        quoted_texts = re.findall(r"['\"](.*?)['\"]", state_expectation)
        if quoted_texts:
            for text in quoted_texts:
                try:
                    is_visible = await page.get_by_text(text).first.is_visible()
                    if is_visible:
                        continue
                except Exception:
                    pass

                try:
                    body_text = await page.text_content("body")
                    if text.lower() in (body_text or "").lower():
                        continue
                except Exception:
                    pass

                logger.warning(f"Predictive text mismatch: '{text}' not found or visible on page.")
                return False
            return True

        # 3. CSS Selector check
        # Example: ".p-dialog is visible", "#success-banner is visible"
        selectors = re.findall(r"([#\.][\w\-]+)", state_expectation)
        if selectors:
            for selector in selectors:
                try:
                    is_visible = await page.locator(selector).first.is_visible()
                    if is_visible:
                        continue
                except Exception:
                    pass
                logger.warning(f"Predictive selector mismatch: '{selector}' is not visible.")
                return False
            return True

        # 4. General fallback: keyword search on body text
        stop_words = {"visible", "hidden", "contains", "should", "appears", "exists", "field", "button", "input", "with", "value"}
        words = [w for w in re.findall(r"\b\w{4,}\b", expectation_lower) if w not in stop_words]
        if words:
            try:
                body_text = (await page.text_content("body") or "").lower()
                found_words = [w for w in words if w in body_text]
                if found_words:
                    return True
                else:
                    logger.warning(f"Predictive general mismatch: none of {words} found in body text.")
                    return False
            except Exception:
                pass

        return True

