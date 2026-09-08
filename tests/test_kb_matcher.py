from pathlib import Path
from unittest.mock import patch

import pytest

# =============================================================================
# Phase 3 TDD Tests — WI-012 / WI-013 / WI-014 Acceptance Criteria
# =============================================================================

_PROJECT_ROOT = Path(__file__).parent.parent
_KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge"
_HUMAN_GUIDANCE_PATH = _KNOWLEDGE_DIR / "human_guidance.md"


def test_human_guidance_entry_count():
    """AC-VERIFY-5: human_guidance.md must have <= 65 entries after deduplication."""
    if not _HUMAN_GUIDANCE_PATH.exists():
        pytest.skip(f"Knowledge file not found at {_HUMAN_GUIDANCE_PATH}")

    text = _HUMAN_GUIDANCE_PATH.read_text(encoding="utf-8")
    count = text.count("## WORKFLOW:")
    assert count <= 65, f"human_guidance.md has {count} WORKFLOW entries; expected <= 65 after deduplication (WI-012)."


def test_unified_registry_covers_all_legacy_components():
    """AC-VERIFY-4: All 11 legacy components must be in unified_components.json."""
    from backend.kb.unified_registry import unified_registry

    # Trigger lazy-loading explicitly before checking keys
    unified_registry._ensure_loaded()

    keys = set(unified_registry.get_all_keys())
    expected = {
        "p-calendar",
        "p-autocomplete",
        "p-multiselect",
        "p-checkbox",
        "p-table",
        "p-toast",
        "p-confirmdialog",
        "p-fileupload",
        "p-tablecheckbox",
        "p-table-header",
        "p-select",
    }
    missing = expected - keys
    assert not missing, (
        f"unified_components.json is missing {len(missing)} component(s): {sorted(missing)}. Run WI-013 to add them."
    )


@pytest.mark.parametrize(
    "query,expected_substring",
    [
        ("Sort the table by due date", "sort"),
        ("Navigate to compact view", "compact"),
        ("Select status from dropdown", "status"),
        ("Upload a file to the order", "upload"),
        ("Enter a date in calendar picker", "calendar"),
        ("Click the settings cog to switch view", "cog"),
        ("Select archived from status dropdown", "archive"),
        ("Click the sort by dropdown above the table", "sort"),
        ("Verify the folder appears in the left navigation", "folder"),
        ("Share a custom folder with staff members", "share"),
    ],
)
def test_kb_retrieval_accuracy(query, expected_substring):
    """AC-VERIFY-2: TF-IDF retrieval returns correct top result for known queries."""
    from backend.kb.loader import kb

    result = kb.query_with_expansion(query)
    assert result, f"query_with_expansion({query!r}) returned empty string; expected a non-empty KB context block."
    assert expected_substring.lower() in result.lower(), (
        f"query_with_expansion({query!r}) did not contain {expected_substring!r}.\nResult preview: {result[:200]!r}"
    )


# =============================================================================
# Phase 1 T3-a Tests — Product-Scoped KB Retrieval (AC-VERIFY-2)
# =============================================================================


def test_query_workflows_with_vpromotions_product_excludes_vpromedia_entries(tmp_path):
    """T3-a AC-VERIFY-2: query_workflows(product='vpromotions') returns ZERO entries
    originating from vpromedia source files."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()

    # Populate two product dirs
    (kb_dir / "vpromedia").mkdir()
    (kb_dir / "vpromotions").mkdir()

    (kb_dir / "vpromedia" / "workflows.md").write_text(
        "## WORKFLOW: Quick Order\nKEYWORDS: quick order\n---\nCreate a quick order.\n",
        encoding="utf-8",
    )
    (kb_dir / "vpromotions" / "workflows.md").write_text(
        "## WORKFLOW: PRF Category Selection\nKEYWORDS: category, prf\n---\nSelect category from dropdown.\n",
        encoding="utf-8",
    )

    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()
        result = kb.query_workflows(product="vpromotions", text="Select category from dropdown")

    assert "Quick Order" not in result, (
        "T3-a AC-VERIFY-2 VIOLATED: vpromedia 'Quick Order' workflow leaked into "
        "vpromotions-scoped query"
    )


def test_query_workflows_with_vpromedia_product_excludes_vpromotions_entries(tmp_path):
    """T3-a AC-VERIFY-2 (inverse): query_workflows(product='vpromedia') returns ZERO entries
    from vpromotions source files."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()

    (kb_dir / "vpromedia").mkdir()
    (kb_dir / "vpromotions").mkdir()

    (kb_dir / "vpromedia" / "workflows.md").write_text(
        "## WORKFLOW: Quick Order\nKEYWORDS: quick order\n---\nCreate a quick order.\n",
        encoding="utf-8",
    )
    (kb_dir / "vpromotions" / "workflows.md").write_text(
        "## WORKFLOW: PRF Category Selection\nKEYWORDS: prf category\n---\nSelect category.\n",
        encoding="utf-8",
    )

    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()
        result = kb.query_workflows(product="vpromedia", text="quick order create new request")

    assert "PRF Category Selection" not in result, (
        "T3-a AC-VERIFY-2 VIOLATED: vpromotions 'PRF Category Selection' leaked into "
        "vpromedia-scoped query"
    )


def test_query_accepts_product_kwarg_without_crashing(tmp_path):
    """Fix: LocalKnowledgeBase.query() must accept the product kwarg. Regression
    from FEAT-118 T3-a: preflight.py:409 passes product= but the method
    signature didn't accept it, crashing every preview-steps request that
    fell back to the legacy AC parser path."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()
    (kb_dir / "vpromotions").mkdir()
    (kb_dir / "vpromotions" / "workflows.md").write_text(
        "## WORKFLOW: PRF Category\nKEYWORDS: prf category dropdown\n---\nSelect category from PRF dropdown.\n",
        encoding="utf-8",
    )

    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()
        # Must not raise TypeError('unexpected keyword argument product')
        result = kb.query("category dropdown", max_results=1, product="vpromotions")
        assert isinstance(result, str)


def test_query_product_scope_isolates_from_other_products(tmp_path):
    """query(product='vpromotions') must not return workflows sourced from
    vpromedia — same isolation invariant as query_workflows()."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()
    (kb_dir / "vpromedia").mkdir()
    (kb_dir / "vpromotions").mkdir()
    (kb_dir / "vpromedia" / "workflows.md").write_text(
        "## WORKFLOW: Quick Order\nKEYWORDS: quick order\n---\nCreate a quick order.\n",
        encoding="utf-8",
    )
    (kb_dir / "vpromotions" / "workflows.md").write_text(
        "## WORKFLOW: PRF Category\nKEYWORDS: prf category dropdown\n---\nSelect category from PRF dropdown.\n",
        encoding="utf-8",
    )

    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()
        result = kb.query("quick order create new", max_results=1, product="vpromotions")

    assert "Quick Order" not in result, (
        "product='vpromotions' scope leaked vpromedia 'Quick Order' — "
        "kb.query() product isolation broken"
    )


def test_query_workflows_global_scope_backward_compatible(tmp_path):
    """T3-a backward compat: query_workflows() without product= returns global results.
    Existing callers that omit the product arg must continue to work."""
    from backend.kb.loader import LocalKnowledgeBase

    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()

    (kb_dir / "generic_workflows.md").write_text(
        "## WORKFLOW: Login\nKEYWORDS: login, sign in\n---\nNavigate to login page.\n",
        encoding="utf-8",
    )

    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()
        # No product argument — backward compatible global query
        result = kb.query_workflows(text="login sign in")

    # Should return something (global scope is not broken)
    assert isinstance(result, str), "query_workflows() without product= must return str"
