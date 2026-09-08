"""
vQA — Domain-Aware AC Enrichment Engine
==========================================
Module: backend/engine/ac_enricher.py

FEAT-002: Pre-processing enrichment stage that runs BEFORE Stage 1 BDD
normalization in the AC parsing pipeline.

This module queries the Knowledge Base using the ticket summary and raw
Acceptance Criteria text to inject domain context — vSuite component names,
interaction patterns, typical preconditions, and role-specific constraints —
directly into the AC text before the LLM parses it.

Example transformation::

    BEFORE: "User can sort the table"
    AFTER:  "User can sort the table

            <domain_context source="kb_enrichment">
            DOMAIN: table_sort
            — In Production Orders compact view, sorting uses the Sort By
              p-select dropdown (button#sort-btn), NOT column headers.
            — Column headers (th elements) are only clickable in List View.
            — Use primeng_dropdown action for compound columns (Due/Days, Start/End).
            </domain_context>"

This eliminates the root cause of vague-AC failures: the LLM no longer
needs to invent context because context is provided at parse time.

Architecture Context
--------------------
  ac_parser_node (ac_parser.py)
      ├── score_ac_quality(raw_ac)     ← FEAT-001: quality gate
      ├── enrich_ac_text(raw_ac, ...)  ← FEAT-002: THIS MODULE
      ├── _stage_1_normalize(enriched) ← BDD normalizer (with context)
      └── _stage_2_compile(bdd_text)   ← JSON compiler

Design Decisions
----------------
  - **Not a separate LangGraph node**: Enrichment is a pure function
    (raw_ac → enriched_ac). Calling it from ac_parser_node avoids graph
    topology changes and keeps the pipeline testable.
  - **Zero LLM cost**: Enrichment is purely KB-retrieval + template-based.
    Uses FEAT-006's BM25 + synonym expansion for retrieval.
  - **XML-tagged context**: The ``<domain_context>`` tag lets Stage 1's
    prompt clearly distinguish original AC from injected context. Rules 9-10
    (FEAT-001: NEVER INVENT + ``<inferred>`` tags) remain effective.

Dependencies
------------
  - ``backend/kb/loader.py``              — KB retrieval (TF-IDF + BM25)
  - ``backend/engine/ac_quality_gate.py`` — ACQualityResult for scoring

See Also
--------
  - ``backend/engine/ac_parser.py``  — calls enrich_ac_text()
  - ``backend/kb/preflight.py``      — uses same theme keywords
  - ``backend/engine/prompts.py``    — Stage 1 BDD normalizer prompt
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# T3-a: ComplaintCounter — AC-negotiator complaint observable signal (CQ-A2)
# ---------------------------------------------------------------------------


class ComplaintCounter:
    """
    T3-a observable signal for AC-INTEGRATION-1.

    Tracks per-product AC-negotiator complaint events and emits structured
    log events with event_type='ac_negotiator_complaint'.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, *, product: str, phrase: str) -> None:
        """Record one AC-negotiator complaint event with structured log emission."""
        self._counts[product] = self._counts.get(product, 0) + 1
        logger.warning(
            "AC negotiator complaint: product=%s phrase=%r",
            product,
            phrase,
            extra={
                "event_type": "ac_negotiator_complaint",
                "product": product,
                "phrase": phrase,
            },
        )

    def get_totals(self) -> dict[str, int]:
        """Return a copy of the per-product complaint counts."""
        return dict(self._counts)

    def to_state_dict(self) -> dict[str, int]:
        """Return state dict compatible with VQAState['complaints_by_product']."""
        return dict(self._counts)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentResult:
    """
    Structured result from the AC enrichment engine.

    Attributes
    ----------
    enriched_ac : str
        The raw AC text with appended domain context (or unchanged if
        no enrichment was applied).
    detected_domains : list[str]
        Domain categories detected from the ticket summary and AC text.
        Examples: "table_sort", "quick_order", "voice_workflow".
    kb_articles_used : list[str]
        Names of KB articles that contributed enrichment context.
    enrichment_applied : bool
        True if domain context was injected, False if no-op.
    enrichment_char_count : int
        Number of characters of domain context injected.
    """

    enriched_ac: str
    detected_domains: list[str] = field(default_factory=list)
    kb_articles_used: list[str] = field(default_factory=list)
    enrichment_applied: bool = False
    enrichment_char_count: int = 0

    def to_dict(self) -> dict:
        """Serialize for storage in VQAState."""
        return {
            "detected_domains": self.detected_domains,
            "kb_articles_used": self.kb_articles_used,
            "enrichment_applied": self.enrichment_applied,
            "enrichment_char_count": self.enrichment_char_count,
        }


# ---------------------------------------------------------------------------
# Domain keyword table
# ---------------------------------------------------------------------------
# Maps domain categories to trigger words.  If the ticket summary or AC text
# contains ANY of these words (case-insensitive), the domain is activated
# and its KB articles are queried for enrichment context.
#
# These mirror _THEME_KEYWORDS from preflight.py for consistency, but are
# structured for the enricher's domain-inference logic.

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "table_sort": [
        "sort",
        "ascending",
        "descending",
        "a-z",
        "z-a",
        "column",
        "column header",
        "sort by",
        "order by",
        "oldest",
        "newest",
        "alphabetical",
        "table order",
    ],
    "quick_order": [
        "quick order",
        "new request",
        "radio commercial",
        "ad type",
        "create order",
        "new order",
        "qo",
        "spot",
    ],
    "voice_workflow": [
        "voice",
        "dubber",
        "talent",
        "voicer",
        "add voice",
        "voice request",
        "voice part",
    ],
    "login_auth": [
        "login",
        "log in",
        "sign in",
        "credentials",
        "email",
        "password",
        "authenticated",
        "account executive",
        "producer",
    ],
    "file_upload": [
        "upload",
        "attach",
        "file",
        "drag and drop",
        "browse",
        "add file",
        "import file",
    ],
    "approval_flow": [
        "approve",
        "approval",
        "bulk",
        "batch",
        "action bar",
        "select all",
        "approve selected",
        "reject",
    ],
    "view_navigation": [
        "compact view",
        "list view",
        "minimal view",
        "switch view",
        "change view",
        "view settings",
        "standard view",
    ],
    "status_change": [
        "status",
        "change status",
        "needs producing",
        "needs dubbing",
        "needs writing",
        "needs scheduling",
        "production notes",
    ],
    "date_picker": [
        "due date",
        "start date",
        "end date",
        "calendar",
        "date pick",
        "set date",
        "select date",
        "datepicker",
    ],
}

# Domain → targeted KB query strings for retrieval.
# These are designed to match KB WORKFLOW keywords for maximum TF-IDF score.
_DOMAIN_KB_QUERIES: dict[str, list[str]] = {
    "table_sort": [
        "sort column header table ascending descending compact view list view",
        "primeng dropdown sort p-select compound column",
    ],
    "quick_order": [
        "quick order new request radio commercial create",
        "quick order form fill client ad type",
    ],
    "voice_workflow": [
        "voice talent dubber assign voicer add voice request",
        "production notes prod notes add notes",
    ],
    "login_auth": [
        "login sign in credentials email password account",
    ],
    "file_upload": [
        "upload attach file drag drop input set_input_files",
    ],
    "approval_flow": [
        "approve approval bulk batch action bar select",
    ],
    "view_navigation": [
        "compact view list view minimal view settings menu navigation",
    ],
    "status_change": [
        "status change needs producing dubbing writing scheduling",
    ],
    "date_picker": [
        "due date calendar datepicker p-calendar date select",
    ],
}


# ---------------------------------------------------------------------------
# Domain inference
# ---------------------------------------------------------------------------


def _detect_domains(summary: str, raw_ac: str, description: str = "") -> list[str]:
    """
    Detect domain categories from ticket summary and AC text.

    Scans the combined text against _DOMAIN_KEYWORDS and returns all
    matching domain categories, sorted by number of keyword matches
    (strongest signal first).

    Args
    ----
    summary : str
        Jira ticket summary/title.
    raw_ac : str
        Raw Acceptance Criteria text.
    description : str
        Full Jira ticket description (additional context).

    Returns
    -------
    list[str]
        Detected domain categories, strongest first.
        Max 3 domains returned.
    """
    combined_text = f"{summary} {raw_ac} {description}".lower()
    domain_scores: list[tuple[str, int]] = []

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw in combined_text)
        if match_count > 0:
            domain_scores.append((domain, match_count))

    # Sort by match count descending, take top 3
    domain_scores.sort(key=lambda x: -x[1])
    detected = [d for d, _ in domain_scores[:3]]

    logger.debug(
        "AC Enricher: domain inference — detected %d domain(s): %s",
        len(detected),
        detected,
    )
    return detected


# ---------------------------------------------------------------------------
# KB query for enrichment
# ---------------------------------------------------------------------------


def _query_kb_for_enrichment(
    domains: list[str],
) -> list[tuple[str, str, str]]:
    """
    Query the KB for enrichment context for each detected domain.

    Uses FEAT-006's BM25 + synonym expansion via kb.query_with_expansion()
    for improved retrieval on short/vague queries.

    Args
    ----
    domains : list[str]
        Detected domain categories.

    Returns
    -------
    list[tuple[str, str, str]]
        List of (domain, article_name, article_content) tuples.
        Each article_content is capped at 500 chars (key steps only).
    """
    from backend.kb.loader import kb  # noqa: PLC0415 — avoid circular import

    kb.reload_if_updated()

    results: list[tuple[str, str, str]] = []
    total_chars = 0
    _CHAR_BUDGET = 1500  # Total enrichment context budget

    for domain in domains:
        queries = _DOMAIN_KB_QUERIES.get(domain, [])
        if not queries:
            continue

        for query_text in queries:
            if total_chars >= _CHAR_BUDGET:
                break

            article = kb.query_with_expansion(query_text, max_results=1)
            if not article:
                continue

            # Extract the article name from the KB format: [KB: <name>]
            name_match = re.search(r"\[KB:\s*(.+?)\]", article)
            article_name = name_match.group(1) if name_match else "Unknown"

            # Extract the actionable content (strip the KB header/footer)
            content = article
            # Remove the ═══ header/footer borders
            content = re.sub(r"^═+\n.*?\n.*?\n═+\n", "", content, flags=re.DOTALL)
            content = re.sub(r"\n═+$", "", content)
            content = content.strip()

            # Cap per-article content to keep prompt compact
            _MAX_PER_ARTICLE = 500
            if len(content) > _MAX_PER_ARTICLE:
                content = content[:_MAX_PER_ARTICLE].rsplit("\n", 1)[0] + "\n..."

            # Deduplicate — don't add same article name twice
            if any(name == article_name for _, name, _ in results):
                continue

            results.append((domain, article_name, content))
            total_chars += len(content)

            logger.debug(
                "AC Enricher: KB query for '%s' → '%s' (%d chars)",
                domain,
                article_name,
                len(content),
            )

        if total_chars >= _CHAR_BUDGET:
            break

    return results


# ---------------------------------------------------------------------------
# Enrichment context builder
# ---------------------------------------------------------------------------


def _build_enrichment_context(
    domains: list[str],
    kb_articles: list[tuple[str, str, str]],
) -> str:
    """
    Build the XML-tagged enrichment context block.

    This block is appended to the raw AC text before Stage 1 BDD
    normalization. The XML tags let the LLM distinguish original AC
    from injected domain context.

    Args
    ----
    domains : list[str]
        Detected domain categories.
    kb_articles : list[tuple[str, str, str]]
        (domain, article_name, article_content) tuples from KB.

    Returns
    -------
    str
        Formatted enrichment context block.
        Empty string if no articles to inject.
    """
    if not kb_articles:
        return ""

    lines: list[str] = [
        "",
        "",
        '<domain_context source="kb_enrichment">',
        "DOMAIN CONTEXT — Use these facts to write more specific BDD steps.",
        "Do NOT invent information not covered by these facts.",
        "",
    ]

    # Group articles by domain for readable structure
    current_domain = ""
    for domain, article_name, content in kb_articles:
        if domain != current_domain:
            lines.append(f"── DOMAIN: {domain} ──")
            current_domain = domain

        # Format as compact bullet points
        # Extract actionable lines from the content
        actionable_lines = _extract_actionable_lines(content)
        if actionable_lines:
            lines.append(f"[{article_name}]")
            lines.extend(f"  — {line}" for line in actionable_lines)
            lines.append("")

    lines.append("</domain_context>")
    return "\n".join(lines)


def _extract_actionable_lines(content: str) -> list[str]:
    """
    Extract the most actionable lines from a KB article.

    Prioritizes lines that contain:
    - Component names (p-select, p-table, button#...)
    - Interaction patterns (click, use, avoid, NEVER)
    - Precondition context (on the, in compact view, after)

    Returns at most 5 lines per article to keep the context compact.

    Args
    ----
    content : str
        Raw KB article content.

    Returns
    -------
    list[str]
        Filtered actionable lines, max 5.
    """
    # Priority keywords for line selection
    _PRIORITY_KEYWORDS = [
        "p-select",
        "p-table",
        "p-calendar",
        "p-dropdown",
        "button#",
        "css_selector",
        "get_by_role",
        "get_by_text",
        "click",
        "use",
        "avoid",
        "never",
        "must",
        "critical",
        "compact view",
        "list view",
        "column header",
        "sort by",
        "forbidden",
        "instead",
        "not",
        "always",
    ]

    lines = content.split("\n")
    scored_lines: list[tuple[float, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 10:
            continue
        # Skip header/separator lines
        if stripped.startswith("═") or stripped.startswith("─") or stripped.startswith("[KB:"):
            continue

        # Score the line by priority keyword matches
        line_lower = stripped.lower()
        score = sum(1 for kw in _PRIORITY_KEYWORDS if kw in line_lower)

        # Boost lines that start with action-oriented markers
        if any(stripped.startswith(m) for m in ["⚠", "✗", "⛔", "-", "•", "*", "RULE", "Step"]):
            score += 1

        if score > 0:
            scored_lines.append((score, stripped))

    # Sort by score descending, take top 5
    scored_lines.sort(key=lambda x: -x[0])
    return [line for _, line in scored_lines[:5]]


# ---------------------------------------------------------------------------
# Playwright context query (parser-time ground-truth injection)
# ---------------------------------------------------------------------------


def _query_playwright_context(
    ticket_id: str,
    summary: str,
    raw_ac: str,
) -> str:
    """
    Query Playwright ground-truth tests and RAG snippets for parser-time context.

    Provides the Stage 1 BDD normalizer with verified selector vocabulary and
    step patterns from existing Playwright tests so the LLM can anchor its
    BDD output to real, passing test code rather than inventing interaction
    patterns from scratch.

    Priority
    --------
    1. ``test_matcher``: exact qa-NNN test file for this ticket (highest signal).
       If a passing ``qa-NNN.test.ts`` exists, the LLM should follow its
       selectors, step sequences, and component names exactly.
    2. ``playwright_rag``: TF-IDF code snippets by semantic similarity (fallback
       when no exact ticket match exists — surfaces similar verified patterns).

    The returned block is an XML-tagged ``<playwright_context>`` string (or
    ``""`` when nothing relevant is found), capped at 1200 chars to keep
    the enriched prompt compact.

    Args
    ----
    ticket_id : str
        Jira ticket ID (e.g., ``"QA-138"``).  Used for test_matcher lookup.
    summary : str
        Jira ticket summary/title.  Combined with ``raw_ac`` for RAG query.
    raw_ac : str
        Raw Acceptance Criteria text.  First 200 chars used in RAG query.

    Returns
    -------
    str
        ``<playwright_context>`` XML block, or empty string if no context found.
    """
    _MAX_PW_CHARS = 1200

    # ── Priority 1: Ground-truth test file for this specific ticket ─────
    try:
        from backend.kb.test_matcher import test_matcher  # noqa: PLC0415

        matched = test_matcher.get_matching_tests(ticket_id)
        if matched:
            content_parts = []
            for test in matched:
                content_parts.append(f"[{test.filename}]\n{test.content[:600]}")
            raw_content = "\n\n".join(content_parts)
            if len(raw_content) > _MAX_PW_CHARS:
                raw_content = raw_content[:_MAX_PW_CHARS] + "\n// ... (truncated)"
            logger.debug(
                "[%s] Playwright context: test_matcher found %d file(s) (%d chars)",
                ticket_id,
                len(matched),
                len(raw_content),
            )
            return (
                '\n\n<playwright_context source="test_matcher" ticket="'
                + ticket_id
                + '">\n'
                "GROUND-TRUTH TEST CODE — Human-written, verified Playwright tests for this ticket.\n"
                "Use these exact selectors, step sequences, and component names as the HIGHEST-FIDELITY\n"
                "reference when constructing BDD steps. Do NOT deviate from verified selectors found here.\n\n"
                + raw_content
                + "\n</playwright_context>"
            )
    except Exception as e:
        logger.debug(
            "[%s] Playwright context: test_matcher unavailable (non-fatal): %s",
            ticket_id,
            e,
        )

    # ── Priority 2: TF-IDF RAG snippets by semantic similarity ─────────
    try:
        from backend.kb.playwright_rag import playwright_rag  # noqa: PLC0415

        query_text = f"{summary} {raw_ac[:200]}"
        snippets = playwright_rag.query(query_text, max_results=2)
        if snippets:
            # Strip the decorative planner-oriented header/footer (═══ borders)
            # to keep the context block clean and compact.
            clean = re.sub(r"^[\u2550\s]+.*?[\u2550\s]+\n", "", snippets, flags=re.DOTALL)
            clean = re.sub(r"\n[\u2550\s]+$", "", clean).strip()
            if not clean:
                clean = snippets.strip()
            if len(clean) > _MAX_PW_CHARS:
                clean = clean[:_MAX_PW_CHARS] + "\n// ... (truncated)"
            logger.debug(
                "[%s] Playwright context: playwright_rag returned %d chars",
                ticket_id,
                len(clean),
            )
            return (
                '\n\n<playwright_context source="playwright_rag">\n'
                "RELEVANT PLAYWRIGHT CODE — Verified selectors and patterns from similar tests.\n"
                "Use as reference for step phrasing, component names, and interaction sequences.\n\n"
                + clean
                + "\n</playwright_context>"
            )
    except Exception as e:
        logger.debug(
            "[%s] Playwright context: playwright_rag unavailable (non-fatal): %s",
            ticket_id,
            e,
        )

    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def enrich_ac_text(
    raw_ac: str,
    summary: str,
    description: str,
    ticket_id: str,
    quality_result: Any = None,
) -> EnrichmentResult:
    """
    Enrich raw Acceptance Criteria text with domain context from the KB, or apply
    an LLM-based repair pipeline if the initial quality score is below GOOD (< 7).

    This is the single public entry point for FEAT-002 / FEAT-070. Called from
    ``ac_parser_node`` after the FEAT-001 quality gate is run.

    The enrichment pipeline:
      - If score < 7 (FAIR or POOR):
        1. Gathers context by querying TestPlanVault for similar historical plans.
        2. Fetches recent issue comments from Jira.
        3. Invokes LLM to rewrite the AC to clarify preconditions, specific PrimeNG
           components, expected target states, and auto-synthesize logical negative paths.
        4. Re-scores the enriched AC to verify it meets the GOOD (>= 7) threshold.
      - If score >= 7 (GOOD):
        1. Detect domains from ticket summary + AC text
        2. Query KB for relevant articles per domain
        3. Build XML-tagged context block
        4. Append context to raw AC text

    Args
    ----
    raw_ac : str
        Raw Acceptance Criteria text from Jira.
    summary : str
        Jira ticket summary/title.
    description : str
        Full Jira ticket description.
    ticket_id : str
        Jira ticket ID for logging.
    quality_result : ACQualityResult, optional
        Quality assessment from FEAT-001.

    Returns
    -------
    EnrichmentResult
        Structured result with enriched AC text and metadata.
    """
    # ── Guard: empty input ────────────────────────────────────────────
    if not raw_ac or not raw_ac.strip():
        logger.debug("[%s] AC Enricher: empty AC text — no-op", ticket_id)
        return EnrichmentResult(enriched_ac=raw_ac)

    from backend.engine.ac_quality_gate import score_ac_quality

    # Evaluate quality if not provided
    if quality_result is None:
        quality_result = score_ac_quality(raw_ac)

    # ── LLM-driven repair for sub-GOOD scores (score < 7) ─────────────
    if quality_result.overall_score < 7:
        logger.info(
            "[%s] AC quality is below GOOD (score %d/10, grade %s) — applying LLM-driven repair",
            ticket_id,
            quality_result.overall_score,
            quality_result.quality_grade,
        )

        # 1. Query TestPlanVault for successful historical test plans
        historical_plans = []
        try:
            from backend.kb.rag import test_plan_vault
            query_text = f"Summary: {summary}\nAC: {raw_ac}\nDescription: {description}"
            historical_plans = test_plan_vault.query_plans(query_text, n_results=3)
            logger.debug("[%s] AC Enricher: TestPlanVault retrieved %d plan(s)", ticket_id, len(historical_plans))
        except Exception as e:
            logger.warning("[%s] AC Enricher: TestPlanVault query failed (non-fatal): %s", ticket_id, e)

        # 2. Fetch comments from Jira
        comments = []
        try:
            from backend.jira.client import fetch_issue_comments
            comments = await fetch_issue_comments(ticket_id)
            logger.debug("[%s] AC Enricher: Jira retrieved %d comment(s)", ticket_id, len(comments))
        except Exception as e:
            logger.warning("[%s] AC Enricher: Fetch Jira comments failed (non-fatal): %s", ticket_id, e)

        # 3. Detect domains & KB articles for extra prompt injection
        domains = _detect_domains(summary, raw_ac, description)
        kb_context = ""
        kb_articles_used = []
        if domains:
            try:
                kb_articles = _query_kb_for_enrichment(domains)
                kb_articles_used = [name for _, name, _ in kb_articles]
                kb_context = _build_enrichment_context(domains, kb_articles)
            except Exception as e:
                logger.warning("[%s] AC Enricher: KB query for LLM repair failed (non-fatal): %s", ticket_id, e)

        # 3b. Query Playwright ground-truth tests and RAG for parser-time context.
        # Injected as a dedicated section in the repair prompt so the LLM can
        # anchor its rewritten AC to real, verified selectors and step sequences.
        playwright_ctx_str = _query_playwright_context(ticket_id, summary, raw_ac)
        if playwright_ctx_str:
            logger.info(
                "[%s] AC Enricher (repair path): playwright context injected (%d chars)",
                ticket_id,
                len(playwright_ctx_str),
            )

        # 4. Format context for prompt
        historical_plans_str = ""
        if historical_plans:
            for idx, plan in enumerate(historical_plans, 1):
                steps_str = "\n".join(
                    f"  - Step {s.step_index}: {s.actor} - {s.action} ({s.description})"
                    for s in plan.steps
                )
                historical_plans_str += f"\n--- Historical Test Plan {idx}: {plan.test_title} ---\n{steps_str}\n"
        else:
            historical_plans_str = "(No historical successful test plans found in TestPlanVault)"

        comments_str = ""
        if comments:
            for idx, c in enumerate(comments, 1):
                comments_str += f"\n- Comment {idx} by {c.get('author', 'Unknown')} ({c.get('created', 'n/a')}):\n  {c.get('body', '')}\n"
        else:
            comments_str = "(No comments found on this Jira ticket)"

        # 5. Build LLM prompt
        repair_prompt = f"""You are the vQA AC Enricher, an expert QA engineer specializing in writing high-quality, unambiguous, specific, and testable BDD Acceptance Criteria.

Your goal is to repair a structurally weak or vague Jira ticket's Acceptance Criteria (AC), making it highly specific and actionable, and auto-synthesizing logical negative test paths.

Here is the original Jira ticket information:
TICKET ID: {ticket_id}
SUMMARY: {summary}
DESCRIPTION: {description or "(None)"}

ORIGINAL RAW AC TEXT:
{raw_ac}

To assist you, here is the context gathered from the workspace:

--- PLAYWRIGHT REFERENCE CODE (HIGHEST PRIORITY) ---
{playwright_ctx_str or "(No matching Playwright tests or code snippets found for this ticket)"}

--- RELEVANT KNOWLEDGE BASE ARTICLES ---
{kb_context or "(None)"}

--- HISTORICAL SUCCESSFUL TEST PLANS ---
{historical_plans_str}

--- JIRA ISSUE COMMENTS ---
{comments_str}

YOUR TASK:
Rewrite the Acceptance Criteria into a clean, complete, and highly specific Given/When/Then BDD format that avoids any ambiguity. You MUST adhere to these strict quality guidelines to pass the quality gate scorer:

1. STRUCTURE & PRECONDITIONS (Given/When/Then):
   - Group your rewritten AC into clear Scenario blocks (e.g. "Scenario: Happy Path - [Description]").
   - Each step should be on its own line and start with standard BDD keywords (Given, When, Then, And).
   - Every scenario must start with clear starting context/preconditions, specifying the page/navigation state or logged-in user role (e.g. "Given the user is on the login page", "Given the producer is logged in and navigates to the Production Orders list view").

2. ACTIONABILITY & ELEMENT SPECIFICITY:
   - Always use concrete action verbs: 'click', 'select', 'fill', 'type', 'enter', 'press', 'uncheck', 'upload', 'download', 'verify', 'confirm', 'assert', 'submit', 'save', 'delete', 'edit', 'update'. Avoid generic verbs like 'interact', 'go to', 'try', etc.
   - Never say "click the button" or "click the dropdown" generically. Always specify the EXACT component name or button label.
   - Use specific PrimeNG component names or pattern-matched terms to maximize the specificity score:
     * Component names: 'p-select', 'p-dropdown', 'p-calendar', 'p-datepicker', 'p-autocomplete', 'p-multiselect', 'p-checkbox', 'p-table', 'p-toast', 'p-confirmdialog', 'p-fileupload', 'p-overlaypanel', 'p-dialog', 'p-menu', 'p-tabview'.
     * Specific labels/selectors: '#sort-btn', '.sort-panel', '#submit-all', 'new request', 'sort by', 'save search', 'compact view', 'list view', 'minimal view', 'client column', 'due date column', 'status column', 'action bar', 'bulk approve'.
     E.g., "When the user clicks the '#sort-btn' button" or "When the user selects 'Client' from the 'p-select' dropdown".

3. OBSERVABLE OUTCOMES:
   - Every verification step (Then) must describe a specific, observable, and verifiable target state.
   - Use specific verification signals like: 'success message toast appears', 'the url changes to /orders', 'the p-table row is visible', 'the submit button is disabled', 'the checkbox is checked'. Avoid vague checks like "verify it works".

4. SCOPE ATOMICITY:
   - Each step must represent a single, atomic action.
   - NEVER join multiple distinct actions with "and" or "then" in the same step. Do not say "click the sort button and select X and verify Y". Write them as separate lines!

5. NEGATIVE PATH SYNTHESIS:
   - You MUST auto-synthesize at least two (2) separate, logical, logic-based negative path scenarios (e.g. boundary condition inputs, unauthorized access, validation/error states, or error-recovery states) based on the primary happy-path.
   - Write them under distinct Scenario blocks (e.g. "Scenario: Negative Path - Validation Error", "Scenario: Negative Path - Unauthorized Access").
   - Ensure the negative path steps are as fully detailed, specific, and actionable as the happy path steps, with explicit assertions (e.g. error toasts or disabled buttons).

6. NO PLACEHOLDERS:
   - Do NOT use placeholders, TODOs, or ellipsis ('...', '[details here]'). Every value, state, and step must be concrete and fully realized.

Return ONLY the rewritten, complete BDD Acceptance Criteria text (including the happy path and all synthesized negative paths). Do NOT wrap it in any explanations, markdown code blocks, or introductory conversational text. Output the raw text of the rewritten ACs directly.
"""

        # 6. Invoke LLM
        try:
            from backend.llm import get_llm
            from langchain_core.messages import SystemMessage

            # temperature=0.0 (was 0.1): the enricher rewrites the AC that both
            # Stage 1 and Stage 2 consume, so any sampling variance here compounds
            # downstream into a different step count on the same ticket. The
            # "creativity" the 0.1 default was meant to buy (varied negative-path
            # phrasing) is not worth the drift.
            llm = get_llm("parser", temperature=0.0, max_tokens=3072)
            messages = [SystemMessage(content=repair_prompt)]

            import time
            t0 = time.monotonic()
            response = await llm.ainvoke(messages)
            latency_ms = int((time.monotonic() - t0) * 1000)

            enriched_text = response.content.strip()

            # Clean markdown code blocks if present
            if enriched_text.startswith("```"):
                lines = enriched_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                enriched_text = "\n".join(lines).strip()

            # Re-score the enriched AC to verify quality (filtering out Scenario headers to prevent low-score dings)
            scoring_text = "\n".join(
                line for line in enriched_text.split("\n")
                if not (line.strip().lower().startswith("scenario:") or line.strip().lower().startswith("feature:"))
            ).strip()
            re_scored = score_ac_quality(scoring_text)
            logger.info(
                "[%s] Re-scored enriched AC: score=%d/10, grade=%s, warnings=%d",
                ticket_id,
                re_scored.overall_score,
                re_scored.quality_grade,
                len(re_scored.warnings),
            )

            # Update quality_result in place
            if quality_result:
                quality_result.overall_score = re_scored.overall_score
                quality_result.quality_grade = re_scored.quality_grade
                quality_result.warnings = re_scored.warnings
                quality_result.step_scores = re_scored.step_scores
                quality_result.dimension_scores = re_scored.dimension_scores

            # Detect negative scenarios count
            negative_scenarios_count = len(re.findall(r"(?i)scenario:\s*negative", enriched_text))
            logger.info(
                "[%s] AC Enricher: repair successful (score=%d, synthesized %d negative scenario(s))",
                ticket_id,
                re_scored.overall_score,
                negative_scenarios_count,
            )

            return EnrichmentResult(
                enriched_ac=enriched_text,
                detected_domains=domains,
                kb_articles_used=kb_articles_used,
                enrichment_applied=True,
                enrichment_char_count=len(enriched_text) - len(raw_ac),
            )

        except Exception as e:
            logger.error("[%s] Failed to apply LLM-driven AC enrichment (falling back to heuristic): %s", ticket_id, e)
            # Proceed to standard heuristic enrichment on failure

    # ── Step 0: Query Playwright ground-truth tests (always, regardless of KB domains) ──
    # Runs before domain detection so playwright context is available even when
    # the ticket uses novel domain vocabulary that misses keyword triggers.
    pw_ctx = _query_playwright_context(ticket_id, summary, raw_ac)

    # ── Step 1: Detect domains (Standard FEAT-002 heuristic) ──────────
    domains = _detect_domains(summary, raw_ac, description)

    if not domains:
        if pw_ctx:
            logger.info(
                "[%s] AC Enricher: no KB domains detected; applying playwright context only (%d chars)",
                ticket_id,
                len(pw_ctx),
            )
            return EnrichmentResult(
                enriched_ac=raw_ac + pw_ctx,
                detected_domains=[],
                enrichment_applied=True,
                enrichment_char_count=len(pw_ctx),
            )
        logger.info(
            "[%s] AC Enricher: no domains detected — no-op",
            ticket_id,
        )
        return EnrichmentResult(enriched_ac=raw_ac)

    # ── Step 2: Query KB for enrichment context ───────────────────────
    try:
        kb_articles = _query_kb_for_enrichment(domains)
    except Exception as e:
        logger.warning(
            "[%s] AC Enricher: KB query failed (non-fatal): %s",
            ticket_id,
            e,
        )
        if pw_ctx:
            return EnrichmentResult(
                enriched_ac=raw_ac + pw_ctx,
                detected_domains=domains,
                enrichment_applied=True,
                enrichment_char_count=len(pw_ctx),
            )
        return EnrichmentResult(
            enriched_ac=raw_ac,
            detected_domains=domains,
        )

    if not kb_articles:
        if pw_ctx:
            logger.info(
                "[%s] AC Enricher: no KB articles matched; applying playwright context only (%d chars)",
                ticket_id,
                len(pw_ctx),
            )
            return EnrichmentResult(
                enriched_ac=raw_ac + pw_ctx,
                detected_domains=domains,
                enrichment_applied=True,
                enrichment_char_count=len(pw_ctx),
            )
        logger.info(
            "[%s] AC Enricher: domains detected %s but no KB articles matched — no-op",
            ticket_id,
            domains,
        )
        return EnrichmentResult(
            enriched_ac=raw_ac,
            detected_domains=domains,
        )

    # ── Step 3: Build enrichment context ──────────────────────────────
    context_block = _build_enrichment_context(domains, kb_articles)

    if not context_block and not pw_ctx:
        return EnrichmentResult(
            enriched_ac=raw_ac,
            detected_domains=domains,
        )

    # ── Step 4: Append context to raw AC ──────────────────────────────
    # KB domain context first (existing pattern), then playwright context.
    enriched_ac = raw_ac + context_block + pw_ctx

    article_names = [name for _, name, _ in kb_articles]

    quality_grade = ""
    if quality_result and hasattr(quality_result, "quality_grade"):
        quality_grade = quality_result.quality_grade

    logger.info(
        "[%s] AC Enricher: enriched AC with %d domain(s), %d KB article(s), "
        "+%d chars (playwright=%s, quality=%s)",
        ticket_id,
        len(domains),
        len(kb_articles),
        len(context_block),
        f"{len(pw_ctx)}chars" if pw_ctx else "none",
        quality_grade or "n/a",
    )

    return EnrichmentResult(
        enriched_ac=enriched_ac,
        detected_domains=domains,
        kb_articles_used=article_names,
        enrichment_applied=True,
        enrichment_char_count=len(context_block) + len(pw_ctx),
    )
