"""
vQA — Playwright Test RAG
===========================
Module: backend/kb/playwright_rag.py

Retrieval-Augmented Generation system that indexes Playwright test code
from vsuitePlatform and retrieves relevant code snippets for the planner.

Instead of lossy markdown summaries, this module:
  1. Reads raw .test.ts and utility .ts files from the Playwright directory
  2. Chunks them into logical action blocks (groups of await page.* calls)
  3. Indexes chunks with TF-IDF for fast keyword matching
  4. Returns the most relevant code snippets when queried with an AC step

The planner injects these code snippets into its system prompt so the LLM
can see VERIFIED working selectors and interaction patterns.

Architecture
------------
  vsuitePlatform/playwright/tests/*.test.ts
      │
      ▼
  PlaywrightRAG._chunk_file()
      │  Split into action blocks on blank lines / comments
      ▼
  PlaywrightRAG._build_index()
      │  TF-IDF over: filename + comments + string literals + code
      ▼
  PlaywrightRAG.query(ac_step_text)
      │  Cosine similarity → top-K chunks
      ▼
  Formatted code snippets for planner prompt

Usage
-----
    from backend.kb.playwright_rag import playwright_rag

    snippets = playwright_rag.query("create Quick Order Radio Commercial")
    if snippets:
        system_prompt += snippets

Configuration
-------------
    Set PLAYWRIGHT_TESTS_DIR in .env (default: ../vsuitePlatform/playwright)
    If the directory doesn't exist, the RAG gracefully initializes empty.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# Default: local playwright/ directory within the vQA repo
_DEFAULT_PW_DIR = Path(__file__).parent.parent.parent / "playwright"


@dataclass
class CodeChunk:
    """A logical block of Playwright code from a test file."""

    source_file: str  # e.g. "qo_form_basic.test.ts"
    line_start: int  # 1-indexed
    line_end: int
    code: str  # The raw TypeScript code
    comments: str  # Associated comments / docstrings
    keywords: list[str] = field(default_factory=list)  # Extracted string literals


class PlaywrightRAG:
    """
    TF-IDF+BM25 hybrid RAG over Playwright test code from the local playwright/ directory.

    Chunks test files into action blocks and indexes them for
    retrieval by the planner.
    """

    # Expand vSuite abbreviations and action phrases to helper-file vocabulary so
    # queries like "QO" or "navigate to quick order" score against QO_helpers.ts.
    _CODE_SYNONYM_MAP: dict[str, str] = {
        "qo": "QO_helpers quick order new request form",
        "quick order": "QO_helpers new request form create order",
        "nav": "NavHelper navigation menu sidebar",
        "navigate": "NavHelper navigation menu",
        "search": "SearchHelper filter lookup",
        "view": "ViewHelper list compact paradigm",
        "firm": "FirmOptionsHelper client advertiser",
        "order": "OrderHelper production order spot",
        "voice": "voice talent dubber assign combobox",
        "login": "login sign in credentials storage",
        "script polish": "QO_helpers script polish checkbox",
        "radio commercial": "QO_helpers radio commercial adtype",
    }

    def __init__(self):
        self._chunks: list[CodeChunk] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._tfidf_matrix = None
        self._bm25: BM25Okapi | None = None
        self._bm25_corpus: list[list[str]] = []
        self._file_mtimes: dict[str, float] = {}

        pw_dir = Path(os.getenv("PLAYWRIGHT_TESTS_DIR", str(_DEFAULT_PW_DIR)))
        if pw_dir.exists():
            self._load_directory(pw_dir)
            self._build_index()
        else:
            logger.warning(
                "Playwright RAG: directory not found: %s — "
                "set PLAYWRIGHT_TESTS_DIR in .env or ensure vsuitePlatform is checked out",
                pw_dir,
            )

    # ── Loading ────────────────────────────────────────────────────────────

    def _load_directory(self, pw_dir: Path) -> None:
        """Load and chunk all .ts files and knowledge docs from the Playwright directory."""
        # Load test files
        test_files = sorted(pw_dir.glob("tests/*.test.ts")) + sorted(pw_dir.glob("tests/*.spec.ts"))
        # Load utility files (helpers, setup, support)
        util_files = sorted(pw_dir.glob("utils/*.ts")) + sorted(pw_dir.glob("tests/support/*.ts"))

        # Skip declaration files and reporters (no actionable code)
        skip_patterns = {".d.ts", "Reporter.ts", "types.ts"}

        all_files = test_files + util_files
        loaded = 0

        for ts_file in all_files:
            if any(ts_file.name.endswith(pat) or pat in ts_file.name for pat in skip_patterns):
                logger.debug("Playwright RAG: skipping %s (declaration/reporter)", ts_file.name)
                continue

            try:
                content = ts_file.read_text(encoding="utf-8", errors="replace")
                # Skip very small files (< 50 chars = probably empty stubs)
                if len(content) < 50:
                    continue

                self._file_mtimes[str(ts_file)] = ts_file.stat().st_mtime
                chunks = self._chunk_file(content, ts_file.name)
                self._chunks.extend(chunks)
                loaded += 1
            except OSError as e:
                logger.warning("Playwright RAG: failed to read %s: %s", ts_file, e)

        # Load Playwright_Knowledge_Sharing.md as semantic chunks
        knowledge_doc = pw_dir / "Playwright_Knowledge_Sharing.md"
        knowledge_chunks = 0
        if knowledge_doc.exists():
            knowledge_chunks = self._load_knowledge_doc(knowledge_doc)

        logger.info(
            "Playwright RAG: loaded %d files → %d code chunks + %d knowledge chunks from %s",
            loaded,
            len(self._chunks) - knowledge_chunks,
            knowledge_chunks,
            pw_dir,
        )

    def _load_knowledge_doc(self, doc_path: Path) -> int:
        """
        Ingest Playwright_Knowledge_Sharing.md as semantic chunks.

        Splits the document on ``##`` section headers, creating one CodeChunk
        per section. This provides the planner with vSuite-specific patterns
        for file uploads (setInputFiles), QO form interactions, date
        calculations, environment handling, and debugging practices.

        Returns the number of chunks created.
        """
        try:
            content = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Playwright RAG: failed to read knowledge doc %s: %s", doc_path, e)
            return 0

        # Split on ## headers
        sections = re.split(r"^## ", content, flags=re.MULTILINE)
        loaded = 0

        for section in sections[1:]:  # skip preamble before first ##
            lines = section.strip().split("\n")
            if not lines:
                continue

            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

            # Skip very short sections
            if len(body) < 50:
                continue

            # Extract code blocks as keywords
            code_blocks = re.findall(r"```(?:typescript|javascript)?\n(.*?)```", body, re.DOTALL)
            code_keywords = []
            for block in code_blocks:
                code_keywords.extend(self._extract_keywords(block))

            # Cap body at 2000 chars to keep chunks manageable
            body_capped = body[:2000]

            chunk = CodeChunk(
                source_file="Playwright_Knowledge_Sharing.md",
                line_start=0,
                line_end=0,
                code=body_capped,
                comments=title,
                keywords=code_keywords,
            )
            self._chunks.append(chunk)
            loaded += 1

        logger.info(
            "Playwright RAG: loaded %d semantic chunks from %s",
            loaded,
            doc_path.name,
        )
        return loaded

    def _chunk_file(self, content: str, filename: str) -> list[CodeChunk]:
        """
        Split a TypeScript file into logical action blocks.

        Chunking strategy:
        - Split on blank lines and comment-only lines
        - Group consecutive await/expect/const lines together
        - Attach preceding comments to each chunk
        - Skip import lines, empty blocks, and trivial code
        """
        lines = content.split("\n")
        chunks: list[CodeChunk] = []

        current_code_lines: list[str] = []
        current_comments: list[str] = []
        chunk_start: int = 1

        def _flush():
            """Create a chunk from accumulated lines."""
            if not current_code_lines:
                return
            code = "\n".join(current_code_lines).strip()
            # Skip trivial chunks (just imports, variable declarations, closing braces)
            if len(code) < 30:
                return
            # Skip chunks that are only imports
            if all(
                ln.strip().startswith("import ") or ln.strip().startswith("const ") and "page" not in ln
                for ln in current_code_lines
                if ln.strip()
            ):
                return

            chunk = CodeChunk(
                source_file=filename,
                line_start=chunk_start,
                line_end=chunk_start + len(current_code_lines) - 1,
                code=code,
                comments="\n".join(current_comments).strip(),
                keywords=self._extract_keywords(code),
            )
            chunks.append(chunk)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip import lines
            if stripped.startswith("import ") or stripped.startswith("from "):
                continue

            # Blank line = potential chunk boundary
            if not stripped:
                if current_code_lines:
                    _flush()
                    current_code_lines = []
                    current_comments = []
                    chunk_start = i + 1
                continue

            # Full-line comment → Part of preceding context
            if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                current_comments.append(stripped.lstrip("/* ").rstrip("*/").strip())
                if not current_code_lines:
                    chunk_start = i
                continue

            # Code line → accumulate
            current_code_lines.append(line)
            if not current_code_lines or chunk_start > i:
                chunk_start = i

        # Flush remaining
        _flush()

        # If the file produced very few chunks, treat the whole file as one chunk
        # (some test files are small and cohesive)
        if len(chunks) <= 1 and len(content) > 100:
            # Extract overall comments (docstring at top)
            file_comments = []
            for line in lines[:20]:
                stripped = line.strip()
                if stripped.startswith("*") or stripped.startswith("//") or stripped.startswith("/*"):
                    file_comments.append(stripped.lstrip("/* ").rstrip("*/").strip())
                elif stripped and not stripped.startswith("import"):
                    break

            # Use the whole file (minus imports) as one chunk, capped at 3000 chars
            code_lines = [
                ln for ln in lines if not ln.strip().startswith("import ") and not ln.strip().startswith("from ")
            ]
            code = "\n".join(code_lines).strip()[:3000]

            chunks = [
                CodeChunk(
                    source_file=filename,
                    line_start=1,
                    line_end=len(lines),
                    code=code,
                    comments="\n".join(file_comments),
                    keywords=self._extract_keywords(code),
                )
            ]

        return chunks

    def _extract_keywords(self, code: str) -> list[str]:
        """Extract string literals and Playwright API names from TypeScript code."""
        keywords: list[str] = []

        # Extract string literals: 'New Request', "Radio Commercial", `Bob's Burgers`
        for match in re.finditer(r"""['"`]([^'"`]{2,60})['"`]""", code):
            val = match.group(1).strip()
            # Skip code-like strings (contains {, =, :, etc.)
            if val and not re.search(r"[{}=>;()]", val):
                keywords.append(val.lower())

        # Extract Playwright API method names
        for method in re.findall(
            r"\.(getByRole|getByText|getByLabel|getByPlaceholder|locator|click|fill|check)\(", code
        ):
            keywords.append(method.lower())

        return keywords

    # ── Indexing ──────────────────────────────────────────────────────────

    def _build_index(self) -> None:
        """Build TF-IDF index over code chunks."""
        if not self._chunks:
            logger.info("Playwright RAG: no chunks to index")
            return

        # Build corpus — combine filename, comments, keywords, and code
        # for maximum matching surface
        corpus = []
        for chunk in self._chunks:
            doc = " ".join(
                [
                    chunk.source_file.replace(".test.ts", "").replace("-", " ").replace("_", " "),
                    chunk.comments,
                    " ".join(chunk.keywords),
                    chunk.code,
                ]
            )
            corpus.append(doc)

        # token_pattern preserves underscores so QO_helpers, NavHelper, etc.
        # are indexed as single tokens rather than split at the underscore.
        self._vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            max_features=8000,
            token_pattern=r"(?u)\b[a-zA-Z_][a-zA-Z0-9_]+\b",
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(corpus)

        # BM25 index for hybrid scoring (catches lexical misses that TF-IDF weights poorly)
        self._bm25_corpus = [doc.lower().split() for doc in corpus]
        self._bm25 = BM25Okapi(self._bm25_corpus)

        logger.info(
            "Playwright RAG: hybrid index built — %d chunks, %d TF-IDF features",
            self._tfidf_matrix.shape[0],
            self._tfidf_matrix.shape[1],
        )

    # ── Query ─────────────────────────────────────────────────────────────

    def query(self, ac_step_text: str, max_results: int = 2) -> str:
        """
        Find the most relevant Playwright code snippets for an AC step.

        Args
        ----
        ac_step_text : str
            The current AC step text.
        max_results : int
            Max number of code chunks to return.

        Returns
        -------
        str
            Formatted code block for injection into the planner prompt.
            Empty string if no relevant chunks found.
        """
        if not ac_step_text or self._vectorizer is None or self._tfidf_matrix is None:
            return ""

        # Expand vSuite abbreviations before scoring so "QO" → QO_helpers vocabulary
        query_lower = ac_step_text.lower()
        expansions: list[str] = []
        for trigger, expansion in self._CODE_SYNONYM_MAP.items():
            if trigger in query_lower:
                expansions.append(expansion)
        expanded_query = ac_step_text + (" " + " ".join(expansions) if expansions else "")

        # TF-IDF scores
        query_vec = self._vectorizer.transform([expanded_query])
        tfidf_scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # BM25 scores (normalized to [0,1])
        if self._bm25 is not None:
            bm25_raw = np.array(self._bm25.get_scores(expanded_query.lower().split()), dtype=float)
            bm25_max = bm25_raw.max()
            bm25_scores = bm25_raw / bm25_max if bm25_max > 0 else bm25_raw
        else:
            bm25_scores = np.zeros_like(tfidf_scores)

        # Hybrid: 0.6 TF-IDF + 0.4 BM25 (same weights as KB loader and selector_rag)
        scores = 0.6 * tfidf_scores + 0.4 * bm25_scores

        threshold = 0.08
        top_indices = np.argsort(scores)[::-1][: max_results * 2]

        results: list[tuple[float, CodeChunk]] = []
        for idx in top_indices:
            score = scores[idx]
            if score >= threshold and len(results) < max_results:
                results.append((score, self._chunks[idx]))
                logger.debug(
                    "Playwright RAG: '%s' score=%.3f (tfidf=%.3f bm25=%.3f) → MATCH (%s:%d-%d)",
                    self._chunks[idx].source_file,
                    score,
                    tfidf_scores[idx],
                    bm25_scores[idx],
                    self._chunks[idx].source_file,
                    self._chunks[idx].line_start,
                    self._chunks[idx].line_end,
                )

        if not results:
            return ""

        # OrderHelper has one import dependency: QO_helpers.ts (DRP-002 finding).
        # When OrderHelper surfaces, co-inject the top QO_helpers chunk so the
        # planner has both the order workflow and the QO form helpers in context.
        matched_files = {chunk.source_file for _, chunk in results}
        if any("OrderHelper" in f for f in matched_files) and not any("QO_helpers" in f for f in matched_files):
            qo_hits = [(0.5, c) for c in self._chunks if "QO_helpers" in c.source_file]
            if qo_hits:
                results.append(qo_hits[0])

        # Format for prompt injection
        sections: list[str] = []
        for score, chunk in results:
            # Truncate code to avoid bloating the prompt (max 1500 chars per chunk)
            code = chunk.code[:1500]
            header = f"[{chunk.source_file}:{chunk.line_start}-{chunk.line_end}]"
            if chunk.comments:
                header += f" — {chunk.comments[:100]}"
            sections.append(f"  {header}\n```typescript\n{code}\n```")

        joined = "\n\n".join(sections)
        return (
            "\n═══════════════════════════════════════════════════════════════\n"
            "📋 PLAYWRIGHT REFERENCE — Verified working test code:\n"
            "(These are REAL selectors from production Playwright tests.\n"
            " Translate these patterns into your action JSON.)\n"
            "═══════════════════════════════════════════════════════════════\n"
            + joined
            + "\n═══════════════════════════════════════════════════════════════"
        )

    def is_stale(self) -> bool:
        """Return True if any indexed file has been modified since the index was built."""
        for path_str, recorded_mtime in self._file_mtimes.items():
            try:
                if Path(path_str).stat().st_mtime != recorded_mtime:
                    return True
            except OSError:
                return True
        return False

    def reload(self) -> None:
        """Reload from disk (useful during development or after file changes)."""
        self._chunks.clear()
        self._bm25 = None
        self._bm25_corpus = []
        self._file_mtimes = {}
        pw_dir = Path(os.getenv("PLAYWRIGHT_TESTS_DIR", str(_DEFAULT_PW_DIR)))
        if pw_dir.exists():
            self._load_directory(pw_dir)
            self._build_index()


# Module-level singleton
playwright_rag = PlaywrightRAG()
