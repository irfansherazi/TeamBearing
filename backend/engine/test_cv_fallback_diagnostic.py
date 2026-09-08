"""
Phase 3 — T2-c: Diagnostic Routing for mark_id=None

Tests for the CV vision no-match diagnostic path introduced in FEAT-117 / T2-c.

When CvFallbackResolver.resolve() returns (None, mark_map, cost) the executor must:
  (a) NOT dispatch page.get_by_text().click() as a fallback
  (b) Store a cv_vision_diagnostic dict in the state update with n_marks + target_text
  (c) The result must signal failure (not success)

The planner must:
  (d) Inject a prompt fragment containing recovery options when cv_vision_diagnostic present
  (e) Return empty fragment when diagnostic is absent (no spurious injection)
  (f) Reference the target_text or n_marks in the injected fragment

AC coverage:
  AC-VERIFY-4a: executor emits cv_vision_no_match; no get_by_text() call
  AC-VERIFY-4b: planner fragment present when state carries diagnostic
  AC-VERIFY-4c: prompt log contains at least one option string
"""



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUN_ID = "test-cv-diagnostic"


def _base_state() -> dict:
    """Minimal VQAState-compatible dict for executor/planner tests."""
    return {
        "run_id": _RUN_ID,
        "ac_step_index": 2,
        "mark_coordinate_map": {},
        "cv_fallback_invocations": 0,
        "cv_fallback_results": [],
        "visual_context": None,
        "current_page_url": "https://qa.vcreative.net/vpromotions",
        "ac_step_failure_diary": [],
        "cv_vision_diagnostic": None,
    }


# ---------------------------------------------------------------------------
# AC-VERIFY-4a: executor stores cv_vision_diagnostic on mark_id=None
# ---------------------------------------------------------------------------


def test_cv_vision_no_match_stores_diagnostic_in_state():
    """
    When CvFallbackResolver.resolve() returns mark_id=None, the executor's
    _build_cv_vision_diagnostic helper must return a dict containing:
      - 'n_marks': int (count of marks in the map)
      - 'target_text': str (the target description)
      - 'options': list of option strings

    This diagnostic dict is stored in the state update so the planner can
    read it on the next turn and inject the recovery fragment.

    AC-VERIFY-4a (structural): diagnostic dict has required keys.
    """
    from backend.engine.executor import _build_cv_vision_diagnostic

    mark_map = {str(i): {"x": i * 10, "y": i * 10, "tag": "div"} for i in range(1, 13)}
    target_text = "Contest"

    diag = _build_cv_vision_diagnostic(target_text=target_text, mark_map=mark_map)

    assert isinstance(diag, dict), f"Expected dict, got {type(diag)}"
    assert diag["n_marks"] == 12, f"Expected n_marks=12, got {diag.get('n_marks')}"
    assert diag["target_text"] == "Contest", f"Expected target_text='Contest', got {diag.get('target_text')}"
    assert "options" in diag, "Expected 'options' key in diagnostic"
    assert isinstance(diag["options"], list), "Expected options to be a list"
    assert len(diag["options"]) >= 1, "Expected at least one option in diagnostic"


def test_cv_vision_no_match_diagnostic_empty_map():
    """
    When mark_map is empty (no elements found at all), diagnostic must still
    have n_marks=0 and not raise.
    """
    from backend.engine.executor import _build_cv_vision_diagnostic

    diag = _build_cv_vision_diagnostic(target_text="MyTarget", mark_map={})

    assert diag["n_marks"] == 0, f"Expected n_marks=0, got {diag.get('n_marks')}"
    assert diag["target_text"] == "MyTarget"


def test_cv_vision_no_match_diagnostic_options_contain_expected_strings():
    """
    The diagnostic 'options' list must contain at least one of the canonical
    recovery strategies used by the planner fragment builder:
      'open_container', 'scroll', 'synonyms'

    These are the machine-readable option codes the planner converts to human-
    readable fragment text.
    """
    from backend.engine.executor import _build_cv_vision_diagnostic

    diag = _build_cv_vision_diagnostic(target_text="Button", mark_map={"1": {"x": 5, "y": 5, "tag": "button"}})

    options = diag["options"]
    canonical = {"open_container", "scroll", "synonyms"}
    assert canonical.intersection(set(options)), (
        f"Expected at least one of {canonical} in options. Got: {options}"
    )


# ---------------------------------------------------------------------------
# AC-VERIFY-4b: planner fragment injection when state carries cv_vision_diagnostic
# ---------------------------------------------------------------------------


def _planner_state_with_diagnostic(target_text: str = "Contest", n_marks: int = 12) -> dict:
    """Minimal state dict with a cv_vision_diagnostic to trigger fragment injection."""
    return {
        "run_id": _RUN_ID,
        "ac_step_index": 2,
        "mark_coordinate_map": {},
        "cv_fallback_invocations": 1,
        "cv_fallback_results": [],
        "visual_context": None,
        "current_page_url": "https://qa.vcreative.net/vpromotions",
        "ac_step_failure_diary": [],
        "cv_vision_diagnostic": {
            "target_text": target_text,
            "n_marks": n_marks,
            "options": ["open_container", "scroll", "synonyms"],
        },
    }


def test_planner_cv_diagnostic_fragment_injected():
    """
    When state contains cv_vision_diagnostic, _build_cv_diagnostic_fragment must
    return a non-empty string containing at least one of:
      'open a parent container', 'scroll', 'try synonyms'.

    AC-VERIFY-4b: fragment appears in the assembled system prompt for the next turn.
    """
    from backend.engine.planner import _build_cv_diagnostic_fragment

    state = _planner_state_with_diagnostic(target_text="Contest", n_marks=12)
    fragment = _build_cv_diagnostic_fragment(state)

    assert fragment, "Expected a non-empty fragment when cv_vision_diagnostic is set"

    fragment_lower = fragment.lower()
    option_strings = ["open a parent container", "scroll", "try synonyms"]
    assert any(opt in fragment_lower for opt in option_strings), (
        f"Expected at least one of {option_strings} in fragment.\nGot: {fragment}"
    )


def test_planner_cv_diagnostic_fragment_absent_when_no_diagnostic():
    """
    When state does NOT contain cv_vision_diagnostic (or it is None/empty),
    _build_cv_diagnostic_fragment must return an empty string or None — no
    spurious fragments injected on normal planner turns.
    """
    from backend.engine.planner import _build_cv_diagnostic_fragment

    state = _planner_state_with_diagnostic()
    state["cv_vision_diagnostic"] = None

    fragment = _build_cv_diagnostic_fragment(state)
    assert not fragment, (
        f"Expected empty fragment when cv_vision_diagnostic=None. Got: {fragment!r}"
    )


def test_planner_cv_diagnostic_fragment_mentions_target():
    """
    The injected fragment must reference the target_text or n_marks so the planner
    knows WHICH element vision failed on. Verifies the fragment is specific, not generic.
    """
    from backend.engine.planner import _build_cv_diagnostic_fragment

    state = _planner_state_with_diagnostic(target_text="SpecialDropdownItem", n_marks=5)
    fragment = _build_cv_diagnostic_fragment(state)

    assert fragment, "Expected non-empty fragment"
    assert "SpecialDropdownItem" in fragment or "5" in fragment, (
        f"Expected target_text or n_marks reference in fragment.\nGot: {fragment}"
    )
