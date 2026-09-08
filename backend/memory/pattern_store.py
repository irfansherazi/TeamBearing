"""
vQA — Cross-Run Failure Pattern Store (FEAT-009)
===================================================
Module: backend/memory/pattern_store.py

Extracts, stores, and retrieves successful self-heal patterns from
completed runs so that future runs encountering the same failure can
skip the retry cycle and immediately use the working solution.

Pattern Lifecycle
-----------------
1. **Extraction** (end of run, called by reporter_node):
   The execution log is scanned for self-heal sequences:
   failure(selector_A) → failure(selector_B) → success(selector_C).
   The pattern (failed_selector, working_selector, component_type, ac_step_keywords)
   is stored with an evidence count.

2. **Injection** (start of each planner call):
   Before the first LLM call, the store is queried for patterns matching
   the current AC step keywords. Matching patterns are formatted as a
   LEARNED_CORRECTIONS block injected into the planner system prompt.

3. **Decay** (background):
   Patterns that haven't been reinforced within 30 days are expired.
   Evidence count increments on each re-observation.

Storage Format
--------------
JSON file at ``knowledge/selector_corrections.json``::

    {
        "<failed_selector>": {
            "working_selector": "<working_selector>",
            "working_strategy": "get_by_text",
            "component_type": "button",
            "ac_keywords": ["click", "submit", "order"],
            "evidence_count": 3,
            "first_seen": "2026-05-08T00:00:00Z",
            "last_seen": "2026-05-08T12:00:00Z",
            "ticket_ids": ["QA-280", "QA-281"]
        }
    }

Dependencies
------------
  - ``backend/engine/state.py`` — VQAState, ExecutionStep
  - ``backend/engine/reporter.py`` — calls extract_patterns at run end
  - ``backend/engine/planner.py`` — calls get_patterns_for_step at plan time
"""

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE_FILE = Path(__file__).parent.parent.parent / "knowledge" / "selector_corrections.json"
_DECAY_DAYS = 30
_MAX_PATTERNS = 200  # Hard cap to prevent unbounded growth
_lock = threading.Lock()


def _load_store() -> dict[str, dict]:
    """Load the pattern store from disk. Returns empty dict if not found."""
    if not _STORE_FILE.exists():
        return {}
    try:
        return json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Pattern store load error: %s", e)
        return {}


def _save_store(store: dict[str, dict]) -> None:
    """Persist the pattern store to disk."""
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
    """Extract lowercase keywords (4+ chars) from text."""
    raw = re.findall(r"[a-zA-Z]{4,}", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for w in raw:
        if w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= max_keywords:
            break
    return result


def extract_patterns(execution_log: list[dict], ticket_id: str = "", product: str = "") -> int:
    """
    Scan the execution log for self-heal success sequences and persist them.

    A self-heal pattern is detected when:
    - Step N fails with a locator error (timeout, strict mode)
    - Step N+k succeeds with a DIFFERENT locator targeting the same AC step

    Args
    ----
    execution_log : list[dict]
        The detailed_execution_log from VQAState.
    ticket_id : str
        Jira ticket ID for provenance.
    product : str
        Product slug this run targeted (e.g. ``"vpromedia"``, ``"vpromotions"``).
        Stored on each new pattern so ``get_patterns_for_step`` can scope
        retrieval — a vpromedia selector heal is not evidence for a
        vpromotions form. Empty = legacy pre-scoped pattern (shared across
        products for backwards compatibility).

    Returns
    -------
    int
        Number of new patterns extracted.
    """
    if not execution_log or len(execution_log) < 2:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    new_count = 0

    with _lock:
        store = _load_store()

        # Group steps by ac_step_index
        steps_by_ac: dict[int, list[dict]] = {}
        for step in execution_log:
            ac_idx = step.get("ac_step_index", -1)
            if ac_idx >= 0:
                steps_by_ac.setdefault(ac_idx, []).append(step)

        for ac_idx, steps in steps_by_ac.items():
            # Find failure→success transitions within the same AC step
            failures: list[dict] = []
            for step in steps:
                if not step.get("success", False):
                    failures.append(step)
                elif step.get("success", False) and failures:
                    # This step succeeded after one or more failures
                    working_locator = step.get("locator_value", "")
                    working_strategy = step.get("locator_strategy", "")
                    working_action = step.get("action_type", "")

                    if not working_locator:
                        failures.clear()
                        continue

                    # Extract AC step text for keyword matching
                    ac_text = step.get("llm_reasoning", "") or ""

                    for failed_step in failures:
                        failed_locator = failed_step.get("locator_value", "")
                        if not failed_locator or failed_locator == working_locator:
                            continue

                        # We found a pattern: failed_locator → working_locator
                        key = failed_locator[:120]  # Cap key length

                        if key in store:
                            # Reinforce existing pattern
                            store[key]["evidence_count"] = store[key].get("evidence_count", 0) + 1
                            store[key]["last_seen"] = now
                            if ticket_id and ticket_id not in store[key].get("ticket_ids", []):
                                store[key].setdefault("ticket_ids", []).append(ticket_id)
                            # Backfill product on first product-scoped observation
                            # of a legacy pattern (does not overwrite a pattern
                            # that was originally seen under a different product —
                            # cross-product reinforcement would defeat scoping).
                            if product and not store[key].get("product"):
                                store[key]["product"] = product
                        else:
                            # New pattern
                            store[key] = {
                                "working_selector": working_locator,
                                "working_strategy": working_strategy,
                                "component_type": working_action,
                                "ac_keywords": _extract_keywords(ac_text),
                                "evidence_count": 1,
                                "first_seen": now,
                                "last_seen": now,
                                "ticket_ids": [ticket_id] if ticket_id else [],
                                "product": product or "",
                            }
                            new_count += 1

                    failures.clear()  # Reset after successful resolution

        # Enforce max patterns cap
        if len(store) > _MAX_PATTERNS:
            # Remove oldest, lowest-evidence patterns
            sorted_keys = sorted(
                store.keys(),
                key=lambda k: (store[k].get("evidence_count", 0), store[k].get("last_seen", "")),
            )
            while len(store) > _MAX_PATTERNS:
                del store[sorted_keys.pop(0)]

        # Decay: remove patterns not seen in _DECAY_DAYS
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_DECAY_DAYS)).isoformat()
        expired_keys = [k for k, v in store.items() if v.get("last_seen", "") < cutoff]
        for k in expired_keys:
            del store[k]

        _save_store(store)

    if new_count > 0:
        logger.info(
            "Pattern store: extracted %d new self-heal patterns (total: %d, expired: %d)",
            new_count,
            len(store),
            len(expired_keys) if "expired_keys" in dir() else 0,
        )
    return new_count


def get_patterns_for_step(ac_step_text: str, max_results: int = 3, product: str = "") -> str:
    """
    Query the pattern store for corrections relevant to the current AC step.

    Returns a formatted prompt block for injection into the planner system prompt.

    Args
    ----
    ac_step_text : str
        The current AC step text.
    max_results : int
        Maximum number of patterns to return.
    product : str
        Product slug of the current run. When set, only patterns whose
        recorded product matches (or is empty for legacy pre-scoping patterns)
        are considered. Empty ``product`` = legacy behavior (return anything).

    Returns
    -------
    str
        Formatted LEARNED_CORRECTIONS block, or empty string if no matches.
    """
    store = _load_store()
    if not store:
        return ""

    step_keywords = set(_extract_keywords(ac_step_text, max_keywords=12))
    if not step_keywords:
        return ""

    # Score patterns by keyword overlap
    scored: list[tuple[float, str, dict]] = []
    for key, pattern in store.items():
        # Product scoping: reject patterns tagged with a DIFFERENT product.
        # Untagged (empty ``product``) patterns are legacy shared corrections
        # and remain visible to every run for backwards compat.
        pat_product = pattern.get("product", "") or ""
        if product and pat_product and pat_product != product:
            continue
        pattern_keywords = set(pattern.get("ac_keywords", []))
        if not pattern_keywords:
            continue
        overlap = len(step_keywords & pattern_keywords)
        if overlap == 0:
            continue
        # Score = overlap * evidence_count (prefer well-evidenced patterns)
        score = overlap * pattern.get("evidence_count", 1)
        scored.append((score, key, pattern))

    if not scored:
        return ""

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_results]

    lines = [
        "═══════════════════════════════════════════════════════════════",
        "⚡ LEARNED CORRECTIONS (from previous successful runs):",
        "═══════════════════════════════════════════════════════════════",
    ]
    for score, failed_sel, pattern in top:
        evidence = pattern.get("evidence_count", 1)
        working = pattern.get("working_selector", "?")
        strategy = pattern.get("working_strategy", "?")
        component_type = str(pattern.get("component_type") or "").strip().lower()
        # Scope tag guards the LLM against mis-applying a click-only correction
        # to a fill action (or vice versa) — e.g. get_by_text(...) is fillable
        # for a text node but not for a placeholder-labeled input.
        if component_type == "click":
            scope_tag = "  ⚠ APPLIES TO: click actions ONLY (do NOT use for fill/type)."
        elif component_type == "fill":
            scope_tag = "  ⚠ APPLIES TO: fill/type actions ONLY (do NOT use for click)."
        elif component_type:
            scope_tag = f"  ⚠ APPLIES TO: {component_type} actions."
        else:
            scope_tag = ""
        lines.append(
            f'  ❌ AVOID: "{failed_sel[:80]}"  '
            f'→  ✅ USE: strategy="{strategy}", selector="{working[:80]}" '
            f"(evidence: {evidence}x)"
        )
        if scope_tag:
            lines.append(scope_tag)
    lines.append("  These corrections were extracted from self-heal successes in prior runs.")
    lines.append("═══════════════════════════════════════════════════════════════")

    return "\n".join(lines)
