"""
vQA — API Key Authentication Middleware (Phase 5D; Phase 2 session extension)
==============================================================================
Module: backend/api/auth_middleware.py

FastAPI dependency that protects endpoints with API key authentication.

When ``API_AUTH_ENABLED=true``, all endpoints except ``/health``,
``/docs``, ``/openapi.json``, and ``/redoc`` require a valid
``X-VQA-API-Key`` header.

Phase 2 extension (per-user-session-isolation):
  ``populate_session_state`` is a lightweight FastAPI dependency that reads
  the vqa_session cookie and sets ``request.state.session`` to the matching
  Session object (or None).

Usage
-----
    # In routes.py:
    from backend.api.auth_middleware import verify_api_key

    @router.post("/execute", dependencies=[Depends(verify_api_key)])
    async def execute(...): ...

    # Or apply globally via middleware (see apply_auth_middleware)

Configuration
-------------
    API_AUTH_ENABLED=true
    API_KEYS=key1,key2,key3

See Also
--------
  - ``backend/config.py``       — api_keys and api_auth_enabled settings
  - ``backend/api/routes.py``   — applies this middleware
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# Header name for API key
_API_KEY_HEADER = APIKeyHeader(name="X-VQA-API-Key", auto_error=False)

# Bearer token for SSO
_BEARER_AUTH = HTTPBearer(auto_error=False)

# Paths that are always accessible without authentication
_PUBLIC_PATHS: set[str] = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/auth/login",
    # Same paths with /api prefix (router is mounted at /api)
    "/api/health",
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc",
    "/api/auth/login",
}


def _get_valid_keys() -> set[str]:
    """
    Get the set of valid API keys from config.

    Lazily imported to avoid circular imports at module load time.

    Returns
    -------
    set[str]
        Set of valid, non-empty API key strings.
    """
    try:
        from backend.config import settings

        raw = settings.api_keys
        if not raw:
            return set()
        return {k.strip() for k in raw.split(",") if k.strip()}
    except Exception:
        return set()


def _is_auth_enabled() -> bool:
    """Check if API authentication is enabled."""
    try:
        from backend.config import settings

        return settings.api_auth_enabled
    except Exception:
        return False


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(_API_KEY_HEADER),
    auth: Optional[HTTPAuthorizationCredentials] = Security(_BEARER_AUTH),
    token: Optional[str] = Query(default=None),
) -> Optional[str | object]:
    """
    FastAPI dependency: verify the authentication (API Key or SSO Token).

    When auth is disabled or the path is public, this is a no-op.
    When auth is enabled and both authentication methods fail, raises 401.

    Parameters
    ----------
    request : Request
        The incoming request (used to check the path).
    api_key : str, optional
        Value from the ``X-VQA-API-Key`` header.
    auth : HTTPAuthorizationCredentials, optional
        Bearer token from the ``Authorization`` header.

    Returns
    -------
    str or SsoToken or None
        The validated API key, SsoToken object, or None if auth is not required.

    Raises
    ------
    HTTPException (401)
        If auth is enabled and no valid authentication is provided.
    """
    # Skip auth for public paths
    path = request.url.path.rstrip("/")
    if path in _PUBLIC_PATHS or path.startswith("/ws/"):
        return None

    # Skip auth if not enabled
    if not _is_auth_enabled():
        return None

    # 1. Try SSO Token if enabled
    from backend.config import settings

    if settings.sso_enabled and auth:
        from backend.auth.sso import validator

        sso_token = validator.validate_token(auth.credentials)
        if sso_token:
            return sso_token

    # 2. Try API Key (header or ?token= query param for browser-navigable URLs)
    valid_keys = _get_valid_keys()
    effective_key = api_key or token
    if valid_keys and effective_key and effective_key in valid_keys:
        return effective_key

    # Auth failed
    logger.warning(
        "Rejected request to %s — missing or invalid authentication",
        path,
    )
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid authentication. Provide X-VQA-API-Key or Bearer token.",
    )


async def populate_session_state(request: Request) -> None:
    """
    FastAPI dependency: populate ``request.state.session`` from the vqa_session cookie.

    Phase 2 (per-user-session-isolation): run/execute endpoints use this
    dependency to access the caller's Session without re-parsing the cookie.

    Sets ``request.state.session`` to the matching ``Session`` object, or
    ``None`` if the cookie is absent or the session is not found.

    This is a soft dependency — it does NOT raise on missing/invalid cookie
    (the route handler enforces the session requirement when needed).
    """
    try:
        from backend.auth.cookies import read_session_cookie
        from backend.session import get_session_manager

        session_id = read_session_cookie(request)
        if session_id:
            mgr = get_session_manager()
            request.state.session = mgr.get_session(session_id)
        else:
            request.state.session = None
    except Exception as exc:
        logger.debug("populate_session_state: error reading session: %s", exc)
        request.state.session = None
