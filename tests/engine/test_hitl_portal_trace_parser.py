"""
tests/engine/test_hitl_portal_trace_parser.py

Unit tests for Phase 2: HITL trace parser portal action encoding.

Tests cover:
- _extract_selector_from_params: portal CSS pattern detection produces
  (selector, kind, container_selector) with container_selector non-None
  for known portal class patterns (AC-VERIFY-3).
- _extract_selector_from_params: non-portal selectors return container_selector=None
  (AC-VERIFY-5 regression — non-portal path unchanged).
- _extract_selector_from_params: all priority levels (role, label, text, css) handle
  the new third return element correctly.
- ExtractedAction: accepts container_selector field (new optional field).
- _actions_to_recipe_steps: portal-scoped actions emit container_selector in YAML
  step dict (AC-VERIFY-3).
- _actions_to_recipe_steps: non-portal actions produce no container_selector key
  (AC-VERIFY-5).
- parse_trace (integration): portal-scoped CSS selector in trace → YAML step with
  container_selector (end-to-end through the trace zip path).
- Portal CSS pattern coverage: all known portal class patterns covered.

These tests execute entirely in Python — no Playwright browser required. The
trace-zip integration test builds a minimal in-memory zip and exercises the full
parse_trace() code path.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from backend.engine.hitl_trace_parser import (
    ExtractedAction,
    TraceParserResult,
    _actions_to_recipe_steps,
    _extract_selector_from_params,
    parse_trace,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal trace zip with a single click action
# ---------------------------------------------------------------------------

def _make_trace_zip(selector: str) -> bytes:
    """
    Build a minimal Playwright trace .zip in memory.

    The zip contains a single trace.trace NDJSON with a successful 'click'
    action using the given selector string.
    """
    call_id = "call-001"
    before_event = json.dumps({
        "type": "before",
        "callId": call_id,
        "class": "Frame",
        "method": "click",
        "params": {"selector": selector},
        "startTime": 1000,
    })
    after_event = json.dumps({
        "type": "after",
        "callId": call_id,
    })
    ndjson = "\n".join([before_event, after_event])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("trace.trace", ndjson)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Constants — known portal CSS patterns (from architecture doc + algorithm doc)
# ---------------------------------------------------------------------------

KNOWN_PORTAL_SELECTORS = [
    ".p-select-overlay",
    ".p-dropdown-panel",
    ".p-autocomplete-panel",
    ".p-tieredmenu",
    ".p-menu",
    ".p-popover",
    ".po-sorting-dropdown-panel",
    ".sort-panel",
    # Variants that embed the class within a longer CSS path
    "html > body > div.p-select-overlay > div > ul > li:nth-child(3)",
    "html > body > div.p-dropdown-panel > div > ul > li",
    "html > body > div.p-autocomplete-panel .p-autocomplete-item",
    "html > body > div.po-sorting-dropdown-panel > ul > li",
    # p-dialog is a portal (modal) per the architecture doc
    ".p-dialog",
    "html > body > div.p-dialog-mask > div.p-dialog",
    # cdk-overlay-container wraps PrimeNG portals
    "html > body > div.cdk-overlay-container > div.p-select-overlay > ul > li",
]

NON_PORTAL_SELECTORS = [
    "button.submit-btn",
    "#header-sort-drop-down",
    ".app-root > div > form > input",
    "html > body > div.app-root > main > section > article > button",
    ".p-button",        # p-button is NOT a portal (it's inline)
    ".p-inputtext",     # inline input, not a portal
    "[data-testid='submit']",
]


# ===========================================================================
# 1. _extract_selector_from_params — portal detection
# ===========================================================================


class TestExtractSelectorPortalDetection:
    """
    _extract_selector_from_params must return a 3-tuple (selector, kind,
    container_selector) when the raw CSS selector indicates a portal container.

    Architecture doc §4 (Implementation Guideline #4):
      extend _extract_selector_from_params to return a third element
      container_selector when the raw CSS matches a portal class pattern
      (.p-* or .po-* with overlay/panel/menu/dialog suffix).
      Non-portal selectors produce container_selector=None.
    """

    def test_bare_portal_class_returns_container_selector(self):
        """'.p-select-overlay' → container_selector='.p-select-overlay'."""
        params = {"selector": ".p-select-overlay"}
        selector, kind, container_selector = _extract_selector_from_params(params)
        assert container_selector == ".p-select-overlay"
        assert kind == "css"

    def test_portal_class_in_css_path_returns_container_selector(self):
        """Full CSS path through a portal container extracts the container class."""
        css_path = "html > body > div.p-select-overlay > div > ul > li:nth-child(3)"
        params = {"selector": css_path}
        selector, kind, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None
        assert ".p-select-overlay" in container_selector

    def test_dropdown_panel_portal_detected(self):
        params = {"selector": "html > body > div.p-dropdown-panel > ul > li"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None
        assert "p-dropdown-panel" in container_selector

    def test_autocomplete_panel_portal_detected(self):
        params = {"selector": ".p-autocomplete-panel"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_tieredmenu_portal_detected(self):
        params = {"selector": ".p-tieredmenu"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_p_menu_portal_detected(self):
        params = {"selector": ".p-menu"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_po_sorting_dropdown_panel_portal_detected(self):
        params = {"selector": ".po-sorting-dropdown-panel"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_p_dialog_portal_detected(self):
        """Modal dialogs are portals per the architecture doc."""
        params = {"selector": ".p-dialog"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_p_dialog_in_path_detected(self):
        params = {"selector": "html > body > div.p-dialog-mask > div.p-dialog > div"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_cdk_overlay_container_path_detected(self):
        """Portal inside cdk-overlay-container wrapper is still detected."""
        css = "html > body > div.cdk-overlay-container > div.p-select-overlay > ul > li"
        params = {"selector": css}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None

    def test_container_selector_has_leading_dot(self):
        """Returned container_selector must start with '.' for page.locator()."""
        params = {"selector": ".p-select-overlay"}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None
        assert container_selector.startswith(".")

    @pytest.mark.parametrize("portal_css", [
        ".p-select-overlay",
        ".p-dropdown-panel",
        ".p-autocomplete-panel",
        ".p-tieredmenu",
        ".p-menu",
        ".p-dialog",
        ".po-sorting-dropdown-panel",
        "html > body > div.p-select-overlay > ul > li",
        "html > body > div.p-dropdown-panel .p-dropdown-item",
    ])
    def test_all_known_portal_patterns_detected(self, portal_css):  # noqa: D401
        """Parametrized coverage of all known portal CSS patterns (AC-VERIFY-1)."""
        params = {"selector": portal_css}
        _, _, container_selector = _extract_selector_from_params(params)
        assert container_selector is not None, (
            f"Expected portal detection for {portal_css!r} but got container_selector=None"
        )


# ===========================================================================
# 2. _extract_selector_from_params — non-portal regression (AC-VERIFY-5)
# ===========================================================================


class TestExtractSelectorNonPortalRegression:
    """
    Non-portal selectors must return container_selector=None so that the
    existing extraction logic and YAML output are byte-identical to pre-feature.
    """

    @pytest.mark.parametrize("non_portal_css", NON_PORTAL_SELECTORS)
    def test_non_portal_selectors_return_none_container(self, non_portal_css):
        params = {"selector": non_portal_css}
        result = _extract_selector_from_params(params)
        assert len(result) == 3, "Must always return 3-tuple"
        _, _, container_selector = result
        assert container_selector is None, (
            f"Non-portal selector {non_portal_css!r} incorrectly detected as portal"
        )

    def test_role_based_selector_no_container(self):
        """role+name priority path still returns 3-tuple with None container."""
        params = {"role": "button", "name": "Submit"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_label_selector_no_container(self):
        params = {"label": "Email address"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_text_selector_no_container(self):
        params = {"text": "Submit"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_text_prefix_selector_no_container(self):
        """'text=Submit' prefix still returns None container."""
        params = {"selector": "text=Submit"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_role_prefix_selector_no_container(self):
        params = {"selector": "role=button[name='Ok']"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_empty_selector_no_container(self):
        params = {}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None

    def test_css_prefix_stripped_no_container(self):
        """css=button.submit remains non-portal — container_selector=None."""
        params = {"selector": "css=button.submit-btn"}
        result = _extract_selector_from_params(params)
        assert len(result) == 3
        _, _, container_selector = result
        assert container_selector is None


# ===========================================================================
# 3. ExtractedAction — container_selector field
# ===========================================================================


class TestExtractedActionContainerSelector:
    """ExtractedAction now has an optional container_selector field."""

    def test_default_container_selector_is_none(self):
        """Non-portal actions default to container_selector=None."""
        action = ExtractedAction(
            event_type="click",
            selector="Submit",
            selector_kind="text",
            value=None,
            aria_label=None,
            timestamp_ms=0,
            call_id="call-001",
        )
        assert action.container_selector is None

    def test_portal_action_stores_container_selector(self):
        """Portal actions can carry a non-None container_selector."""
        action = ExtractedAction(
            event_type="click",
            selector="Due Date A-Z",
            selector_kind="text",
            value=None,
            aria_label=None,
            timestamp_ms=100,
            call_id="call-002",
            container_selector=".p-select-overlay",
        )
        assert action.container_selector == ".p-select-overlay"


# ===========================================================================
# 4. _actions_to_recipe_steps — portal step encoding (AC-VERIFY-3)
# ===========================================================================


class TestActionsToRecipeStepsPortal:
    """
    _actions_to_recipe_steps must emit container_selector in the YAML step dict
    for portal-scoped click actions (AC-VERIFY-3).
    """

    def _portal_action(self, selector: str = "Due Date A-Z",
                       container: str = ".p-select-overlay") -> ExtractedAction:
        return ExtractedAction(
            event_type="click",
            selector=selector,
            selector_kind="text",
            value=None,
            aria_label=None,
            timestamp_ms=100,
            call_id="call-portal",
            container_selector=container,
        )

    def _non_portal_action(self, selector: str = "Submit") -> ExtractedAction:
        return ExtractedAction(
            event_type="click",
            selector=selector,
            selector_kind="text",
            value=None,
            aria_label=None,
            timestamp_ms=0,
            call_id="call-np",
        )

    def test_portal_step_has_container_selector_key(self):
        """Portal-scoped action step includes container_selector."""
        steps = _actions_to_recipe_steps([self._portal_action()])
        assert len(steps) == 1
        assert "container_selector" in steps[0]
        assert steps[0]["container_selector"] == ".p-select-overlay"

    def test_portal_step_action_is_click(self):
        """Portal steps use 'click' action (Literal-compatible; AC-VERIFY-3)."""
        steps = _actions_to_recipe_steps([self._portal_action()])
        assert steps[0]["action"] == "click"

    def test_portal_step_strategy_is_get_by_text(self):
        """Portal steps use get_by_text strategy."""
        steps = _actions_to_recipe_steps([self._portal_action()])
        assert steps[0]["strategy"] == "get_by_text"

    def test_portal_step_selector_is_target_text(self):
        """Selector in portal step is the option text."""
        steps = _actions_to_recipe_steps([self._portal_action(selector="Due Date A-Z")])
        assert steps[0]["selector"] == "Due Date A-Z"

    def test_non_portal_step_no_container_selector(self):
        """Non-portal actions MUST NOT have container_selector key (AC-VERIFY-5)."""
        steps = _actions_to_recipe_steps([self._non_portal_action()])
        assert "container_selector" not in steps[0]

    def test_mixed_sequence_only_portal_step_has_container(self):
        """Mixed portal + non-portal sequence: only portal step gets container_selector."""
        actions = [self._non_portal_action(), self._portal_action(), self._non_portal_action()]
        steps = _actions_to_recipe_steps(actions)
        assert "container_selector" not in steps[0]
        assert "container_selector" in steps[1]
        assert "container_selector" not in steps[2]

    def test_dropdown_panel_container_selector(self):
        """Different portal classes propagate correctly."""
        action = self._portal_action(container=".p-dropdown-panel")
        steps = _actions_to_recipe_steps([action])
        assert steps[0]["container_selector"] == ".p-dropdown-panel"

    def test_yaml_serializable(self):
        """Step dict with container_selector is YAML-serializable (no type errors)."""
        steps = _actions_to_recipe_steps([self._portal_action()])
        dumped = yaml.dump(steps, default_flow_style=False)
        reloaded = yaml.safe_load(dumped)
        assert reloaded[0]["container_selector"] == ".p-select-overlay"


# ===========================================================================
# 5. parse_trace integration — portal CSS → YAML step with container_selector
# ===========================================================================


class TestParseTracePortalIntegration:
    """
    Integration test: a trace zip containing a click on a portal CSS selector
    produces a YAML with a container_selector step (AC-VERIFY-3 end-to-end).
    """

    @pytest.fixture
    def tmp_output_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "generated"

    def _run_parse(self, selector: str, tmp_output_dir: Path) -> TraceParserResult:
        import asyncio
        zip_bytes = _make_trace_zip(selector)
        zip_path = tmp_output_dir.parent / "test.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(zip_bytes)

        # Use a new dedicated event loop so we don't interfere with any
        # loop state that other tests (e.g. Phase-1 tests using the legacy
        # get_event_loop() API) may rely on.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                parse_trace(
                    zip_path=zip_path,
                    ac_step_goal="Sort orders by due date",
                    run_id="run-test-001",
                    takeover_seq=0,
                    output_dir=tmp_output_dir,
                )
            )
        finally:
            loop.close()

    def test_portal_css_trace_produces_container_selector_in_yaml(self, tmp_output_dir):
        """End-to-end: portal CSS in trace → YAML step with container_selector."""
        result = self._run_parse(
            "html > body > div.p-select-overlay > ul > li",
            tmp_output_dir,
        )
        assert result.ok, f"parse_trace failed: {result.failure_detail}"
        assert result.recipe_yaml_path is not None
        yaml_text = result.recipe_yaml_path.read_text()
        recipe = yaml.safe_load(yaml_text)
        steps = recipe["steps"]
        assert len(steps) >= 1
        portal_steps = [s for s in steps if "container_selector" in s]
        assert portal_steps, (
            f"No step with container_selector found in YAML. Steps: {steps}"
        )
        assert "p-select-overlay" in portal_steps[0]["container_selector"]

    def test_non_portal_css_trace_no_container_selector_in_yaml(self, tmp_output_dir):
        """Non-portal CSS in trace → YAML step without container_selector (AC-VERIFY-5)."""
        result = self._run_parse("button.submit-btn", tmp_output_dir)
        assert result.ok
        yaml_text = result.recipe_yaml_path.read_text()
        recipe = yaml.safe_load(yaml_text)
        steps = recipe["steps"]
        for step in steps:
            assert "container_selector" not in step, (
                f"Non-portal step should not have container_selector: {step}"
            )

    def test_portal_step_action_is_click_in_yaml(self, tmp_output_dir):
        """Portal step in YAML uses 'click' action (Literal-compatible)."""
        result = self._run_parse(".p-dropdown-panel", tmp_output_dir)
        assert result.ok
        recipe = yaml.safe_load(result.recipe_yaml_path.read_text())
        portal_steps = [s for s in recipe["steps"] if "container_selector" in s]
        assert portal_steps
        assert portal_steps[0]["action"] == "click"

    def test_extracted_action_has_container_selector_field(self, tmp_output_dir):
        """parse_trace result includes ExtractedAction with container_selector."""
        result = self._run_parse(".p-select-overlay", tmp_output_dir)
        assert result.ok
        portal_actions = [a for a in result.actions if a.container_selector is not None]
        assert portal_actions, "Expected at least one ExtractedAction with container_selector"
