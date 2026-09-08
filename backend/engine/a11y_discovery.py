"""
vQA — Accessibility-First Dynamic Locator Discovery
===================================================
Module: backend/engine/a11y_discovery.py

Captures accessibility tree snapshots from Chromium and structures/maps them
to Playwright page.getByRole() selectors to eliminate brittle CSS selectors.
"""

import logging
from typing import Any, Dict, List
from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Standard translation dictionary for Playwright getByRole locators
ROLE_METHOD_MAP = {
    "button": "button",
    "textbox": "textbox",
    "checkbox": "checkbox",
    "combobox": "combobox",
    "link": "link",
    "menuitem": "menuitem",
    "tab": "tab",
    "radio": "radio"
}


async def capture_a11y_snapshot(page: Page) -> Dict[str, Any]:
    """
    Captures the accessibility tree snapshot of the page using Playwright.
    
    Args:
        page (Page): Playwright async Page instance.
        
    Returns:
        Dict[str, Any]: The raw or structured accessibility snapshot.
    """
    try:
        snapshot = await page.accessibility.snapshot()
        if snapshot is None:
            logger.warning("page.accessibility.snapshot() returned None, falling back to empty structure")
            return {"role": "WebArea", "children": []}
        return snapshot
    except Exception as e:
        logger.error("Failed to capture accessibility snapshot: %s", str(e), exc_info=True)
        return {"role": "WebArea", "children": []}


def prune_and_map_a11y_tree(raw_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Prunes noise (structural elements, disabled, unnamed) and maps remaining
    interactive elements to their corresponding Playwright page.getByRole() locators.
    
    Args:
        raw_snapshot (Dict[str, Any]): The raw accessibility snapshot from Playwright.
        
    Returns:
        List[Dict[str, Any]]: List of interactive element dicts, each containing:
            - "role": str
            - "name": str
            - "locator": str
    """
    interactive_elements = []
    
    # We target interactive roles specified in the requirements
    interactive_roles = set(ROLE_METHOD_MAP.keys())

    def traverse(node: Dict[str, Any]):
        if not node:
            return
            
        role = node.get("role")
        name = node.get("name", "").strip()
        # To handle both real-world Playwright (which doesn't have focusable in snapshot API)
        # and mock data / requirements that specify focusable=True.
        focusable = node.get("focusable", True)
        disabled = node.get("disabled", False)
        
        if role in interactive_roles and focusable and not disabled:
            if name:
                locator_role = ROLE_METHOD_MAP[role]
                # Replace double quotes in name with escaped quotes for safe string interpolation
                safe_name = name.replace('"', '\\"')
                locator_str = f'page.getByRole("{locator_role}", {{"name": "{safe_name}"}})'
                
                interactive_elements.append({
                    "role": role,
                    "name": name,
                    "locator": locator_str
                })
                
        # Recurse children
        for child in node.get("children", []):
            traverse(child)
            
    traverse(raw_snapshot)
    return interactive_elements
