"""
TASK-117: Build Number Tracking — Unit Tests
=============================================

Tests for build number loading and exposure via /health endpoints.

Run: .venv/bin/python -m pytest backend/api/test_health_build_number.py -v
"""

import os
import sys
import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Settings resolution tests (config.py AC-1, AC-2)
# ---------------------------------------------------------------------------

def _make_settings(**env_overrides):
    """Instantiate Settings with a clean environment for isolated testing."""
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ("VQA_BUILD_NUMBER", "vqa_build_number")
    }
    clean_env.update(env_overrides)
    with patch.dict(os.environ, clean_env, clear=True):
        # Re-import to pick up env changes in the validator
        import backend.config as cfg_mod
        importlib.reload(cfg_mod)
        return cfg_mod.Settings()


def test_build_number_from_env_var():
    """AC-1: Build number is loaded from VQA_BUILD_NUMBER env var."""
    settings = _make_settings(VQA_BUILD_NUMBER="build-42")
    assert settings.vqa_build_number == "build-42"


def test_build_number_from_dot_file(tmp_path):
    """AC-2: Falls back to .build_number file when env var is absent."""
    build_file = tmp_path / ".build_number"
    build_file.write_text("1.2.3-rc")

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        settings = _make_settings()
        assert settings.vqa_build_number == "1.2.3-rc"
    finally:
        os.chdir(original_cwd)


def test_build_number_from_BUILD_NUMBER_file(tmp_path):
    """AC-2: Falls back to BUILD_NUMBER file when env var and .build_number absent."""
    build_file = tmp_path / "BUILD_NUMBER"
    build_file.write_text("99")

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        settings = _make_settings()
        assert settings.vqa_build_number == "99"
    finally:
        os.chdir(original_cwd)


def test_build_number_defaults_when_no_source(tmp_path):
    """AC-2: Falls back to a version string when no env var or file is present."""
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        settings = _make_settings()
        # Either a git-derived "1.0.N" string or "1.0.0"
        assert settings.vqa_build_number.startswith("1.0.")
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Health endpoint tests (routes.py AC-4)
# ---------------------------------------------------------------------------

def test_health_liveness_includes_build_number():
    """AC-4: /api/health response includes build_number field."""
    import backend.config as cfg_mod
    importlib.reload(cfg_mod)

    with patch.dict(os.environ, {"VQA_BUILD_NUMBER": "test-build-liveness"}):
        importlib.reload(cfg_mod)
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "build_number" in data


def test_health_readiness_includes_build_number():
    """AC-4: /api/health/ready response includes build_number field."""
    import backend.config as cfg_mod
    importlib.reload(cfg_mod)

    with patch.dict(os.environ, {"VQA_BUILD_NUMBER": "test-build-ready"}):
        importlib.reload(cfg_mod)
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "build_number" in data
