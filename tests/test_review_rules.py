"""
tests/test_review_rules.py
==========================
Parse PR review checklists for the Review rules page.
"""

import pytest

from backend.engine.ai_review_runner import AiReviewValidationError
from backend.engine.review_rules import (
    load_review_rules,
    parse_checklist_markdown,
)
from backend.engine.review_rule_summaries import plain_language_for

PARSE_CASES = [
    {
        "description": "reads a checklist id, section, and first-line rule",
        "setup": lambda: (
            "### 1. Code Quality\n"
            "- **[CQ-01]** Code follows team conventions.\n"
            "- **[CQ-02]** No commented-out or dead code.\n"
        ),
        "expectations": lambda items: (
            len(items) == 2
            and items[0]["id"] == "CQ-01"
            and items[0]["section"] == "Code Quality"
            and "team conventions" in items[0]["rule"]
        ),
    },
    {
        "description": "keeps continuation lines on the same rule",
        "setup": lambda: (
            "### 1. Code Quality\n"
            "- **[CQ-08]** Component lifecycle — no leaks after destroy:\n"
            "  1. Every timer is cleared.\n"
            "- **[CQ-09]** No hardcoded plain text.\n"
        ),
        "expectations": lambda items: (
            items[0]["id"] == "CQ-08"
            and "Every timer is cleared" in items[0]["rule"]
            and items[1]["id"] == "CQ-09"
        ),
    },
]


@pytest.mark.parametrize("case", PARSE_CASES, ids=lambda c: c["description"])
def test_parse_checklist_markdown(case):
    markdown = case["setup"]()
    items = parse_checklist_markdown(markdown)
    assert case["expectations"](items)


def test_parse_checklist_markdown_rejects_empty():
    with pytest.raises(Exception):
        parse_checklist_markdown("# Empty\n")


def test_load_review_rules_platform_includes_cq_01():
    payload = load_review_rules("platform")
    ids = [
        rule["id"]
        for section in payload["sections"]
        for rule in section["rules"]
    ]
    assert payload["app"] == "platform"
    assert payload["label"] == "vsuitePlatform"
    assert "CQ-01" in ids
    assert "CQ-02" in ids
    assert "F-01" in ids
    cq01 = next(
        rule
        for section in payload["sections"]
        for rule in section["rules"]
        if rule["id"] == "CQ-01"
    )
    assert "names" in cq01["plain"].lower() or "conventions" in cq01["plain"].lower()


def test_load_review_rules_vcapi_has_own_cq_05():
    payload = load_review_rules("vcapi")
    cq05 = next(
        rule
        for section in payload["sections"]
        for rule in section["rules"]
        if rule["id"] == "CQ-05"
    )
    assert "console" in cq05["plain"].lower()


def test_load_review_rules_rejects_unknown_app():
    with pytest.raises(AiReviewValidationError):
        load_review_rules("unknown")


PLAIN_CASES = [
    {
        "description": "uses a platform-specific explanation for CQ-08",
        "setup": lambda: {
            "app": "platform",
            "rule_id": "CQ-08",
            "official": "Component lifecycle — no leaks after destroy.",
        },
        "expectations": lambda result: "timers" in result.lower() or "leave the page" in result.lower(),
    },
    {
        "description": "uses the saved CQ-34 analytics explanation",
        "setup": lambda: {
            "app": "platform",
            "rule_id": "CQ-34",
            "official": "Official wording.",
        },
        "expectations": lambda result: "email" in result.lower() and "analytics" in result.lower(),
    },
    {
        "description": "falls back to official text when no summary exists",
        "setup": lambda: {
            "app": "platform",
            "rule_id": "ZZ-99",
            "official": "A made-up rule.",
        },
        "expectations": lambda result: result == "A made-up rule.",
    },
]


@pytest.mark.parametrize("case", PLAIN_CASES, ids=lambda c: c["description"])
def test_plain_language_for(case):
    args = case["setup"]()
    result = plain_language_for(args["app"], args["rule_id"], args["official"])
    assert case["expectations"](result)
