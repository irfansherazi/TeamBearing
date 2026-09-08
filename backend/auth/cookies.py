"""
vQA — Session Cookie Helpers
==============================
Module: backend/auth/cookies.py

Centralises the HttpOnly/Secure/SameSite=Lax flag logic for the
``vqa_session`` cookie (ADR-4, ADR-11).

The session cookie carries the session_id (an opaque UUID string) that
authenticates all non-JWT endpoints (WebSocket handshakes, /execute*, /session/rebind).

Cookie contract (ADR-11):
  - Issued at ``POST /session/start`` with Max-Age = jwt.exp - now.
  - Re-issued at ``POST /session/rebind`` with Max-Age = new_jwt.exp - now.
  - Without re-issue on rebind, the cookie expires at the original JWT exp
    and the browser drops it — defeating the rebind flow.
  - ``Secure`` is conditional: True in production (HTTPS), False in dev (HTTP).
  - ``SameSite=Lax`` allows normal browser navigation while blocking CSRF.

Usage (FastAPI response)::

    from backend.auth.cookies import issue_session_cookie, read_session_cookie

    # In session/start handler:
    cookie = issue_session_cookie(session_id, max_age=3600, secure=True)
    response.set_cookie(
        key=cookie["name"],
        value=cookie["value"],
        max_age=cookie["max_age"],
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
        path=cookie["path"],
    )

    # In request handlers (reading the cookie):
    session_id = read_session_cookie(request)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: Cookie name — overrideable via SESSION_COOKIE_NAME env var.
_DEFAULT_COOKIE_NAME = "vqa_session"


def _get_cookie_name() -> str:
    return os.environ.get("SESSION_COOKIE_NAME", _DEFAULT_COOKIE_NAME)


def issue_session_cookie(
    session_id: str,
    max_age: int,
    secure: bool,
) -> dict:
    """
    Build the cookie attributes dict for ``Set-Cookie: vqa_session=<session_id>``.

    Parameters
    ----------
    session_id
        The opaque session UUID to store as the cookie value.
    max_age
        ``Max-Age`` seconds (= new_jwt.exp - now at time of issue/rebind).
    secure
        If True, the ``Secure`` flag is set (required for HTTPS / production).
        If False (local HTTP dev), the flag is omitted so the browser accepts it.

    Returns
    -------
    dict
        Keyword-argument dict suitable for ``response.set_cookie(**cookie)``.
        Fields: name, value, max_age, httponly, secure, samesite, path.
    """
    return {
        "name": _get_cookie_name(),
        "value": session_id,
        "max_age": max_age,
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
    }


def read_session_cookie(request) -> Optional[str]:
    """
    Extract the session_id from the incoming request's vqa_session cookie.

    Works with both FastAPI ``Request`` objects and plain dicts (for testing).

    Parameters
    ----------
    request
        A FastAPI ``Request`` (has ``.cookies`` dict-like) or a plain dict.

    Returns
    -------
    str or None
        The session_id string, or None if the cookie is absent.
    """
    cookie_name = _get_cookie_name()
    try:
        if hasattr(request, "cookies"):
            return request.cookies.get(cookie_name)
        if isinstance(request, dict):
            return request.get("cookies", {}).get(cookie_name)
    except Exception as exc:
        logger.warning("read_session_cookie: error reading cookie: %s", exc)
    return None
