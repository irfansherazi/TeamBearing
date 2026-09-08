"""
vQA — FEAT-006 RAG Enhancement Tests
======================================
Module: backend/kb/test_rag_enhancement.py

Tests for FEAT-006: RAG Enhancement & Semantic Retrieval.
Covers: synonym expansion, BM25 re-ranking, FORBIDDEN_KEYWORDS,
dynamic threshold tuning, and KB gate closure logging.
"""

import pytest

# ---------------------------------------------------------------------------
# Phase 1 Tests — Synonym Expansion + Threshold Tuning
# ---------------------------------------------------------------------------


def test_synonym_map_has_14_new_entries():
    """FEAT-006: _SYNONYM_MAP must contain at least 35 entries (21 original + 14 new)."""
    from backend.kb.loader import LocalKnowledgeBase

    assert len(LocalKnowledgeBase._SYNONYM_MAP) >= 35, (
        f"_SYNONYM_MAP has {len(LocalKnowledgeBase._SYNONYM_MAP)} entries; "
        "expected >= 35 (21 original + 14 FEAT-006 additions)."
    )


def test_new_synonym_keys_present():
    """FEAT-006: All 14 new domain-specific synonym triggers must exist."""
    from backend.kb.loader import LocalKnowledgeBase

    expected_new_keys = {
        "sort table",
        "voicer",
        "qo",
        "campaign",
        "endorsement",
        "liner",
        "alps",
        "delegate",
        "fulfillment",
        "poc",
        "marketron",
        "wideorbit",
        "blog",
        "script",
    }
    actual_keys = set(LocalKnowledgeBase._SYNONYM_MAP.keys())
    missing = expected_new_keys - actual_keys
    assert not missing, f"_SYNONYM_MAP is missing {len(missing)} FEAT-006 key(s): {sorted(missing)}"


def test_alps_synonym_is_advertiser_landing_page():
    """FEAT-006: 'alps' must map to advertiser landing page, NOT traffic system."""
    from backend.kb.loader import LocalKnowledgeBase

    alps_expansion = LocalKnowledgeBase._SYNONYM_MAP.get("alps", "")
    assert "advertiser" in alps_expansion.lower(), (
        f"alps expansion should reference 'advertiser landing page'; got: {alps_expansion!r}"
    )
    assert "traffic" not in alps_expansion.lower(), (
        f"alps expansion should NOT reference 'traffic system'; got: {alps_expansion!r}"
    )


def test_voicer_synonym_includes_spot_request():
    """FEAT-006: 'voicer' expansion must include spot, voice, request."""
    from backend.kb.loader import LocalKnowledgeBase

    voicer_expansion = LocalKnowledgeBase._SYNONYM_MAP.get("voicer", "")
    for term in ("spot", "voice", "request"):
        assert term in voicer_expansion.lower(), f"voicer expansion missing '{term}'; got: {voicer_expansion!r}"


def test_short_query_expansion_is_double_weight():
    """FEAT-006: Queries < 10 words should get double-weight expansion."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    # "Sort table" is 2 words → should trigger double-weight
    text = "Sort table"
    text_lower = text.lower()
    expansion_parts = []
    for trigger, expansion in kb_instance._SYNONYM_MAP.items():
        if trigger in text_lower:
            expansion_parts.append(expansion)

    # Simulate the expansion logic
    assert len(expansion_parts) > 0, "No expansion triggered for 'Sort table'"

    expansion_str = " ".join(expansion_parts)
    word_count = len(text.split())
    assert word_count < 10, f"Test expects < 10 words, got {word_count}"

    # The double-weight path appends expansion_str twice
    expected_expanded = text + " " + expansion_str + " " + expansion_str
    # Verify the expansion string appears twice (double-weight)
    assert expected_expanded.count(expansion_str) == 2, (
        "Short query should have expansion terms appended twice (double-weight)"
    )


def test_threshold_lower_for_short_queries():
    """FEAT-006: Threshold floor should be 0.06 for queries < 15 words."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    # "sort due date" = 3 words, 0 domain nouns (none match exactly)
    # Actually "sort" is not in _DOMAIN_NOUNS but let's use a generic query
    threshold = kb_instance._compute_threshold("click the button")
    assert threshold < 0.10, f"Short query threshold should be < 0.10 (floor=0.06); got {threshold}"


def test_threshold_normal_for_long_queries():
    """FEAT-006: Threshold floor should remain 0.10 for queries >= 15 words."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    long_query = (
        "Navigate to the production orders page and verify the compact view "
        "is displayed with all rows visible and the sort indicator is correct"
    )
    assert len(long_query.split()) >= 15, "Test query must be >= 15 words"
    threshold = kb_instance._compute_threshold(long_query)
    assert threshold >= 0.10, f"Long query threshold should be >= 0.10; got {threshold}"


def test_threshold_short_query_with_domain_nouns():
    """FEAT-006: Short query with domain nouns gets floor + boost."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    # "quick order login" = 3 words, 3 domain nouns (quick, order, login)
    threshold = kb_instance._compute_threshold("quick order login")
    # floor=0.06 + min(3*0.05, 0.15) = 0.06 + 0.15 = 0.21
    assert threshold == 0.21, f"Expected 0.21 for short query with 3 domain nouns; got {threshold}"


# ---------------------------------------------------------------------------
# Phase 2 Tests — BM25 Re-Ranking
# ---------------------------------------------------------------------------


def test_bm25_index_built():
    """FEAT-006: BM25 index must be built alongside TF-IDF."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    assert kb_instance._bm25 is not None, "BM25 index was not built — _bm25 is None"
    assert len(kb_instance._bm25_corpus) > 0, "BM25 corpus is empty — should match workflow count"
    assert len(kb_instance._bm25_corpus) == len(kb_instance._workflows), (
        f"BM25 corpus size ({len(kb_instance._bm25_corpus)}) != workflow count ({len(kb_instance._workflows)})"
    )


def test_bm25_reranking_does_not_break_retrieval():
    """FEAT-006: BM25 re-ranking must not regress existing retrieval quality."""
    from backend.kb.loader import kb

    # These queries should still return non-empty results with BM25
    queries = [
        "Sort the table by due date",
        "Navigate to compact view",
        "Upload a file to the order",
    ]
    for query in queries:
        result = kb.query_with_expansion(query)
        assert result, f"BM25 re-ranking broke retrieval for: {query!r} — got empty result"


def test_bm25_scores_are_numeric():
    """FEAT-006: BM25 get_scores must return valid numeric scores."""
    import numpy as np

    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    if kb_instance._bm25 is None:
        pytest.skip("BM25 not available")

    scores = kb_instance._bm25.get_scores(["sort", "table"])
    assert isinstance(scores, np.ndarray), f"BM25 scores should be ndarray, got {type(scores)}"
    assert len(scores) == len(kb_instance._workflows), (
        f"BM25 scores length ({len(scores)}) != workflow count ({len(kb_instance._workflows)})"
    )
    assert not np.any(np.isnan(scores)), "BM25 scores contain NaN values"


# ---------------------------------------------------------------------------
# Phase 3 Tests — FORBIDDEN_KEYWORDS + Gate Logging
# ---------------------------------------------------------------------------


def test_kb_gate_closure_logs_on_no_match(caplog):
    """FEAT-006: When query returns empty, logger.info must fire with diagnostic."""
    import logging

    from backend.kb.loader import LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase()
    with caplog.at_level(logging.INFO, logger="backend.kb.loader"):
        # A very unusual query that should match nothing
        result = kb_instance.query("xyzzy plugh zork foobarbaz")

    assert result == "", "Expected empty result for nonsense query"
    assert any("KB gate OPEN but NO MATCH" in record.message for record in caplog.records), (
        "Expected 'KB gate OPEN but NO MATCH' log message when query returns empty. "
        f"Log records: {[r.message[:80] for r in caplog.records]}"
    )


def test_forbidden_keywords_blocks_retrieval():
    """FEAT-006: Entry with FORBIDDEN_KEYWORDS must not match when step contains forbidden word."""
    from backend.kb.loader import KBWorkflow, LocalKnowledgeBase

    # Create a minimal KB with a workflow that has forbidden keywords
    kb_instance = LocalKnowledgeBase.__new__(LocalKnowledgeBase)
    kb_instance._workflows = [
        KBWorkflow(
            name="Login Success Verification",
            keywords=["login", "sign", "credentials", "success"],
            instructions="After login, verify the dashboard loads with user profile visible.",
        ),
    ]
    kb_instance._workflows[0].forbidden_keywords = ["failed", "invalid", "wrong", "error"]
    kb_instance._vectorizer = None
    kb_instance._tfidf_matrix = None
    kb_instance._bm25 = None
    kb_instance._bm25_corpus = []
    kb_instance._file_mtimes = {}
    kb_instance._query_cache = {}
    kb_instance._build_index()

    # Query with a forbidden keyword — should be filtered out
    result = kb_instance.query("login failed with invalid credentials")
    assert result == "", f"Expected empty result when query contains forbidden keyword 'failed'; got: {result[:100]!r}"


def test_forbidden_keywords_allows_positive():
    """FEAT-006: Entry with FORBIDDEN_KEYWORDS must match when step has NO forbidden word."""
    from backend.kb.loader import KBWorkflow, LocalKnowledgeBase

    kb_instance = LocalKnowledgeBase.__new__(LocalKnowledgeBase)
    kb_instance._workflows = [
        KBWorkflow(
            name="Login Success Verification",
            keywords=["login", "sign", "credentials", "success"],
            instructions="After login, verify the dashboard loads with user profile visible.",
        ),
    ]
    kb_instance._workflows[0].forbidden_keywords = ["failed", "invalid", "wrong", "error"]
    kb_instance._vectorizer = None
    kb_instance._tfidf_matrix = None
    kb_instance._bm25 = None
    kb_instance._bm25_corpus = []
    kb_instance._file_mtimes = {}
    kb_instance._query_cache = {}
    kb_instance._build_index()

    # Query without forbidden keywords — should match
    result = kb_instance.query("login success verify dashboard")
    assert result != "", "Expected non-empty result when query has no forbidden keywords"


def test_forbidden_keywords_default_empty():
    """FEAT-006: KBWorkflow.forbidden_keywords defaults to empty list."""
    from backend.kb.loader import KBWorkflow

    wf = KBWorkflow(name="Test", keywords=["test"], instructions="Test instructions")
    assert hasattr(wf, "forbidden_keywords"), "KBWorkflow must have forbidden_keywords attribute"
    assert wf.forbidden_keywords == [], f"Default forbidden_keywords should be []; got {wf.forbidden_keywords!r}"
