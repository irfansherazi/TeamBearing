"""
vQA — Unit Tests for Accessibility-First Discovery
==================================================
Module: tests/test_a11y_discovery.py

Verifies capturing, pruning, and role-mapping of the Playwright accessibility tree.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from backend.engine.a11y_discovery import capture_a11y_snapshot, prune_and_map_a11y_tree


@pytest.mark.anyio
async def test_capture_a11y_snapshot_success():
    """Verify that a successful accessibility snapshot is returned cleanly."""
    mock_page = AsyncMock()
    expected_snapshot = {
        "role": "WebArea",
        "name": "vSuite Dashboard",
        "children": [
            {"role": "button", "name": "Submit", "focusable": True}
        ]
    }
    mock_page.accessibility.snapshot.return_value = expected_snapshot
    
    result = await capture_a11y_snapshot(mock_page)
    assert result == expected_snapshot
    mock_page.accessibility.snapshot.assert_called_once()


@pytest.mark.anyio
async def test_capture_a11y_snapshot_failure():
    """Verify that a failed accessibility snapshot is handled gracefully without raising."""
    mock_page = AsyncMock()
    mock_page.accessibility.snapshot.side_effect = Exception("Browser context disconnected")
    
    result = await capture_a11y_snapshot(mock_page)
    assert result == {"role": "WebArea", "children": []}


def test_prune_and_map_a11y_tree_filtering():
    """Verify pruning rules (focusable, disabled, unnamed, and invalid roles)."""
    raw_snapshot = {
        "role": "WebArea",
        "name": "vSuite Test Page",
        "children": [
            # Valid interactive elements
            {"role": "button", "name": "Click Me", "focusable": True},
            {"role": "textbox", "name": "Email Input", "focusable": True},
            {"role": "link", "name": "Learn More", "focusable": True},
            {"role": "combobox", "name": "Status Select", "focusable": True},
            {"role": "checkbox", "name": "Agree", "focusable": True},
            
            # Invalid: disabled
            {"role": "button", "name": "Disabled Button", "focusable": True, "disabled": True},
            
            # Invalid: focusable = False
            {"role": "button", "name": "Unfocusable Button", "focusable": False},
            
            # Invalid: no name
            {"role": "button", "name": "", "focusable": True},
            {"role": "textbox", "name": "   ", "focusable": True},
            
            # Invalid: structural/non-target roles
            {"role": "heading", "name": "Page Title", "focusable": False},
            {"role": "generic", "name": "Some Container", "focusable": True},
        ]
    }
    
    elements = prune_and_map_a11y_tree(raw_snapshot)
    
    # Check count of valid interactive elements
    assert len(elements) == 5
    
    # Verify mapping details for button
    btn = elements[0]
    assert btn["role"] == "button"
    assert btn["name"] == "Click Me"
    assert btn["locator"] == 'page.getByRole("button", {"name": "Click Me"})'
    
    # Verify mapping details for textbox
    tb = elements[1]
    assert tb["role"] == "textbox"
    assert tb["name"] == "Email Input"
    assert tb["locator"] == 'page.getByRole("textbox", {"name": "Email Input"})'
    
    # Verify checkbox locator
    cb = elements[4]
    assert cb["role"] == "checkbox"
    assert cb["name"] == "Agree"
    assert cb["locator"] == 'page.getByRole("checkbox", {"name": "Agree"})'


def test_prune_and_map_a11y_tree_escaped_name():
    """Verify names with double quotes are correctly escaped in locators."""
    raw_snapshot = {
        "role": "WebArea",
        "name": "Test Escaping",
        "children": [
            {"role": "button", "name": 'Click "Now"', "focusable": True}
        ]
    }
    
    elements = prune_and_map_a11y_tree(raw_snapshot)
    assert len(elements) == 1
    assert elements[0]["locator"] == 'page.getByRole("button", {"name": "Click \\"Now\\""})'


def test_prune_and_map_a11y_tree_nested():
    """Verify that nested trees are traversed recursively."""
    raw_snapshot = {
        "role": "WebArea",
        "name": "Nested Page",
        "children": [
            {
                "role": "generic",
                "children": [
                    {
                        "role": "generic",
                        "children": [
                            {"role": "button", "name": "Deep Button", "focusable": True}
                        ]
                    }
                ]
            }
        ]
    }
    
    elements = prune_and_map_a11y_tree(raw_snapshot)
    assert len(elements) == 1
    assert elements[0]["name"] == "Deep Button"
