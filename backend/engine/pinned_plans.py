"""
backend/engine/pinned_plans.py
==============================

Pinned TestPlan Store — Lock B for the ``/vc`` pipeline's red→green transition.

Design:
  - Each ``save()`` call generates a UUID4 opaque ``plan_id``, serialises the
    TestPlan + metadata to ``storage/pinned_plans/<plan_id>.json``, and returns
    the id.
  - ``load(plan_id)`` reads the file, checks TTL, and either returns the
    TestPlan dict or raises ``PinnedPlanNotFound`` / ``PinnedPlanExpired``.
  - Missing plan_id → ``PinnedPlanNotFound`` (HTTP 404 at route layer).
  - Expired plan_id → ``PinnedPlanExpired`` + lazy delete (HTTP 410 at route layer).
  - ``prune_expired()`` is called at startup (lifespan) to eagerly remove stale
    files; returns the count of deleted files and logs the count.
  - Store directory is configurable via ``PINNED_PLANS_DIR`` env var (for test
    isolation) — defaults to ``storage/pinned_plans``.
  - No new external dependencies: stdlib ``json``, ``time``, ``pathlib``, ``uuid``,
    ``os``, ``logging``.

Observable via structured INFO logs:
  - ``pinned_plans SET <plan_id>``
  - ``pinned_plans HIT <plan_id>``
  - ``pinned_plans MISS <plan_id> reason=not_found``
  - ``pinned_plans MISS <plan_id> reason=expired``
  - ``pinned_plans PRUNED count=<N>``
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Store directory (configurable via env var for test isolation)
# ---------------------------------------------------------------------------

_STORE_DIR_ENV = "PINNED_PLANS_DIR"
_DEFAULT_STORE_DIR = Path("storage/pinned_plans")


def _store_dir() -> Path:
    """Return the store directory, creating it if needed."""
    env_override = os.environ.get(_STORE_DIR_ENV, "")
    base = Path(env_override) if env_override else _DEFAULT_STORE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# TTL helper (indirected so tests can monkeypatch it)
# ---------------------------------------------------------------------------


def _get_ttl_days() -> int:
    """Return the configured TTL in days from Settings (defaulting to 14)."""
    try:
        from backend.config import settings  # type: ignore[import]
        return settings.pinned_plan_ttl_days
    except Exception:
        return 14


def _ttl_seconds() -> float:
    """Return the TTL in seconds."""
    return _get_ttl_days() * 86_400.0


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PinnedPlanNotFound(KeyError):
    """Raised by load() when the plan_id file does not exist on disk."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        super().__init__(f"pinned plan not found: {plan_id}")


class PinnedPlanExpired(KeyError):
    """Raised by load() when the plan_id file exists but its TTL has elapsed."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        super().__init__(f"pinned plan expired: {plan_id}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save(test_plan: dict, acceptance_criteria: str) -> str:
    """
    Persist a TestPlan under an opaque UUID4 plan_id.

    Parameters
    ----------
    test_plan : dict
        The compiled TestPlan dict to pin.
    acceptance_criteria : str
        The raw AC text that generated the plan (stored for audit/tracing).

    Returns
    -------
    str
        The opaque plan_id (UUID4 hex string).

    Notes
    -----
    Each call generates a fresh UUID4 plan_id even for identical inputs.
    The pinned-plan store is NOT a content-addressed cache — two preview
    calls on the same AC produce two independent plan files, each with its
    own TTL clock.

    The write is atomic: the JSON is written to ``<plan_id>.tmp`` then
    renamed to ``<plan_id>.json`` so concurrent readers never see a partial
    file.
    """
    plan_id = uuid.uuid4().hex
    store = _store_dir()
    file_path = store / f"{plan_id}.json"
    tmp_path = store / f"{plan_id}.tmp"

    payload = {
        "plan_id": plan_id,
        "created_at": time.time(),
        "test_plan": test_plan,
        "acceptance_criteria": acceptance_criteria,
    }

    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, default=str)
    os.replace(tmp_path, file_path)

    logger.info("pinned_plans SET %s", plan_id)
    return plan_id


def load(plan_id: str) -> dict:
    """
    Load a pinned TestPlan by its opaque plan_id.

    Parameters
    ----------
    plan_id : str
        The opaque id returned by ``save()``.

    Returns
    -------
    dict
        The TestPlan dict, byte-identical to what was passed to ``save()``.

    Raises
    ------
    PinnedPlanNotFound
        If the plan_id file does not exist on disk.
    PinnedPlanExpired
        If the plan_id file exists but its ``created_at`` is older than
        ``pinned_plan_ttl_days`` (default 14).  The expired file is deleted
        from disk (lazy prune) before the exception is raised.
    """
    store = _store_dir()
    file_path = store / f"{plan_id}.json"

    if not file_path.exists():
        logger.info("pinned_plans MISS %s reason=not_found", plan_id)
        raise PinnedPlanNotFound(plan_id)

    with file_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    age_seconds = time.time() - float(payload["created_at"])
    if age_seconds > _ttl_seconds():
        # Lazy prune: delete expired file before raising
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("pinned_plans MISS %s reason=expired", plan_id)
        raise PinnedPlanExpired(plan_id)

    logger.info("pinned_plans HIT %s", plan_id)
    return payload["test_plan"]


def prune_expired() -> int:
    """
    Remove all expired pinned plan files from the store directory.

    Intended to be called once at application startup from the FastAPI
    lifespan on-startup block to prevent unbounded disk growth.

    Returns
    -------
    int
        The number of expired files deleted.

    Notes
    -----
    Files that cannot be read (corrupt JSON, missing fields) are treated as
    expired and deleted — better to require a re-preview than serve corrupt
    data.
    """
    store = _store_dir()
    ttl = _ttl_seconds()
    now = time.time()
    pruned = 0

    for file_path in store.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            created_at = float(payload.get("created_at", 0))
            if now - created_at > ttl:
                file_path.unlink(missing_ok=True)
                pruned += 1
        except Exception:
            # Corrupt / unreadable file — delete it
            try:
                file_path.unlink(missing_ok=True)
                pruned += 1
            except Exception:
                pass

    logger.info("pinned_plans PRUNED count=%d", pruned)
    return pruned
