"""
tests/test_memory_watch_runner.py
=================================
Unit tests for Memory Watch argv / validation helpers.
"""

import pytest

from backend.engine.memory_watch_runner import (
    MemoryWatchValidationError,
    build_memory_watch_argv,
    is_memory_watch_run_id,
    parse_memory_sample_line,
    parse_memory_verdict_line,
    validate_cycles,
    validate_env,
    validate_flow,
)

FLOW_CASES = [
    {
        "description": "accepts po-open-spot",
        "setup": lambda: "po-open-spot",
        "expectations": lambda result: result == "po-open-spot",
    },
    {
        "description": "accepts sidebar-open-close",
        "setup": lambda: "sidebar-open-close",
        "expectations": lambda result: result == "sidebar-open-close",
    },
]


@pytest.mark.parametrize("case", FLOW_CASES, ids=lambda c: c["description"])
def test_validate_flow_accepts(case):
    result = validate_flow(case["setup"]())
    assert case["expectations"](result)


def test_validate_flow_rejects_unknown():
    with pytest.raises(MemoryWatchValidationError):
        validate_flow("not-a-flow")


ENV_CASES = [
    {
        "description": "defaults-adjacent qa",
        "setup": lambda: "qa",
        "expectations": lambda result: result == "qa",
    },
    {
        "description": "accepts test",
        "setup": lambda: "test",
        "expectations": lambda result: result == "test",
    },
]


@pytest.mark.parametrize("case", ENV_CASES, ids=lambda c: c["description"])
def test_validate_env_accepts(case):
    result = validate_env(case["setup"]())
    assert case["expectations"](result)


def test_validate_env_rejects_prod():
    with pytest.raises(MemoryWatchValidationError):
        validate_env("prod")


def test_validate_cycles_accepts_five():
    assert validate_cycles(5) == 5


def test_validate_cycles_rejects_zero():
    with pytest.raises(MemoryWatchValidationError):
        validate_cycles(0)


def test_build_memory_watch_argv_includes_flags():
    cmd = build_memory_watch_argv("po-open-spot", "qa", 5)
    joined = " ".join(cmd)
    assert "--flow=po-open-spot" in joined
    assert "--env=qa" in joined
    assert "--cycles=5" in joined


def test_parse_sample_and_verdict_lines():
    sample = parse_memory_sample_line(
        'MEMORY_WATCH_SAMPLE {"cycle":0,"usedMb":42.0,"deltaMb":0,"gcRuns":3,"status":"watching"}'
    )
    assert sample is not None
    assert sample["cycle"] == 0
    verdict = parse_memory_verdict_line(
        'MEMORY_WATCH_VERDICT {"pass":true,"growthMb":8.0,"reason":"ok"}'
    )
    assert verdict is not None
    assert verdict["pass"] is True


RUN_ID_CASES = [
    {
        "description": "accepts mw- plus 8 hex chars",
        "setup": lambda: "mw-abcd1234",
        "expect_ok": True,
    },
    {
        "description": "rejects path traversal",
        "setup": lambda: "../etc",
        "expect_ok": False,
    },
]


@pytest.mark.parametrize("case", RUN_ID_CASES, ids=lambda c: c["description"])
def test_is_memory_watch_run_id(case):
    assert is_memory_watch_run_id(case["setup"]()) is case["expect_ok"]


def test_require_run_id_rejects_bad_ids():
    from fastapi import HTTPException

    from backend.api.memory_watch_routes import _require_run_id

    assert _require_run_id("mw-abcd1234") == "mw-abcd1234"
    with pytest.raises(HTTPException) as exc:
        _require_run_id("../etc")
    assert exc.value.status_code == 422
