"""
backend/storage/playwright_registry.py
=======================================
Manages the canonical Playwright test index.

The index file (playwright/playwright_index.json) is the single source
of truth for all 40+ production Playwright tests.  It is pre-generated
by scripts/sync_playwright_index.py and read-only at runtime.

Each entry contains:
  id          — unique test identifier (used in API allow-list)
  file        — relative path within playwright/tests/
  jira_keys   — list of associated JIRA ticket keys
  description — human-readable test description
  steps_count — number of test.step() blocks
  step_names  — names of all test steps
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


class PlaywrightRegistry:
    """
    Manages the list of static Playwright tests from the canonical index.

    Reads from playwright/playwright_index.json (the PLAYWRIGHT_INDEX_FILE
    env var default). Does NOT scan the filesystem at runtime — the index
    is a pre-built artifact from scripts/sync_playwright_index.py.
    """

    def __init__(self, tests_dir: str, registry_file: str):
        """
        Initialise the registry.

        Args
        ----
        tests_dir : str
            Directory containing Playwright test files (informational only;
            not scanned at runtime).
        registry_file : str
            Path to the JSON index file (playwright/playwright_index.json).
        """
        self.tests_dir = Path(tests_dir)
        self.registry_file = Path(registry_file)
        self._tests: List[Dict] = []
        self._load()

    def _load(self) -> None:
        """Load the registry from the JSON index file."""
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r") as f:
                    self._tests = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._tests = []
        else:
            self._tests = []

    def list_tests(self) -> List[Dict]:
        """Return a list of all tests in the registry."""
        return self._tests

    def get_test(self, test_id: str) -> Optional[Dict]:
        """Retrieve a test by its ID (allow-list lookup)."""
        for test in self._tests:
            if test.get("id") == test_id:
                return test
        return None

    def list_tests_for_product(self, playwright_tests_dir: str) -> List[Dict]:
        """Return tests whose file path falls under the product's test directory.

        The index stores paths relative to playwright/ (e.g. 'tests/vpromedia/qa-100.test.ts').
        playwright_tests_dir is also relative to the repo root (e.g. 'playwright/tests/vpromedia').
        We derive the relative prefix by stripping the leading 'playwright/' component.
        """
        # playwright_tests_dir = "playwright/tests/vpromedia"
        # relative prefix for index matching = "tests/vpromedia/"
        prefix = playwright_tests_dir.removeprefix("playwright/").rstrip("/") + "/"
        # Normalise separators: the index may store Windows backslashes
        prefix_fwd = prefix.replace("\\", "/")
        return [
            t for t in self._tests
            if t.get("file", "").replace("\\", "/").startswith(prefix_fwd)
        ]

    def get_tests_by_jira_key(self, key: str) -> List[Dict]:
        """
        Retrieve a list of tests associated with a given Jira key.
        Case-insensitive match.
        """
        if not key:
            return []
        normalized_key = key.strip().upper()
        return [
            t for t in self._tests
            if any(normalized_key == k.strip().upper() for k in t.get("jira_keys", []))
        ]

    def get_valid_ids(self) -> set:
        """Return the set of all valid test IDs (used for allow-list validation)."""
        return {t.get("id") for t in self._tests if t.get("id")}

    def refresh(self) -> None:
        """
        Reload the registry from the JSON index file.

        The index should be updated by scripts/sync_playwright_index.py
        when new tests are added to playwright/tests/.
        """
        self._load()

    def verify_dependencies(self) -> bool:
        """
        Verify that Node.js and Playwright are available in the environment.

        Returns True if all dependencies are met, False otherwise.
        """
        try:
            subprocess.run(["node", "--version"], check=True, capture_output=True)
            subprocess.run(["npx", "--version"], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
