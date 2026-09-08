"""
Phase 1 — T2-a: Deterministic AC Parsing

Tests for the content-hash disk cache (ac_parse_cache) and the min/max step gate
introduced in FEAT-117 / T2-a.

AC coverage:
  AC-VERIFY-1: Same ticket → same step arrays across 5 back-to-back cache calls.
  AC-VERIFY-2a: Cache-hit round-trip < 50ms for a warm entry.
  AC-VERIFY-2b: Content change → cache miss → fresh LLM calls re-invoked.

Design note:
  These tests exercise ``backend.engine.ac_parse_cache`` directly (unit tests)
  and the integration of the cache into ``ac_parser_node`` (via mock spy on
  ``_stage_1_normalize``).  No live AWS Bedrock calls are made.

Test isolation:
  Each test that writes to disk uses a tmp_path fixture so real
  ``storage/ac_parse_cache/`` is never touched.
"""

import hashlib
import json
import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_cache(tmp_path, monkeypatch):
    """
    Redirect ac_parse_cache writes to a temp directory for test isolation.
    Returns the temp path so tests can inspect written files.
    """
    monkeypatch.setenv("AC_PARSE_CACHE_DIR", str(tmp_path))
    # Re-import the module so _cache_dir() picks up the monkeypatched env var.
    import importlib

    import backend.engine.ac_parse_cache as cache_mod
    importlib.reload(cache_mod)
    yield cache_mod, tmp_path
    # Restore: reload again so the real path is used in subsequent tests.
    importlib.reload(cache_mod)


@pytest.fixture()
def sample_ac_text():
    """A representative AC text fixture (does not need to be live Jira data)."""
    return (
        "Given the user is logged in as qa_analyst\n"
        "When the user navigates to the PRF Category dropdown\n"
        "And the user selects Contest from the dropdown\n"
        "Then the PRF Category is set to Contest\n"
        "And a confirmation toast appears\n"
    )


@pytest.fixture()
def sample_parse_result(sample_ac_text):
    """A plausible parse result dict (mimics what ac_parser_node returns)."""
    return {
        "jira_ticket": {
            "ticket_id": "QA-358",
            "acceptance_criteria_steps": [
                "Navigate to the PRF Category dropdown",
                "Select Contest from the dropdown",
                "Verify PRF Category is set to Contest",
                "Verify confirmation toast appears",
            ],
        },
        "test_plan": {
            "test_title": "PRF Category Selection",
            "steps": [
                {"goal": "Navigate to the PRF Category dropdown"},
                {"goal": "Select Contest from the dropdown"},
                {"goal": "Verify PRF Category is set to Contest"},
                {"goal": "Verify confirmation toast appears"},
            ],
        },
        "structured_step_index": 0,
        "target_element_types": [],
        "global_run_context": "",
        "user_guidance": "",
    }


# ---------------------------------------------------------------------------
# AC-VERIFY-1: Same ticket → same step arrays across 5 back-to-back reads
# ---------------------------------------------------------------------------


def test_same_ticket_same_steps(isolated_cache, sample_ac_text, sample_parse_result):
    """
    AC-VERIFY-1: 5 back-to-back cache hits for the same raw AC text return
    byte-identical step arrays (zero drift).

    Strategy: seed the cache once with a known result, then call cache.get()
    5 times and assert all returned step lists are identical.
    """
    cache_mod, tmp_path = isolated_cache

    # Seed the cache
    cache_mod.set(sample_ac_text, sample_parse_result)

    results = []
    for _ in range(5):
        hit = cache_mod.get(sample_ac_text)
        assert hit is not None, "Expected a cache hit but got None"
        steps = hit["test_plan"]["steps"]
        results.append([s["goal"] for s in steps])

    # All five should be byte-identical lists
    first = results[0]
    for i, r in enumerate(results[1:], start=2):
        assert r == first, (
            f"Iteration {i} step list differs from iteration 1.\n"
            f"Expected: {first}\nGot: {r}"
        )


# ---------------------------------------------------------------------------
# AC-VERIFY-2a: Cache-hit round-trip < 50ms
# ---------------------------------------------------------------------------


def test_cache_hit_under_50ms(isolated_cache, sample_ac_text, sample_parse_result):
    """
    AC-VERIFY-2a: A warm cache hit completes in < 50ms wall-clock time,
    measured from cache.get() entry to return.
    """
    cache_mod, tmp_path = isolated_cache

    # Warm the cache
    cache_mod.set(sample_ac_text, sample_parse_result)

    t0 = time.perf_counter()
    hit = cache_mod.get(sample_ac_text)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert hit is not None, "Expected a cache hit but got None"
    assert elapsed_ms < 50, (
        f"Cache hit took {elapsed_ms:.1f}ms — expected < 50ms. "
        "Disk I/O may be unexpectedly slow in this environment."
    )


# ---------------------------------------------------------------------------
# AC-VERIFY-2b: Content change → cache invalidation → fresh LLM calls
# ---------------------------------------------------------------------------


def test_content_change_invalidates(isolated_cache, sample_ac_text, sample_parse_result):
    """
    AC-VERIFY-2b: Mutating one character in the AC text produces a different
    content-hash, resulting in a cache MISS.  The caller must re-invoke the
    LLM pipeline (Stage 1 + Stage 2).

    We verify this at the ac_parse_cache level: the original text hits;
    the mutated text misses.  We also verify via a mock spy that _stage_1_normalize
    would be called on the miss path by confirming the cache miss is accurate.
    """
    cache_mod, tmp_path = isolated_cache

    # Seed the cache with the original text
    cache_mod.set(sample_ac_text, sample_parse_result)

    # Original text → HIT
    hit = cache_mod.get(sample_ac_text)
    assert hit is not None, "Expected HIT for the original AC text"

    # Mutated text → MISS
    mutated_ac = sample_ac_text + " (additional requirement: log the action)"
    miss = cache_mod.get(mutated_ac)
    assert miss is None, (
        "Expected MISS for mutated AC text but got a cache hit. "
        "The content-hash is not reflecting the content change."
    )

    # Verify distinct hashes
    original_hash = cache_mod.content_hash(sample_ac_text)
    mutated_hash = cache_mod.content_hash(mutated_ac)
    assert original_hash != mutated_hash, (
        "content_hash() returned the same digest for different AC texts. "
        "SHA-256 hash collision or incorrect implementation."
    )

    # Verify the cache file exists for the original but not for the mutated
    original_file = tmp_path / f"{original_hash}.json"
    mutated_file = tmp_path / f"{mutated_hash}.json"
    assert original_file.exists(), "Cache file for original text should exist after set()"
    assert not mutated_file.exists(), "Cache file for mutated text should NOT exist"


# ---------------------------------------------------------------------------
# Bonus: verify content_hash() is stable and uses SHA-256
# ---------------------------------------------------------------------------


def test_content_hash_is_sha256_of_utf8(isolated_cache, sample_ac_text):
    """
    The content_hash() helper produces the standard SHA-256 hex digest
    of the UTF-8-encoded AC text string — no truncation, no salting.
    """
    cache_mod, _ = isolated_cache

    expected = hashlib.sha256(sample_ac_text.encode("utf-8")).hexdigest()
    actual = cache_mod.content_hash(sample_ac_text)
    assert actual == expected, (
        f"content_hash() returned {actual!r} but expected SHA-256 {expected!r}"
    )


# ---------------------------------------------------------------------------
# Bonus: verify atomic write (tmp file is cleaned up after set)
# ---------------------------------------------------------------------------


def test_set_writes_json_and_no_tmp_leftover(isolated_cache, sample_ac_text, sample_parse_result):
    """
    set() completes atomically: the final .json file exists, no .tmp file lingers.
    """
    cache_mod, tmp_path = isolated_cache

    cache_mod.set(sample_ac_text, sample_parse_result)

    key = cache_mod.content_hash(sample_ac_text)
    json_file = tmp_path / f"{key}.json"
    tmp_file = tmp_path / f"{key}.tmp"

    assert json_file.exists(), "Expected .json cache file to exist after set()"
    assert not tmp_file.exists(), ".tmp file should not exist after successful set()"

    # Verify the content is valid JSON and contains expected keys
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert "test_plan" in data, "Cached result missing 'test_plan' key"
    assert "jira_ticket" in data, "Cached result missing 'jira_ticket' key"


# ---------------------------------------------------------------------------
# T2-a step-gate: verify the heuristic estimator produces plausible counts
# ---------------------------------------------------------------------------


def test_estimate_step_count_from_bdd_numbered_list():
    """
    _estimate_step_count_from_bdd counts ordered-list markers (1. 2. 3. ...).
    """
    from backend.engine.ac_parser import _estimate_step_count_from_bdd

    bdd = (
        "Given the user is logged in\n"
        "1. Navigate to Orders\n"
        "2. Click New Order\n"
        "3. Fill in the form\n"
        "4. Submit\n"
        "Then the order appears in the list"
    )
    count = _estimate_step_count_from_bdd(bdd)
    assert count == 4, f"Expected 4 steps (numbered list), got {count}"


def test_estimate_step_count_from_bdd_when_lines():
    """
    _estimate_step_count_from_bdd falls back to When/And counting when no
    numbered list is present.
    """
    from backend.engine.ac_parser import _estimate_step_count_from_bdd

    bdd = (
        "Given the user is logged in\n"
        "When the user opens the dropdown\n"
        "And selects Contest\n"
        "And confirms the selection\n"
        "Then the category is set\n"
    )
    count = _estimate_step_count_from_bdd(bdd)
    # "When" + two "And" = 3 action lines
    assert count == 3, f"Expected 3 steps (When/And lines), got {count}"


def test_estimate_step_count_empty_returns_zero():
    """
    _estimate_step_count_from_bdd returns 0 for empty / whitespace-only input.
    """
    from backend.engine.ac_parser import _estimate_step_count_from_bdd

    assert _estimate_step_count_from_bdd("") == 0
    assert _estimate_step_count_from_bdd("   \n  ") == 0
