"""
tests/test_memory_watch_stop.py
===============================
Stop a Memory Watch run from History even after the page reloads.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.storage.memory_watch_runs import MemoryWatchRunStore


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    with TestClient(app) as test_client:
        yield test_client


def test_stop_without_pid_marks_running_history_stopped(client, tmp_path):
    store = MemoryWatchRunStore(tmp_path / "memory_watch_runs.db")
    store.create_run("mw-abcd1234", "po-open-spot", "qa", 5)
    with (
        patch("backend.api.memory_watch_routes.memory_watch_run_store", store),
        patch("backend.api.memory_watch_routes.kill_memory_watch_pid") as mock_kill,
    ):
        response = client.post("/api/memory-watch/run/mw-abcd1234/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert store.get_run("mw-abcd1234")["status"] == "stopped"
    mock_kill.assert_not_called()


def test_stop_with_pid_kills_process_tree(client, tmp_path):
    store = MemoryWatchRunStore(tmp_path / "memory_watch_runs.db")
    store.create_run("mw-abcd1234", "po-open-spot", "qa", 5)
    with (
        patch("backend.api.memory_watch_routes.memory_watch_run_store", store),
        patch("backend.api.memory_watch_routes.kill_memory_watch_pid") as mock_kill,
        patch.dict("backend.api.memory_watch_routes._memory_watch_pids", {"mw-abcd1234": 4242}),
    ):
        response = client.post("/api/memory-watch/run/mw-abcd1234/stop")
    assert response.status_code == 200
    mock_kill.assert_called_once_with(4242)
    assert store.get_run("mw-abcd1234")["status"] == "stopped"
