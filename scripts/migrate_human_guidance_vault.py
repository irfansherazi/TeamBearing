#!/usr/bin/env python3
"""
T1-d One-Shot Migration: HumanGuidanceVault HNSW Parameter Fix
===============================================================
Deletes the existing ``human_guidance`` ChromaDB collection and recreates it
with tuned HNSW parameters:
    hnsw:space="cosine", hnsw:M=32, hnsw:construction_ef=200, hnsw:search_ef=100

The previous defaults (M=16, ef=10) cause:
    "Cannot return the results in a contigious 2D array. Probably ef or M is too small"
at every query when the collection reaches 500+ vectors.

Usage
-----
    python scripts/migrate_human_guidance_vault.py

Environment variables (all optional — defaults match production layout):
    HUMAN_GUIDANCE_CHROMA_DIR   Path to the ChromaDB persist dir
                                (default: <project_root>/storage/chromadb)
    HUMAN_GUIDANCE_MD_PATH      Path to the primary human_guidance.md
                                (default: <project_root>/knowledge/human_guidance.md)
    SIMULATE_PERMISSION_ERROR   Set to "1" to trigger a simulated PermissionError
                                (test hook — exits non-zero)
    SIMULATE_EMBED_ERROR        Set to "1" to trigger a simulated embedding error
                                (test hook — exits non-zero)

Exit codes
----------
    0  Migration successful (or nothing to migrate — collection didn't exist)
    1  Migration failed — full traceback logged to stderr
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("migrate_human_guidance_vault")

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# HNSW parameters that prevent the contiguous-2D-array error at scale.
TUNED_HNSW_METADATA = {
    "hnsw:space": "cosine",
    "hnsw:M": 32,
    "hnsw:construction_ef": 200,
    "hnsw:search_ef": 100,
}

COLLECTION_NAME = "human_guidance"


def _get_chroma_dir() -> Path:
    env_val = os.environ.get("HUMAN_GUIDANCE_CHROMA_DIR")
    if env_val:
        return Path(env_val)
    return _PROJECT_ROOT / "storage" / "chromadb"


def _get_guidance_md_path() -> Path:
    env_val = os.environ.get("HUMAN_GUIDANCE_MD_PATH")
    if env_val:
        return Path(env_val)
    return _PROJECT_ROOT / "knowledge" / "human_guidance.md"


def _parse_guidance_md(file_path: Path) -> list[tuple[str, str]]:
    """Parse human_guidance.md into (doc_text, title) pairs.

    Returns a list of (document_text, title) tuples, one per ## WORKFLOW: section.
    """
    if not file_path.exists():
        logger.warning("Guidance file not found: %s — skipping re-embed", file_path)
        return []

    content = file_path.read_text(encoding="utf-8")
    sections = content.split("## WORKFLOW:")

    entries: list[tuple[str, str]] = []
    for section in sections[1:]:
        lines = section.strip().split("\n")
        if not lines:
            continue
        title = lines[0].strip()

        keywords: list[str] = []
        body_lines: list[str] = []
        in_body = False
        for line in lines[1:]:
            stripped = line.strip()
            if not in_body:
                if stripped.startswith("KEYWORDS:"):
                    keywords = [k.strip() for k in stripped.removeprefix("KEYWORDS:").split(",") if k.strip()]
                elif stripped == "---":
                    in_body = True
            else:
                body_lines.append(line)

        instructions = "\n".join(body_lines).strip()
        if not instructions:
            continue

        doc_text = f"{title}\nKeywords: {', '.join(keywords)}\n{instructions}"
        entries.append((doc_text, title))

    return entries


def main() -> int:
    """Run the migration. Returns 0 on success, 1 on failure."""

    # Test hooks — allow CI/unit tests to simulate failure paths.
    if os.environ.get("SIMULATE_PERMISSION_ERROR") == "1":
        logger.error(
            "SIMULATE_PERMISSION_ERROR: PermissionError writing to ChromaDB directory"
        )
        raise PermissionError("Simulated: cannot write to ChromaDB directory")

    if os.environ.get("SIMULATE_EMBED_ERROR") == "1":
        logger.error(
            "SIMULATE_EMBED_ERROR: BotoCoreError during Bedrock embedding call"
        )
        raise RuntimeError("Simulated: embedding call failed (BotoCoreError)")

    chroma_dir = _get_chroma_dir()
    guidance_md = _get_guidance_md_path()

    logger.info("=== HumanGuidanceVault HNSW Migration ===")
    logger.info("ChromaDB directory: %s", chroma_dir)
    logger.info("Guidance file:      %s", guidance_md)
    logger.info("Target HNSW params: %s", TUNED_HNSW_METADATA)

    # ------------------------------------------------------------------ #
    # Import chromadb (must be available; requirements.txt lists it directly
    # after the T1-c LlamaIndex removal).
    # ------------------------------------------------------------------ #
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from chromadb.utils import embedding_functions
    except ImportError as exc:
        logger.error("chromadb is not installed: %s", exc)
        raise

    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    # ------------------------------------------------------------------ #
    # Step 1: Delete existing collection (if present).
    # ------------------------------------------------------------------ #
    try:
        existing_collections = [c.name for c in client.list_collections()]
    except Exception:
        existing_collections = []

    if COLLECTION_NAME in existing_collections:
        logger.info("Deleting existing '%s' collection …", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)
        logger.info("Deleted '%s' collection.", COLLECTION_NAME)
    else:
        logger.info("Collection '%s' does not exist — nothing to delete.", COLLECTION_NAME)

    # ------------------------------------------------------------------ #
    # Step 2: Recreate collection with tuned HNSW parameters.
    # ------------------------------------------------------------------ #
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata=TUNED_HNSW_METADATA,
    )
    logger.info("Created '%s' collection with tuned HNSW params.", COLLECTION_NAME)

    # ------------------------------------------------------------------ #
    # Step 3: Re-embed all entries from the guidance file.
    # ------------------------------------------------------------------ #
    entries = _parse_guidance_md(guidance_md)
    if not entries:
        logger.warning(
            "No workflow entries found in %s — collection created but is empty.", guidance_md
        )
        # This is NOT an error: the migration itself succeeded; the vault is
        # correctly configured — it simply has no entries until index_guidance_file
        # is called on next startup.
        return 0

    documents = [doc for doc, _title in entries]
    ids = [
        f"vpromedia_{title.lower().replace(' ', '_')}_{idx}"
        for idx, (_doc, title) in enumerate(entries)
    ]
    metadatas = [
        {
            "title": title,
            "instructions": doc.split("\n", 2)[-1] if "\n" in doc else doc,
            "keywords": "[]",
            "jira": "",
            "type": "human-guidance",
            "product": "vpromedia",
            "source_path": str(guidance_md.resolve()),
        }
        for doc, title in entries
    ]

    logger.info("Re-embedding %d workflow entries …", len(entries))
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )
    logger.info(
        "Migration complete: %d entries indexed into '%s' with tuned HNSW params.",
        len(entries),
        COLLECTION_NAME,
    )

    # Write a migration-complete marker alongside the Chroma directory.
    marker = chroma_dir / ".hnsw_migrated_v1"
    try:
        marker.write_text(str(len(entries)))
    except Exception as e:
        logger.warning("Could not write migration marker: %s", e)

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as exc:
        logger.error(
            "Migration FAILED: %s: %s", type(exc).__name__, exc, exc_info=True
        )
        sys.exit(1)
