"""
vQA — Test Source Adapters Package
====================================
Module: backend/adapters/__init__.py

Exports ``get_adapter()`` factory for resolving test source adapters
by ``source_type``.

Usage
-----
    from backend.adapters import get_adapter

    adapter = get_adapter("jira")
    result = await adapter.fetch_ac("VC2-8967")

    adapter = get_adapter("raw_text")
    result = await adapter.fetch_ac("Given I click Save\\nThen I see a toast")
"""

from __future__ import annotations

import logging

from backend.adapters.base import ACResult, TestSourceAdapter

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependency issues
_ADAPTER_REGISTRY: dict[str, type[TestSourceAdapter]] = {}


def _ensure_registered() -> None:
    """Lazily register all built-in adapters on first call."""
    if _ADAPTER_REGISTRY:
        return

    from backend.adapters.github_adapter import GitHubAdapter
    from backend.adapters.jira_adapter import JiraAdapter
    from backend.adapters.raw_text_adapter import RawTextAdapter

    _ADAPTER_REGISTRY["jira"] = JiraAdapter
    _ADAPTER_REGISTRY["raw_text"] = RawTextAdapter
    _ADAPTER_REGISTRY["github"] = GitHubAdapter

    logger.debug(
        "adapters: registered %d adapters — %s",
        len(_ADAPTER_REGISTRY),
        list(_ADAPTER_REGISTRY.keys()),
    )


def get_adapter(source_type: str = "jira") -> TestSourceAdapter:
    """
    Resolve a test source adapter by type.

    Parameters
    ----------
    source_type : str
        One of ``"jira"`` (default), ``"raw_text"``, ``"github"``.

    Returns
    -------
    TestSourceAdapter
        An instantiated adapter ready for ``fetch_ac()``.

    Raises
    ------
    ValueError
        If ``source_type`` is not a registered adapter.
    """
    _ensure_registered()

    adapter_cls = _ADAPTER_REGISTRY.get(source_type)
    if adapter_cls is None:
        available = ", ".join(sorted(_ADAPTER_REGISTRY.keys()))
        raise ValueError(f"Unknown source_type '{source_type}'. Available adapters: {available}")

    return adapter_cls()


def resolve_adapter_auto(identifier: str) -> TestSourceAdapter:
    """
    Auto-detect and return the appropriate adapter from the identifier format.

    This is a convenience wrapper around ``adapter_factory.resolve_adapter()``.

    Parameters
    ----------
    identifier : str
        Jira key, GitHub URL/shorthand, or raw AC text.

    Returns
    -------
    TestSourceAdapter
        The appropriate adapter instance.
    """
    from backend.adapters.adapter_factory import resolve_adapter

    return resolve_adapter(identifier)


__all__ = [
    "ACResult",
    "TestSourceAdapter",
    "get_adapter",
    "resolve_adapter_auto",
]
