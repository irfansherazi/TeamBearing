"""
tests/test_ai_review_runner.py
==============================
Unit tests for the thin npm run ai:review argv / validation helpers.
"""

from pathlib import Path

import pytest

from backend.engine.ai_review_runner import (
    AiReviewConfigError,
    AiReviewValidationError,
    build_ai_review_argv,
    has_ai_review_script,
    parse_review_table_row,
    resolve_ai_review_cwd,
    summarize_review_rows,
    upsert_review_row,
    validate_app,
    validate_commits,
    validate_git_ref,
)

VALIDATE_REF_CASES = [
    {
        "description": "accepts a namespaced feature branch",
        "setup": lambda: {"value": "Syed/TD-260", "field": "Branch"},
        "expectations": lambda result: result == "Syed/TD-260",
    },
    {
        "description": "strips surrounding whitespace",
        "setup": lambda: {"value": "  feature/demo  ", "field": "Branch"},
        "expectations": lambda result: result == "feature/demo",
    },
]


@pytest.mark.parametrize("case", VALIDATE_REF_CASES, ids=lambda c: c["description"])
def test_validate_git_ref_accepts(case):
    args = case["setup"]()
    result = validate_git_ref(args["value"], args["field"])
    assert case["expectations"](result)


REJECT_REF_CASES = [
    {
        "description": "rejects empty branch",
        "setup": lambda: {"value": "   ", "field": "Branch"},
    },
    {
        "description": "rejects shell metacharacters",
        "setup": lambda: {"value": "foo;rm", "field": "Branch"},
    },
    {
        "description": "rejects command substitution",
        "setup": lambda: {"value": "$(whoami)", "field": "Branch"},
    },
]


@pytest.mark.parametrize("case", REJECT_REF_CASES, ids=lambda c: c["description"])
def test_validate_git_ref_rejects(case):
    args = case["setup"]()
    with pytest.raises(AiReviewValidationError):
        validate_git_ref(args["value"], args["field"])


COMMITS_CASES = [
    {
        "description": "empty commits are allowed",
        "setup": lambda: "  ",
        "expectations": lambda result: result == "",
    },
    {
        "description": "accepts comma-separated hex SHAs",
        "setup": lambda: "abc123,def456",
        "expectations": lambda result: result == "abc123,def456",
    },
]


@pytest.mark.parametrize("case", COMMITS_CASES, ids=lambda c: c["description"])
def test_validate_commits_accepts(case):
    result = validate_commits(case["setup"]())
    assert case["expectations"](result)


def test_validate_commits_rejects_spaces():
    with pytest.raises(AiReviewValidationError):
        validate_commits("abc 123")


ARGV_CASES = [
    {
        "description": "omits --commits when empty",
        "setup": lambda: {"branch": "a/b", "base": "Develop", "commits": ""},
        "expectations": lambda cmd: "--commits=" not in " ".join(cmd)
        and "--branch=a/b" in cmd
        and "--app=platform" in cmd
        and "--base=Develop" in cmd,
    },
    {
        "description": "includes --commits when provided",
        "setup": lambda: {"branch": "a/b", "base": "Develop", "commits": "abc,def"},
        "expectations": lambda cmd: "--commits=abc,def" in cmd and "--app=platform" in cmd,
    },
    {
        "description": "includes --app=vcapi when provided",
        "setup": lambda: {"branch": "a/b", "base": "develop", "commits": "", "app": "vcapi"},
        "expectations": lambda cmd: "--app=vcapi" in cmd and "--base=develop" in cmd,
    },
]


@pytest.mark.parametrize("case", ARGV_CASES, ids=lambda c: c["description"])
def test_build_ai_review_argv(case):
    args = case["setup"]()
    cmd = build_ai_review_argv(
        args["branch"], args["base"], args["commits"], args.get("app", "platform")
    )
    assert "ai:review" in cmd
    assert "--" in cmd
    assert case["expectations"](cmd)


TABLE_ROW_CASES = [
    {
        "description": "parses a FAIL checklist row",
        "setup": lambda: "| CQ-01 | FAIL | stray indent |",
        "expectations": lambda row: row == {"item": "CQ-01", "status": "FAIL", "evidence": "stray indent"},
    },
    {
        "description": "parses a PASS row",
        "setup": lambda: "| CQ-05 | PASS | no console.log |",
        "expectations": lambda row: row["status"] == "PASS" and row["item"] == "CQ-05",
    },
    {
        "description": "parses a SKIP row",
        "setup": lambda: "| PH-01 | SKIP | no PR yet |",
        "expectations": lambda row: row == {"item": "PH-01", "status": "SKIP", "evidence": "no PR yet"},
    },
    {
        "description": "skips markdown separator",
        "setup": lambda: "|---|---|---|",
        "expectations": lambda row: row is None,
    },
    {
        "description": "skips header row",
        "setup": lambda: "| Check | PASS / FAIL | Evidence |",
        "expectations": lambda row: row is None,
    },
    {
        "description": "ignores non-table lines",
        "setup": lambda: "Running review...",
        "expectations": lambda row: row is None,
    },
]


@pytest.mark.parametrize("case", TABLE_ROW_CASES, ids=lambda c: c["description"])
def test_parse_review_table_row(case):
    row = parse_review_table_row(case["setup"]())
    assert case["expectations"](row)


UPSERT_CASES = [
    {
        "description": "appends a new item",
        "setup": lambda: {
            "rows": [{"item": "CQ-01", "status": "FAIL", "evidence": "a"}],
            "next": {"item": "CQ-02", "status": "PASS", "evidence": "b"},
        },
        "expectations": lambda result: len(result) == 2 and result[1]["item"] == "CQ-02",
    },
    {
        "description": "replaces an existing item",
        "setup": lambda: {
            "rows": [{"item": "CQ-01", "status": "FAIL", "evidence": "a"}],
            "next": {"item": "CQ-01", "status": "PASS", "evidence": "fixed"},
        },
        "expectations": lambda result: len(result) == 1 and result[0]["status"] == "PASS",
    },
]


@pytest.mark.parametrize("case", UPSERT_CASES, ids=lambda c: c["description"])
def test_upsert_review_row(case):
    args = case["setup"]()
    result = upsert_review_row(args["rows"], args["next"])
    assert case["expectations"](result)


SUMMARIZE_CASES = [
    {
        "description": "counts PASS FAIL and SKIP",
        "setup": lambda: [
            {"item": "A", "status": "PASS", "evidence": ""},
            {"item": "B", "status": "FAIL", "evidence": ""},
            {"item": "C", "status": "SKIP", "evidence": ""},
            {"item": "D", "status": "N/A", "evidence": ""},
        ],
        "expectations": lambda result: result == (1, 1, 2),
    },
    {
        "description": "empty rows are all zeros",
        "setup": lambda: [],
        "expectations": lambda result: result == (0, 0, 0),
    },
]


@pytest.mark.parametrize("case", SUMMARIZE_CASES, ids=lambda c: c["description"])
def test_summarize_review_rows(case):
    result = summarize_review_rows(case["setup"]())
    assert case["expectations"](result)


def test_validate_app_accepts_platform_and_vcapi():
    assert validate_app("platform") == "platform"
    assert validate_app("vsuitePlatform") == "platform"
    assert validate_app("vcapi") == "vcapi"


def test_validate_app_rejects_unknown():
    with pytest.raises(AiReviewValidationError):
        validate_app("other")


def test_has_ai_review_script(tmp_path: Path):
    assert has_ai_review_script(tmp_path) is False
    script = tmp_path / "scripts" / "ai-review.js"
    script.parent.mkdir()
    script.write_text("module.exports = {};\n", encoding="utf-8")
    assert has_ai_review_script(tmp_path) is True


def test_resolve_ai_review_cwd_uses_configured_path(tmp_path: Path):
    script = tmp_path / "scripts" / "ai-review.js"
    script.parent.mkdir()
    script.write_text("// tool\n", encoding="utf-8")
    resolved = resolve_ai_review_cwd(str(tmp_path))
    assert resolved == tmp_path.resolve()


def test_resolve_ai_review_cwd_rejects_configured_path_without_script(tmp_path: Path):
    with pytest.raises(AiReviewConfigError):
        resolve_ai_review_cwd(str(tmp_path))
