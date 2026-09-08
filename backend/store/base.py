"""
vQA — Run State Store Base
==============================
Module: backend/store/base.py

Defines the ``RunStateStore`` abstract base class that all state
store backends must implement.

See Also
--------
  - ``backend/store/memory.py`` — in-memory implementation (default)
  - ``backend/store/redis.py``  — Redis-backed implementation
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RunStateStore(ABC):
    """
    Abstract base class for run state storage.

    All implementations must support async get/set/update/delete
    operations on run state dicts keyed by ``run_id``.
    """

    @abstractmethod
    async def get(self, run_id: str) -> dict[str, Any] | None:
        """
        Retrieve the state for a run.

        Returns ``None`` if the run does not exist.
        """
        ...

    @abstractmethod
    async def set(self, run_id: str, data: dict[str, Any]) -> None:
        """
        Create or replace the state for a run.
        """
        ...

    @abstractmethod
    async def update(self, run_id: str, **kwargs: Any) -> None:
        """
        Update specific fields in an existing run's state.

        Raises ``KeyError`` if the run does not exist.
        """
        ...

    @abstractmethod
    async def delete(self, run_id: str) -> None:
        """
        Delete a run's state.

        No-op if the run does not exist.
        """
        ...

    @abstractmethod
    async def exists(self, run_id: str) -> bool:
        """
        Check whether a run exists in the store.
        """
        ...

    @abstractmethod
    async def list_runs(self, status: str | None = None) -> list[str]:
        """
        List run IDs, optionally filtered by status.

        Parameters
        ----------
        status : str | None
            If provided, only return runs with this status.
            If ``None``, return all runs.
        """
        ...
