"""
backend/engine/registry_first_gate.py

T3-b — Registry-First Gate (Phase 2, FEAT-118)
===============================================

Implements ``RegistryFirstGate``: the mandatory pre-emit gate that intercepts
a planned action AFTER the LLM has emitted it and BEFORE it is written to
``VQAState.planned_action``.

Behaviour summary
-----------------
* **On a registry hit** (the AC step's target has an entry in
  ``knowledge/selector_registry.json`` for the active product):
  - The action's ``strategy``, ``role``, and ``name`` are rewritten to the
    registry-provided values.
  - A ``_registry_hit=True`` flag is set on the action dict.
  - A ``registry_hit`` log event is emitted (always, including in shadow mode).

* **On a registry miss** (no matching entry):
  - A ``registry_enrichment_needed`` structured log event is emitted with
    the required telemetry fields (AC-VERIFY-4).
  - The action is returned unchanged.

Environment knobs (12-Factor)
------------------------------
``REGISTRY_FIRST_GATE_ENABLED`` (default ``true``)
    Master toggle. Set to ``false`` to disable the gate entirely (e.g., during
    emergency rollback).

``REGISTRY_FIRST_GATE_SHADOW_MODE`` (default ``false``)
    When ``true``, the gate performs the lookup and emits telemetry, but does
    NOT rewrite the action. Use for dark-launch validation before enabling.

Architecture note (CQ-B1)
--------------------------
The gate is a single call site at the tail of ``_planner_node_inner()`` in
``planner.py``, inserted just before the ``return`` statement that sets
``planned_action``. It does NOT inline into every ``get_by_text`` fallback
site in the 5,460-line planner (that approach was rejected in CQ-B1 as
"missed one site" prone). The single seam is the only place where the gate
runs; all 7 get_by_text fallback paths converge here after LLM emission.

See also
--------
* ``backend/kb/selector_registry.py`` — provides the ``.lookup()`` method.
* ``knowledge/selector_registry.json`` — the data source (nested by product
  slug under the top-level ``selectors`` key).
* ``tests/engine/test_planner_selector_registry.py`` — unit tests.
* ``memory-bank/creative/FEAT-118-vqa-tier3-architectural-hardening-architecture.md``
  §CQ-B1, §CQ-B2, §CQ-B3.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from backend.kb.selector_registry import selector_registry

logger = logging.getLogger(__name__)


def _gate_enabled() -> bool:
    """Return True unless REGISTRY_FIRST_GATE_ENABLED is explicitly 'false'."""
    return os.environ.get("REGISTRY_FIRST_GATE_ENABLED", "true").lower() not in ("false", "0", "no")


def _shadow_mode() -> bool:
    """Return True when REGISTRY_FIRST_GATE_SHADOW_MODE is 'true'."""
    return os.environ.get("REGISTRY_FIRST_GATE_SHADOW_MODE", "false").lower() in ("true", "1", "yes")


def _infer_target_from_step(ac_step_text: str) -> str:
    """
    Best-effort extraction of a target element name from AC step text.

    Used when the planned action does not carry an explicit ``name`` field
    (e.g., the LLM emitted a css_selector action with no name).

    The heuristic: take the last noun phrase after verbs like
    "click", "select", "fill", "choose", etc.
    """
    _VERBS = ("click", "select", "choose", "fill", "enter", "press", "navigate to", "go to")
    text = ac_step_text.strip()
    for verb in _VERBS:
        if text.lower().startswith(verb):
            remainder = text[len(verb):].strip()
            # Return the first quoted string, or the first few words
            if remainder.startswith(('"', "'")):
                inner = remainder[1:]
                close = inner.find(remainder[0])
                if close > 0:
                    return inner[:close]
            return remainder[:60]
    return text[:60]


class RegistryFirstGate:
    """
    Static-method gate — no instance state.

    All methods are ``@staticmethod`` so callers need not maintain an instance;
    the gate is stateless and its only I/O is ``selector_registry.lookup()``.
    """

    @staticmethod
    def check(
        planned_action: dict[str, Any],
        ac_step_text: str,
        product_slug: str,
        run_id: str = "",
        ac_step_index: int = -1,
    ) -> dict[str, Any]:
        """
        Intercept a planned action and apply the registry-first gate.

        Args
        ----
        planned_action : dict
            The action dict emitted by the LLM planner (mutable; may be
            rewritten in-place and returned).
        ac_step_text : str
            The current AC step text. Used for registry pattern matching
            and telemetry.
        product_slug : str
            The active product slug (e.g. "vpromotions"). Only this product's
            namespace is searched in the registry.
        run_id : str
            Current run identifier for telemetry (optional; empty string OK).
        ac_step_index : int
            Index of the current AC step in the test plan (0-based; -1 if unknown).

        Returns
        -------
        dict
            The (possibly rewritten) action dict. Fields not touched by the
            gate (``action``, ``reasoning``, ``container_selector``, etc.)
            are preserved verbatim.
        """
        if not _gate_enabled():
            logger.debug(
                "RegistryFirstGate: disabled (REGISTRY_FIRST_GATE_ENABLED=false) — passthrough"
            )
            return planned_action

        target_name = planned_action.get("name") or _infer_target_from_step(ac_step_text)
        fallback_strategy = planned_action.get("strategy", "get_by_text")
        fallback_locator = planned_action.get("name", "")

        hit = selector_registry.lookup(
            product_slug=product_slug,
            ac_step_text=ac_step_text,
            target_name=target_name,
        )

        if hit:
            shadow = _shadow_mode()

            # Always emit a registry_hit log event (including in shadow mode)
            logger.info(
                "registry_hit: product=%s ac_step=%r rewritten_strategy=%s shadow=%s",
                product_slug,
                ac_step_text[:80],
                hit["playwright_strategy"],
                shadow,
                extra={
                    "event_type": "registry_hit" if not shadow else "registry_hit_shadow",
                    "product": product_slug,
                    "ac_step_text": ac_step_text,
                    "rewritten_strategy": hit["playwright_strategy"],
                    "shadow_mode": shadow,
                    "run_id": run_id,
                    "ac_step_index": ac_step_index,
                },
            )

            if shadow:
                # Shadow mode: observe but do not rewrite
                return planned_action

            # Rewrite the action with registry-provided values
            planned_action["strategy"] = hit["playwright_strategy"]
            if hit.get("role") is not None:
                planned_action["role"] = hit["role"]
            if hit.get("name") is not None:
                planned_action["name"] = hit["name"]
            if hit.get("vqa_id") is not None:
                planned_action["vqa_id"] = hit["vqa_id"]
            planned_action["_registry_hit"] = True

            logger.info(
                "[%s] RegistryFirstGate: HIT product=%s step=%r → strategy=%s name=%r",
                run_id,
                product_slug,
                ac_step_text[:60],
                hit["playwright_strategy"],
                hit.get("name"),
            )
            return planned_action

        # Registry miss — emit enrichment-needed telemetry
        logger.info(
            "registry_enrichment_needed: product=%s ac_step=%r fallback_strategy=%s",
            product_slug,
            ac_step_text[:80],
            fallback_strategy,
            extra={
                "event_type": "registry_enrichment_needed",
                "product": product_slug,
                "ac_step_text": ac_step_text,
                "inferred_target": target_name,
                "planner_fallback_strategy": fallback_strategy,
                "planner_fallback_locator": fallback_locator,
                "run_id": run_id,
                "ac_step_index": ac_step_index,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.debug(
            "[%s] RegistryFirstGate: MISS product=%s step=%r — passthrough to %s",
            run_id,
            product_slug,
            ac_step_text[:60],
            fallback_strategy,
        )
        return planned_action

    @staticmethod
    def build_prompt_block(
        ac_step_text: str,
        product_slug: str,
    ) -> str:
        """
        Build a ``<registry_hits>`` XML block for injection into the planner
        system prompt (CQ-B1 prompt-time steering component).

        Called BEFORE the LLM call so the model favours registry-provided
        strategies on the first attempt, reducing wasted Bedrock invocations.

        Returns an empty string when the gate is disabled, in shadow mode, or
        when no registry hit exists for the current step.

        Args
        ----
        ac_step_text : str
            The current AC step text.
        product_slug : str
            Active product slug.

        Returns
        -------
        str
            A non-empty ``<registry_hits>`` XML block if a hit is found, or
            an empty string otherwise.
        """
        if not _gate_enabled():
            return ""

        hit = selector_registry.lookup(
            product_slug=product_slug,
            ac_step_text=ac_step_text,
        )
        if not hit:
            return ""

        parts = [
            "<registry_hits>",
            f"  MANDATORY: A confirmed selector exists for this AC step ({ac_step_text[:60]!r}).",
            f"  You MUST use strategy={hit['playwright_strategy']!r}",
        ]
        if hit.get("role"):
            parts.append(f"  role={hit['role']!r}")
        if hit.get("name"):
            parts.append(f"  name={hit['name']!r}")
        if hit.get("vqa_id"):
            parts.append(f"  vqa_id={hit['vqa_id']!r}")
        parts.append("  Do NOT emit strategy='get_by_text' for this target.")
        parts.append("</registry_hits>")

        return "\n".join(parts)
