#!/usr/bin/env python3
"""
vQA Knowledge Base Deduplication Script
========================================
Module: dedup_kb.py (project root)

Reads knowledge/human_guidance.md, parses ## WORKFLOW: blocks, groups them
by normalized topic (first 60 chars, lowercase), keeps only the NEWEST entry
per group (by timestamp or file order), and rewrites the file safely.

Usage:
    python3 dedup_kb.py              # Preview mode (shows what would change)
    python3 dedup_kb.py --apply      # Apply deduplication and rewrite file

Safety:
    - Creates a .bak backup before rewriting
    - Preview mode is the default (no --apply = dry run)
    - Preserves the file preamble (content before first ## WORKFLOW:)
"""

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────
KB_FILE = Path(__file__).parent / "knowledge" / "human_guidance.md"
BACKUP_SUFFIX = ".bak"
NORM_PREFIX_LEN = 60  # Characters to compare for topic grouping


def parse_workflows(text: str) -> tuple[str, list[dict]]:
    """
    Parse human_guidance.md into a preamble and list of workflow entries.

    Returns
    -------
    tuple[str, list[dict]]
        (preamble, entries) where each entry is:
        {
            "raw": str,         # Full raw text of the section (without leading ## WORKFLOW:)
            "name": str,        # Workflow name (first line after ## WORKFLOW:)
            "norm_key": str,    # Normalized key for grouping (lowered, first N chars)
            "timestamp": str,   # Extracted timestamp or "" if none found
            "char_count": int,  # Length of raw content
        }
    """
    # Split on ## WORKFLOW: headers, preserving the preamble
    parts = re.split(r"^## WORKFLOW:", text, flags=re.MULTILINE)

    preamble = parts[0].rstrip() + "\n" if parts else ""
    entries: list[dict] = []

    for section in parts[1:]:
        raw = section.rstrip()
        lines = raw.strip().split("\n")
        if not lines:
            continue

        name = lines[0].strip()

        # Normalize the key for grouping
        # Remove ticket prefixes like "[ticket: QA-321]" for comparison
        clean_name = re.sub(r"\[ticket:\s*\S+\]\s*", "", name, flags=re.IGNORECASE)
        norm_key = clean_name.strip().lower()[:NORM_PREFIX_LEN]

        # Extract timestamp if present (ISO format in the body)
        ts_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", raw)
        timestamp = ts_match.group(0) if ts_match else ""

        entries.append({
            "raw": raw,
            "name": name,
            "norm_key": norm_key,
            "timestamp": timestamp,
            "char_count": len(raw),
        })

    return preamble, entries


def deduplicate(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Group entries by norm_key and keep only the newest per group.

    Returns
    -------
    tuple[list[dict], list[dict]]
        (kept, removed) — entries to keep and entries that were deduplicated.
    """
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["norm_key"], []).append(entry)

    kept: list[dict] = []
    removed: list[dict] = []

    for norm_key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue

        # Sort by timestamp (newest first), then by char_count (longest first)
        # as a tiebreaker — longer entries tend to be more complete
        def sort_key(e):
            ts = e["timestamp"]
            try:
                dt = datetime.fromisoformat(ts) if ts else datetime.min
            except ValueError:
                dt = datetime.min
            return (dt, e["char_count"])

        group.sort(key=sort_key, reverse=True)

        # Keep the newest/longest entry, remove the rest
        kept.append(group[0])
        removed.extend(group[1:])

    return kept, removed


def rebuild_file(preamble: str, kept: list[dict]) -> str:
    """Rebuild the markdown file from preamble and kept entries."""
    sections = [preamble]
    for entry in kept:
        sections.append(f"\n## WORKFLOW:{entry['raw']}")
    return "\n".join(sections) + "\n"


def main():
    apply_mode = "--apply" in sys.argv

    if not KB_FILE.exists():
        print(f"ERROR: KB file not found: {KB_FILE}")
        sys.exit(1)

    original_text = KB_FILE.read_text(encoding="utf-8")
    original_size = len(original_text)

    preamble, entries = parse_workflows(original_text)

    print(f"=== vQA Knowledge Base Deduplication ===")
    print(f"File: {KB_FILE}")
    print(f"Original size: {original_size:,} bytes")
    print(f"Total entries: {len(entries)}")
    print()

    kept, removed = deduplicate(entries)

    print(f"Unique topics: {len(kept)}")
    print(f"Duplicates to remove: {len(removed)}")
    print()

    if removed:
        print("── Duplicate Groups ──────────────────────────────────")
        # Group removed entries by norm_key for display
        removed_by_key: dict[str, list[dict]] = {}
        for entry in removed:
            removed_by_key.setdefault(entry["norm_key"], []).append(entry)

        for norm_key, group in removed_by_key.items():
            # Find the kept entry for this group
            kept_entry = next((e for e in kept if e["norm_key"] == norm_key), None)
            print(f"\n  Topic: \"{norm_key}\"")
            if kept_entry:
                print(f"  ✓ KEPT: \"{kept_entry['name'][:70]}\" ({kept_entry['timestamp'] or 'no timestamp'})")
            for entry in group:
                print(f"  ✗ DROP: \"{entry['name'][:70]}\" ({entry['timestamp'] or 'no timestamp'})")

        new_text = rebuild_file(preamble, kept)
        new_size = len(new_text)
        savings = original_size - new_size

        print(f"\n── Summary ───────────────────────────────────────────")
        print(f"  Before: {original_size:,} bytes, {len(entries)} entries")
        print(f"  After:  {new_size:,} bytes, {len(kept)} entries")
        print(f"  Saved:  {savings:,} bytes ({savings/original_size*100:.1f}%)")

        if apply_mode:
            # Create backup
            backup_path = KB_FILE.with_suffix(KB_FILE.suffix + BACKUP_SUFFIX)
            shutil.copy2(KB_FILE, backup_path)
            print(f"\n  Backup created: {backup_path}")

            # Write deduplicated file
            KB_FILE.write_text(new_text, encoding="utf-8")
            print(f"  ✓ File rewritten successfully!")
            print(f"\n  To restore: cp {backup_path} {KB_FILE}")
        else:
            print(f"\n  DRY RUN — no changes made.")
            print(f"  Run with --apply to rewrite the file:")
            print(f"    python3 dedup_kb.py --apply")
    else:
        print("No duplicates found — file is already clean.")


if __name__ == "__main__":
    main()
