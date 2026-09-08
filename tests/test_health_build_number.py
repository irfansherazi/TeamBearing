import os
from unittest.mock import patch, mock_open
import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear settings LRU cache before and after every test to isolate state."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_build_number_from_env(monkeypatch):
    """AC-1: Load build number from environment variable VQA_BUILD_NUMBER."""
    monkeypatch.setenv("VQA_BUILD_NUMBER", "1.2.345")
    settings = get_settings()
    assert settings.vqa_build_number == "1.2.345"


def test_build_number_fallback_dot_build_number(monkeypatch):
    """AC-2: Fallback to .build_number file if VQA_BUILD_NUMBER is not set, empty, or 'dev'."""
    monkeypatch.delenv("VQA_BUILD_NUMBER", raising=False)

    original_exists = os.path.exists

    def mock_exists(path):
        if ".build_number" in path:
            return True
        if "BUILD_NUMBER" in path:
            return False
        return original_exists(path)

    with patch("os.path.exists", side_effect=mock_exists), patch(
        "builtins.open", mock_open(read_data="1.2.999")
    ):
        settings = get_settings()
        assert settings.vqa_build_number == "1.2.999"


def test_build_number_fallback_upper_build_number(monkeypatch):
    """AC-2: Fallback to BUILD_NUMBER file if .build_number does not exist."""
    monkeypatch.delenv("VQA_BUILD_NUMBER", raising=False)

    original_exists = os.path.exists

    def mock_exists(path):
        if ".build_number" in path:
            return False
        if "BUILD_NUMBER" in path:
            return True
        return original_exists(path)

    with patch("os.path.exists", side_effect=mock_exists), patch(
        "builtins.open", mock_open(read_data="1.2.888")
    ):
        settings = get_settings()
        assert settings.vqa_build_number == "1.2.888"


def test_build_number_default_to_fallback(monkeypatch):
    """AC-2: Default to '1.0.0' if env is missing and no fallback files are present."""
    monkeypatch.delenv("VQA_BUILD_NUMBER", raising=False)

    original_exists = os.path.exists

    def mock_exists(path):
        if ".build_number" in path or "BUILD_NUMBER" in path:
            return False
        return original_exists(path)

    with patch("os.path.exists", side_effect=mock_exists), patch("subprocess.run", side_effect=Exception("git failed")):
        settings = get_settings()
        assert settings.vqa_build_number == "1.0.0"


def test_build_number_fallback_to_git(monkeypatch):
    """Fallback to 1.0.<git-commit-count> if env and files are missing but git command succeeds."""
    monkeypatch.delenv("VQA_BUILD_NUMBER", raising=False)

    from unittest.mock import MagicMock

    mock_res = MagicMock()
    mock_res.stdout = "375\n"

    original_exists = os.path.exists

    def mock_exists(path):
        if ".build_number" in path or "BUILD_NUMBER" in path:
            return False
        return original_exists(path)

    with patch("os.path.exists", side_effect=mock_exists), patch("subprocess.run", return_value=mock_res):
        settings = get_settings()
        assert settings.vqa_build_number == "1.0.375"


def test_health_endpoints_include_build_number():
    """AC-4: Verify build number is included in /api/health, /api/health/ready, and /health."""
    from backend.config import settings

    with patch.object(settings, "vqa_build_number", "1.2.456"):
        client = TestClient(app)

        # Check bare /health passthrough
        resp_bare = client.get("/health")
        assert resp_bare.status_code == 200
        data_bare = resp_bare.json()
        assert data_bare["build_number"] == "1.2.456"

        # Check liveness /api/health
        resp_live = client.get("/api/health")
        assert resp_live.status_code == 200
        data_live = resp_live.json()
        assert data_live["build_number"] == "1.2.456"

        # Check readiness /api/health/ready
        with patch("backend.jira.client.validate_jira_connectivity", return_value=True), patch(
            "backend.storage.s3.validate_s3_connectivity", return_value=True
        ):
            resp_ready = client.get("/api/health/ready")
            assert resp_ready.status_code == 200
            data_ready = resp_ready.json()
            assert data_ready["build_number"] == "1.2.456"
