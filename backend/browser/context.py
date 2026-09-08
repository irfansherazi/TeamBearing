"""
vQA — Playwright Browser Context Manager
==========================================
Module: backend/browser/context.py

Manages the lifecycle of Playwright browser instances and browser
contexts for vQA test execution.  This module handles:

  1. **Browser launch** — Chromium in headless or headed (Xvfb) mode.
  2. **Context creation** — with video recording, viewport sizing,
     user-agent override, and local storage injection.
  3. **Session teardown** — graceful close with video file retrieval.

Architecture Context
--------------------
**Phase 0 (per-user-session-isolation)**: The ``BrowserManager`` class
has been renamed to ``SessionBrowserManager`` with an ``id`` parameter
that accepts either a ``run_id`` (existing callers) or a ``session_id``
(session-scoped path, Phase 2+).  ``BrowserManager`` remains as a
class alias for full import backward-compat.

**Phase 4 (per-user-session-isolation)**: ``__legacy_singleton__`` is
removed.  All callers now use ``get_manager(run_id)`` (run-level lookup)
or the session-scoped ``SessionBrowserManager(id=session_id, display_num=N)``
path.  The ``display_num`` parameter wires Playwright to the correct
per-session Xvfb virtual display (``VQA_DISPLAY=:{display_num}`` env var).

``SessionBrowserManager`` is instantiated once per test run by the
``login_node`` in the LangGraph engine.  It is stored as a reference
in a run-level registry (keyed by ``run_id``) so that the executor,
planner, and reporter nodes can all access the same live page.

When the run completes, ``reporter_node`` calls ``close()`` to shut
down the context and browser, which finalises the ``.webm`` video
recording.

Video Recording
---------------
Playwright's built-in ``record_video_dir`` captures a continuous
``.webm`` (VP8) recording of the browser context.  The video file is
written to a temporary directory during the run and uploaded to S3
by ``reporter_node`` after the context is closed.

Important: the video file is only complete and flushed to disk
*after* ``context.close()`` is called.  Do not attempt to upload it
while the context is still open.

Interactive vs Headless
-----------------------
- **Headed mode** (local development, default):
  Playwright launches Chromium in headed mode with ``slowMo=500``.  The
  user can watch the automation live in the browser window on their
  desktop.  No noVNC or display server required.

- **Headless** (``VQA_MODE=headless``):
  Playwright launches Chromium in headless mode with ``slowMo=0``.
  Used in CI/CD pipelines where no display is available.

Dependencies
------------
  - ``playwright.async_api`` — async Playwright API
  - ``backend/config.py``    — settings for mode, viewport, video dir

See Also
--------
  - ``backend/engine/graph.py``  — login_node creates the context
  - ``backend/browser/screenshot.py`` — uses the active page for captures
  - ``backend/browser/accessibility.py`` — uses the active page for a11y snapshots
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Final

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from backend.config import settings
from backend.engine.state import ActorRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default viewport dimensions — 1920×1080 gives full-HD for the multimodal LLM.
DEFAULT_VIEWPORT_WIDTH: Final[int] = 1920
DEFAULT_VIEWPORT_HEIGHT: Final[int] = 1080

#: slowMo injected between every Playwright action (ms).
#: Headed mode: 10ms (just enough for visual observation, no artificial stalling).
#: Headless mode: 0 (rely entirely on Playwright native auto-waiting — no fake delays).
#: Override via VQA_SLOW_MO env var if needed.
import os as _os

_SLOW_MO_OVERRIDE = _os.environ.get("VQA_SLOW_MO")


def _get_slow_mo(is_headless: bool) -> int:
    """Return the appropriate slowMo value for the launch mode."""
    if _SLOW_MO_OVERRIDE is not None:
        return int(_SLOW_MO_OVERRIDE)
    return 0 if is_headless else 10  # 10ms headed (visual trace), 0 headless (max speed)


#: User-agent string identifying the vQA agent in server logs.
#: Useful for filtering agent traffic from real-user traffic.
VQA_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "vQA-Agent/1.0"
)

#: JavaScript snippet injected into every browser context to capture PrimeNG toast
#: messages into a global FIFO buffer (window.__VQA_TOAST_BUFFER__).
#: This is used for verification when visual inspection of the screenshot is ambiguous.
TOAST_OBSERVER_JS: Final[str] = """
(function() {
    if (window.__VQA_TOAST_BUFFER_INITIALIZED__) return;
    window.__VQA_TOAST_BUFFER_INITIALIZED__ = true;
    window.__VQA_TOAST_BUFFER__ = [];

    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            mutation.addedNodes.forEach(node => {
                if (node.nodeType !== 1) return; // 1 = Node.ELEMENT_NODE

                const toasts = [];
                // Check if the node itself matches
                if (node.matches('.p-toast-message')) {
                    toasts.push(node);
                }
                // Check for children
                const children = node.querySelectorAll('.p-toast-message');
                if (children.length > 0) {
                    toasts.push(...children);
                }

                toasts.forEach(toast => {
                    const summary = toast.querySelector('.p-toast-summary')?.innerText || '';
                    const detail = toast.querySelector('.p-toast-detail')?.innerText || '';
                    const text = (summary + ' ' + detail).trim() || toast.innerText.trim();

                    // Extract severity from class name (p-toast-message-success, etc.)
                    let severity = 'info';
                    const severityClasses = ['success', 'info', 'warn', 'error'];
                    for (const s of severityClasses) {
                        if (toast.classList.contains(`p-toast-message-${s}`)) {
                            severity = s;
                            break;
                        }
                    }

                    window.__VQA_TOAST_BUFFER__.push({
                        text: text,
                        timestamp: Date.now(),
                        severity: severity
                    });

                    // Maintain FIFO limit of 10
                    if (window.__VQA_TOAST_BUFFER__.length > 10) {
                        window.__VQA_TOAST_BUFFER__.shift();
                    }
                });
            });
        }
    });

    // Observe the whole document to catch additions anywhere (including before body exists)
    observer.observe(document, { childList: true, subtree: true });
})();
"""

#: vQA Angular Bridge
#: Pierces the Angular 9+ (Ivy) internal state for deterministic inspection and interaction.
def get_angular_bridge_js() -> str:
    path = Path(__file__).parent / "injection.js"
    return path.read_text() if path.exists() else ""


# ---------------------------------------------------------------------------
# Browser Manager
# ---------------------------------------------------------------------------


class SessionBrowserManager:
    """
    Manages the Playwright browser lifecycle for a single vQA session or run.

    **Phase 0 (per-user-session-isolation)**: Renamed from ``BrowserManager``
    to ``SessionBrowserManager``.  The constructor now accepts an ``id``
    keyword argument (the session ID or run ID) in addition to the legacy
    positional ``run_id``.  ``BrowserManager`` remains as a class alias;
    all existing callers continue to work unchanged.

    Each instance is fully isolated — no class-level mutable state is shared
    between instances.  Two ``SessionBrowserManager`` instances with different
    ``id`` values share no pages, video paths, actor registries, or browser
    processes.

    Attributes
    ----------
    session_id : str
        The canonical per-session identifier.  Equals ``id`` from the
        constructor.  Phase 2+ code should use this attribute; legacy code
        may still reference ``run_id`` (kept as an alias).

    run_id : str
        Alias for ``session_id`` — maintained for backward-compat with all
        LangGraph engine nodes that reference ``manager.run_id``.

    page : Page | None
        The active Playwright page.  ``None`` before ``start()`` and
        after ``close()``.

    video_path : Path | None
        Absolute path to the ``.webm`` video file recorded by Playwright.
        Only available after ``close()`` is called (Playwright finalises
        the video file on context close).

    Usage via async context manager
    --------------------------------
    >>> async with SessionBrowserManager(id="session-abc123") as bm:
    ...     await bm.page.goto("https://example.com")
    ...     # bm.page is the live Playwright Page
    ... # bm.video_path now contains the .webm file path

    Usage via explicit start/close
    -------------------------------
    >>> bm = SessionBrowserManager(id="session-abc123")
    >>> await bm.start()
    >>> await bm.page.goto("https://example.com")
    >>> video = await bm.close()
    >>> print(video)   # /tmp/vqa-videos-session-abc123/.../video.webm

    Legacy usage (unchanged — BrowserManager alias):
    -------------------------------------------------
    >>> bm = BrowserManager(run_id="run-abc123")  # still works
    """

    def __init__(self, run_id: str = "", *, id: str = "", display_num: int = 0) -> None:  # noqa: A002
        """
        Initialise a new SessionBrowserManager.

        Does NOT launch the browser — call ``start()`` or use as an
        async context manager.

        Args
        ----
        run_id : str
            Legacy positional argument.  Kept for backward-compat with all
            existing callers that do ``BrowserManager(run_id="...")`` or
            ``BrowserManager("run-id")``.  If both ``run_id`` and ``id``
            are provided, ``id`` takes precedence.
        id : str
            Session or run identifier (keyword-only).  Use this in new
            Phase 2+ code.  Overrides ``run_id`` when both are supplied.
        display_num : int, optional
            Per-session Xvfb display number (Phase 4, per-user-session-isolation).
            When non-zero, ``start()`` sets ``VQA_DISPLAY=:{display_num}`` in the
            process environment before launching Playwright so Chromium attaches
            to the correct per-session virtual display (ADR-1).
            Default ``0`` leaves the existing ``DISPLAY`` / ``VQA_DISPLAY`` env
            vars untouched — safe for legacy/headless callers (kill-switch path).

        Notes
        -----
        - ``session_id`` is the canonical Phase 2+ attribute.
        - ``run_id`` is an alias kept for backward-compat.
        - ``display_num`` is the Phase 4 addition; ``display_num=0`` is a safe
          no-op default that preserves all pre-Phase-4 behaviour.
        """
        # Resolve the canonical identifier: `id` wins over `run_id`
        _effective_id = id if id else run_id
        self.session_id: str = _effective_id
        self.run_id: str = _effective_id  # backward-compat alias
        self.display_num: int = display_num  # Phase 4: per-session Xvfb display
        self.page: Page | None = None
        self.video_path: Path | None = None

        # Internal references — set by start(), cleared by close()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._video_dir: Path | None = None

        # ── Actor Persistence (TASK-090: Omniscient Blackboard) ───────
        self._actor_db = ActorRegistry()

        # ── Multi-Actor Registry (Supervisor-Worker Phase 1) ──────────
        # Maps role_key → (BrowserContext, Page) for pre-authenticated
        # sessions.  All contexts share the same browser process — they
        # are extremely lightweight (~2 MB RAM each).  Keeping them alive
        # enables instant switching (~50 ms) instead of re-authenticating
        # (~5-15 s per role).
        # The first context created via start() is NOT auto-registered;
        # it only enters the registry when switch_actor() is called with
        # the primary role key (or when login_node explicitly registers it).
        self._actor_registry: dict[str, tuple[BrowserContext, Page]] = {}
        self._active_actor: str = ""

    # ------------------------------------------------------------------
    # Async context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "SessionBrowserManager":
        """Start the browser and return self."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the browser on context exit."""
        await self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, storage_state: str | dict | None = None) -> Page:
        """
        Launch Chromium, create a browser context with video recording,
        and open a new page.

        This method:
        1. Starts the Playwright async engine.
        2. Launches Chromium (headed or headless based on settings).
        3. Creates a browser context with:
           - Optional ``storage_state`` (restored session)
           - Video recording enabled (``record_video_dir``)
           - 1920×1080 viewport
           - Custom user-agent
        4. Opens a blank page in the context.

        Returns
        -------
        Page
            The newly created Playwright page ready for navigation.

        Args
        ----
        storage_state : str | dict | None
            Optional Playwright storage state (path to JSON or dict).
            If provided, the browser context starts with this session data.
        """
        # ── Headless / headed decision ─────────────────────────────────
        # Priority (highest → lowest):
        #   1. settings.vqa_mode == "headless"  (set via API request payload)
        #   2. VQA_HEADLESS=1 env var           (CI / Docker override)
        #   3. Default: headed (False)          — QA/Product watch the run locally
        #
        # NOTE: Do NOT use a DISPLAY/WAYLAND heuristic here — macOS has no
        # DISPLAY var and would incorrectly default to headless.
        import os as _env_os

        # ── Phase 4: Per-session display wiring (ADR-1) ───────────────
        # When display_num > 0, set VQA_DISPLAY=:{display_num} so Playwright
        # attaches to the correct per-session Xvfb virtual display.
        # display_num=0 (default) leaves the existing env vars untouched —
        # safe for legacy/headless callers and the SESSION_ISOLATION_ENABLED=false
        # kill-switch path.
        if self.display_num > 0:
            _env_os.environ["VQA_DISPLAY"] = f":{self.display_num}"
            logger.debug(
                "[%s] Phase 4: set VQA_DISPLAY=%s for per-session display",
                self.run_id,
                _env_os.environ["VQA_DISPLAY"],
            )

        is_headless = (
            settings.vqa_mode == "headless" if hasattr(settings, "vqa_mode") else False
        ) or _env_os.environ.get("VQA_HEADLESS", "").strip() == "1"
        slow_mo = _get_slow_mo(is_headless)
        mode_label = "headless" if is_headless else f"headed (slowMo={slow_mo}ms)"

        logger.info(
            "[%s] Launching Chromium in %s mode",
            self.run_id,
            mode_label,
        )

        # ── Step 1: Start Playwright ──────────────────────────────────
        self._playwright = await async_playwright().start()

        # ── Step 2: Launch browser ────────────────────────────────────
        launch_args: list[str] = [
            "--no-sandbox",  # Required in Docker containers
            "--disable-dev-shm-usage",  # /dev/shm is too small in Docker
        ]

        if is_headless:
            # Headless: disable GPU, use explicit viewport for stable screenshots
            launch_args.append("--disable-gpu")
        else:
            # Headed: maximise the OS window so the full UI is always visible.
            # Without this, Chromium requests a 1920×1080 window which the OS
            # clips on smaller displays — causing PrimeNG sidebar buttons that
            # live at the bottom of the panel to be unreachable.
            launch_args.append("--start-maximized")

        self._browser = await self._playwright.chromium.launch(
            headless=is_headless,
            slow_mo=slow_mo,
            args=launch_args,
        )

        # ── Step 3: Create browser context ────────────────────────────
        if is_headless:
            # Headless: explicit 1920×1080 viewport gives the LLM a consistent
            # screenshot size for its multimodal reasoning.
            ctx_viewport: dict | None = {
                "width": DEFAULT_VIEWPORT_WIDTH,
                "height": DEFAULT_VIEWPORT_HEIGHT,
            }
        else:
            # Headed with --start-maximized: viewport=None lets Chromium inherit
            # the actual screen dimensions.  The window fills the display so
            # sidepanel footers, dialogs, and sticky buttons are always on-screen.
            ctx_viewport = None

        # ── Video recording directory ──────────────────────────────────
        # Playwright writes a .webm VP8 file into this dir.  The file is
        # NOT complete until context.close() is called.  We store the dir
        # reference so close() can scan for the .webm and return its path.
        self._video_dir = Path(tempfile.mkdtemp(prefix=f"vqa-videos-{self.run_id}-"))
        logger.info("[%s] Video recording dir: %s", self.run_id, self._video_dir)

        self._context = await self._browser.new_context(
            storage_state=storage_state,
            viewport=ctx_viewport,
            # User-agent: identify vQA traffic in server access logs
            user_agent=VQA_USER_AGENT,
            # Ignore HTTPS errors on test environments with self-signed certs
            ignore_https_errors=True,
            # Video recording — .webm file is finalised on context.close()
            record_video_dir=str(self._video_dir),
            record_video_size={"width": DEFAULT_VIEWPORT_WIDTH, "height": DEFAULT_VIEWPORT_HEIGHT},
        )

        # ── Step 3.5: Inject Toast Observer (TASK-009) ────────────────
        if settings.enable_toast_buffer:
            await self._context.add_init_script(TOAST_OBSERVER_JS)
            logger.info("[%s] Toast observer injected into context", self.run_id)

        # ── Step 3.6: Inject Angular Bridge (TASK-091) ────────────────
        bridge_js = get_angular_bridge_js()
        if bridge_js:
            await self._context.add_init_script(bridge_js)
            logger.info("[%s] Angular bridge injected into context", self.run_id)

        # ── Step 4: Open a new page ───────────────────────────────────
        self.page = await self._context.new_page()

        # Log the effective viewport (None = native screen size in headed mode)
        effective_vp = f"{DEFAULT_VIEWPORT_WIDTH}x{DEFAULT_VIEWPORT_HEIGHT}" if is_headless else "native (maximised)"
        logger.info(
            "[%s] Browser ready: Chromium %s, viewport %s",
            self.run_id,
            mode_label,
            effective_vp,
        )

        return self.page

    async def get_cdp_session(self) -> "CDPSession":
        """
        Create and return a new CDP session attached to the current page.

        Returns
        -------
        CDPSession
            A live Playwright CDP session.
        """
        if not self.page:
            raise RuntimeError("Browser not started or page closed.")
        return await self.page.context.new_cdp_session(self.page)

    async def query_angular(self, selector: str, method: str, *args) -> Any:
        """
        Query the Angular bridge for a given element.

        Args
        ----
        selector : str
            CSS selector for the target element.
        method : str
            Bridge method to call (e.g., 'getComponentState', 'markForCheck').
        *args : Any
            Additional arguments for the method.

        Returns
        -------
        Any
            Result from the Angular bridge method, or None if the page
            is not available or the bridge is missing.
        """
        if not self.page:
            return None

        # Ensure the bridge is available before querying
        bridge_ready = await self.page.evaluate("() => !!window.__VQA_ANGULAR_BRIDGE__")
        if not bridge_ready:
            # Re-inject if missing (e.g. after hard navigation that bypassed add_init_script)
            bridge_js = get_angular_bridge_js()
            if bridge_js:
                await self.page.evaluate(bridge_js)
            else:
                logger.warning("[%s] query_angular: bridge JS not available", self.run_id)
                return None

        try:
            return await self.page.evaluate(
                "(args) => {"
                "  const [sel, meth, ...rest] = args;"
                "  const el = document.querySelector(sel);"
                "  if (!el) return { error: 'Element not found', selector: sel };"
                "  if (!window.__VQA_ANGULAR_BRIDGE__[meth]) return { error: 'Method not found', method: meth };"
                "  return window.__VQA_ANGULAR_BRIDGE__[meth](el, ...rest);"
                "}",
                [selector, method, *args],
            )
        except Exception as e:
            logger.error("[%s] query_angular error: %s", self.run_id, e)
            return None

    # ------------------------------------------------------------------
    # Multi-Actor Context Switching
    # ------------------------------------------------------------------

    async def switch_actor(self, role_key: str) -> Page:
        """
        Switch to the browser context for the given role.

        If the role has been authenticated before (exists in the actor
        registry), its existing ``BrowserContext`` and ``Page`` are
        reactivated instantly (~50 ms).  The page is exactly where it
        was left — no re-login, no re-navigation.

        If the role is new, a fresh ``BrowserContext`` is created using
        the role's Playwright storage-state file (from ``AuthManager``),
        and the new context is registered for future instant switching.

        All contexts share the same underlying Chromium browser process
        — they are extremely lightweight (~2 MB RAM each).

        Args
        ----
        role_key : str
            Canonical role key (e.g., ``"account_executive"``,
            ``"voice_talent"``).  Must match a key in ``ROLE_REGISTRY``
            or a valid alias in ``ROLE_ALIASES``.

        Returns
        -------
        Page
            The active Playwright Page for the switched-to role.
            Ready for immediate interaction — no navigation needed.

        Raises
        ------
        RuntimeError
            If the browser has not been started (``self._browser`` is None),
            or if ``AuthManager`` cannot authenticate the role.

        Example
        -------
        >>> manager = get_manager(run_id)
        >>> # Switch from AE to Voice Talent (instant if already opened)
        >>> voicer_page = await manager.switch_actor("voice_talent")
        >>> await voicer_page.goto("https://two-test.vcreative.net")
        """
        if self._browser is None:
            raise RuntimeError(
                f"BrowserManager [{self.run_id}]: cannot switch_actor — browser not started. Call start() first."
            )

        # ── Fast path: actor already in registry → instant switch ─────
        if role_key in self._actor_registry:
            ctx, page = self._actor_registry[role_key]
            self._context = ctx
            self.page = page
            self._active_actor = role_key
            logger.info(
                "[%s] switch_actor: instant switch to '%s' (context reused, total actors: %d)",
                self.run_id,
                role_key,
                len(self._actor_registry),
            )
            return page

        # ── Slow path: new actor → restore from DB or fresh login ──────
        stored_state = self._actor_db.get_storage_state(self.run_id, role_key)

        if stored_state:
            logger.info(
                "[%s] switch_actor: restored '%s' from ActorRegistry",
                self.run_id,
                role_key,
            )
            state_to_use = stored_state
        else:
            from backend.engine.auth_manager import ensure_role_authenticated
            state_to_use = ensure_role_authenticated(role_key)
            logger.info(
                "[%s] switch_actor: creating new context for '%s' (auth state: %s)",
                self.run_id,
                role_key,
                state_to_use,
            )

        new_ctx = await self._browser.new_context(
            storage_state=state_to_use,
            viewport={"width": DEFAULT_VIEWPORT_WIDTH, "height": DEFAULT_VIEWPORT_HEIGHT},
            user_agent=VQA_USER_AGENT,
            ignore_https_errors=True,
            record_video_dir=str(self._video_dir) if self._video_dir else None,
            record_video_size={
                "width": DEFAULT_VIEWPORT_WIDTH,
                "height": DEFAULT_VIEWPORT_HEIGHT,
            },
        )

        # ── Multi-Actor Toast Observer (TASK-009) ─────────────────────
        if settings.enable_toast_buffer:
            await new_ctx.add_init_script(TOAST_OBSERVER_JS)
            logger.info(
                "[%s] Toast observer injected into actor '%s' context",
                self.run_id,
                role_key,
            )

        # ── Multi-Actor Angular Bridge (TASK-091) ─────────────────────
        bridge_js = get_angular_bridge_js()
        if bridge_js:
            await new_ctx.add_init_script(bridge_js)
            logger.info(
                "[%s] Angular bridge injected into actor '%s' context",
                self.run_id,
                role_key,
            )

        new_page = await new_ctx.new_page()

        # Save to DB if it was a fresh login (so subsequent runs can restore it)
        if not stored_state:
            initial_state = await new_ctx.storage_state()
            self._actor_db.set_storage_state(self.run_id, role_key, initial_state)

        # Register in actor registry for future instant switching
        self._actor_registry[role_key] = (new_ctx, new_page)
        self._context = new_ctx
        self.page = new_page
        self._active_actor = role_key

        logger.info(
            "[%s] switch_actor: '%s' context created and registered (total actors: %d)",
            self.run_id,
            role_key,
            len(self._actor_registry),
        )
        return new_page

    async def register_primary_actor(self, role_key: str) -> None:
        """
        Register the current primary context in the actor registry.

        Called by ``login_node`` after the initial ``start()`` + login
        sequence completes, so the primary role's context is available
        for instant switching via ``switch_actor()``.

        This is a no-op if the context or page is None (browser not started).

        Args
        ----
        role_key : str
            The canonical role key for the primary (first) actor.
        """
        if self._context is not None and self.page is not None:
            self._actor_registry[role_key] = (self._context, self.page)
            self._active_actor = role_key

            # Save initial state to DB (TASK-090: Omniscient Blackboard)
            try:
                initial_state = await self._context.storage_state()
                self._actor_db.set_storage_state(self.run_id, role_key, initial_state)
                logger.debug("[%s] register_primary_actor: saved state for '%s'", self.run_id, role_key)
            except Exception as e:
                logger.warning("[%s] register_primary_actor: failed to save state: %s", self.run_id, e)

            logger.info(
                "[%s] register_primary_actor: '%s' registered in actor registry",
                self.run_id,
                role_key,
            )

    @property
    def active_actor(self) -> str:
        """Return the role_key of the currently active actor."""
        return self._active_actor

    @property
    def actor_count(self) -> int:
        """Return the number of actors currently registered."""
        return len(self._actor_registry)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """
        Close ALL browser contexts (primary + actors), the browser process,
        and the Playwright engine.  Finalise the video recording.

        This method MUST be called after the test run completes.  It:
        1. Closes every actor context in the registry.
        2. Closes the primary context (if not already in the registry).
        3. Scans the video directory for the recorded .webm file.
        4. Closes the browser process and stops Playwright.

        Notes
        -----
        After ``close()`` is called, ``self.page`` and ``self._context``
        are set to ``None``.  Any further calls to ``page.goto()`` etc.
        will raise ``AttributeError``.

        Returns
        -------
        Path | None
            Absolute path to the .webm video file, or None if recording
            failed or was not configured.
        """
        logger.info("[%s] Closing browser...", self.run_id)

        # ── Step 0: Save and Close all actor-registry contexts ─────────
        # These are the multi-actor contexts created by switch_actor().
        # We save their current storage state to the ActorRegistry (SQLite)
        # before closing so they can be restored in future runs.
        _TEARDOWN_SUPPRESSED_KEYWORDS = (
            "target closed",
            "epipe",
            "connection closed",
            "browser has been closed",
            "context was destroyed",
            "writeunix",  # FEAT-062: Suppress transient socket errors
            "closed=true",  # FEAT-062: Suppress already-closed errors
        )

        for actor_key, (actor_ctx, _actor_page) in list(self._actor_registry.items()):
            try:
                # Save storage state to DB before closing
                try:
                    current_state = await actor_ctx.storage_state()
                    self._actor_db.set_storage_state(self.run_id, actor_key, current_state)
                    logger.debug("[%s] Saved storage state for actor '%s'", self.run_id, actor_key)
                except Exception as save_err:
                    logger.warning("[%s] Failed to save state for actor '%s': %s", self.run_id, actor_key, save_err)

                await actor_ctx.close()
                logger.info(
                    "[%s] Closed actor context for '%s'",
                    self.run_id,
                    actor_key,
                )
            except Exception as actor_err:
                err_str = str(actor_err).lower()
                if any(kw in err_str for kw in _TEARDOWN_SUPPRESSED_KEYWORDS):
                    logger.warning(
                        "[%s] Suppressed non-fatal teardown error for actor '%s': %s",
                        self.run_id,
                        actor_key,
                        str(actor_err)[:120],
                    )
                else:
                    logger.error(
                        "[%s] Error closing actor '%s': %s",
                        self.run_id,
                        actor_key,
                        str(actor_err)[:120],
                    )
        self._actor_registry.clear()
        self._active_actor = ""

        # ── Step 1: Close the primary context (if not already closed
        #    by the actor-registry loop above) ─────────────────────────
        try:
            if self._context:
                try:
                    await self._context.close()
                    self._context = None
                    self.page = None
                    logger.info("[%s] Browser context closed.", self.run_id)
                except Exception as ctx_err:
                    # Suppress EPIPE / TargetClosed errors during teardown.
                    # These occur when the browser process is already gone by
                    # the time context.close() runs (e.g. user closed window,
                    # or page crash). They are non-fatal and must not propagate.
                    err_str = str(ctx_err).lower()
                    if any(kw in err_str for kw in _TEARDOWN_SUPPRESSED_KEYWORDS):
                        logger.warning(
                            "[%s] Suppressed non-fatal teardown error: %s",
                            self.run_id,
                            str(ctx_err)[:120],
                        )
                        self._context = None
                        self.page = None
                    else:
                        raise  # Re-raise genuinely unexpected errors

        except Exception as e:
            logger.error(
                "[%s] Error during browser close: %s",
                self.run_id,
                str(e),
                exc_info=True,
            )

        finally:
            # Always clean up browser and playwright processes.
            # The asyncio.sleep gives Playwright's Node.js bridge a brief window
            # to flush any in-progress video buffer to disk before the process exits.
            import asyncio as _asyncio

            await _asyncio.sleep(0.5)  # 500 ms — video flush window

            # FIX: Suppress EPIPE / broken-pipe errors during browser teardown.
            # Playwright's Node.js driver can race against the Python process
            # closing the pipe's read end, causing an unhandled 'write EPIPE'
            # error that crashes the entire driver subprocess.  These errors
            # are non-fatal during shutdown and must be swallowed.
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as _browser_err:
                    _b_msg = str(_browser_err).lower()
                    if any(kw in _b_msg for kw in _TEARDOWN_SUPPRESSED_KEYWORDS):
                        logger.warning(
                            "[%s] Suppressed non-fatal browser.close() error: %s",
                            self.run_id,
                            str(_browser_err)[:120],
                        )
                    else:
                        logger.error(
                            "[%s] Unexpected browser.close() error: %s",
                            self.run_id,
                            str(_browser_err)[:120],
                        )
                self._browser = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as _pw_err:
                    # Playwright.stop() can also EPIPE if the Node.js driver
                    # has already exited due to the browser.close() race.
                    logger.warning(
                        "[%s] Suppressed playwright.stop() error: %s",
                        self.run_id,
                        str(_pw_err)[:80],
                    )
                self._playwright = None

        # ── Locate the finalised .webm file ──────────────────────────
        # Playwright writes the video to self._video_dir with a random filename.
        # Scan the dir for the first .webm file and return its path.
        if self._video_dir and self._video_dir.exists():
            webm_files = sorted(self._video_dir.glob("*.webm"))
            if webm_files:
                self.video_path = webm_files[0]
                logger.info(
                    "[%s] Video file ready: %s (%d bytes)",
                    self.run_id,
                    self.video_path,
                    self.video_path.stat().st_size,
                )
                return self.video_path
            else:
                logger.warning(
                    "[%s] Video dir exists but no .webm found: %s",
                    self.run_id,
                    self._video_dir,
                )
        else:
            logger.warning("[%s] Video dir not set or missing", self.run_id)

        return None

    @property
    def is_active(self) -> bool:
        """
        Check whether the browser session is currently open.

        Returns
        -------
        bool
            ``True`` if the page is open and the browser is running.
            ``False`` after ``close()`` or before ``start()``.
        """
        return self.page is not None and self._context is not None


# ---------------------------------------------------------------------------
# Phase 0: Backward-compat class alias
# Phase 4 (per-user-session-isolation): __legacy_singleton__ REMOVED.
# All callers now use get_manager(run_id) or the session-scoped path.
# ---------------------------------------------------------------------------

#: ``BrowserManager`` is preserved as a class alias so all existing import
#: sites (``from backend.browser.context import BrowserManager``) continue
#: to work without modification.
BrowserManager = SessionBrowserManager


# ---------------------------------------------------------------------------
# Run-level registry
# ---------------------------------------------------------------------------
# Each active test run has its own SessionBrowserManager instance.
# The login_node creates it; the reporter_node closes it.
# Other nodes (planner, executor) look it up by run_id.

_active_managers: dict[str, SessionBrowserManager] = {}


def register_manager(run_id: str, manager: "SessionBrowserManager") -> None:
    """
    Register a ``SessionBrowserManager`` for a test run.

    Called by ``login_node`` after ``manager.start()`` succeeds.

    Args
    ----
    run_id : str
        Unique run identifier.
    manager : SessionBrowserManager
        The initialised and started browser manager.
    """
    _active_managers[run_id] = manager
    logger.debug("Registered SessionBrowserManager for run '%s'", run_id)


def get_manager(run_id: str) -> "SessionBrowserManager":
    """
    Retrieve the active ``BrowserManager`` for a test run.

    Args
    ----
    run_id : str
        The run ID to look up.

    Returns
    -------
    BrowserManager
        The browser manager for the specified run.

    Raises
    ------
    KeyError
        If no manager is registered for the given run_id.
        This indicates a logic error — the node called without
        login_node having run first.
    """
    if run_id not in _active_managers:
        raise KeyError(f"No active BrowserManager for run '{run_id}'. Ensure login_node has executed before this node.")
    return _active_managers[run_id]


def unregister_manager(run_id: str) -> None:
    """
    Remove a ``BrowserManager`` from the registry after the run completes.

    Called by ``reporter_node`` after ``manager.close()`` and video upload.

    Also purges any ephemeral persona credentials stored by
    ``persona_switch_node`` during HITL persona switching (TASK-063 Phase 4).

    Args
    ----
    run_id : str
        The run ID to remove.  No-op if not found.
    """
    removed = _active_managers.pop(run_id, None)
    if removed:
        logger.debug("Unregistered BrowserManager for run '%s'", run_id)

    # Purge ephemeral persona credentials (TASK-063 Phase 4).
    # Credentials are held in-memory only and must be discarded on run teardown.
    try:
        from backend.engine.persona_switch_node import clear_run_creds
        clear_run_creds(run_id)
    except ImportError:
        pass  # persona_switch_node not available in all deployments


def get_all_managers() -> dict[str, "SessionBrowserManager"]:
    """
    Return a snapshot of all currently active ``BrowserManager`` instances.

    Used by the FastAPI lifespan teardown to drain all open browser sessions
    gracefully when the server shuts down (uvicorn SIGINT/SIGTERM).

    Returns
    -------
    dict[str, BrowserManager]
        A shallow copy of the registry — modifying the returned dict does
        not affect the live registry.
    """
    return dict(_active_managers)


def resolve_display(env: dict[str, str]) -> None:
    """
    Set DISPLAY in the env dict for headed Playwright execution.
    Consistently used across playwright_routes.py and playwright_executor.py.
    """
    import os
    if "VQA_DISPLAY" in os.environ:
        env["DISPLAY"] = os.environ["VQA_DISPLAY"]
    elif os.getenv("VQA_MODE") == "interactive" and "DISPLAY" not in env:
        env["DISPLAY"] = ":99"
