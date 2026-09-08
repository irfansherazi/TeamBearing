"""
TASK-010: Session Navigation Context — Unit Tests
=================================================
Tests for the session navigation context that provides the planner with
current URL, page heading, and last 3 navigation actions.

Acceptance Criteria:
  AC-HAPPY-1: VQAState schema updated to include navigation_history
  AC-HAPPY-2: navigation_history is populated on navigation actions
  AC-HAPPY-3: Planner prompt injection adds <session_context> XML
  AC-HAPPY-4: page_heading is correctly retrieved from StateTracker
  AC-HAPPY-5: enable_session_navigation_context controls the feature
"""

from typing import get_type_hints

from backend.engine.executor import _update_navigation_history
from backend.engine.planner import _build_session_context_block
from backend.engine.state import VQAState, make_initial_state
from backend.engine.state_tracker import PageState

# ---------------------------------------------------------------------------
# AC-HAPPY-1: VQAState schema
# ---------------------------------------------------------------------------


def test_state_has_navigation_history():
    """AC-HAPPY-1: navigation_history field exists in VQAState as list[str]"""
    # Validate TypedDict annotations
    hints = get_type_hints(VQAState)
    assert "navigation_history" in hints
    assert hints["navigation_history"] == list[str]

    # Validate initialization
    state = make_initial_state(
        run_id="test", target_url="https://test.com", role="ae", jira_ticket_id="QA-123", mode="headless"
    )
    assert "navigation_history" in state
    assert state["navigation_history"] == []


# ---------------------------------------------------------------------------
# AC-HAPPY-2: navigation_history population
# ---------------------------------------------------------------------------


def test_update_navigation_history_appends_and_slices():
    """AC-HAPPY-2: navigation_history capped at 3 entries, FIFO"""
    history = ["/page1", "/page2"]

    # Update with new navigation
    new_history = _update_navigation_history(history, "navigate", "/page3")
    assert new_history == ["/page1", "/page2", "/page3"]

    # Update again, should shift
    final_history = _update_navigation_history(new_history, "navigate", "/page4")
    assert final_history == ["/page2", "/page3", "/page4"]
    assert len(final_history) == 3


def test_update_navigation_history_prefers_actual_url():
    """Navigate action should prefer actual_url from result if provided"""
    history = ["/page1"]
    new_history = _update_navigation_history(history, "navigate", "/requested", actual_url="/actual")
    assert new_history == ["/page1", "/actual"]


def test_update_navigation_history_only_on_navigate():
    """Only navigate actions should be recorded in navigation_history (per resolution)"""
    history = ["/page1"]

    # Click should NOT be recorded in navigation_history
    new_history = _update_navigation_history(history, "click", "button")
    assert new_history == ["/page1"]

    # go_back NOT recorded (per PR resolution unless explicitly enabled)
    final_history = _update_navigation_history(new_history, "go_back", None)
    assert final_history == ["/page1"]


# ---------------------------------------------------------------------------
# AC-HAPPY-3: XML block generation
# ---------------------------------------------------------------------------


def test_build_session_context_block():
    """AC-HAPPY-3: <session_context> XML format"""
    state = {
        "current_page_url": "https://test.com/dashboard",
        "navigation_history": ["/home", "/login", "/dashboard"],
    }
    # Mocking PageState for page_heading
    page_state = PageState(page_heading="Dashboard", current_url="https://test.com/dashboard")

    xml = _build_session_context_block(state, page_state)

    assert "<session_context>" in xml
    assert "<current_url>https://test.com/dashboard</current_url>" in xml
    assert "<page_heading>Dashboard</page_heading>" in xml
    assert "<navigation_history>" in xml
    assert "/home" in xml
    assert "/login" in xml
    assert "/dashboard" in xml
    assert "</session_context>" in xml


# ---------------------------------------------------------------------------
# AC-HAPPY-4: page_heading retrieval
# ---------------------------------------------------------------------------


def test_session_context_handles_empty_heading():
    """AC-HAPPY-4: Handles empty or missing page heading gracefully"""
    state = {"current_page_url": "https://test.com/", "navigation_history": []}
    page_state = PageState(page_heading="", current_url="https://test.com/")

    xml = _build_session_context_block(state, page_state)
    assert "<page_heading></page_heading>" in xml


# ---------------------------------------------------------------------------
# AC-HAPPY-5: Feature flag
# ---------------------------------------------------------------------------


def test_session_context_respects_feature_flag(monkeypatch):
    """AC-HAPPY-5: enable_session_navigation_context controls output"""
    from backend.config import settings

    state = {"current_page_url": "https://test.com/", "navigation_history": ["/"]}
    page_state = PageState(page_heading="Home", current_url="https://test.com/")

    # Enabled (default)
    monkeypatch.setattr(settings, "enable_session_navigation_context", True)
    assert _build_session_context_block(state, page_state) != ""

    # Disabled
    monkeypatch.setattr(settings, "enable_session_navigation_context", False)
    assert _build_session_context_block(state, page_state) == ""
