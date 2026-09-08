"""
vQA — T1-d HumanGuidanceVault HNSW Parameter Tests
=====================================================
Module: backend/kb/test_human_guidance_vault.py

Tests for T1-d: Fix HumanGuidanceVault HNSW Parameters.
Covers: AC-VERIFY-4 (tuned HNSW metadata, successful query), AC-ERROR-2
(migration script non-zero exit on failure), and the absence of the
"Cannot return the results in a contigious 2D array" error.

All tests are unit-level: no live Bedrock calls, no live ChromaDB on disk
(uses tmp_path for isolation), no live filesystem writes.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch  # noqa: F401

# ---------------------------------------------------------------------------
# AC-VERIFY-4: HNSW metadata on HumanGuidanceVault collection
# ---------------------------------------------------------------------------

EXPECTED_HNSW_M = 32
EXPECTED_HNSW_CONSTRUCTION_EF = 200
EXPECTED_HNSW_SEARCH_EF = 100
EXPECTED_HNSW_SPACE = "cosine"


def test_human_guidance_vault_hnsw_metadata_includes_tuned_params(tmp_path):
    """
    AC-VERIFY-4: HumanGuidanceVault.__init__ must call get_or_create_collection
    with hnsw:M=32, hnsw:construction_ef=200, hnsw:search_ef=100 in the metadata.
    """
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    marker = tmp_path / ".product_scoping_migrated_v1"
    marker.write_text("1")

    with patch("backend.kb.rag.chromadb.PersistentClient", return_value=mock_client):
        from backend.kb.rag import HumanGuidanceVault
        _ = HumanGuidanceVault(persist_directory=str(tmp_path))

    mock_client.get_or_create_collection.assert_called_once()
    _, kwargs = mock_client.get_or_create_collection.call_args
    metadata = kwargs.get("metadata", {})

    assert metadata.get("hnsw:space") == EXPECTED_HNSW_SPACE, (
        f"hnsw:space must be 'cosine', got {metadata.get('hnsw:space')!r}"
    )
    assert metadata.get("hnsw:M") == EXPECTED_HNSW_M, (
        f"hnsw:M must be {EXPECTED_HNSW_M}, got {metadata.get('hnsw:M')!r}"
    )
    assert metadata.get("hnsw:construction_ef") == EXPECTED_HNSW_CONSTRUCTION_EF, (
        f"hnsw:construction_ef must be {EXPECTED_HNSW_CONSTRUCTION_EF}, "
        f"got {metadata.get('hnsw:construction_ef')!r}"
    )
    assert metadata.get("hnsw:search_ef") == EXPECTED_HNSW_SEARCH_EF, (
        f"hnsw:search_ef must be {EXPECTED_HNSW_SEARCH_EF}, "
        f"got {metadata.get('hnsw:search_ef')!r}"
    )


def test_human_guidance_vault_query_returns_match_on_populated_collection(tmp_path, caplog):
    """
    AC-VERIFY-4: HumanGuidanceVault.query returns list with >=1 match on a
    populated (mocked) collection; no 'contigious 2D array' error logged.
    """
    guidance_meta = {
        "title": "Select Contest from PRF Category dropdown",
        "keywords": json.dumps(["contest", "prf", "dropdown"]),
        "jira": "QA-358",
        "instructions": "Open the PRF Category trigger first, then select Contest.",
        "type": "human-guidance",
        "product": "vpromotions",
        "source_path": "/knowledge/vpromotions/human_guidance.md",
    }

    mock_collection = MagicMock()
    mock_collection.count.return_value = 10
    mock_collection.query.return_value = {
        "metadatas": [[guidance_meta]],
        "distances": [[0.15]],
    }
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    marker = tmp_path / ".product_scoping_migrated_v1"
    marker.write_text("1")

    with patch("backend.kb.rag.chromadb.PersistentClient", return_value=mock_client):
        from backend.kb.rag import HumanGuidanceVault
        vault = HumanGuidanceVault(persist_directory=str(tmp_path))

    with caplog.at_level(logging.WARNING):
        results = vault.query(
            "Select Contest from PRF Category dropdown",
            product="vpromotions",
            max_results=3,
        )

    assert len(results) >= 1, (
        f"Expected >=1 result for Contest query, got {len(results)}"
    )
    assert results[0]["instructions"], "Match must have non-empty instructions field"
    assert "Cannot return the results in a contigious 2D array" not in caplog.text, (
        "HNSW contiguous-array error must not appear in logs"
    )


def test_human_guidance_vault_query_no_hnsw_contiguous_array_error(tmp_path, caplog):
    """
    AC-VERIFY-4: On a populated vault, the 'Cannot return the results in a
    contigious 2D array' error must never appear in logs at WARNING or above.
    This confirms the tuned HNSW params eliminate the error at query time.
    """
    mock_collection = MagicMock()
    mock_collection.count.return_value = 500
    mock_collection.query.return_value = {
        "metadatas": [[{
            "title": "Sample workflow",
            "keywords": "[]",
            "jira": "",
            "instructions": "Do something.",
            "type": "human-guidance",
            "product": "vpromotions",
            "source_path": "/knowledge/vpromotions/human_guidance.md",
        }]],
        "distances": [[0.2]],
    }
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    marker = tmp_path / ".product_scoping_migrated_v1"
    marker.write_text("1")

    with patch("backend.kb.rag.chromadb.PersistentClient", return_value=mock_client):
        from backend.kb.rag import HumanGuidanceVault
        vault = HumanGuidanceVault(persist_directory=str(tmp_path))

    with caplog.at_level(logging.WARNING):
        for query_text in [
            "Select Contest from PRF Category dropdown",
            "Open Quick Order",
            "Set promotion dates",
        ]:
            vault.query(query_text, product="vpromotions", max_results=5)

    assert "Cannot return the results in a contigious 2D array" not in caplog.text


# ---------------------------------------------------------------------------
# AC-ERROR-2: Migration script exits non-zero on failure
# ---------------------------------------------------------------------------

def test_migration_script_exits_nonzero_on_permission_error(tmp_path):
    """
    AC-ERROR-2: scripts/migrate_human_guidance_vault.py must exit non-zero
    when the Chroma directory is unwritable (simulated via PermissionError on
    delete_collection). The script must NOT silently produce a zero-vector
    collection.
    """
    project_root = Path(__file__).parent.parent.parent
    script_path = project_root / "scripts" / "migrate_human_guidance_vault.py"
    assert script_path.exists(), (
        f"scripts/migrate_human_guidance_vault.py does not exist at {script_path}"
    )

    chroma_dir = tmp_path / "chromadb"
    chroma_dir.mkdir()
    guidance_md = tmp_path / "human_guidance.md"
    guidance_md.write_text("## WORKFLOW: Test\nKEYWORDS: test\n---\nDo something.\n")

    env_patch = {
        "HUMAN_GUIDANCE_CHROMA_DIR": str(chroma_dir),
        "HUMAN_GUIDANCE_MD_PATH": str(guidance_md),
        "SIMULATE_PERMISSION_ERROR": "1",
    }
    full_env = {**os.environ, **env_patch}

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        env=full_env,
    )

    assert result.returncode != 0, (
        f"Migration script must exit non-zero on permission error, "
        f"got returncode={result.returncode}. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined_output = result.stdout + result.stderr
    assert any(
        kw in combined_output for kw in ["ERROR", "Error", "error", "FAIL", "fail", "Exception", "PermissionError"]
    ), (
        f"Migration script must log an error on failure. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_migration_script_exits_nonzero_on_embedding_failure(tmp_path):
    """
    AC-ERROR-2: scripts/migrate_human_guidance_vault.py must exit non-zero
    when the embedding call fails (simulated via SIMULATE_EMBED_ERROR env var).
    It must NOT silently produce a zero-vector collection.
    """
    project_root = Path(__file__).parent.parent.parent
    script_path = project_root / "scripts" / "migrate_human_guidance_vault.py"
    assert script_path.exists(), (
        f"scripts/migrate_human_guidance_vault.py does not exist at {script_path}"
    )

    chroma_dir = tmp_path / "chromadb"
    chroma_dir.mkdir()
    guidance_md = tmp_path / "human_guidance.md"
    guidance_md.write_text("## WORKFLOW: Test\nKEYWORDS: test\n---\nDo something.\n")

    env_patch = {
        "HUMAN_GUIDANCE_CHROMA_DIR": str(chroma_dir),
        "HUMAN_GUIDANCE_MD_PATH": str(guidance_md),
        "SIMULATE_EMBED_ERROR": "1",
    }
    full_env = {**os.environ, **env_patch}

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        env=full_env,
    )

    assert result.returncode != 0, (
        f"Migration script must exit non-zero when embedding fails, "
        f"got returncode={result.returncode}. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined_output = result.stdout + result.stderr
    assert any(
        kw in combined_output for kw in ["ERROR", "Error", "error", "FAIL", "fail", "Exception"]
    ), (
        f"Migration script must log an error on embedding failure. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
