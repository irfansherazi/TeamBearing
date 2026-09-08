"""
vQA — HITL Playwright Trace → ActionRecipe parser (FEAT-117 / T2-b)
====================================================================

Consumes a Playwright trace .zip produced by tracing.start()/stop()
in human_takeover_node(), extracts the last successful DOM interaction
sequence, and emits an ActionRecipe YAML under knowledge/blueprints/generated/.

Invoked SYNCHRONOUSLY from human_takeover_node finalization path (Option 1A
per architecture decision in creative/vqa-tier2-planner-memory-hardening-
architecture.md §1.4).

Failures produce a WARN log + preserved .zip; no stub Recipe is written
(AC-ERROR-1).

Wall-clock target: < 1500ms for a typical HITL trace (< 50 actions).
"""
from __future__ import annotations

import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Actions accepted from Playwright trace events
_INTERACTIVE_METHODS = frozenset({
    "click",
    "dblclick",
    "fill",
    "type",
    "press",
    "selectOption",
    "check",
    "uncheck",
    "tap",
    "dispatchEvent",
})

# Classes we care about (Frame/Locator produce real user-visible DOM interactions)
_INTERACTIVE_CLASSES = frozenset({"Frame", "Locator", "Page"})

# Max trigger phrases per auto-generated recipe
_MAX_TRIGGER_PHRASES = 5

# Path in trace .zip that holds the NDJSON event stream
_TRACE_FILE_NAME = "trace.trace"

# ---------------------------------------------------------------------------
# Phase 2 (hitl-portal-aware-click-capture):
# Portal CSS pattern detection for trace-parser sink (AC-VERIFY-3).
#
# The trace parser has no access to JS-captured portal fields — it only sees
# Playwright trace events. Portal detection is done by pattern-matching the
# raw CSS selector: if any component of the CSS path matches a known PrimeNG
# portal class pattern, we treat the click as portal-scoped.
#
# Pattern: ^\.(p-|po-).*(overlay|panel|menu|dialog) (per architecture doc §4
# Implementation Guideline #4). Also detects these classes when they appear as
# a qualifier inside a longer CSS path (e.g. "div.p-select-overlay > ul > li").
#
# The extracted container_selector is always a single-class selector with a
# leading dot (e.g. ".p-select-overlay") — the shape executor.py:2187 expects.
# ---------------------------------------------------------------------------

# Explicit allowlist of known portal class suffixes — conservative whitelist
# matching the allowlist in the JS layer (algorithm doc PORTAL_ALLOWLIST).
_PORTAL_CLASS_SUFFIXES = (
    "overlay",
    "panel",
    "menu",
    "dialog",
    "popover",
)

# Exact-match allowlist for portal classes that don't follow the p-/po- prefix
# convention but are still known portal containers (vSuite custom overlays).
# Matched against any class token in the CSS path.
_PORTAL_EXACT_CLASSES = frozenset({
    "sort-panel",
})


def _detect_portal_container(selector: str) -> str | None:
    """
    Return the portal container CSS class selector if the given CSS selector
    string references a known PrimeNG / vProMedia portal container.

    A portal container is identified by:
    1. A class starting with `.p-` or `.po-` AND ending with a known portal
       suffix (overlay, panel, menu, dialog, popover).
    2. The class may appear as the full selector OR as a component of a longer
       CSS path (e.g. "html > body > div.p-select-overlay > ul > li:nth-child(3)").

    Returns the container selector as a single-class string with leading dot
    (e.g. ".p-select-overlay"), or None if no portal class is found.
    The returned selector is the FIRST matching portal class in the path — i.e.
    the outermost portal ancestor, which is the shape page.locator() expects.

    Architecture doc §4, Implementation Guideline #4:
      "extend _extract_selector_from_params to return a third element
       container_selector when the raw CSS matches a portal class pattern
       like .p-* or .po-* with overlay/panel/menu/dialog suffix."
    """
    # Tokenize on CSS combinators and whitespace so each class token is isolated
    # This handles "html > body > div.p-select-overlay > ul > li:nth-child(3)"
    tokens = re.split(r"[\s>~+,]+", selector)
    for token in tokens:
        # Each token may be "div.p-select-overlay" or ".p-select-overlay"
        # Extract all class qualifiers from the token
        classes = re.findall(r"\.([\w-]+)", token)
        for cls in classes:
            lower_cls = cls.lower()
            # Exact-match allowlist (e.g. "sort-panel" — no vendor prefix)
            if lower_cls in _PORTAL_EXACT_CLASSES:
                return f".{cls}"
            # Vendor-prefix allowlist: must start with p- or po- AND end with
            # a known portal suffix (overlay, panel, menu, dialog, popover).
            if not (cls.startswith("p-") or cls.startswith("po-")):
                continue
            if any(lower_cls.endswith(sfx) for sfx in _PORTAL_CLASS_SUFFIXES):
                return f".{cls}"
    return None


# ---------------------------------------------------------------------------
# Public enumerations / dataclasses
# ---------------------------------------------------------------------------


class TraceParseFailureReason(str, Enum):
    """Why parse_trace() produced ok=False."""

    CORRUPTED_ZIP = "corrupted_zip"
    NO_TRACE_FILE = "no_trace_file"
    NO_INTERACTIVE_EVENTS = "no_interactive_events"
    UNRESOLVABLE_SELECTOR = "unresolvable_selector"
    SCHEMA_MISMATCH = "schema_mismatch"


@dataclass
class ExtractedAction:
    """One DOM interaction extracted from the Playwright trace."""

    event_type: str                      # "click" | "fill" | "select" | "press"
    selector: str                        # semantic locator preferred; CSS fallback
    selector_kind: str                   # "role" | "label" | "text" | "css"
    value: str | None                    # for fill/type/selectOption/press
    aria_label: str | None               # for trigger phrase synthesis
    timestamp_ms: int                    # relative to trace start
    call_id: str                         # trace callId for debugging
    container_selector: str | None = None  # Phase 2 (hitl-portal-aware-click-capture):
    # When the click was inside a PrimeNG portal container, this is the leading-dot
    # CSS class selector for that container (e.g. ".p-select-overlay").  None means
    # this is an ordinary non-portal click — no container_selector in YAML output.


@dataclass
class TraceParserResult:
    """Return value of parse_trace(). Never raises — always returns this object."""

    ok: bool
    actions: list[ExtractedAction] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    recipe_yaml_path: Path | None = None
    failure_reason: TraceParseFailureReason | None = None
    failure_detail: str = ""
    zip_path: Path | None = None     # set on failure so caller knows where the zip is
    parse_duration_ms: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_selector_from_params(params: dict) -> tuple[str, str, str | None]:
    """
    Extract a selector string, its kind, and an optional portal container selector
    from a Playwright action's params dict.

    Preference order (Semantic Locators First — systemPatterns.md):
      1. role + name → get_by_role(role, name=...) synthetic repr
      2. text        → get_by_text(...)
      3. label       → get_by_label(...)
      4. placeholder → get_by_placeholder(...)
      5. testId      → get_by_test_id(...)
      6. selector    → raw CSS / XPath (fallback)

    Phase 2 (hitl-portal-aware-click-capture):
      Portal detection is applied ONLY to raw CSS selectors (path 6 above).
      Semantic selectors (role, text, label) are never portal-scoped — they are
      intrinsically safe. Portal detection: _detect_portal_container() scans the
      raw CSS for PrimeNG class patterns. If found, the third element is the
      container_selector (e.g. ".p-select-overlay"); otherwise None.

    Returns (selector_str, kind_str, container_selector_or_None)
    """
    # Role-based (highest priority) — never portal-scoped
    if "role" in params and "name" in params:
        return f'[role="{params["role"]}"][aria-label="{params["name"]}"]', "role", None

    # Explicit label — never portal-scoped
    if "label" in params:
        return str(params["label"]), "label", None

    # Text match — never portal-scoped
    if "text" in params:
        return str(params["text"]), "text", None

    # Playwright .selector string (may encode strategy info in prefix)
    raw = params.get("selector", "")
    if not raw:
        # some methods use positional arg
        if params.get("value"):
            return str(params["value"]), "text", None
        return "", "css", None

    # Parse playwright internal selector protocol prefixes
    # e.g. "css=[aria-label='foo']", "role=button[name='Ok']", "text=Submit"
    if raw.startswith("role="):
        return raw, "role", None
    if raw.startswith("text="):
        return raw[5:], "text", None
    if raw.startswith("css="):
        # Strip prefix then check the bare CSS for portal patterns
        bare = raw[4:]
        return bare, "css", _detect_portal_container(bare)
    if raw.startswith("xpath="):
        return raw, "css", None

    # Raw CSS path — check for portal container class
    container_selector = _detect_portal_container(raw)
    return raw, "css", container_selector


def _normalize_event_type(method: str) -> str:
    """Map a Playwright method name to our canonical event_type."""
    mapping = {
        "click": "click",
        "dblclick": "click",
        "fill": "fill",
        "type": "fill",
        "press": "press",
        "selectOption": "select",
        "check": "click",
        "uncheck": "click",
        "tap": "click",
        "dispatchEvent": "click",
    }
    return mapping.get(method, "click")


def _extract_actions_from_ndjson(ndjson_text: str) -> list[ExtractedAction]:
    """
    Parse the trace.trace NDJSON stream and extract successful DOM interactions.

    Strategy:
    - Collect all `before` events by callId to get params.
    - Mark callIds that have an `after` event with no `error` field as successful.
    - Emit one ExtractedAction per successful callId whose method is interactive.
    """
    before_by_call: dict[str, dict] = {}
    successful_calls: set[str] = set()

    for line in ndjson_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = event.get("type", "")
        call_id = event.get("callId", "")

        if ev_type == "before" and call_id:
            before_by_call[call_id] = event

        elif ev_type == "after" and call_id:
            # No "error" key = success
            if "error" not in event:
                successful_calls.add(call_id)

    actions: list[ExtractedAction] = []
    start_time: int | None = None

    # Walk in call-ID order (Python 3.7+ dicts preserve insertion order and
    # before events are emitted in chronological order)
    for call_id, before_ev in before_by_call.items():
        if call_id not in successful_calls:
            continue

        method = before_ev.get("method", "")
        cls = before_ev.get("class", "")

        if cls not in _INTERACTIVE_CLASSES:
            continue
        if method not in _INTERACTIVE_METHODS:
            continue

        params = before_ev.get("params", {})
        start_time_ms = int(before_ev.get("startTime", 0))
        if start_time is None:
            start_time = start_time_ms

        selector, kind, container_selector = _extract_selector_from_params(params)
        if not selector:
            continue

        # Extract value for fill/type/selectOption
        value: str | None = None
        if method in ("fill", "type"):
            value = str(params.get("value", ""))
        elif method == "selectOption":
            opt = params.get("values", params.get("value", []))
            if isinstance(opt, list):
                value = ", ".join(str(v) for v in opt)
            else:
                value = str(opt)
        elif method == "press":
            value = str(params.get("key", ""))

        # aria_label from params
        aria_label = params.get("name") or params.get("label") or None
        if aria_label:
            aria_label = str(aria_label)

        actions.append(ExtractedAction(
            event_type=_normalize_event_type(method),
            selector=selector,
            selector_kind=kind,
            value=value,
            aria_label=aria_label,
            timestamp_ms=start_time_ms - (start_time or 0),
            call_id=call_id,
            container_selector=container_selector,
        ))

    return actions


def _synthesize_trigger_phrases(
    ac_step_goal: str,
    actions: list[ExtractedAction],
    max_phrases: int = _MAX_TRIGGER_PHRASES,
) -> list[str]:
    """
    Build trigger keyword phrases for the auto-generated ActionRecipe.

    Sources (per architecture doc §1.6):
    1. Noun-heads from the AC step goal (primary)
    2. aria_label / text from the DOM interactions (secondary)

    Returns at most `max_phrases` deduplicated, lowercased 1–4-token phrases.
    """
    phrases: list[str] = []

    # --- Source 1: goal-derived phrases ---
    # Tokenize, filter stopwords, build bigrams and unigrams
    _STOPWORDS = frozenset({
        "the", "a", "an", "from", "to", "in", "on", "at", "of", "and",
        "or", "is", "it", "be", "as", "by", "for", "with", "that", "this",
        "then", "when", "if", "select", "click", "open", "close", "enter",
        "type", "fill", "press", "check", "verify", "confirm", "navigate",
    })

    goal_tokens = [
        t for t in re.sub(r"[^\w\s]", " ", ac_step_goal.lower()).split()
        if len(t) >= 2 and t not in _STOPWORDS
    ]

    # Add content bigrams from the goal
    for i in range(len(goal_tokens) - 1):
        bigram = f"{goal_tokens[i]} {goal_tokens[i+1]}"
        if bigram not in phrases:
            phrases.append(bigram)

    # Add individual content words from goal (fallback)
    for token in goal_tokens:
        if token not in phrases:
            phrases.append(token)

    # --- Source 2: DOM-derived labels from actions ---
    for action in actions:
        if action.aria_label:
            label = action.aria_label.lower().strip()
            if label and label not in phrases and len(label.split()) <= 4:
                phrases.append(label)
        # Also extract text content from selector if it's a text= kind
        if action.selector_kind == "text":
            text = action.selector.lower().strip()
            if text and text not in phrases and len(text.split()) <= 4:
                phrases.append(text)

    # Deduplicate and cap
    seen: set[str] = set()
    result: list[str] = []
    for p in phrases:
        p_clean = re.sub(r"\s+", " ", p.strip())
        if p_clean and p_clean not in seen:
            seen.add(p_clean)
            result.append(p_clean)
            if len(result) >= max_phrases:
                break

    return result


def _actions_to_recipe_steps(actions: list[ExtractedAction]) -> list[dict]:
    """Convert ExtractedAction list into ActionRecipe YAML step dicts.

    Phase 2 (hitl-portal-aware-click-capture):
    When an action carries a container_selector (detected portal), the step is
    emitted with:
      action: click
      strategy: get_by_text
      selector: <option text>
      container_selector: <portal class>   ← RecipeStep.container_selector
    This maps to recipe_runner._resolve_locator:
      page.locator(container_selector).get_by_text(selector)
    which is exactly the replayable form for PrimeNG portal option clicks.

    Non-portal actions: unchanged from pre-feature (AC-VERIFY-5 — no
    container_selector key emitted, byte-identical output for existing sinks).
    """
    steps = []
    for action in actions:
        # Phase 2: portal-scoped click
        if action.container_selector is not None and action.event_type == "click":
            # Use selector as the text to match within the portal container.
            # For portal-scoped actions the selector is the raw CSS path or a
            # text value; we extract the visible text from it when possible.
            # The selector itself (whether raw CSS or extracted text) serves as
            # the locator scoped by container_selector at replay time.
            step: dict = {
                "action": "click",
                "strategy": "get_by_text",
                "selector": action.selector,
                "container_selector": action.container_selector,
            }
            if action.value is not None:
                step["value"] = action.value
            steps.append(step)
            continue

        # Non-portal: existing path — unchanged (AC-VERIFY-5)
        step = {"action": action.event_type}

        # Selector strategy — prefer semantic
        if action.selector_kind == "role":
            step["strategy"] = "get_by_role"
            step["selector"] = action.selector
        elif action.selector_kind == "label":
            step["strategy"] = "get_by_label"
            step["selector"] = action.selector
        elif action.selector_kind == "text":
            step["strategy"] = "get_by_text"
            step["selector"] = action.selector
        else:
            step["strategy"] = "css_selector"
            step["selector"] = action.selector

        if action.value is not None:
            step["value"] = action.value

        steps.append(step)
    return steps


def _recipe_name_from_goal(ac_step_goal: str, run_id: str, takeover_seq: int) -> str:
    """Generate a snake_case recipe name from the AC step goal + run context."""
    # Take first 5 significant tokens from the goal
    tokens = re.sub(r"[^\w\s]", " ", ac_step_goal.lower()).split()
    significant = [t for t in tokens if len(t) >= 3][:5]
    base = "_".join(significant) if significant else "hitl_recipe"
    # Append short run suffix for uniqueness
    suffix = f"{run_id.replace('-', '_')}_{takeover_seq}"
    full = f"hitl_{base}_{suffix}"
    # Trim to 64 chars
    return full[:64].rstrip("_")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def parse_trace(
    zip_path: Path,
    ac_step_goal: str,
    run_id: str,
    takeover_seq: int,
    output_dir: Path = Path("knowledge/blueprints/generated"),
) -> TraceParserResult:
    """
    Parse a Playwright trace .zip and, on success, write an ActionRecipe YAML.

    Contract:
    - Returns TraceParserResult; never raises to caller.
    - On failure, .zip is left in place (not deleted). No stub YAML written.
    - WARN log emitted with run_id and failure_reason on failure.
    - Wall-clock target: < 1500ms for a typical HITL trace (< 50 actions).

    Parameters
    ----------
    zip_path : Path
        Absolute path to the Playwright trace .zip produced by tracing.stop().
    ac_step_goal : str
        The AC step text at the moment of takeover — used for trigger-phrase synthesis.
    run_id : str
        The vQA run ID (threaded for structured logging).
    takeover_seq : int
        Sequential takeover index within the run (0-based) — used for naming.
    output_dir : Path
        Directory where the ActionRecipe YAML is written.
        Defaults to knowledge/blueprints/generated/.

    Returns
    -------
    TraceParserResult
    """
    t0 = time.monotonic()

    # --- 1. Open the zip ---
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except (zipfile.BadZipFile, OSError, FileNotFoundError) as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id,
            TraceParseFailureReason.CORRUPTED_ZIP,
            str(exc),
            zip_path,
        )
        return TraceParserResult(
            ok=False,
            failure_reason=TraceParseFailureReason.CORRUPTED_ZIP,
            failure_detail=str(exc),
            zip_path=zip_path,
            parse_duration_ms=elapsed,
        )

    # --- 2. Read trace.trace NDJSON ---
    try:
        with zf:
            if _TRACE_FILE_NAME not in zf.namelist():
                elapsed = int((time.monotonic() - t0) * 1000)
                logger.warning(
                    "[%s] hitl_trace_parse_failed: reason=%s zip_preserved=%s",
                    run_id,
                    TraceParseFailureReason.NO_TRACE_FILE,
                    zip_path,
                )
                return TraceParserResult(
                    ok=False,
                    failure_reason=TraceParseFailureReason.NO_TRACE_FILE,
                    failure_detail=f"'{_TRACE_FILE_NAME}' not found in zip. Contents: {zf.namelist()}",
                    zip_path=zip_path,
                    parse_duration_ms=elapsed,
                )
            ndjson_text = zf.read(_TRACE_FILE_NAME).decode("utf-8", errors="replace")
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id,
            TraceParseFailureReason.CORRUPTED_ZIP,
            str(exc),
            zip_path,
        )
        return TraceParserResult(
            ok=False,
            failure_reason=TraceParseFailureReason.CORRUPTED_ZIP,
            failure_detail=str(exc),
            zip_path=zip_path,
            parse_duration_ms=elapsed,
        )

    # --- 3. Extract actions ---
    try:
        actions = _extract_actions_from_ndjson(ndjson_text)
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id,
            TraceParseFailureReason.SCHEMA_MISMATCH,
            str(exc),
            zip_path,
        )
        return TraceParserResult(
            ok=False,
            failure_reason=TraceParseFailureReason.SCHEMA_MISMATCH,
            failure_detail=str(exc),
            zip_path=zip_path,
            parse_duration_ms=elapsed,
        )

    if not actions:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id,
            TraceParseFailureReason.NO_INTERACTIVE_EVENTS,
            "No successful interactive DOM events found in trace",
            zip_path,
        )
        return TraceParserResult(
            ok=False,
            failure_reason=TraceParseFailureReason.NO_INTERACTIVE_EVENTS,
            failure_detail="No successful interactive DOM events found in trace",
            zip_path=zip_path,
            parse_duration_ms=elapsed,
        )

    # --- 4. Build trigger phrases ---
    trigger_phrases = _synthesize_trigger_phrases(ac_step_goal, actions)

    # --- 5. Build recipe dict ---
    recipe_name = _recipe_name_from_goal(ac_step_goal, run_id, takeover_seq)
    steps = _actions_to_recipe_steps(actions)

    recipe_dict = {
        "name": recipe_name,
        "description": (
            f"Auto-generated from HITL takeover — run={run_id}, seq={takeover_seq}. "
            f"AC step: {ac_step_goal[:120]}"
        ),
        "trigger_keywords": trigger_phrases,
        "parameters": [],
        "steps": steps,
        "cleanup_on_failure": [],
        "verify_after": None,
        "is_sort_recipe": False,
        "force_wait_before_next": False,
        "force_wait_ms": 1500,
    }

    # --- 6. Write YAML ---
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = output_dir / f"{recipe_name}.yaml"

        with yaml_path.open("w", encoding="utf-8") as fh:
            yaml.dump(recipe_dict, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    except OSError as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "[%s] hitl_trace_parse_failed: reason=%s detail=%s zip_preserved=%s",
            run_id,
            TraceParseFailureReason.UNRESOLVABLE_SELECTOR,
            f"Could not write Recipe YAML: {exc}",
            zip_path,
        )
        return TraceParserResult(
            ok=False,
            failure_reason=TraceParseFailureReason.UNRESOLVABLE_SELECTOR,
            failure_detail=f"Could not write Recipe YAML: {exc}",
            zip_path=zip_path,
            parse_duration_ms=elapsed,
        )

    elapsed = int((time.monotonic() - t0) * 1000)
    logger.info(
        "[%s] hitl_trace_parse_ok: %d actions extracted, recipe_yaml=%s, duration_ms=%d",
        run_id,
        len(actions),
        yaml_path,
        elapsed,
    )

    return TraceParserResult(
        ok=True,
        actions=actions,
        trigger_phrases=trigger_phrases,
        recipe_yaml_path=yaml_path,
        parse_duration_ms=elapsed,
    )
