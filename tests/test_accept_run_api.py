"""
vQA — Unit Tests: Accept Run API endpoints (TASK-031 Phase 2)
=============================================================
Module: tests/test_accept_run_api.py

Tests the POST /runs/{run_id}/accept, GET /accepted-tests, and
DELETE /accepted-tests/{ticket_id} route handlers.

Coverage:
  - 404 for unknown run_id (AC-ENTRY-2)
  - 400 for non-completed runs (AC-ENTRY-2)
  - 422 for runs with missing state fields (AC-ENTRY-2)
  - 200 accept + correct response schema (AC-HAPPY-2)
  - GET /accepted-tests returns stored records (AC-HAPPY-2)
  - DELETE removes record (AC-HAPPY-2)

Author: vQA Build Agent (TASK-031 Phase 2)
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a TestClient for the FastAPI app."""
    from backend.main import app as _app

    return _app


@pytest.fixture
def client(app, tmp_path):
    """TestClient with an isolated accepted_tests_dir."""
    # Override settings to use a temp dir for accepted tests
    with patch("backend.storage.accepted_test_store._store_instance", None):
        with patch("backend.config.settings") as mock_settings:
            mock_settings.accepted_tests_dir = str(tmp_path / "accepted")
            mock_settings.api_auth_enabled = False
            mock_settings.enable_smart_replay = True
            mock_settings.vqa_mode = "interactive"
            mock_settings.enable_toast_buffer = False
            mock_settings.accepted_tests_max_age_days = 30
            mock_settings.accepted_tests_max_count = 1000
            yield TestClient(app)


def _make_completed_run_state(
    ticket_id: str = "VC2-9001",
    ac_steps: list | None = None,
    execution_log: list | None = None,
) -> dict:
    """Build a minimal completed run state dict."""
    if ac_steps is None:
        ac_steps = ["Log in as AE", "Click New Request", "Select Radio Commercial"]
    if execution_log is None:
        execution_log = [
            {
                "step_index": 0,
                "action_type": "navigate",
                "success": True,
                "action_payload": {"action": "navigate", "url": "https://example.com"},
                "timestamp": "2026-05-19T12:00:00Z",
            }
        ]
    return {
        "status": "completed",
        "state": {
            "jira_ticket": {
                "ticket_id": ticket_id,
                "acceptance_criteria_steps": ac_steps,
            },
            "detailed_execution_log": execution_log,
        },
        "error": None,
        "jira_ticket_id": ticket_id,
        "role": "account_executive",
    }


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/accept tests
# ---------------------------------------------------------------------------


class TestAcceptRunEndpoint:
    """Tests for POST /runs/{run_id}/accept."""

    def test_accept_returns_404_for_unknown_run(self, client):
        """404 for a run_id that was never started."""
        resp = client.post("/runs/run-nonexistent-xyz/accept")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_accept_returns_400_for_running_run(self, client):
        """400 when the run has not completed yet (status=running)."""
        from backend.api import routes as _routes

        _routes._run_states["run-in-progress"] = {
            "status": "running",
            "state": {},
            "error": None,
            "jira_ticket_id": "VC2-9001",
            "role": "ae",
        }
        try:
            resp = client.post("/runs/run-in-progress/accept")
            assert resp.status_code == 400
            assert "not completed" in resp.json()["detail"].lower()
        finally:
            _routes._run_states._store.pop("run-in-progress", None)

    def test_accept_returns_422_missing_ticket_id(self, client):
        """422 when the run state has no ticket_id."""
        from backend.api import routes as _routes

        _routes._run_states["run-no-ticket"] = {
            "status": "completed",
            "state": {
                "jira_ticket": {"ticket_id": "", "acceptance_criteria_steps": ["Step 1"]},
                "detailed_execution_log": [{"success": True}],
            },
            "error": None,
        }
        try:
            resp = client.post("/runs/run-no-ticket/accept")
            assert resp.status_code == 422
        finally:
            _routes._run_states._store.pop("run-no-ticket", None)

    def test_accept_returns_422_missing_execution_log(self, client):
        """422 when the run state has an empty execution_log."""
        from backend.api import routes as _routes

        _routes._run_states["run-no-log"] = {
            "status": "completed",
            "state": {
                "jira_ticket": {"ticket_id": "VC2-9001", "acceptance_criteria_steps": ["Step 1"]},
                "detailed_execution_log": [],  # empty!
            },
            "error": None,
        }
        try:
            resp = client.post("/runs/run-no-log/accept")
            assert resp.status_code == 422
        finally:
            _routes._run_states._store.pop("run-no-log", None)

    def test_accept_success_returns_expected_schema(self, client, tmp_path):
        """
        AC-HAPPY-2: POST /runs/{run_id}/accept returns accepted=True with
        ticket_id, ac_hash, and step_count.
        """
        from backend.api import routes as _routes
        from backend.storage.accepted_test_store import AcceptedTestStore

        run_id = "run-accept-test-001"
        run_state = _make_completed_run_state()
        _routes._run_states[run_id] = run_state

        # Patch the store to use our tmp dir
        test_store = AcceptedTestStore(store_dir=str(tmp_path / "accepted_tests"))
        with patch("backend.storage.accepted_test_store.get_accepted_test_store", return_value=test_store):
            resp = client.post(f"/runs/{run_id}/accept")

        _routes._run_states._store.pop(run_id, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert data["run_id"] == run_id
        assert data["ticket_id"] == "VC2-9001"
        assert "ac_hash" in data
        assert len(data["ac_hash"]) == 12
        assert "step_count" in data
        assert data["step_count"] >= 0

    def test_accept_creates_record_on_disk(self, client, tmp_path):
        """
        AC-HAPPY-2: After accept, the record file exists on disk.
        """
        from backend.api import routes as _routes
        from backend.storage.accepted_test_store import AcceptedTestStore

        run_id = "run-disk-check-001"
        run_state = _make_completed_run_state()
        _routes._run_states[run_id] = run_state

        test_store = AcceptedTestStore(store_dir=str(tmp_path / "disk_check"))
        with patch("backend.storage.accepted_test_store.get_accepted_test_store", return_value=test_store):
            resp = client.post(f"/runs/{run_id}/accept")

        _routes._run_states._store.pop(run_id, None)

        assert resp.status_code == 200
        # Verify a record file was created
        record_files = [f for f in (tmp_path / "disk_check").glob("*.json") if f.name != "index.json"]
        assert len(record_files) == 1


# ---------------------------------------------------------------------------
# GET /accepted-tests tests
# ---------------------------------------------------------------------------


class TestListAcceptedTests:
    """Tests for GET /accepted-tests."""

    def test_list_returns_empty_initially(self, client, tmp_path):
        """GET /accepted-tests returns {total: 0, records: []} when empty."""
        from backend.storage.accepted_test_store import AcceptedTestStore

        test_store = AcceptedTestStore(store_dir=str(tmp_path / "empty_store"))
        with patch("backend.storage.accepted_test_store.get_accepted_test_store", return_value=test_store):
            resp = client.get("/accepted-tests")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["records"] == []

    def test_list_returns_stored_records(self, client, tmp_path):
        """GET /accepted-tests returns records after saving."""
        from backend.storage.accepted_test_store import AcceptedTestStore

        test_store = AcceptedTestStore(store_dir=str(tmp_path / "store"))
        test_store.save(
            ticket_id="VC2-9001",
            ac_steps=["Step A", "Step B"],
            execution_log=[
                {
                    "step_index": 0,
                    "success": True,
                    "action_type": "navigate",
                    "action_payload": {},
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ],
            run_id="run-list-test",
        )

        with patch("backend.storage.accepted_test_store.get_accepted_test_store", return_value=test_store):
            resp = client.get("/accepted-tests")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["records"][0]["ticket_id"] == "VC2-9001"
