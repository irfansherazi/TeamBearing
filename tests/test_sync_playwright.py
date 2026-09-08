import json

import pytest

from scripts.sync_playwright import SelectorMerger


@pytest.fixture
def temp_kb(tmp_path):
    kb_path = tmp_path / "selector_registry.json"
    data = {
        "version": "1.0",
        "selectors": {
            "protected_selector": {
                "description": "Don't touch me",
                "protected": True,
                "strategies": [{"method": "css", "selector": ".old-protected"}]
            },
            "unprotected_selector": {
                "description": "Update me",
                "strategies": [{"method": "css", "selector": ".old-unprotected"}]
            }
        }
    }
    kb_path.write_text(json.dumps(data, indent=2))
    return kb_path

def test_merger_overrides_unprotected(temp_kb, tmp_path):
    merger = SelectorMerger(kb_path=temp_kb, backup_dir=tmp_path / "backups", backup=False)
    new_selectors = {
        "unprotected_selector": {
            "description": "New description",
            "strategies": [{"method": "css", "selector": ".new-unprotected"}]
        },
        "new_selector": {
            "description": "Completely new",
            "strategies": [{"method": "css", "selector": ".brand-new"}]
        }
    }

    merger.merge(new_selectors)

    with open(temp_kb, "r") as f:
        data = json.load(f)

    assert data["selectors"]["unprotected_selector"]["strategies"][0]["selector"] == ".new-unprotected"
    assert data["selectors"]["new_selector"]["strategies"][0]["selector"] == ".brand-new"

def test_merger_respects_protected(temp_kb, tmp_path):
    merger = SelectorMerger(kb_path=temp_kb, backup_dir=tmp_path / "backups", backup=False)
    new_selectors = {
        "protected_selector": {
            "description": "Attempted update",
            "strategies": [{"method": "css", "selector": ".should-not-be-here"}]
        }
    }

    merger.merge(new_selectors)

    with open(temp_kb, "r") as f:
        data = json.load(f)

    assert data["selectors"]["protected_selector"]["strategies"][0]["selector"] == ".old-protected"
    assert data["selectors"]["protected_selector"].get("protected") is True

def test_merger_creates_backup(temp_kb, tmp_path):
    backup_dir = tmp_path / "backups"
    merger = SelectorMerger(kb_path=temp_kb, backup_dir=backup_dir, backup=True)

    merger.create_backup()

    backups = list(backup_dir.glob("selector_registry_*.json"))
    assert len(backups) == 1
    assert backups[0].exists()

def test_merger_dry_run(temp_kb, tmp_path):
    merger = SelectorMerger(kb_path=temp_kb, backup_dir=tmp_path / "backups", backup=False, dry_run=True)
    new_selectors = {
        "unprotected_selector": {
            "description": "New description",
            "strategies": [{"method": "css", "selector": ".new-unprotected"}]
        }
    }

    merger.merge(new_selectors)

    with open(temp_kb, "r") as f:
        data = json.load(f)

    # Should NOT have changed
    assert data["selectors"]["unprotected_selector"]["strategies"][0]["selector"] == ".old-unprotected"
