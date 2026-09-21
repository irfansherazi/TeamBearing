"""
tests/test_ai_review_rules_api.py
=================================
GET /api/ai-review/rules handler returns parsed checklist codes.
"""

import asyncio

import pytest
from fastapi import HTTPException

from backend.api.ai_review_routes import list_ai_review_rules

RULES_API_CASES = [
    {
        "description": "returns platform CQ-01",
        "setup": lambda: "platform",
        "expectations": lambda body: (
            body.app == "platform"
            and "CQ-01" in {
                rule.id for section in body.sections for rule in section.rules
            }
        ),
    },
]


@pytest.mark.parametrize("case", RULES_API_CASES, ids=lambda c: c["description"])
def test_list_ai_review_rules_platform(case):
    app_value = case["setup"]()
    body = asyncio.run(list_ai_review_rules(app_value))
    assert case["expectations"](body)


def test_list_ai_review_rules_rejects_unknown_app():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(list_ai_review_rules("unknown"))
    assert exc.value.status_code == 422
