"""
vQA — FEAT-088 Minimum Similarity Threshold Unit Tests
======================================================
Tests: tests/test_feat_088_min_score.py

This module contains unit tests for the KB RAG similarity score gating (TASK-100).
It mocks ChromaDB to verify the similarity calculation (similarity = 1.0 - distance)
and ensures that lower-scoring matches are correctly filtered out or completely
discarded when they fall below the minimum threshold.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from backend.config import settings
from backend.kb.rag import TestPlanVault
from backend.engine.schemas import MultiActorTestPlan, MultiActorStep


def make_mock_plan(plan_id: str, title: str) -> MultiActorTestPlan:
    """Helper to generate a valid minimal MultiActorTestPlan."""
    return MultiActorTestPlan(
        test_plan_id=plan_id,
        test_title=title,
        actors=["account_executive"],
        steps=[
            MultiActorStep(
                step_index=1,
                actor="account_executive",
                action="click",
                description="Click submit button",
            )
        ]
    )


@pytest.fixture
def mock_chroma():
    """Mock out ChromaDB PersistentClient and its collection."""
    with patch("chromadb.PersistentClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        
        # Chain get_or_create_collection
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_client_cls.return_value = mock_client
        
        yield mock_collection


def test_test_plan_vault_empty_collection(mock_chroma):
    """Test that TestPlanVault immediately returns [] if collection is empty."""
    mock_chroma.count.return_value = 0
    
    vault = TestPlanVault(persist_directory="/tmp/mock_chroma")
    results = vault.query_plans("search query")
    
    assert results == []
    mock_chroma.query.assert_not_called()


def test_test_plan_vault_default_filtering(mock_chroma):
    """
    Test that default similarity filtering (default threshold 0.2)
    keeps matches with high similarity and filters out low similarity.
    
    Similarity score = 1.0 - distance.
    Distance 0.1  => Score 0.90 (>= 0.2, KEPT)
    Distance 0.85 => Score 0.15 (< 0.2, DISCARDED)
    Distance 0.95 => Score 0.05 (< 0.2, DISCARDED)
    """
    mock_chroma.count.return_value = 3
    
    plan1 = make_mock_plan("QA-1", "High similarity plan")
    plan2 = make_mock_plan("QA-2", "Low similarity plan")
    plan3 = make_mock_plan("QA-3", "Very low similarity plan")
    
    mock_chroma.query.return_value = {
        "metadatas": [[
            {"plan_json": plan1.model_dump_json(), "test_title": plan1.test_title},
            {"plan_json": plan2.model_dump_json(), "test_title": plan2.test_title},
            {"plan_json": plan3.model_dump_json(), "test_title": plan3.test_title},
        ]],
        "distances": [[
            0.1,   # 1 - 0.1 = 0.9 (kept)
            0.85,  # 1 - 0.85 = 0.15 (discarded)
            0.95,  # 1 - 0.95 = 0.05 (discarded)
        ]]
    }
    
    vault = TestPlanVault(persist_directory="/tmp/mock_chroma")
    results = vault.query_plans("vague search query")
    
    # Only plan1 should be returned
    assert len(results) == 1
    assert results[0].test_plan_id == "QA-1"
    assert results[0].test_title == "High similarity plan"


def test_test_plan_vault_all_below_threshold(mock_chroma):
    """Test that [] is returned when all plans are below the default similarity threshold."""
    mock_chroma.count.return_value = 2
    
    plan1 = make_mock_plan("QA-1", "Poor match 1")
    plan2 = make_mock_plan("QA-2", "Poor match 2")
    
    mock_chroma.query.return_value = {
        "metadatas": [[
            {"plan_json": plan1.model_dump_json(), "test_title": plan1.test_title},
            {"plan_json": plan2.model_dump_json(), "test_title": plan2.test_title},
        ]],
        "distances": [[
            0.82,  # Score 0.18 (< 0.2, discarded)
            0.90,  # Score 0.10 (< 0.2, discarded)
        ]]
    }
    
    vault = TestPlanVault(persist_directory="/tmp/mock_chroma")
    results = vault.query_plans("unrelated query")
    
    assert results == []


def test_test_plan_vault_query_time_override(mock_chroma):
    """Test overriding min_score at query time."""
    mock_chroma.count.return_value = 2
    
    plan1 = make_mock_plan("QA-1", "High similarity plan")
    plan2 = make_mock_plan("QA-2", "Medium similarity plan")
    
    mock_chroma.query.return_value = {
        "metadatas": [[
            {"plan_json": plan1.model_dump_json(), "test_title": plan1.test_title},
            {"plan_json": plan2.model_dump_json(), "test_title": plan2.test_title},
        ]],
        "distances": [[
            0.1,  # Score 0.9 (kept for either)
            0.85, # Score 0.15 (kept with min_score=0.1, discarded with min_score=0.3)
        ]]
    }
    
    vault = TestPlanVault(persist_directory="/tmp/mock_chroma")
    
    # 1. Query with strict override (min_score=0.3) -> keeps only plan1
    results_strict = vault.query_plans("search", min_score=0.3)
    assert len(results_strict) == 1
    assert results_strict[0].test_plan_id == "QA-1"
    
    # 2. Query with permissive override (min_score=0.1) -> keeps both
    results_permissive = vault.query_plans("search", min_score=0.1)
    assert len(results_permissive) == 2
    assert results_permissive[0].test_plan_id == "QA-1"
    assert results_permissive[1].test_plan_id == "QA-2"


def test_test_plan_vault_settings_override(mock_chroma):
    """Test overriding similarity threshold via global config settings."""
    mock_chroma.count.return_value = 2
    
    plan1 = make_mock_plan("QA-1", "High similarity plan")
    plan2 = make_mock_plan("QA-2", "Medium similarity plan")
    
    mock_chroma.query.return_value = {
        "metadatas": [[
            {"plan_json": plan1.model_dump_json(), "test_title": plan1.test_title},
            {"plan_json": plan2.model_dump_json(), "test_title": plan2.test_title},
        ]],
        "distances": [[
            0.1,  # Score 0.9
            0.85, # Score 0.15
        ]]
    }
    
    vault = TestPlanVault(persist_directory="/tmp/mock_chroma")
    
    # Temporarily patch setting value
    with patch.object(settings, "kb_min_similarity_score", 0.5):
        results = vault.query_plans("search")
        # Only plan1 should be returned (score 0.9 >= 0.5). Plan 2 (score 0.15 < 0.5) is filtered.
        assert len(results) == 1
        assert results[0].test_plan_id == "QA-1"
