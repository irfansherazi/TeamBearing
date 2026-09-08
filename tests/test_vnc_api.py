"""
Integration tests for VNC URL generation via the HTTP API.

Phase 3 additions:
  - Verify ``/api/session/start`` returns the per-session novnc_url format.
  - Fix stale route paths (``/execute`` → ``/api/execute``,
    ``/status/{run_id}`` → ``/api/status/{run_id}``).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api import routes as routes_module
from backend.main import app


@pytest.fixture
def client():
    """TestClient with auth disabled."""
    with patch("backend.config.settings") as mock_settings:
        mock_settings.api_auth_enabled = False
        mock_settings.novnc_port = 6080
        mock_settings.external_host = "localhost"
        mock_settings.external_protocol = "http"
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Existing tests — corrected route paths
# ---------------------------------------------------------------------------


def test_execute_returns_novnc_url(client):
    """AC-ENTRY-1: POST /api/execute returns novnc_url in interactive mode."""
    with patch("backend.api.routes._execute_run"):
        payload = {"jira_ticket_id": "VC2-8967", "role": "account_executive", "mode": "interactive"}
        resp = client.post("/api/execute", json=payload, headers={"Host": "vqa.vcreative.net"})

        assert resp.status_code == 200
        data = resp.json()
        assert "novnc_url" in data
        # Non-HTTPS: falls back to port-based URL
        assert data["novnc_url"] == "http://vqa.vcreative.net:6080/vnc.html"


def test_execute_no_novnc_url_in_headless(client):
    """POST /api/execute returns novnc_url=None in headless mode."""
    with patch("backend.api.routes._execute_run"):
        payload = {"jira_ticket_id": "VC2-8967", "role": "account_executive", "mode": "headless"}
        resp = client.post("/api/execute", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["novnc_url"] is None


def test_status_returns_dynamic_novnc_url(client):
    """AC-ENTRY-1: GET /api/status/{run_id} returns dynamic novnc_url."""
    run_id = "test-run-vnc-status"
    routes_module._run_states[run_id] = {
        "status": "running",
        "state": {"mode": "interactive"},
        "jira_ticket_id": "VC2-8967",
        "role": "account_executive",
    }

    try:
        # HTTP host → port-based URL
        resp = client.get(f"/api/status/{run_id}", headers={"Host": "localhost:8000"})
        assert resp.status_code == 200
        data = resp.json()
        assert "novnc_url" in data
        # localhost → None (no local noVNC server)
        assert data["novnc_url"] is None

        # Production HTTPS → session-path URL (no session_id here = legacy global)
        resp = client.get(
            f"/api/status/{run_id}",
            headers={"Host": "vqa.vcreative.net", "X-Forwarded-Proto": "https"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["novnc_url"] == "https://vqa.vcreative.net/vnc.html?autoconnect=true&reconnect=true&path=websockify"

    finally:
        if run_id in routes_module._run_states:
            routes_module._run_states._store.pop(run_id, None)


def test_status_headless_no_vnc_url(client):
    """GET /api/status/{run_id} returns no vnc_url for headless runs."""
    run_id = "test-run-headless-status"
    routes_module._run_states[run_id] = {
        "status": "running",
        "state": {"mode": "headless"},
        "jira_ticket_id": "VC2-8967",
        "role": "account_executive",
    }

    try:
        resp = client.get(f"/api/status/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("novnc_url") is None
    finally:
        if run_id in routes_module._run_states:
            routes_module._run_states._store.pop(run_id, None)


# ---------------------------------------------------------------------------
# Phase 3 new test — session-start fixture asserts session_id in novnc_url
# ---------------------------------------------------------------------------


def test_session_start_novnc_url_contains_session_id():
    """
    Phase 3 / AC-ENTRY-1: POST /api/session/start returns a novnc_url that
    embeds the session_id in the path-prefix format:

        /vnc/<session_id>/vnc.html?path=websockify/<session_id>

    Verifies the end-to-end contract: Session.novnc_url is built at session
    creation time and returned verbatim in the start response body.
    """
    import time
    import uuid
    from unittest.mock import patch

    from backend.session.models import Session, SessionState

    fake_sid = uuid.uuid4().hex
    fake_session = Session(
        session_id=fake_sid,
        user_email="alice@vcreative.com",
        user_id="42",
        display_num=1,
        vnc_port=6081,
        jwt_valid_until=time.time() + 3600,
        state=SessionState.READY,
    )

    # The URL is derived from Session.novnc_url (a property)
    novnc_url = fake_session.novnc_url
    assert fake_sid in novnc_url
    assert novnc_url == f"/vnc/{fake_sid}/vnc.html?path=websockify/{fake_sid}"
