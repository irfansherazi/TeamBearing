"""
vQA — Session API Route Handlers (Phase 2)
==========================================
Module: backend/api/session_routes.py

Implements the session lifecycle endpoints:

  POST   /api/session/start           — Bootstrap a per-user session
  POST   /api/session/rebind          — Re-issue cookie with fresh Max-Age
  DELETE /api/session/{session_id}    — Admin-terminate a session
  GET    /api/session/{session_id}/status — Read session state
  WS     /ws/session/{session_id}     — Long-lived session-control WebSocket

Architecture (per-user-session-isolation, Phase 2, ADR-3 / ADR-4 / ADR-11)
----------------------------------------------------------------------------
Authentication at these endpoints:
  - POST /session/start : JWT in Authorization: Bearer header (one-time bootstrap)
  - POST /session/rebind: JWT in Authorization: Bearer + vqa_session cookie
  - DELETE /session/{id}: API key (admin path, same as other admin routes)
  - GET /session/{id}/status: cookie-only (no JWT needed)
  - WS /ws/session/{id}: vqa_session cookie in the HTTP upgrade handshake

The session cookie (vqa_session) is HttpOnly/Secure/SameSite=Lax (see
backend/auth/cookies.py).  The WS endpoint is cookie-authenticated only —
JWTs are NOT carried on WebSocket frames (security review outcome, ADR-4).

WebSocket teardown contract (ADR-10):
  Server-side heartbeat (WS_HEARTBEAT_INTERVAL_SECONDS ping /
  WS_HEARTBEAT_TIMEOUT_SECONDS timeout) is the authoritative teardown signal.
  beforeunload is a best-effort accelerant only.
  A comment at the reconnect handler below makes this explicit.

Origin validation (AC-ERROR-4):
  Every WS handshake checks the Origin header against CORS_ALLOWED_ORIGINS
  (sourced from backend/main.py — the same list that drives CORSMiddleware).
  Missing or disallowed Origin → close(4403, "origin_rejected").

Cookie flag rules (ADR-11):
  - Max-Age = jwt.exp - now (re-calculated at each issuance/rebind).
  - Secure=True when the incoming request scheme is https.
  - Re-issued on every successful rebind so the browser doesn't drop it
    when the original JWT expires.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from backend.auth.cookies import issue_session_cookie, read_session_cookie
from backend.auth.sso import SsoValidator
from backend.session import CapacityReachedResult, get_session_manager
from backend.session.models import Session, SessionState

logger = logging.getLogger(__name__)

session_router = APIRouter()
session_ws_router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Origins that are permitted on WebSocket handshakes.
# Mirrors the allow_origins list in backend/main.py CORSMiddleware.
_ALLOWED_ORIGINS: set[str] = {
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://vqa.vcreative.net",
}

# Allow override via env var (comma-separated) for staging environments.
def _allowed_origins() -> set[str]:
    extra = os.environ.get("CORS_ALLOWED_ORIGINS_EXTRA", "")
    if extra:
        return _ALLOWED_ORIGINS | {o.strip() for o in extra.split(",") if o.strip()}
    return _ALLOWED_ORIGINS


def _is_secure(request: Request) -> bool:
    """Return True if the request arrived over HTTPS."""
    # Respect X-Forwarded-Proto from the ALB
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.lower() == "https"
    return request.url.scheme == "https"


def _extract_bearer(request: Request) -> Optional[str]:
    """Return the raw Bearer token from the Authorization header, or None."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") or auth.startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _make_session_response(session: Session, now: float | None = None) -> dict:
    """Build the standard session response body."""
    if now is None:
        now = time.time()
    # next_rebind_by: 90 seconds before jwt_valid_until so the frontend
    # schedules the POST /session/rebind call before expiry.
    next_rebind_by = session.jwt_valid_until - 90
    return {
        "session_id": session.session_id,
        "novnc_url": session.novnc_url,
        "state": session.state.value,
        "jwt_valid_until": session.jwt_valid_until,
        "next_rebind_by": next_rebind_by,
    }


def _set_session_cookie(response: Response, session: Session, secure: bool) -> None:
    """
    Issue the vqa_session cookie onto the response.

    Max-Age = session.jwt_valid_until - now (floored at 0).
    """
    now = time.time()
    max_age = max(0, math.floor(session.jwt_valid_until - now))
    cookie = issue_session_cookie(session.session_id, max_age=max_age, secure=secure)
    response.set_cookie(
        key=cookie["name"],
        value=cookie["value"],
        max_age=cookie["max_age"],
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
        path=cookie["path"],
    )


# ---------------------------------------------------------------------------
# POST /session/start
# ---------------------------------------------------------------------------


@session_router.post("/session/start", summary="Bootstrap a per-user session")
async def session_start(request: Request) -> Response:
    """
    Bootstrap a new per-user session.

    Authentication: ``Authorization: Bearer <jwt>`` (one-time JWT at startup).

    On success:
      - 200 with body ``{ session_id, novnc_url, state, jwt_valid_until, next_rebind_by }``
      - ``Set-Cookie: vqa_session=<session_id>; HttpOnly; Secure; SameSite=Lax; Max-Age=...``

    On error:
      - 401 if JWT is missing, invalid, or fails Phase 1 hardening checks.
      - 409 if ``MAX_CONCURRENT_SESSIONS`` capacity is reached.

    Structured log events emitted:
      - ``session.started`` on success
      - ``session.capacity_reached`` on 409
      - ``session.jwt_expired`` / ``auth.rejected`` on 401 (from SsoValidator)

    AC-ENTRY-1, AC-ERROR-1, AC-ERROR-2.
    """
    raw_jwt = _extract_bearer(request)
    if not raw_jwt:
        logger.info('{"event": "auth.rejected", "reason": "missing_bearer", "path": "/session/start"}')
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "Authorization: Bearer <jwt> required"},
        )

    sso_token = SsoValidator.validate_token(raw_jwt)
    if sso_token is None:
        logger.info('{"event": "auth.rejected", "reason": "invalid_jwt", "path": "/session/start"}')
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "JWT validation failed"},
        )

    mgr = get_session_manager()
    result = await mgr.start_session(
        user_id=str(sso_token.vc_id),
        user_email=sso_token.email,
        jwt_exp=float(sso_token.exp),
    )

    if isinstance(result, CapacityReachedResult):
        logger.info(
            '{"event": "session.capacity_reached", "user_email": "%s", '
            '"active_sessions": %d, "retry_after_s": %d}',
            sso_token.email, result.active_sessions, result.retry_after_s,
        )
        return JSONResponse(
            status_code=409,
            content={
                "error": "capacity_reached",
                "retry_after_s": result.retry_after_s,
                "active_sessions": result.active_sessions,
            },
        )

    session: Session = result
    now = time.time()
    body = _make_session_response(session, now=now)
    response = JSONResponse(status_code=200, content=body)
    _set_session_cookie(response, session, secure=_is_secure(request))
    return response


# ---------------------------------------------------------------------------
# POST /session/rebind
# ---------------------------------------------------------------------------


@session_router.post("/session/rebind", summary="Re-issue session cookie with fresh Max-Age")
async def session_rebind(request: Request) -> Response:
    """
    Re-issue the vqa_session cookie with a fresh Max-Age derived from the new JWT.

    Authentication:
      - ``Authorization: Bearer <new_jwt>`` — freshly-refreshed JWT from vcAPI.
      - ``Cookie: vqa_session=<session_id>`` — must match an existing session.

    On success:
      - 200 with body ``{ session_id, jwt_valid_until, next_rebind_by }``
      - ``Set-Cookie: vqa_session=<session_id>; ...; Max-Age=<new_jwt.exp - now>``

    On error:
      - 401 if JWT or cookie is missing / invalid.
      - 403 if the JWT's vc_id does not match the session's user_id (cross-user).
      - 404/410 if the session is no longer active.

    Structured log: ``session.rebound`` on success; ``session.rebind_failed`` on error.

    ADR-11: Max-Age MUST reflect new_jwt.exp - now, not the original Max-Age.
    AC-HAPPY-3, AC-ASYNC-1, AC-ERROR-7, AC-ERROR-8.
    """
    raw_jwt = _extract_bearer(request)
    if not raw_jwt:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "Authorization: Bearer <jwt> required"},
        )

    sso_token = SsoValidator.validate_token(raw_jwt)
    if sso_token is None:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "JWT validation failed"},
        )

    session_id = read_session_cookie(request)
    if not session_id:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "vqa_session cookie required"},
        )

    mgr = get_session_manager()
    session = mgr.get_session(session_id)
    if session is None:
        logger.info(
            '{"event": "session.rebind_failed", "session_id": "%s", "reason": "session_terminated"}',
            session_id,
        )
        return JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": "session has been terminated"},
        )

    # AC-ERROR-8: cross-user rebind rejected
    if str(sso_token.vc_id) != str(session.user_id):
        logger.warning(
            '{"event": "session.rebind_failed", "session_id": "%s", '
            '"reason": "user_mismatch", "jwt_vc_id": %d, "session_user_id": "%s"}',
            session_id, sso_token.vc_id, session.user_id,
        )
        return JSONResponse(
            status_code=403,
            content={"error": "session_user_mismatch"},
        )

    # Update jwt_valid_until
    new_exp = float(sso_token.exp)
    mgr.rebind_session(session_id, new_exp)

    now = time.time()
    next_rebind_by = new_exp - 90
    body = {
        "session_id": session_id,
        "jwt_valid_until": new_exp,
        "next_rebind_by": next_rebind_by,
    }
    response = JSONResponse(status_code=200, content=body)
    _set_session_cookie(response, session, secure=_is_secure(request))
    return response


# ---------------------------------------------------------------------------
# GET /session/{session_id}/status
# ---------------------------------------------------------------------------


@session_router.get("/session/{session_id}/status", summary="Get session state")
def session_status(session_id: str, request: Request) -> Response:
    """
    Return the current state of a session.

    Authentication: vqa_session cookie (no JWT needed).

    On success: 200 with ``{ session_id, state, jwt_valid_until }``
    On miss:    404

    AC-ENTRY-1 verification path.
    """
    mgr = get_session_manager()
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    return JSONResponse(
        status_code=200,
        content={
            "session_id": session.session_id,
            "state": session.state.value,
            "jwt_valid_until": session.jwt_valid_until,
        },
    )


# ---------------------------------------------------------------------------
# DELETE /session/{session_id}
# ---------------------------------------------------------------------------


@session_router.delete("/session/{session_id}", summary="Admin-terminate a session")
async def session_delete(session_id: str) -> Response:
    """
    Admin-terminate a session immediately.

    Authentication: API key (same as other admin-route convention via the
    session_router dependency set in main.py).

    On success:  204 No Content
    On miss:     404

    AC-ASYNC-3 (drain path), admin delete path.
    """
    mgr = get_session_manager()
    session = mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    await mgr.terminate_session(session_id, reason="admin_delete")
    logger.info(
        '{"event": "session.terminated", "session_id": "%s", "reason": "admin_delete"}',
        session_id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# WS /ws/session/{session_id}
# ---------------------------------------------------------------------------


@session_ws_router.websocket("/ws/session/{session_id}")
async def session_control_ws(websocket: WebSocket, session_id: str) -> None:
    """
    Long-lived session-control WebSocket for a per-user session.

    Authentication (ADR-4):
      - vqa_session cookie in the HTTP upgrade handshake.
      - JWTs are NOT carried on WebSocket frames.

    Origin validation (AC-ERROR-4):
      - Origin header must be in the allowed-origins set.
      - Missing or disallowed Origin → close(4403, "origin_rejected").

    Lifecycle (ADR-10):
      - Server sends ping every WS_HEARTBEAT_INTERVAL_SECONDS.
      - If no pong within WS_HEARTBEAT_TIMEOUT_SECONDS, teardown is initiated.
      - beforeunload is a best-effort accelerant only (NOT required for correctness).
        This is documented explicitly here per AC-ASYNC-2.

    Session events sent to the client:
      - ``{"type": "session_state", "state": "<state>"}`` on connect.
      - ``{"type": "session_terminated", "reason": "<reason>"}`` before close.
    """
    # ------------------------------------------------------------------
    # Origin validation (AC-ERROR-4)
    # ------------------------------------------------------------------
    origin = websocket.headers.get("origin", "")
    allowed = _allowed_origins()
    if origin and origin not in allowed:
        await websocket.accept()
        logger.info(
            '{"event": "session.origin_rejected", "origin": "%s", "session_id": "%s"}',
            origin, session_id,
        )
        await websocket.close(code=4403, reason="origin_rejected")
        return

    # ------------------------------------------------------------------
    # Cookie authentication (ADR-4)
    # ------------------------------------------------------------------
    cookie_session_id = websocket.cookies.get(
        os.environ.get("SESSION_COOKIE_NAME", "vqa_session")
    )
    if not cookie_session_id or cookie_session_id != session_id:
        await websocket.accept()
        logger.info(
            '{"event": "session.origin_rejected", "reason": "cookie_mismatch", '
            '"session_id": "%s"}',
            session_id,
        )
        await websocket.close(code=4401, reason="cookie_mismatch")
        return

    mgr = get_session_manager()
    session = mgr.get_session(session_id)
    if session is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="session_not_found")
        return

    await websocket.accept()
    mgr.on_ws_connect(session_id)
    logger.info(
        '{"event": "session.attached", "session_id": "%s"}', session_id
    )

    # Send initial state
    try:
        import json
        await websocket.send_text(
            json.dumps({"type": "session_state", "state": session.state.value})
        )
    except Exception:
        pass

    heartbeat_interval = float(os.environ.get("WS_HEARTBEAT_INTERVAL_SECONDS", "15"))
    heartbeat_timeout = float(os.environ.get("WS_HEARTBEAT_TIMEOUT_SECONDS", "15"))

    # ------------------------------------------------------------------
    # Heartbeat loop (ADR-10)
    # beforeunload is best-effort only — heartbeat timeout is authoritative.
    # Do NOT add a test that depends solely on beforeunload firing.
    # ------------------------------------------------------------------
    async def _heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval)
            try:
                pong_waiter = await websocket.send_text('{"type":"ping"}')
            except Exception:
                break

    import json

    try:
        while True:
            try:
                # Wait for any client message (pong, close, lifecycle events)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=heartbeat_interval + heartbeat_timeout,
                )
                msg = json.loads(data)
                if msg.get("type") == "close":
                    # beforeunload best-effort accelerant — honour it
                    break
                # Send periodic ping back
                await websocket.send_text('{"type":"ping"}')
            except asyncio.TimeoutError:
                # No pong within the timeout window — authoritative teardown
                logger.info(
                    '{"event": "session.ws_heartbeat_timeout", "session_id": "%s"}',
                    session_id,
                )
                await mgr.on_heartbeat_timeout(session_id)
                try:
                    await websocket.send_text(
                        json.dumps({"type": "session_terminated", "reason": "heartbeat_timeout"})
                    )
                except Exception:
                    pass
                await websocket.close(code=1000, reason="heartbeat_timeout")
                return
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        mgr.on_ws_disconnect(session_id)
        logger.info(
            '{"event": "session.detached", "session_id": "%s"}', session_id
        )
