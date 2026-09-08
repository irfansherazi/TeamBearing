"""
vQA — Proactive KB Preflight Scanner
======================================
Module: backend/kb/preflight.py

Runs ONCE per test execution, immediately after ``ac_parser_node`` finishes
populating ``acceptance_criteria_steps``.  Instead of querying the KB
reactively (one step at a time), this module scans the ENTIRE list of AC
steps up-front to:

  1. Detect which high-level **themes** the run will touch (tables, uploads,
     quick orders, voice talent, date pickers, etc.)

  2. Pre-load broad KB articles for every detected theme — so the planner
     has domain context from Iteration 1, not just after the first failure.

  3. Extract **component gotchas** from ``component_registry.json`` for every
     PrimeNG component that appears in any AC step — forbidden patterns and
     Angular quirks are injected at Attempt 0, not gated on ``retry_count``.

  4. Return a compact ``global_run_context`` string (≤ 2000 chars) that is
     stored in ``VQAState.global_run_context`` and injected at the top of
     every planner prompt for the remainder of the run.

Why this exists
---------------
Short AC steps like "Sort by Due Date" produce weak TF-IDF vectors.  A
single-step query often scores below the relevance threshold and the KB
returns nothing — leaving the agent completely blind on Attempt 0 and
forcing it to hallucinate PrimeNG interaction patterns.

By scanning all steps together and mapping them to known themes, we can
pull broad domain knowledge (e.g., the full TABLE SORTING RULES article)
even when no individual step contains the words "PrimeNG" or "compound
column".

Usage
-----
Called at the end of ``ac_parser_node``:

    from backend.kb.preflight import build_global_context
    global_ctx = await build_global_context(ac_steps, ticket_id)
    # → returned as {"global_run_context": global_ctx} in the state patch

Public API
----------
  build_global_context(steps, ticket_id)  — async, returns str

Internal helpers (not for external use)
----------------------------------------
  _detect_themes(steps)          — keyword → theme mapping
  _load_component_registry()     — reads component_registry.json (cached)
  _extract_gotchas(steps, reg)   — scan steps → component forbidden patterns
  _summarise_gotchas(gotchas)    — format dict → compact prompt block
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

from backend.kb.unified_registry import unified_registry

# ── Theme keyword table ────────────────────────────────────────────────────
# Maps a broad theme name to trigger words.  If ANY AC step contains ANY of
# these words (case-insensitive), the theme is activated and its KB article
# is pre-loaded.
#
# Theme names are used as query text passed directly to kb.query(), so they
# should match keywords that appear in vSuite-actions.md WORKFLOW headers.
_THEME_KEYWORDS: dict[str, list[str]] = {
    # Sorting, views, column headers
    "sort column header table compact view": [
        "sort",
        "ascending",
        "descending",
        "a-z",
        "z-a",
        "column",
        "client name",
        "due date",
        "start date",
        "end date",
        "days",
        "submitted",
        "status",
        "compact view",
        "list view",
        "standard view",
    ],
    # Quick Order / New Request form
    "quick order new request radio commercial": [
        "quick order",
        "new request",
        "radio commercial",
        "ad type",
        "create order",
        "new order",
        "qo",
        "spot",
    ],
    # File upload / attachment
    "upload attach file traffic production": [
        "upload",
        "attach",
        "file",
        "drag and drop",
        "browse",
        "add file",
        "import file",
    ],
    # Approval workflows
    "approve approval bulk batch action bar": [
        "approve",
        "approval",
        "bulk",
        "batch",
        "action bar",
        "select all",
        "select multiple",
        "approve selected",
    ],
    # Voice talent / dubber assignment
    "voice talent dubber assign voicer": [
        "voice",
        "dubber",
        "talent",
        "voicer",
        "assign voice",
        "add voice",
        "voice request",
    ],
    # Date pickers
    "due date calendar date picker datepicker": [
        "due date",
        "start date",
        "end date",
        "calendar",
        "date pick",
        "set date",
        "select date",
    ],
    # Login / credentials
    "login sign in credentials account": [
        "login",
        "log in",
        "sign in",
        "credentials",
        "email",
        "password",
        "account executive",
        "producer",
        "production director",
    ],
    # Production notes
    "production notes script add notes": [
        "production notes",
        "prod notes",
        "add notes",
        "script",
        "view script",
    ],
    # ── vPromotions themes ────────────────────────────────────────────────
    # Query strings are aligned with the KEYWORDS: lines on the vpromotions
    # KB workflows so the resulting kb.query() reaches prf-form.md,
    # kb-promotion-request-forms-prfs.md, kb-contests-and-giveaways.md,
    # and kb-sponsorships.md at Attempt 0 instead of after the circuit
    # breaker trips.
    "prf new prf create prf submit prf promotion request form category": [
        "prf",
        "promotion request form",
        "new prf",
        "submit a prf",
        "create prf",
        "prf category",
        "prf form",
        "prf builder",
        "prf wizard",
    ],
    "select2 vpromotions dropdown prf category ghost in as select person": [
        "select2",
        "select person",
        "select client",
        "ghost in as",
        "ghost login",
        "ghost impersonation",
    ],
    "contest text-to-win prize winner plays recurring solicit": [
        "contest",
        "contesting",
        "text-to-win",
        "text to win",
        "solicit",
        "prize",
        "prizes",
        "winner",
        "plays",
        "recurring contest",
        "grand prize",
        "jackpot",
        "release form",
    ],
    "sponsorship liner psa live mention": [
        "sponsorship",
        "sponsor",
        "liner",
        "liners",
        "psa",
        "live mention",
    ],
    "prf setup wizard assign prizes assign rules create plays add release": [
        "prf wizard",
        "setup wizard",
        "assign prizes",
        "assign rules",
        "create plays",
        "add release",
        "create liners",
        "add contest",
    ],
}

# Themes that describe product-specific workflows. When the run's active
# product matches, these are loaded ahead of generic themes so their
# articles reach the planner even when CHAR_BUDGET truncates loading.
# Without this, generic themes ('sort', 'upload', 'login') consume the
# budget first and product-specific anti-pattern warnings (e.g. the
# vPromotions select2 vs. PrimeNG guidance) never reach iteration 0.
_PRODUCT_THEMES: dict[str, set[str]] = {
    "vpromotions": {
        "prf new prf create prf submit prf promotion request form category",
        "select2 vpromotions dropdown prf category ghost in as select person",
        "contest text-to-win prize winner plays recurring solicit",
        "sponsorship liner psa live mention",
        "prf setup wizard assign prizes assign rules create plays add release",
    },
}

# ── Theme detection ────────────────────────────────────────────────────────


def _detect_themes(steps: list[str]) -> list[str]:
    """
    Scan all AC steps and return a list of activated theme query strings.

    A theme is activated if ANY step contains ANY of its trigger keywords
    (case-insensitive substring match — fast, no tokenisation needed).

    Args
    ----
    steps : list[str]
        All AC step strings from the parsed test plan.

    Returns
    -------
    list[str]
        De-duplicated list of activated theme query strings (used as KB
        query text in ``build_global_context``).
    """
    all_text = " ".join(steps).lower()
    activated: list[str] = []

    for theme_query, triggers in _THEME_KEYWORDS.items():
        if any(trigger in all_text for trigger in triggers):
            activated.append(theme_query)
            logger.debug("Preflight: theme activated — '%s'", theme_query.split()[0])

    return activated


# ── Gotcha extractor ──────────────────────────────────────────────────────


def _extract_gotchas(steps: list[str]) -> dict[str, list[str]]:
    """
    Scan AC steps against the unified registry to extract relevant gotchas.

    For each PrimeNG component whose trigger words appear in ANY step,
    this function collects the component's ``forbidden_patterns`` and
    ``angular_quirks`` lists.

    Args
    ----
    steps : list[str]
        All AC step strings.

    Returns
    -------
    dict[str, list[str]]
        Maps component name → list of gotcha strings.
        Example: {"p-table": ["verify action for sort order — use verify_table_sort..."]}
    """
    all_text = " ".join(steps).lower()
    gotchas: dict[str, list[str]] = {}

    # Detect components using the unified registry's keywords
    detected_keys = unified_registry.detect_components(all_text)

    for key in detected_keys:
        comp = unified_registry.lookup(key)
        if not comp:
            continue

        items: list[str] = []

        if comp.forbidden_patterns:
            items.extend(f"✗ FORBIDDEN: {p}" for p in comp.forbidden_patterns if p)

        if comp.angular_quirks:
            items.extend(f"⚠ QUIRK: {q}" for q in comp.angular_quirks if q)

        # ── Surface animation budgets ─────────────────────────────────────
        anim = comp.animation_budget
        anim_parts = []
        if anim.open_ms:
            anim_parts.append(f"open={anim.open_ms}ms")
        if anim.close_ms:
            anim_parts.append(f"close={anim.close_ms}ms")
        if anim.verifier_wait_ms:
            anim_parts.append(f"wait_before_assert={anim.verifier_wait_ms}ms")
        if anim.debounce_ms:
            anim_parts.append(f"debounce={anim.debounce_ms}ms")

        if anim_parts:
            items.append(f"⏱ ANIMATION: {', '.join(anim_parts)}")

        if items:
            gotchas[key] = items
            logger.debug("Preflight: %d gotcha(s) extracted for %s", len(items), key)

    return gotchas


def _summarise_gotchas(gotchas: dict[str, list[str]]) -> str:
    """
    Format the extracted gotchas into a compact, planner-readable block.

    Args
    ----
    gotchas : dict[str, list[str]]
        Output of ``_extract_gotchas()``.

    Returns
    -------
    str
        Formatted gotcha block, or empty string if no gotchas.
    """
    if not gotchas:
        return ""

    lines = [
        "═" * 63,
        "⭐ COMPONENT GOTCHAS (pre-loaded for this run — read before acting):",
        "These forbidden patterns and quirks apply to components this run WILL USE.",
        "═" * 63,
    ]
    for component, items in gotchas.items():
        lines.append(f"\n[{component}]")
        lines.extend(f"  {item}" for item in items)

    lines.append("═" * 63)
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────


async def build_global_context(
    steps: list[str],
    ticket_id: str = "",
    product: str | None = None,
) -> str:
    """
    Build the ``global_run_context`` string for this test run.

    This is the single public entry point.  Called once per run from
    ``ac_parser_node`` after AC steps are finalised.

    It runs synchronous CPU work (theme detection, gotcha extraction,
    file reads) in a thread-pool executor to avoid blocking the event loop.

    Args
    ----
    steps : list[str]
        All AC step strings from the parsed test plan.
    ticket_id : str
        Jira ticket ID for log provenance.

    Returns
    -------
    str
        A compact prompt block (≤ ~3000 chars) containing:
          - Component gotchas (forbidden patterns + Angular quirks)
          - Pre-loaded KB articles for each detected theme
        Returns empty string if no themes or gotchas are found.
    """
    if not steps:
        return ""

    def _build() -> str:
        # Import here to avoid circular imports at module load time
        from backend.kb.loader import kb  # noqa: PLC0415

        # 1. Detect themes across all AC steps
        themes = _detect_themes(steps)
        logger.info(
            "[%s] Preflight: detected %d theme(s): %s",
            ticket_id,
            len(themes),
            [t.split()[0] for t in themes],
        )

        # 2. Extract component gotchas
        gotchas = _extract_gotchas(steps)

        # 3. Pre-load KB articles for each theme
        # Prioritize product-specific themes so their articles survive the
        # char budget cutoff (vPromotions ghost-login was hitting an
        # anti-pattern the truncated-out select2 article warned against).
        kb.reload_if_updated()
        product_themes = _PRODUCT_THEMES.get(product or "", set())
        prioritized_themes = (
            [t for t in themes if t in product_themes]
            + [t for t in themes if t not in product_themes]
        )
        theme_articles: list[str] = []
        total_chars = 0
        CHAR_BUDGET = 4500  # room for ~4-5 articles; product themes come first

        for theme_query in prioritized_themes:
            if total_chars >= CHAR_BUDGET:
                break
            article = kb.query(theme_query, max_results=1, product=product)
            if article and article not in theme_articles:
                theme_articles.append(article)
                total_chars += len(article)

        logger.info(
            "[%s] Preflight: pre-loaded %d KB article(s) (%d chars), %d component(s) with gotchas",
            ticket_id,
            len(theme_articles),
            total_chars,
            len(gotchas),
        )

        # 4. Assemble the final block
        sections: list[str] = []

        gotcha_block = _summarise_gotchas(gotchas)
        if gotcha_block:
            sections.append(gotcha_block)

        if theme_articles:
            sections.append(
                "═" * 63 + "\n"
                "📚 PRE-LOADED KNOWLEDGE (scanned from all AC steps before run start):\n"
                "These articles apply to components this run WILL interact with.\n"
                + "═" * 63
                + "\n"
                + "\n\n---\n\n".join(theme_articles)
            )

        if not sections:
            return ""

        header = (
            "═" * 63 + "\n"
            f"🌐 GLOBAL RUN CONTEXT — ticket {ticket_id} ({len(steps)} steps)\n"
            "Pre-scanned knowledge injected before Attempt 0 on every step.\n" + "═" * 63 + "\n"
        )
        return header + "\n\n".join(sections)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _build)
