"""
vQA — Unit Tests for SearchHelper Conditional Prompting
======================================================
Module: tests/test_generator_search_prompt.py

Verifies that generator_node.py conditional prompting correctly includes
SearchHelper rules and imports when a card is search/filtering-related,
and excludes them for non-search cards.
"""

from backend.engine.generator_node import _build_prompt


def test_build_prompt_with_search_card():
    """Verify that _build_prompt includes SearchHelper when search/filtering is involved."""
    card = {
        "ticket_id": "QA-170",
        "summary": "Advanced Search Panel",
        "acceptance_criteria": "Given I am logged in, When I open search and filter by Client, Then correct results show.",
        "expected_steps": ["Open search panel", "Select a client", "Click search button"]
    }
    
    tenant_context = {
        "selectors": {
            "search-btn": {"selector": "#search", "description": "Trigger search button"}
        },
        "helper_files": []
    }
    
    system_prompt, user_prompt = _build_prompt(card, tenant_context)
    
    # Assert SearchHelper import and rules are in the user prompt
    assert "import * as SearchHelper from '@utils/SearchHelper';" in user_prompt
    assert "MANDATORY SEARCH/FILTER RULES" in user_prompt
    assert "ALWAYS use SearchHelper.openSearchPanel(page, 'context')" in user_prompt
    assert "ALWAYS use SearchHelper.performSearch" in user_prompt


def test_build_prompt_with_non_search_card():
    """Verify that _build_prompt does not include SearchHelper for non-search cards."""
    card = {
        "ticket_id": "QA-105",
        "summary": "Check Dashboard Widgets",
        "acceptance_criteria": "Verify widgets are visible",
        "expected_steps": ["Assert widget visible"]
    }
    
    tenant_context = {
        "selectors": {},
        "helper_files": []
    }
    
    system_prompt, user_prompt = _build_prompt(card, tenant_context)
    
    # Assert SearchHelper is NOT in the user prompt
    assert "SearchHelper" not in user_prompt
    assert "MANDATORY SEARCH/FILTER RULES" not in user_prompt
