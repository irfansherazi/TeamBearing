"""
vQA — RAG Debugger Pipeline (direct ChromaDB, no LlamaIndex)
=============================================================
Module: backend/engine/rag_debugger.py

Semantically searches indexed Playwright tests and knowledge-base docs to
surface relevant code/rule snippets when a QA execution step fails.

Architecture
------------
::

    query_knowledge_base(error_log)
         │
         ▼
    _embed_query(error_log)  ← Bedrock Titan v2 embedding (boto3 direct call)
         │
         ▼
    chromadb.Collection.query(query_embeddings=[...], n_results=top_k)
         │
         ▼
    Format top-K documents → formatted string (ready for Debugger LLM prompt)

LlamaIndex was removed (T1-c).  It added only overhead on the query path:
  - response_mode="no_text" meant the LLM synthesis step was a no-op
  - The BedrockEmbedding wrapper duplicated what a single boto3 call does
  - llama-index-llms-openai was silently pulled in by llama-index-core, breaking
    every session in environments without an OpenAI key

The ingestion path (ingest_knowledge_base) retains paragraph-level text
splitting; the query path calls chromadb.Collection.query() directly.

Public API
----------
    from backend.engine.rag_debugger import query_knowledge_base, ingest_knowledge_base

    # One-time ingestion (called at startup or on-demand):
    ingest_knowledge_base()

    # Per-failure query (called by the Debugger node):
    recommendation = query_knowledge_base("TimeoutError: locator not found …")

Configuration (via environment / .env)
---------------------------------------
    PLAYWRIGHT_TESTS_DIR   Path to vsuitePlatform/playwright tree
    KNOWLEDGE_BASE_DIR     Path to vQA/knowledge/ (default: auto-detected)
    RAG_CHROMA_DIR         ChromaDB persist dir (default: memory/chroma_rag)
    RAG_EMBED_MODEL_ID     Bedrock embedding model (default: amazon.titan-embed-text-v2:0)
    AWS_BEDROCK_REGION     Bedrock region (default: us-west-2)

Dependencies
------------
    chromadb>=0.5.0,<1.0.0   (direct; no longer transitive via LlamaIndex)
    boto3>=1.34.0,<2.0.0     (already a core dep; used for Bedrock embeddings)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import boto3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# chromadb is a direct dependency (no LlamaIndex shim needed).
# ---------------------------------------------------------------------------
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    _CHROMA_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _CHROMA_AVAILABLE = False
    logger.warning(
        "rag_debugger: chromadb not installed (%s). "
        "Install: pip install chromadb",
        _e,
    )

# ---------------------------------------------------------------------------
# Paths & settings
# ---------------------------------------------------------------------------

_VQAROOT = Path(__file__).parent.parent.parent  # vQA/

_DEFAULT_PW_DIR = _VQAROOT.parent / "vsuitePlatform" / "playwright"
_DEFAULT_KB_DIR = _VQAROOT / "knowledge"
_DEFAULT_CHROMA_DIR = _VQAROOT / "memory" / "chroma_rag"

_PLAYWRIGHT_DIR = Path(os.getenv("PLAYWRIGHT_TESTS_DIR", str(_DEFAULT_PW_DIR)))
_KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_BASE_DIR", str(_DEFAULT_KB_DIR)))
_CHROMA_DIR = Path(os.getenv("RAG_CHROMA_DIR", str(_DEFAULT_CHROMA_DIR)))
_EMBED_MODEL_ID = os.getenv("RAG_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
_BEDROCK_REGION = os.getenv("AWS_BEDROCK_REGION", "us-west-2")

_CHROMA_COLLECTION = "vqa_rag_v1"

# Paragraph splitting settings for ingestion (no LlamaIndex needed)
_MD_CHUNK_SIZE = 512    # approximate characters per chunk
_MD_CHUNK_OVERLAP = 77  # characters of overlap between adjacent chunks

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_chroma_collection_singleton: "chromadb.Collection | None" = None
_chroma_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Bedrock embedding helper (direct boto3 — no LlamaIndex wrapper)
# ---------------------------------------------------------------------------

_bedrock_client: "boto3.client | None" = None
_bedrock_lock = threading.Lock()


def _get_bedrock_client():
    """Return (and cache) the boto3 Bedrock runtime client."""
    global _bedrock_client
    with _bedrock_lock:
        if _bedrock_client is None:
            _bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=_BEDROCK_REGION,
            )
    return _bedrock_client


def _embed_query(text: str) -> list[float]:
    """
    Embed a single query string via Bedrock Titan Embed v2.

    Returns a list of floats (the embedding vector).
    Raises on Bedrock errors so the caller can handle gracefully.
    """
    client = _get_bedrock_client()
    body = json.dumps({"inputText": text})
    response = client.invoke_model(
        modelId=_EMBED_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["embedding"]


def _embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of documents for ingestion.

    Calls _embed_query for each text; batching is left to the caller if
    needed. For ingestion (one-time) this is acceptable.
    """
    return [_embed_query(t) for t in texts]


# ---------------------------------------------------------------------------
# Document loading helpers
# ---------------------------------------------------------------------------


def _load_ts_documents() -> list[dict]:
    """
    Load all TypeScript Playwright test and utility files as plain dicts.
    Each dict has keys: ``text``, ``source_file``, ``file_type``, ``full_path``.

    Skips declaration (.d.ts), reporter, and stub files.
    """
    if not _PLAYWRIGHT_DIR.exists():
        logger.warning(
            "rag_debugger: Playwright dir not found (%s) — no .ts files ingested.",
            _PLAYWRIGHT_DIR,
        )
        return []

    _skip_patterns = {".d.ts", "Reporter.ts", "types.ts"}
    glob_patterns = [
        "tests/*.test.ts",
        "tests/*.spec.ts",
        "utils/*.ts",
        "tests/support/*.ts",
    ]

    documents: list[dict] = []
    for pattern in glob_patterns:
        for ts_file in sorted(_PLAYWRIGHT_DIR.glob(pattern)):
            if any(ts_file.name.endswith(pat) or pat in ts_file.name for pat in _skip_patterns):
                continue
            try:
                content = ts_file.read_text(encoding="utf-8", errors="replace")
                if len(content) < 100:  # skip stubs
                    continue
                documents.append(
                    {
                        "text": content,
                        "source_file": ts_file.name,
                        "file_type": "typescript",
                        "full_path": str(ts_file),
                    }
                )
            except OSError as exc:
                logger.warning("rag_debugger: cannot read %s: %s", ts_file, exc)

    logger.info(
        "rag_debugger: loaded %d TypeScript documents from %s",
        len(documents),
        _PLAYWRIGHT_DIR,
    )
    return documents


def _load_md_documents() -> list[dict]:
    """
    Load all Markdown knowledge-base files as plain dicts.
    Each dict has keys: ``text``, ``source_file``, ``file_type``, ``full_path``.

    Includes: knowledge_base_manuals.md, knowledge/*.md
    """
    md_paths: list[Path] = []

    # Top-level manuals
    manuals = _VQAROOT / "knowledge_base_manuals.md"
    if manuals.exists():
        md_paths.append(manuals)

    # knowledge/ directory
    if _KNOWLEDGE_DIR.exists():
        md_paths.extend(sorted(_KNOWLEDGE_DIR.glob("**/*.md")))

    documents: list[dict] = []
    for md_file in md_paths:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            if len(content) < 50:
                continue
            documents.append(
                {
                    "text": content,
                    "source_file": md_file.name,
                    "file_type": "markdown",
                    "full_path": str(md_file),
                }
            )
        except OSError as exc:
            logger.warning("rag_debugger: cannot read %s: %s", md_file, exc)

    logger.info("rag_debugger: loaded %d Markdown documents", len(documents))
    return documents


# ---------------------------------------------------------------------------
# Text splitting (paragraph-level, no LlamaIndex required)
# ---------------------------------------------------------------------------


def _split_text(text: str, chunk_size: int = _MD_CHUNK_SIZE, overlap: int = _MD_CHUNK_OVERLAP) -> list[str]:
    """
    Split ``text`` into overlapping character-level chunks.

    Splits on paragraph boundaries (double newline) when possible;
    falls back to character-count slicing when paragraphs are too large.
    """
    if not text:
        return []

    # First, try paragraph-level splitting.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > chunk_size and current:
            chunks.append("\n\n".join(current))
            # Carry the last paragraph as overlap.
            current = current[-1:] if overlap > 0 else []
            current_len = len(current[0]) if current else 0
        current.append(para)
        current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _make_chunks(documents: list[dict]) -> list[dict]:
    """
    Split each document into overlapping text chunks.

    Returns a flat list of chunk dicts with keys:
    ``text``, ``source_file``, ``file_type``, ``chunk_id``.
    """
    chunks: list[dict] = []
    for doc in documents:
        text = doc.get("text", "")
        source = doc.get("source_file", "unknown")
        file_type = doc.get("file_type", "text")
        for idx, chunk_text in enumerate(_split_text(text)):
            if not chunk_text.strip():
                continue
            chunks.append(
                {
                    "text": chunk_text,
                    "source_file": source,
                    "file_type": file_type,
                    "chunk_id": f"{source}__chunk_{idx}",
                }
            )
    logger.info("rag_debugger: produced %d chunks from %d documents", len(chunks), len(documents))
    return chunks


# ---------------------------------------------------------------------------
# ChromaDB collection (direct, no LlamaIndex)
# ---------------------------------------------------------------------------


def _get_or_create_collection() -> "chromadb.Collection":
    """
    Return the singleton Chroma collection, creating it if it doesn't exist.

    Thread-safe via module-level lock.
    """
    global _chroma_collection_singleton
    with _chroma_lock:
        if _chroma_collection_singleton is not None:
            return _chroma_collection_singleton

        if not _CHROMA_AVAILABLE:
            raise RuntimeError(
                "rag_debugger: chromadb is not installed. Run: pip install chromadb"
            )

        _CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        chroma_client = chromadb.PersistentClient(
            path=str(_CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = chroma_client.get_or_create_collection(
            name=_CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        _chroma_collection_singleton = collection
        return collection


def _build_and_ingest(collection: "chromadb.Collection") -> int:
    """
    Build the vector index from scratch: load docs → split → embed → upsert.

    Returns the total number of chunks ingested.
    Called once when the ChromaDB collection is empty.
    """
    ts_docs = _load_ts_documents()
    md_docs = _load_md_documents()
    all_docs = ts_docs + md_docs
    all_chunks = _make_chunks(all_docs)

    if not all_chunks:
        logger.warning(
            "rag_debugger: no chunks to index — check PLAYWRIGHT_TESTS_DIR and KNOWLEDGE_BASE_DIR"
        )
        return 0

    logger.info(
        "rag_debugger: embedding %d chunks via Bedrock …",
        len(all_chunks),
    )
    texts = [c["text"] for c in all_chunks]
    embeddings = _embed_documents(texts)
    ids = [c["chunk_id"] for c in all_chunks]
    metadatas = [
        {"source_file": c["source_file"], "file_type": c["file_type"]}
        for c in all_chunks
    ]

    # Upsert in batches to stay within Chroma's batch limits.
    _BATCH = 100
    for start in range(0, len(all_chunks), _BATCH):
        collection.upsert(
            ids=ids[start : start + _BATCH],
            embeddings=embeddings[start : start + _BATCH],
            documents=texts[start : start + _BATCH],
            metadatas=metadatas[start : start + _BATCH],
        )

    logger.info("rag_debugger: ingestion complete — %d chunks in ChromaDB", len(all_chunks))
    return len(all_chunks)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_knowledge_base(force_rebuild: bool = False) -> int:
    """
    Trigger (or re-trigger) the ingestion pipeline.

    Safe to call multiple times — skips embedding if the ChromaDB
    collection already has documents, unless ``force_rebuild=True``.

    Args
    ----
    force_rebuild : bool
        If True, drop and rebuild the ChromaDB collection from scratch.
        Use when the source files have changed significantly.

    Returns
    -------
    int
        Number of vector chunks in the collection after ingestion.
    """
    global _chroma_collection_singleton

    if not _CHROMA_AVAILABLE:
        logger.error("rag_debugger.ingest_knowledge_base(): chromadb not installed")
        return 0

    if force_rebuild:
        with _chroma_lock:
            _chroma_collection_singleton = None
            try:
                _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                chroma_client = chromadb.PersistentClient(
                    path=str(_CHROMA_DIR),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                chroma_client.delete_collection(_CHROMA_COLLECTION)
                logger.info(
                    "rag_debugger: force_rebuild — deleted ChromaDB collection '%s'",
                    _CHROMA_COLLECTION,
                )
            except Exception:
                pass  # Collection may not exist yet

    try:
        collection = _get_or_create_collection()
        existing = collection.count()
        if existing > 0 and not force_rebuild:
            logger.info(
                "rag_debugger: collection '%s' already has %d vectors — skipping ingestion",
                _CHROMA_COLLECTION,
                existing,
            )
            return existing

        count = _build_and_ingest(collection)
        logger.info("rag_debugger: collection has %d vectors after ingest", count)
        return count
    except Exception as exc:
        logger.error("rag_debugger.ingest_knowledge_base() failed: %s", exc)
        return 0


def query_knowledge_base(error_log: str, top_k: int = 3) -> str:
    """
    Semantic vector search: find code snippets or doc rules causing a failure.

    Takes the raw error log or AC step failure text, embeds it via Bedrock,
    and returns the top-K most semantically similar chunks from the indexed
    Playwright tests and vQA knowledge documents.

    Uses direct chromadb.Collection.query() — no LlamaIndex dependency.

    Args
    ----
    error_log : str
        The error message, stack trace, or free-text description of the
        failure.  Passed verbatim to the embedding model.
    top_k : int
        Number of nearest-neighbour chunks to retrieve (default 3).

    Returns
    -------
    str
        A formatted string ready for injection into the Debugger LLM prompt.
        Empty string if the collection is unavailable or no results found.

    Example
    -------
    >>> recommendation = query_knowledge_base(
    ...     "TimeoutError: locator get_by_role('button', name='Submit All') "
    ...     "timed out after 15000ms"
    ... )
    >>> print(recommendation[:200])
    ═══════[RAG DEBUGGER] Relevant Code / Doc Snippets════════
    Source: qo_form_basic.test.ts
    ...
    """
    if not error_log or not error_log.strip():
        return ""

    if not _CHROMA_AVAILABLE:
        logger.warning("rag_debugger.query_knowledge_base(): chromadb unavailable — returning empty result")
        return ""

    try:
        collection = _get_or_create_collection()
        existing = collection.count()

        if existing == 0:
            logger.warning(
                "rag_debugger: collection '%s' is empty — no results to return",
                _CHROMA_COLLECTION,
            )
            return ""

        query_vector = _embed_query(error_log)
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, existing),
            include=["documents", "metadatas", "distances"],
        )

        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        if not documents:
            logger.debug("rag_debugger: no relevant chunks found for error_log=%.80s", error_log)
            return ""

        sections: list[str] = []
        for i, (doc_text, meta, dist) in enumerate(zip(documents, metadatas, distances), 1):
            source = (meta or {}).get("source_file", "unknown")
            file_type = (meta or {}).get("file_type", "text")
            lang_tag = "typescript" if file_type == "typescript" else "markdown"
            # Cosine distance → similarity (Chroma returns distance, not similarity)
            similarity = 1.0 - float(dist)

            # Cap chunk length so the Debugger prompt stays focused
            chunk_text = (doc_text or "").strip()
            if len(chunk_text) > 1800:
                chunk_text = chunk_text[:1800] + "\n... [truncated]"

            sections.append(
                f"[{i}] Source: {source}  (cosine similarity: {similarity:.3f})\n```{lang_tag}\n{chunk_text}\n```"
            )

        joined = "\n\n".join(sections)
        header = (
            "\n===============================================================\n"
            "[RAG DEBUGGER] Relevant Code / Doc Snippets\n"
            "  (Semantically matched via BedrockEmbedding + ChromaDB)\n"
            "  These are the MOST LIKELY sources of the failure. Analyse them\n"
            "  to identify the exact selector, timing, or rule that is wrong.\n"
            "===============================================================\n"
        )
        footer = "===============================================================\n"
        return header + joined + "\n" + footer

    except Exception as exc:
        logger.error(
            "rag_debugger.query_knowledge_base() failed: %s — returning empty result",
            exc,
        )
        return ""
