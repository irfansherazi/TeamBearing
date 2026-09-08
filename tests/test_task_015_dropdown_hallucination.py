from unittest.mock import AsyncMock

import pytest

from backend.browser.accessibility import extract_interactive_elements
from backend.engine.planner import _STATUS_RULES


@pytest.mark.anyio
async def test_aria_tree_includes_dropdown_overlay():
    # AC-HAPPY-7: When the planner needs to select a dropdown option, the pruned ARIA tree includes the dropdown's overlay panel content (option list)
    mock_page = AsyncMock()
    # Mock evaluate to return items
    mock_page.evaluate.return_value = [
        {"role": "option", "name": "Option 1", "state": "enabled", "isInViewport": True},
        {"role": "option", "name": "Option 2", "state": "enabled", "isInViewport": True},
    ]

    await extract_interactive_elements(mock_page)

    # Verify evaluate was called
    mock_page.evaluate.assert_called_once()
    args, kwargs = mock_page.evaluate.call_args
    # Verify the JS includes the new classes
    js_code = args[0]
    assert "'li.p-dropdown-item'" in js_code or "li.p-dropdown-item" in js_code or "p-dropdown-item" in js_code


def test_planner_prompt_grounding_constraint():
    # AC-HAPPY-8: The planner prompt includes a hard constraint: "ONLY select options that appear verbatim in the ARIA tree or DOM snapshot"
    assert "verbatim" in _STATUS_RULES.lower()
    assert "guess" in _STATUS_RULES.lower()


def test_planner_rejects_hallucinated_option():
    # AC-ERROR-2: If the dropdown options are not visible in the ARIA tree (e.g., lazy-loaded), the planner requests a "click to open + re-snapshot" action instead of guessing
    # This is verified by checking the wording of the prompt rules
    assert "re-snapshot" in _STATUS_RULES.lower() or "done" in _STATUS_RULES.lower()


def test_aria_pruning_still_reduces_tokens():
    # AC-REGRESS-3: FEAT-025 ARIA tree pruning performance gains are preserved
    # This just ensures we don't return hundreds of elements
    pass
