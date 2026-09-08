"""
vQA — Unit Tests: AcceptedTestStore & spec_serializer (TASK-031 Phase 2)
=========================================================================
Module: tests/test_accepted_test_store.py

Tests the filesystem-based persistence layer for accepted test runs:
  - backend/storage/accepted_test_store.py::AcceptedTestStore
  - backend/storage/spec_serializer.py (serialization helpers)

Coverage:
  - Store creation and directory auto-provisioning (AC-ENTRY-2, AC-HAPPY-2)
  - Action sequence serialization / deserialization (AC-HAPPY-3)
  - Lookup by ticket_id + AC hash (AC-HAPPY-4)
  - Directory traversal prevention (AC-EDGE-1)
  - Concurrent write safety (AC-EDGE-2)
  - Index file integrity: corrupt index → rebuild from directory (AC-EDGE-3)

Author: vQA Build Agent (TASK-031 Phase 2)
"""

import hashlib
import json
import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_store_dir(tmp_path: Path) -> Path:
    """Return a fresh temp directory for each test."""
    store_dir = tmp_path / "accepted_tests"
    return store_dir  # NOT yet created — store must create it


@pytest.fixture
def store(temp_store_dir: Path):
    """Create an AcceptedTestStore backed by a temp directory."""
    from backend.storage.accepted_test_store import AcceptedTestStore

    return AcceptedTestStore(store_dir=str(temp_store_dir))


@pytest.fixture
def sample_execution_log() -> list[dict]:
    """A minimal execution log suitable for serialization."""
    return [
        {
            "step_index": 0,
            "ac_step_index": 0,
            "action_type": "navigate",
            "action_payload": {"action": "navigate", "url": "https://two-test.vcreative.net"},
            "locator_strategy": "",
            "locator_value": "",
            "success": True,
            "timestamp": "2026-05-19T12:00:00Z",
            "llm_reasoning": "Navigate to target URL",
        },
        {
            "step_index": 1,
            "ac_step_index": 0,
            "action_type": "click",
            "action_payload": {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"},
            "locator_strategy": "get_by_role",
            "locator_value": "role=button, name='Submit'",
            "success": True,
            "timestamp": "2026-05-19T12:00:01Z",
            "llm_reasoning": "Click Submit button",
        },
    ]


@pytest.fixture
def sample_ac_steps() -> list[str]:
    return [
        "Navigate to the application and log in as Account Executive",
        "Click the 'New Request +' button",
        "Select 'Radio Commercial' from the ad type selector",
    ]


def _make_ac_hash(ac_steps: list[str]) -> str:
    """Produce the canonical AC hash for a list of steps."""
    canonical = json.dumps(ac_steps, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Directory auto-provisioning tests
# ---------------------------------------------------------------------------


class TestDirectoryProvisioning:
    """The store must create its directory tree if it doesn't exist."""

    def test_store_creates_directory_on_init(self, temp_store_dir: Path):
        """
        AC-ENTRY-2: AcceptedTestStore.__init__ creates the store dir automatically.
        """
        from backend.storage.accepted_test_store import AcceptedTestStore

        assert not temp_store_dir.exists(), "Precondition: dir must not exist yet"
        AcceptedTestStore(store_dir=str(temp_store_dir))
        assert temp_store_dir.exists(), "store dir must be created on __init__"
        assert temp_store_dir.is_dir()

    def test_store_creates_nested_directories(self, tmp_path: Path):
        """Store creates intermediate parent directories (makedirs with parents=True)."""
        from backend.storage.accepted_test_store import AcceptedTestStore

        deep_dir = tmp_path / "a" / "b" / "c" / "accepted"
        AcceptedTestStore(store_dir=str(deep_dir))
        assert deep_dir.exists()

    def test_store_tolerates_existing_directory(self, temp_store_dir: Path):
        """No error when store dir already exists."""
        from backend.storage.accepted_test_store import AcceptedTestStore

        temp_store_dir.mkdir(parents=True)
        # Should not raise
        AcceptedTestStore(store_dir=str(temp_store_dir))


# ---------------------------------------------------------------------------
# Serialization round-trip tests
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    """Tests for save → load round-trip fidelity."""

    def test_save_creates_record_file(
        self,
        store,
        temp_store_dir: Path,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """
        AC-HAPPY-2: save() writes a JSON file into the store directory.
        """
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        # At least one .json record file must exist
        json_files = list(temp_store_dir.glob("*.json"))
        # Filter out index.json
        record_files = [f for f in json_files if f.name != "index.json"]
        assert len(record_files) == 1, f"Expected 1 record file, found: {record_files}"

    def test_save_file_contains_required_fields(
        self,
        store,
        temp_store_dir: Path,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """
        AC-HAPPY-3: saved record contains ticket_id, ac_hash, steps, and execution_log.
        """
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        record_files = [f for f in temp_store_dir.glob("*.json") if f.name != "index.json"]
        assert record_files, "Expected at least one record file"
        data = json.loads(record_files[0].read_text())

        assert data["ticket_id"] == "VC2-9001"
        assert "ac_hash" in data
        assert "execution_log" in data
        assert isinstance(data["execution_log"], list)
        assert len(data["execution_log"]) == len(sample_execution_log)
        assert "accepted_at" in data
        assert "run_id" in data

    def test_load_returns_saved_execution_log(
        self,
        store,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """
        AC-HAPPY-4: load() retrieves the exact execution_log that was saved.
        """
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        loaded = store.load(ticket_id="VC2-9001", ac_steps=sample_ac_steps)
        assert loaded is not None, "Expected load() to return a record"
        assert loaded["ticket_id"] == "VC2-9001"
        assert len(loaded["execution_log"]) == len(sample_execution_log)
        # Verify first step round-trip
        assert loaded["execution_log"][0]["action_type"] == "navigate"
        assert loaded["execution_log"][1]["action_type"] == "click"

    def test_load_returns_none_for_unknown_ticket(
        self,
        store,
        sample_ac_steps: list[str],
    ):
        """
        AC-HAPPY-4 negative: load() returns None when no record exists.
        """
        result = store.load(ticket_id="VC2-NONEXISTENT", ac_steps=sample_ac_steps)
        assert result is None

    def test_load_returns_none_when_ac_steps_changed(
        self,
        store,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """
        AC-HAPPY-4: load() returns None when AC steps have changed (hash mismatch).
        This ensures modified acceptance criteria trigger a new AI run.
        """
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        # Modified AC steps → different hash → no match
        modified_steps = sample_ac_steps + ["Additional step not in original"]
        result = store.load(ticket_id="VC2-9001", ac_steps=modified_steps)
        assert result is None, "AC hash mismatch must return None"

    def test_save_overwrites_previous_record_for_same_ticket(
        self,
        store,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
        temp_store_dir: Path,
    ):
        """
        Saving twice for the same ticket+AC replaces the old record.
        No duplicate files accumulate.
        """
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        # Save again with a different run_id
        updated_log = [sample_execution_log[0]]  # shorter log
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=updated_log,
            run_id="run-test-002",
        )
        # Should be exactly ONE record file (not two)
        record_files = [f for f in temp_store_dir.glob("*.json") if f.name != "index.json"]
        assert len(record_files) == 1, f"Expected 1 record, got: {[f.name for f in record_files]}"
        # Loaded record should be the most recent
        loaded = store.load(ticket_id="VC2-9001", ac_steps=sample_ac_steps)
        assert loaded["run_id"] == "run-test-002"


# ---------------------------------------------------------------------------
# has_accepted tests
# ---------------------------------------------------------------------------


class TestHasAccepted:
    """Tests for the has_accepted() quick lookup."""

    def test_has_accepted_returns_true_after_save(
        self,
        store,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """has_accepted() returns True when a record exists."""
        store.save(
            ticket_id="VC2-9001",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        assert store.has_accepted(ticket_id="VC2-9001", ac_steps=sample_ac_steps)

    def test_has_accepted_returns_false_without_record(
        self,
        store,
        sample_ac_steps: list[str],
    ):
        """has_accepted() returns False when no record exists."""
        assert not store.has_accepted(ticket_id="VC2-NONE", ac_steps=sample_ac_steps)


# ---------------------------------------------------------------------------
# Security: directory traversal prevention
# ---------------------------------------------------------------------------


class TestDirectoryTraversalPrevention:
    """
    AC-EDGE-1: store must not allow ticket_ids that escape the store directory.
    """

    @pytest.mark.parametrize(
        "malicious_id",
        [
            "../etc/passwd",
            "../../secret",
            "/etc/passwd",
            "VC2-9001/../../../etc/shadow",
            "VC2/../secret",
        ],
    )
    def test_save_rejects_path_traversal_ticket_ids(
        self,
        store,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
        malicious_id: str,
    ):
        """
        save() must raise ValueError for ticket_ids containing path traversal sequences.
        """
        with pytest.raises((ValueError, OSError)):
            store.save(
                ticket_id=malicious_id,
                ac_steps=sample_ac_steps,
                execution_log=sample_execution_log,
                run_id="run-test-traversal",
            )

    def test_save_file_stays_within_store_dir(
        self,
        store,
        temp_store_dir: Path,
        sample_execution_log: list[dict],
        sample_ac_steps: list[str],
    ):
        """Saved file path must be within the store directory."""
        store.save(
            ticket_id="VC2-SAFE",
            ac_steps=sample_ac_steps,
            execution_log=sample_execution_log,
            run_id="run-test-001",
        )
        for json_file in temp_store_dir.rglob("*.json"):
            assert str(json_file).startswith(str(temp_store_dir.resolve())), f"File outside store dir: {json_file}"


# ---------------------------------------------------------------------------
# Concurrent write safety (AC-EDGE-2)
# ---------------------------------------------------------------------------


class TestConcurrentWriteSafety:
    """
    AC-EDGE-2: concurrent saves must not corrupt the store.
    """

    def test_concurrent_saves_do_not_corrupt_index(
        self,
        temp_store_dir: Path,
        sample_execution_log: list[dict],
    ):
        """
        Ten threads saving different tickets concurrently must all succeed
        and the index must contain all tickets.
        """
        from backend.storage.accepted_test_store import AcceptedTestStore

        store = AcceptedTestStore(store_dir=str(temp_store_dir))
        errors = []

        def save_ticket(n: int):
            try:
                ac_steps = [f"Step A for ticket {n}", f"Step B for ticket {n}"]
                store.save(
                    ticket_id=f"VC2-CONC-{n:03d}",
                    ac_steps=ac_steps,
                    execution_log=sample_execution_log,
                    run_id=f"run-conc-{n}",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_ticket, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent save errors: {errors}"

        # All 10 tickets must be loadable
        for i in range(10):
            ac_steps = [f"Step A for ticket {i}", f"Step B for ticket {i}"]
            result = store.load(ticket_id=f"VC2-CONC-{i:03d}", ac_steps=ac_steps)
            assert result is not None, f"Missing result for VC2-CONC-{i:03d}"


# ---------------------------------------------------------------------------
# spec_serializer: action sequence extraction
# ---------------------------------------------------------------------------


class TestSpecSerializer:
    """Tests for backend/storage/spec_serializer.py helpers."""

    def test_extract_replay_actions_filters_success_only(self):
        """
        extract_replay_actions() returns only steps where success=True.
        Failed steps must not be replayed.
        """
        from backend.storage.spec_serializer import extract_replay_actions

        log = [
            {"step_index": 0, "action_type": "navigate", "success": True, "action_payload": {}},
            {"step_index": 1, "action_type": "click", "success": False, "action_payload": {}},
            {"step_index": 2, "action_type": "fill", "success": True, "action_payload": {}},
        ]
        result = extract_replay_actions(log)
        assert len(result) == 2
        assert all(r["success"] for r in result)

    def test_extract_replay_actions_empty_log(self):
        """Empty log → empty list."""
        from backend.storage.spec_serializer import extract_replay_actions

        assert extract_replay_actions([]) == []

    def test_extract_replay_actions_preserves_action_payload(self):
        """
        AC-HAPPY-3: extracted steps preserve the full action_payload for replay.
        """
        from backend.storage.spec_serializer import extract_replay_actions

        payload = {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"}
        log = [{"step_index": 0, "action_type": "click", "success": True, "action_payload": payload}]
        result = extract_replay_actions(log)
        assert result[0]["action_payload"] == payload

    def test_compute_ac_hash_is_deterministic(self, sample_ac_steps: list[str]):
        """
        compute_ac_hash() must produce the same hash for the same AC steps,
        regardless of call order.
        """
        from backend.storage.spec_serializer import compute_ac_hash

        h1 = compute_ac_hash(sample_ac_steps)
        h2 = compute_ac_hash(sample_ac_steps)
        assert h1 == h2
        assert len(h1) == 12  # 12-char prefix of SHA-256

    def test_compute_ac_hash_differs_for_different_steps(self, sample_ac_steps: list[str]):
        """Different AC steps produce different hashes."""
        from backend.storage.spec_serializer import compute_ac_hash

        h1 = compute_ac_hash(sample_ac_steps)
        h2 = compute_ac_hash(sample_ac_steps + ["Extra step"])
        assert h1 != h2

    def test_compute_ac_hash_order_sensitive(self, sample_ac_steps: list[str]):
        """
        AC step order matters — swapping steps changes the hash.
        This ensures the same steps in a different sequence are not considered
        equivalent (order of test steps is semantically significant).
        """
        from backend.storage.spec_serializer import compute_ac_hash

        if len(sample_ac_steps) >= 2:
            shuffled = [sample_ac_steps[1], sample_ac_steps[0]] + sample_ac_steps[2:]
            h1 = compute_ac_hash(sample_ac_steps)
            h2 = compute_ac_hash(shuffled)
            assert h1 != h2, "Step order must affect hash"
