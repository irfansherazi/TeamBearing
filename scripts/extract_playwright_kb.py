#!/usr/bin/env python3
"""
vQA — Playwright KB Extractor
================================
Script: scripts/extract_playwright_kb.py

One-time extraction script that parses the vsuitePlatform Playwright test
branch and generates vQA knowledge assets:
  - knowledge/selector_registry.json  (locators from utility helpers)
  - knowledge/workflow_*.md           (workflows from test spec files)
  - knowledge/angular_timing_contracts.md (timing patterns)

This script is designed to be run MANUALLY when significant new Playwright
tests are added. It is NOT called at agent runtime.

Usage
-----
    # Preferred: use git worktree to avoid disturbing your working branch
    git worktree add /tmp/pw-branch remotes/origin/Doc/qa-playwright-test-creation

    # Run the extractor
    python scripts/extract_playwright_kb.py \\
        --playwright-root /tmp/pw-branch \\
        --output-dir knowledge

    # Review generated files, then commit
    git add knowledge/ && git commit -m "chore: regenerate KB from Playwright branch"

    # Clean up worktree
    git worktree remove /tmp/pw-branch

Makefile target (make kb-refresh) runs the above steps automatically.

What It Parses
--------------
1. playwright/utils/*.ts (helper files):
   - Extracts locator strategy objects and method calls
   - Maps to selector_registry.json entries

2. playwright/tests/qa-*.test.ts (spec files):
   - Extracts test.describe names → workflow names
   - Extracts test.step() calls → ordered workflow steps
   - Extracts expect() assertions → verification steps
   - Outputs knowledge/workflow_{sanitized_name}.md

3. Timing patterns (waitForTimeout, waitForSelector, etc.) in helpers →
   appended to angular_timing_contracts.md (deduped, does NOT overwrite hand-written content)

Compatibility
-------------
Python 3.10+. No additional dependencies — stdlib only.
"""

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class SelectorEntry:
    """A single entry in the selector registry."""

    key: str
    description: str
    strategies: list[dict] = field(default_factory=list)
    context: Optional[str] = None
    timing_note: Optional[str] = None


@dataclass
class WorkflowStep:
    """A single step in a workflow extracted from a test spec."""

    text: str
    is_assertion: bool = False


@dataclass
class Workflow:
    """A complete workflow extracted from a test spec file."""

    name: str
    source_file: str
    steps: list[WorkflowStep] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Playwright TypeScript Parsers
# ---------------------------------------------------------------------------


def parse_helper_locators(ts_content: str, source_file: str) -> list[SelectorEntry]:
    """
    Extract Playwright locator patterns from a TypeScript helper file.

    Looks for patterns like:
      page.getByRole('button', { name: 'Submit All' })
      page.getByText('New Request +')
      page.getByLabel('Client or Advertiser')
      page.locator('button.p-datepicker-dropdown')
      page.getByPlaceholder('Search')
    """
    entries: list[SelectorEntry] = []

    # Patterns → (method, role, name, selector) extraction
    patterns = [
        # getByRole('link', { name: 'New Request +' })
        (re.compile(r"getByRole\(['\"](\w+)['\"],\s*\{\s*name:\s*['\"]([^'\"]+)['\"]"), "get_by_role"),
        # getByText('Submit All') — simple form
        (re.compile(r"getByText\(['\"]([^'\"]+)['\"]"), "get_by_text"),
        # getByLabel('Client or Advertiser')
        (re.compile(r"getByLabel\(['\"]([^'\"]+)['\"]"), "get_by_label"),
        # getByPlaceholder('Search')
        (re.compile(r"getByPlaceholder\(['\"]([^'\"]+)['\"]"), "get_by_placeholder"),
        # locator('button.p-datepicker-dropdown') or locator('.some-css')
        (re.compile(r"\.locator\(['\"]([^'\"]+)['\"]"), "css"),
    ]

    seen: set[str] = set()

    for line in ts_content.split("\n"):
        for pattern, method in patterns:
            m = pattern.search(line)
            if not m:
                continue

            # Build a key and entry from the match
            if method == "get_by_role":
                role, name = m.group(1), m.group(2)
                key = _make_key(f"{role}_{name}")
                if key in seen:
                    continue
                seen.add(key)
                entry = SelectorEntry(
                    key=key,
                    description=f"{role.capitalize()} '{name}'",
                    strategies=[{"method": method, "role": role, "name": name}],
                    context=f"Extracted from {Path(source_file).name}",
                )

            elif method in ("get_by_text", "get_by_label", "get_by_placeholder"):
                name = m.group(1)
                if len(name) < 2 or len(name) > 80:
                    continue
                key = _make_key(f"{method}_{name}")
                if key in seen:
                    continue
                seen.add(key)
                entry = SelectorEntry(
                    key=key,
                    description=f"'{name}' ({method.replace('get_by_', '').replace('_', ' ')} locator)",
                    strategies=[{"method": method, "name": name}],
                    context=f"Extracted from {Path(source_file).name}",
                )

            elif method == "css":
                selector = m.group(1)
                # Skip trivial or overly long selectors
                if len(selector) < 3 or len(selector) > 120:
                    continue
                key = _make_key(f"css_{selector}")
                if key in seen:
                    continue
                seen.add(key)
                entry = SelectorEntry(
                    key=key,
                    description=f"CSS '{selector}'",
                    strategies=[{"method": "css", "selector": selector}],
                    context=f"Extracted from {Path(source_file).name}",
                )
            else:
                continue

            entries.append(entry)

    logger.info("  Extracted %d locators from %s", len(entries), source_file)
    return entries


def parse_test_spec(ts_content: str, source_file: str) -> Optional[Workflow]:
    """
    Extract a workflow from a Playwright test spec file.

    Looks for:
      test.describe('Workflow Name', () => { ... })
      test.step('step description', async () => { ... })
      expect(...).toBeVisible()
      await page.getByRole('button', { name: 'Submit' }).click()
    """
    # Extract describe block name
    describe_match = re.search(r"test\.describe\(['\"]([^'\"]+)['\"]", ts_content)
    if not describe_match:
        return None

    workflow_name = describe_match.group(1)

    # Extract test.step() calls
    steps: list[WorkflowStep] = []
    step_pattern = re.compile(r"test\.step\(['\"]([^'\"]+)['\"]", re.MULTILINE)
    for m in step_pattern.finditer(ts_content):
        step_text = m.group(1).strip()
        if step_text:
            steps.append(WorkflowStep(text=step_text, is_assertion=False))

    # Extract expect() calls that describe assertions
    expect_pattern = re.compile(
        r"expect.*?\.to(?:BeVisible|HaveText|HaveURL|Contain|BeEnabled)\(['\"]?([^'\"()]+)['\"]?\)",
        re.MULTILINE,
    )
    for m in expect_pattern.finditer(ts_content):
        text = m.group(1).strip()
        if text and len(text) > 3:
            steps.append(
                WorkflowStep(
                    text=f"Verify: {text}",
                    is_assertion=True,
                )
            )

    if not steps:
        # Try extracting bare // comment lines as steps (some spec styles)
        comment_steps = re.findall(r"//\s+([A-Z][^/\n]{10,80})", ts_content)
        for cs in comment_steps:
            steps.append(WorkflowStep(text=cs.strip()))

    # Extract keywords from the describe name and step texts
    all_words = " ".join([workflow_name] + [s.text for s in steps])
    keywords = list(
        set(
            w.lower()
            for w in re.findall(r"\b[a-zA-Z]{4,}\b", all_words)
            if w.lower()
            not in {
                "with",
                "that",
                "this",
                "should",
                "have",
                "into",
                "from",
                "will",
                "step",
                "then",
                "when",
                "page",
                "test",
                "click",
            }
        )
    )[:12]

    return Workflow(
        name=workflow_name,
        source_file=source_file,
        steps=steps,
        keywords=keywords,
    )


def extract_timing_patterns(ts_content: str, source_file: str) -> list[str]:
    """
    Extract waitForTimeout and waitForSelector patterns with surrounding context.
    Returns a list of human-readable timing observations.
    """
    patterns: list[str] = []
    lines = ts_content.split("\n")

    for i, line in enumerate(lines):
        if "waitForTimeout" in line:
            m = re.search(r"waitForTimeout\((\d+)\)", line)
            if m:
                ms = int(m.group(1))
                # Get the comment on the same line or previous line
                comment = ""
                if "//" in line:
                    comment = line[line.index("//") + 2 :].strip()
                elif i > 0 and "//" in lines[i - 1]:
                    comment = lines[i - 1][lines[i - 1].index("//") + 2 :].strip()
                if comment:
                    patterns.append(f"- Wait {ms}ms: {comment} (from {Path(source_file).name})")
                else:
                    patterns.append(f"- Wait {ms}ms (from {Path(source_file).name})")

        elif "waitForSelector" in line or "waitFor(" in line:
            m = re.search(r"waitFor(?:Selector)?\(['\"]([^'\"]+)['\"]", line)
            if m:
                selector = m.group(1)[:80]
                patterns.append(f"- waitForSelector: {selector} (from {Path(source_file).name})")

    return list(set(patterns))  # Dedupe


# ---------------------------------------------------------------------------
# Output Generators
# ---------------------------------------------------------------------------


def generate_selector_registry(
    entries: list[SelectorEntry],
    existing_path: Path,
) -> dict:
    """
    Merge extracted entries into the existing registry JSON.
    Existing hand-written entries take priority — never overwrite them.
    """
    existing: dict = {"version": "1.0", "selectors": {}}

    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            logger.info("Loaded existing registry: %d entries", len(existing.get("selectors", {})))
        except json.JSONDecodeError as e:
            logger.warning("Could not parse existing registry: %s — will create fresh", e)

    existing_keys = set(existing.get("selectors", {}).keys())
    new_count = 0

    for entry in entries:
        if entry.key not in existing_keys:
            existing["selectors"][entry.key] = {
                "description": entry.description,
                "strategies": entry.strategies,
                "context": entry.context,
                "timing_note": entry.timing_note,
            }
            new_count += 1

    from datetime import date

    existing["last_updated"] = str(date.today())
    logger.info("Registry: %d new entries added (%d total)", new_count, len(existing["selectors"]))
    return existing


def generate_workflow_md(workflow: Workflow) -> str:
    """Convert a Workflow to KB markdown format."""
    lines = [
        f"## WORKFLOW: {workflow.name}",
        f"KEYWORDS: {', '.join(workflow.keywords[:12])}",
        "---",
        f"Source: {Path(workflow.source_file).relative_to(Path(workflow.source_file).parent.parent.parent)}",
        "",
    ]

    for i, step in enumerate(workflow.steps, 1):
        prefix = "[VERIFY] " if step.is_assertion else ""
        lines.append(f"{i}. {prefix}{step.text}")

    return "\n".join(lines)


def generate_timing_addendum(patterns: list[str]) -> str:
    """Format extracted timing patterns as a KB addendum section."""
    if not patterns:
        return ""
    lines = [
        "\n══════════════════════════════════════════════════════════════",
        "AUTO-EXTRACTED TIMING PATTERNS (from Playwright tests)",
        "══════════════════════════════════════════════════════════════",
    ]
    lines.extend(patterns)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _make_key(text: str) -> str:
    """Sanitize text into a snake_case JSON key."""
    text = re.sub(r"[^a-zA-Z0-9\s_]", "", text)
    text = re.sub(r"\s+", "_", text.strip().lower())
    return text[:60]


def _sanitize_filename(name: str) -> str:
    """Convert workflow name to a safe filename component."""
    name = re.sub(r"[^a-zA-Z0-9\s]", "", name)
    name = re.sub(r"\s+", "_", name.strip().lower())
    return name[:50]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def extract_all_selectors(playwright_root: Path) -> list[SelectorEntry]:
    """Extract all selectors from all TS files in playwright_root."""
    utils_files = list(playwright_root.glob("**/utils/*.ts"))
    support_files = list(playwright_root.glob("**/support/*.ts"))
    test_files = sorted(
        set(list(playwright_root.glob("**/tests/*.test.ts")) + list(playwright_root.glob("**/tests/*.spec.ts")))
    )

    all_entries: list[SelectorEntry] = []
    all_ts_files = utils_files + support_files + test_files
    for ts_file in all_ts_files:
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
            entries = parse_helper_locators(content, str(ts_file))
            all_entries.extend(entries)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping %s: %s", ts_file, e)
    return all_entries

def main(args: argparse.Namespace) -> int:
    playwright_root = Path(args.playwright_root)
    output_dir = Path(args.output_dir)

    if not playwright_root.exists():
        logger.error("Playwright root not found: %s", playwright_root)
        logger.error("Use: git worktree add /tmp/pw-branch remotes/origin/Doc/qa-playwright-test-creation")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Find TypeScript files ─────────────────────────────────────────────
    utils_files = list(playwright_root.glob("**/utils/*.ts"))
    support_files = list(playwright_root.glob("**/support/*.ts"))
    # Match ALL test and spec files, not just qa-* prefixed ones
    test_files = sorted(
        set(list(playwright_root.glob("**/tests/*.test.ts")) + list(playwright_root.glob("**/tests/*.spec.ts")))
    )

    logger.info(
        "Found %d utility files, %d support files, %d test spec files",
        len(utils_files),
        len(support_files),
        len(test_files),
    )

    # ── Parse ALL TypeScript files for locators ───────────────────────────
    # Locators live in test files too, not just utils. Extract from everything.
    all_entries: list[SelectorEntry] = []
    all_timing: list[str] = []

    all_ts_files = utils_files + support_files + test_files
    for ts_file in all_ts_files:
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
            entries = parse_helper_locators(content, str(ts_file))
            all_entries.extend(entries)
            timing = extract_timing_patterns(content, str(ts_file))
            all_timing.extend(timing)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping %s: %s", ts_file, e)

    # Write selector registry
    registry_path = output_dir / "selector_registry.json"
    registry = generate_selector_registry(all_entries, registry_path)
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("✔ Written: %s", registry_path)

    # Optionally append timing patterns to angular_timing_contracts.md
    timing_path = output_dir / "angular_timing_contracts.md"
    if all_timing and args.append_timing:
        addendum = generate_timing_addendum(list(set(all_timing)))
        if timing_path.exists():
            existing = timing_path.read_text(encoding="utf-8")
            # Don't add if already there
            if "AUTO-EXTRACTED TIMING PATTERNS" not in existing:
                timing_path.write_text(existing + "\n" + addendum, encoding="utf-8")
                logger.info("✔ Appended timing patterns to %s", timing_path)
        else:
            timing_path.write_text(addendum, encoding="utf-8")
            logger.info("✔ Written: %s", timing_path)

    # ── Parse test spec files → workflow KB entries ───────────────────────
    workflows_written = 0
    for ts_file in test_files:
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
            workflow = parse_test_spec(content, str(ts_file))
            if workflow and workflow.steps:
                safe_name = _sanitize_filename(workflow.name)
                out_path = output_dir / f"workflow_{safe_name}.md"
                # Don't overwrite existing hand-written files with the same name
                if out_path.exists() and args.skip_existing:
                    logger.debug("Skipping existing: %s", out_path)
                    continue
                out_path.write_text(
                    generate_workflow_md(workflow),
                    encoding="utf-8",
                )
                logger.info("  ✔ %s → %s", ts_file.name, out_path.name)
                workflows_written += 1
            else:
                logger.debug("No steps found in: %s", ts_file.name)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Skipping %s: %s", ts_file, e)

    logger.info(
        "\n✓ KB refresh complete:\n"
        "  - Selector registry: %d entries\n"
        "  - Workflow files written: %d\n"
        "  - Timing patterns extracted: %d",
        len(registry.get("selectors", {})),
        workflows_written,
        len(set(all_timing)),
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract vQA KB knowledge from vsuitePlatform Playwright tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--playwright-root",
        required=True,
        help=(
            "Root directory of the checked-out Playwright branch. "
            "Example: /tmp/pw-branch (via git worktree). "
            "Use git worktree add /tmp/pw-branch remotes/origin/Doc/qa-playwright-test-creation"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="knowledge",
        help="Directory to write generated KB files (default: knowledge)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip workflow files that already exist (default: True, protects hand-edited files)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="Overwrite existing workflow files",
    )
    parser.add_argument(
        "--append-timing",
        action="store_true",
        default=False,
        help="Append extracted timing patterns to angular_timing_contracts.md",
    )

    sys.exit(main(parser.parse_args()))
