import json
import logging
from pathlib import Path
from typing import List, Optional

# ONNX runtime CoreML provider bypass on macOS to prevent compilation hangs
try:
    import onnxruntime
    # Force onnxruntime to only advertise and use CPUExecutionProvider
    onnxruntime.get_available_providers = lambda: ["CPUExecutionProvider"]
    _original_session = onnxruntime.InferenceSession
    class CPUInferenceSession(_original_session):
        def __init__(self, *args, **kwargs):
            kwargs["providers"] = ["CPUExecutionProvider"]
            super().__init__(*args, **kwargs)
    onnxruntime.InferenceSession = CPUInferenceSession
except ImportError:
    pass

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from chromadb.utils import embedding_functions
    _CHROMADB_AVAILABLE = True
except Exception as _e:
    chromadb = None
    ChromaSettings = None
    embedding_functions = None
    _CHROMADB_AVAILABLE = False
    logging.getLogger(__name__).warning("chromadb not available: %s", _e)

from backend.config import settings
from backend.engine.schemas import MultiActorTestPlan

logger = logging.getLogger(__name__)

# Default persist directory for ChromaDB
_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_CHROMA_DIR = _VQAROOT / "memory" / "chroma_rag" / "test_plan_vault"
_DEFAULT_GUIDANCE_CHROMA_DIR = _VQAROOT / "storage" / "chromadb"

class TestPlanVault:
    """
    ChromaDB-backed vault for storing and retrieving successful MultiActorTestPlans.

    Indexes plans by the ticket text (embeddings) to allow semantic retrieval
    of similar past test plans.
    """
    __test__ = False

    def __init__(self, persist_directory: Optional[str] = None, collection_name: str = "test_plans"):
        self.persist_directory = persist_directory or str(_DEFAULT_CHROMA_DIR)
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        if not _CHROMADB_AVAILABLE:
            self.client = None
            self.collection = None
            return

        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"TestPlanVault initialized at {self.persist_directory}")

    def index_plan(self, ticket_text: str, plan: MultiActorTestPlan):
        """
        Index a successful test plan.

        Args:
            ticket_text: The raw JIRA ticket text used to generate the plan.
            plan: The MultiActorTestPlan object.
        """
        plan_id = plan.test_plan_id
        plan_json = plan.model_dump_json()

        self.collection.add(
            documents=[ticket_text],
            metadatas=[{"plan_json": plan_json, "test_title": plan.test_title}],
            ids=[plan_id]
        )
        logger.info(f"Indexed test plan: {plan_id}")

    def query_plans(
        self,
        query_text: str,
        n_results: int = 3,
        min_score: Optional[float] = None
    ) -> List[MultiActorTestPlan]:
        """
        Retrieve the most similar test plans for a given query text,
        filtering by minimum similarity threshold (1 - distance).

        Args:
            query_text: The ticket text or description to search for.
            n_results: Maximum number of results to return.
            min_score: Optional minimum similarity threshold. Default from settings.

        Returns:
            List of MultiActorTestPlan objects that meet the threshold.
        """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )

        plans = []
        if results and "metadatas" in results and results["metadatas"]:
            metadatas = results["metadatas"][0] if results["metadatas"] else []
            distances = results["distances"][0] if (results and "distances" in results and results["distances"]) else [0.0] * len(metadatas)

            effective_min_score = min_score if min_score is not None else settings.kb_min_similarity_score

            for metadata, dist in zip(metadatas, distances):
                score = 1.0 - dist
                if score >= effective_min_score:
                    plan_json = metadata.get("plan_json")
                    if plan_json:
                        try:
                            plans.append(MultiActorTestPlan.model_validate_json(plan_json))
                        except Exception as e:
                            logger.error(f"Failed to deserialize plan from vault: {e}")

        return plans


class HumanGuidanceVault:
    """
    ChromaDB-backed vault for storing and retrieving human guidance workflows.

    Indexes workflow instructions using dense semantic embeddings (all-MiniLM-L6-v2)
    to allow semantic querying instead of keyword/literal matching.
    """
    def __init__(self, persist_directory: Optional[str] = None, collection_name: str = "human_guidance"):
        self.persist_directory = persist_directory or str(_DEFAULT_GUIDANCE_CHROMA_DIR)
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        if not _CHROMADB_AVAILABLE:
            self.client = None
            self.collection = None
            self.embedding_function = None
            return

        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        self.embedding_function = embedding_functions.DefaultEmbeddingFunction()

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:M": 32,
                "hnsw:construction_ef": 200,
                "hnsw:search_ef": 100,
            }
        )
        logger.info(f"HumanGuidanceVault initialized at {self.persist_directory}")

        # One-time migration: purge legacy entries that lack the ``product``
        # metadata field. Those were written by pre-scoping code paths and,
        # left in place, would leak vpromedia guidance into a vpromotions
        # query (they'd match any product's ``$in`` filter because the field
        # is missing). The source .md files are re-parsed by ``_load_all`` on
        # the same startup, so no data is lost — only the untagged copies.
        self._migrate_untagged_entries_once()

    def _migrate_untagged_entries_once(self) -> None:
        """Delete legacy entries that predate the product-scoping change.

        Idempotent: writes a marker file after the first successful run and
        skips on subsequent boots. Safe to remove the marker to force a
        re-migration.
        """
        marker = Path(self.persist_directory) / ".product_scoping_migrated_v1"
        if marker.exists():
            return
        try:
            # ChromaDB has no "get all" without a where; peek() with a large
            # limit returns everything for the small vaults this code targets.
            snapshot = self.collection.get(include=["metadatas"])
            ids = snapshot.get("ids", []) or []
            metas = snapshot.get("metadatas", []) or []
            untagged_ids = [
                _id for _id, meta in zip(ids, metas)
                if not (meta or {}).get("product")
            ]
            if untagged_ids:
                # Batch-delete to avoid one call per id on large collections.
                self.collection.delete(ids=untagged_ids)
                logger.info(
                    "HumanGuidanceVault: purged %d legacy un-tagged entries "
                    "(they will be re-indexed from source .md files with correct product scope)",
                    len(untagged_ids),
                )
            marker.write_text("1")
        except Exception as e:
            # Non-fatal: leaving untagged entries means product filters may
            # be leakier than intended, but the vault still functions. Log
            # and let the caller retry on next boot.
            logger.warning(
                "HumanGuidanceVault: legacy-entry migration failed (will retry next boot): %s",
                e,
            )

    def index_guidance_file(self, file_path: Path, product: str | None = None):
        """
        Parses and indexes a human guidance markdown file.

        Splits the file on '## WORKFLOW:' and indexes each section.

        Args
        ----
        file_path : Path
            The guidance file to index.
        product : str | None
            Product slug to tag every entry with. When ``None`` the entry is
            global-neutral (rare — the legacy root ``knowledge/human_guidance.md``
            is treated as ``product="vpromedia"`` because that's the product it
            was populated from).
        """
        if not file_path.exists():
            logger.warning(f"Guidance file not found: {file_path}")
            return

        # Check if we need to index based on file mtime. The mtime cache is
        # per-file, keyed by the file path, so per-product guidance files
        # don't fight over one shared mtime marker.
        mtime = file_path.stat().st_mtime
        _mtime_key = str(file_path.resolve()).replace("/", "_").replace("\\", "_")
        mtime_file = Path(self.persist_directory) / f".last_guidance_mtime_{_mtime_key}"
        legacy_mtime_file = Path(self.persist_directory) / ".last_guidance_mtime"
        # Migrate legacy single-file mtime cache to per-file so re-indexing
        # doesn't re-run unnecessarily after upgrade.
        if legacy_mtime_file.exists() and not mtime_file.exists() and file_path.name == "human_guidance.md" and product == "vpromedia":
            try:
                mtime_file.write_text(legacy_mtime_file.read_text())
            except Exception:
                pass
        if mtime_file.exists() and self.collection.count() > 0:
            try:
                last_mtime = float(mtime_file.read_text().strip())
                if mtime <= last_mtime:
                    logger.info(
                        "HumanGuidanceVault: %s has not changed (product=%s), skipping indexing.",
                        file_path.name,
                        product or "<global>",
                    )
                    return
            except Exception:
                pass

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to read guidance file {file_path}: {e}")
            return

        sections = content.split("## WORKFLOW:")
        documents = []
        metadatas = []
        ids = []

        # Purge any prior entries indexed from this (file, product) scope so
        # workflow blocks that were removed by hand-editing (or by an admin
        # cleanup pass) actually vanish from retrieval. Without this step
        # ``upsert`` only overwrites entries whose ID is still generated by
        # the current file — stale IDs live forever, hijacking Phase -1
        # semantic retrieval.
        #
        # Strategy: exactly one guidance file per product feeds the vault
        # (root ``human_guidance.md`` is indexed as ``product="vpromedia"``;
        # per-product files as their own slug), so purging by product tag is
        # sound and also catches legacy entries that lack ``source_path``.
        _source_path_str = str(file_path.resolve())
        if product:
            try:
                existing = self.collection.get(where={"product": product})
                existing_ids = (existing or {}).get("ids") or []
                if existing_ids:
                    self.collection.delete(ids=existing_ids)
                    logger.info(
                        "HumanGuidanceVault: purged %d stale entr%s tagged product=%s before re-index of %s",
                        len(existing_ids),
                        "y" if len(existing_ids) == 1 else "ies",
                        product,
                        file_path.name,
                    )
            except Exception as purge_err:
                logger.debug(
                    "HumanGuidanceVault: pre-index purge for %s skipped (%s)",
                    file_path.name,
                    purge_err,
                )

        for idx, section in enumerate(sections[1:]):
            lines = section.strip().split("\n")
            if not lines:
                continue
            title = lines[0].strip()

            keywords = []
            jira = ""
            body_lines = []
            in_body = False

            for line in lines[1:]:
                stripped = line.strip()
                if not in_body:
                    if stripped.startswith("KEYWORDS:"):
                        keywords = [k.strip() for k in stripped.removeprefix("KEYWORDS:").split(",") if k.strip()]
                    elif stripped.startswith("JIRA:"):
                        jira = stripped.removeprefix("JIRA:").strip()
                    elif stripped == "---":
                        in_body = True
                else:
                    body_lines.append(line)

            instructions = "\n".join(body_lines).strip()
            if not instructions:
                continue

            # Combine title, keywords and instructions for embedding
            doc_text = f"{title}\nKeywords: {', '.join(keywords)}\n{instructions}"

            documents.append(doc_text)
            # ChromaDB metadata values must be scalars, so ``product`` is stored
            # as a string (empty string = global-neutral). The vault's ``query()``
            # accepts a ``product`` filter and uses this field via a ``where`` clause.
            metadatas.append({
                "title": title,
                "keywords": json.dumps(keywords),
                "jira": jira,
                "instructions": instructions,
                "type": "human-guidance",
                "product": product or "",
                # Source path lets us purge stale entries when a workflow
                # block is removed from a guidance file. See the pre-index
                # cleanup a few lines above.
                "source_path": _source_path_str,
            })
            # ID scheme: prefix with product so different products can index
            # a workflow with the same title/index without collision. Legacy
            # un-prefixed IDs from the pre-scoped era continue to coexist —
            # they'll simply carry ``product=""`` (global-neutral) after the
            # migration pass below and match every product's ``$in`` filter.
            _prod_prefix = f"{product}_" if product else ""
            ids.append(f"{_prod_prefix}{title.lower().replace(' ', '_')}_{idx}")

        if documents:
            self.collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            try:
                mtime_file.write_text(str(mtime))
            except Exception as e:
                logger.warning(f"Failed to write guidance mtime cache: {e}")
            logger.info(f"Indexed {len(documents)} guidance workflows from {file_path}")

    def query(
        self,
        text: str,
        max_results: int = 1,
        distance_threshold: float = 0.7,
        product: str | None = None,
    ) -> List[dict]:
        """
        Retrieves the most similar human guidance workflows for a given query text.

        Args:
            text: Query text.
            max_results: Max results to return.
            distance_threshold: Cosine distance threshold (smaller means closer/more similar).
            product: If provided, restricts results to entries tagged with this
                product OR empty (global-neutral). When ``None``, the whole
                collection is queried — legacy behavior preserved for scripts
                and tests.

        Returns:
            List of dictionaries containing matched workflows.
        """
        collection_count = self.collection.count()
        if collection_count == 0:
            return []

        # Clamp n_results to the collection size — HNSW raises
        # "Cannot return the results in a contigious 2D array. Probably ef
        # or M is too small" when n_results exceeds the number of vectors,
        # especially in freshly-populated per-product collections. Requesting
        # more than we have is never useful anyway.
        effective_n = max(1, min(max_results, collection_count))

        # Product scoping via ChromaDB ``where`` clause. Passing ``""`` as
        # the sentinel for global-neutral lets us OR-match same-product and
        # global entries in one query.
        query_kwargs = {
            "query_texts": [text],
            "n_results": effective_n,
        }
        if product is not None:
            query_kwargs["where"] = {"product": {"$in": [product, ""]}}

        try:
            results = self.collection.query(**query_kwargs)
        except Exception as chroma_err:
            # Defensive fallback #1: if the where-clause query fails (e.g. old
            # collections without the ``product`` field, or HNSW ef/M too small
            # for a small collection), retry without the filter and post-filter
            # in Python.
            logger.warning(
                "HumanGuidanceVault.query: filtered query raised %s — falling back to unfiltered + Python filter",
                chroma_err,
            )
            try:
                results = self.collection.query(query_texts=[text], n_results=effective_n)
            except Exception as fallback_err:
                # Defensive fallback #2: HNSW graph is genuinely degenerate
                # (too few vectors, or the graph state is corrupt). Fall back
                # to a full ``.get()`` and compute cosine similarity in Python
                # against the query embedding. Slower, but bounded — the vault
                # is expected to be small (< 200 entries) in production.
                logger.warning(
                    "HumanGuidanceVault.query: unfiltered chroma query ALSO failed (%s) — "
                    "falling back to full .get() + Python similarity",
                    fallback_err,
                )
                try:
                    snapshot = self.collection.get(include=["metadatas", "embeddings"])
                    metas = snapshot.get("metadatas") or []
                    embs_raw = snapshot.get("embeddings")
                    # ChromaDB returns numpy arrays for embeddings; ``not embs``
                    # raises on ndarray. Normalize to plain Python lists and check
                    # length explicitly.
                    embs = list(embs_raw) if embs_raw is not None else []
                    if not metas or len(embs) == 0:
                        return []
                    query_emb_raw = self.embedding_function([text])[0]
                    query_emb = list(query_emb_raw)
                    # Cosine distance = 1 - cos_sim (Chroma convention)
                    import math

                    def _cos_dist(a, b):
                        a_list = list(a)
                        b_list = list(b)
                        dot = sum(x * y for x, y in zip(a_list, b_list))
                        na = math.sqrt(sum(x * x for x in a_list)) or 1.0
                        nb = math.sqrt(sum(x * x for x in b_list)) or 1.0
                        return 1.0 - dot / (na * nb)

                    scored = [(_cos_dist(query_emb, e), m) for e, m in zip(embs, metas)]
                    scored.sort(key=lambda t: t[0])
                    top = scored[: effective_n]
                    # Reshape into Chroma's expected structure so the downstream
                    # metadatas/distances unpacking works unchanged.
                    results = {
                        "metadatas": [[m for _d, m in top]],
                        "distances": [[d for d, _m in top]],
                    }
                except Exception as final_err:
                    logger.warning(
                        "HumanGuidanceVault.query: full-collection Python fallback failed (%s) — "
                        "returning empty",
                        final_err,
                    )
                    return []

        matched_workflows = []
        if results and "metadatas" in results and results["metadatas"]:
            metadatas = results["metadatas"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(metadatas)

            for meta, dist in zip(metadatas, distances):
                if dist > distance_threshold:
                    continue
                entry_product = meta.get("product") or ""
                # Python-side product filter — belt-and-suspenders for the
                # rare fallback path above and for legacy entries missing
                # the ``product`` metadata field.
                if product is not None and entry_product and entry_product != product:
                    continue
                matched_workflows.append({
                    "title": meta.get("title"),
                    "instructions": meta.get("instructions"),
                    "keywords": json.loads(meta.get("keywords", "[]")),
                    "jira": meta.get("jira"),
                    "distance": dist,
                    "product": entry_product or None,
                })

        return matched_workflows

# Singleton instances
test_plan_vault = TestPlanVault()
human_guidance_vault = HumanGuidanceVault()
