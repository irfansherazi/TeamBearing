"""
vQA — Worker Sub-Graphs
========================
Package: backend/engine/workers/

Specialised Worker nodes for the Supervisor-Worker architecture.

Workers
-------
  - GenericWorker    — catch-all wrapping the existing planner loop
  - TableWorker      — table navigation, scoped clicks, pagination
  - FormWorker       — PrimeNG form filling, dropdown selection
  - VerifyWorker     — read-only verification (no DOM mutation)
  - NavigateWorker   — URL-first navigation, vSuite route awareness
  - AuthWorker       — login, logout, role switching

Modules
-------
    variable_extractor  — Extract_And_Store_Variable tool for global memory

Usage
-----
    from backend.engine.workers import get_worker_node

    node_fn = get_worker_node("table")  # → table_worker_node
    result = await node_fn(state)
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker registry (lazy-loaded to avoid circular imports)
# ---------------------------------------------------------------------------

_WORKER_REGISTRY: dict[str, Callable] | None = None


def _ensure_registry() -> dict[str, Callable]:
    """Lazily build the worker registry on first access."""
    global _WORKER_REGISTRY
    if _WORKER_REGISTRY is not None:
        return _WORKER_REGISTRY

    from backend.engine.workers.auth_worker import auth_worker_node
    from backend.engine.workers.form_worker import form_worker_node
    from backend.engine.workers.generic_worker import generic_worker_node
    from backend.engine.workers.navigate_worker import navigate_worker_node
    from backend.engine.workers.table_worker import table_worker_node
    from backend.engine.workers.verify_worker import verify_worker_node

    _WORKER_REGISTRY = {
        "generic": generic_worker_node,
        "form": form_worker_node,
        "table": table_worker_node,
        "verify": verify_worker_node,
        "navigate": navigate_worker_node,
        "auth": auth_worker_node,
    }

    logger.debug(
        "workers: registered %d workers — %s",
        len(_WORKER_REGISTRY),
        list(_WORKER_REGISTRY.keys()),
    )
    return _WORKER_REGISTRY


def get_worker_node(worker_type: str) -> Callable:
    """
    Resolve a worker node function by worker_type.

    Parameters
    ----------
    worker_type : str
        One of ``"form"``, ``"table"``, ``"verify"``, ``"navigate"``,
        ``"auth"``, ``"generic"``.

    Returns
    -------
    Callable
        The async worker node function.
        Falls back to ``generic_worker_node`` for unknown types.
    """
    registry = _ensure_registry()
    node = registry.get(worker_type)

    if node is None:
        logger.warning(
            "workers: unknown worker_type '%s' — falling back to generic",
            worker_type,
        )
        node = registry["generic"]

    return node
