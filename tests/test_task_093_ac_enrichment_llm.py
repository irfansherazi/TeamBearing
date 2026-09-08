import pytest
import re
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.ac_enricher import enrich_ac_text, EnrichmentResult
from backend.engine.ac_parser import ac_parser_node
from backend.engine.state import make_initial_state
from backend.engine.schemas import MultiActorTestPlan, MultiActorStep
from backend.engine.ac_quality_gate import score_ac_quality, ACQualityResult

# Simple MultiActorTestPlan mock setup
def make_mock_historical_plan(title: str) -> MultiActorTestPlan:
    return MultiActorTestPlan(
        test_plan_id="QA-123-PAST",
        test_title=title,
        actors=["account_executive"],
        steps=[
            MultiActorStep(
                step_index=1,
                actor="account_executive",
                action="click",
                description="Click button#submit",
            )
        ]
    )

@pytest.mark.anyio
async def test_llm_enrichment_routing_sub_good_score():
    """Verify raw ACs with initial quality score < 7 route to the LLM-based Enricher."""
    raw_ac = "User can sort table." # Very vague, score < 7
    summary = "Vague Sort Ticket"
    description = "A very vague ticket description."
    ticket_id = "QA-101"

    # Initial score will be poor (< 4) or fair (4-6)
    initial_quality = score_ac_quality(raw_ac)
    assert initial_quality.overall_score < 7

    # Mock TestPlanVault and Jira Comments
    mock_plans = [make_mock_historical_plan("Past Table Sort Plan")]
    mock_comments = [{"author": "QA Team", "body": "Make sure sorting works in compact view.", "created": "2026-06-02"}]

    mock_llm_output = """
    Scenario: Happy Path - Sort table
    Given on the Production Orders compact view click '#sort-btn' button to verify success message toast is visible
    When on the compact view select 'Client' from the 'p-select' dropdown to verify table is visible
    Then click '#sort-btn' on the compact view to assert success message toast appears

    Scenario: Negative Path - Empty Table
    Given on the Production Orders compact view click '#sort-btn' button to verify success message toast is visible
    When on the compact view select 'Client' from the 'p-select' dropdown to verify table is visible
    Then click '#sort-btn' on the compact view to assert success message toast appears

    Scenario: Negative Path - Unauthorized Sorting
    Given on the Production Orders compact view click '#sort-btn' button to verify success message toast is visible
    When on the compact view select 'Client' from the 'p-select' dropdown to verify table is visible
    Then click '#sort-btn' on the compact view to assert success message toast appears
    """

    # Mock response object from LangChain LLM
    mock_response = MagicMock()
    mock_response.content = mock_llm_output
    mock_response.response_metadata = {"usage": {"input_tokens": 100, "output_tokens": 200}}

    mock_llm_instance = AsyncMock()
    mock_llm_instance.ainvoke.return_value = mock_response

    with (
        patch("backend.kb.rag.test_plan_vault.query_plans", return_value=mock_plans) as mock_query,
        patch("backend.jira.client.fetch_issue_comments", new_callable=AsyncMock, return_value=mock_comments) as mock_fetch,
        patch("backend.llm.get_llm", return_value=mock_llm_instance) as mock_get_llm
    ):
        result = await enrich_ac_text(
            raw_ac=raw_ac,
            summary=summary,
            description=description,
            ticket_id=ticket_id,
        )

        # Assert retrieval was called because score < 7
        mock_query.assert_called_once()
        mock_fetch.assert_called_once_with(ticket_id)
        mock_get_llm.assert_called_once()

        # Verify LLM-enriched result details
        assert result.enrichment_applied is True
        assert "compact view click" in result.enriched_ac
        assert "Scenario: Negative Path" in result.enriched_ac

        # Verify negative paths are indeed in the enriched AC
        neg_count = len(re.findall(r"(?i)scenario:\s*negative", result.enriched_ac))
        assert neg_count >= 2


@pytest.mark.anyio
async def test_llm_enrichment_rescores_to_good():
    """Verify that LLM-enriched ACs achieve a GOOD (overall_score >= 7) quality score."""
    raw_ac = "User sorts."
    summary = "Vague Sort Ticket"
    ticket_id = "QA-102"

    # Initial score
    initial_score = score_ac_quality(raw_ac).overall_score
    assert initial_score < 7

    mock_llm_output = """
    Given on the Production Orders compact view click '#sort-btn' button to verify success message toast is visible
    When on the compact view select 'Client' from the 'p-select' dropdown to verify table is visible
    Then click '#sort-btn' on the compact view to assert success message toast appears
    """

    mock_response = MagicMock()
    mock_response.content = mock_llm_output
    mock_response.response_metadata = {"usage": {"input_tokens": 100, "output_tokens": 200}}

    mock_llm_instance = AsyncMock()
    mock_llm_instance.ainvoke.return_value = mock_response

    # Prepare quality result to be updated
    quality_result = score_ac_quality(raw_ac)

    with (
        patch("backend.kb.rag.test_plan_vault.query_plans", return_value=[]),
        patch("backend.jira.client.fetch_issue_comments", new_callable=AsyncMock, return_value=[]),
        patch("backend.llm.get_llm", return_value=mock_llm_instance)
    ):
        result = await enrich_ac_text(
            raw_ac=raw_ac,
            summary=summary,
            description="",
            ticket_id=ticket_id,
            quality_result=quality_result
        )

        # Check in-place quality score update
        assert quality_result.overall_score >= 7
        assert quality_result.quality_grade == "good"


@pytest.mark.anyio
async def test_ac_parser_node_passes_repaired_ac_and_updates_state():
    """Verify ac_parser_node calls LLM repair and updates VQAState with high score and final plan."""
    # State containing vague AC with poor score (< 4)
    state = make_initial_state(
        run_id="test-run-001",
        jira_ticket_id="QA-103",
        role="account_executive",
        target_url="http://test.com",
        mode="headless"
    )
    state["jira_ticket"]["acceptance_criteria"] = "Vague user sorting text."
    state["jira_ticket"]["summary"] = "Vague sorting issue"

    mock_llm_output = """
    Given on the Production Orders compact view click '#sort-btn' button to verify success message toast is visible
    When on the compact view select 'Client' from the 'p-select' dropdown to verify table is visible
    Then click '#sort-btn' on the compact view to assert success message toast appears
    """

    # Mock stage 1 BDD normalizer and stage 2 JSON compiler
    mock_plan = MagicMock()
    mock_plan.steps = [
        MagicMock(goal="Given the user is on compact view", target_element_types=["button"], step_id=1, step_type="CLICK", target_component="sort", verification=[]),
        MagicMock(goal="Scenario: Negative Path step", target_element_types=["textbox"], step_id=2, step_type="FILL", target_component="edit", verification=[])
    ]
    mock_plan.model_dump.return_value = {
        "steps": [
            {"goal": "Given the user is on compact view", "target_element_types": ["button"]},
            {"goal": "Scenario: Negative Path step", "target_element_types": ["textbox"]}
        ],
        "test_title": "Enriched Test Plan"
    }

    mock_response = MagicMock()
    mock_response.content = mock_llm_output
    mock_response.response_metadata = {"usage": {"input_tokens": 100, "output_tokens": 200}}

    mock_llm_instance = AsyncMock()
    mock_llm_instance.ainvoke.return_value = mock_response

    with (
        patch("backend.kb.rag.test_plan_vault.query_plans", return_value=[]),
        patch("backend.jira.client.fetch_issue_comments", new_callable=AsyncMock, return_value=[]),
        patch("backend.llm.get_llm", return_value=mock_llm_instance),
        patch("backend.engine.ac_parser._stage_1_normalize", return_value="BDD text"),
        patch("backend.engine.ac_parser._stage_2_compile", return_value=mock_plan),
        patch("backend.engine.ac_parser.build_global_context", return_value="context")
    ):
        result = await ac_parser_node(state)

        # Assert no rejection happened (since it healed to good)
        assert result["test_plan"] is not None
        assert result["parse_quality"] == "good"
        assert result["ac_quality_result"]["overall_score"] >= 7


@pytest.mark.anyio
async def test_llm_enrichment_noop_on_good_score():
    """Verify that if the initial quality score is >= 7, LLM-driven repair is bypassed entirely."""
    raw_ac = "Some raw AC text"
    summary = "Specific Sort Ticket"
    ticket_id = "QA-104"

    mock_quality = MagicMock()
    mock_quality.overall_score = 8
    mock_quality.quality_grade = "good"

    with (
        patch("backend.engine.ac_quality_gate.score_ac_quality", return_value=mock_quality) as mock_score,
        patch("backend.kb.rag.test_plan_vault.query_plans") as mock_query,
        patch("backend.jira.client.fetch_issue_comments", new_callable=AsyncMock) as mock_fetch,
        patch("backend.llm.get_llm") as mock_get_llm
    ):
        result = await enrich_ac_text(
            raw_ac=raw_ac,
            summary=summary,
            description="",
            ticket_id=ticket_id,
            quality_result=mock_quality
        )

        # Assert zero LLM or context gathering tools were invoked
        mock_query.assert_not_called()
        mock_fetch.assert_not_called()
        mock_get_llm.assert_not_called()

        # Standard domain context heuristic is applied instead
        assert isinstance(result, EnrichmentResult)


@pytest.mark.anyio
async def test_llm_enrichment_fallback_to_heuristic_on_exception():
    """Verify that if the LLM enricher fails with an exception, it falls back to standard heuristic enrichment."""
    raw_ac = "Vague AC"
    summary = "Vague Ticket"
    ticket_id = "QA-105"

    initial_quality = score_ac_quality(raw_ac)
    assert initial_quality.overall_score < 7

    # Mock LLM to throw an exception
    with (
        patch("backend.kb.rag.test_plan_vault.query_plans", return_value=[]),
        patch("backend.jira.client.fetch_issue_comments", new_callable=AsyncMock, return_value=[]),
        patch("backend.llm.get_llm", side_effect=RuntimeError("Bedrock connection error")),
        patch("backend.engine.ac_enricher._detect_domains", return_value=["table_sort"]) as mock_detect,
        patch("backend.engine.ac_enricher._query_kb_for_enrichment", return_value=[("table_sort", "Article Name", "Content with click button#sort-btn p-select")]) as mock_kb
    ):
        result = await enrich_ac_text(
            raw_ac=raw_ac,
            summary=summary,
            description="",
            ticket_id=ticket_id,
            quality_result=initial_quality
        )

        # Standard heuristic detection and enrichment is triggered as fallback
        mock_detect.assert_called()
        mock_kb.assert_called()
        assert result.enrichment_applied is True
        assert "Article Name" in result.enriched_ac
