"""
vQA — Human Takeover Module
=============================
Module: backend/engine/human_takeover.py

When the agent gets stuck (2+ consecutive locator failures on the same AC step),
this module pauses the LangGraph graph execution and waits for a human to
complete the stuck browser action manually via the vQA app's interactive
screenshot panel.

Flow
----
1. evaluator_node routes to "human_takeover" when locator_fail_count >= 2
2. human_takeover_node:
   a. Broadcasts a WS message directly (via injected callback, pre-await)
   b. Calls await asyncio.Event.wait() — suspends THIS coroutine but keeps
      the event loop running so other async tasks (HTTP, WebSocket) continue
3. User clicks in the screenshot → POST /runs/{run_id}/interact (mouse injection)
4. User clicks "Done" → POST /runs/{run_id}/human-takeover/done
5. complete_takeover() sets the event → human_takeover_node resumes
6. Node writes learned action to long_term_memory, resets fail counters
7. Returns _next_node: "planner" to resume the run

Circular Import Prevention
--------------------------
routes.py imports from graph.py (which imports this module).
This module must NOT import from routes.py.

Instead, routes.py calls set_ws_broadcaster() at startup to inject its
broadcast function as a callback.  human_takeover_node calls this callback
directly, bypassing the LangGraph state diff mechanism for the WS event.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from backend.browser.context import get_manager
from backend.browser.screenshot import capture_screenshot_b64
from backend.browser.vnc_builder import VncUrlBuilder
from backend.config import settings
from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global registries
# ---------------------------------------------------------------------------

# Per-run asyncio Events.  Set by complete_takeover() to resume the node.
_takeover_events: dict[str, asyncio.Event] = {}

# Per-run user response data from POST /human-takeover/done.
_takeover_data: dict[str, dict[str, str]] = {}

# WebSocket broadcast callback injected by routes.py at startup.
# Signature: async (run_id, ac_step, ac_step_index, error_message) -> None
_WS_BROADCAST_FN: Optional[Callable] = None

# Screenshot broadcast callback injected by routes.py at startup.
# Signature: async (run_id, data_b64) -> None
_WS_SCREENSHOT_FN: Optional[Callable] = None

# Action recorded broadcast callback injected by routes.py at startup.
# Signature: async (run_id, action_dict) -> None
_WS_ACTION_FN: Optional[Callable] = None

# Dialog opened broadcast callback injected by routes.py at startup.
# Signature: async (run_id, message, dialog_type, default_value) -> None
_WS_DIALOG_FN: Optional[Callable] = None

# Per-run slot for the LAST click captured by the JS click-capture listener.
# Key: run_id, Value: dict with captured selector info.
_last_human_click: dict[str, dict] = {}

# Per-run slot for the FULL action sequence captured during takeover.
# Key: run_id, Value: list of action records in order.
_human_action_sequence: dict[str, list[dict]] = {}

# Per-run slot for active browser dialogs (alert/confirm/prompt).
_pending_dialogs: dict[str, Any] = {}

# KB staging file — human-learned selectors accumulate here until kb-human-sync
_KB_STAGING_FILE = Path(__file__).parent.parent.parent / "knowledge" / "human_learned.jsonl"

# Learned workflows file — full action sequences keyed by AC step text
_LEARNED_WORKFLOWS_FILE = Path(__file__).parent.parent.parent / "knowledge" / "blueprints" / "learned_workflows.json"

# vSuite actions KB — auto-generated workflow blocks are appended here
_KB_VSUITE_ACTIONS_FILE = Path(__file__).parent.parent.parent / "knowledge" / "vSuite-actions.md"

# Human guidance KB — user instructions persisted here so future runs can query them.
# Written in ## WORKFLOW: format so the TF-IDF loader indexes it automatically.
# One file, append-only. Each entry = one guidance block from one user interaction.
_HUMAN_GUIDANCE_KB_FILE = Path(__file__).parent.parent.parent / "knowledge" / "human_guidance.md"

# T2-b: Storage directory for Playwright trace .zip files produced on each HITL.
# Default: storage/hitl_traces/ relative to the project root (local-only; not synced to S3).
HITL_TRACES_DIR = Path(__file__).parent.parent.parent / "storage" / "hitl_traces"

# T2-b: Per-run takeover sequence counter (incremented each time a HITL fires within a run).
_takeover_seq: dict[str, int] = {}


def _resolve_recorded_by(run_id: str) -> str:
    """
    Resolve the recorded_by attribution email for a KB write from the run's
    owning session (Phase 5 / AC-HAPPY-3). Falls back to ``"anonymous"`` when
    session isolation is disabled or the session lookup fails — the KB stays
    writable in the legacy path.
    """
    try:
        from backend.api.routes import _run_states  # lazy — avoid circular
        meta = _run_states.get(run_id) or {}
        sid = meta.get("session_id")
        if not sid:
            return "anonymous"
        from backend.session.manager import get_session_manager
        session = get_session_manager().get_session(sid)
        if session is None or not getattr(session, "user_email", ""):
            return "anonymous"
        return session.user_email
    except Exception:
        return "anonymous"


async def persist_user_guidance(
    guidance_text: str,
    ac_step: str,
    ticket_id: str,
    source: str = "user_guidance",
    run_id: str = "",
    product: str | None = None,
) -> None:
    """
    Write free-text user guidance to the Human Guidance KB file.

    Called from two places:
      1. API start payload — when the user provides ``user_guidance`` text
         before the run begins (routes.py calls this after setting state).
      2. HITL explanation field — when the user types an explanation in the
         takeover modal and clicks Done (human_takeover_node calls this).

    Format: ``## WORKFLOW:`` blocks so the TF-IDF loader indexes them
    automatically on the next ``kb.reload_if_updated()`` call (every query).

    De-duplication: if the exact guidance text already appears in the file
    for this AC step, the write is skipped to prevent unbounded growth.

    Args
    ----
    guidance_text : str
        The free-text instruction the user provided.
    ac_step : str
        The AC step this guidance applies to (used as the WORKFLOW name key).
    ticket_id : str
        Jira ticket ID for provenance.
    source : str
        Either ``"user_guidance"`` (pre-run) or ``"hitl_explanation"``
        (mid-run takeover).
    """
    if not guidance_text or not guidance_text.strip():
        return

    import re as _re
    from datetime import datetime, timezone

    from backend.kb.writer import KBWriter

    recorded_at = datetime.now(timezone.utc).isoformat()
    recorded_by = _resolve_recorded_by(run_id)

    def _write() -> None:
        _HUMAN_GUIDANCE_KB_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if _HUMAN_GUIDANCE_KB_FILE.exists():
            existing = _HUMAN_GUIDANCE_KB_FILE.read_text(encoding="utf-8")

        dedup_key = guidance_text.strip()[:80]
        if dedup_key in existing:
            logger.info(
                "Human Guidance KB: guidance already stored for step '%s' — skipping",
                ac_step[:60],
            )
            return

        combined_text = f"{ac_step} {guidance_text}"
        raw_words = _re.findall(r"[a-zA-Z]{4,}", combined_text.lower())
        seen: set = set()
        keywords: list[str] = []
        for w in raw_words:
            if w not in seen:
                seen.add(w)
                keywords.append(w)
            if len(keywords) >= 10:
                break
        keywords_str = ", ".join(keywords) + ", human-guidance, user-instruction"
        if product:
            keywords_str += f", product-{product}"

        step_slug = ac_step[:80].strip()
        block = (
            f"\n\n## WORKFLOW: {step_slug}\n"
            f"KEYWORDS: {keywords_str}\n"
            "---\n"
            f"USER-PROVIDED GUIDANCE ({source}, {recorded_at}, ticket {ticket_id}):\n"
            f"{guidance_text.strip()}\n\n"
            "INSTRUCTIONS FOR THE AGENT:\n"
            "  Follow the guidance above VERBATIM. This instruction came directly from\n"
            "  a human operator who knows the correct interaction pattern for this step.\n"
            "  Do NOT deviate from this approach.\n"
        )

        KBWriter.append_markdown_with_lock(
            file_path=_HUMAN_GUIDANCE_KB_FILE,
            content=block,
            recorded_by=recorded_by,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)
    logger.info(
        "Human Guidance KB: persisted %d-char guidance for step '%s...' (source=%s recorded_by=%s) → %s",
        len(guidance_text),
        ac_step[:40],
        source,
        recorded_by,
        _HUMAN_GUIDANCE_KB_FILE.name,
    )


from backend.engine.autorecord import autorecord_serializer


async def _save_combined_hitl_entry(
    ac_step: str,
    explanation: str,
    action_sequence: list[dict],
    ticket_id: str,
    run_id: str = "",
) -> None:
    """
    Write a combined HITL knowledge base entry to human_guidance.md.

    Phase 5: routes the append through ``KBWriter.append_markdown_with_lock``
    so concurrent HITL writes serialize under flock and carry a
    ``<!-- recorded_by: ... -->`` attribution comment.
    """
    import re as _re
    from datetime import datetime, timezone

    from backend.kb.writer import KBWriter

    if not explanation.strip() and not action_sequence:
        return

    recorded_at = datetime.now(timezone.utc).isoformat()
    recorded_by = _resolve_recorded_by(run_id)

    def _write() -> None:
        _HUMAN_GUIDANCE_KB_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if _HUMAN_GUIDANCE_KB_FILE.exists():
            existing = _HUMAN_GUIDANCE_KB_FILE.read_text(encoding="utf-8")

        dedup_key = (explanation or "").strip()[:80]
        if dedup_key and dedup_key in existing:
            logger.info(
                "Combined HITL KB: entry already stored for step '%s' — skipping dedup",
                ac_step[:60],
            )
            return

        combined_text = f"{ticket_id} {ac_step} {explanation}"
        raw_words = _re.findall(r"[a-zA-Z]{4,}", combined_text.lower())
        seen: set = set()
        keywords: list[str] = []
        for w in raw_words:
            if w not in seen:
                seen.add(w)
                keywords.append(w)
            if len(keywords) >= 12:
                break
        keywords_str = ", ".join(keywords) + f", human-guidance, hitl-selector, {ticket_id}"

        clean_actions = autorecord_serializer.serialize(action_sequence)

        dom_steps_lines: list[str] = []
        for i, pw in enumerate(clean_actions, start=1):
            dom_steps_lines.append(f"  Step {i}: {json.dumps(pw)}")

        dom_block = "\nCAPTURED DOM ACTIONS (replay these verbatim in Playwright):\n" + (
            "\n".join(dom_steps_lines) if dom_steps_lines else "  (no DOM actions captured)"
        )

        explanation_block = ""
        if explanation.strip():
            explanation_block = f"\nUSER EXPLANATION ({ticket_id}, {recorded_at}):\n{explanation.strip()}\n"

        step_slug = ac_step[:80].strip()
        block = (
            f"\n\n## WORKFLOW: {step_slug}\n"
            f"KEYWORDS: {keywords_str}\n"
            f"JIRA: {ticket_id}\n"
            "---\n"
            f"{explanation_block}"
            f"{dom_block}\n"
            "\nINSTRUCTIONS FOR THE AGENT:\n"
            "  Follow the DOM actions above VERBATIM. These were captured from a human\n"
            "  operator who manually completed this step. Use the exact selectors shown.\n"
            "  If an explanation is provided, it describes WHY this sequence works.\n"
        )

        KBWriter.append_markdown_with_lock(
            file_path=_HUMAN_GUIDANCE_KB_FILE,
            content=block,
            recorded_by=recorded_by,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)


# ---------------------------------------------------------------------------
# Public API (called by routes.py)
# ---------------------------------------------------------------------------


def set_ws_broadcaster(fn: Callable) -> None:
    """
    Inject the WebSocket broadcast function from routes.py.

    Must be called once at application startup before any runs begin.
    This breaks the circular import between routes.py and this module.

    Args
    ----
    fn : Callable
        Async function with signature:
        ``async (run_id: str, ac_step: str, ac_step_index: int, error: str) -> None``
    """
    global _WS_BROADCAST_FN
    _WS_BROADCAST_FN = fn
    logger.info("HumanTakeover: WS broadcaster registered")


def set_hitl_screenshot_broadcaster(fn: Callable) -> None:
    """Inject the HITL screencast broadcaster."""
    global _WS_SCREENSHOT_FN
    _WS_SCREENSHOT_FN = fn


def set_hitl_action_broadcaster(fn: Callable) -> None:
    """Inject the HITL action-echo broadcaster."""
    global _WS_ACTION_FN
    _WS_ACTION_FN = fn


def set_hitl_dialog_broadcaster(fn: Callable) -> None:
    """Inject the HITL dialog broadcaster."""
    global _WS_DIALOG_FN
    _WS_DIALOG_FN = fn


def register_takeover(run_id: str) -> asyncio.Event:
    """
    Create and register a new takeover Event for the given run.

    Returns
    -------
    asyncio.Event
        The event the node should await.
    """
    event = asyncio.Event()
    _takeover_events[run_id] = event
    return event


def complete_takeover(run_id: str, explanation: str = "") -> bool:
    """
    Signal that the human has completed the stuck step.

    Called by the POST /runs/{run_id}/human-takeover/done route handler.

    Args
    ----
    run_id : str
        The run to resume.
    explanation : str
        Optional description of what the user did (feeds long_term_memory).

    Returns
    -------
    bool
        True if the event was found and set, False if no pending takeover.
    """
    event = _takeover_events.get(run_id)
    if not event:
        return False
    _takeover_data[run_id] = {"explanation": explanation}
    event.set()
    logger.info("[%s] Human takeover completed: explanation='%s'", run_id, explanation[:80])
    return True


async def handle_dialog_response(run_id: str, accept: bool, prompt_text: str = "") -> bool:
    """
    Accept or dismiss a pending browser dialog for the given run.

    Args
    ----
    run_id : str
        The run ID.
    accept : bool
        True to click OK/Accept, False for Cancel/Dismiss.
    prompt_text : str
        The text to enter for 'prompt' type dialogs.

    Returns
    -------
    bool
        True if the dialog was handled, False if no pending dialog was found.
    """
    dialog = _pending_dialogs.pop(run_id, None)
    if not dialog:
        return False

    try:
        if accept:
            await dialog.accept(prompt_text)
        else:
            await dialog.dismiss()
        return True
    except Exception as e:
        logger.warning("[%s] Failed to handle dialog response: %s", run_id, e)
        return False


def skip_takeover(run_id: str) -> bool:
    """
    Signal that the user chose to skip the stuck AC step.

    Stores a special sentinel so human_takeover_node knows to advance
    the AC step index rather than retry the same step.

    Returns
    -------
    bool
        True if the event was found and set.
    """
    event = _takeover_events.get(run_id)
    if not event:
        return False
    _takeover_data[run_id] = {"explanation": "__SKIP__"}
    event.set()
    logger.info("[%s] Human takeover: step SKIPPED by user", run_id)
    return True


def is_waiting(run_id: str) -> bool:
    """Return True if this run is currently waiting for human takeover."""
    event = _takeover_events.get(run_id)
    return event is not None and not event.is_set()


def get_takeover_step(run_id: str) -> str:
    """Return the AC step text stored during the last register_takeover call."""
    return _takeover_step_text.get(run_id, "")


def _clear(run_id: str) -> None:
    _takeover_events.pop(run_id, None)
    _takeover_data.pop(run_id, None)
    _takeover_step_text.pop(run_id, None)
    _last_human_click.pop(run_id, None)
    _human_action_sequence.pop(run_id, None)
    _takeover_seq.pop(run_id, None)  # T2-b: clean up per-run tracing sequence counter

    # Cleanup navigation listeners
    cleanup_fn = _nav_listeners.pop(run_id, None)
    if cleanup_fn:
        try:
            cleanup_fn()
        except Exception:
            pass


# Internal: stores the AC step text so status endpoint can return it
_takeover_step_text: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Click & change capture helpers (Self-Learning HITL Loop)
# ---------------------------------------------------------------------------

# Per-run navigation listener cleanup callbacks
_nav_listeners: dict[str, Callable] = {}


async def _inject_click_capture_listener(page: Any, run_id: str, theme: str = "light") -> None:
    """
    Inject a JavaScript click+change-capture listener into the headed browser.

    Records the FULL action sequence (not just the last click) while the human
    is in control.  Every click, input, keyup, change, and scroll event is
    pushed over a Playwright exposeFunction bridge into Python.

    The captured sequence is stored in:
      - _last_human_click[run_id]  — last click (legacy, kept for compatibility)
      - _human_action_sequence[run_id]  — ordered list of ALL captured events

    Args
    ----
    page : playwright.async_api.Page
        The active Playwright page (headed browser window).
    run_id : str
        The current run ID — threaded through via JS so the callback stores
        results in the correct slot.
    theme : str
        The VNC theme to inject (p-theme-light or p-theme-dark). Defaults to "light".
    """
    _human_action_sequence[run_id] = []  # Reset sequence for this takeover

    # Python callback: receives action records from JS for BOTH click and change
    async def _on_human_action(action_record: dict) -> None:
        rid = action_record.get("run_id", "")
        if not rid:
            return
        # Append to sequence
        _human_action_sequence.setdefault(rid, []).append(action_record)
        # Keep legacy _last_human_click pointing to the most recent click
        if action_record.get("event_type") == "click":
            _last_human_click[rid] = action_record

        # ── Phase 1: Portal partial-capture WARN log (AC-ERROR-1) ────
        # Emit a structured WARN when the JS layer captured a portal click but
        # could not resolve the trigger element. Persists the partial record and
        # continues — never raises, never blocks the takeover session.
        if action_record.get("capture_confidence") == "portal_only":
            logger.warning(
                "[%s] hitl_portal_partial_capture: portal_class=%s trigger_empty=%s target_empty=%s",
                rid,
                action_record.get("portal_class", ""),
                not action_record.get("trigger_selector", ""),
                not action_record.get("target_text", ""),
            )

        # ── [TASK-085] Echo action to UI ─────────────────────────────
        if _WS_ACTION_FN:
            try:
                await _WS_ACTION_FN(rid, action_record)
            except Exception as echo_err:
                logger.warning("[%s] Failed to echo human action: %s", rid, echo_err)

        logger.info(
            "[%s] Human action captured: type=%s strategy=%s selector='%s'",
            rid,
            action_record.get("event_type", "?"),
            action_record.get("strategy", "?"),
            action_record.get("best_selector", "?")[:80],
        )

    # Expose the Python callback to the browser's JS context.
    # page.expose_function is idempotent on the same name — safe to re-call.
    try:
        await page.expose_function("__vqa_record_human_action__", _on_human_action)
    except Exception:
        pass  # Already exposed if page was reused across takeovers

    # Also maintain backward-compat alias for the old click-only callback
    try:
        await page.expose_function(
            "__vqa_capture_click__",
            lambda r: _on_human_action(r),
        )
    except Exception:
        pass

    # Clear stale state from a previous takeover
    _last_human_click.pop(run_id, None)

    # The JS injection payload
    js_code = """
        (run_id, theme) => {
            if (window.__vqa_listener_active__) return;
            window.__vqa_listener_active__ = true;

            // ── Phase 4: Theme Injection ─────────────────────────────
            // Inject PrimeNG theme class into body to ensure visual
            // consistency between Copilot and VNC.
            if (theme) {
                document.body.classList.remove('p-theme-light', 'p-theme-dark');
                document.body.classList.add('p-theme-' + theme);
                console.log('VNC Theme injected:', theme);
            }

            function getCssPath(el) {
                const parts = [];
                while (el && el.nodeType === 1) {
                    let selector = el.nodeName.toLowerCase();
                    if (el.id) {
                        selector += '#' + el.id;
                        parts.unshift(selector);
                        break;
                    }
                    const siblings = el.parentNode
                        ? Array.from(el.parentNode.children).filter(s => s.nodeName === el.nodeName)
                        : [];
                    if (siblings.length > 1) {
                        selector += ':nth-child(' + (Array.from(el.parentNode.children).indexOf(el) + 1) + ')';
                    }
                    parts.unshift(selector);
                    
                    // Support Shadow DOM traversal
                    if (el.parentNode) {
                        el = el.parentNode;
                    } else if (el.getRootNode && el.getRootNode().host) {
                        el = el.getRootNode().host;
                    } else {
                        el = null;
                    }
                }
                return parts.join(' > ');
            }

            // ── ADDITION 1: Portal-detection constants ─────────────────────
            // (hitl-portal-aware-click-capture Phase 1 — AC-VERIFY-1)
            const PORTAL_ALLOWLIST = [
                'p-select-overlay',
                'p-dropdown-panel',
                'p-autocomplete-panel',
                'p-tieredmenu',
                'p-menu',
                'p-popover',
                'po-sorting-dropdown-panel',
                'sort-panel',
            ];
            const PORTAL_ALLOWLIST_SELECTOR = PORTAL_ALLOWLIST.map(c => '.' + c).join(', ');
            const CDK_OVERLAY_SELECTOR = '.cdk-overlay-container';
            const FOCUS_TTL_MS = 2000;
            const SENSITIVE_INPUT_TYPES = new Set(['password']);
            const SENSITIVE_AUTOCOMPLETE = new Set(['current-password', 'new-password', 'cc-number', 'cc-csc']);

            // ── ADDITION 2: Focus/mousedown history tracker (idempotent) ──
            // Tracks the last main-document element focused/mousedown'd before a portal
            // opens — used by resolveTrigger Layer 2 (Q2-D focus fallback).
            if (!window.__vqa_focus_tracker_installed__) {
                window.__vqa_focus_tracker_installed__ = true;
                window.__vqa_last_focus__ = { el: null, ts: 0 };
                document.addEventListener('mousedown', function(e) {
                    var leaf = (e.composedPath && e.composedPath()[0]) || e.target;
                    if (!leaf) return;
                    if (leaf.closest && leaf.closest(PORTAL_ALLOWLIST_SELECTOR + ', ' + CDK_OVERLAY_SELECTOR)) return;
                    window.__vqa_last_focus__ = { el: leaf, ts: Date.now() };
                }, { capture: true });
                document.addEventListener('focusin', function(e) {
                    var el = e.target;
                    if (!el || !el.closest) return;
                    if (el.closest(PORTAL_ALLOWLIST_SELECTOR + ', ' + CDK_OVERLAY_SELECTOR)) return;
                    window.__vqa_last_focus__ = { el: el, ts: Date.now() };
                }, { capture: true });
            }

            // ── ADDITION 3: MutationObserver for portal-open detection (idempotent) ──
            // Detects when a portal container is added to the DOM and records the
            // focus snapshot at that moment — used by resolveTrigger Layer 2 (Q2-D).
            // On nav re-injection: disconnect old observer before installing fresh one
            // so AC-ASYNC-1 is satisfied (post-nav portal observer is always fresh).
            if (window.__vqa_portal_observer__) {
                try { window.__vqa_portal_observer__.disconnect(); } catch(e) {}
                window.__vqa_portal_observer__ = null;
            }
            window.__vqa_open_portals__ = new WeakMap();
            window.__vqa_portal_observer__ = new MutationObserver(function(mutations) {
                for (var mi = 0; mi < mutations.length; mi++) {
                    var m = mutations[mi];
                    for (var ni = 0; ni < m.addedNodes.length; ni++) {
                        var node = m.addedNodes[ni];
                        if (!(node instanceof Element)) continue;
                        var portal = (node.matches && node.matches(PORTAL_ALLOWLIST_SELECTOR))
                            ? node
                            : (node.querySelector && node.querySelector(PORTAL_ALLOWLIST_SELECTOR));
                        var anonPortal = !portal && (node.matches && node.matches(CDK_OVERLAY_SELECTOR))
                            ? node
                            : (!portal && node.querySelector && node.querySelector(CDK_OVERLAY_SELECTOR));
                        var detected = portal || anonPortal;
                        if (!detected) continue;
                        var now = Date.now();
                        var focusRec = window.__vqa_last_focus__;
                        var trigger = (focusRec && focusRec.el && (now - focusRec.ts) < FOCUS_TTL_MS)
                            ? focusRec.el : null;
                        window.__vqa_open_portals__.set(detected, { trigger: trigger, ts: now });
                    }
                }
            });
            window.__vqa_portal_observer__.observe(document.body, { childList: true, subtree: true });

            // ── ADDITION 4: detectPortal helper ───────────────────────────
            // Q1-D: .closest() allowlist PRIMARY + cdk-overlay-container FALLBACK.
            // Returns { portal_class, portal_el, is_anonymous }.
            function detectPortal(leaf) {
                if (!leaf || !leaf.closest) return { portal_class: '', portal_el: null, is_anonymous: false };
                var known = leaf.closest(PORTAL_ALLOWLIST_SELECTOR);
                if (known) {
                    for (var i = 0; i < PORTAL_ALLOWLIST.length; i++) {
                        if (known.classList.contains(PORTAL_ALLOWLIST[i])) {
                            return { portal_class: '.' + PORTAL_ALLOWLIST[i], portal_el: known, is_anonymous: false };
                        }
                    }
                }
                var anon = leaf.closest(CDK_OVERLAY_SELECTOR);
                if (anon) {
                    return { portal_class: '', portal_el: anon, is_anonymous: true };
                }
                return { portal_class: '', portal_el: null, is_anonymous: false };
            }

            // ── ADDITION 5: resolveTrigger helper (Q2-D layered) ─────────
            // Layer 1: aria-owns / aria-controls reverse lookup.
            // Layer 2: MutationObserver-time focus snapshot (WeakMap).
            // Layer 3: current focus-history within TTL.
            // Returns { selector, confidence }.
            function resolveTrigger(portalEl) {
                if (!portalEl) return { selector: '', confidence: 'none' };
                // Layer 1: aria reverse lookup
                if (portalEl.id) {
                    var safeId = portalEl.id.replace(/"/g, '\\"');
                    var ariaMatch = document.querySelector(
                        '[aria-owns="' + safeId + '"], [aria-controls="' + safeId + '"]'
                    );
                    if (ariaMatch) return { selector: getCssPath(ariaMatch), confidence: 'aria' };
                }
                // Layer 2: MutationObserver-time snapshot
                var rec = window.__vqa_open_portals__.get(portalEl);
                if (rec && rec.trigger && document.contains(rec.trigger)) {
                    return { selector: getCssPath(rec.trigger), confidence: 'focus' };
                }
                // Layer 3: current focus history within TTL
                var focus = window.__vqa_last_focus__;
                if (focus && focus.el && document.contains(focus.el) &&
                        (Date.now() - focus.ts) < FOCUS_TTL_MS) {
                    return { selector: getCssPath(focus.el), confidence: 'mutation' };
                }
                return { selector: '', confidence: 'none' };
            }

            // ── ADDITION 6: extractTargetText (PII-aware) ────────────────
            // Extracts visible text of the clicked portal option, masking
            // sensitive input types per the PII policy.
            function extractTargetText(el) {
                if (!el) return '';
                var inputType = (el.type || '').toLowerCase();
                var autocomplete = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
                if (SENSITIVE_INPUT_TYPES.has(inputType) || SENSITIVE_AUTOCOMPLETE.has(autocomplete)) {
                    return '';
                }
                return (el.innerText || el.textContent || '').trim().slice(0, 80);
            }

            // ── ADDITION 7: deriveCaptureConfidence ───────────────────────
            // Single source of truth for the coarse serializer-branching enum
            // (architecture doc §Interfaces from Algorithm Doc).
            // "none"        → not a portal click; serializer uses byte-identical path
            // "full"        → primeng_dropdown (all three replay-critical fields present)
            // "portal_only" → partial capture; serializer uses scoped click fallback
            function deriveCaptureConfidence(portalInfo, triggerInfo, targetText) {
                if (!portalInfo.portal_el) return 'none';
                if (portalInfo.is_anonymous) return 'portal_only';
                if (portalInfo.portal_class && triggerInfo.selector && targetText) return 'full';
                return 'portal_only';
            }

            function buildRecord(el, eventType, extraValue, eventObj) {
                // Support Shadow DOM leaf target extraction
                let targetEl = el;
                if (eventObj && typeof eventObj.composedPath === 'function') {
                    const path = eventObj.composedPath();
                    if (path && path.length > 0) {
                        targetEl = path[0];
                    }
                }
                const elToUse = targetEl || el;

                if (!elToUse || !elToUse.tagName) {
                   if (eventType === 'scroll') {
                       return {
                           run_id: run_id,
                           event_type: 'scroll',
                           tag: 'window',
                           best_selector: 'window',
                           strategy: 'window',
                           value: extraValue,
                           timestamp: new Date().toISOString()
                       };
                   }
                   return null;
                }

                const tagName = elToUse.tagName.toLowerCase();

                // Priority 1: data-testid (most stable)
                const testId = elToUse.getAttribute('data-testid')
                    || (elToUse.closest('[data-testid]') || {}).getAttribute('data-testid');

                // Priority 2: aria-label
                const ariaLabel = elToUse.getAttribute('aria-label')
                    || (elToUse.closest('[aria-label]') || {}).getAttribute('aria-label');

                // Priority 3: role + visible text
                const role = elToUse.getAttribute('role')
                    || (elToUse.closest('[role]') || {}).getAttribute('role');
                const innerText = (elToUse.innerText || elToUse.textContent || '').trim().slice(0, 80);

                // Resolve best selector
                let best_selector = '';
                let strategy = '';
                if (testId) {
                    best_selector = '[data-testid="' + testId + '"]';
                    strategy = 'get_by_test_id';
                } else if (ariaLabel) {
                    best_selector = '[aria-label="' + ariaLabel + '"]';
                    strategy = 'get_by_label';
                } else if (role && innerText) {
                    best_selector = innerText;
                    strategy = 'get_by_role:' + role;
                } else if (innerText) {
                    best_selector = innerText;
                    strategy = 'get_by_text';
                } else {
                    best_selector = getCssPath(elToUse);
                    strategy = 'css';
                }

                // ── Portal-aware field computation (Phase 1) ─────────────
                // Only computed for click events — other event types pass through unchanged.
                var portalInfo = { portal_class: '', portal_el: null, is_anonymous: false };
                var triggerInfo = { selector: '', confidence: 'none' };
                var targetText = '';
                var captureConfidence = 'none';
                if (eventType === 'click') {
                    portalInfo = detectPortal(elToUse);
                    if (portalInfo.portal_el) {
                        triggerInfo = resolveTrigger(portalInfo.portal_el);
                        targetText = extractTargetText(elToUse);
                    }
                    captureConfidence = deriveCaptureConfidence(portalInfo, triggerInfo, targetText);
                }

                return {
                    run_id: run_id,
                    event_type: eventType,
                    tag: tagName,
                    test_id: testId || '',
                    aria_label: ariaLabel || '',
                    role: role || '',
                    inner_text: innerText,
                    best_selector: best_selector,
                    strategy: strategy,
                    css_path: getCssPath(elToUse),
                    value: extraValue || '',
                    timestamp: new Date().toISOString(),
                    // Portal-aware fields (Phase 1 — always present on click events;
                    // capture_confidence='none' means non-portal, serializer ignores).
                    portal_class: portalInfo.portal_class,
                    trigger_selector: triggerInfo.selector,
                    target_text: targetText,
                    trigger_resolution_confidence: triggerInfo.confidence,
                    is_anonymous_portal: portalInfo.is_anonymous,
                    capture_confidence: captureConfidence,
                };
            }

            // Capture clicks
            document.addEventListener('click', function(e) {
                const record = buildRecord(e.target, 'click', null, e);
                if (record) window.__vqa_record_human_action__(record);
            }, { capture: true });

            // Capture input/change events (typing, dropdowns, checkboxes)
            let changeTimer;
            document.addEventListener('change', function(e) {
                const el = e.target;
                if (!el) return;
                clearTimeout(changeTimer);
                changeTimer = setTimeout(() => {
                    const val = el.value || el.checked || '';
                    const record = buildRecord(el, 'change', String(val), e);
                    if (record) window.__vqa_record_human_action__(record);
                }, 300);
            }, { capture: true });

            // Capture keyup (for granular typing — debounced)
            let keyupTimer;
            document.addEventListener('keyup', function(e) {
                const el = e.target;
                if (!el || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA')) return;
                clearTimeout(keyupTimer);
                keyupTimer = setTimeout(() => {
                    const record = buildRecord(el, 'keyup', el.value, e);
                    if (record) window.__vqa_record_human_action__(record);
                }, 800);
            }, { capture: true });

            // Capture scroll (debounced)
            let scrollTimer;
            window.addEventListener('scroll', function(e) {
                clearTimeout(scrollTimer);
                scrollTimer = setTimeout(() => {
                    const val = window.scrollX + ',' + window.scrollY;
                    const record = buildRecord(null, 'scroll', val, e);
                    if (record) window.__vqa_record_human_action__(record);
                }, 500);
            }, { capture: true, passive: true });
        }
    """

    # 1. Add init script for context-wide future injection (popup & frame load resilience)
    try:
        init_script = f"const run_id = '{run_id}'; const theme = '{theme}'; ({js_code})(run_id, theme);"
        await page.add_init_script(script=init_script)
    except Exception as e:
        logger.debug("[%s] add_init_script failed: %s", run_id, e)

    # 2. Main injection evaluated on the page (backward compatible for mock tests)
    try:
        await page.evaluate("() => { window.__vqa_listener_active__ = false; }")
        await page.evaluate(js_code, run_id, theme)
        logger.info("[%s] Multi-event capture listener injected into main page (theme=%s)", run_id, theme)
    except Exception as e:
        logger.debug("[%s] main page evaluate failed: %s", run_id, e)

    # 3. Initial injection on ALL currently existing sub-frames in the page
    try:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                await frame.evaluate("() => { window.__vqa_listener_active__ = false; }")
                await frame.evaluate(js_code, run_id, theme)
                logger.info("[%s] Multi-event capture listener injected into subframe: url=%s theme=%s", run_id, frame.url[:60], theme)
            except Exception as frame_err:
                logger.debug("[%s] Failed initial evaluate in frame: %s", run_id, frame_err)
    except Exception as frames_err:
        logger.debug("[%s] page.frames iteration failed: %s", run_id, frames_err)

    # 4. Navigation re-injection hook for navigated frame and children
    async def re_inject_on_nav(frame):
        try:
            # Give the frame a moment to load/render before re-injecting
            await asyncio.sleep(0.5)
            if not page.is_closed():
                try:
                    await frame.evaluate("() => { window.__vqa_listener_active__ = false; }")
                    await frame.evaluate(js_code, run_id, theme)
                    logger.info("[%s] Re-injected listener after navigation on frame: name=%s url=%s theme=%s", run_id, frame.name, frame.url[:60], theme)
                except Exception as frame_err:
                    logger.debug("[%s] Failed to evaluate in navigated frame: %s", run_id, frame_err)

                # Also handle child frames
                for child in frame.child_frames:
                    try:
                        await child.evaluate("() => { window.__vqa_listener_active__ = false; }")
                        await child.evaluate(js_code, run_id, theme)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("[%s] Failed to re-inject listener on navigation: %s", run_id, e)

    # Register navigation listener
    page.on("framenavigated", re_inject_on_nav)

    # 5. Instrument any popups/new pages opened in this browser context during takeover
    async def on_popup(popup):
        try:
            await popup.expose_function("__vqa_record_human_action__", _on_human_action)
        except Exception:
            pass
        try:
            popup_init = f"const run_id = '{run_id}'; const theme = '{theme}'; ({js_code})(run_id, theme);"
            await popup.add_init_script(script=popup_init)
            for f in popup.frames:
                try:
                    await f.evaluate("() => { window.__vqa_listener_active__ = false; }")
                    await f.evaluate(js_code, run_id, theme)
                except Exception:
                    pass
            logger.info("[%s] Instrumented new popup page (theme=%s)", run_id, theme)
        except Exception as popup_err:
            logger.warning("[%s] Failed to instrument popup page: %s", run_id, popup_err)

    is_mock = False
    if hasattr(page, "context"):
        if hasattr(page.context, "_mock_name") or type(page.context).__name__ in ("Mock", "MagicMock", "AsyncMock"):
            is_mock = True

    if not is_mock:
        try:
            page.context.on("page", on_popup)
        except Exception as e:
            logger.debug("[%s] Failed to register popup context listener: %s", run_id, e)

    # Store cleanup function
    def cleanup():
        try:
            page.remove_listener("framenavigated", re_inject_on_nav)
        except Exception:
            pass
        if not is_mock:
            try:
                page.context.remove_listener("page", on_popup)
            except Exception:
                pass
        # Disconnect the portal-open MutationObserver (Phase 1 — AC-ASYNC-1).
        # The ADDITION 3 JS logic disconnects and re-creates on nav re-injection;
        # this cleanup() call ensures tear-down when the takeover session ends.
        try:
            page.evaluate("() => { window.__vqa_portal_observer__ && window.__vqa_portal_observer__.disconnect(); }")
        except Exception:
            pass

    _nav_listeners[run_id] = cleanup


async def _save_to_learned_workflows(
    ac_step: str,
    action_sequence: list[dict],
    ticket_id: str,
    run_id: str = "",
) -> None:
    """
    Persist a human-recorded action sequence to knowledge/blueprints/learned_workflows.json.

    Phase 5: routes the write through ``KBWriter.append_with_lock`` so
    concurrent takeovers on the same host serialize under ``fcntl.flock``
    and every entry is stamped with ``recorded_by`` / ``recorded_at``.
    """
    from backend.kb.writer import KBWriter

    recorded_by = _resolve_recorded_by(run_id)
    compact_actions = autorecord_serializer.serialize(action_sequence)

    def _write() -> None:
        KBWriter.append_with_lock(
            file_path=_LEARNED_WORKFLOWS_FILE,
            key=ac_step,
            value={
                "ticket_id": ticket_id,
                "action_sequence": compact_actions,
            },
            recorded_by=recorded_by,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)
    logger.info(
        "Learned workflows: saved %d-action sequence for step '%s...' → %s (recorded_by=%s)",
        len(action_sequence),
        ac_step[:40],
        _LEARNED_WORKFLOWS_FILE,
        recorded_by,
    )


async def _append_to_kb_staging(
    ac_step: str,
    pw_action: dict,
    ticket_id: str,
    run_id: str = "",
) -> None:
    """
    Append a human-captured selector to the KB staging JSONL file.

    Phase 5: routes the write through ``KBWriter.append_jsonl_with_lock`` so
    concurrent takeovers can't corrupt the JSONL and every record carries
    ``recorded_by`` / ``recorded_at`` attribution.
    """
    from backend.kb.writer import KBWriter

    recorded_by = _resolve_recorded_by(run_id)
    record = {
        "source": "human_takeover",
        "ticket_id": ticket_id,
        "ac_step": ac_step,
        "pw_action": pw_action,
    }

    def _write() -> None:
        KBWriter.append_jsonl_with_lock(
            file_path=_KB_STAGING_FILE,
            record=record,
            recorded_by=recorded_by,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)
    logger.info(
        "KB staging: appended human selector for step '%s...' → %s (recorded_by=%s)",
        ac_step[:40],
        _KB_STAGING_FILE,
        recorded_by,
    )


async def _write_to_vsuite_actions_kb(
    ac_step: str,
    action_sequence: list[dict],
    ticket_id: str,
    explanation: str = "",
    run_id: str = "",
) -> None:
    """
    Auto-generate a human-readable KB workflow block and append it to
    knowledge/vSuite-actions.md.

    Phase 5: routes the append through ``KBWriter.append_markdown_with_lock``
    so concurrent writers serialize under ``fcntl.flock`` and every block
    is prefixed with a ``<!-- recorded_by: ... -->`` attribution comment.
    """
    from backend.kb.writer import KBWriter

    recorded_by = _resolve_recorded_by(run_id)

    def _build_and_write() -> None:
        if not action_sequence:
            logger.info(
                "KB auto-update skipped for '%s': no DOM actions captured during takeover",
                ac_step[:60],
            )
            return

        _KB_VSUITE_ACTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing_text = ""
        if _KB_VSUITE_ACTIONS_FILE.exists():
            existing_text = _KB_VSUITE_ACTIONS_FILE.read_text(encoding="utf-8")
        dedup_key = ac_step[:60].strip()
        if dedup_key in existing_text:
            logger.info(
                "KB auto-update: AC step already in vSuite-actions.md, skipping: '%s'",
                dedup_key,
            )
            return

        import re

        raw_words = re.findall(r"[a-zA-Z]{4,}", ac_step.lower())
        seen: set = set()
        keywords: list[str] = []
        for w in raw_words:
            if w not in seen:
                seen.add(w)
                keywords.append(w)
            if len(keywords) >= 8:
                break

        recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = [
            "",
            "---",
            "",
            f"## WORKFLOW: AUTO-LEARNED — {ac_step[:100]}",
            f"KEYWORDS: {', '.join(keywords)}, human-learned, auto-learned, human, operator",
            f"SOURCE: Human Takeover — ticket {ticket_id}, recorded {recorded_at}",
            "---",
            f"A human operator completed this step manually during a vQA run ({ticket_id}).",
            "The action sequence below was captured automatically and should be used",
            "verbatim on future runs that encounter this exact AC step.",
            "",
        ]

        if explanation.strip():
            lines += [
                "HUMAN EXPLANATION:",
                f"  {explanation.strip()}",
                "",
            ]

        clean_actions = autorecord_serializer.serialize(action_sequence)

        if clean_actions:
            lines.append("═" * 42)
            lines.append("CAPTURED ACTION SEQUENCE")
            lines.append("═" * 42)
            for i, pw in enumerate(clean_actions, 1):
                lines.append(f"  Step {i}: {json.dumps(pw)}")
            lines.append("")
        else:
            lines += [
                "NOTE: No browser actions were captured by the JS listener.",
                f"Human explanation: {explanation or '(none provided)'}",
                "",
            ]

        lines += [
            "VERIFICATION:",
            "  Wait 500ms after the last step for Angular to re-render.",
            "",
        ]

        block = "\n".join(lines)
        KBWriter.append_markdown_with_lock(
            file_path=_KB_VSUITE_ACTIONS_FILE,
            content=block,
            recorded_by=recorded_by,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _build_and_write)
    logger.info(
        "KB auto-update: appended workflow for '%s...' → %s (recorded_by=%s)",
        ac_step[:40],
        _KB_VSUITE_ACTIONS_FILE,
        recorded_by,
    )


async def human_takeover_node(state: VQAState) -> dict:
    """
    LangGraph node: pause the run and wait for human interaction.

    This node:
    1. Broadcasts a WebSocket event to the frontend (via injected callback)
    2. Awaits an asyncio.Event — the ONLY suspended coroutine; event loop
       remains free for HTTP/WebSocket requests
    3. On resume:
       a. If user clicked "Done" — resets fail counters, writes learning,
          returns _next_node: "planner"
       b. If user clicked "Skip" — marks step as skipped, advances AC index,
          returns _next_node: "planner"
       c. If timeout (5 min) — routes to reporter

    Args
    ----
    state : VQAState
        Current run state.

    Returns
    -------
    dict
        Partial state update with routing and learning data.
    """
    run_id: str = state["run_id"]
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    current_step = ac_steps[ac_index] if ac_index < len(ac_steps) else "?"
    last_error = state.get("last_error", "stuck after repeated failures")

    logger.info(
        "[%s] HUMAN TAKEOVER — AC step %d/%d: %s",
        run_id,
        ac_index + 1,
        len(ac_steps),
        current_step[:80],
    )

    # Store for status endpoint
    _takeover_step_text[run_id] = current_step

    # T2-b: Track the tracing sequence number for this takeover. -1 = tracing did not start.
    _current_takeover_seq: int = -1

    # ── 1. Inject click-capture listener into headed browser ──────────
    # Capture the JavaScript exposeFunction BEFORE broadcasting/waiting so
    # any click the human makes during takeover is captured automatically.
    # If the page closed (e.g. a dialog closed the tab), try to recover
    # by opening the current URL in a new page on the same context.
    try:
        manager = get_manager(run_id)
        page = manager.page

        if page is None or page.is_closed():
            logger.warning(
                "[%s] Page is closed — attempting to open a new page for click capture.",
                run_id,
            )
            try:
                page = await manager._context.new_page()
                manager.page = page
                # Navigate back to the app so the human has a live browser
                target = state.get("current_page_url") or state.get("target_url", "")
                if target:
                    await page.goto(target, wait_until="networkidle", timeout=20000)
            except Exception as nav_err:
                logger.warning("[%s] Could not reopen page: %s", run_id, nav_err)
                page = None

        if page and not page.is_closed():
            await _inject_click_capture_listener(page, run_id, theme=settings.vnc_theme)

            # ── T2-b: Start Playwright tracing session ────────────────────────
            # Captures every CDP-level action (including PrimeNG portal clicks
            # and OS-native <select> interactions that the JS listener misses).
            # The trace is stopped and parsed into an ActionRecipe on DONE.
            _current_takeover_seq = _takeover_seq.get(run_id, 0)
            _takeover_seq[run_id] = _current_takeover_seq + 1
            try:
                await page.context.tracing.start(screenshots=True, snapshots=True, sources=False)
                logger.info("[%s] Playwright tracing started (takeover_seq=%d)", run_id, _current_takeover_seq)
            except Exception as trace_start_err:
                logger.warning("[%s] Could not start Playwright tracing: %s", run_id, trace_start_err)
                _current_takeover_seq = -1  # sentinel: skip stop+parse on DONE

            # ── [TASK-085] Dialog Interception ───────────────────────────
            async def on_dialog(dialog):
                _pending_dialogs[run_id] = dialog
                logger.info("[%s] Intercepted browser dialog: %s", run_id, dialog.message)
                if _WS_DIALOG_FN:
                    try:
                        await _WS_DIALOG_FN(
                            run_id=run_id,
                            message=dialog.message,
                            dialog_type=dialog.type,
                            default_value=dialog.default_value,
                        )
                    except Exception as dial_err:
                        logger.warning("[%s] Failed to broadcast dialog event: %s", run_id, dial_err)

            page.on("dialog", on_dialog)
    except Exception as e:
        logger.warning("[%s] Could not inject click-capture listener: %s", run_id, e)
        _current_takeover_seq = -1  # tracing didn't start; skip parse

    # ── 2. Broadcast WS event to the frontend BEFORE awaiting ────────
    # Build a context-aware instructions string:
    # - credential failure → tell the user which account to log in as
    # - file-picker → tell the user to pick a file
    # - default → generic instructions
    instructions_str = ""
    if "invalid user" in last_error.lower() or "credentials unknown" in last_error.lower():
        # Try to extract who was assigned from action history
        from backend.engine.evaluator import _extract_assigned_voicer

        voicer_name = _extract_assigned_voicer(state)
        if voicer_name:
            instructions_str = (
                f"The agent doesn't know '{voicer_name}'s login credentials. "
                f"Please log in as {voicer_name} in the browser window, then click ✅ Done — "
                f"the agent will learn this account for future runs."
            )
        else:
            instructions_str = (
                "The agent doesn't know the credentials for this role. "
                "Please log in manually in the browser window, then click ✅ Done."
            )
    elif "file picker" in last_error.lower() or "cannot be automated" in last_error.lower():
        instructions_str = (
            "The agent cannot control the file picker dialog. "
            "Please click Browse/Upload in the browser, select your file, and click ✅ Done when uploaded."
        )

    # ── Resolve noVNC URL for dynamic interactive stream (Phase 1) ────
    # Uses the stored request metadata to build a VNC URL that matches the
    # operator's current connection protocol and host.
    novnc_url = None
    if state.get("execution_mode") == "interactive":
        vnc_builder = VncUrlBuilder()
        novnc_url = vnc_builder.build_url(
            mode="interactive",
            host_header=state.get("request_host"),
            protocol=state.get("request_protocol"),
        )

    if _WS_BROADCAST_FN:
        try:
            await _WS_BROADCAST_FN(
                run_id=run_id,
                ac_step=current_step,
                ac_step_index=ac_index,
                error_message=last_error,
                instructions=instructions_str,
                novnc_url=novnc_url,
            )
        except Exception as e:
            logger.warning("[%s] Failed to broadcast human_takeover WS event: %s", run_id, e)

    # ── [TASK-085] Live CDP Screencast ───────────────────────────────
    cdp_session = None
    if page and not page.is_closed():
        try:
            cdp_session = await manager.get_cdp_session()

            async def on_screencast_frame(event: dict):
                if _WS_SCREENSHOT_FN:
                    await _WS_SCREENSHOT_FN(run_id, event["data"])
                try:
                    await cdp_session.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
                except:
                    pass

            cdp_session.on("Page.screencastFrame", on_screencast_frame)
            # format=jpeg for smaller payload, everyNthFrame=1 for max fps
            await cdp_session.send(
                "Page.startScreencast", {"format": "jpeg", "quality": 80, "everyNthFrame": 1}
            )
            logger.info("[%s] CDP Screencast started (target: 10fps+)", run_id)
        except Exception as cdp_err:
            logger.warning("[%s] Could not start CDP screencast: %s", run_id, cdp_err)

    # ── 3. Register event and wait (suspends coroutine, not event loop) ──
    event = register_takeover(run_id)

    try:
        await asyncio.wait_for(event.wait(), timeout=300)  # 5 min max
    except asyncio.TimeoutError:
        logger.warning("[%s] Human takeover timed out (5 min) — routing to reporter", run_id)
        _clear(run_id)
        return {
            "_next_node": "reporter",
            "awaiting_human_takeover": False,
            "agent_critique": "Human takeover timed out (5 minutes). Run terminated.",
        }
    finally:
        # ── [TASK-085] Stop Screencast ─────────────────────────────
        if cdp_session:
            try:
                # Stop screencast and detach session to free resources
                await cdp_session.send("Page.stopScreencast")
                await cdp_session.detach()
                logger.info("[%s] CDP Screencast stopped and session detached", run_id)
            except Exception as stop_err:
                logger.warning("[%s] Error stopping CDP screencast: %s", run_id, stop_err)

    # ── 4. Human responded — read their explanation ───────────────────
    data = _takeover_data.get(run_id, {})
    explanation = data.get("explanation", "")

    # ── 4a. Harvest ALL captured data BEFORE clearing the slot ───────────
    # _clear() wipes _last_human_click, _human_action_sequence, and
    # _takeover_data — so pop everything we need FIRST.
    captured_click = _last_human_click.pop(run_id, None)
    captured_sequence = _human_action_sequence.pop(run_id, [])
    _clear(run_id)

    # ── T2-b: Stop Playwright tracing + parse to ActionRecipe ─────────
    # Done AFTER harvesting captured_sequence (above) so the JS-listener
    # data and the trace are both available. Parsing is synchronous/in-band
    # so the "every HITL → Recipe" guarantee holds (AC-INTEGRATION-1).
    if _current_takeover_seq >= 0:
        try:
            mgr_for_trace = get_manager(run_id)
            page_for_trace = mgr_for_trace.page if mgr_for_trace else None
            if page_for_trace and not page_for_trace.is_closed():
                HITL_TRACES_DIR.mkdir(parents=True, exist_ok=True)
                zip_path = HITL_TRACES_DIR / f"{run_id}-{_current_takeover_seq}.zip"
                await page_for_trace.context.tracing.stop(path=str(zip_path))
                logger.info("[%s] Playwright trace saved: %s", run_id, zip_path)

                # Parse the trace into an ActionRecipe (Option 1A: synchronous)
                try:
                    from backend.engine.hitl_trace_parser import parse_trace

                    parse_result = await parse_trace(
                        zip_path=zip_path,
                        ac_step_goal=current_step,
                        run_id=run_id,
                        takeover_seq=_current_takeover_seq,
                    )
                    if not parse_result.ok:
                        logger.warning(
                            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
                            run_id,
                            parse_result.failure_reason,
                            parse_result.failure_detail,
                            parse_result.zip_path,
                        )
                    else:
                        logger.info(
                            "[%s] hitl_trace_parse_ok: %d actions → recipe=%s",
                            run_id,
                            len(parse_result.actions),
                            parse_result.recipe_yaml_path,
                        )
                except Exception as parse_err:
                    # Belt-and-suspenders: parse_trace is designed not to raise,
                    # but catch here so tracing never crashes the takeover node.
                    logger.warning("[%s] hitl_trace_parser exception: %s", run_id, parse_err)
            else:
                logger.warning("[%s] Page closed after HITL — skipping trace stop", run_id)
        except Exception as trace_stop_err:
            logger.warning("[%s] Could not stop Playwright tracing: %s", run_id, trace_stop_err)

    # ── 4b. SKIP ──────────────────────────────────────────────────────
    if explanation == "__SKIP__":
        logger.info("[%s] AC step %d skipped by user", run_id, ac_index + 1)
        new_ac_index = ac_index + 1
        skipped_note = f"AC step {ac_index + 1} skipped by human operator: '{current_step[:80]}'"

        # Return only the NEW integer index — ac_steps_completed uses operator.add
        # so returning the full list would duplicate all previous entries.
        # The DONE guardrail checks integer indices; never append step text here.
        if new_ac_index >= len(ac_steps):
            return {
                "_next_node": "reporter",
                "awaiting_human_takeover": False,
                "retry_count": 0,
                "ac_step_index": new_ac_index,
                "ac_steps_completed": [ac_index],
                "ac_step_fail_counts": {},
                "current_ac_step_action_count": 0,  # Reset circuit breaker
                "vision_mode": "dom",  # Fresh start for next step
                "long_term_memory": [skipped_note],
            }
        return {
            "_next_node": "planner",
            "awaiting_human_takeover": False,
            "retry_count": 0,
            "ac_step_index": new_ac_index,
            "ac_steps_completed": [ac_index],
            "ac_step_fail_counts": {},
            "current_ac_step_action_count": 0,  # Reset circuit breaker
            "vision_mode": "dom",  # Fresh start for next step
            "agent_critique": "",
            "last_error": "",
            "long_term_memory": [skipped_note],
        }

    # ── 4c. DONE — process captured sequence + write to memory ──────────
    logger.info("[%s] Human takeover done — resuming planner", run_id)

    new_memories: list[str] = []
    ticket_id = state.get("jira_ticket", {}).get("ticket_id", "")

    # captured_sequence and captured_click were already popped before _clear()

    # Save the full sequence to learned_workflows.json if we captured anything
    if captured_sequence:
        try:
            await _save_to_learned_workflows(
                ac_step=current_step,
                action_sequence=captured_sequence,
                ticket_id=ticket_id,
                run_id=run_id,
            )
            logger.info(
                "[%s] Saved %d-step human action sequence for AC step '%s'",
                run_id,
                len(captured_sequence),
                current_step[:60],
            )
        except Exception as seq_err:
            logger.error("[%s] Failed to save learned workflow sequence: %s", run_id, seq_err)

    # Auto-write a KB workflow block to vSuite-actions.md so future runs
    # benefit from the human's knowledge immediately, without any manual sync.
    try:
        await _write_to_vsuite_actions_kb(
            ac_step=current_step,
            action_sequence=captured_sequence,
            ticket_id=ticket_id,
            explanation=explanation,
            run_id=run_id,
        )
    except Exception as kb_err:
        logger.error("[%s] Failed to auto-write KB entry: %s", run_id, kb_err)

    # ── Combined HITL knowledge base entry ───────────────────────────────────
    # Write a combined entry that co-locates the text explanation AND the
    # DOM action sequence so future KB retrievals return both in one hit.
    # This is the fix for the P0 bug where only one of the two was retrievable.
    try:
        await _save_combined_hitl_entry(
            ac_step=current_step,
            explanation=explanation,
            action_sequence=captured_sequence,
            ticket_id=ticket_id,
            run_id=run_id,
        )
        logger.info(
            "[%s] Combined HITL KB entry written for ticket='%s' step='%s'",
            run_id,
            ticket_id,
            current_step[:60],
        )
    except Exception as combined_err:
        logger.error("[%s] Failed to write combined HITL KB entry: %s", run_id, combined_err)

    if captured_click:
        selector = captured_click.get("best_selector", "")
        strategy = captured_click.get("strategy", "get_by_text")
        inner_text = captured_click.get("inner_text", "")
        aria_label = captured_click.get("aria_label", "")
        test_id = captured_click.get("test_id", "")

        # Build Playwright-compatible action dict
        if strategy.startswith("get_by_role:"):
            role = strategy.split(":", 1)[1]
            pw_action = {"action": "click", "strategy": "get_by_role", "role": role, "name": inner_text}
        elif strategy == "get_by_label":
            pw_action = {"action": "click", "strategy": "get_by_label", "name": aria_label or selector}
        elif strategy == "get_by_test_id":
            pw_action = {"action": "click", "strategy": "get_by_test_id", "name": test_id or selector}
        elif strategy == "get_by_text":
            pw_action = {"action": "click", "strategy": "get_by_text", "name": selector}
        else:
            pw_action = {"action": "click", "strategy": "css", "name": selector}

        # ── Write to SQLite persistent memory ─────────────────────────────
        # situation = the AC step text so get_few_shot_examples() can match
        # it by word-overlap on future runs that encounter the same step.
        try:
            from backend.memory.persistent import persistent_memory

            persistent_memory.record(
                situation=current_step,  # ← step text, not "human completed:"
                strategy_tried=json.dumps(pw_action),
                worked=True,
                strategy_fix="",
                ac_step=current_step,
                ticket_id=ticket_id,
            )
            logger.info(
                "[%s] Selector written to persistent memory: strategy=%s selector='%s'",
                run_id,
                strategy,
                selector[:60],
            )
        except Exception as e:
            logger.error("[%s] Failed to write to persistent memory: %s", run_id, e)

        # ── Write to KB staging file ──────────────────────────────────
        try:
            await _append_to_kb_staging(
                ac_step=current_step,
                pw_action=pw_action,
                ticket_id=ticket_id,
                run_id=run_id,
            )
        except Exception as e:
            logger.error("[%s] Failed to write to KB staging: %s", run_id, e)

        # ── Write to Selector Registry (instant, persistent) ──────────────
        # Writes the HITL-confirmed selector directly to selector_registry.json
        # so the planner can query it on the next tick — no kb-refresh needed.
        try:
            from backend.kb.selector_registry import selector_registry as _sel_reg

            _hitl_name = inner_text or aria_label or test_id or selector
            _hitl_role = ""
            _hitl_strategy = "get_by_text"
            if strategy.startswith("get_by_role:"):
                _hitl_strategy = "get_by_role"
                _hitl_role = strategy.split(":", 1)[1]
            elif strategy == "get_by_label":
                _hitl_strategy = "get_by_label"
            elif strategy == "get_by_test_id":
                _hitl_strategy = "css_selector"
            elif strategy in ("css", "css_selector"):
                _hitl_strategy = "css_selector"

            # ── Phase 1: Portal-aware selector registry context ───────────
            # Encode portal metadata in the free-form `context` string using the
            # grammar: portal:<class>|trigger:<selector>|ac:<step[:80]>
            # This preserves the existing 6-arg signature (AC-VERIFY-5 / schema-compat).
            _portal_class = captured_click.get("portal_class", "") if captured_click else ""
            _trigger = captured_click.get("trigger_selector", "") if captured_click else ""
            _confidence = captured_click.get("capture_confidence", "none") if captured_click else "none"

            if _confidence in ("full", "portal_only") and _portal_class:
                # Portal click: use semantic locator scoped to the portal container.
                _sel_context = f"portal:{_portal_class}|trigger:{_trigger}|ac:{current_step[:80]}"
                _sel_strategy = "get_by_text"
                _sel_name = (
                    (captured_click.get("target_text") if captured_click else None)
                    or inner_text
                    or aria_label
                    or ""
                )
            else:
                # Non-portal click: unchanged from pre-feature behavior (AC-VERIFY-5).
                _sel_context = f"AC step: {current_step[:100]}"
                _sel_strategy = _hitl_strategy
                _sel_name = _hitl_name

            _sel_reg.record_hitl_selector(
                description=f"HITL: {current_step[:70]}",
                selector=selector,
                strategy=_sel_strategy,
                context=_sel_context,
                role=_hitl_role,
                name=_sel_name,
            )
            logger.info(
                "[%s] HITL selector registered: strategy=%s selector='%s'",
                run_id,
                _hitl_strategy,
                selector[:60],
            )
        except Exception as e:
            logger.error("[%s] Failed to write HITL selector to registry: %s", run_id, e)

        new_memories.append(
            f"HUMAN CLICK on AC step {ac_index + 1} ('{current_step[:60]}'): "
            f"Human clicked '{selector}' using strategy '{strategy}'. "
            f"Playwright action: {json.dumps(pw_action)}. "
            f"Agent MUST use this EXACT selector if this step is retried."
        )
        (
            f"Human completed step {ac_index + 1}. "
            f"The human clicked: '{selector}' (strategy: '{strategy}'). "
            f"USE THIS EXACT SELECTOR if you need to interact with this element. "
            f"Continue from the current page state."
        )
    else:
        # No click captured (human may have typed, keyboard, or listener failed).
        # Still write a memory entry so the agent learns this step is difficult.
        explanation_text = explanation.strip()
        note = explanation_text or "Human completed this step manually (no click captured)."

        try:
            from backend.memory.persistent import persistent_memory

            persistent_memory.record(
                situation=current_step,  # match on step text, not "human completed:"
                strategy_tried="human_manual",
                worked=True,
                strategy_fix=note[:500],  # ← extended to 500 chars to preserve full instructions
                ac_step=current_step,
                ticket_id=ticket_id,
            )
            logger.info("[%s] Human manual memory recorded (no click capture).", run_id)
        except Exception as e:
            logger.error("[%s] Failed to record manual memory: %s", run_id, e)

        # ── Build a high-priority guidance memory block ──────────────────
        # The explanation text the user typed is the most valuable signal we have.
        # Write it as a CRITICAL OVERRIDE so the planner treats it as mandatory,
        # not just a hint that can be ignored in favour of persistent memory.
        if explanation_text:
            # Parse the explanation into a structured instruction the LLM can act on
            guidance_mem = (
                f"🚨 CRITICAL HUMAN GUIDANCE for AC step {ac_index + 1} "
                f"('{current_step[:80]}'):\n"
                f"  The vQA agent failed, and a human operator intervened.\n"
                f"  The human's EXACT instruction (must be followed VERBATIM):\n"
                f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  {explanation_text}\n"
                f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  DO NOT use the previously-failed approach. Implement exactly "
                f"what the human described above."
            )
            new_memories.append(guidance_mem)
            logger.info(
                "[%s] Human guidance stored as CRITICAL OVERRIDE memory for AC step %d: '%s'",
                run_id,
                ac_index + 1,
                explanation_text[:80],
            )

            # ── Persist to human_guidance.md KB ───────────────────────────
            # This makes the guidance TF-IDF indexed and available to ALL
            # future runs — not just the current in-session long_term_memory.
            try:
                await persist_user_guidance(
                    guidance_text=explanation_text,
                    ac_step=current_step,
                    ticket_id=ticket_id,
                    source="hitl_explanation",
                    run_id=run_id,
                )
            except Exception as persist_err:
                logger.error("[%s] Failed to persist guidance to KB: %s", run_id, persist_err)

            (
                f"🚨 HUMAN GUIDANCE AVAILABLE — AC step {ac_index + 1} DONE by human.\n"
                f"Human instruction: '{explanation_text}'.\n"
                f"AC step {ac_index + 1} is COMPLETE. Now work on step {ac_index + 2}: "
                f"'{ac_steps[ac_index + 1][:120] if (ac_index + 1) < len(ac_steps) else 'N/A'}'.\n"
                f"If this same type of step appears again, follow the human's method EXACTLY."
            )
        else:
            new_memories.append(
                f"HUMAN ACTION on AC step {ac_index + 1}: human completed "
                f"'{current_step[:80]}' manually (no explanation provided — no click captured)."
            )

    # Take a fresh screenshot so the planner sees current page state
    try:
        manager = get_manager(run_id)
        page_after = manager.page if manager else None
        if page_after and not page_after.is_closed():
            fresh_screenshot = await capture_screenshot_b64(page_after)
        else:
            fresh_screenshot = ""
    except Exception:
        page_after = None
        fresh_screenshot = ""

    # ── Learn credentials if this was a credential-failure takeover ───
    # If the human just logged in manually, read the email they used from
    # localStorage so the agent knows this account for future runs.
    if page_after and not page_after.is_closed():
        try:
            # Retrieve the email stored by vSuite during the login flow
            logged_in_email = await page_after.evaluate(
                "() => localStorage.getItem('vc2Email') || localStorage.getItem('userEmail') || ''"
            )
            if not logged_in_email:
                # Fallback: read JWT and decode sub claim for email-like hints
                jwt_raw = await page_after.evaluate("() => localStorage.getItem('vc2JWT') || ''")
                if jwt_raw:
                    import base64
                    import json as _json

                    try:
                        payload_part = jwt_raw.split(".")[1]
                        padding = "=" * (-len(payload_part) % 4)
                        decoded = _json.loads(base64.b64decode(payload_part + padding))
                        logged_in_email = decoded.get("email", "") or decoded.get("sub", "")
                    except Exception:
                        pass

            if logged_in_email:
                from backend.engine.evaluator import _extract_assigned_voicer

                voicer_name = _extract_assigned_voicer(state)
                credential_key = voicer_name or "unknown_role"
                from backend.memory.persistent import persistent_memory

                persistent_memory.record(
                    situation=f"login as {credential_key}",
                    strategy_tried=f"email:{logged_in_email}",
                    worked=True,
                    strategy_fix=f"Human confirmed login: {logged_in_email}",
                    ac_step=current_step,
                    ticket_id=ticket_id,
                )
                new_memories.append(
                    f"CREDENTIAL LEARNED: '{credential_key}' logs in as '{logged_in_email}'. "
                    f"Use this email when the AC step requires switching to this account."
                )
                logger.info(
                    "[%s] Credential learned: '%s' → %s",
                    run_id,
                    credential_key,
                    logged_in_email,
                )
        except Exception as cred_err:
            logger.debug("[%s] Could not read logged-in email: %s", run_id, cred_err)

    # ── Advance to the NEXT AC step ───────────────────────────────────
    # The human has completed this step — mark it passed and move on.
    # Do NOT send the planner back to the same step or it will re-verify
    # and potentially loop back into another takeover.
    new_ac_index = ac_index + 1
    # Return only the NEW integer index — ac_steps_completed uses operator.add
    # so appending the full list would duplicate all previous entries.
    # The DONE guardrail checks integer indices; never append step text.
    completed_steps = [ac_index]

    logger.info(
        "[%s] AC step %d marked PASSED by human — advancing to step %d/%d",
        run_id,
        ac_index + 1,
        new_ac_index + 1,
        len(ac_steps),
    )

    # ── FIX 2: Build structured HITL override payload ─────────────────────
    # Instead of injecting guidance as freetext into long_term_memory (where it
    # competes with other entries and gets diluted), we write a structured dict
    # that the planner reads FIRST, before any other context, and injects as a
    # MANDATORY OVERRIDE block at position 0 of the system prompt.
    hitl_override_dict: dict | None = None
    if captured_sequence or explanation.strip():
        # Use serializer for clean steps
        clean_actions = autorecord_serializer.serialize(captured_sequence)

        hitl_override_dict = {
            "ac_step": current_step,
            "completed_index": ac_index,
            "next_step_index": new_ac_index,
            "action_sequence": clean_actions,
            "explanation": explanation.strip(),
            "is_hard_override": bool(clean_actions),
        }
        logger.info(
            "[%s] HITL override built: is_hard_override=%s, %d actions, explanation=%d chars",
            run_id,
            hitl_override_dict["is_hard_override"],
            len(hitl_override_dict["action_sequence"]),
            len(hitl_override_dict["explanation"]),
        )

    if new_ac_index >= len(ac_steps):
        # All AC steps done — go straight to reporter
        logger.info("[%s] All AC steps completed after human takeover — routing to reporter", run_id)
        return {
            "_next_node": "reporter",
            "awaiting_human_takeover": False,
            "retry_count": 0,
            "ac_step_index": new_ac_index,
            "ac_steps_completed": completed_steps,
            "ac_step_fail_counts": {},
            "ac_step_action_fail_count": 0,
            "current_ac_step_action_count": 0,
            "vision_mode": "dom",
            "verifier_not_yet_count": 0,
            "verifier_total_not_yet_count": 0,
            "long_term_memory": new_memories,
            "current_screenshot_b64": fresh_screenshot,
            "last_error": "",
            "hitl_override": hitl_override_dict,
        }

    return {
        "_next_node": "planner",
        "awaiting_human_takeover": False,
        "retry_count": 0,
        "ac_step_index": new_ac_index,
        "ac_steps_completed": completed_steps,
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "current_ac_step_action_count": 0,  # Reset circuit breaker for new step
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "agent_critique": (
            f"Human completed step {ac_index + 1} ('{current_step[:80]}'). "
            f"That step is DONE \u2014 do NOT retry it. "
            f"Now start working on step {new_ac_index + 1}: "
            f"'{ac_steps[new_ac_index][:120] if new_ac_index < len(ac_steps) else 'N/A'}'. "
            f"Begin from the current page state."
        ),
        "last_error": "",
        "long_term_memory": new_memories,
        "current_screenshot_b64": fresh_screenshot,
        "hitl_override": hitl_override_dict,
    }
