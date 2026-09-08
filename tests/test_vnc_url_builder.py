"""
Unit tests for VNC URL Builder — Phase 3 (per-session URL format).

Phase 3 adds ``session_id`` as an optional argument to ``build_url``.
When provided in a production (HTTPS) context the returned URL uses the
per-session path-prefix scheme:

    /vnc/<session_id>/vnc.html?path=websockify/<session_id>

Without a session_id (pre-Phase-4 backward-compat path via
``__legacy_singleton__``) the old global URL is returned as before.
"""

import pytest

from backend.browser.vnc_builder import vnc_builder
from backend.config import settings


@pytest.fixture
def mock_request():
    class MockRequest:
        def __init__(self, host="localhost:8000", scheme="http", headers=None):
            self.headers = headers or {"host": host}
            self.url = type("obj", (object,), {"scheme": scheme})

    return MockRequest


# ---------------------------------------------------------------------------
# Existing tests — preserved with corrected expectations
# ---------------------------------------------------------------------------


def test_build_url_batch_mode(mock_request):
    req = mock_request()
    assert vnc_builder.build_url(req, "batch") is None


def test_build_url_localhost_returns_none(mock_request):
    """
    Phase 0 change: localhost has no noVNC server running locally.
    build_url returns None so callers fall back to the CDP screencast path.
    """
    req = mock_request(host="localhost:8000")
    url = vnc_builder.build_url(req, "interactive")
    assert url is None


def test_build_url_remote_host(mock_request):
    req = mock_request(host="vqa.vcreative.net")
    url = vnc_builder.build_url(req, "interactive")
    assert url == f"http://vqa.vcreative.net:{settings.novnc_port}/vnc.html"


def test_build_url_https_proxy_no_session(mock_request):
    """
    Production HTTPS without a session_id: legacy global path (backward compat).
    """
    req = mock_request(
        host="vqa.vcreative.net",
        scheme="http",
        headers={"host": "vqa.vcreative.net", "x-forwarded-proto": "https"},
    )
    url = vnc_builder.build_url(req, "interactive")
    assert url == "https://vqa.vcreative.net/vnc.html?autoconnect=true&reconnect=true&path=websockify"


def test_build_url_settings_override(mock_request):
    original_host = settings.external_host
    settings.external_host = "vqa-prod.vcreative.net"
    try:
        req = mock_request(host="localhost:8000")
        url = vnc_builder.build_url(req, "interactive")
        # external_host is non-localhost but no X-Forwarded-Proto → HTTP fallback
        assert url == f"http://vqa-prod.vcreative.net:{settings.novnc_port}/vnc.html"
    finally:
        settings.external_host = original_host


def test_build_url_standard_ports(mock_request):
    original_port = settings.novnc_port
    settings.novnc_port = 443
    try:
        req = mock_request(host="vqa.vcreative.net", scheme="https")
        url = vnc_builder.build_url(req, "interactive")
        assert url == "https://vqa.vcreative.net/vnc.html?autoconnect=true&reconnect=true&path=websockify"
    finally:
        settings.novnc_port = original_port


def test_build_url_raw_strings():
    """Verify that build_url works with raw metadata strings (Phase 1 fix)."""
    url = vnc_builder.build_url(
        host_header="vqa-manual.example.com",
        protocol="https",
        mode="interactive",
    )
    assert url == "https://vqa-manual.example.com/vnc.html?autoconnect=true&reconnect=true&path=websockify"


# ---------------------------------------------------------------------------
# Phase 3 new tests — per-session URL format
# ---------------------------------------------------------------------------


def test_build_url_with_session_id_production(mock_request):
    """
    AC-HAPPY-1: build_url(session_id=<sid>) in production (HTTPS) returns
    the per-session path-prefix URL:

        /vnc/<session_id>/vnc.html?path=websockify/<session_id>

    This is the format that the nginx sidecar routes to the correct per-session
    websockify port by reading /var/run/vqa/sessions.map.
    """
    sid = "abc123-session"
    req = mock_request(
        host="vqa.vcreative.net",
        scheme="http",
        headers={"host": "vqa.vcreative.net", "x-forwarded-proto": "https"},
    )
    url = vnc_builder.build_url(req, "interactive", session_id=sid)
    assert url == f"/vnc/{sid}/vnc.html?path=websockify/{sid}"


def test_build_url_with_session_id_localhost_returns_none(mock_request):
    """
    With a session_id on localhost, still return None — no local noVNC server.
    The caller falls back to the CDP screencast path.
    """
    sid = "abc123-session"
    req = mock_request(host="localhost:8000")
    url = vnc_builder.build_url(req, "interactive", session_id=sid)
    assert url is None


def test_build_url_with_session_id_http_remote(mock_request):
    """
    With a session_id on non-HTTPS remote host, use the old port-based URL
    (no nginx sidecar in HTTP dev/staging).  The session_id arg is accepted
    but not embedded in the URL for non-production contexts.
    """
    sid = "abc123-session"
    req = mock_request(host="vqa-dev.vcreative.net")
    url = vnc_builder.build_url(req, "interactive", session_id=sid)
    # Non-HTTPS: legacy format
    assert url == f"http://vqa-dev.vcreative.net:{settings.novnc_port}/vnc.html"


def test_build_url_session_id_via_raw_strings():
    """
    Phase 3: session_id works with the raw-metadata call path (host_header + protocol).
    Used by session_routes when constructing novnc_url during session start.
    """
    sid = "my-session-id-xyz"
    url = vnc_builder.build_url(
        host_header="vqa.vcreative.net",
        protocol="https",
        mode="interactive",
        session_id=sid,
    )
    assert url == f"/vnc/{sid}/vnc.html?path=websockify/{sid}"
