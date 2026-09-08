import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from backend.engine.culler import semantic_dom_cull
from backend.kb.loader import LocalKnowledgeBase

# Import the system under test (we'll implement this next)
from backend.kb.rag import HumanGuidanceVault


@pytest.fixture
def temp_chroma_dir():
    """Fixture to create and clean up a temporary directory for ChromaDB."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_guidance_file(tmp_path):
    """Fixture to create a sample human_guidance.md file."""
    content = """
## WORKFLOW: List View Sorting
KEYWORDS: list, view, sorting, headers, column, human-guidance, user-instruction
---
List View Sorting
In the List View, sort items by clicking the column headers. Some column headers act as comboboxes and will open a dropdown panel.

## WORKFLOW: Compact View Navigation
KEYWORDS: compact, view, sort, dropdown, settings, cog, human-guidance, user-instruction
---
You are in compact view when there is a "Sort By" dropdown above the table and there are no column headers.
To navigate: click the settings cog icon → select "Compact" from dropdown.

## WORKFLOW: Save Search Automation Folder
KEYWORDS: save, search, folder, beta, boys, human-guidance
---
Need to type "Beta Boys Automation" into the new folder name input then click save, then wait for the page to load.
"""
    file_path = tmp_path / "human_guidance.md"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def test_human_guidance_vault_indexing_and_query(temp_chroma_dir, sample_guidance_file):
    """Test that HumanGuidanceVault parses, indexes, and queries human guidance files."""
    vault = HumanGuidanceVault(
        persist_directory=temp_chroma_dir,
        collection_name="test_human_guidance"
    )

    # Index the sample file
    vault.index_guidance_file(sample_guidance_file)

    # Query with semantic matching (e.g. "how to sort due date in list view")
    # This query has no exact match with "List View Sorting" except "list view",
    # but semantic search should match it.
    results = vault.query("how to sort due date in list view", max_results=1)

    assert len(results) == 1
    assert results[0]["title"] == "List View Sorting"
    assert "In the List View, sort items by clicking the column headers" in results[0]["instructions"]

    # Query for compact view setup
    results_compact = vault.query("change layout to compact view settings cog", max_results=1)
    assert len(results_compact) == 1
    assert results_compact[0]["title"] == "Compact View Navigation"

    # Verify distance thresholding works
    # A completely unrelated query should not return matches if we filter by threshold
    results_unrelated = vault.query("completely unrelated random gibberish query", max_results=1, distance_threshold=0.3)
    assert len(results_unrelated) == 0


def test_loader_skips_human_guidance_file(tmp_path):
    """Verify that the LocalKnowledgeBase skips human_guidance.md in its standard TF-IDF index."""
    # Create temp KB directory
    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()

    # Create standard workflow file
    std_file = kb_dir / "vpromedia-workflows.md"
    std_file.write_text("""
## WORKFLOW: Login to system
KEYWORDS: login, system, credentials
---
Enter username and password then click login.
""", encoding="utf-8")

    # Create human guidance file
    guidance_file = kb_dir / "human_guidance.md"
    guidance_file.write_text("""
## WORKFLOW: Special HITL login guidance
KEYWORDS: login, system, credentials, human-guidance
---
Special instructions for logging in.
""", encoding="utf-8")

    # Patch the _KB_DIR in backend.kb.loader
    with patch("backend.kb.loader._KB_DIR", kb_dir):
        kb = LocalKnowledgeBase()

        # Verify only the standard workflow is loaded into the tfidf/bm25 workflows
        workflow_names = [w.name for w in kb._workflows]
        assert "Login to system" in workflow_names
        assert "Special HITL login guidance" not in workflow_names


def test_loader_routes_queries_to_human_guidance_vault(temp_chroma_dir, sample_guidance_file):
    """Test that LocalKnowledgeBase routes queries through HumanGuidanceVault."""
    # Create a mock human guidance vault
    mock_vault = MagicMock()
    mock_vault.query.return_value = [{
        "title": "Compact View Navigation",
        "instructions": "Click the settings cog icon → select 'Compact' from dropdown.",
        "keywords": ["compact", "view", "settings"],
        "jira": "QA-321"
    }]

    kb = LocalKnowledgeBase()
    # Replace standard vault in loader with our mock
    with patch("backend.kb.loader.human_guidance_vault", mock_vault):
        result = kb.query("sorting compact view client")

        # Verify mock_vault was queried
        mock_vault.query.assert_called_once_with("sorting compact view client", max_results=1, distance_threshold=0.7)

        # Verify formatting matches loader standards
        assert "KNOWLEDGE BASE — vSuite Expert Instructions" in result
        assert "Compact View Navigation" in result
        assert "Click the settings cog icon" in result


def test_semantic_dom_culling():
    """Verify that semantic_dom_cull prunes structural boilerplate but keeps interactive & safety nodes."""
    dense_tree = (
        "[WebArea] \"vSuite Dashboard\"\n"
        "  [navigation] \"Main Navigation\"\n"
        "    [generic]\n"
        "      [generic]\n"
        "        [link] \"Dashboard\"\n"
        "        [link] \"Production Orders\"\n"
        "    [generic]\n"
        "      [none]\n"
        "  [generic]\n"
        "    [generic]\n"
        "      [generic]\n"
        "        [presentation]\n"
        "          [none]\n"
        "            [generic]\n"
        "  [main]\n"
        "    [generic]\n"
        "      [heading] \"Quick Order Form\" (level=1)\n"
        "      [generic]\n"
        "        [generic]\n"
        "          [generic]\n"
        "            [textbox] \"Client Name\" value=\"Bob\"\n"
        "          [generic]\n"
        "            [presentation]\n"
        "        [generic]\n"
        "          [generic]\n"
        "            [generic]\n"
        "              [button] \"Submit All\"\n"
        "      [generic]\n"
        "        [generic]\n"
        "          [generic]\n"
        "            [none]\n"
        "  [generic]\n"
        "    [presentation]\n"
        "      [generic]\n"
        "        [none] \"Decorative Side Widget\"\n"
        "  [generic]\n"
        "    [none] \"Background Image Banner\"\n"
        "  [contentinfo]\n"
        "    [generic]\n"
        "      [generic]\n"
        "        [none]\n"
    )

    culled = semantic_dom_cull(dense_tree)

    # Check that interactive elements are kept
    assert "[link] \"Dashboard\"" in culled
    assert "[link] \"Production Orders\"" in culled
    assert "[textbox] \"Client Name\" value=\"Bob\"" in culled
    assert "[button] \"Submit All\"" in culled

    # Check that safety/landmark elements are kept
    assert "[navigation] \"Main Navigation\"" in culled
    assert "[main]" in culled
    assert "[heading] \"Quick Order Form\" (level=1)" in culled
    assert "[contentinfo]" in culled

    # Check that structural/boilerplate wrappers with no interactive/safety children are pruned
    assert "Decorative Side Widget" not in culled
    assert "Background Image Banner" not in culled

    # Verify size reduction of >= 40%
    original_len = len(dense_tree)
    culled_len = len(culled)
    reduction = (original_len - culled_len) / original_len

    # Let's log it
    print(f"\nOriginal: {original_len} chars, Culled: {culled_len} chars, Reduction: {reduction:.1%}")
    assert reduction >= 0.40


@pytest.mark.anyio
async def test_split_execution_coordinate_resolution():
    """Verify that LocalObjectDetector maps a target description to coordinates and the executor executes it."""
    from unittest.mock import AsyncMock

    from backend.browser.vision_utils import LocalObjectDetector
    from backend.engine.executor import _dispatch_action

    mock_page = MagicMock()
    mock_page.is_closed.return_value = False

    # Mock elements returned by the JS query
    mock_elements = [
        {
            "tag": "button",
            "role": "button",
            "text": "Submit All",
            "ariaLabel": "",
            "placeholder": "",
            "title": "",
            "name": "",
            "x": 100,
            "y": 200,
            "width": 80,
            "height": 30,
            "selector": "button.submit-all",
        },
        {
            "tag": "input",
            "role": "textbox",
            "text": "",
            "ariaLabel": "Folder name input",
            "placeholder": "Enter name",
            "title": "",
            "name": "folder_name",
            "x": 300,
            "y": 400,
            "width": 150,
            "height": 40,
            "selector": "input#folder-name",
        },
    ]

    # Mock evaluate to return our element list
    async def mock_evaluate(js_query, *args):
        return mock_elements

    mock_page.evaluate = mock_evaluate

    # 1. Test LocalObjectDetector resolution
    coords_click = await LocalObjectDetector.resolve_target(mock_page, "Submit button")
    assert coords_click is not None
    assert coords_click["x"] == 100
    assert coords_click["y"] == 200
    assert coords_click["selector"] == "button.submit-all"

    coords_fill = await LocalObjectDetector.resolve_target(mock_page, "Folder name input")
    assert coords_fill is not None
    assert coords_fill["x"] == 300
    assert coords_fill["y"] == 400
    assert coords_fill["selector"] == "input#folder-name"

    # Test resolution failure/fallback
    coords_none = await LocalObjectDetector.resolve_target(mock_page, "completely non-existent element label")
    assert coords_none is None

    # 2. Test executor dispatching semantic_click
    mock_page.mouse = MagicMock()
    mock_page.mouse.move = AsyncMock()
    mock_page.mouse.click = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    action_click = {
        "action": "semantic_click",
        "target": "Submit button",
        "reasoning": "Test click resolution",
        "kb_acknowledgement": "No KB rules found for this step.",
    }

    result = await _dispatch_action(mock_page, action_click)
    # _dispatch_action returns None or is no-op if successful and no overlays/toasts found
    # But wait, does it return None or a dict?
    # Let's check: normally it returns a dict or None. If it successfully finishes, it continues to final lines of _dispatch_action which returns None or a dict.
    # Actually, let's verify if _dispatch_action returns None or a dict on success.
    # In executor.py, standard return on success is None (if not overridden by a recipe or primeng_dropdown).
    assert result is None or isinstance(result, dict)

    # Verify mouse actions were called on correct coordinates
    mock_page.mouse.move.assert_called_with(100, 200)
    mock_page.mouse.click.assert_called_with(100, 200, delay=100)

    # 3. Test executor dispatching semantic_fill
    mock_page.keyboard = MagicMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.keyboard.type = AsyncMock()

    action_fill = {
        "action": "semantic_fill",
        "target": "Folder name input",
        "value": "Beta Folder",
        "reasoning": "Test fill resolution",
        "kb_acknowledgement": "No KB rules found for this step.",
    }

    result_fill = await _dispatch_action(mock_page, action_fill)
    assert result_fill is None or isinstance(result_fill, dict)

    # Verify mouse and keyboard actions
    mock_page.mouse.move.assert_called_with(300, 400)
    mock_page.mouse.click.assert_called_with(300, 400, delay=100)
    mock_page.keyboard.press.assert_called_with("Control+a")
    mock_page.keyboard.type.assert_called_with("Beta Folder", delay=30)



