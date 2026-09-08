import pytest
from backend.engine.ac_parser import _detect_nav_paths
from backend.api.schemas import PreviewStepsResponse


# ---------------------------------------------------------------------------
# _detect_nav_paths unit tests
# ---------------------------------------------------------------------------

def test_multi_path_ac_detects_multiple_paths():
    raw_ac = (
        "Given the user navigates to HDah > Module Abilities > Edit Module\n"
        "And the user navigates to HDah > Settings > Permissions\n"
        "When the user clicks Save\n"
        "Then the changes are persisted"
    )
    paths = _detect_nav_paths(raw_ac)
    assert len(paths) == 2
    assert "HDah > Module Abilities > Edit Module" in paths
    assert "HDah > Settings > Permissions" in paths


def test_single_path_ac_detects_one_path():
    raw_ac = (
        "Given the user navigates to HDah > Module Abilities > Edit Module\n"
        "When the user clicks Save\n"
        "Then changes are saved"
    )
    paths = _detect_nav_paths(raw_ac)
    assert len(paths) == 1
    assert "HDah > Module Abilities > Edit Module" in paths


def test_no_path_ac_returns_empty():
    raw_ac = (
        "Given the user is logged in\n"
        "When the user clicks the Save button\n"
        "Then a success toast appears"
    )
    paths = _detect_nav_paths(raw_ac)
    assert paths == []


def test_markdown_blockquote_not_detected():
    raw_ac = (
        "> This is a blockquote note about the feature\n"
        "Given the user is on the dashboard\n"
        "When the user clicks Save\n"
        "Then the form submits"
    )
    paths = _detect_nav_paths(raw_ac)
    assert paths == []


def test_path_without_spaces_around_arrow():
    raw_ac = (
        "Given the user navigates to HDah>Module>Settings\n"
        "When the user updates the config\n"
        "Then changes are saved"
    )
    paths = _detect_nav_paths(raw_ac)
    assert len(paths) == 1


def test_deduplicated_paths():
    raw_ac = (
        "Given the user navigates to HDah > Module Abilities > Edit Module\n"
        "And again navigates to HDah > Module Abilities > Edit Module\n"
        "When the user saves\n"
        "Then one record is created"
    )
    paths = _detect_nav_paths(raw_ac)
    assert len(paths) == 1
    assert "HDah > Module Abilities > Edit Module" in paths


def test_arithmetic_comparison_not_detected():
    raw_ac = (
        "Given the result count > 5\n"
        "When the threshold is exceeded\n"
        "Then an alert fires"
    )
    paths = _detect_nav_paths(raw_ac)
    assert paths == []


def test_compound_bug_paths_detected():
    raw_ac = (
        "Bug A: navigating to HDah > Reports > Summary shows blank page\n"
        "Bug B: navigating to HDah > Reports > Detail crashes the app\n"
        "Both bugs are reproducible in the latest build"
    )
    paths = _detect_nav_paths(raw_ac)
    assert len(paths) == 2


# ---------------------------------------------------------------------------
# PreviewStepsResponse schema tests
# ---------------------------------------------------------------------------

def test_preview_steps_response_has_detected_paths_field():
    resp = PreviewStepsResponse(
        ticket_id="VQAA-1",
        summary="Test ticket",
        acceptance_criteria="raw AC",
        steps=["Step 1"],
        detected_paths=["HDah > Module Abilities > Edit Module"],
    )
    assert resp.detected_paths == ["HDah > Module Abilities > Edit Module"]


def test_preview_steps_response_has_ambiguities_field():
    resp = PreviewStepsResponse(
        ticket_id="VQAA-1",
        summary="Test ticket",
        acceptance_criteria="raw AC",
        steps=["Step 1"],
        ambiguities=["vague warning"],
    )
    assert resp.ambiguities == ["vague warning"]


def test_preview_steps_response_defaults_empty():
    resp = PreviewStepsResponse(
        ticket_id="VQAA-1",
        summary="Test ticket",
        acceptance_criteria="raw AC",
        steps=["Step 1"],
    )
    assert resp.detected_paths == []
    assert resp.ambiguities == []
    assert resp.has_ghost_login is False
    assert resp.has_ghost_description is False


def test_preview_steps_response_carries_ghost_flags():
    # Regression: fields must be declared on the schema — Pydantic v2 silently
    # drops undeclared kwargs, which previously stripped these flags from the
    # wire response and hid the ghost credential panel on the frontend.
    resp = PreviewStepsResponse(
        ticket_id="QA-358",
        summary="Regression - Contesting",
        acceptance_criteria="raw AC",
        steps=["Step 1"],
        has_ghost_login=True,
        has_ghost_description=True,
    )
    assert resp.has_ghost_login is True
    assert resp.has_ghost_description is True
    dumped = resp.model_dump()
    assert dumped["has_ghost_login"] is True
    assert dumped["has_ghost_description"] is True
