"""
tests/test_ai_review_runs.py
============================
Unit tests for AI Review history SQLite store.
"""

from pathlib import Path

import pytest

from backend.storage.ai_review_runs import AiReviewRunStore

CREATE_CASES = [
    {
        "description": "create_run stores a running row with branch metadata",
        "setup": lambda: {
            "review_id": "ar-abcd1234",
            "branch": "Syed/VC2-9167",
            "base": "Develop",
            "commits": "",
        },
        "expectations": lambda item: (
            item["status"] == "running"
            and item["branch"] == "Syed/VC2-9167"
            and item["base"] == "Develop"
            and item["finished_at"] is None
            and item["app"] == "platform"
        ),
    },
]


@pytest.fixture
def store(tmp_path: Path) -> AiReviewRunStore:
    return AiReviewRunStore(tmp_path / "ai_review_runs.db")


@pytest.mark.parametrize("case", CREATE_CASES, ids=lambda c: c["description"])
def test_create_run(store: AiReviewRunStore, case):
    args = case["setup"]()
    store.create_run(**args)
    listed = store.list_runs()
    assert len(listed) == 1
    assert listed[0]["review_id"] == args["review_id"]
    assert "log_text" not in listed[0]
    assert case["expectations"](listed[0])


def test_finish_run_persists_counts_rows_and_log(store: AiReviewRunStore):
    store.create_run("ar-abcd1234", "feature/demo", "Develop", "abc123")
    store.finish_run(
        "ar-abcd1234",
        "completed",
        [
            {"item": "CQ-01", "status": "FAIL", "evidence": "indent"},
            {"item": "CQ-02", "status": "PASS", "evidence": "ok"},
            {"item": "PH-01", "status": "SKIP", "evidence": "no PR"},
        ],
        "line one\n| CQ-01 | FAIL | indent |",
    )
    listed = store.list_runs()
    assert listed[0]["status"] == "completed"
    assert listed[0]["pass_count"] == 1
    assert listed[0]["fail_count"] == 1
    assert listed[0]["skip_count"] == 1
    assert listed[0]["commits"] == "abc123"
    assert listed[0]["finished_at"]

    detail = store.get_run("ar-abcd1234")
    assert detail is not None
    assert detail["log_text"].startswith("line one")
    assert detail["rows"][0]["item"] == "CQ-01"


def test_list_runs_newest_first_and_missing_get(store: AiReviewRunStore):
    store.create_run("ar-11111111", "a/one", "Develop")
    store.create_run("ar-22222222", "a/two", "Develop")
    listed = store.list_runs()
    assert [item["review_id"] for item in listed] == ["ar-22222222", "ar-11111111"]
    assert store.get_run("ar-00000000") is None


def test_two_reviews_of_same_branch_are_separate_rows(store: AiReviewRunStore):
    store.create_run("ar-aaa11111", "Syed/VC2-9167", "Develop")
    store.finish_run("ar-aaa11111", "completed", [], "first")
    store.create_run("ar-bbb22222", "Syed/VC2-9167", "Develop")
    store.finish_run("ar-bbb22222", "failed", [], "second")
    listed = store.list_runs()
    assert len(listed) == 2
    assert {item["review_id"] for item in listed} == {"ar-aaa11111", "ar-bbb22222"}


REVIEW_ID_CASES = [
    {
        "description": "accepts ar- plus 8 hex chars",
        "setup": lambda: "ar-abcd1234",
        "expect_ok": True,
    },
    {
        "description": "rejects path traversal",
        "setup": lambda: "../etc",
        "expect_ok": False,
    },
]


@pytest.mark.parametrize("case", REVIEW_ID_CASES, ids=lambda c: c["description"])
def test_require_review_id(case):
    from fastapi import HTTPException

    from backend.api.ai_review_routes import _require_review_id

    if case["expect_ok"]:
        assert _require_review_id(case["setup"]()) == case["setup"]()
        return
    with pytest.raises(HTTPException) as exc:
        _require_review_id(case["setup"]())
    assert exc.value.status_code == 422
