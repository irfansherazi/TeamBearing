"""
vQA — RAG-Driven Selector & Skill Retrieval (FEAT-042)
=======================================================
Module: backend/kb/selector_rag.py

Replaces the full-dump injection of selector_registry.json (~373 entries,
~51K tokens) with a BM25 + TF-IDF dual-index retrieval layer. At planning
time only the top-K most relevant selector entries and blueprint skills are
injected, with a hard 2,000-char budget cap.

Architecture
------------
  SelectorRAG (this module)
    ├── build_index()  — offline: reads registry + blueprints, builds indices
    ├── load_index()   — hot path: restores pickled indices from disk
    ├── _is_stale()    — compares registry mtime vs .last_built
    ├── query(ac_step) — returns budget-capped selector+skill block
    └── _apply_budget_cap(results, max_chars) — trims by score

Pattern reuse from loader.py LocalKnowledgeBase:
  - Same BM25Okapi + TfidfVectorizer hybrid
  - Same 0.6·tfidf + 0.4·bm25_normalized combined score
  - Same synonym expansion via _SYNONYM_MAP

Env config (12-Factor):
  ENABLE_SELECTOR_RAG      — "true"|"false"  (default: "true")
  SELECTOR_RAG_MAX_CHARS   — int             (default: 2000)
  SELECTOR_RAG_MAX_SELECTORS — int           (default: 20)
  SELECTOR_RAG_MAX_SKILLS  — int             (default: 5)
  SELECTOR_RAG_DIR         — path override   (default: memory/selector_rag/)

Usage
-----
    from backend.kb.selector_rag import selector_rag

    block = selector_rag.query("Sort production orders by CLIENT ascending")
    # Returns ≤2000-char formatted string for prompt injection
"""

import json
import logging
import os
import pickle
import re
import threading
import time
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ── Default paths (overridable via env vars / constructor args) ────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_REGISTRY_PATH = _PROJECT_ROOT / "knowledge" / "selector_registry.json"
_DEFAULT_BLUEPRINTS_DIR = _PROJECT_ROOT / "knowledge" / "blueprints"
_DEFAULT_INDEX_DIR = Path(os.getenv("SELECTOR_RAG_DIR", str(_PROJECT_ROOT / "memory" / "selector_rag")))
# Base dir under which product-scoped selector_registry.json files live at
# knowledge/<product>/selector_registry.json (hierarchical page/global schema).
_DEFAULT_KNOWLEDGE_ROOT = _PROJECT_ROOT / "knowledge"
# Top-level keys inside a product-scoped registry that are DOCUMENTATION,
# not selector-bearing subtrees. Skipped by the walker.
_PRODUCT_REGISTRY_META_KEYS = frozenset({
    "registryVersion", "generated", "site", "conventions",
})
# Per-product entry cap to prevent index bloat from a huge inventory file.
_MAX_PRODUCT_SELECTOR_ENTRIES = int(os.getenv("SELECTOR_RAG_MAX_PRODUCT_ENTRIES", "500"))

# ── Env-config constants ───────────────────────────────────────────────────────
_ENABLE_RAG = os.getenv("ENABLE_SELECTOR_RAG", "true").lower() != "false"
_MAX_CHARS = int(os.getenv("SELECTOR_RAG_MAX_CHARS", "2000"))
_MAX_SELECTORS = int(os.getenv("SELECTOR_RAG_MAX_SELECTORS", "20"))
_MAX_SKILLS = int(os.getenv("SELECTOR_RAG_MAX_SKILLS", "5"))

# ── Semantic locator scoring boost (Decision 7 in creative doc) ───────────────
_SEMANTIC_METHODS = {"get_by_role", "get_by_label", "get_by_text"}
_SEMANTIC_SCORE_BONUS = 0.1
# Product-scoped registries are extracted directly from product source and
# annotated with reachability. Boost them so they outrank stale global-registry
# entries that may still document deprecated flows or previously-failed vQA
# strategies (e.g., "Ghost login as a Sales Person" using get_by_text with the
# wrong placeholder). Applied in query() after the semantic boost. Overridable
# via env var so operators can tune retrieval preference at deploy time.
_PRODUCT_SCOPED_SCORE_BONUS = float(os.getenv("SELECTOR_RAG_PRODUCT_BOOST", "0.30"))

# ── Synonym map (reused from loader.py _SYNONYM_MAP) ─────────────────────────
_SYNONYM_MAP: dict[str, str] = {
    "ascending": "sort ascending a-z column header table",
    "descending": "sort descending z-a column header table",
    "a-z": "sort ascending alphabetical column",
    "z-a": "sort descending alphabetical column",
    "compact": "compact view table density settings menu sort-btn Sort By button",
    "standard": "standard view list view layout settings",
    "sort": "sort column header table ascending descending Sort By dropdown",
    "column": "column header table sort list view",
    "due date": "due date calendar datepicker p-select dropdown",
    "start date": "start date compound column dropdown p-select",
    "end date": "end date compound column dropdown p-select",
    "upload": "upload attach file drag drop input",
    "approve": "approve approval batch bulk action bar",
    "voice": "voice talent dubber assign voicer combobox",
    "talent": "voice talent dubber assign combobox",
    "login": "login sign in credentials email password",
    "checkbox": "checkbox p-checkbox click toggle visible",
    "dropdown": "dropdown p-select p-autocomplete select option",
    "toast": "toast notification success error message",
    "sort table": "ascending descending column sort-btn Sort-By p-select",
    "qo": "quick order radio commercial create new request",
    "campaign": "campaign client advertiser brand account",
    "script": "script copy commercial spot text body",
    "quick order": "quick order form new request radio commercial submit",
    "filter": "filter search refine results narrow p-select",
    "search": "filter search find lookup p-select autocomplete",
    "table": "grid table rows columns cell po-table-wrapper",
    "modal": "dialog popup overlay p-dialog p-confirmdialog",
    "button": "button click action btn p-button",
    "click": "click press action select",
    "fill": "fill type enter input set value",
    "select": "select click pick choose option p-select p-dropdown",
}


def _expand_query(text: str) -> str:
    """Apply synonym expansion to an AC step query (same as loader.py pattern)."""
    text_lower = text.lower()
    expansion_parts: list[str] = []
    for trigger, expansion in _SYNONYM_MAP.items():
        if trigger in text_lower:
            expansion_parts.append(expansion)
    if not expansion_parts:
        return text
    expansion_str = " ".join(expansion_parts)
    word_count = len(text.split())
    # Optimize for short AC steps (TD-022)
    if word_count < 5:
        return f"{text} {expansion_str} {expansion_str} {expansion_str}"
    if word_count < 10:
        return f"{text} {expansion_str} {expansion_str}"
    return f"{text} {expansion_str}"


def _make_selector_corpus_text(key: str, entry: dict) -> str:
    """Build the TF-IDF/BM25 corpus document string for a selector entry."""
    description = entry.get("description", "")
    context = entry.get("context", "")
    strategies = entry.get("strategies", [])
    strategy_parts = []
    for s in strategies:
        method = s.get("method", "")
        name = s.get("name", "")
        role = s.get("role", "")
        selector = s.get("selector", "")
        strategy_parts.append(f"{method} {name} {role} {selector}".strip())
    strategy_text = " ".join(strategy_parts)
    return f"{key} {description} {context} {strategy_text}".strip()


def _make_blueprint_corpus_text(stem: str, yaml_text: str) -> str:
    """Build the TF-IDF/BM25 corpus document string for a blueprint YAML."""
    # Use filename slug + first 3 step description lines
    lines = [line.strip() for line in yaml_text.splitlines() if line.strip()]
    desc_lines = [
        line.lstrip("- ").strip()
        for line in lines
        if line.lstrip("- ").startswith("description:") or (line.startswith("- ") and len(line) > 4)
    ][:3]
    return f"{stem} {' '.join(desc_lines)}".strip()


def _looks_like_selector(value: str) -> bool:
    """
    Heuristic — treat as selector when the string starts with a CSS anchor
    (#, ., [) or an XPath (//). Reject empty strings and free-prose values.
    """
    if not isinstance(value, str) or not value:
        return False
    trimmed = value.strip()
    if not trimmed:
        return False
    if trimmed.startswith(("#", ".", "[", "//")):
        return True
    # Compound CSS with a tag anchor at head (e.g., "body > div.select2-drop-active")
    if " " in trimmed and any(c in trimmed for c in ("#", ".", ">", "[")):
        return True
    return False


def _walk_product_selectors(
    product_slug: str,
    tree: dict,
    path: tuple[str, ...] = (),
) -> list[dict]:
    """
    Walk a hierarchical product-scoped selector registry and produce flat
    RAG-ready entries in the same shape the global-registry loader emits.

    Emits one entry per string leaf that looks like a selector. For dict
    leaves the walker recurses and pulls adjacent metadata (title, note,
    description) as CONTEXT for sibling selector entries — that's how the
    RAG picks up phrases like "Ghost In As impersonation picker" for the
    #s2id_ghost_id entry.
    """
    entries: list[dict] = []

    # Collect sibling metadata once at this level to enrich each entry
    # produced from the same dict.
    sibling_context_parts: list[str] = []
    for meta_key in ("title", "note", "description", "purpose"):
        val = tree.get(meta_key)
        if isinstance(val, str) and val.strip():
            sibling_context_parts.append(val.strip())
    sibling_context = " | ".join(sibling_context_parts)

    for key, value in tree.items():
        if key in ("title", "note", "description", "purpose"):
            continue
        cur_path = path + (key,)
        if isinstance(value, str):
            if _looks_like_selector(value):
                entries.append(_build_walked_entry(
                    product_slug, cur_path, value, sibling_context,
                ))
        elif isinstance(value, dict):
            entries.extend(_walk_product_selectors(product_slug, value, cur_path))
        # Lists (station name arrays, category arrays, status-id maps) are
        # domain data, not selectors — skip them.

    return entries


def _build_walked_entry(
    product_slug: str,
    path: tuple[str, ...],
    selector_value: str,
    sibling_context: str,
) -> dict:
    """Assemble an entry in the same shape the global registry loader emits."""
    key = f"{product_slug}::" + ".".join(path)
    # Humanize the path for retrieval and human display.
    # 'pages.home.newPrfButton' → 'pages > home > new prf button'
    human_segs: list[str] = []
    for seg in path:
        # camelCase → space-separated lowercase: newPrfButton → new prf button
        space_split = re.sub(r"(?<!^)([A-Z])", r" \1", seg).lower()
        human_segs.append(space_split)
    display = " > ".join(human_segs)
    # description doubles as prompt-facing label; keep it terse
    description = f"{product_slug}: {display}"

    method = "xpath" if selector_value.strip().startswith("//") else "css"

    # Boost retrieval by mixing in AC-language aliases the raw JSON key does
    # not contain. Example: raw path 'ghostUserSelect' becomes searchable via
    # "ghost login", "impersonate", "select person" — the phrasing AC steps
    # actually use. Alias mapping is heuristic, applied when the path/selector
    # matches a known domain token.
    alias_text = _synthesize_aliases(display, sibling_context, selector_value)

    entry = {
        "description": description,
        "context": (sibling_context + " " + alias_text).strip() if alias_text else sibling_context,
        "strategies": [
            {"method": method, "selector": selector_value.strip()}
        ],
        "product": product_slug,
        "source": "product_scoped_registry",
    }
    corpus_text = _make_selector_corpus_text(key, entry)
    return {"key": key, "entry": entry, "corpus_text": corpus_text}


# Static alias table — keyed by tokens present in a walked entry's path or
# selector value, values are AC-language phrases that boost TF-IDF retrieval
# for natural queries.
_WALKER_DOMAIN_ALIASES: dict[str, str] = {
    "ghost":         "ghost login impersonate impersonation select person switch user act as",
    "prf":           "promotion request form PRF drawer new promotion",
    "new_prf":       "new PRF create PRF start PRF add PRF",
    "cal":           "calendar fullcalendar promo calendar month week day",
    "sponsor":       "sponsorship sponsor add sponsor",
    "liner":         "liner PSA on-air liner liner category",
    "prize":         "prize prize closet prize package winner",
    "proposal":      "proposal idea request salesperson",
    "approval":      "approve approval pending PRF status",
    "revise":        "revise revision edit approved PRF",
    "upload":        "upload attach file dropzone add file",
    "cancel":        "cancel dismiss discard close",
    "submit":        "submit save form complete",
    "login":         "login sign in authenticate credentials",
    "logout":        "logout sign out",
    "settings":      "settings preferences admin",
    "sort":          "sort ordering ascending descending",
    "filter":        "filter search refine narrow",
    "station":       "station stations market FM AM broadcast",
    "category":      "category categories contest campaign",
}


def _synthesize_aliases(display: str, context: str, selector_value: str) -> str:
    """Return space-joined AC-language aliases based on tokens in the entry."""
    haystack = f"{display} {context} {selector_value}".lower()
    hits: list[str] = []
    for token, alias in _WALKER_DOMAIN_ALIASES.items():
        if token in haystack:
            hits.append(alias)
    return " ".join(hits)


def _discover_product_selector_files(
    knowledge_root: Path,
    exclude_paths: set[Path] | None = None,
) -> list[tuple[str, Path]]:
    """
    Find `knowledge/<product>/selector_registry.json` files.

    Returns list of (product_slug, path). Products whose file matches a
    path in exclude_paths (used to skip the global registry) are dropped.
    """
    excluded = exclude_paths or set()
    found: list[tuple[str, Path]] = []
    if not knowledge_root.is_dir():
        return found
    for sub in sorted(knowledge_root.iterdir()):
        if not sub.is_dir():
            continue
        candidate = sub / "selector_registry.json"
        if not candidate.is_file():
            continue
        if candidate.resolve() in excluded:
            continue
        found.append((sub.name, candidate))
    return found


def _load_product_scoped_selectors(
    knowledge_root: Path,
    exclude_paths: set[Path],
    global_keys: set[str],
) -> list[dict]:
    """
    Load and flatten every product-scoped selector registry into RAG entries.

    Skips the global registry file (via exclude_paths) and de-duplicates
    against keys already produced by the global loader.
    """
    import json as _json
    all_entries: list[dict] = []
    for product_slug, path in _discover_product_selector_files(
        knowledge_root, exclude_paths=exclude_paths,
    ):
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "Selector RAG: failed to read product-scoped registry %s: %s",
                path, exc,
            )
            continue

        if not isinstance(data, dict):
            continue

        # Skip DOCUMENTATION sections (site, conventions, ...) — walk the rest.
        walkable = {
            k: v for k, v in data.items()
            if k not in _PRODUCT_REGISTRY_META_KEYS and isinstance(v, dict)
        }
        walked = _walk_product_selectors(product_slug, walkable)

        # De-dup against global keys AND against already-seen product keys.
        product_entries: list[dict] = []
        seen = set(global_keys)
        for e in walked:
            if e["key"] in seen:
                continue
            seen.add(e["key"])
            product_entries.append(e)
            if len(product_entries) >= _MAX_PRODUCT_SELECTOR_ENTRIES:
                logger.warning(
                    "Selector RAG: product '%s' hit cap of %d entries — truncating",
                    product_slug, _MAX_PRODUCT_SELECTOR_ENTRIES,
                )
                break

        logger.info(
            "Selector RAG: product-scoped registry '%s' contributed %d entries",
            product_slug, len(product_entries),
        )
        all_entries.extend(product_entries)

    return all_entries


def _has_semantic_strategy(entry: dict) -> bool:
    """Return True if entry has any strategy with a semantic Playwright method."""
    for s in entry.get("strategies", []):
        if s.get("method") in _SEMANTIC_METHODS:
            return True
    return False


class SelectorRAG:
    """
    BM25 + TF-IDF dual-index retrieval for selector registry and blueprint skills.

    Attributes
    ----------
    _registry_path : Path
        Path to knowledge/selector_registry.json.
    _blueprints_dir : Path
        Path to knowledge/blueprints/ directory.
    _index_dir : Path
        Path to memory/selector_rag/ where pkl files are written.

    State (populated by load_index() or build_index())
    ---------------------------------------------------
    _sel_vectorizer, _sel_tfidf, _sel_bm25, _sel_entries
    _bp_vectorizer, _bp_tfidf, _bp_bm25, _bp_entries
    """

    def __init__(
        self,
        registry_path: Path | None = None,
        blueprints_dir: Path | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self._registry_path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY_PATH
        self._blueprints_dir = Path(blueprints_dir) if blueprints_dir else _DEFAULT_BLUEPRINTS_DIR
        self._index_dir = Path(index_dir) if index_dir else _DEFAULT_INDEX_DIR
        self._rebuild_lock = threading.Lock()

        # Selector index state
        self._sel_vectorizer: TfidfVectorizer | None = None
        self._sel_tfidf = None
        self._sel_bm25: BM25Okapi | None = None
        self._sel_entries: list[dict] | None = None  # [{key, entry, corpus_text}]

        # Blueprint/skill index state
        self._bp_vectorizer: TfidfVectorizer | None = None
        self._bp_tfidf = None
        self._bp_bm25: BM25Okapi | None = None
        self._bp_entries: list[dict] | None = None  # [{stem, text, yaml_text}]

        self._index_dir.mkdir(parents=True, exist_ok=True)

    def _save_json_manifest(self, sel_entries: list[dict], bp_entries: list[dict]) -> None:
        """
        Save a JSON fallback manifest of raw entries.
        Ensures we can rebuild indices even if pkl fails (TD-013).
        """
        manifest = {
            "version": "1.0",
            "timestamp": time.time(),
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
            "selectors": sel_entries,
            "blueprints": bp_entries,
        }
        try:
            (self._index_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Selector RAG: failed to write JSON manifest: %s", exc)

    def _load_from_json_manifest(self) -> bool:
        """
        Try to rebuild the index from the JSON manifest fallback.
        """
        manifest_path = self._index_dir / "manifest.json"
        if not manifest_path.exists():
            return False

        try:
            logger.info("Selector RAG: attempting rebuild from JSON manifest fallback...")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sel_entries = manifest.get("selectors", [])
            bp_entries = manifest.get("blueprints", [])

            if not sel_entries and not bp_entries:
                return False

            # Build in-memory
            sel_pkl = self._build_dual_index(sel_entries)
            bp_pkl = self._build_dual_index(bp_entries)

            self._sel_vectorizer = sel_pkl.get("tfidf_vectorizer")
            self._sel_tfidf = sel_pkl.get("tfidf_matrix")
            self._sel_bm25 = sel_pkl.get("bm25")
            self._sel_entries = sel_pkl.get("entries", [])

            self._bp_vectorizer = bp_pkl.get("tfidf_vectorizer")
            self._bp_tfidf = bp_pkl.get("tfidf_matrix")
            self._bp_bm25 = bp_pkl.get("bm25")
            self._bp_entries = bp_pkl.get("entries", [])

            return True
        except Exception as exc:
            logger.warning("Selector RAG: failed to rebuild from JSON manifest: %s", exc)
            return False

    # ── Index Build ────────────────────────────────────────────────────────────

    def build_index(self) -> None:
        """
        Build TF-IDF + BM25 indices from selector_registry.json and blueprints/*.yaml.

        Serializes to:
          {index_dir}/selector_index.pkl
          {index_dir}/skill_index.pkl
          {index_dir}/.last_built   (timestamp file)

        Logs INFO on completion (AC-INDEX-1).
        """
        import json as _json

        start = time.monotonic()

        # ── Load selector entries ─────────────────────────────────────────────
        sel_entries: list[dict] = []
        if self._registry_path.exists():
            try:
                data = _json.loads(self._registry_path.read_text(encoding="utf-8"))
                raw_selectors = data.get("selectors", {})
                for key, entry in raw_selectors.items():
                    corpus_text = _make_selector_corpus_text(key, entry)
                    sel_entries.append({"key": key, "entry": entry, "corpus_text": corpus_text})
            except Exception as exc:
                logger.error("Selector RAG: failed to read registry: %s", exc)

        # ── Merge product-scoped registries at knowledge/<product>/selector_registry.json ─
        # Format there is hierarchical (site/global/pages sections), not the
        # flat {selectors: {...}} shape of the primary registry. The walker
        # flattens each string selector leaf into the same entry dict shape
        # this index consumes downstream.
        try:
            global_keys = {e["key"] for e in sel_entries}
            product_entries = _load_product_scoped_selectors(
                _DEFAULT_KNOWLEDGE_ROOT,
                exclude_paths={self._registry_path.resolve()},
                global_keys=global_keys,
            )
            sel_entries.extend(product_entries)
        except Exception as exc:
            logger.error("Selector RAG: product-scoped registry merge failed: %s", exc)

        # ── Load blueprint entries ────────────────────────────────────────────
        bp_entries: list[dict] = []
        if self._blueprints_dir.exists():
            for yaml_file in sorted(self._blueprints_dir.glob("*.yaml")):
                try:
                    yaml_text = yaml_file.read_text(encoding="utf-8")
                    corpus_text = _make_blueprint_corpus_text(yaml_file.stem, yaml_text)
                    bp_entries.append(
                        {
                            "stem": yaml_file.stem,
                            "yaml_text": yaml_text,
                            "corpus_text": corpus_text,
                        }
                    )
                except Exception as exc:
                    logger.warning("Selector RAG: failed to read blueprint %s: %s", yaml_file.name, exc)

        # ── Build selector index ──────────────────────────────────────────────
        sel_pkl = self._build_dual_index(sel_entries)

        # ── Build blueprint/skill index ───────────────────────────────────────
        bp_pkl = self._build_dual_index(bp_entries)

        elapsed = time.monotonic() - start

        # ── Serialize to disk ─────────────────────────────────────────────────
        try:
            (self._index_dir / "selector_index.pkl").write_bytes(pickle.dumps(sel_pkl, protocol=4))
            (self._index_dir / "skill_index.pkl").write_bytes(pickle.dumps(bp_pkl, protocol=4))
            (self._index_dir / ".last_built").write_text(str(time.time()), encoding="utf-8")
            # TASK-054: Save JSON manifest as a safe version-independent fallback
            self._save_json_manifest(sel_entries, bp_entries)
        except OSError as exc:
            logger.error("Selector RAG: failed to write index files: %s", exc)
            return

        # ── Populate in-memory state ──────────────────────────────────────────
        self._sel_vectorizer = sel_pkl.get("tfidf_vectorizer")
        self._sel_tfidf = sel_pkl.get("tfidf_matrix")
        self._sel_bm25 = sel_pkl.get("bm25")
        self._sel_entries = sel_pkl.get("entries", [])
        self._bp_vectorizer = bp_pkl.get("tfidf_vectorizer")
        self._bp_tfidf = bp_pkl.get("tfidf_matrix")
        self._bp_bm25 = bp_pkl.get("bm25")
        self._bp_entries = bp_pkl.get("entries", [])

        logger.info(
            "Selector RAG: index built — %d selectors, %d blueprints, %.1fs",
            len(sel_entries),
            len(bp_entries),
            elapsed,
        )

    def _build_dual_index(self, entries: list[dict]) -> dict:
        """
        Build a TF-IDF + BM25 index from a list of corpus entry dicts.

        Each entry dict must have a 'corpus_text' key.
        Returns a pkl-serializable dict with keys:
          tfidf_vectorizer, tfidf_matrix, bm25, entries
        """
        if not entries:
            return {"tfidf_vectorizer": None, "tfidf_matrix": None, "bm25": None, "entries": []}

        corpus = [e["corpus_text"] for e in entries]

        # TF-IDF (capped at 5000 features — same as loader.py)
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            max_features=5000,
        )
        tfidf_matrix = vectorizer.fit_transform(corpus)

        # BM25Okapi
        bm25_corpus = [doc.lower().split() for doc in corpus]
        bm25 = BM25Okapi(bm25_corpus)

        return {
            "tfidf_vectorizer": vectorizer,
            "tfidf_matrix": tfidf_matrix,
            "bm25": bm25,
            "entries": entries,
        }

    # ── Index Load ─────────────────────────────────────────────────────────────

    def load_index(self) -> bool:
        """
        Load pickled indices from disk into memory.

        Returns True on success, False if files are missing or corrupt.
        On False, the caller should fall back to keyword-only matching.
        """
        sel_path = self._index_dir / "selector_index.pkl"
        skill_path = self._index_dir / "skill_index.pkl"

        if not sel_path.exists() or not skill_path.exists():
            logger.debug("Selector RAG: index files not found — not yet built")
            return False

        try:
            sel_data = pickle.loads(sel_path.read_bytes())
            bp_data = pickle.loads(skill_path.read_bytes())
        except Exception as exc:
            logger.warning("Selector RAG: failed to load pickle index: %s. Trying JSON manifest...", exc)
            return self._load_from_json_manifest()

        self._sel_vectorizer = sel_data.get("tfidf_vectorizer")
        self._sel_tfidf = sel_data.get("tfidf_matrix")
        self._sel_bm25 = sel_data.get("bm25")
        self._sel_entries = sel_data.get("entries", [])

        self._bp_vectorizer = bp_data.get("tfidf_vectorizer")
        self._bp_tfidf = bp_data.get("tfidf_matrix")
        self._bp_bm25 = bp_data.get("bm25")
        self._bp_entries = bp_data.get("entries", [])

        logger.debug(
            "Selector RAG: index loaded — %d selectors, %d blueprints",
            len(self._sel_entries or []),
            len(self._bp_entries or []),
        )
        return True

    # ── Staleness Detection ────────────────────────────────────────────────────

    def _is_stale(self) -> bool:
        """
        Return True if the index needs rebuilding.

        Conditions triggering stale:
          1. .last_built does not exist (never built)
          2. selector_registry.json mtime > .last_built mtime
          3. Any blueprint YAML mtime > .last_built mtime
          4. Any knowledge/<product>/selector_registry.json mtime > .last_built mtime

        Logs INFO when stale is detected (AC-LIFECYCLE-1).
        """
        last_built_path = self._index_dir / ".last_built"

        if not last_built_path.exists():
            logger.debug("Selector RAG: .last_built absent — stale")
            return True

        index_mtime = last_built_path.stat().st_mtime

        # Check registry
        if self._registry_path.exists():
            registry_mtime = self._registry_path.stat().st_mtime
            if registry_mtime > index_mtime:
                logger.info(
                    "Selector RAG: stale — rebuilding (registry mtime: %.0f, index mtime: %.0f)",
                    registry_mtime,
                    index_mtime,
                )
                return True

        # Check blueprints
        if self._blueprints_dir.exists():
            for yaml_file in self._blueprints_dir.glob("*.yaml"):
                if yaml_file.stat().st_mtime > index_mtime:
                    logger.info(
                        "Selector RAG: stale — blueprint '%s' updated since last index build",
                        yaml_file.name,
                    )
                    return True

        # Check product-scoped registries (knowledge/<product>/selector_registry.json).
        # Reuses the same discovery helper the loader uses, so any file the walker
        # would ingest also participates in staleness detection.
        try:
            for _slug, path in _discover_product_selector_files(
                _DEFAULT_KNOWLEDGE_ROOT,
                exclude_paths={self._registry_path.resolve()},
            ):
                if path.stat().st_mtime > index_mtime:
                    logger.info(
                        "Selector RAG: stale — product-scoped registry '%s' updated",
                        path,
                    )
                    return True
        except Exception as exc:
            logger.warning(
                "Selector RAG: staleness scan on product-scoped registries failed: %s",
                exc,
            )

        return False

    def rebuild_if_stale(self) -> bool:
        """Check staleness and rebuild in the current thread if stale. Returns True if rebuilt."""
        if self._is_stale():
            with self._rebuild_lock:
                # Double-check after acquiring lock
                if self._is_stale():
                    self.build_index()
                    return True
        return False

    def rebuild_in_background(self) -> None:
        """Trigger a background rebuild without blocking the caller (AC-LIFECYCLE-1)."""

        def _rebuild():
            with self._rebuild_lock:
                if self._is_stale():
                    logger.info("Selector RAG: background rebuild starting")
                    self.build_index()

        t = threading.Thread(target=_rebuild, daemon=True, name="selector-rag-rebuild")
        t.start()

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(
        self,
        ac_step: str,
        domain_context: str = "",
        max_selectors: int | None = None,
        max_skills: int | None = None,
        max_chars: int | None = None,
    ) -> str:
        """
        Retrieve budget-capped selector + skill context for an AC step.

        Returns a formatted string ready for planner system prompt injection.
        Returns empty string if RAG is disabled or no matches found.

        Args
        ----
        ac_step : str
            The current AC step text.
        domain_context : str
            Optional domain XML context (max 100 chars appended to query).
        max_selectors : int
            Max selector entries to retrieve (default: SELECTOR_RAG_MAX_SELECTORS).
        max_skills : int
            Max blueprint skills to retrieve (default: SELECTOR_RAG_MAX_SKILLS).
        max_chars : int
            Hard char cap on combined block (default: SELECTOR_RAG_MAX_CHARS).
        """
        if not _ENABLE_RAG or not ac_step:
            return ""

        _max_sel = max_selectors if max_selectors is not None else _MAX_SELECTORS
        _max_sk = max_skills if max_skills is not None else _MAX_SKILLS
        _max_ch = max_chars if max_chars is not None else _MAX_CHARS

        t_start = time.monotonic()

        # Ensure index is loaded
        if self._sel_vectorizer is None:
            loaded = self.load_index()
            if not loaded:
                # Check if we can build
                if self._registry_path.exists():
                    self.build_index()
                else:
                    return ""

        # Build expanded query
        query_text = _expand_query(ac_step)
        if domain_context:
            query_text = f"{query_text} {domain_context[:100]}"

        # Retrieve selectors
        sel_results = self._retrieve(
            query_text,
            self._sel_vectorizer,
            self._sel_tfidf,
            self._sel_bm25,
            self._sel_entries or [],
            top_k=_max_sel,
        )

        # Apply semantic locator score boost (Decision 7)
        for r in sel_results:
            if _has_semantic_strategy(r.get("entry", {})):
                r["score"] += _SEMANTIC_SCORE_BONUS

        # Boost product-scoped-registry entries (extracted from product source)
        # so they outrank stale global entries when relevance is comparable.
        for r in sel_results:
            if r.get("entry", {}).get("source") == "product_scoped_registry":
                r["score"] += _PRODUCT_SCOPED_SCORE_BONUS

        # Re-sort after boosts
        sel_results.sort(key=lambda x: -x["score"])
        sel_results = sel_results[:_max_sel]

        # Retrieve blueprint skills
        bp_results = self._retrieve(
            query_text,
            self._bp_vectorizer,
            self._bp_tfidf,
            self._bp_bm25,
            self._bp_entries or [],
            top_k=_max_sk,
        )

        latency_ms = (time.monotonic() - t_start) * 1000
        top_score = sel_results[0]["score"] if sel_results else 0.0
        n_results = len(sel_results)

        logger.debug(
            "RAG selector query: '%s' → top_score=%.3f, %d results, budget=%dch",
            ac_step[:40],
            top_score,
            n_results,
            _max_ch,
        )

        # Format blocks
        sel_block = self._format_selector_block(sel_results)
        bp_block = self._format_blueprint_block(bp_results)

        # Apply hard budget cap
        combined = self._apply_budget_cap(
            sel_block=sel_block,
            bp_block=bp_block,
            sel_results=sel_results,
            max_chars=_max_ch,
        )

        chars_injected = len(combined)
        len(sel_results)
        logger.debug(
            "RAG budget: selectors=%d chars, skills=%d chars, total=%d chars, latency=%.1fms",
            len(sel_block),
            len(bp_block),
            chars_injected,
            latency_ms,
        )

        return combined

    # ── Retrieval ──────────────────────────────────────────────────────────────

    def _retrieve(
        self,
        query_text: str,
        vectorizer: TfidfVectorizer | None,
        tfidf_matrix,
        bm25: BM25Okapi | None,
        entries: list[dict],
        top_k: int,
    ) -> list[dict]:
        """
        Core hybrid BM25 + TF-IDF retrieval. Returns top_k scored entries.

        Returns list of dicts: {entry_dict_key: ..., 'score': float}
        """
        if not entries or vectorizer is None or tfidf_matrix is None:
            return []

        try:
            query_vec = vectorizer.transform([query_text])
            tfidf_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()

            _RERANK_POOL = min(top_k * 2, len(entries))
            top_indices = np.argsort(tfidf_scores)[::-1][:_RERANK_POOL]

            if bm25 is not None:
                query_tokens = query_text.lower().split()
                bm25_scores = bm25.get_scores(query_tokens)
                bm25_max = bm25_scores.max() if bm25_scores.max() > 0 else 1.0
                bm25_norm = bm25_scores / bm25_max

                combined: list[tuple[float, int]] = []
                for idx in top_indices:
                    score = 0.6 * tfidf_scores[idx] + 0.4 * bm25_norm[idx]
                    combined.append((score, int(idx)))
                combined.sort(key=lambda x: -x[0])
            else:
                combined = [(float(tfidf_scores[idx]), int(idx)) for idx in top_indices]

            results: list[dict] = []
            for score, idx in combined[:top_k]:
                if score <= 0:
                    continue
                e = entries[idx].copy()
                e["score"] = score
                results.append(e)

            return results

        except Exception as exc:
            logger.warning("Selector RAG: retrieval error: %s", exc)
            return []

    # ── Formatting ────────────────────────────────────────────────────────────

    def _format_selector_block(self, results: list[dict]) -> str:
        """Format retrieved selector entries as a prompt-ready block."""
        if not results:
            return ""

        lines = [
            "\n═══════════════════════════════════════════════════════════════",
            "🎯 SELECTOR REGISTRY — RAG-Retrieved Ground-Truth Locators:",
            "═══════════════════════════════════════════════════════════════",
        ]
        for r in results:
            entry = r.get("entry", {})
            key = r.get("key", "")
            lines.append(f"\n  [{entry.get('description', key)}]")
            for s in entry.get("strategies", [])[:2]:
                method = s.get("method", "")
                if method == "get_by_role":
                    lines.append(
                        f'  → strategy: "get_by_role", role: "{s.get("role", "")}", name: "{s.get("name", "")}"'
                    )
                elif method == "get_by_text":
                    lines.append(f'  → strategy: "get_by_text", name: "{s.get("name", "")}"')
                elif method == "get_by_label":
                    lines.append(f'  → strategy: "get_by_label", name: "{s.get("name", "")}"')
                elif method == "css":
                    lines.append(f'  → strategy: "css_selector", selector: "{s.get("selector", "")}"')
                elif method == "xpath":
                    lines.append(f'  → strategy: "xpath", selector: "{s.get("selector", "")}"')
                elif method == "get_by_placeholder":
                    lines.append(f'  → strategy: "get_by_placeholder", name: "{s.get("name", "")}"')
            if entry.get("context"):
                lines.append(f"  ℹ Context: {entry['context']}")
            if entry.get("source") == "product_scoped_registry":
                lines.append(
                    f"  ✓ Source: product-scoped registry ({entry.get('product', '')})"
                    " — verified against product code"
                )
        lines.append("═══════════════════════════════════════════════════════════════")
        return "\n".join(lines)

    def _format_blueprint_block(self, results: list[dict]) -> str:
        """Format retrieved blueprint YAML entries as a prompt-ready block."""
        if not results:
            return ""

        lines = [
            "\n═══════════════════════════════════════════════════════════════",
            "📋 SKILL BLUEPRINTS — RAG-Retrieved Workflow Patterns:",
            "═══════════════════════════════════════════════════════════════",
        ]
        for r in results:
            stem = r.get("stem", "?")
            yaml_text = r.get("yaml_text", "")
            lines.append(f"\n  [Blueprint: {stem}]")

            # Per-step chunking (TD-035): Extract and summarize steps list for large blueprints
            if len(yaml_text) > 600:
                # Find the 'steps:' section and the 'name:'/ 'description:'
                summary_parts = []
                desc_match = re.search(r'description:\s*>?\s*(.*?)(?=\n\S|$)', yaml_text, re.DOTALL)
                if desc_match:
                    desc = desc_match.group(1).strip()[:150]
                    summary_parts.append(f"  Description: {desc}...")

                steps_match = re.search(r'steps:\s*(.*)', yaml_text, re.DOTALL)
                if steps_match:
                    steps_text = steps_match.group(1).strip()
                    # Extract just the action types from the steps list
                    actions = re.findall(r'action:\s*(\w+)', steps_text)
                    if actions:
                        summary_parts.append(f"  Steps: {' -> '.join(actions)}")
                    else:
                        summary_parts.append(f"  Steps Raw: {steps_text[:200]}...")

                if summary_parts:
                    lines.extend(summary_parts)
                else:
                    lines.append(f"  {yaml_text[:400].strip()}...")
            else:
                lines.append(f"  {yaml_text.strip()}")

        lines.append("═══════════════════════════════════════════════════════════════")
        return "\n".join(lines)

    # ── Budget Cap ─────────────────────────────────────────────────────────────

    def _apply_budget_cap(
        self,
        sel_block: str,
        bp_block: str,
        sel_results: list[dict],
        max_chars: int = _MAX_CHARS,
    ) -> str:
        """
        Enforce the hard character cap on the combined injection block (AC-BUDGET-1).

        Trims lowest-scored selector entries until the combined block fits.
        Blueprint block is preserved if possible; trimmed last.
        """
        combined = sel_block + bp_block
        if len(combined) <= max_chars:
            return combined

        # Trim selectors from the bottom (lowest score) until we fit
        trimmed_results = list(sel_results)
        while len(combined) > max_chars and len(trimmed_results) > 0:
            trimmed_results.pop()  # remove lowest-score entry (already sorted desc)
            new_sel_block = self._format_selector_block(trimmed_results)
            combined = new_sel_block + bp_block

        # If still over cap, hard-truncate (reserve space for suffix so total ≤ max_chars)
        if len(combined) > max_chars:
            _SUFFIX = "\n... [RAG block truncated at budget cap]"
            combined = combined[: max_chars - len(_SUFFIX)] + _SUFFIX

        trimmed_count = len(sel_results) - len(trimmed_results)
        if trimmed_count > 0:
            logger.debug(
                "RAG budget cap: trimmed %d entries to fit %d char limit",
                trimmed_count,
                max_chars,
            )

        return combined


# ── Module-level singleton ────────────────────────────────────────────────────
# Loaded lazily — build_index() / load_index() called on first query().
selector_rag = SelectorRAG()
