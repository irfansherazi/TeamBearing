"""
vQA — AC-parser ARIA Enrichment Pass (Phase 3 — accessibility-tree-grounding)
=============================================================================
Module: backend/engine/ac_aria_enricher.py

Post-compilation deterministic Python pass that populates ``aria_role`` and
``aria_name`` on each ``TestPlanStep`` from the live ARIA snapshot captured by
``page.accessibility.snapshot()``.

Architecture Decision 2 (accessibility-tree-grounding-architecture.md):
  Enrichment runs as a **post-compile Python pass** invoked from
  ``planner_node`` on **first entry** (``iteration == 1``) after the page is
  fully loaded (post-``login_node``).  The pass is **NOT** done inside
  ``ac_parser_node``, which runs *before* the login node and therefore has no
  live ARIA tree to inspect — doing it there would require the LLM to
  hallucinate ARIA values (violates AC-VERIFY-2).

  The enricher calls ``page.accessibility.snapshot()`` once per enrichment
  invocation (not per step) and walks the test-plan steps to find a matching
  ARIA node for each ``target_component``.  Matching uses a two-tier strategy:

    Tier 1 — ``target_element_types`` hint (from ``schemas.py:244``):
      If the step carries ``target_element_types``, only ARIA nodes whose role
      is in that list are considered, shrinking the search space dramatically.

    Tier 2 — accessible-name contains ``target_component`` text:
      Among the role-filtered candidates, the first node whose ``name``
      contains the step's ``target_component`` string (case-insensitive,
      stripped) is selected.  This is deliberately conservative — no fuzzy
      matching — to avoid false-positive ARIA enrichment.

  On a match, ``aria_role`` and ``aria_name`` are set on the step dict
  in-place.  Unmatched steps are left unchanged (``aria_role=None``).

Feature Flag:
  ``settings.a11y_enrichment_enabled`` (default ``False``).
  The enricher is a no-op when the flag is off — zero behavior change for
  existing runs.

Performance:
  ``page.accessibility.snapshot()`` adds ~30-80 ms (one call per enrichment
  run).  The ARIA tree walk is O(N) where N is the pruned node count (≤ 75
  after ``accessibility.py`` pruning).  Total overhead is < 100 ms per planner
  first-entry — well within the 15 s per-step NFR.

Observability:
  Logs at DEBUG level:
  - Node count in the ARIA snapshot
  - Per-step enrichment result (``aria_role``, ``aria_name``, or "no match")
  At INFO level:
  - Summary: "enriched N/M steps" with a hit-rate for the run
"""

import logging
from typing import Any

from playwright.async_api import Page

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def enrich_test_plan_with_aria(
    page: Page,
    test_plan: dict[str, Any],
    run_id: str = "unknown",
) -> dict[str, Any]:
    """Populate ``aria_role`` / ``aria_name`` on each ``TestPlanStep`` dict.

    This function is the single entry point called from ``planner_node`` on
    the first iteration.  It is a **no-op** when
    ``settings.a11y_enrichment_enabled`` is ``False``, returning the test plan
    unchanged.

    The function mutates the **step dicts inside** ``test_plan["steps"]``
    in-place (the list and each dict are mutable; callers hold the same
    reference).  The updated test plan is also returned for convenience.

    Args:
        page: The live Playwright page (must be post-login).
        test_plan: The compiled test plan dict (``{"steps": [...], ...}``).
        run_id: The current run identifier (for structured logging).

    Returns:
        The (possibly mutated) test plan dict.
    """
    if not settings.a11y_enrichment_enabled:
        logger.debug("[%s] ac_aria_enricher: a11y_enrichment_enabled=False — skipping.", run_id)
        return test_plan

    steps: list[dict[str, Any]] = test_plan.get("steps", [])
    if not steps:
        logger.debug("[%s] ac_aria_enricher: test plan has no steps — skipping.", run_id)
        return test_plan

    # ── Step 1: Capture the live ARIA snapshot (once per enrichment run) ──
    try:
        snapshot = await page.accessibility.snapshot()
    except Exception as exc:
        logger.warning(
            "[%s] ac_aria_enricher: page.accessibility.snapshot() raised %s — "
            "enrichment skipped for this run.",
            run_id,
            exc,
        )
        return test_plan

    if snapshot is None:
        logger.debug("[%s] ac_aria_enricher: ARIA snapshot is None — skipping.", run_id)
        return test_plan

    # ── Step 2: Flatten the ARIA tree into a list of (role, name) nodes ──
    aria_nodes: list[dict[str, str]] = []
    _flatten_aria_tree(snapshot, aria_nodes)
    logger.debug(
        "[%s] ac_aria_enricher: ARIA snapshot contains %d nodes.",
        run_id,
        len(aria_nodes),
    )

    # ── Step 3: Enrich each step ──────────────────────────────────────────
    enriched_count = 0
    for step in steps:
        # Skip steps that already have ARIA fields (e.g. from a prior pass)
        if step.get("aria_role") or step.get("aria_name"):
            continue

        target: str = step.get("target_component", "") or ""
        target_stripped = target.strip()
        if not target_stripped:
            continue

        # ``target_element_types`` narrows which ARIA roles to consider
        candidate_roles: list[str] | None = step.get("target_element_types") or None

        matched = _find_aria_node(aria_nodes, target_stripped, candidate_roles)
        if matched:
            step["aria_role"] = matched["role"]
            step["aria_name"] = matched["name"]
            enriched_count += 1
            logger.debug(
                "[%s] ac_aria_enricher: step %d '%s' → aria_role=%r aria_name=%r",
                run_id,
                step.get("step_index", "?"),
                target_stripped[:60],
                matched["role"],
                matched["name"],
            )
        else:
            logger.debug(
                "[%s] ac_aria_enricher: step %d '%s' → no ARIA match.",
                run_id,
                step.get("step_index", "?"),
                target_stripped[:60],
            )

    logger.info(
        "[%s] ac_aria_enricher: enriched %d/%d steps (aria_enrichment_hit_rate=%.0f%%).",
        run_id,
        enriched_count,
        len(steps),
        (enriched_count / len(steps) * 100) if steps else 0,
    )
    return test_plan


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flatten_aria_tree(
    node: dict[str, Any],
    result: list[dict[str, str]],
) -> None:
    """Recursively flatten an ARIA snapshot tree into a flat list of nodes.

    Each entry in *result* is a ``{"role": str, "name": str}`` dict.
    Nodes with empty or absent ``name`` are included (the matcher may still
    use role-only matching in future extensions) but will not satisfy the
    Tier-2 name-contains check.

    Args:
        node: A single node from the Playwright ARIA snapshot.
        result: Accumulator list — populated in-place (DFS order).
    """
    role: str = (node.get("role") or "").strip()
    name: str = (node.get("name") or "").strip()
    if role:
        result.append({"role": role, "name": name})
    for child in node.get("children") or []:
        _flatten_aria_tree(child, result)


def _find_aria_node(
    nodes: list[dict[str, str]],
    target_component: str,
    candidate_roles: list[str] | None,
) -> dict[str, str] | None:
    """Return the first ARIA node that matches *target_component*.

    Two-tier matching (conservative — no fuzzy matching):

    Tier 1 (role filter):
      If ``candidate_roles`` is provided and non-empty, only nodes whose
      ``role`` is in that list are examined.

    Tier 2 (name contains):
      Among the role-filtered candidates, select the first node whose
      ``name`` contains ``target_component`` (case-insensitive, stripped).

    Returns ``None`` if no match is found.

    Args:
        nodes: Flattened ARIA node list from ``_flatten_aria_tree``.
        target_component: The step's CSS selector or descriptive text used as
            the lookup key.
        candidate_roles: Optional list of ARIA roles to narrow the search.
            Pass ``None`` or ``[]`` to consider all roles.

    Returns:
        A ``{"role": str, "name": str}`` dict for the best-matching node, or
        ``None`` when no match was found.
    """
    target_lower = target_component.lower()

    # Build the candidate set (role-filtered if hints are available)
    if candidate_roles:
        role_set = {r.lower() for r in candidate_roles}
        candidates = [n for n in nodes if n["role"].lower() in role_set]
        if not candidates:
            # No role matches — fall back to searching all nodes (graceful)
            candidates = nodes
    else:
        candidates = nodes

    # Tier 2: name-contains check
    for node in candidates:
        if node["name"] and target_lower in node["name"].lower():
            return node

    return None
