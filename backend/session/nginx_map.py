"""
vQA — Nginx Session Map Writer
================================
Module: backend/session/nginx_map.py

Maintains /var/run/vqa/sessions.map — an nginx ``map`` directive source
that routes per-session noVNC/websockify requests to the correct port.

Map format (nginx map variables):
  <session_id>  <vnc_port>;

The nginx sidecar (docker/nginx.conf) reads this file via:
  map $vqa_session_id $backend_port { include /var/run/vqa/sessions.map; }

File writes are atomic: content is written to a temp file alongside the
target and then renamed, so nginx never reads a partial map.

nginx reload:
  After each write the module calls ``nginx -s reload`` (or alternatively
  relies on inotify in the nginx config).  If the reload command fails, the
  write still completes — nginx will reload on the next write or scheduled
  reload, so a brief routing gap is acceptable.

Architecture Notes (ADR-3):
  The nginx sidecar is the in-container multiplexer for /vnc/<sid>/* and
  /websockify/<sid>.  The ALB is configured with a single path-prefix rule
  (``/vnc/*`` and ``/websockify/*``) and is otherwise dumb.  Session-to-port
  routing lives entirely in the container via this map file.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

#: Default path for the nginx session map file inside the container.
_DEFAULT_MAP_PATH = "/var/run/vqa/sessions.map"

_lock = Lock()


def _get_map_path() -> Path:
    """Return the map file path, overrideable via VQA_NGINX_MAP_PATH env var."""
    return Path(os.environ.get("VQA_NGINX_MAP_PATH", _DEFAULT_MAP_PATH))


class NginxSessionMap:
    """
    Atomic writer for the nginx session→port map file.

    Typically used as a module-level singleton (see ``get_nginx_map()``).
    """

    def __init__(self, map_path: Path | None = None) -> None:
        self._map_path = map_path or _get_map_path()
        self._sessions: dict[str, int] = {}  # session_id → vnc_port
        self._lock = Lock()

    def write(self, session_id: str, vnc_port: int) -> None:
        """
        Add or update a session→port mapping and atomically write the map file.
        """
        with self._lock:
            self._sessions[session_id] = vnc_port
            self._write_atomic()

    def remove(self, session_id: str) -> None:
        """
        Remove a session from the map and atomically write the map file.
        """
        with self._lock:
            self._sessions.pop(session_id, None)
            self._write_atomic()

    def _write_atomic(self) -> None:
        """
        Write the current sessions dict to the map file atomically.

        Creates the parent directory if it does not exist.
        Uses a temp file + rename for atomic replacement.
        """
        map_path = self._map_path
        try:
            map_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("nginx_map: could not create parent dir %s: %s", map_path.parent, exc)

        lines = [f"{sid} {port};\n" for sid, port in self._sessions.items()]
        try:
            # Write to a temp file in the same directory for atomic rename
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=map_path.parent,
                prefix=".sessions_map_tmp_",
                delete=False,
            ) as tmp:
                tmp.writelines(lines)
                tmp_path = Path(tmp.name)
            tmp_path.rename(map_path)
            logger.debug("nginx_map: wrote %d entries to %s", len(lines), map_path)
            self._reload_nginx()
        except Exception as exc:
            logger.error("nginx_map: atomic write failed: %s", exc)

    def _reload_nginx(self) -> None:
        """Signal nginx to reload its configuration (pick up the new map)."""
        try:
            result = subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.warning("nginx -s reload returned rc=%d: %s", result.returncode, result.stderr)
        except FileNotFoundError:
            # nginx not installed (e.g., in unit tests or headless dev)
            logger.debug("nginx_map: nginx binary not found — skipping reload")
        except Exception as exc:
            logger.warning("nginx_map: reload failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_nginx_map_instance: NginxSessionMap | None = None
_nginx_map_lock = Lock()


def get_nginx_map() -> NginxSessionMap:
    """Return the module-level NginxSessionMap singleton."""
    global _nginx_map_instance
    if _nginx_map_instance is None:
        with _nginx_map_lock:
            if _nginx_map_instance is None:
                _nginx_map_instance = NginxSessionMap()
    return _nginx_map_instance


# ---------------------------------------------------------------------------
# Convenience helpers for testing and batch reconstruction
# ---------------------------------------------------------------------------


def write_sessions_map(sessions: list, map_path: str | None = None) -> None:
    """
    Atomically write the nginx sessions.map from a list of Session objects.

    Each Session contributes one line:  ``<session_id> <vnc_port>;``

    This is a convenience helper used by:
      - Tests (``tests/test_nginx_multiplex.py``) to verify the map format.
      - ``SessionManager`` on startup / reconciliation to rebuild the map
        from in-memory state.

    Args
    ----
    sessions : list[Session]
        Active Session objects (must have ``session_id`` and ``vnc_port``
        attributes).  Terminated sessions should be excluded by the caller.
    map_path : str, optional
        Override the map file path.  Defaults to ``/var/run/vqa/sessions.map``
        (or the ``VQA_NGINX_MAP_PATH`` env var).
    """
    target = Path(map_path) if map_path else _get_map_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("write_sessions_map: could not create parent dir %s: %s", target.parent, exc)

    lines = [f"{s.session_id} {s.vnc_port};\n" for s in sessions]
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=target.parent,
            prefix=".sessions_map_tmp_",
            delete=False,
        ) as tmp:
            tmp.writelines(lines)
            tmp_path = Path(tmp.name)
        tmp_path.rename(target)
        logger.debug("write_sessions_map: wrote %d entries to %s", len(lines), target)
    except Exception as exc:
        logger.error("write_sessions_map: atomic write failed: %s", exc)
