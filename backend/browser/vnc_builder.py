"""
vQA — VNC URL Builder
=====================
Module: backend/browser/vnc_builder.py

Handles dynamic construction of noVNC URLs based on request headers
to support remote deployments, proxies, and multi-tenant environments.

Phase 3 (per-user-session-isolation): added ``session_id`` parameter.
When a ``session_id`` is provided and the request is in a production
(HTTPS) context, the returned URL uses the per-session path-prefix
format handled by the in-container nginx sidecar:

    /vnc/<session_id>/vnc.html?path=websockify/<session_id>

Without a ``session_id`` (pre-Phase-4 backward-compat path via the
``__legacy_singleton__`` stub) the legacy global URL is returned as
before, ensuring zero disruption to callers that have not yet been
wired through the SessionManager.

Architecture reference: ADR-3 (nginx multiplexer), ADR-14 (deploy.sh
scoped edits).  The ALB path-prefix rules for ``/vnc/*`` and
``/websockify/*`` are configured in ``deploy.sh`` (Phase 3 update).
"""

import logging

from fastapi import Request

from backend.config import settings

logger = logging.getLogger("vqa.vnc")


class VncUrlBuilder:
    """
    Constructs dynamic noVNC URLs using incoming request headers.

    This ensures that if a user accesses the dashboard at https://vqa.vcreative.net,
    the embedded noVNC iframe points to the correct per-session path
    (Phase 3+) or the legacy global path (pre-Phase-4 backward compat).
    """

    def build_url(
        self,
        request: Request | None = None,
        mode: str = "interactive",
        host_header: str | None = None,
        protocol: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """
        Build a noVNC URL for the given request or provided metadata.

        Args
        ----
        request : Request, optional
            The incoming FastAPI request object.
        mode : str
            The execution mode ('interactive' or 'batch').
        host_header : str, optional
            A pre-resolved host header string (e.g. from state).
        protocol : str, optional
            A pre-resolved protocol string (e.g. from state).
        session_id : str, optional
            The per-user session ID from the SessionManager.  When
            provided and the request is HTTPS (production), the returned
            URL uses the per-session path-prefix format:

                /vnc/<session_id>/vnc.html?path=websockify/<session_id>

            The nginx sidecar maps this path to the correct per-session
            websockify port via /var/run/vqa/sessions.map.

            When absent (pre-Phase-4 backward-compat), the legacy global
            URL is returned (``/vnc.html?...&path=websockify``).

        Returns
        -------
        str | None
            The noVNC URL, or None if not in interactive mode or when
            running on localhost (no local noVNC server).
        """
        if mode != "interactive":
            return None

        # 1. Determine Host
        # Prefer 'external_host' from settings if it's NOT the default 'localhost'
        host = settings.external_host

        # Determine current request host
        curr_host = host_header
        if not curr_host and request:
            # Try to get host from headers (case-insensitive)
            if hasattr(request.headers, "get"):
                curr_host = request.headers.get("host", "") or request.headers.get("Host", "")
            else:
                curr_host = request.headers.get("host", "")

            if curr_host:
                curr_host = curr_host.split(":")[0]

        if host == "localhost" and curr_host and curr_host not in ("localhost", "127.0.0.1"):
            logger.info("VncUrlBuilder: using request host '%s' (external_host is default localhost)", curr_host)
            host = curr_host
        elif host == "localhost":
            logger.debug("VncUrlBuilder: using default localhost")
        else:
            logger.debug("VncUrlBuilder: using configured external_host '%s'", host)

        # 2. Determine Protocol
        # Respect X-Forwarded-Proto for proxies/ALBs
        proto = protocol
        if not proto and request:
            if hasattr(request.headers, "get"):
                proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
            else:
                proto = request.headers.get("x-forwarded-proto")

            if not proto:
                proto = request.url.scheme

        if not proto:
            proto = "http"  # Fallback

        # 3. Localhost guard — noVNC is not available in local dev.
        if host == "localhost":
            logger.debug("VncUrlBuilder: localhost — returning None (no local noVNC server)")
            return None

        # 4. Port (only used for non-HTTPS non-standard-port fallback)
        port = settings.novnc_port

        # 5. Construct URL
        # Phase 3: in production (HTTPS + non-localhost) with a session_id,
        # return the per-session path-prefix URL that the nginx sidecar handles.
        # The ALB forwards /vnc/* and /websockify/* to the container via the
        # path-prefix rules configured in deploy.sh (ADR-3, ADR-14).
        if host != "localhost" and proto == "https":
            if session_id:
                # Per-session path-prefix URL (Phase 3+)
                logger.debug(
                    "VncUrlBuilder: production session URL for session_id=%s", session_id
                )
                return f"/vnc/{session_id}/vnc.html?path=websockify/{session_id}"
            # Legacy global URL (pre-Phase-4 backward-compat)
            return f"https://{host}/vnc.html?autoconnect=true&reconnect=true&path=websockify"

        # Fallback for standard ports (HTTP non-localhost)
        if port in [80, 443]:
            return f"{proto}://{host}/vnc.html"

        return f"{proto}://{host}:{port}/vnc.html"


vnc_builder = VncUrlBuilder()
