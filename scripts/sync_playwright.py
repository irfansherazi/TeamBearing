#!/usr/bin/env python3
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add current directory to path so we can import extract_playwright_kb
sys.path.append(str(Path(__file__).parent))
try:
    from extract_playwright_kb import extract_all_selectors
except ImportError:
    # Handle the case where we might be running from a different context
    from scripts.extract_playwright_kb import extract_all_selectors

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

class SelectorMerger:
    def __init__(self, kb_path=None, backup_dir=None, backup=True, dry_run=False):
        self.kb_path = Path(kb_path) if kb_path else Path("knowledge/selector_registry.json")
        self.backup_dir = Path(backup_dir) if backup_dir else Path("memory/backups")
        self.backup = backup
        self.dry_run = dry_run

    def create_backup(self):
        if not self.backup or not self.kb_path.exists():
            return

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"selector_registry_{timestamp}.json"

        if not self.dry_run:
            shutil.copy2(self.kb_path, backup_path)
            logger.info(f"Created backup at {backup_path}")
        else:
            logger.info(f"[Dry Run] Would create backup at {backup_path}")
        return backup_path

    def merge(self, new_selectors_input):
        # Convert input to dict keyed by key
        new_selectors = {}
        if isinstance(new_selectors_input, dict):
            for key, val in new_selectors_input.items():
                new_selectors[key] = val
        elif isinstance(new_selectors_input, list):
            for entry in new_selectors_input:
                if isinstance(entry, dict):
                    key = entry.get("key")
                    if key:
                        new_selectors[key] = entry
                else:
                    new_selectors[entry.key] = {
                        "description": entry.description,
                        "strategies": entry.strategies,
                        "context": entry.context,
                        "timing_note": entry.timing_note,
                    }
        else:
            logger.error("Invalid input type for new_selectors_input")
            return

        if not self.kb_path.exists():
            kb_data = {"version": "1.0", "selectors": {}}
        else:
            try:
                with open(self.kb_path, "r", encoding="utf-8") as f:
                    kb_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                kb_data = {"version": "1.0", "selectors": {}}

        existing_selectors = kb_data.get("selectors", {})
        merged_count = 0
        overridden_count = 0
        protected_skipped_count = 0

        for key, new_entry in new_selectors.items():
            if key in existing_selectors:
                if existing_selectors[key].get("protected", False):
                    logger.info(f"Skipping protected selector: {key}")
                    protected_skipped_count += 1
                    continue

                # Check if it's actually different (excluding metadata like 'protected')
                existing_val = {k: v for k, v in existing_selectors[key].items() if k != "protected"}
                new_val = {k: v for k, v in new_entry.items() if k != "protected"}

                if existing_val != new_val:
                    logger.info(f"Overriding selector: {key}")
                    # Keep existing protected status if any (should be False here anyway)
                    protected = existing_selectors[key].get("protected", False)
                    existing_selectors[key] = new_entry
                    existing_selectors[key]["protected"] = protected
                    overridden_count += 1
            else:
                existing_selectors[key] = new_entry
                merged_count += 1

        kb_data["selectors"] = existing_selectors
        kb_data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        kb_data["source"] = "vQA auto-synced from Playwright"

        if not self.dry_run:
            self.kb_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.kb_path, "w", encoding="utf-8") as f:
                json.dump(kb_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Sync complete: {merged_count} new, {overridden_count} overridden, {protected_skipped_count} protected skipped.")
        else:
            logger.info(f"[Dry Run] Would sync: {merged_count} new, {overridden_count} overridden, {protected_skipped_count} protected skipped.")

def main():
    parser = argparse.ArgumentParser(description="Sync vQA Selector Registry from Playwright tests")
    parser.add_argument("--playwright-root", default="playwright", help="Path to playwright root")
    parser.add_argument("--kb-path", default="knowledge/selector_registry.json", help="Path to selector registry")
    parser.add_argument("--no-backup", action="store_false", dest="backup", help="Do not create backup")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    args = parser.parse_args()

    merger = SelectorMerger(kb_path=args.kb_path, backup=args.backup, dry_run=args.dry_run)

    if args.backup:
        merger.create_backup()

    pw_root = Path(args.playwright_root)
    if not pw_root.exists():
        logger.error(f"Playwright root not found: {pw_root}")
        sys.exit(1)

    logger.info(f"Extracting selectors from {pw_root}...")
    new_selectors = extract_all_selectors(pw_root)

    logger.info(f"Merging {len(new_selectors)} extracted selectors into {args.kb_path}...")
    merger.merge(new_selectors)

if __name__ == "__main__":
    main()
