"""
backend/engine/ui_delta.py
==========================
Shared utility for 4-signal stagnant UI detection:
URL, Element Count, ARIA Snapshot, and Active Overlay Markers.
"""

import logging
import json
import inspect
from typing import Any, Dict

logger = logging.getLogger(__name__)

def _is_page_closed(page) -> bool:
    """Robustly check if a page is closed, handling mocks elegantly to avoid RuntimeWarnings."""
    try:
        is_closed = page.is_closed
        if callable(is_closed):
            res = is_closed()
            if inspect.iscoroutine(res):
                if hasattr(res, "close"):
                    res.close()  # Prevent RuntimeWarning: coroutine was never awaited
                return False
            return bool(res)
        return bool(is_closed)
    except Exception:
        return False

async def compute_ui_delta(
    page,
    pre_state: Dict[str, Any],
    run_id: str = "UNKNOWN",
) -> Dict[str, Any]:
    """
    Computes a delta of the page state against the given pre_state using 4 signals:
    1. URL (url_changed)
    2. Element count (element_count_changed)
    3. ARIA snapshot (snapshot_changed)
    4. Active overlay markers (overlays_changed)
    
    pre_state dictionary structure:
    {
        "url": str,
        "element_count": int,
        "aria_snapshot": str,
        "active_overlays": list[str]
    }
    """
    results = {
        "has_changed": False,
        "url_changed": False,
        "snapshot_changed": False,
        "element_count_changed": False,
        "overlays_changed": False,
        "url_before": pre_state.get("url"),
        "url_after": None,
        "element_count_before": pre_state.get("element_count"),
        "element_count_after": None,
        "snapshot_before": pre_state.get("aria_snapshot"),
        "snapshot_after": None,
        "overlays_before": pre_state.get("active_overlays", []),
        "overlays_after": [],
    }

    if _is_page_closed(page):
        return results

    # Signal 1: URL change
    try:
        current_url = page.url
        results["url_after"] = current_url
        if pre_state.get("url") is not None and current_url != pre_state.get("url"):
            results["url_changed"] = True
            results["has_changed"] = True
            logger.info(
                "[%s] compute_ui_delta: URL changed — '%s' → '%s'",
                run_id, pre_state.get("url", ""), current_url
            )
    except Exception as e:
        logger.debug("[%s] compute_ui_delta: URL check failed: %s", run_id, e)

    # Signal 2: Element count change
    try:
        current_count = await page.evaluate("document.querySelectorAll('*').length")
        results["element_count_after"] = current_count
        if pre_state.get("element_count") is not None and current_count != pre_state.get("element_count"):
            results["element_count_changed"] = True
            results["has_changed"] = True
            logger.info(
                "[%s] compute_ui_delta: Element count changed — %s → %s (Δ%+d)",
                run_id, pre_state.get("element_count"), current_count, current_count - pre_state.get("element_count", 0)
            )
    except Exception as e:
        logger.debug("[%s] compute_ui_delta: Element count check failed: %s", run_id, e)

    # Signal 3: ARIA snapshot change
    try:
        raw_snapshot = await page.accessibility.snapshot()
        if raw_snapshot:
            current_snapshot = json.dumps(raw_snapshot, sort_keys=True)
        else:
            current_snapshot = await page.evaluate("document.body.innerText") or ""
        results["snapshot_after"] = current_snapshot
        
        snapshot_before = pre_state.get("aria_snapshot")
        if snapshot_before is not None and current_snapshot != snapshot_before:
            results["snapshot_changed"] = True
            results["has_changed"] = True
            logger.info(
                "[%s] compute_ui_delta: Snapshot changed (%d chars → %d chars)",
                run_id, len(snapshot_before), len(current_snapshot)
            )
    except Exception as e:
        logger.debug("[%s] compute_ui_delta: ARIA snapshot check failed: %s", run_id, e)

    # Signal 4: Overlay markers
    try:
        js_code = """() => {
            const selectors = [
                "div.p-dialog", "div.p-sidebar", "div.p-sidebar-active", "div.p-overlaypanel",
                "div.p-toast", ".v-spinner", "p-progress-spinner", ".loading-overlay", ".p-blockui"
            ];
            return selectors.filter(sel => document.querySelector(sel) !== null);
        }"""
        current_overlays = await page.evaluate(js_code)
        results["overlays_after"] = current_overlays
        
        overlays_before = pre_state.get("active_overlays", []),
        # Handle tuple wrapping from trailing comma
        if isinstance(overlays_before, tuple):
            overlays_before = overlays_before[0]
            
        if sorted(current_overlays) != sorted(overlays_before):
            results["overlays_changed"] = True
            results["has_changed"] = True
            logger.info(
                "[%s] compute_ui_delta: Overlay markers changed — %s → %s",
                run_id, overlays_before, current_overlays
            )
    except Exception as e:
        logger.debug("[%s] compute_ui_delta: Overlay check failed: %s", run_id, e)

    return results


async def capture_pre_action_state(page) -> Dict[str, Any]:
    """
    Capture the state of the page before an action is taken.
    """
    state = {
        "url": "",
        "element_count": 0,
        "aria_snapshot": "",
        "active_overlays": []
    }
    if _is_page_closed(page):
        return state

    try:
        state["url"] = page.url
    except Exception:
        pass

    try:
        state["element_count"] = await page.evaluate("document.querySelectorAll('*').length")
    except Exception:
        pass

    try:
        raw_snapshot = await page.accessibility.snapshot()
        if raw_snapshot:
            state["aria_snapshot"] = json.dumps(raw_snapshot, sort_keys=True)
        else:
            state["aria_snapshot"] = await page.evaluate("document.body.innerText") or ""
    except Exception:
        pass

    try:
        js_code = """() => {
            const selectors = [
                "div.p-dialog", "div.p-sidebar", "div.p-sidebar-active", "div.p-overlaypanel",
                "div.p-toast", ".v-spinner", "p-progress-spinner", ".loading-overlay", ".p-blockui"
            ];
            return selectors.filter(sel => document.querySelector(sel) !== null);
        }"""
        state["active_overlays"] = await page.evaluate(js_code)
    except Exception:
        pass

    return state
