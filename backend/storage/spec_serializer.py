"""
vQA — Spec Serializer
======================
Module: backend/storage/spec_serializer.py

Utility functions for serializing, filtering, and hashing vQA test records.

These are pure functions with no filesystem dependencies — they operate only
on Python data structures and are therefore trivially testable.

Functions
---------
  compute_ac_hash(ac_steps)
      Compute a stable 12-char SHA-256 hash for a list of AC step strings.
      Used as the cache key for accepted test lookup.

  extract_replay_actions(execution_log)
      Filter an execution log to only the steps that should be replayed
      (success=True; failed/retried actions are excluded).

Author: vQA Build Agent (TASK-031 Phase 2)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_ac_hash(ac_steps: list[str]) -> str:
    """
    Compute a stable, short hash for a list of Acceptance Criteria steps.

    The hash is order-sensitive — two lists with the same steps in different
    orders produce different hashes, because test step order is semantically
    significant.

    Args
    ----
    ac_steps : list[str]
        The list of AC step strings from ``jira_ticket.acceptance_criteria_steps``.

    Returns
    -------
    str
        A 12-character hexadecimal prefix of the SHA-256 hash.
        Short enough to embed in filenames; collision probability is
        ~1 in 281 trillion for the typical fleet of ≤ 10,000 unique tickets.

    Examples
    --------
    >>> compute_ac_hash(["Log in", "Click Submit"])
    'a3f8c12de901'

    >>> compute_ac_hash(["Click Submit", "Log in"])  # Different order
    'b92f4701c0e3'                                   # Different hash
    """
    # Use json.dumps with sorted=False (we want order sensitivity) and
    # deterministic separators so the hash is stable across Python versions.
    canonical = json.dumps(ac_steps, sort_keys=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:12]


def extract_replay_actions(execution_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filter an execution log to only the actions that should be replayed.

    During a live AI-driven run, the executor may dispatch actions that fail
    (success=False) before self-healing succeeds.  These failed attempts must
    NOT be replayed — they would cause the replay to fail on the same element
    they originally failed on.

    Only actions where ``success=True`` are included.  The replay engine will
    dispatch them in the original order.

    Args
    ----
    execution_log : list[dict]
        Raw list of ``ExecutionStep`` dicts from ``VQAState.detailed_execution_log``.
        Each dict must contain at minimum ``success`` (bool) and
        ``action_payload`` (dict).

    Returns
    -------
    list[dict]
        Filtered list containing only successful steps, in their original order.
        Empty list if no steps succeeded.

    Notes
    -----
    The returned dicts preserve ALL original fields.  The replay engine
    uses ``action_payload`` for dispatching; other fields are kept for
    audit trail purposes.

    Examples
    --------
    >>> extract_replay_actions([
    ...     {"step_index": 0, "success": True,  "action_type": "click", ...},
    ...     {"step_index": 1, "success": False, "action_type": "fill",  ...},
    ...     {"step_index": 2, "success": True,  "action_type": "fill",  ...},
    ... ])
    [  # Returns steps 0 and 2 only
        {"step_index": 0, "success": True,  "action_type": "click", ...},
        {"step_index": 2, "success": True,  "action_type": "fill",  ...},
    ]
    """
    if not execution_log:
        return []

    replay_actions = [step for step in execution_log if step.get("success", False)]

    logger.debug(
        "extract_replay_actions: %d/%d steps passed filter (success=True)",
        len(replay_actions),
        len(execution_log),
    )

    return replay_actions
