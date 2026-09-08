#!/usr/bin/env python3
"""
vQA — Dropdown Registry Sync Utility
====================================
Module: scripts/sync_dropdown_registry.py

Scans Angular templates and components to auto-populate dropdown_registry.json
with available options.  This reduces manual KB maintenance and ensures the
LLM planner has up-to-date knowledge of valid dropdown choices.

Usage
-----
    python scripts/sync_dropdown_registry.py --path ../vsuitePlatform/src/app
"""

import argparse
import json
import os
import re
from pathlib import Path

# Regex for PrimeNG dropdown components
DROPDOWN_TAG_PATTERN = re.compile(r'<(p-select|p-dropdown|p-multiselect|p-autocomplete)\s+([^>]+)>', re.IGNORECASE | re.DOTALL)
OPTIONS_PATTERN = re.compile(r'\[options\]="([^"]+)"')
PLACEHOLDER_PATTERN = re.compile(r'placeholder="([^"]+)"')
ARIA_LABEL_PATTERN = re.compile(r'aria-label="([^"]+)"')
LABEL_FOR_PATTERN = re.compile(r'<label\s+for="([^"]+)">([^<]+)</label>')

# Regex for TS variables (simplified)
def get_ts_array_pattern(var_name: str):
    # Matches: var_name = [ ... ]; or var_name: any[] = [ ... ];
    return re.compile(rf'{var_name}\s*(?::[^=]+)?\s*=\s*(\[[^\]]+\])', re.IGNORECASE | re.DOTALL)

def parse_dropdown_options(ts_content: str, var_name: str) -> list[str]:
    """Try to extract option labels from a TS array definition."""
    pattern = get_ts_array_pattern(var_name)
    match = pattern.search(ts_content)
    if not match:
        return []

    array_str = match.group(1)
    # Simple extraction of 'label' or 'name' fields, or raw strings
    labels = re.findall(r"label\s*:\s*['\"]([^'\"]+)['\"]", array_str)
    if not labels:
        labels = re.findall(r"name\s*:\s*['\"]([^'\"]+)['\"]", array_str)
    if not labels:
        # Try raw strings like ['A', 'B']
        labels = re.findall(r"['\"]([^'\"]+)['\"]", array_str)

    return labels

def main():
    parser = argparse.ArgumentParser(description="Sync dropdown options from Angular templates.")
    parser.add_argument("--path", required=True, help="Path to Angular source directory.")
    parser.add_argument("--output", default="knowledge/dropdown_registry.json", help="Path to dropdown_registry.json.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without saving.")
    args = parser.parse_args()

    source_path = Path(args.path)
    if not source_path.exists():
        print(f"Error: Path not found: {source_path}")
        return

    # 1. Map labels/IDs from HTML
    labels_to_ids = {}

    registry = {}
    # Load existing registry
    output_path = Path(args.output)
    if output_path.exists():
        try:
            registry = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: Failed to load existing registry: {e}")

    # Walk through the directory
    for root, _, files in os.walk(source_path):
        for file in files:
            if file.endswith(".html"):
                html_path = Path(root) / file
                ts_path = html_path.with_suffix(".ts")

                html_content = html_path.read_text(encoding="utf-8")

                # Pre-scan for labels to match inputId
                label_matches = LABEL_FOR_PATTERN.findall(html_content)
                id_to_label = {fid: label.strip() for fid, label in label_matches}

                # Find dropdown tags
                for tag, attrs in DROPDOWN_TAG_PATTERN.findall(html_content):
                    # Identify the dropdown name
                    dropdown_name = None

                    placeholder_match = PLACEHOLDER_PATTERN.search(attrs)
                    if placeholder_match:
                        dropdown_name = placeholder_match.group(1)

                    if not dropdown_name:
                        aria_match = ARIA_LABEL_PATTERN.search(attrs)
                        if aria_match:
                            dropdown_name = aria_match.group(1)

                    if not dropdown_name:
                        id_match = re.search(r'id="([^"]+)"', attrs) or re.search(r'inputId="([^"]+)"', attrs)
                        if id_match:
                            dropdown_name = id_to_label.get(id_match.group(1))

                    if not dropdown_name:
                        continue

                    # Find options
                    options_match = OPTIONS_PATTERN.search(attrs)
                    if options_match:
                        var_name = options_match.group(1)
                        # Check if it's a hardcoded array in HTML
                        if var_name.startswith("[") and var_name.endswith("]"):
                            labels = re.findall(r"label\s*:\s*['\"]([^'\"]+)['\"]", var_name)
                            if not labels:
                                labels = re.findall(r"['\"]([^'\"]+)['\"]", var_name)
                        elif ts_path.exists():
                            ts_content = ts_path.read_text(encoding="utf-8")
                            labels = parse_dropdown_options(ts_content, var_name)
                        else:
                            labels = []

                        if labels:
                            # Normalize names to title case to match registry convention
                            # but keep original if it looks like a specific brand/term
                            # Actually, let's just keep as is for now.

                            # Merge into registry
                            existing = set(registry.get(dropdown_name, []))
                            new_options = [l for l in labels if l not in existing]
                            if new_options:
                                print(f"Found {len(new_options)} new options for '{dropdown_name}'")
                                registry[dropdown_name] = sorted(list(existing | set(labels)))

    if args.dry_run:
        print("\nDry Run: Not saving changes.")
        # print(json.dumps(registry, indent=2))
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nSaved updated registry to {output_path}")

if __name__ == "__main__":
    main()
