"""
tests/test_review_rule_proposer.py
==================================
Propose / save a new AI Review rule with the LLM mocked.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.engine.review_rule_additions import ReviewRuleIdeaError, store_proposal
from backend.engine.review_rule_proposer import (
    local_judge_new_review_rule,
    model_id_for_rule_judge,
    parse_llm_json_object,
    propose_review_rule,
    rewrite_idea_as_rule,
    save_approved_review_rule,
    suggest_section_for_idea,
)

PARSE_CASES = [
    {
        "description": "reads a fenced JSON object",
        "setup": lambda: 'Sure.\n```json\n{"verdict":"reject","reason":"No."}\n```\n',
        "expectations": lambda data: data["verdict"] == "reject",
    },
    {
        "description": "reads a raw JSON object",
        "setup": lambda: '{"verdict":"overlap","reason":"Covered.","overlap_ids":["CQ-08"]}',
        "expectations": lambda data: data["overlap_ids"] == ["CQ-08"],
    },
]


@pytest.mark.parametrize("case", PARSE_CASES, ids=lambda c: c["description"])
def test_parse_llm_json_object(case):
    data = parse_llm_json_object(case["setup"]())
    assert case["expectations"](data)


MODEL_CASES = [
    {
        "description": "replaces retired Claude 3.5 with the parser / Sonnet 4 id",
        "setup": lambda: {
            "configured": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "parser": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        },
        "expectations": lambda result: "sonnet-4" in result,
    },
    {
        "description": "keeps a living configured model",
        "setup": lambda: {
            "configured": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "parser": "ignored",
        },
        "expectations": lambda result: result.endswith("v1:0") and "3-5" not in result,
    },
]


@pytest.mark.parametrize("case", MODEL_CASES, ids=lambda c: c["description"])
def test_model_id_for_rule_judge(case):
    args = case["setup"]()
    result = model_id_for_rule_judge(args["configured"], args["parser"])
    assert case["expectations"](result)


def test_local_judge_marks_near_duplicate_as_overlap():
    rules = [
        {
            "id": "CQ-01",
            "plain": "Changed code should match how this team already names, formats, and structures files.",
            "rule": "Code follows team conventions (naming, formatting, structure).",
        }
    ]
    result = local_judge_new_review_rule(
        "Changed code should match how this team already names, formats and structures files.",
        rules,
    )
    assert result["verdict"] == "overlap"
    assert "CQ-01" in result["overlap_ids"]


def test_local_judge_accepts_a_new_concrete_check():
    rules = [
        {
            "id": "CQ-01",
            "plain": "Changed code should match how this team already names files.",
            "rule": "Code follows team conventions.",
        }
    ]
    result = local_judge_new_review_rule(
        "Empty catch blocks in changed TypeScript must log or rethrow the error.",
        rules,
    )
    assert result["verdict"] == "accept"
    assert result["suggestions"]


def test_propose_rejects_before_llm():
    with pytest.raises(ReviewRuleIdeaError):
        asyncio.run(
            propose_review_rule(
                "platform",
                "Code Quality",
                "",
                "the lazy dog jumps over the quick brown fox today",
            )
        )


def test_propose_accept_returns_a_ticket():
    judged = {
        "verdict": "accept",
        "reason": "Clear check.",
        "overlap_ids": [],
        "suggestions": [
            {"wording": "Empty catch blocks must log or rethrow.", "plain": "Do not swallow errors."}
        ],
    }
    with patch(
        "backend.engine.review_rule_proposer.judge_new_review_rule",
        new=AsyncMock(return_value=judged),
    ):
        result = asyncio.run(
            propose_review_rule(
                "platform",
                "Code Quality",
                "",
                    "Never commit secrets or .env files in a PR.",
            )
        )
    assert result["verdict"] == "accept"
    assert result["proposal_id"]
    assert result["assigned_id"].startswith("CQ-")
    assert result["suggestions"][0]["id"] == result["assigned_id"]


def test_propose_overlap_has_no_ticket():
    judged = {
        "verdict": "overlap",
        "reason": "Already covered by CQ-08.",
        "overlap_ids": ["CQ-08"],
        "suggestions": [],
    }
    with patch(
        "backend.engine.review_rule_proposer.judge_new_review_rule",
        new=AsyncMock(return_value=judged),
    ):
        result = asyncio.run(
            propose_review_rule(
                "platform",
                "Code Quality",
                "",
                "When you leave the page, timers and polls must stop running.",
            )
        )
    assert result["verdict"] == "overlap"
    assert result["proposal_id"] is None
    assert result["suggestions"] == []


def test_save_approved_review_rule_writes_choice():
    proposal_id = store_proposal(
        {
            "app": "platform",
            "section": "Code Quality",
            "assigned_id": "CQ-99",
            "suggestions": [
                {"id": "CQ-99", "wording": "First wording.", "plain": "First plain."},
                {"id": "CQ-99", "wording": "Second wording.", "plain": "Second plain."},
            ],
        }
    )
    with patch(
        "backend.engine.review_rule_additions.save_rule_to_checklist"
    ) as mock_save:
        saved = asyncio.run(save_approved_review_rule(proposal_id, 1))
    assert saved["id"] == "CQ-99"
    assert saved["rule"] == "Second wording."
    mock_save.assert_called_once()
    with pytest.raises(ReviewRuleIdeaError):
        asyncio.run(save_approved_review_rule(proposal_id, 0))


PII_IDEA = (
    "This sends email/full name into analytics user properties. "
    "To avoid PII and align with GA4, pass a non-PII stable user identifier "
    "(e.g., internal user id) and firm context only."
)

REWRITE_CASES = [
    {
        "description": "rewrites a Copilot PII note into a do-not check",
        "setup": lambda: PII_IDEA,
        "expectations": lambda result: (
            result[0]["wording"].lower().startswith("do not send ")
            and "email" in result[0]["wording"].lower()
            and len(result) == 1
        ),
    },
]


@pytest.mark.parametrize("case", REWRITE_CASES, ids=lambda c: c["description"])
def test_rewrite_idea_as_rule(case):
    result = rewrite_idea_as_rule(case["setup"]())
    assert case["expectations"](result)


SECTION_HINT_CASES = [
    {
        "description": "points a PII analytics idea at Functionality",
        "setup": lambda: {
            "idea": PII_IDEA,
            "available": ["Code Quality", "Functionality", "Testing"],
            "picked": "Code Quality",
        },
        "expectations": lambda result: result == "Functionality",
    },
    {
        "description": "keeps Code Quality for a catch-block idea",
        "setup": lambda: {
            "idea": "Empty catch blocks in changed TypeScript must log or rethrow the error.",
            "available": ["Code Quality", "Functionality"],
            "picked": "Code Quality",
        },
        "expectations": lambda result: result == "Code Quality",
    },
]


@pytest.mark.parametrize("case", SECTION_HINT_CASES, ids=lambda c: c["description"])
def test_suggest_section_for_idea(case):
    args = case["setup"]()
    result = suggest_section_for_idea(args["idea"], args["available"], args["picked"])
    assert case["expectations"](result)


def test_save_uses_suggested_section_when_asked():
    proposal_id = store_proposal(
        {
            "app": "platform",
            "section": "Code Quality",
            "assigned_id": "CQ-99",
            "suggested_section": "Functionality",
            "suggested_id": "F-40",
            "suggestions": [
                {"id": "CQ-99", "wording": "Do not send email in analytics.", "plain": "No PII in analytics."},
            ],
        }
    )
    with patch(
        "backend.engine.review_rule_additions.save_rule_to_checklist"
    ) as mock_save:
        saved = asyncio.run(
            save_approved_review_rule(proposal_id, 0, use_suggested_section=True)
        )
    assert saved["id"] == "F-40"
    assert saved["section"] == "Functionality"
    mock_save.assert_called_once()
    assert mock_save.call_args.args[1] == "Functionality"
    assert mock_save.call_args.args[2] == "F-40"


def test_propose_pii_idea_overlaps_saved_cq_34():
    with patch(
        "backend.engine.review_rule_proposer.judge_new_review_rule",
        new=AsyncMock(side_effect=RuntimeError("no llm")),
    ):
        result = asyncio.run(
            propose_review_rule("platform", "Code Quality", "", PII_IDEA)
        )
    assert result["verdict"] == "overlap"
    assert "CQ-34" in result["overlap_ids"]


def test_propose_new_idea_rewrites_and_hints_functionality():
    idea = (
        "This stores PII home address in the session cookie. "
        "To avoid leaking location, keep only a region code."
    )
    with patch(
        "backend.engine.review_rule_proposer.judge_new_review_rule",
        new=AsyncMock(side_effect=RuntimeError("no llm")),
    ):
        result = asyncio.run(
            propose_review_rule("platform", "Code Quality", "", idea)
        )
    assert result["verdict"] == "accept"
    assert result["suggested_section"] == "Functionality"
    assert result["assigned_id"].startswith("CQ-")
    assert result["suggested_id"].startswith("F-")
    assert result["suggestions"][0]["wording"].lower().startswith("do not store ")
