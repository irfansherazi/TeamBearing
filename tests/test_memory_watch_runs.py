"""
tests/test_memory_watch_runs.py
===============================
Unit tests for Memory Watch history SQLite store.
"""

from pathlib import Path

from backend.storage.memory_watch_runs import MemoryWatchRunStore


def test_create_and_finish_run(tmp_path: Path):
    store = MemoryWatchRunStore(tmp_path / "memory_watch_runs.db")
    store.create_run("mw-abcd1234", "po-open-spot", "qa", 5)
    listed = store.list_runs()
    assert listed[0]["run_id"] == "mw-abcd1234"
    assert listed[0]["status"] == "running"
    assert listed[0]["flow"] == "po-open-spot"
    assert "log_text" not in listed[0]

    store.finish_run(
        "mw-abcd1234",
        "completed",
        [{"cycle": 0, "usedMb": 42.0, "deltaMb": 0, "gcRuns": 3, "status": "watching"}],
        [{"item": "HEAP", "status": "PASS", "evidence": "+8 MB"}],
        "line one\n| HEAP | PASS | +8 MB |",
        True,
        8.0,
        str(tmp_path / "report"),
        "recording.webm",
    )
    listed = store.list_runs()
    assert listed[0]["status"] == "completed"
    assert listed[0]["verdict_pass"] is True
    assert listed[0]["growth_mb"] == 8.0

    detail = store.get_run("mw-abcd1234")
    assert detail is not None
    assert detail["log_text"].startswith("line one")
    assert detail["samples"][0]["cycle"] == 0
    assert detail["video_file"] == "recording.webm"


def test_list_newest_first_and_missing(tmp_path: Path):
    store = MemoryWatchRunStore(tmp_path / "memory_watch_runs.db")
    store.create_run("mw-11111111", "po-open-spot", "qa", 5)
    store.create_run("mw-22222222", "po-search-panel", "test", 3)
    listed = store.list_runs()
    assert [item["run_id"] for item in listed] == ["mw-22222222", "mw-11111111"]
    assert store.get_run("mw-00000000") is None
