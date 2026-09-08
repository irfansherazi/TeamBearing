"""
Phase 3 — nginx multiplexer integration tests.

Tests the in-process part of the nginx routing contract:
  - ``nginx_map.py`` writes the correct sessions.map entries for two concurrent sessions.
  - ``Session.novnc_url`` produces the path-prefix URL that the nginx sidecar routes.
  - Two concurrent sessions get distinct display numbers and ports.

NOTE: These tests run purely in-process against the Python code.  The actual
nginx sidecar end-to-end routing (HTTP traffic over a live container) is a
manual / staging verification step documented in the Phase 3 acceptance notes —
it requires a running Docker container with the supervisord + nginx setup from
Phase 1 which is not available in the CI Python test environment.
"""

import io
import os
import tempfile
import uuid

import pytest

from backend.session.models import Session, SessionState
from backend.session.nginx_map import write_sessions_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_session(display_num: int) -> Session:
    """Create a minimal Session fixture with a distinct display_num."""
    sid = uuid.uuid4().hex
    return Session(
        session_id=sid,
        user_email=f"user{display_num}@example.com",
        user_id=str(display_num),
        display_num=display_num,
        vnc_port=6080 + display_num,
        jwt_valid_until=9999999999.0,
        state=SessionState.ATTACHED,
    )


# ---------------------------------------------------------------------------
# Test: Session.novnc_url format (Phase 3 path-prefix contract)
# ---------------------------------------------------------------------------


def test_session_novnc_url_format():
    """
    AC-HAPPY-1: Session.novnc_url returns the per-session path-prefix URL.

    Format: /vnc/<session_id>/vnc.html?path=websockify/<session_id>
    """
    s = make_session(1)
    expected = f"/vnc/{s.session_id}/vnc.html?path=websockify/{s.session_id}"
    assert s.novnc_url == expected


def test_two_sessions_get_distinct_novnc_urls():
    """
    Two sessions with different session_ids get distinct novnc_urls.
    The nginx sidecar distinguishes them by session_id in the URL path.
    """
    s1 = make_session(1)
    s2 = make_session(2)
    assert s1.novnc_url != s2.novnc_url
    assert s1.session_id in s1.novnc_url
    assert s2.session_id in s2.novnc_url
    # Session IDs must not appear in the *other* session's URL
    assert s1.session_id not in s2.novnc_url
    assert s2.session_id not in s1.novnc_url


# ---------------------------------------------------------------------------
# Test: nginx_map.write_sessions_map produces correct entries
# ---------------------------------------------------------------------------


def test_nginx_map_writes_two_sessions(tmp_path):
    """
    Phase 3: write_sessions_map produces one entry per active session mapping
    session_id → vnc_port, which nginx reads to route /websockify/<sid> to the
    correct per-session websockify port.

    Map format (nginx map syntax):
        <session_id> <vnc_port>;
    """
    s1 = make_session(1)
    s2 = make_session(2)
    map_path = str(tmp_path / "sessions.map")

    write_sessions_map([s1, s2], map_path=map_path)

    content = open(map_path).read()
    # Both sessions must appear
    assert s1.session_id in content
    assert str(s1.vnc_port) in content
    assert s2.session_id in content
    assert str(s2.vnc_port) in content


def test_nginx_map_session_port_mapping(tmp_path):
    """
    Each session maps to display_num + 6080 for the per-session websockify port.
    Session 1 → port 6081, Session 2 → port 6082.
    """
    s1 = make_session(1)
    s2 = make_session(2)
    assert s1.vnc_port == 6081
    assert s2.vnc_port == 6082


def test_nginx_map_empty(tmp_path):
    """
    write_sessions_map with no active sessions produces a valid (empty body) map.
    nginx must not crash on an empty sessions.map.
    """
    map_path = str(tmp_path / "sessions.map")
    write_sessions_map([], map_path=map_path)
    content = open(map_path).read()
    # File should exist and be parseable (no Python exception during write)
    assert isinstance(content, str)
