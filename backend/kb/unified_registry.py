"""
vQA — Unified Component Interaction Registry
================================================
Module: backend/kb/unified_registry.py

Phase 5 of the vQA hardening roadmap: consolidates fragmented domain
knowledge into a single, versioned interaction registry.

Problem Statement
-----------------
Before this module, component interaction knowledge was scattered across:
  - knowledge/component_registry.json (PrimeNG component protocols)
  - knowledge/selector_registry.json (3,969 lines of selectors)
  - knowledge/human_guidance.md (683 lines of human-written rules)
  - backend/kb/component_registry.py (keyword detection)
  - backend/kb/selector_registry.py (fuzzy selector lookup)

This fragmentation caused:
  1. Conflicting advice (component_registry says "use click", selector_registry
     says "use css_selector" for the same element)
  2. Stale entries that never get pruned
  3. The planner receiving duplicate or contradictory rules from multiple sources

Solution
--------
``ComponentInteraction`` is a single Pydantic model that unifies:
  - Selector strategies (with version tags and confidence scores)
  - Interaction protocols (open → wait → select → close)
  - Forbidden patterns (hard blocks)
  - Timing requirements (animation budgets)
  - Version compatibility (PrimeNG v17 vs v19)

The ``UnifiedRegistry`` loads from ``knowledge/unified_components.json``
and provides a single ``lookup(component_key)`` method that returns
everything the planner needs in one call.

Migration Path
--------------
  1. [DONE] Create the model and registry in this file
  2. [TODO] Generate unified_components.json from existing sources
  3. [TODO] Update planner.py to prefer UnifiedRegistry over the 3 legacy sources
  4. [TODO] Deprecate component_registry.py and selector_registry.py

See Also
--------
  - backend/kb/component_registry.py — legacy, to be deprecated
  - backend/kb/selector_registry.py  — legacy, to be deprecated
  - backend/engine/planner.py        — consumer
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_UNIFIED_PATH = Path(__file__).parent.parent.parent / "knowledge" / "unified_components.json"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class SelectorStrategy:
    """A single selector strategy with version and confidence metadata.

    Attributes
    ----------
    method : str
        Playwright locator method: ``"get_by_role"``, ``"get_by_text"``,
        ``"get_by_label"``, ``"css_selector"``, etc.
    role : str
        ARIA role (for ``get_by_role`` only).
    name : str
        Element name / text.
    selector : str
        CSS selector (for ``css_selector`` only).
    primeng_versions : list[str]
        PrimeNG versions this selector is known to work with.
        Example: ``["v17", "v18", "v19"]``.
    confidence : float
        0.0-1.0 score based on testing history.
        1.0 = verified in automated tests.
        0.8 = verified by HITL interaction.
        0.5 = extracted from source code, untested.
    notes : str
        Free-form notes about when to use this strategy.
    """

    method: str = ""
    role: str = ""
    name: str = ""
    selector: str = ""
    primeng_versions: list[str] = field(default_factory=lambda: ["v17", "v18", "v19"])
    confidence: float = 0.5
    notes: str = ""


@dataclass
class InteractionStep:
    """A single step in a component interaction protocol.

    Attributes
    ----------
    action : str
        Playwright action: ``"click"``, ``"fill"``, ``"type"``,
        ``"press_key"``, ``"wait"``, ``"wait_for_selector"``.
    strategy : str
        Locator strategy for the target element.
    selector : str
        CSS selector or role-based locator string.
    value : str
        Fill value, key name, or wait duration.
    wait_after_ms : int
        Mandatory wait after this step (for animation/CD).
    notes : str
        Why this step exists and what can go wrong.
    """

    action: str = ""
    strategy: str = ""
    selector: str = ""
    value: str = ""
    wait_after_ms: int = 0
    notes: str = ""


@dataclass
class AnimationBudget:
    """Timing constraints for a component's open/close animations.

    These timings prevent the agent from interacting with elements
    that are still animating (causes misclicks and stale refs).

    Attributes
    ----------
    open_ms : int
        Milliseconds for the open animation to complete.
    close_ms : int
        Milliseconds for the close animation to complete.
    debounce_ms : int
        Milliseconds of input debounce (for autocomplete/search).
    verifier_wait_ms : int
        Total time the verifier should wait before asserting visibility.
    """

    open_ms: int = 200
    close_ms: int = 100
    debounce_ms: int = 0
    verifier_wait_ms: int = 300


@dataclass
class ComponentInteraction:
    """Unified interaction descriptor for a PrimeNG/vSuite UI component.

    This is the single source of truth for how to interact with a
    specific component type. Replaces the fragmented knowledge from
    component_registry.json + selector_registry.json + human_guidance.md.

    Attributes
    ----------
    key : str
        Component identifier (e.g., ``"p-calendar"``, ``"p-select"``).
    description : str
        Human-readable description of the component.
    primeng_versions : list[str]
        Supported PrimeNG versions.
    selectors : list[SelectorStrategy]
        Ordered selector strategies (highest confidence first).
    interaction_protocol : list[InteractionStep]
        Step-by-step interaction sequence.
    forbidden_patterns : list[str]
        Actions/selectors that will always fail on this component.
    angular_quirks : list[str]
        PrimeNG/Angular-specific gotchas.
    animation_budget : AnimationBudget
        Timing constraints for animations and debounce.
    trigger_keywords : list[str]
        AC step keywords that indicate this component is relevant.
    related_recipe : str
        Name of the YAML recipe that handles this component atomically
        (e.g., ``"p_calendar_single"``). Empty if no recipe exists.
    """

    key: str = ""
    description: str = ""
    primeng_versions: list[str] = field(default_factory=lambda: ["v17", "v18", "v19"])
    selectors: list[SelectorStrategy] = field(default_factory=list)
    interaction_protocol: list[InteractionStep] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    angular_quirks: list[str] = field(default_factory=list)
    animation_budget: AnimationBudget = field(default_factory=AnimationBudget)
    trigger_keywords: list[str] = field(default_factory=list)
    related_recipe: str = ""


# ---------------------------------------------------------------------------
# Unified Registry
# ---------------------------------------------------------------------------


class UnifiedRegistry:
    """Consolidated component interaction registry.

    Loads from ``knowledge/unified_components.json`` and provides
    a single ``lookup(component_key)`` interface.

    Usage::

        from backend.kb.unified_registry import unified_registry

        # Lookup a component
        comp = unified_registry.lookup("p-calendar")
        if comp:
            print(comp.interaction_protocol)
            print(comp.forbidden_patterns)

        # Detect components from AC step text
        detected = unified_registry.detect_components("select a due date")
        # → ["p-calendar"]

        # Get formatted rules for prompt injection
        rules = unified_registry.get_rules_for_prompt(detected)
    """

    def __init__(self) -> None:
        self._components: dict[str, ComponentInteraction] = {}
        self._loaded: bool = False

    def _ensure_loaded(self) -> None:
        """Lazy-load the registry from disk on first access."""
        if self._loaded:
            return
        self._loaded = True

        if not _UNIFIED_PATH.exists():
            logger.info(
                "Unified registry not found at %s — will use legacy registries",
                _UNIFIED_PATH,
            )
            return

        try:
            raw = json.loads(_UNIFIED_PATH.read_text(encoding="utf-8"))
            for key, data in raw.get("components", {}).items():
                comp = ComponentInteraction(
                    key=key,
                    description=data.get("description", ""),
                    primeng_versions=data.get("primeng_versions", ["v17", "v18", "v19"]),
                    forbidden_patterns=data.get("forbidden_patterns", []),
                    angular_quirks=data.get("angular_quirks", []),
                    trigger_keywords=data.get("trigger_keywords", []),
                    related_recipe=data.get("related_recipe", ""),
                )

                # Parse selectors
                for sel_data in data.get("selectors", []):
                    comp.selectors.append(
                        SelectorStrategy(
                            method=sel_data.get("method", ""),
                            role=sel_data.get("role", ""),
                            name=sel_data.get("name", ""),
                            selector=sel_data.get("selector", ""),
                            primeng_versions=sel_data.get("primeng_versions", ["v17", "v18", "v19"]),
                            confidence=sel_data.get("confidence", 0.5),
                            notes=sel_data.get("notes", ""),
                        )
                    )

                # Parse interaction protocol
                for step_data in data.get("interaction_protocol", []):
                    comp.interaction_protocol.append(
                        InteractionStep(
                            action=step_data.get("action", ""),
                            strategy=step_data.get("strategy", ""),
                            selector=step_data.get("selector", ""),
                            value=step_data.get("value", ""),
                            wait_after_ms=step_data.get("wait_after_ms", 0),
                            notes=step_data.get("notes", ""),
                        )
                    )

                # Parse animation budget
                anim = data.get("animation_budget", {})
                if anim:
                    comp.animation_budget = AnimationBudget(
                        open_ms=anim.get("open_ms", 200),
                        close_ms=anim.get("close_ms", 100),
                        debounce_ms=anim.get("debounce_ms", 0),
                        verifier_wait_ms=anim.get("verifier_wait_ms", 300),
                    )

                self._components[key] = comp

            logger.info(
                "Unified registry loaded: %d components from %s",
                len(self._components),
                _UNIFIED_PATH.name,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load unified registry: %s", e)

    def lookup(self, component_key: str) -> Optional[ComponentInteraction]:
        """Look up a component by its key.

        Parameters
        ----------
        component_key : str
            Component identifier (e.g., ``"p-calendar"``).

        Returns
        -------
        ComponentInteraction or None
            The component descriptor, or None if not found.
        """
        self._ensure_loaded()
        return self._components.get(component_key)

    def detect_components(self, ac_step_text: str) -> list[str]:
        """Detect which components are relevant to an AC step.

        Uses keyword matching against trigger_keywords.

        Parameters
        ----------
        ac_step_text : str
            The current AC step text.

        Returns
        -------
        list[str]
            Component keys detected (most specific first).
        """
        self._ensure_loaded()
        if not ac_step_text:
            return []

        step_lower = ac_step_text.lower()
        detected: list[str] = []

        for key, comp in self._components.items():
            if any(kw in step_lower for kw in comp.trigger_keywords):
                detected.append(key)

        return detected

    def get_rules_for_prompt(self, component_keys: list[str]) -> str:
        """Build formatted rules for prompt injection.

        For each component, includes:
          - Interaction protocol steps
          - Forbidden patterns
          - Angular quirks
          - Animation budget

        Parameters
        ----------
        component_keys : list[str]
            Component keys from detect_components().

        Returns
        -------
        str
            Formatted rules block, or empty string if no components.
        """
        self._ensure_loaded()
        if not component_keys:
            return ""

        sections: list[str] = []

        for key in component_keys:
            comp = self._components.get(key)
            if not comp:
                continue

            lines: list[str] = [f"\n  [{key.upper()}] — {comp.description}"]

            # Selectors (highest confidence first)
            sorted_sels = sorted(comp.selectors, key=lambda s: s.confidence, reverse=True)
            if sorted_sels:
                lines.append("    Selectors (by confidence):")
                for sel in sorted_sels[:5]:
                    label = f"{sel.method}"
                    if sel.role:
                        label += f"('{sel.role}', name='{sel.name}')"
                    elif sel.selector:
                        label += f" → {sel.selector}"
                    elif sel.name:
                        label += f"('{sel.name}')"
                    lines.append(
                        f"      {sel.confidence:.0%} {label}"
                        + (f"  [{', '.join(sel.primeng_versions)}]" if sel.primeng_versions else "")
                    )

            # Interaction protocol
            if comp.interaction_protocol:
                lines.append("    Protocol:")
                for i, step in enumerate(comp.interaction_protocol, 1):
                    step_desc = f"      {i}. {step.action}"
                    if step.selector:
                        step_desc += f" → {step.selector}"
                    if step.value:
                        step_desc += f" value={step.value}"
                    if step.wait_after_ms:
                        step_desc += f" (wait {step.wait_after_ms}ms after)"
                    if step.notes:
                        step_desc += f"\n         ℹ️  {step.notes}"
                    lines.append(step_desc)

            # Recipe hint
            if comp.related_recipe:
                lines.append(f'    ⚡ Use recipe: action="recipe", recipe_name="{comp.related_recipe}"')

            # Forbidden patterns
            if comp.forbidden_patterns:
                lines.append("    ⛔ FORBIDDEN:")
                for fp in comp.forbidden_patterns:
                    lines.append(f"      - {fp}")

            # Angular quirks
            if comp.angular_quirks:
                lines.append("    ⚠️ Quirks:")
                for q in comp.angular_quirks:
                    lines.append(f"      - {q}")

            sections.append("\n".join(lines))

        if not sections:
            return ""

        joined = "\n".join(sections)
        return (
            "\n═══════════════════════════════════════════════════════════════\n"
            "🔧 UNIFIED COMPONENT REGISTRY — Interaction Protocols:\n"
            "═══════════════════════════════════════════════════════════════"
            + joined
            + "\n═══════════════════════════════════════════════════════════════"
        )

    @property
    def is_loaded(self) -> bool:
        """Return True if the unified registry has data loaded."""
        self._ensure_loaded()
        return bool(self._components)

    def get_all_keys(self) -> list[str]:
        """Return all registered component keys."""
        self._ensure_loaded()
        return list(self._components.keys())


# Module-level singleton (lazy-loaded)
unified_registry = UnifiedRegistry()
