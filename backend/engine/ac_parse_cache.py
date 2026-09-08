"""
vQA — Content-Hash AC Parse Cache (FEAT-117 / T2-a)
====================================================

Persistent disk cache for AC parse results, keyed by SHA-256 of the raw
Acceptance Criteria text.  A hit means the SAME raw AC text was previously
parsed — both Stage 1 and Stage 2 LLM calls are skipped entirely.

Design decisions (from architecture creative doc, Q3 Option 3C):
  - Cache key: SHA-256(raw_ac.encode("utf-8")) — pure content hash, no
    ticket ID or guidance in the key.  If the AC text is identical, the
    parse result is deterministic (temp=0.0, schema-constrained).
  - Storage: ``storage/ac_parse_cache/<hash>.json`` — one JSON file per
    unique AC text.  Survives process restarts; survives Docker rebuilds if
    ``storage/`` is volume-mounted.
  - Invalidation: content change (different SHA-256) → automatic miss.
    There is no TTL because the AC text itself IS the cache key; a changed
    AC produces a new key automatically.
  - Thread safety: each ``set()`` is a rename-atomic write (write to
    ``<hash>.tmp`` then ``os.replace``).  Concurrent readers never see a
    partial file.
  - Failure mode: any read/write error is non-fatal — logged at WARNING
    and the caller falls through to the LLM path.

Integration with the existing ``ACStepCache`` (``backend/jira/cache.py``):
  This cache sits ABOVE ``ACStepCache``.  On a content-hash HIT, we skip
  both Stage 1 and Stage 2 calls AND the ``ACStepCache.set()`` call
  (the result is already on disk).  On a MISS we let the existing pipeline
  run and call ``set()`` with the freshly-compiled result.

Observable at:
  - INFO log ``ac_parse_cache: HIT <hash>`` — in backend process log
  - Files at ``storage/ac_parse_cache/<hash>.json``
"""

import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cache directory (configurable via env var for test isolation)
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_DIR_ENV = "AC_PARSE_CACHE_DIR"
_DEFAULT_CACHE_DIR = Path("storage/ac_parse_cache")


def _cache_dir() -> Path:
    """Return the cache directory, creating it if needed."""
    env_override = os.environ.get(_DEFAULT_CACHE_DIR_ENV, "")
    base = Path(env_override) if env_override else _DEFAULT_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def content_hash(raw_ac: str) -> str:
    """Return the SHA-256 hex digest (64 chars) of the raw AC text."""
    return hashlib.sha256(raw_ac.encode("utf-8")).hexdigest()


def get(raw_ac: str) -> dict | None:
    """
    Look up a cached parse result by content hash.

    Returns the stored dict on HIT, None on MISS or any read error.

    Parameters
    ----------
    raw_ac : str
        The raw Acceptance Criteria text to hash and look up.

    Returns
    -------
    dict | None
        The cached parse result dict, or None on cache miss.
    """
    key = content_hash(raw_ac)
    cache_path = _cache_dir() / f"{key}.json"
    try:
        if not cache_path.exists():
            logger.debug("ac_parse_cache: MISS %s", key[:16])
            return None
        with cache_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        logger.info("ac_parse_cache: HIT %s", key[:16])
        return data
    except Exception as exc:
        logger.warning(
            "ac_parse_cache: read error for %s (non-fatal, falling through to LLM): %s",
            key[:16],
            exc,
        )
        return None


def set(raw_ac: str, result: dict) -> None:  # noqa: A001
    """
    Store a parse result under the content-hash of the raw AC text.

    Write is atomic: data is written to a ``.tmp`` file then renamed
    to the final path so concurrent readers never see a partial file.

    Parameters
    ----------
    raw_ac : str
        The raw AC text (used to derive the cache key).
    result : dict
        The parse result dict to store (must be JSON-serialisable).
    """
    key = content_hash(raw_ac)
    cache_path = _cache_dir() / f"{key}.json"
    tmp_path = cache_path.with_suffix(".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, default=str)
        os.replace(tmp_path, cache_path)
        logger.info("ac_parse_cache: SET %s", key[:16])
    except Exception as exc:
        logger.warning(
            "ac_parse_cache: write error for %s (non-fatal, result not cached): %s",
            key[:16],
            exc,
        )
        # Clean up temp file if it exists
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def invalidate(raw_ac: str) -> bool:
    """
    Remove the cached entry for the given raw AC text.

    Returns True if the entry existed and was removed, False if it was
    already absent.  Any removal error is logged and False is returned.

    Parameters
    ----------
    raw_ac : str
        The raw AC text whose cache entry should be removed.
    """
    key = content_hash(raw_ac)
    cache_path = _cache_dir() / f"{key}.json"
    try:
        cache_path.unlink()
        logger.info("ac_parse_cache: INVALIDATED %s", key[:16])
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.warning("ac_parse_cache: invalidate error for %s: %s", key[:16], exc)
        return False
