import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.storage.accepted_test_store import AcceptedTestStore


@pytest.fixture
def store(tmp_path):
    return AcceptedTestStore(store_dir=str(tmp_path))

def test_store_save_includes_last_used(store):
    ac_steps = ["Step 1"]
    store.save("VC2-1001", ac_steps, [{"success": True}], "run-1")

    # Check index
    index = store._load_index_raw()
    key = "VC2-1001__" + list(index.keys())[0].split("__")[1]
    assert "last_used" in index[key]

    # Check file
    file_path = store.store_dir / index[key]["file_name"]
    data = json.loads(file_path.read_text())
    assert "last_used" in data

def test_store_load_updates_last_used(store):
    ac_steps = ["Step 1"]
    store.save("VC2-1001", ac_steps, [{"success": True}], "run-1")

    index_before = store._load_index_raw()
    key = list(index_before.keys())[0]
    last_used_before = index_before[key]["last_used"]

    # Wait a bit or manually backdate
    old_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    store._update_index("VC2-1001", key.split("__")[1], index_before[key]["file_name"], last_used=old_time)

    # Load should update it
    store.load("VC2-1001", ac_steps)

    index_after = store._load_index_raw()
    last_used_after = index_after[key]["last_used"]
    assert last_used_after > old_time

def test_store_prune_by_age(store, monkeypatch):
    # Mock settings - start with high age so nothing is pruned during setup
    monkeypatch.setattr("backend.config.settings.accepted_tests_max_age_days", 100)

    # Create 3 records: 2 old, 1 new
    now = datetime.now(UTC)

    def save_with_time(tid, time):
        # We need to compute the hash to match what save() does
        from backend.storage.spec_serializer import compute_ac_hash
        ac_steps = ["Steps"]
        ac_hash = compute_ac_hash(ac_steps)

        store.save(tid, ac_steps, [{"success": True}], f"run-{tid}")

        # Manually backdate in index and file
        with store._lock:
            raw = store._load_index_raw()
            key = f"{tid}__{ac_hash}"
            raw[key]["last_used"] = time
            store._save_index_raw(raw)
            # Also update the file
            fpath = store.store_dir / raw[key]["file_name"]
            data = json.loads(fpath.read_text())
            data["last_used"] = time
            fpath.write_text(json.dumps(data))

    save_with_time("OLD-1", (now - timedelta(days=10)).isoformat())
    save_with_time("OLD-2", (now - timedelta(days=6)).isoformat())
    save_with_time("NEW-1", (now - timedelta(days=1)).isoformat())

    assert len(store._load_index_raw()) == 3

    # Now lower the limit and prune
    monkeypatch.setattr("backend.config.settings.accepted_tests_max_age_days", 5)
    pruned = store.prune()
    assert pruned == 2
    assert len(store._load_index_raw()) == 1
    assert list(store._load_index_raw().keys())[0].startswith("NEW-1")

def test_store_prune_by_count(store, monkeypatch):
    # Mock settings - start with high count
    monkeypatch.setattr("backend.config.settings.accepted_tests_max_count", 10)

    import time
    store.save("T1", ["S1"], [{"success": True}], "r1")
    time.sleep(0.01)
    store.save("T2", ["S2"], [{"success": True}], "r2")
    time.sleep(0.01)
    store.save("T3", ["S3"], [{"success": True}], "r3")

    assert len(store._load_index_raw()) == 3

    # Now lower the limit and prune
    monkeypatch.setattr("backend.config.settings.accepted_tests_max_count", 2)
    pruned = store.prune()
    assert pruned == 1
    assert len(store._load_index_raw()) == 2

    # Should have kept T2 and T3 (the newest)
    index = store._load_index_raw()
    keys = list(index.keys())
    assert any(k.startswith("T2") for k in keys)
    assert any(k.startswith("T3") for k in keys)
    assert not any(k.startswith("T1") for k in keys)
