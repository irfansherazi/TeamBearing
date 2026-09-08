"""
vQA — Autorecord Engine
=======================
Module: backend/engine/autorecord.py

Translates raw human interaction events (captured via JS bridge) into clean,
deterministic Playwright action sequences for Knowledge Base injection.

Phase 1 — Portal-aware serialization (hitl-portal-aware-click-capture):
  Non-portal records are byte-identical to pre-feature output (AC-VERIFY-5).
  Portal records branch on capture_confidence (from JS deriveCaptureConfidence):
    "full"         → action: primeng_dropdown  (executor's existing handler)
    "portal_only"  → action: click + container_selector  (scoped get_by_text)
    "none" / absent → byte-identical standard click
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Portal-aware helpers (Phase 1)
# ---------------------------------------------------------------------------

# CSS class prefixes that identify PrimeNG / vProMedia portal containers.
# Derived from the PORTAL_ALLOWLIST in the JS injection — must be kept in sync.
_PORTAL_CLASS_PREFIXES = (".p-", ".po-", ".sort-panel")


def _normalize_portal_class(portal_class: str) -> str:
    """Ensure portal_class has a leading dot (guards against JS contract drift).

    The JS layer should always emit portal_class with a leading dot (e.g.
    '.p-select-overlay'), but we normalize defensively so downstream code that
    passes portal_class directly to page.locator() always gets a CSS class selector.
    """
    if portal_class and not portal_class.startswith("."):
        return "." + portal_class
    return portal_class


def _maybe_portal_serialize(rec: dict) -> "dict | None":
    """Return a portal-aware serialized action dict, or None for the non-portal path.

    Branches on capture_confidence (emitted by JS deriveCaptureConfidence, ADDITION 7):
      "full"        → primeng_dropdown action (all three replay-critical fields present)
      "portal_only" → click with container_selector (partial capture; warn-but-persist)
      "none"/absent → return None (caller uses byte-identical standard click serialization)

    Never raises — any unexpected shape produces None, which falls through to standard
    click serialization and thus preserves byte-identical output (AC-VERIFY-5).

    Architecture doc §Handoff-to-Build "Change 1" defines this function contract.
    """
    confidence = rec.get("capture_confidence", "none")
    if confidence == "none":
        return None
    if rec.get("event_type") != "click":
        return None

    portal_class = _normalize_portal_class(rec.get("portal_class", ""))
    # Only process recognized portal class prefixes — unknown classes fall through to
    # standard click serialization (AC-ERROR-2 anonymous portals with empty portal_class
    # already collapse to capture_confidence="portal_only" with portal_class="" which
    # fails the prefix check here and routes to the standard click path).
    if not portal_class or not any(portal_class.startswith(p) for p in _PORTAL_CLASS_PREFIXES):
        return None

    if confidence == "full":
        return {
            "action": "primeng_dropdown",
            "trigger_selector": rec.get("trigger_selector", ""),
            "target_text": rec.get("target_text", ""),
            "portal_class": portal_class,
            "inner_text": rec.get("inner_text", ""),
            "_capture_confidence": "full",
        }

    # portal_only — scoped click within the portal container
    target = (
        rec.get("target_text", "")
        or rec.get("inner_text", "")
        or rec.get("aria_label", "")
    )
    if target:
        return {
            "action": "click",
            "strategy": "get_by_text",
            "name": target,
            "container_selector": portal_class,
            "inner_text": rec.get("inner_text", ""),
            "_capture_confidence": "portal_only",
        }

    # portal_only_degraded — no text available; use css_path scoped to the portal
    return {
        "action": "click",
        "strategy": "css_selector",
        "name": rec.get("css_path", ""),
        "container_selector": portal_class,
        "inner_text": "",
        "_capture_confidence": "portal_only_degraded",
    }


class AutorecordSerializer:
    """
    Translates a sequence of raw DOM events into high-quality Playwright steps.

    Handles:
      - Merging rapid 'keyup' events into a single 'fill' action.
      - Filtering out noise (e.g. redundant scrolls, clicks on non-interactive tags).
      - Normalizing strategies (get_by_role, get_by_label, etc).
    """

    def serialize(self, raw_sequence: list[dict]) -> list[dict]:
        """
        Convert raw JS records into clean Playwright actions.

        Args
        ----
        raw_sequence : list[dict]
            The list of events captured by the JS listener.

        Returns
        -------
        list[dict]
            Cleaned and normalized action list: [{action, strategy, name, value, ...}]
        """
        if not raw_sequence:
            return []

        clean_actions = []

        # Buffer for merging rapid typing events
        typing_buffer: dict[str, Any] = {}

        def flush_typing():
            if typing_buffer:
                clean_actions.append(typing_buffer.copy())
                typing_buffer.clear()

        for rec in raw_sequence:
            event_type = rec.get("event_type")

            # 1. Handle Keyup (Typing) -> merge into 'fill'
            if event_type == "keyup":
                selector = rec.get("best_selector")
                value = rec.get("value", "")

                if typing_buffer and typing_buffer.get("name") == selector:
                    # Update existing typing buffer with latest value
                    typing_buffer["value"] = value
                else:
                    # Different field or first field — flush old and start new
                    flush_typing()
                    typing_buffer = {
                        "action": "fill",
                        "strategy": rec.get("strategy", "get_by_text"),
                        "name": selector,
                        "value": value,
                        "inner_text": rec.get("inner_text", ""),
                    }
                continue

            # 2. Handle Change (Dropdowns/Checkboxes/Blur-typing)
            if event_type == "change":
                selector = rec.get("best_selector")
                value = rec.get("value", "")

                # If we were typing in this same field, the 'change' event
                # usually carries the same final value. We can replace or skip.
                if typing_buffer and typing_buffer.get("name") == selector:
                    typing_buffer["value"] = value
                    flush_typing()
                else:
                    flush_typing()
                    clean_actions.append(
                        {
                            "action": "fill",  # Playwright uses 'fill' for text, 'select_option' for selects
                            "strategy": rec.get("strategy", "get_by_text"),
                            "name": selector,
                            "value": value,
                            "inner_text": rec.get("inner_text", ""),
                        }
                    )
                continue

            # 3. Handle Clicks (portal-aware — Phase 1)
            if event_type == "click":
                flush_typing()
                portal_action = _maybe_portal_serialize(rec)
                if portal_action is not None:
                    # Portal click: primeng_dropdown (full) or scoped click (portal_only)
                    clean_actions.append(portal_action)
                else:
                    # Non-portal click: byte-identical to pre-feature output (AC-VERIFY-5)
                    clean_actions.append(
                        {
                            "action": "click",
                            "strategy": rec.get("strategy", "get_by_text"),
                            "name": rec.get("best_selector", ""),
                            "inner_text": rec.get("inner_text", ""),
                        }
                    )
                continue

            # 4. Handle Scrolls (Debounced)
            if event_type == "scroll":
                flush_typing()
                # For now, we just record it as an evaluate script or skip
                # Playwright usually doesn't need explicit scrolls if selectors work
                # but we'll record it for visual completeness in the KB.
                clean_actions.append(
                    {
                        "action": "scroll",
                        "strategy": "window",
                        "name": "window",
                        "value": rec.get("value", "0,0"),
                    }
                )
                continue

        # Final flush
        flush_typing()

        return self._post_process(clean_actions)

    def _post_process(self, actions: list[dict]) -> list[dict]:
        """Final cleanup: de-duplicate redundant clicks, etc."""
        if not actions:
            return []

        processed = []
        for i, act in enumerate(actions):
            # If a click is immediately followed by a 'fill' on the same element,
            # we can often skip the click as Playwright's fill() auto-focuses.
            if i + 1 < len(actions):
                next_act = actions[i + 1]
                if act["action"] == "click" and next_act["action"] == "fill" and act["name"] == next_act["name"]:
                    continue  # Skip redundant focus click

            processed.append(act)

        return processed


# Global instance
autorecord_serializer = AutorecordSerializer()
