"""
tests/test_ghost_login_api.py
==============================
TDD tests for TASK-102, Phase 4: API Endpoint.

Covers:
  - Schema existence and validation of GhostCredentialsRequest / GhostCredentialsResponse
  - POST /runs/{run_id}/ghost-credentials endpoint
  - 404 for unknown run_id
  - 200 on success (calls set_ghost_credentials, unblocks event)
  - Security: password never echoed in response
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create the FastAPI app under test."""
    from backend.main import app as _app

    return _app


@pytest.fixture
def client(app):
    """TestClient with API auth disabled."""
    yield TestClient(app)


def _seed_run(run_id: str, status: str = "running") -> None:
    """Insert a minimal run into _run_states so endpoints recognise it."""
    from backend.api import routes as _routes

    _routes._run_states[run_id] = {"status": status, "state": {}}


# ---------------------------------------------------------------------------
# 1. Schema — GhostCredentialsRequest and GhostCredentialsResponse
# ---------------------------------------------------------------------------


class TestGhostCredentialsSchema:
    """The API schema module must expose GhostCredentialsRequest and Response."""

    def test_ghost_credentials_request_exists(self):
        """GhostCredentialsRequest must be importable from backend.api.schemas."""
        from backend.api.schemas import GhostCredentialsRequest  # noqa: F401

    def test_ghost_credentials_response_exists(self):
        """GhostCredentialsResponse must be importable from backend.api.schemas."""
        from backend.api.schemas import GhostCredentialsResponse  # noqa: F401

    def test_request_requires_email(self):
        """GhostCredentialsRequest must require email field."""
        import pydantic

        from backend.api.schemas import GhostCredentialsRequest

        with pytest.raises((pydantic.ValidationError, TypeError)):
            GhostCredentialsRequest(password="pass")

    def test_request_requires_password(self):
        """GhostCredentialsRequest must require password field."""
        import pydantic

        from backend.api.schemas import GhostCredentialsRequest

        with pytest.raises((pydantic.ValidationError, TypeError)):
            GhostCredentialsRequest(email="bob@x.com")

    def test_request_valid(self):
        """GhostCredentialsRequest must accept both email and password."""
        from backend.api.schemas import GhostCredentialsRequest

        req = GhostCredentialsRequest(
            email="admin@vpromedia.com",
            password="secret123",
        )
        assert req.email == "admin@vpromedia.com"
        assert req.password == "secret123"


# ---------------------------------------------------------------------------
# 2. API Endpoint — POST /runs/{run_id}/ghost-credentials
# ---------------------------------------------------------------------------


class TestGhostCredentialsEndpoint:
    """Tests for the POST /runs/{run_id}/ghost-credentials endpoint."""

    def test_ghost_credentials_requires_valid_json(self, client):
        """Malformatted JSON should return 422 Unprocessable Entity."""
        _seed_run("run-invalid")
        # Empty payload
        resp = client.post("/api/runs/run-invalid/ghost-credentials", json={})
        assert resp.status_code == 422

    def test_ghost_credentials_unknown_run_id(self, client):
        """POST for unknown run_id should return 404."""
        resp = client.post(
            "/api/runs/run-does-not-exist/ghost-credentials",
            json={"email": "admin@vpro.com", "password": "pass"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("backend.api.routes.set_ghost_credentials")
    def test_ghost_credentials_success(self, mock_set_ghost, client):
        """POST with valid run_id and credentials should return 200 and unblock."""
        run_id = "run-success"
        _seed_run(run_id)

        resp = client.post(
            f"/api/runs/{run_id}/ghost-credentials",
            json={"email": "admin@vpro.com", "password": "pass123"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": ""}
        mock_set_ghost.assert_called_once_with(run_id, "admin@vpro.com", "pass123")
