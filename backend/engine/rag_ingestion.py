"""
vQA — RAG Ingestion Pipeline
==============================
Module: backend/engine/rag_ingestion.py

Ingests Markdown knowledge base profile files from ``backend/kb/profiles/``
into a persistent local ChromaDB vector store using LlamaIndex and Amazon
Bedrock embeddings.

Usage
-----
Run as a script to (re-)build the vector store from scratch:

    python -m backend.engine.rag_ingestion

Or import the ``get_query_engine`` helper to query at runtime:

    from backend.engine.rag_ingestion import get_query_engine
    engine = get_query_engine()
    response = engine.query("How do I click a PrimeNG 19 dropdown?")

Architecture
------------
1.  ``ProfileLoader``   – Scans ``backend/kb/profiles/`` for ``*.md`` files.
2.  ``MarkdownNodeParser`` – Splits each doc on Markdown headers (##, ###) so
    each UI rule section becomes its own node (avoids severing rules mid-way).
    Falls back to ``SentenceSplitter`` with overlap for large sections.
3.  ``BedrockEmbedding`` – Uses Amazon Titan text-embeddings-v2 (1536-dim) via
    Bedrock. Falls back to Cohere Embed v3 if Titan fails.
4.  ``ChromaVectorStore`` – Persists the HNSW index on disk at
    ``backend/memory/vector_store/``. Subsequent runs ONLY re-ingest files
    whose ``mtime`` has changed (incremental hot-reload).
5.  ``VectorStoreIndex`` – Wraps the Chroma store; exposes a ``query_engine``
    with similarity_top_k=5 for planner injection.

Configuration
-------------
All Amazon Bedrock credentials come from ``backend.config`` / environment:
  - AWS_REGION          (default: us-east-1)
  - AWS_ACCESS_KEY_ID   (or IAM role / instance profile)
  - AWS_SECRET_ACCESS_KEY

Embedding model priority:
  1. amazon.titan-embed-text-v2:0  (1536 dims, best coverage)
  2. cohere.embed-english-v3       (1024 dims, fallback)

ChromaDB collection name: ``vsuite_primeng_rules``
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

# ── LlamaIndex: ChromaDB vector store ────────────────────────────────────────
import chromadb
from chromadb.config import Settings as ChromaSettings

# ── LlamaIndex core ──────────────────────────────────────────────────────────
from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.schema import Node, TextNode

# ── LlamaIndex: Bedrock embeddings ───────────────────────────────────────────
from llama_index.embeddings.bedrock import BedrockEmbedding  # type: ignore
from llama_index.vector_stores.chroma import ChromaVectorStore  # type: ignore

logger = logging.getLogger(__name__)

# ── Path Constants ────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent  # backend/engine/
_BACKEND_DIR = _HERE.parent  # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent  # project root (vQA/)

PROFILES_DIR = _BACKEND_DIR / "kb" / "profiles"
VECTOR_STORE_DIR = _BACKEND_DIR / "memory" / "vector_store"
META_FILE = VECTOR_STORE_DIR / ".ingest_meta.json"  # tracks file mtimes

# ── Chroma collection name ────────────────────────────────────────────────────
CHROMA_COLLECTION = "vsuite_primeng_rules"

# ── Embedding config ─────────────────────────────────────────────────────────
_TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
_COHERE_MODEL_ID = "cohere.embed-english-v3"

# ── Chunking config ───────────────────────────────────────────────────────────
# MarkdownNodeParser splits on ## / ### headers.
# SentenceSplitter is used as a second pass for sections > MAX_SECTION_CHARS
# to prevent a single oversized node from dominating retrieval.
MAX_SECTION_CHARS = 1800  # split large sections into overlapping sub-chunks
CHUNK_OVERLAP_CHARS = 200  # overlap to avoid severing rules mid-sentence


def _get_aws_region() -> str:
    """Read AWS region from env or config, defaulting to us-east-1."""
    try:
        from backend.config import settings  # type: ignore

        return getattr(settings, "AWS_REGION", None) or os.environ.get("AWS_REGION", "us-east-1")
    except ImportError:
        return os.environ.get("AWS_REGION", "us-east-1")


def _build_embed_model() -> BedrockEmbedding:
    """
    Build the Bedrock embedding model.

    Tries Titan v2 first. If unavailable (e.g., region restriction or quota),
    falls back to Cohere Embed English v3.
    """
    region = _get_aws_region()
    logger.info("RAG: initialising Bedrock embedding model (region=%s)", region)

    last_titan_err = None
    try:
        model = BedrockEmbedding(
            model_name=_TITAN_MODEL_ID,
            region_name=region,
        )
        # Smoke-test with a tiny string to catch auth/quota issues early
        _ = model.get_text_embedding("ping")
        logger.info("RAG: using Amazon Titan Embed v2 (%s)", _TITAN_MODEL_ID)
        return model
    except Exception as titan_err:
        last_titan_err = titan_err
        logger.warning(
            "RAG: Titan embed failed (%s) — falling back to Cohere Embed v3",
            titan_err,
        )

    try:
        model = BedrockEmbedding(
            model_name=_COHERE_MODEL_ID,
            region_name=region,
        )
        _ = model.get_text_embedding("ping")
        logger.info("RAG: using Cohere Embed v3 (%s)", _COHERE_MODEL_ID)
        return model
    except Exception as cohere_err:
        raise RuntimeError(
            f"RAG: both Titan and Cohere Bedrock embeddings failed.\n"
            f"Titan error: {last_titan_err}\n"
            f"Cohere error: {cohere_err}\n"
            f"Check AWS credentials, region ({region}), and Bedrock model access."
        ) from cohere_err


def _build_chroma_store(
    collection_name: str = CHROMA_COLLECTION,
) -> tuple[chromadb.Collection, ChromaVectorStore]:
    """
    Create (or open) the persistent ChromaDB collection at VECTOR_STORE_DIR.

    Returns
    -------
    tuple[chromadb.Collection, ChromaVectorStore]
    """
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(VECTOR_STORE_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    store = ChromaVectorStore(chroma_collection=collection)
    return collection, store


def _load_profiles() -> list[Document]:
    """
    Scan PROFILES_DIR for ``*.md`` files and load them as LlamaIndex Documents.

    Each Document carries metadata:
      - ``file_name``: basename of the source file
      - ``file_path``: absolute path
      - ``mtime``: file modification time (float)
      - ``profile``: stem name (e.g., ``primeng_rules``)
    """
    if not PROFILES_DIR.exists():
        raise FileNotFoundError(
            f"RAG: profiles directory not found: {PROFILES_DIR}\n"
            f"Expected: backend/kb/profiles/ containing *.md rule files."
        )

    md_files = sorted(PROFILES_DIR.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"RAG: no *.md files found in {PROFILES_DIR}")

    documents: list[Document] = []
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        doc = Document(
            text=text,
            metadata={
                "file_name": path.name,
                "file_path": str(path.resolve()),
                "mtime": path.stat().st_mtime,
                "profile": path.stem,
            },
            id_=_doc_id(path),
        )
        documents.append(doc)
        logger.info(
            "RAG: loaded profile '%s' (%d chars)",
            path.name,
            len(text),
        )

    return documents


def _doc_id(path: Path) -> str:
    """Stable deterministic document ID derived from the file's absolute path."""
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]


def _chunk_documents(documents: list[Document]) -> list[TextNode]:
    """
    Parse and chunk documents using a two-stage strategy:

    Stage 1 — MarkdownNodeParser:
        Splits on Markdown section headers (## and ###). Each rule section
        in primeng_rules.md maps cleanly to one node. Headers are retained
        in the node text so retrieval context is self-contained.

    Stage 2 — SentenceSplitter (overflow guard):
        Any node produced by stage 1 that exceeds MAX_SECTION_CHARS is
        further sub-chunked with CHUNK_OVERLAP_CHARS overlap to prevent a
        single large section from dominating retrieval similarity scores.

    Returns
    -------
    list[TextNode]
        Flat list of all chunked nodes ready for embedding.
    """
    logger.info(
        "RAG: chunking %d document(s) with MarkdownNodeParser → SentenceSplitter overflow",
        len(documents),
    )

    # Stage 1: split on Markdown headers
    md_parser = MarkdownNodeParser()
    stage1_nodes: list[Node] = md_parser.get_nodes_from_documents(documents)
    logger.info("RAG: MarkdownNodeParser produced %d nodes", len(stage1_nodes))

    # Stage 2: overflow guard — sub-chunk large sections
    overflow_splitter = SentenceSplitter(
        chunk_size=MAX_SECTION_CHARS,
        chunk_overlap=CHUNK_OVERLAP_CHARS,
    )

    final_nodes: list[TextNode] = []
    overflow_count = 0

    for node in stage1_nodes:
        if not isinstance(node, TextNode):
            continue
        if len(node.text) > MAX_SECTION_CHARS:
            # Sub-chunk this section to avoid oversized nodes
            sub_nodes = overflow_splitter.get_nodes_from_documents([Document(text=node.text, metadata=node.metadata)])
            final_nodes.extend(n for n in sub_nodes if isinstance(n, TextNode))
            overflow_count += len(sub_nodes)
        else:
            final_nodes.append(node)

    logger.info(
        "RAG: final node count = %d (%d overflow sub-chunks from large sections)",
        len(final_nodes),
        overflow_count,
    )
    return final_nodes


def _load_meta() -> dict[str, float]:
    """Load the ingest metadata file (maps file path → last-ingested mtime)."""
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_meta(meta: dict[str, float]) -> None:
    """Persist the ingest metadata file."""
    META_FILE.write_text(json.dumps(meta, indent=2))


def _files_need_ingestion(
    documents: list[Document],
    meta: dict[str, float],
) -> list[Document]:
    """
    Return only the documents whose mtime has changed since last ingest.

    This enables incremental re-ingestion: unchanged files are skipped,
    saving Bedrock API calls and time.
    """
    changed: list[Document] = []
    for doc in documents:
        path_str = doc.metadata["file_path"]
        current_mtime = doc.metadata["mtime"]
        if meta.get(path_str, -1.0) != current_mtime:
            changed.append(doc)
            logger.info(
                "RAG: '%s' — mtime changed (%.0f → %.0f), will re-ingest",
                doc.metadata["file_name"],
                meta.get(path_str, 0.0),
                current_mtime,
            )
        else:
            logger.debug(
                "RAG: '%s' — unchanged, skipping",
                doc.metadata["file_name"],
            )
    return changed


# ── Public API ────────────────────────────────────────────────────────────────


def ingest(force: bool = False) -> VectorStoreIndex:
    """
    Full ingest pipeline: load → chunk → embed → persist to ChromaDB.

    Parameters
    ----------
    force : bool
        If True, re-ingest ALL profile files regardless of mtime changes.
        Default is False (incremental mode).

    Returns
    -------
    VectorStoreIndex
        The loaded/updated index, ready for querying.
    """
    logger.info("RAG: starting ingest pipeline (force=%s)", force)

    # 1. Load all profile documents
    documents = _load_profiles()

    # 2. Incremental check (skip unchanged files unless force=True)
    meta = _load_meta()
    if force:
        to_ingest = documents
        logger.info("RAG: force=True — re-ingesting all %d document(s)", len(to_ingest))
    else:
        to_ingest = _files_need_ingestion(documents, meta)

    if not to_ingest:
        logger.info("RAG: all profile files are up-to-date — loading existing index")
        return _load_existing_index()

    # 3. Chunk the changed documents
    nodes = _chunk_documents(to_ingest)

    if not nodes:
        raise ValueError("RAG: chunking produced 0 nodes — check Markdown file content.")

    # 4. Build embedding model
    embed_model = _build_embed_model()
    Settings.embed_model = embed_model
    Settings.llm = None  # We don't need an LLM for ingestion

    # 5. Build / open ChromaDB store
    _collection, chroma_store = _build_chroma_store()
    storage_context = StorageContext.from_defaults(vector_store=chroma_store)

    # 6. Delete stale nodes for re-ingested files so we don't accumulate duplicates
    _purge_stale_nodes(_collection, [d.metadata["file_path"] for d in to_ingest])

    # 7. Build / update the index
    logger.info(
        "RAG: embedding %d nodes via Bedrock → persisting to ChromaDB at %s",
        len(nodes),
        VECTOR_STORE_DIR,
    )
    index = VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        show_progress=True,
    )

    # 8. Update metadata to reflect new mtimes
    for doc in to_ingest:
        meta[doc.metadata["file_path"]] = doc.metadata["mtime"]
    _save_meta(meta)

    logger.info(
        "RAG: ingest complete — %d new/updated nodes persisted to '%s'",
        len(nodes),
        CHROMA_COLLECTION,
    )
    return index


def _load_existing_index() -> VectorStoreIndex:
    """
    Load the existing ChromaDB-backed index without re-embedding.
    Called when all files are up-to-date.
    """
    embed_model = _build_embed_model()
    Settings.embed_model = embed_model
    Settings.llm = None

    _collection, chroma_store = _build_chroma_store()
    storage_context = StorageContext.from_defaults(vector_store=chroma_store)
    return VectorStoreIndex.from_vector_store(
        chroma_store,
        storage_context=storage_context,
    )


def _purge_stale_nodes(
    collection: chromadb.Collection,
    file_paths: list[str],
) -> None:
    """
    Delete all Chroma nodes whose ``file_path`` metadata matches any of
    the given paths. Called before re-ingesting updated files to prevent
    duplicate nodes accumulating in the index.
    """
    for file_path in file_paths:
        try:
            results = collection.get(where={"file_path": file_path})
            ids_to_delete = results.get("ids", [])
            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.info(
                    "RAG: purged %d stale nodes for '%s'",
                    len(ids_to_delete),
                    Path(file_path).name,
                )
        except Exception as e:
            logger.warning("RAG: could not purge stale nodes for '%s': %s", file_path, e)


def get_query_engine(
    similarity_top_k: int = 5,
    force_ingest: bool = False,
) -> BaseQueryEngine:
    """
    Get a ready-to-use query engine backed by the persisted vector store.

    Automatically triggers incremental ingest if any profile files have
    changed since the last run.

    Parameters
    ----------
    similarity_top_k : int
        Number of most-similar nodes to retrieve per query.
        Default 5 provides good coverage across the 20 UI rule sections.
    force_ingest : bool
        If True, force a full re-ingest before returning the engine.

    Returns
    -------
    BaseQueryEngine
        A LlamaIndex query engine. Call ``engine.query("your question")``
        and access ``.response`` on the result.

    Example
    -------
    >>> from backend.engine.rag_ingestion import get_query_engine
    >>> engine = get_query_engine()
    >>> result = engine.query("How do I open a PrimeNG 19 dropdown?")
    >>> print(result.response)
    """
    index = ingest(force=force_ingest)
    return index.as_query_engine(similarity_top_k=similarity_top_k)


def query_ui_rules(question: str, top_k: int = 5) -> str:
    """
    Convenience wrapper: query the UI rules vector store and return the
    synthesised response string.

    Suitable for direct injection into the agent's planning prompt.

    Parameters
    ----------
    question : str
        A natural-language description of the UI interaction challenge, e.g.:
        "How do I click a PrimeNG datepicker in Modal context?"
    top_k : int
        Number of nodes to retrieve (default 5).

    Returns
    -------
    str
        The synthesised answer from the retrieved KB nodes, or an empty string
        if retrieval fails.
    """
    try:
        engine = get_query_engine(similarity_top_k=top_k)
        result = engine.query(question)
        return str(result.response) if result else ""
    except Exception as exc:
        logger.error("RAG query failed: %s", exc)
        return ""


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    """
    CLI entry point.

    Usage:
        python -m backend.engine.rag_ingestion [--force] [--query "..."] [--verbose]

    Flags:
        --force         Re-ingest ALL profile files (ignore mtime cache)
        --query "..."   After ingesting, run a test query and print the result
        --verbose       Enable DEBUG logging
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="vQA RAG Ingestion Pipeline — embeds backend/kb/profiles/*.md into ChromaDB"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full re-ingest of all profile files (ignore mtime cache)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        metavar="QUESTION",
        help="After ingesting, run a test query and print the result",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    args = parser.parse_args()

    _configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("vQA RAG Ingestion Pipeline")
    logger.info("  Profiles dir : %s", PROFILES_DIR)
    logger.info("  Vector store : %s", VECTOR_STORE_DIR)
    logger.info("  Collection   : %s", CHROMA_COLLECTION)
    logger.info("=" * 60)

    try:
        index = ingest(force=args.force)
        logger.info("✓ Ingest complete.")

        if args.query:
            logger.info('\nRunning test query: "%s"', args.query)
            engine = index.as_query_engine(similarity_top_k=5)
            result = engine.query(args.query)
            print("\n" + "=" * 60)
            print("QUERY:", args.query)
            print("=" * 60)
            print(result.response)
            print("=" * 60)

            # Print source nodes for inspection
            if hasattr(result, "source_nodes") and result.source_nodes:
                print(f"\nTop {len(result.source_nodes)} retrieved node(s):")
                for i, node in enumerate(result.source_nodes, 1):
                    score = getattr(node, "score", "N/A")
                    text_preview = node.text[:120].replace("\n", " ")
                    print(f"  [{i}] score={score:.4f}  '{text_preview}...'")

    except FileNotFoundError as e:
        logger.error("Setup error: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        logger.error("Bedrock error: %s", e)
        sys.exit(2)
    except Exception as e:
        logger.exception("Unexpected error during ingest: %s", e)
        sys.exit(3)


if __name__ == "__main__":
    main()
