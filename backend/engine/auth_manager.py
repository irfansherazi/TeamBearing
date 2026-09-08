"""
vQA — Role-Based Authentication Manager
==========================================
Module: backend/engine/auth_manager.py

Manages Playwright storage-state files for every vProMedia role so that the
browser-use ``web_surfer.py`` node can launch sessions that are already
authenticated — no login form interaction required during regression runs.

Architecture
------------
::

    AuthManager(role_name)
        │
        ├─ resolve_credentials()   ← backend/engine/roles.py (KB → env → fallback)
        │
        ├─ get_state_path()        → memory/auth_states/{role_key}_state.json
        │
        ├─ is_state_valid()        → checks file age against AUTH_STATE_TTL_HOURS
        │
        └─ ensure_authenticated()
               │
               ├─ (state exists & fresh) → return state_path immediately
               │
               └─ (missing / expired)   → _perform_login()
                       │
                       ├─ playwright.sync_api
                       ├─ navigate target_url
                       ├─ fill email + password
                       ├─ click submit
                       ├─ poll localStorage.vc2JWT (up to 10 s)
                       ├─ context.storage_state(path=state_path)
                       └─ return state_path

Credential Sources (in priority order)
---------------------------------------
1. Bedrock Roles KB (``JXMMTMTI06``) — queried at ``roles.py`` module load
2. ``ROLE_EMAIL_*`` / ``ROLE_DEFAULT_PASSWORD`` environment variables
3. Hardcoded imail-test fallbacks in ``roles.py``

No credentials are stored in this file.

Auth State Files
----------------
    memory/auth_states/
    ├── account_executive_state.json
    ├── producer_state.json
    └── …

Each file is a Playwright ``BrowserContext.storage_state()`` dump containing:
  - ``cookies``      — session cookies (used across HTTP requests)
  - ``origins``      — ``localStorage`` entries including ``vc2JWT``

TTL & Expiry
------------
Default TTL: 4 hours (configurable via ``AUTH_STATE_TTL_HOURS`` env var).
On TTL expiry the manager silently re-authenticates and overwrites the file.

Usage
-----
    from backend.engine.auth_manager import AuthManager

    manager = AuthManager("account_executive")
    state_path = manager.ensure_authenticated()
    # Pass state_path to BrowserConfig(storage_state=state_path)

    # Or use the functional shortcut:
    from backend.engine.auth_manager import ensure_role_authenticated
    state_path = ensure_role_authenticated("producer")

Configuration (env / .env)
--------------------------
    AUTH_STATE_TTL_HOURS   Hours before a state file is considered expired (default: 4)
    AUTH_STATE_DIR         Override the storage directory (default: memory/auth_states)
    AUTH_LOGIN_TIMEOUT_MS  Playwright timeout for page operations in ms (default: 30000)
    AUTH_JWT_POLL_MS       Polling interval while waiting for JWT (default: 500)
    AUTH_JWT_MAX_POLLS     Max polls before giving up on JWT (default: 20, i.e. 10 s)
    AUTH_LOGIN_URL         Override login URL (default: settings.target_url)
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants (env-overridable)
# ---------------------------------------------------------------------------

#: Hours a storage-state file is considered fresh before forcing re-login
AUTH_STATE_TTL_HOURS: Final[float] = float(os.getenv("AUTH_STATE_TTL_HOURS", "4"))

#: Playwright timeout for page.goto / form operations (milliseconds)
_LOGIN_TIMEOUT_MS: Final[int] = int(os.getenv("AUTH_LOGIN_TIMEOUT_MS", "30000"))

#: Polling interval while waiting for vc2JWT to appear in localStorage
_JWT_POLL_MS: Final[int] = int(os.getenv("AUTH_JWT_POLL_MS", "500"))

#: Maximum number of JWT polls before aborting login (default 20 × 500 ms = 10 s)
_JWT_MAX_POLLS: Final[int] = int(os.getenv("AUTH_JWT_MAX_POLLS", "20"))

#: Default auth-state storage directory
_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_STATE_DIR = _VQAROOT / "memory" / "auth_states"
_STATE_DIR: Final[Path] = Path(os.getenv("AUTH_STATE_DIR", str(_DEFAULT_STATE_DIR)))

#: Key written by vSuite Angular app to localStorage after login
_JWT_STORAGE_KEY: Final[str] = "vc2JWT"

#: Metadata sidecar filename suffix (stored alongside the Playwright state JSON)
_META_SUFFIX: Final[str] = ".meta.json"


# ---------------------------------------------------------------------------
# Credential resolution (thin wrapper around ROLE_REGISTRY)
# ---------------------------------------------------------------------------


def _resolve_role_credentials(role_key: str) -> dict[str, str]:
    """
    Fetch email + password for ``role_key`` from the vQA ROLE_REGISTRY.

    Internally calls ``backend.engine.roles.get_role_context()`` which
    already implements the three-tier KB → env → fallback resolution chain.

    Args
    ----
    role_key : str
        One of the keys in ``ROLE_REGISTRY`` (e.g. ``"account_executive"``).
        Aliases like ``"ae"`` are NOT accepted here — pass the canonical key.

    Returns
    -------
    dict[str, str]
        Dict with keys ``"email"``, ``"password"``, and ``"role_name"``.

    Raises
    ------
    KeyError
        If ``role_key`` is not in the ROLE_REGISTRY.
    ValueError
        If the resolved email is empty (credentials not configured).
    """
    # Lazy import to avoid circular imports at module level
    from backend.engine.roles import ROLE_ALIASES, ROLE_REGISTRY

    # Accept aliases transparently (e.g. "ae" → "account_executive")
    normalized = role_key.strip().lower()
    canonical_key = ROLE_ALIASES.get(normalized, normalized)

    if canonical_key not in ROLE_REGISTRY:
        raise KeyError(
            f"AuthManager: unknown role_key or alias '{role_key}'. Supported roles: {list(ROLE_REGISTRY.keys())}"
        )

    ctx = ROLE_REGISTRY[canonical_key]
    email: str = ctx.get("login_email", "") or ""
    password: str = ctx.get("login_password", "") or ""

    if not email:
        raise ValueError(
            f"AuthManager: role '{canonical_key}' has no configured email. "
            f"Check ROLE_EMAIL_* env vars or the Bedrock Roles KB."
        )
    if not password:
        raise ValueError(
            f"AuthManager: role '{canonical_key}' has no configured password. Set ROLE_DEFAULT_PASSWORD in .env or SSM."
        )

    return {
        "email": email,
        "password": password,
        "role_name": ctx.get("role_name", canonical_key),
        "role_key": canonical_key,
    }


# ---------------------------------------------------------------------------
# State file metadata helpers
# ---------------------------------------------------------------------------


def _meta_path(state_path: Path) -> Path:
    """Return the sidecar metadata path for a given state JSON path."""
    return state_path.parent / (state_path.name + _META_SUFFIX)


def _write_meta(state_path: Path, role_key: str, email: str) -> None:
    """
    Write a JSON sidecar next to the Playwright storage-state file.

    The sidecar records when the state was captured and which email was
    authenticated, so ``is_state_valid()`` can read TTL without parsing
    the full Playwright state blob.

    Args
    ----
    state_path : Path
        Path to the Playwright state file.
    role_key : str
        The role key that was authenticated.
    email : str
        The email address used for login (partial, for logs only).
    """
    meta = {
        "role_key": role_key,
        "email": email,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": AUTH_STATE_TTL_HOURS,
    }
    try:
        _meta_path(state_path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "AuthManager: failed to write metadata sidecar for '%s': %s",
            state_path.name,
            exc,
        )


def _read_meta(state_path: Path) -> dict | None:
    """
    Read the sidecar metadata for ``state_path``.

    Returns ``None`` if the sidecar is missing or malformed.
    """
    mp = _meta_path(state_path)
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Core AuthManager class
# ---------------------------------------------------------------------------


class AuthManager:
    """
    Role-based authentication state manager for the browser-use web surfer.

    Creates and maintains Playwright ``storage_state`` JSON files for each
    vProMedia role.  Callers call ``ensure_authenticated()`` which guarantees
    a fresh state file exists before browser-use launches.

    Parameters
    ----------
    role_name : str
        A canonical role key (``"account_executive"``) or any alias defined
        in ``ROLE_ALIASES`` (``"ae"``, ``"demo ae"``, etc.).
    login_url : str | None
        The URL of the application login page.  Defaults to
        ``settings.target_url`` if not provided.
    headless : bool
        Whether the Playwright auto-login browser runs headlessly.
        Override to ``False`` to debug login flows visually.

    Example
    -------
    >>> manager = AuthManager("producer")
    >>> state_path = manager.ensure_authenticated()
    >>> print(state_path)
    /path/to/vQA/memory/auth_states/producer_state.json
    """

    def __init__(
        self,
        role_name: str,
        *,
        login_url: str | None = None,
        headless: bool = True,
    ) -> None:
        self._role_input = role_name

        # Resolve canonical key + credentials immediately so auth errors
        # surface at construction time, not buried inside ensure_authenticated.
        self._creds = _resolve_role_credentials(role_name)
        self._role_key: str = self._creds["role_key"]
        self._role_display: str = self._creds["role_name"]

        # Login page URL
        if login_url:
            self._login_url = login_url
        else:
            try:
                from backend.config import settings as _settings

                self._login_url = _settings.target_url or os.getenv("AUTH_LOGIN_URL", "https://two-test.vcreative.net")
            except Exception:
                self._login_url = os.getenv("AUTH_LOGIN_URL", "https://two-test.vcreative.net")

        # Namespace the state file by URL host so per-env caches don't collide
        # (e.g. two-test.vcreative.net vs. localhost:4200 for the same role).
        from urllib.parse import urlparse as _urlparse

        _parsed = _urlparse(self._login_url)
        _host_raw = (_parsed.netloc or _parsed.path or "").strip().lower()
        # Filesystem-safe: replace ':' (port separator) and any path chars
        self._url_host_key: str = re.sub(r"[^a-z0-9._-]", "_", _host_raw) or "default"

        self._headless = headless

        # Ensure the auth_states directory exists
        _STATE_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "AuthManager: initialised for role '%s' (%s) — login_url=%s",
            self._role_key,
            self._role_display,
            self._login_url,
        )

    # ── State path ─────────────────────────────────────────────────────────

    @property
    def state_path(self) -> Path:
        """
        Absolute path to the Playwright storage-state JSON file for this role.

        Format: ``memory/auth_states/{role_key}__{url_host}_state.json``. The
        URL-host suffix keeps per-env caches separate (a login against
        ``two-test.vcreative.net`` won't clobber a login against
        ``localhost_4200`` for the same role). Falls back to the legacy
        unsuffixed name if a pre-existing state file is present without the
        host suffix, so we don't force a re-login on the first upgrade.
        """
        suffixed = _STATE_DIR / f"{self._role_key}__{self._url_host_key}_state.json"
        if suffixed.exists():
            return suffixed
        legacy = _STATE_DIR / f"{self._role_key}_state.json"
        # Prefer the suffixed path for new writes; use legacy only if it's the
        # only one present AND the login_url matches the historical default.
        if legacy.exists() and self._url_host_key in {"two-test.vcreative.net", "default"}:
            return legacy
        return suffixed

    # ── Validity check ──────────────────────────────────────────────────────

    def is_state_valid(self) -> bool:
        """
        Return True if a usable, non-expired auth state file exists.

        Validity criteria (ALL must pass):
        1. The .json file exists and is non-empty.
        2. The sidecar .meta.json exists and parses successfully.
        3. ``captured_at`` + TTL_HOURS is still in the future.
        4. (Soft check) The state JSON has ``cookies`` or ``origins`` keys,
           confirming it's a legitimate Playwright storage_state dump.

        Returns
        -------
        bool
        """
        sp = self.state_path
        if not sp.exists() or sp.stat().st_size < 10:
            logger.debug(
                "AuthManager [%s]: state file missing or empty at %s",
                self._role_key,
                sp,
            )
            return False

        # Read sidecar metadata for TTL check
        meta = _read_meta(sp)
        if meta is None:
            # No sidecar → treat as expired (legacy or corrupted state)
            logger.debug(
                "AuthManager [%s]: no metadata sidecar — treating state as expired",
                self._role_key,
            )
            return False

        captured_at_str: str = meta.get("captured_at", "")
        if not captured_at_str:
            return False

        try:
            captured_at = datetime.fromisoformat(captured_at_str)
        except ValueError:
            logger.warning(
                "AuthManager [%s]: unparseable captured_at '%s' in sidecar — refreshing",
                self._role_key,
                captured_at_str,
            )
            return False

        ttl = timedelta(hours=AUTH_STATE_TTL_HOURS)
        now = datetime.now(timezone.utc)
        # Ensure captured_at is timezone-aware for comparison
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)

        expires_at = captured_at + ttl
        if now >= expires_at:
            logger.info(
                "AuthManager [%s]: state expired at %s (TTL=%.1fh) — will re-authenticate",
                self._role_key,
                expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                AUTH_STATE_TTL_HOURS,
            )
            return False

        # Soft structural check — peek at the JSON content
        try:
            with sp.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            has_cookies = bool(payload.get("cookies"))
            has_origins = bool(payload.get("origins"))
            if not has_cookies and not has_origins:
                logger.warning(
                    "AuthManager [%s]: state JSON has neither cookies nor origins — refreshing",
                    self._role_key,
                )
                return False
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "AuthManager [%s]: state JSON unreadable (%s) — refreshing",
                self._role_key,
                exc,
            )
            return False

        remaining = expires_at - now
        logger.info(
            "AuthManager [%s]: state is VALID — expires in %.0f min",
            self._role_key,
            remaining.total_seconds() / 60,
        )
        return True

    # ── Public entry point ──────────────────────────────────────────────────

    def ensure_authenticated(self) -> str:
        """
        Guarantee that a valid auth state file exists and return its path.

        If the state file is present and within TTL, this is a fast no-op
        (sub-millisecond).  If it is missing or expired, a synchronous
        Playwright login flow is triggered — typically 3−8 seconds.

        Returns
        -------
        str
            Absolute path string to ``memory/auth_states/{role_key}_state.json``,
            ready to pass as ``storage_state=`` in BrowserConfig.

        Raises
        ------
        RuntimeError
            If Playwright login fails (wrong credentials, unreachable URL,
            JWT never appears in localStorage).
        """
        if self.is_state_valid():
            logger.info(
                "AuthManager [%s]: reusing cached state — %s",
                self._role_key,
                self.state_path,
            )
            return str(self.state_path)

        logger.info(
            "AuthManager [%s]: state missing/expired — performing Playwright login …",
            self._role_key,
        )
        self._perform_login()
        logger.info(
            "AuthManager [%s]: login complete — state saved to %s",
            self._role_key,
            self.state_path,
        )
        return str(self.state_path)

    # ── Login implementation ────────────────────────────────────────────────

    def _perform_login(self) -> None:
        """
        Silently log in as this role via ``playwright.sync_api`` and save
        the Playwright ``BrowserContext.storage_state()`` to disk.

        Login flow (mirrors ``login_node`` in ``graph.py``):
        1.  Launch a Chromium browser (headed or headless per ``self._headless``).
        2.  Navigate to ``self._login_url`` and wait for networkidle.
        3.  Check if ``vc2JWT`` is ALREADY in localStorage (reuse without form fill).
        4.  Wait for the email textbox to appear (up to ``_LOGIN_TIMEOUT_MS`` ms).
        5.  Fill email, fill password.
        6.  Click the login button (tries role=button "Log In", "Login", "Sign In",
            and finally ``button[type=submit]``).
        7.  Wait for networkidle post-click.
        8.  Poll ``localStorage.vc2JWT`` up to ``_JWT_MAX_POLLS × _JWT_POLL_MS`` ms.
        9.  If JWT found: call ``context.storage_state(path=…)`` + write sidecar.
        10. Raise ``RuntimeError`` if JWT is never found.

        Raises
        ------
        RuntimeError
            Login failed — JWT not detected within the polling budget.
        ImportError
            ``playwright`` package is not installed.
        """
        try:
            from playwright.sync_api import TimeoutError as PWTimeout
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "AuthManager._perform_login: 'playwright' is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ) from exc

        email: str = self._creds["email"]
        password: str = self._creds["password"]

        logger.info(
            "AuthManager [%s]: launching Playwright browser to login as %s …",
            self._role_key,
            email[:30] + ("…" if len(email) > 30 else ""),
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self._headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                # Disable all security features that might interfere with
                # the Angular app's cookie handling in test environments
                ignore_https_errors=True,
                # Reasonable viewport to avoid responsive-layout issues
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()

            try:
                # ── Step 1: Navigate to login page ─────────────────────────
                logger.debug(
                    "AuthManager [%s]: navigating to %s",
                    self._role_key,
                    self._login_url,
                )
                # `wait_until="domcontentloaded"` — networkidle never fires on
                # Angular dev-server URLs (localhost:4200) due to HMR WebSocket
                # traffic, and the subsequent "wait for email input visible"
                # step already gates on the SPA being rendered.
                page.goto(
                    self._login_url,
                    wait_until="domcontentloaded",
                    timeout=_LOGIN_TIMEOUT_MS,
                )

                # ── Step 2: Fast-path — already authenticated ───────────────
                # If a previous session cookie / localStorage JWT exists in the
                # blank context (unlikely, but defensive), skip the form.
                jwt_early: str | None = page.evaluate(f"localStorage.getItem('{_JWT_STORAGE_KEY}')")
                if jwt_early:
                    logger.info(
                        "AuthManager [%s]: JWT already present in localStorage — skipping login form (session reuse)",
                        self._role_key,
                    )
                    self._save_state(context, email)
                    return

                # ── Step 3: Wait for email input ────────────────────────────
                # vSuite uses PrimeNG — the email field has ARIA role=textbox
                # with name/label "Email".  Try multiple selectors.
                email_locator = None
                _EMAIL_CANDIDATES = [
                    lambda: page.get_by_role("textbox", name="Email"),
                    lambda: page.get_by_placeholder("Email"),
                    lambda: page.locator("input[type='email']"),
                    lambda: page.locator("input[name='email']"),
                ]
                for _cand_fn in _EMAIL_CANDIDATES:
                    try:
                        loc = _cand_fn()
                        loc.wait_for(state="visible", timeout=10_000)
                        email_locator = loc
                        break
                    except PWTimeout:
                        continue

                if email_locator is None:
                    raise RuntimeError(
                        f"AuthManager [{self._role_key}]: login form not found "
                        f"at {self._login_url!r} — no email input visible within 10 s. "
                        f"Check the URL or increase AUTH_LOGIN_TIMEOUT_MS."
                    )

                # ── Step 4: Fill email ─────────────────────────────────────
                email_locator.fill(email)
                logger.debug("AuthManager [%s]: filled email field", self._role_key)

                # ── Step 5: Fill password ──────────────────────────────────
                _PASSWORD_CANDIDATES = [
                    lambda: page.get_by_role("textbox", name="Password"),
                    lambda: page.get_by_placeholder("Password"),
                    lambda: page.locator("input[type='password']"),
                    lambda: page.locator("input[name='password']"),
                ]
                password_locator = None
                for _cand_fn in _PASSWORD_CANDIDATES:
                    try:
                        loc = _cand_fn()
                        loc.wait_for(state="visible", timeout=5_000)
                        password_locator = loc
                        break
                    except PWTimeout:
                        continue

                if password_locator is None:
                    raise RuntimeError(
                        f"AuthManager [{self._role_key}]: password input not found after email was filled."
                    )

                password_locator.fill(password)
                logger.debug("AuthManager [%s]: filled password field", self._role_key)

                # ── Step 6: Click login button ─────────────────────────────
                # vSuite button text varies by environment; try ordered candidates.
                _BUTTON_CANDIDATES = [
                    lambda: page.get_by_role("button", name="Log In"),
                    lambda: page.get_by_role("button", name="Login"),
                    lambda: page.get_by_role("button", name="Sign In"),
                    lambda: page.get_by_role("button", name="Submit"),
                    lambda: page.locator("button[type='submit']").first,
                    lambda: page.locator("input[type='submit']").first,
                ]
                login_button = None
                for _btn_fn in _BUTTON_CANDIDATES:
                    try:
                        btn = _btn_fn()
                        btn.wait_for(state="visible", timeout=4_000)
                        login_button = btn
                        break
                    except PWTimeout:
                        continue

                if login_button is None:
                    raise RuntimeError(
                        f"AuthManager [{self._role_key}]: could not find a submit button on the login form."
                    )

                login_button.click()
                logger.debug(
                    "AuthManager [%s]: clicked login button — waiting for navigation",
                    self._role_key,
                )

                # ── Step 7: Wait for post-login navigation ─────────────────
                try:
                    page.wait_for_load_state("networkidle", timeout=_LOGIN_TIMEOUT_MS)
                except PWTimeout:
                    # networkidle never fires due to vSuite WebSocket polling —
                    # this is expected; proceed to the JWT poll below.
                    logger.debug(
                        "AuthManager [%s]: networkidle timed out (expected for vSuite) — proceeding to JWT poll",
                        self._role_key,
                    )

                # ── Step 8: Poll for auth token / cookie / URL redirect ────
                is_authenticated = False
                jwt: str | None = None
                for attempt in range(_JWT_MAX_POLLS):
                    # Check 1: vc2JWT in localStorage
                    try:
                        jwt = page.evaluate(f"localStorage.getItem('{_JWT_STORAGE_KEY}')")
                        if jwt:
                            is_authenticated = True
                            logger.info(
                                "AuthManager [%s]: JWT detected in localStorage after %d poll(s) — login successful",
                                self._role_key,
                                attempt + 1,
                            )
                            break
                    except Exception:
                        pass

                    # Check 2: Session cookies in BrowserContext (gated on non-login URL)
                    try:
                        cur_url = page.url.lower()
                        off_login = "login" not in cur_url and "auth" not in cur_url and cur_url != "about:blank"
                        cookies = context.cookies()
                        for c in cookies:
                            c_name = c.get("name", "").lower()
                            if any(k in c_name for k in ["ssojwt", "vc2jwt", "vcreative_session", "ppo_session"]) or (off_login and any(k in c_name for k in ["session", "token"])):
                                is_authenticated = True
                                logger.info(
                                    "AuthManager [%s]: Auth cookie '%s' detected on url '%s' after %d poll(s) — login successful",
                                    self._role_key,
                                    c.get("name"),
                                    page.url,
                                    attempt + 1,
                                )
                                break
                    except Exception:
                        pass

                    if is_authenticated:
                        break

                    # Check 3: Page redirected away from login URL
                    try:
                        cur_url = page.url.lower()
                        if "login" not in cur_url and "auth" not in cur_url and cur_url != "about:blank":
                            is_authenticated = True
                            logger.info(
                                "AuthManager [%s]: Redirected to non-login URL '%s' after %d poll(s) — login successful",
                                self._role_key,
                                page.url,
                                attempt + 1,
                            )
                            break
                    except Exception:
                        pass

                    page.wait_for_timeout(_JWT_POLL_MS)

                if not is_authenticated:
                    # Capture a diagnostic screenshot before raising
                    _diag_path = _STATE_DIR / f"{self._role_key}_login_failure.png"
                    try:
                        page.screenshot(path=str(_diag_path), full_page=True)
                        logger.warning(
                            "AuthManager [%s]: diagnostic screenshot saved to %s",
                            self._role_key,
                            _diag_path,
                        )
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"AuthManager [{self._role_key}]: login failed — "
                        f"No auth token, cookie, or non-login URL redirect detected after "
                        f"{_JWT_MAX_POLLS * _JWT_POLL_MS // 1000} s. "
                        f"Check credentials for {email!r}. "
                        f"Diagnostic screenshot: {_diag_path}"
                    )

                # ── Step 9: Save storage state ─────────────────────────────
                self._save_state(context, email)

            finally:
                # Always close the context and browser — even on exception
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    def _save_state(self, context: object, email: str) -> None:  # type: ignore[type-arg]
        """
        Persist ``context.storage_state()`` to disk and write the sidecar.

        Args
        ----
        context
            A live ``playwright.sync_api.BrowserContext`` after successful login.
        email : str
            The authenticated email address (for sidecar metadata only).
        """
        state_path = self.state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            context.storage_state(path=str(state_path))  # type: ignore[attr-defined]
            state_size = state_path.stat().st_size
            logger.info(
                "AuthManager [%s]: storage state saved — %s (%.1f KB)",
                self._role_key,
                state_path,
                state_size / 1024,
            )
        except Exception as exc:
            raise RuntimeError(f"AuthManager [{self._role_key}]: failed to save storage state: {exc}") from exc

        _write_meta(state_path, self._role_key, email)

    # ── Utility: force refresh ──────────────────────────────────────────────

    def invalidate(self) -> None:
        """
        Delete the existing state file and sidecar, forcing a re-login on the
        next ``ensure_authenticated()`` call.

        Use this after a deliberate logout or when credentials change.
        """
        for path in (self.state_path, _meta_path(self.state_path)):
            try:
                if path.exists():
                    path.unlink()
                    logger.info(
                        "AuthManager [%s]: invalidated cached state — %s",
                        self._role_key,
                        path.name,
                    )
            except OSError as exc:
                logger.warning(
                    "AuthManager [%s]: could not delete %s: %s",
                    self._role_key,
                    path,
                    exc,
                )

    def __repr__(self) -> str:
        return (
            f"AuthManager(role_key={self._role_key!r}, "
            f"state_path={str(self.state_path)!r}, "
            f"valid={self.is_state_valid()!r})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton cache
# ---------------------------------------------------------------------------
# One AuthManager per role_key, reused across calls within the same process.
# Keyed by canonical role_key (not input alias).

_manager_cache: dict[str, AuthManager] = {}
_cache_lock_import = __import__("threading").Lock()


# ---------------------------------------------------------------------------
# Functional public API
# ---------------------------------------------------------------------------


def ensure_role_authenticated(
    role_name: str,
    *,
    login_url: str | None = None,
    headless: bool = True,
    force_refresh: bool = False,
) -> str:
    """
    Ensure a valid Playwright auth state file exists for ``role_name``.

    This is the primary public API for ``web_surfer.py``.  It is a thin
    wrapper around ``AuthManager.ensure_authenticated()`` that caches one
    ``AuthManager`` per role_key across the process lifetime.

    Args
    ----
    role_name : str
        Canonical role key or alias (e.g. ``"account_executive"``, ``"ae"``).
    login_url : str | None
        Override the login URL (defaults to ``settings.target_url``).
    headless : bool
        Whether the auto-login Playwright browser runs headlessly.
    force_refresh : bool
        If ``True``, invalidate any existing state file before authenticating,
        forcing a fresh login regardless of TTL.

    Returns
    -------
    str
        Absolute path to the valid storage-state JSON file.

    Raises
    ------
    KeyError
        If ``role_name`` is unknown.
    RuntimeError
        If the Playwright login fails.

    Examples
    --------
    >>> state_path = ensure_role_authenticated("producer")
    >>> # Pass to browser-use:
    >>> browser_config = BrowserConfig(storage_state=state_path)
    """
    # Resolve canonical key to use as cache key
    try:
        from backend.engine.roles import ROLE_ALIASES, ROLE_REGISTRY

        normalized = role_name.strip().lower()
        role_cache_key = ROLE_ALIASES.get(normalized, normalized)
        if role_cache_key not in ROLE_REGISTRY:
            # Let AuthManager raise the descriptive KeyError
            role_cache_key = role_name
    except Exception:
        role_cache_key = role_name

    # Include the login_url in the manager cache key so per-env managers stay
    # independent. Otherwise switching from two-test to localhost:4200 (or
    # vice-versa) would reuse a stale manager with the wrong URL.
    cache_key = f"{role_cache_key}@@{login_url or '__default__'}"

    with _cache_lock_import:
        if cache_key not in _manager_cache:
            _manager_cache[cache_key] = AuthManager(
                role_name,
                login_url=login_url,
                headless=headless,
            )
        manager = _manager_cache[cache_key]

    if force_refresh:
        manager.invalidate()

    return manager.ensure_authenticated()


def invalidate_role_state(role_name: str) -> None:
    """
    Delete the cached auth state for ``role_name``.

    Forces a fresh login on the next ``ensure_role_authenticated()`` call.
    Useful after a deliberate logout or credential rotation.

    Args
    ----
    role_name : str
        Canonical role key or alias.
    """
    try:
        from backend.engine.roles import ROLE_ALIASES

        normalized = role_name.strip().lower()
        cache_key = ROLE_ALIASES.get(normalized, normalized)
    except Exception:
        cache_key = role_name

    with _cache_lock_import:
        manager = _manager_cache.get(cache_key)

    if manager:
        manager.invalidate()
    else:
        # Manager not in cache — still delete the state file if it exists
        state_path = _STATE_DIR / f"{cache_key}_state.json"
        for path in (state_path, _meta_path(state_path)):
            try:
                if path.exists():
                    path.unlink()
                    logger.info("invalidate_role_state: deleted %s", path.name)
            except OSError as exc:
                logger.warning("invalidate_role_state: could not delete %s: %s", path, exc)


def list_cached_states() -> list[dict]:
    """
    Return metadata for all stored auth state files in ``_STATE_DIR``.

    Useful for health-check endpoints and admin dashboards.

    Returns
    -------
    list[dict]
        One dict per state file with keys:
        ``role_key``, ``state_path``, ``valid``, ``captured_at``,
        ``expires_at``, ``size_kb``.
    """
    results = []
    if not _STATE_DIR.exists():
        return results

    for json_file in sorted(_STATE_DIR.glob("*_state.json")):
        role_key = json_file.stem.removesuffix("_state")
        meta = _read_meta(json_file)
        captured_at: str = (meta or {}).get("captured_at", "unknown")
        ttl_h: float = (meta or {}).get("ttl_hours", AUTH_STATE_TTL_HOURS)

        expires_at = "unknown"
        if captured_at != "unknown":
            try:
                ca = datetime.fromisoformat(captured_at)
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                expires_at = (ca + timedelta(hours=ttl_h)).isoformat()
            except ValueError:
                pass

        # Check validity without creating a full AuthManager
        try:
            manager = AuthManager(role_key)
            valid = manager.is_state_valid()
        except Exception:
            valid = False

        results.append(
            {
                "role_key": role_key,
                "state_path": str(json_file),
                "valid": valid,
                "captured_at": captured_at,
                "expires_at": expires_at,
                "size_kb": round(json_file.stat().st_size / 1024, 1),
            }
        )

    return results
