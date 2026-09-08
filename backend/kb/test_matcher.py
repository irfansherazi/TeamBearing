"""
vQA — Ground-Truth Test Matcher
=================================
Module: backend/kb/test_matcher.py

When the agent executes a Jira ticket, this module scans the
vsuitePlatform/playwright/tests/ directory for Playwright test files
whose filenames match the ticket's key (e.g., QA-138 → qa-138_basics.test.ts).

If found, the FULL test file content is loaded and formatted for injection
into the planner's system prompt at the HIGHEST priority level — above
RAG, selector registry, and KB lookups.

A human-written, passing Playwright test is the ultimate ground truth.
The agent should follow its exact patterns, selectors, and sequences.

Matching Strategy
-----------------
    Ticket ID: QA-138  → normalize to "qa-138"
    Scan: vsuitePlatform/playwright/tests/ for filenames containing "qa-138"
    Match: qa-138_basics.test.ts ✓

    Ticket ID: QA-196  → 8 matching files (qa-196-Files.test.ts, ...)
    All matches are returned and formatted.

Usage
-----
    from backend.kb.test_matcher import test_matcher

    tests = test_matcher.get_matching_tests("QA-138")
    if tests:
        prompt_block = test_matcher.format_for_prompt(tests)
        system_prompt = prompt_block + system_prompt
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import pytest
except ImportError:  # pragma: no cover — pytest not installed in production container
    pytest = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

# Default path relative to vQA project root
_DEFAULT_PW_DIR = Path(__file__).parent.parent.parent.parent / "vsuitePlatform" / "playwright"

# Max characters per test file to inject (prevents prompt bloat)
_MAX_CHARS_PER_FILE = 4000

# Max number of test files to inject for a single ticket
_MAX_FILES_PER_TICKET = 4


@dataclass
class MatchedTest:
    """A Playwright test file that matches a Jira ticket key."""

    filename: str  # e.g. "qa-138_basics.test.ts"
    ticket_key: str  # e.g. "QA-138"
    content: str  # Full file content (capped at _MAX_CHARS_PER_FILE)
    description: str  # Extracted from docstring/comments at file top


class JiraTestMatcher:
    """
    Discovers and loads Playwright test files matching a Jira ticket key.

    __test__ = False  # Prevent pytest from trying to collect this as a test class

    At init time, indexes all test files in the Playwright tests/ directory
    by their QA-NNN prefix. When queried with a ticket ID, returns the
    matching test file contents formatted for the planner prompt.

    Attributes
    ----------
    _test_dir : Path
        Path to vsuitePlatform/playwright/tests/
    _index : dict[str, list[Path]]
        Mapping from normalized ticket prefix (e.g. "qa-138") to file paths.
    """

    def __init__(self):
        self._test_dir: Path = Path(os.getenv("PLAYWRIGHT_TESTS_DIR", str(_DEFAULT_PW_DIR))) / "tests"
        self._index: dict[str, list[Path]] = {}
        self._build_index()

    def _build_index(self) -> None:
        """
        Index all test files by their QA-NNN prefix.

        Scans for *.test.ts and *.spec.ts files in the tests/ directory.
        Extracts the QA-NNN prefix from filenames like:
            qa-138_basics.test.ts  → qa-138
            qa-196-Files.test.ts   → qa-196
            qa-58-poc_counts.test.ts → qa-58
        """
        if not self._test_dir.exists():
            logger.warning(
                "TestMatcher: tests directory not found: %s — ground-truth test matching will be unavailable",
                self._test_dir,
            )
            return

        all_tests = sorted(self._test_dir.glob("*.test.ts")) + sorted(self._test_dir.glob("*.spec.ts"))

        # Index under EVERY qa-NNN token in the filename so that compound
        # filenames like qa-58-59-poc-delegation.test.ts are found by both
        # QA-58 and QA-59 lookups. Using re.findall instead of re.match
        # to capture all tickets, not just the first prefix.
        for path in all_tests:
            keys = [k.lower() for k in re.findall(r"qa-\d+", path.name, re.IGNORECASE)]
            for key in keys:
                self._index.setdefault(key, []).append(path)

        # Log the index for debugging
        total_files = sum(len(v) for v in self._index.values())
        logger.info(
            "TestMatcher: indexed %d test files across %d tickets from %s",
            total_files,
            len(self._index),
            self._test_dir,
        )
        for key, paths in sorted(self._index.items()):
            logger.debug(
                "  %s → %s",
                key,
                [p.name for p in paths],
            )

    def get_matching_tests(self, ticket_id: str) -> list[MatchedTest]:
        """
        Find all Playwright test files matching the given Jira ticket key.

        Normalizes the ticket ID to extract the QA-NNN prefix, then looks
        up matching files from the index.

        Args
        ----
        ticket_id : str
            The Jira issue key (e.g., "QA-138", "VC2-QA-196", "qa-58").

        Returns
        -------
        list[MatchedTest]
            List of matched tests with their content loaded.
            Empty list if no matches found.
        """
        if not ticket_id:
            return []

        # Normalize: "QA-138", "qa-138", "VC2-QA-138" → "qa-138"
        match = re.search(r"(qa-\d+)", ticket_id, re.IGNORECASE)
        if not match:
            logger.debug(
                "TestMatcher: no QA-NNN pattern in ticket '%s' — skipping",
                ticket_id,
            )
            return []

        key = match.group(1).lower()
        paths = self._index.get(key, [])

        if not paths:
            logger.info(
                "TestMatcher: no matching test files for %s (key=%s)",
                ticket_id,
                key,
            )
            return []

        # Load matching files (cap at _MAX_FILES_PER_TICKET)
        results: list[MatchedTest] = []
        for path in paths[:_MAX_FILES_PER_TICKET]:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                description = self._extract_description(content)

                # Strip import lines to save tokens — the planner only needs
                # the test body (await/expect/page calls)
                content_stripped = self._strip_imports(content)

                # Cap content to prevent prompt bloat
                if len(content_stripped) > _MAX_CHARS_PER_FILE:
                    content_stripped = content_stripped[:_MAX_CHARS_PER_FILE] + "\n// ... (truncated)"

                results.append(
                    MatchedTest(
                        filename=path.name,
                        ticket_key=ticket_id,
                        content=content_stripped,
                        description=description,
                    )
                )
                logger.info(
                    "TestMatcher: loaded %s (%d chars) for ticket %s",
                    path.name,
                    len(content_stripped),
                    ticket_id,
                )
            except OSError as e:
                logger.warning(
                    "TestMatcher: failed to read %s: %s",
                    path,
                    e,
                )

        if len(paths) > _MAX_FILES_PER_TICKET:
            logger.info(
                "TestMatcher: %d files matched %s but capped at %d",
                len(paths),
                ticket_id,
                _MAX_FILES_PER_TICKET,
            )

        return results

    def format_for_prompt(self, tests: list[MatchedTest]) -> str:
        """
        Format matched test files for injection into the planner system prompt.

        This block is framed as the HIGHEST PRIORITY reference — the planner
        should follow these exact selectors, interaction patterns, and sequences.

        Args
        ----
        tests : list[MatchedTest]
            The matched test files to format.

        Returns
        -------
        str
            Formatted prompt block, or empty string if no tests.
        """
        if not tests:
            return ""

        ticket_id = tests[0].ticket_key
        file_count = len(tests)
        plural = "s" if file_count > 1 else ""

        sections: list[str] = []
        for test in tests:
            header = f"[{test.filename}]"
            if test.description:
                header += f" — {test.description[:120]}"
            sections.append(f"  {header}\n```typescript\n{test.content}\n```")

        joined = "\n\n".join(sections)

        return (
            "\n═══════════════════════════════════════════════════════════════\n"
            f"⭐ GROUND-TRUTH TEST{plural.upper()} — Human-written Playwright test{plural} "
            f"for ticket {ticket_id}\n"
            "═══════════════════════════════════════════════════════════════\n"
            f"The QA team has {file_count} PASSING Playwright test{plural} for this ticket.\n"
            "This is the DEFINITIVE reference. Use these EXACT selectors,\n"
            "interaction patterns, and sequences. Do NOT deviate from them.\n"
            "If a selector below contradicts the accessibility tree, trust\n"
            "the test code — it has been verified by humans.\n"
            "═══════════════════════════════════════════════════════════════\n"
            f"{joined}\n"
            "═══════════════════════════════════════════════════════════════\n"
        )

    @staticmethod
    def _extract_description(content: str) -> str:
        """
        Extract the top-level description from a test file's header comments.

        Looks for JSDoc-style comments (/** ... */) or // line comments
        in the first 20 lines of the file.
        """
        lines = content.split("\n")[:20]
        desc_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("/**") or stripped.startswith("*"):
                text = stripped.lstrip("/* ").rstrip("*/").strip()
                if text and not text.startswith("@"):
                    desc_lines.append(text)
            elif stripped.startswith("//"):
                text = stripped.lstrip("/ ").strip()
                if text:
                    desc_lines.append(text)
            elif stripped.startswith("import ") or stripped.startswith("const "):
                break  # Past the header
            elif stripped and not stripped.startswith("'") and not stripped.startswith('"'):
                break

        return " ".join(desc_lines)[:200] if desc_lines else ""

    @staticmethod
    def _strip_imports(content: str) -> str:
        """
        Remove import/from lines from TypeScript content to save tokens.

        The planner only needs the test body (await/expect calls), not
        the module import declarations.
        """
        lines = content.split("\n")
        stripped: list[str] = []
        for line in lines:
            s = line.strip()
            if s.startswith("import ") or s.startswith("from "):
                continue
            stripped.append(line)
        return "\n".join(stripped)

    def reload(self) -> None:
        """Reload the index from disk (useful during development)."""
        self._index.clear()
        self._build_index()


# Module-level singleton — imported by planner.py
# Singleton instance
test_matcher = JiraTestMatcher()


# =============================================================================
# Phase 3 TDD Tests — WI-012 / WI-013 / WI-014 Acceptance Criteria
# =============================================================================
# These tests are written BEFORE the implementation and will fail until
# WI-012 (deduplication), WI-013 (unified registry expansion), and
# WI-014 (retrieval accuracy) are implemented.
# =============================================================================


_KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"
_HUMAN_GUIDANCE_PATH = _KNOWLEDGE_DIR / "human_guidance.md"


# Guard: only define test functions when pytest is available.
# In production (no pytest installed), this block is skipped entirely.
if pytest is not None:
    def test_human_guidance_entry_count():
        """AC-VERIFY-5: human_guidance.md must have <= 55 entries after deduplication."""
        text = _HUMAN_GUIDANCE_PATH.read_text(encoding="utf-8")
        count = text.count("## WORKFLOW:")
        assert count <= 55, f"human_guidance.md has {count} WORKFLOW entries; expected <= 55 after deduplication (WI-012)."

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
        # Deferred import: conftest.py pre-caches numpy/sklearn before
        # test_blueprint_validation.py modifies sys.path (see conftest.py).
        from backend.kb.loader import kb

        result = kb.query_with_expansion(query)
        assert result, f"query_with_expansion({query!r}) returned empty string; expected a non-empty KB context block."
        assert expected_substring.lower() in result.lower(), (
            f"query_with_expansion({query!r}) did not contain {expected_substring!r}.\nResult preview: {result[:200]!r}"
        )

