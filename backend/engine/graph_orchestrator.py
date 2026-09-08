"""
vQA — LangGraph Multi-Agent Orchestrator (Regression Sub-Graph)
=================================================================
Module: backend/engine/graph_orchestrator.py

Implements a **four-node** LangGraph state machine for **regression test replay**:

    Commander → Surfer → Verifier → [is_verified=True]  → memory_log → END
                                 ↓  [is_verified=False]
                               Debugger → END

This graph is independent of the main vQA ``build_graph()`` in ``graph.py``.
It is designed to be invoked directly for targeted AC-step regression checks,
or embedded as a sub-graph within the main pipeline for autonomous self-healing.

Node Responsibilities
---------------------

Commander
    Receives a raw Acceptance Criteria step string (``ac_step``), enriches it
    with context from the SQLite few-shot memory, and emits a precise natural-
    language browser instruction for the Surfer.  Uses ChatBedrockConverse
    (Claude 3.5 Sonnet) for structured instruction synthesis.

Surfer
    Calls ``run_browser_task()`` from ``web_surfer.py`` and populates
    ``browser_result``.  Always routes to the **Verifier** — the browser-use
    success flag alone is not sufficient to mark an AC step as satisfied.

Verifier  *(New node)*
    LLM-as-a-Judge (``verifier_node.py``).  Compares the AC step against
    ``BrowserResult`` evidence (``final_url``, ``extracted_text``) and emits
    a ``VerificationResult`` with ``is_verified`` + ``failure_reason``.
    Routes to ``memory_log`` on pass, ``debugger`` on fail.

memory_log  *(New node)*
    Fires only after a verified pass.  Writes the successful AC step to
    SQLite (``orchestrator_runs`` + ``persistent_memory``) for future
    few-shot injection into the Commander prompt.

Debugger
    Takes ``error_log``, calls ``query_knowledge_base()`` from
    ``rag_debugger.py``, and uses ChatBedrockConverse to synthesise a
    structured **Refactoring Recommendation** containing:
      - Root Cause (which selector / rule caused the failure)
      - Actionable Fix (code-level change)
      - Prevention Guidance (what to update in the KB or recipe)

SQLite Memory (cross-run few-shot examples)
--------------------------------------------
Successful steps are logged to the same ``memory/learned_patterns.db`` used
by the main vQA graph (via ``backend.memory.persistent.PersistentMemory``),
enabling bidirectional learning across both pipelines.

A separate ``orchestrator_runs`` table tracks regression run outcomes so the
Commander can inject proven patterns as few-shot examples into its prompt.

Graph State
-----------
    OrchestratorState (TypedDict):
        ac_step             : str   — The AC step being tested
        browser_result      : dict  — BrowserResult fields (from Surfer)
        verification_result : dict  — VerificationResult fields (from Verifier)
        error_log           : str   — Failure reason from Verifier (empty on pass)
        fix_recommendation  : str   — Refactoring recommendation from Debugger
        _route              : str   — Routing signal: "memory_log" | "debugger" | ""
        run_id              : str   — Unique ID for this orchestrator invocation
        ticket_id           : str   — Optional Jira ticket ID for attribution
        role_name           : str   — Optional vProMedia role key for authenticated sessions
        auth_state_path     : str   — Absolute path to the Playwright storage-state JSON used

Usage
-----
    from backend.engine.graph_orchestrator import build_orchestrator_graph, make_orchestrator_state

    graph = build_orchestrator_graph()
    result = await graph.ainvoke(
        make_orchestrator_state(
            ac_step="Verify the 'New Request +' button is visible on the dashboard",
            run_id="regression-vc2-1234-abc",
            ticket_id="VC2-1234",
            role_name="account_executive",
        )
    )
    # result["verification_result"]["is_verified"] → True/False
    # result["fix_recommendation"]                 → non-empty only if Verifier failed

Dependencies
------------
  - backend/engine/rag_debugger.py   — query_knowledge_base()
  - backend/engine/web_surfer.py     — run_browser_task(), BrowserResult
  - backend/engine/verifier_node.py  — verifier_node(), VerificationResult
  - backend/memory/persistent.py     — PersistentMemory (SQLite)
  - langchain_aws                    — ChatBedrockConverse
  - langgraph                        — StateGraph, END
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional-import guards
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _LANGGRAPH_AVAILABLE = False
    logger.warning("graph_orchestrator: langgraph not installed (%s)", _e)

try:
    from langchain_aws import ChatBedrockConverse
    from langchain_core.messages import HumanMessage, SystemMessage

    _LANGCHAIN_AWS_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _LANGCHAIN_AWS_AVAILABLE = False
    logger.warning("graph_orchestrator: langchain-aws not installed (%s)", _e)

from backend.config import settings
from backend.engine.rag_debugger import query_knowledge_base
from backend.engine.verifier_node import verifier_node
from backend.engine.web_surfer import BrowserResult, run_browser_task

# ---------------------------------------------------------------------------
# RAG UI rules — optional import so the orchestrator degrades gracefully
# if the vector store has not been initialised yet (first-run, no ingest)
# ---------------------------------------------------------------------------
try:
    from backend.engine.rag_ingestion import query_ui_rules as _rag_query_ui_rules

    _RAG_UI_RULES_AVAILABLE = True
except Exception as _rag_import_err:  # pragma: no cover
    _RAG_UI_RULES_AVAILABLE = False
    logger.warning(
        "graph_orchestrator: rag_ingestion not available (%s) — "
        "Commander will run without vector-KB enrichment. "
        "Run: python -m backend.engine.rag_ingestion to build the index.",
        _rag_import_err,
    )

# Hard cap on how many characters of RAG UI rules to inject into the
# Surfer instruction.  Keeps the browser-use prompt under the context limit
# while still delivering the most relevant rule sections (top-5 nodes).
_RAG_RULES_MAX_CHARS: int = 3_000

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BEDROCK_REGION = settings.aws_bedrock_region
_VQAROOT = Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# SQLite memory for orchestrator run history
# ---------------------------------------------------------------------------

_MEMORY_DIR = _VQAROOT / "memory"
_DB_FILE = _MEMORY_DIR / "learned_patterns.db"
_DB_LOCK = threading.Lock()


def _ensure_orchestrator_table() -> None:
    """
    Create the ``orchestrator_runs`` table if it doesn't exist.

    Called lazily on first write.  Safe to call multiple times (IF NOT EXISTS).
    """
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(_DB_FILE), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_runs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      TEXT    NOT NULL,
                run_id         TEXT    NOT NULL,
                ticket_id      TEXT    DEFAULT '',
                ac_step        TEXT    NOT NULL,
                success        INTEGER NOT NULL DEFAULT 0,
                browser_final_url TEXT DEFAULT '',
                error_log      TEXT    DEFAULT '',
                fix_recommendation TEXT DEFAULT ''
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_ac_step
                ON orchestrator_runs(ac_step);
        """)
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        logger.error("graph_orchestrator: failed to create orchestrator_runs table: %s", exc)


def _log_orchestrator_run(
    run_id: str,
    ac_step: str,
    success: bool,
    final_url: str = "",
    error_log: str = "",
    fix_recommendation: str = "",
    ticket_id: str = "",
) -> None:
    """
    Persist a regression run outcome to the ``orchestrator_runs`` SQLite table.

    Args
    ----
    run_id : str
        Unique ID for this orchestrator invocation.
    ac_step : str
        The AC step that was tested.
    success : bool
        Whether the Surfer completed the step successfully.
    final_url : str
        The browser's final URL (for debugging).
    error_log : str
        Error message from the Surfer (empty on success).
    fix_recommendation : str
        Refactoring recommendation from the Debugger (empty on success).
    ticket_id : str
        Jira ticket ID for traceability.
    """
    _ensure_orchestrator_table()
    ts = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        try:
            conn = sqlite3.connect(str(_DB_FILE), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """INSERT INTO orchestrator_runs
                   (timestamp, run_id, ticket_id, ac_step, success,
                    browser_final_url, error_log, fix_recommendation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts,
                    run_id,
                    ticket_id,
                    ac_step[:240],
                    1 if success else 0,
                    final_url[:500],
                    error_log[:2000],
                    fix_recommendation[:4000],
                ),
            )
            conn.commit()
            conn.close()
            logger.info(
                "graph_orchestrator: logged run '%s' — success=%s, ac_step=%.80s",
                run_id,
                success,
                ac_step,
            )
        except sqlite3.Error as exc:
            logger.error("graph_orchestrator: SQLite write failed: %s", exc)


def _get_few_shot_successes(ac_step: str, limit: int = 3) -> list[dict]:
    """
    Query the SQLite ``orchestrator_runs`` table for past successful runs of
    similar AC steps to use as few-shot examples in the Commander prompt.

    Args
    ----
    ac_step : str
        The current AC step text.
    limit : int
        Maximum number of past examples to return.

    Returns
    -------
    list[dict]
        List of dicts with 'ac_step' and 'browser_final_url' keys.
        Empty if no past successes are found.
    """
    _ensure_orchestrator_table()
    try:
        conn = sqlite3.connect(str(_DB_FILE), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Simple keyword overlap: split ac_step and search
        words = [
            w.lower()
            for w in ac_step.split()
            if len(w) > 3
            and w.lower()
            not in {
                "the",
                "and",
                "that",
                "this",
                "with",
                "from",
                "click",
                "verify",
                "check",
                "navigate",
                "ensure",
                "open",
                "view",
            }
        ]
        if not words:
            conn.close()
            return []

        # LIKE query for each keyword — union of matches
        clauses = " OR ".join(["LOWER(ac_step) LIKE ?" for _ in words])
        params = [f"%{w}%" for w in words] + [limit * 5]
        rows = conn.execute(
            f"SELECT ac_step, browser_final_url FROM orchestrator_runs "
            f"WHERE success = 1 AND ({clauses}) "
            f"ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows[:limit]]
    except sqlite3.Error as exc:
        logger.warning("graph_orchestrator: few-shot query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LangGraph State definition
# ---------------------------------------------------------------------------


class OrchestratorState(TypedDict):
    """
    State schema for the four-node regression orchestrator.

    Attributes
    ----------
    ac_step : str
        The Acceptance Criteria step being regression-tested.
        Example: "Verify the Quick Order form submits successfully."

    browser_result : dict
        Serialised ``BrowserResult`` from the Surfer node.
        Keys: success, final_url, extracted_text, error_message, steps_taken,
        role_name, auth_state_path.
        Empty dict before the Surfer runs.

    verification_result : dict
        Serialised ``VerificationResult`` from the Verifier node.
        Keys: thought_process, is_verified, failure_reason.
        Empty dict before the Verifier runs.

    error_log : str
        When the Verifier returns ``is_verified=False``: the enriched
        ``failure_reason`` string used as the Debugger's RAG query input.
        Empty string when the Verifier passes.

    fix_recommendation : str
        Structured Refactoring Recommendation produced by the Debugger.
        Contains root cause, actionable fix, and prevention guidance.
        Empty string if the Verifier passed (Debugger is skipped).

    _route : str
        Internal routing signal written by the Verifier.
        ``"memory_log"`` → Verifier passed; route to memory_log → END.
        ``"debugger"``   → Verifier failed; route to Debugger → END.

    run_id : str
        Unique ID for this orchestrator invocation (UUID).

    ticket_id : str
        Optional Jira ticket ID for SQLite attribution and log correlation.

    target_url : str
        Base URL of the application under test.
        Injected into the Commander instruction so the Surfer starts
        on the correct environment.

    role_name : str
        Optional vProMedia role key (e.g. ``"account_executive"``) or alias.
        When set, the Surfer node calls ``AuthManager.ensure_authenticated()``
        before launching the browser-use Agent.  Empty string = anonymous.

    auth_state_path : str
        Absolute path to the Playwright storage-state JSON that was injected
        into ``BrowserConfig``.  Populated by the Surfer node.  Empty if no
        role was authenticated.
    """

    ac_step: str
    target_element_types: list[str]  # FEAT-025: roles for semantic tree pruning
    browser_result: dict

    verification_result: dict
    error_log: str
    fix_recommendation: str
    _route: str
    run_id: str
    ticket_id: str
    target_url: str
    role_name: str
    auth_state_path: str


# ---------------------------------------------------------------------------
# LLM factory — delegates to centralized provider
# ---------------------------------------------------------------------------


def _get_llm() -> "ChatBedrockConverse":
    """Create an LLM client for the Commander/Debugger.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Uses the ``commander`` purpose preset (4096 max_tokens, temp=0).
    """
    from backend.llm import get_llm

    return get_llm("commander")


# ---------------------------------------------------------------------------
# Node 1: Commander
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Compiler (Pre-Processor) LLM — fast, cheap model for context pruning
# ---------------------------------------------------------------------------


def _get_compiler_llm() -> "ChatBedrockConverse":
    """Create a fast LLM client for the Pre-Processor call.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Uses the ``compiler`` purpose preset (512 max_tokens, temp=0).
    """
    from backend.llm import get_llm

    return get_llm("compiler")


def _run_compiler_preprocessor(ac_step: str, target_app: str) -> dict:
    """
    Step A — Pre-Processor: synchronous LLM call that returns a lightweight
    JSON context spec dictating what context is actually needed for this step.

    Designed to be called inside ``loop.run_in_executor`` so it never blocks
    the asyncio event loop.

    Args
    ----
    ac_step : str
        The current AC step text.
    target_app : str
        Human-readable application name (e.g. "vProMedia / vSuite").

    Returns
    -------
    dict
        {
          "needed_rag_topics": ["query1", "query2", ...],
          "target_element_types": ["button", "combobox", ...]
        }
        Returns a safe default if the LLM call fails or returns invalid JSON.
    """
    _SAFE_DEFAULT = {
        "needed_rag_topics": [ac_step[:120]],
        "target_element_types": ["button", "link", "textbox", "combobox", "checkbox", "tab"],
    }
    try:
        llm = _get_compiler_llm()
        system_msg = (
            "You are a Context Pruning Pre-Processor for a browser automation agent "
            f"that tests '{target_app}'. Your job is to read an Acceptance Criteria step "
            "and return a COMPACT JSON object (no prose, no markdown) specifying:\n\n"
            "  needed_rag_topics: an array of 1-3 SHORT search queries to retrieve relevant "
            "UI interaction rules from a vector knowledge base. Be specific (e.g. "
            '["compact view sort button", "PrimeNG p-select dropdown"]) rather than '
            "copying the full AC step verbatim.\n\n"
            "  target_element_types: an array of ARIA roles the agent actually needs to "
            'interact with for this step (e.g. ["button", "combobox", "table"]). '
            "ONLY include roles that will be directly acted on — omit everything else "
            "(paragraphs, images, decorative links, etc.).\n\n"
            "Return ONLY a valid JSON object with those two keys. No other text."
        )
        user_msg = f"Acceptance Criteria Step:\n{ac_step}\n\nReturn the JSON context spec now:"
        from langchain_core.messages import HumanMessage as _HM
        from langchain_core.messages import SystemMessage as _SM

        response = llm.invoke([_SM(content=system_msg), _HM(content=user_msg)])
        raw = (response.content or "").strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        import json as _json

        spec = _json.loads(raw)
        # Validate and normalise
        rag_topics = spec.get("needed_rag_topics", [ac_step[:120]])
        elem_types = spec.get("target_element_types", _SAFE_DEFAULT["target_element_types"])
        if not isinstance(rag_topics, list) or not rag_topics:
            rag_topics = [ac_step[:120]]
        if not isinstance(elem_types, list) or not elem_types:
            elem_types = _SAFE_DEFAULT["target_element_types"]
        return {"needed_rag_topics": rag_topics[:5], "target_element_types": elem_types[:10]}
    except Exception as exc:
        logger.warning("graph_orchestrator: Pre-Processor LLM call failed (%s) — using safe default.", exc)
        return _SAFE_DEFAULT


def _run_targeted_rag(topics: list[str], top_k: int = 3) -> str:
    """
    Step B helper — Targeted RAG: run one ``query_ui_rules`` call per topic and
    merge the results.  Deduplicates lines so overlapping topics don't double-inject.

    Designed to be called inside ``loop.run_in_executor``.

    Args
    ----
    topics : list[str]
        Search queries from the Pre-Processor.
    top_k : int
        Number of KB nodes to retrieve per query.

    Returns
    -------
    str
        De-duplicated, merged RAG text.  Empty string if unavailable.
    """
    if not _RAG_UI_RULES_AVAILABLE:
        return ""
    seen_lines: set[str] = set()
    merged: list[str] = []
    for topic in topics:
        try:
            chunk = _rag_query_ui_rules(topic.strip(), top_k=top_k)
            if not chunk or not chunk.strip():
                continue
            for line in chunk.splitlines():
                stripped = line.rstrip()
                if stripped and stripped not in seen_lines:
                    seen_lines.add(stripped)
                    merged.append(stripped)
        except Exception as exc:
            logger.warning("graph_orchestrator: Targeted RAG query failed for topic '%s': %s", topic[:60], exc)
    return "\n".join(merged)


async def commander_node(state: OrchestratorState) -> dict:
    """
    Commander — Dynamic Context Optimizer (two-step Prompt Compiler).

    This node has been upgraded from a static RAG injector into a
    semantic context assembler that prunes both RAG and DOM data before
    calling the Surfer, preventing prompt bloat and attention dilution.

    Pipeline
    --------
    Step A — Pre-Processor (Context Pruning)
        A fast synchronous call to Claude 3 Haiku (via ``run_in_executor``)
        analyses the current AC step and returns a lightweight JSON spec:
          • ``needed_rag_topics``   — targeted search queries for the vector KB
          • ``target_element_types`` — ARIA roles the Surfer should focus on

    Step B — Semantic Context Assembly
        a. Targeted RAG  : pass ``needed_rag_topics`` to ``query_ui_rules``
           instead of the full AC step (2-3 focused queries > 1 broad query).
        b. DOM pruning hint : include ``target_element_types`` in the Surfer
           instruction so it can filter its interactive element list.
        c. Final assembly : merge Pruned RAG + DOM hint + Execution History
           + Human Guidance.  Human Guidance and AC step are ALWAYS placed
           LAST so Claude reads them with maximum attention (recency effect).

    Bedrock thread safety
    ---------------------
    Both the Pre-Processor call and the Targeted RAG queries are executed
    inside ``loop.run_in_executor`` — neither blocks the asyncio event loop.

    Args
    ----
    state : OrchestratorState
        Current graph state. Must contain ``ac_step``.

    Returns
    -------
    dict
        Partial state update: ``browser_result`` with ``_instruction`` key.
    """
    run_id: str = state.get("run_id", "")
    ac_step: str = state.get("ac_step", "")
    target_url: str = state.get("target_url", settings.target_url)
    # MIGRATION: identity from the active AppProfile.
    try:
        from backend.profiles import get_active_profile as _gap_orch

        target_app = _gap_orch().display_name
    except Exception:
        target_app = "vProMedia / vSuite"

    logger.info(
        "[%s] Commander (Prompt Compiler): synthesising instruction for AC step: %.120s",
        run_id,
        ac_step,
    )

    # ── 1. Fetch few-shot examples from SQLite ─────────────────────────────
    few_shot_rows = _get_few_shot_successes(ac_step)
    few_shot_text = ""
    if few_shot_rows:
        examples = "\n".join(
            f"  • STEP: {r['ac_step'][:120]}\n"
            f"    OUTCOME: completed successfully (URL: {r.get('browser_final_url', '?')[:80]})"
            for r in few_shot_rows
        )
        few_shot_text = (
            "\n\n--- FEW-SHOT EXAMPLES (similar past successes) ---\n" + examples + "\n--- END FEW-SHOT ---\n"
        )

    # ── Step A: Pre-Processor — run in thread so we don't block the loop ──
    loop = asyncio.get_event_loop()
    logger.info("[%s] Commander Step A: running Pre-Processor (Haiku)…", run_id)
    context_spec: dict = await loop.run_in_executor(
        None,
        lambda: _run_compiler_preprocessor(ac_step, target_app),
    )
    needed_rag_topics: list[str] = context_spec.get("needed_rag_topics", [ac_step[:120]])
    target_element_types: list[str] = context_spec.get("target_element_types", [])
    logger.info(
        "[%s] Step A complete — rag_topics=%s, elem_types=%s",
        run_id,
        needed_rag_topics,
        target_element_types,
    )

    # ── Step B-a: Targeted RAG (one query per topic, merged + deduped) ────
    rag_ui_rules_block: str = ""
    if _RAG_UI_RULES_AVAILABLE and needed_rag_topics:
        logger.info(
            "[%s] Commander Step B-a: running Targeted RAG for %d topic(s)…",
            run_id,
            len(needed_rag_topics),
        )
        raw_rules: str = await loop.run_in_executor(
            None,
            lambda: _run_targeted_rag(needed_rag_topics, top_k=3),
        )
        if raw_rules and raw_rules.strip():
            capped = raw_rules.strip()
            if len(capped) > _RAG_RULES_MAX_CHARS:
                capped = capped[:_RAG_RULES_MAX_CHARS].rsplit("\n", 1)[0]
                capped += f"\n... [UI rules truncated — showing first {_RAG_RULES_MAX_CHARS} chars]"
            rag_ui_rules_block = capped
            logger.info(
                "[%s] Targeted RAG retrieved — %d chars across %d topic(s)",
                run_id,
                len(rag_ui_rules_block),
                len(needed_rag_topics),
            )
        else:
            logger.debug("[%s] Targeted RAG returned empty result.", run_id)

    # ── Step B-b: DOM pruning hint for the Surfer instruction ─────────────
    dom_hint = ""
    if target_element_types:
        elem_list = ", ".join(f'"{t}"' for t in target_element_types)
        dom_hint = (
            f"\n\n<dom_filter>\n"
            f"SEMANTIC DOM PRUNING — For this step, focus ONLY on these element types: [{elem_list}].\n"
            f"Ignore <p> tags, decorative images, unrelated links, and any element whose "
            f"role is not in the list above.\n"
            f"</dom_filter>"
        )

    # ── Step B-c: Build Commander system prompt ────────────────────────────
    system_prompt = (
        "You are the Commander node of a multi-agent browser regression pipeline. "
        "Your job is to translate a raw Acceptance Criteria (AC) step into a "
        "SINGLE, precise, self-contained natural-language browser instruction that "
        "a browser automation agent can execute without additional context.\n\n"
        "Rules:\n"
        "1. The instruction MUST start with the target application URL.\n"
        "2. Use concrete UI element names (button labels, column headers, form field labels).\n"
        "3. Break compound AC steps into a numbered sequence of actions.\n"
        "4. Do NOT use vague verbs like 'check' or 'ensure' — use 'click', 'fill', "
        "'verify the text', 'assert the URL contains', etc.\n"
        "5. If the AC step involves verification, end the instruction with "
        "'Return the verified value or PASS/FAIL'.\n"
        "6. Output ONLY the instruction text — no preamble, no markdown, no JSON.\n"
        f"{few_shot_text}"
    )

    user_msg = (
        f"Target application URL: {target_url}\n\n"
        f"Acceptance Criteria Step:\n{ac_step}\n\n"
        f"Write the browser instruction now:"
    )

    # ── Step B-c continued: Call commander LLM ────────────────────────────
    instruction = ""
    try:
        llm = _get_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
        instruction = (response.content or "").strip()
        logger.info("[%s] Commander: instruction synthesised (%.120s …)", run_id, instruction)
    except Exception as exc:
        instruction = f"Navigate to {target_url} and {ac_step}"
        logger.warning(
            "[%s] Commander: LLM call failed (%s) — using raw AC step as instruction",
            run_id,
            exc,
        )

    # ── Final assembly — ORDERING IS CRITICAL ─────────────────────────────
    # Layout (highest attention first in LLM reading order):
    #   1. UI_RULES (RAG)         — hard constraints from the KB
    #   2. DOM filter hint        — element types the Surfer should focus on
    #   3. Core action sequence   — the LLM-synthesised browser instruction
    #   4. Human Guidance / AC    — ALWAYS LAST (recency = max attention weight)
    #
    # NOTE: The AC step is embedded in the core instruction (step 3) which
    # already ends with the goal statement. The UI_RULES block is prepended
    # so the Surfer reads the interaction rules BEFORE planning actions.
    final_instruction = instruction + dom_hint

    if rag_ui_rules_block:
        final_instruction = (
            "<UI_RULES>\n"
            "CRITICAL UI RULES — follow the CSS selectors and action patterns below "
            "EXACTLY. These rules were derived from a live audit of the application's "
            "Angular source code and are authoritative over generic Playwright locators.\n\n"
            + rag_ui_rules_block
            + "\n</UI_RULES>\n\n"
            + final_instruction
        )
        logger.info(
            "[%s] Commander: UI_RULES block prepended (%d total chars)",
            run_id,
            len(final_instruction),
        )

    return {
        "browser_result": {"_instruction": final_instruction},
        "target_element_types": target_element_types,  # FEAT-025
    }


# ---------------------------------------------------------------------------
# Node 2: Surfer
# ---------------------------------------------------------------------------


async def surfer_node(state: OrchestratorState) -> dict:
    """
    Surfer: execute the Commander's instruction via browser-use Agent.

    Reads the ``_instruction`` key from ``browser_result`` (set by Commander),
    calls ``run_browser_task()``, and:

    - On SUCCESS  → logs the step to SQLite, writes success data to state,
                    sets ``_route = "END"``.
    - On FAILURE  → writes ``error_log`` (combined error + browser details),
                    sets ``_route = "debugger"``.

    When ``role_name`` is present in state, passes it to ``run_browser_task``
    which will call the ``AuthManager`` to guarantee a valid Playwright
    storage-state JSON before the browser-use Agent launches.

    Args
    ----
    state : OrchestratorState
        Must contain ``browser_result._instruction``.
        May contain ``role_name`` for authenticated sessions.

    Returns
    -------
    dict
        Partial state update with ``browser_result``, ``error_log``,
        ``auth_state_path``, and ``_route``.
    """
    run_id: str = state.get("run_id", "")
    state.get("ticket_id", "")
    ac_step: str = state.get("ac_step", "")
    target_url: str = state.get("target_url", settings.target_url)
    role_name: str = state.get("role_name", "") or ""

    # Extract instruction built by Commander
    current_result: dict = state.get("browser_result", {})
    instruction: str = current_result.get("_instruction", "") or ac_step

    logger.info(
        "[%s] Surfer: executing browser task — role=%s, %.120s",
        run_id,
        role_name or "anonymous",
        instruction,
    )

    result: BrowserResult = await run_browser_task(
        instruction=instruction,
        role_name=role_name or None,
        start_url=target_url if not role_name else "",
    )

    result_dict = {
        "success": result.success,
        "final_url": result.final_url,
        "extracted_text": result.extracted_text,
        "error_message": result.error_message,
        "steps_taken": result.steps_taken,
        "_instruction": instruction,  # preserve for audit
        "role_name": result.role_name,
        "auth_state_path": result.auth_state_path,
    }

    # ── Always forward to Verifier regardless of browser-use success flag ────
    # browser-use's internal success heuristic (agent.is_done()) is insufficient
    # to confirm an AC step was met — the LLM-as-a-Judge Verifier makes the
    # authoritative pass/fail decision based on page evidence.
    if result.success:
        logger.info(
            "[%s] Surfer: browser-use reports SUCCESS — forwarding to Verifier (final_url=%s, steps=%d)",
            run_id,
            result.final_url,
            result.steps_taken,
        )
    else:
        logger.warning(
            "[%s] Surfer: browser-use reports FAILURE — forwarding to Verifier for diagnosis (error=%.160s)",
            run_id,
            result.error_message,
        )

    # _route is intentionally left blank here — verifier_node overwrites it.
    return {
        "browser_result": result_dict,
        "auth_state_path": result.auth_state_path,
        "_route": "",  # Verifier owns the routing decision
    }


# ---------------------------------------------------------------------------
# Node 3: Debugger
# ---------------------------------------------------------------------------


async def debugger_node(state: OrchestratorState) -> dict:
    """
    Debugger: diagnose the browser failure and produce a Refactoring Recommendation.

    1. Takes ``error_log`` from state.
    2. Calls ``query_knowledge_base(error_log)`` to retrieve semantically
       matched code snippets and documentation rules.
    3. Calls ChatBedrockConverse to synthesise a structured recommendation.

    The recommendation follows this exact schema:

        ## Root Cause
        <What selector / timing / rule caused the failure>

        ## Actionable Fix
        <Exact code or locator change required>

        ## KB / Recipe Update
        <What to add/change in knowledge/ or blueprints/ to prevent recurrence>

        ## Confidence
        HIGH / MEDIUM / LOW — based on how closely the RAG snippets match the error

    Args
    ----
    state : OrchestratorState
        Must contain ``error_log``.

    Returns
    -------
    dict
        Partial state update: ``fix_recommendation`` (the structured report).
    """
    run_id: str = state.get("run_id", "")
    ticket_id: str = state.get("ticket_id", "")
    ac_step: str = state.get("ac_step", "")
    error_log: str = state.get("error_log", "")

    logger.info("[%s] Debugger: analysing failure for AC step: %.120s", run_id, ac_step)

    # ── Step 1: Semantic RAG lookup ─────────────────────────────────────────
    rag_context: str = query_knowledge_base(error_log, top_k=4)
    if not rag_context:
        logger.warning(
            "[%s] Debugger: RAG returned no snippets — proceeding without code context",
            run_id,
        )
        rag_context = "(No matching code snippets found in the knowledge base.)"

    # ── Step 2: LLM Refactoring Recommendation ─────────────────────────────
    system_prompt = (
        "You are the Debugger node of a multi-agent browser regression pipeline. "
        "Your goal is to produce a HIGHLY STRUCTURED, actionable Refactoring "
        "Recommendation based on:\n"
        "  (a) The error log from the failed browser task\n"
        "  (b) Semantically matched code snippets and documentation retrieved "
        "from the knowledge base (RAG context below)\n\n"
        "Output Format — use EXACTLY these section headers:\n\n"
        "## Root Cause\n"
        "Identify the EXACT selector, timing assumption, API contract, or UI rule "
        "that caused the failure. Be specific (e.g. 'The locator get_by_role(button, "
        'name="Submit All") fails because PrimeNG renders the button as a p-button '
        "component with role=button only after the overlay animation completes.').\n\n"
        "## Actionable Fix\n"
        "Provide the precise code change, selector replacement, or wait strategy "
        "needed to make the test pass. Include code examples where possible.\n\n"
        "## KB / Recipe Update\n"
        "Specify what needs to be updated in the knowledge base "
        "(knowledge/*.md, knowledge/blueprints/*.json) or selector registry to "
        "prevent this failure from recurring in future runs.\n\n"
        "## Confidence\n"
        "Rate HIGH / MEDIUM / LOW based on how strongly the RAG snippets support "
        "your diagnosis. If RAG returned no matches, always output LOW.\n\n"
        "Do NOT add commentary outside these four sections."
    )

    user_msg = (
        f"AC Step Under Test:\n{ac_step}\n\n"
        f"Error Log:\n{error_log}\n\n"
        f"RAG Context (matched code / docs):\n{rag_context}\n\n"
        f"Produce the Refactoring Recommendation now:"
    )

    fix_recommendation = ""
    try:
        llm = _get_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
        fix_recommendation = (response.content or "").strip()
        logger.info(
            "[%s] Debugger: recommendation generated (%.120s …)",
            run_id,
            fix_recommendation,
        )
    except Exception as exc:
        fix_recommendation = (
            f"## Root Cause\nDebugger LLM call failed: {exc}\n\n"
            f"## Actionable Fix\nReview the error log manually:\n{error_log[:500]}\n\n"
            f"## KB / Recipe Update\nN/A — LLM unavailable.\n\n"
            f"## Confidence\nLOW"
        )
        logger.error("[%s] Debugger: LLM call failed: %s", run_id, exc)

    # Persist failure + recommendation to SQLite
    _log_orchestrator_run(
        run_id=run_id,
        ac_step=ac_step,
        success=False,
        error_log=error_log,
        fix_recommendation=fix_recommendation,
        ticket_id=ticket_id,
    )

    return {"fix_recommendation": fix_recommendation}


# ---------------------------------------------------------------------------
# Memory-log node (fires only on verified pass)
# ---------------------------------------------------------------------------


async def memory_log_node(state: OrchestratorState) -> dict:
    """
    memory_log: persist a verified-pass outcome to SQLite and PersistentMemory.

    Fires ONLY when the Verifier returns ``is_verified=True``.  Writes the
    successful AC step to:
      1. ``orchestrator_runs`` SQLite table (for Commander few-shot injection)
      2. ``persistent_memory`` (shared vQA planner few-shot store)

    Isolated from the Surfer so that memory is only written after the LLM
    judge has confirmed the AC was actually satisfied.

    Args
    ----
    state : OrchestratorState
        Must contain: ``run_id``, ``ac_step``, ``browser_result``, ``ticket_id``.

    Returns
    -------
    dict
        Empty dict — this node is a pure side-effect node (no state mutations).
    """
    run_id: str = state.get("run_id", "")
    ac_step: str = state.get("ac_step", "")
    ticket_id: str = state.get("ticket_id", "")
    browser_result: dict = state.get("browser_result", {})
    final_url: str = browser_result.get("final_url", "")
    instruction: str = browser_result.get("_instruction", "")

    logger.info(
        "[%s] memory_log: persisting VERIFIED pass — ac_step=%.80s",
        run_id,
        ac_step,
    )

    # ── SQLite orchestrator_runs ───────────────────────────────────────────
    _log_orchestrator_run(
        run_id=run_id,
        ac_step=ac_step,
        success=True,
        final_url=final_url,
        ticket_id=ticket_id,
    )

    # ── Shared PersistentMemory (vQA planner few-shot store) ───────────────
    try:
        from backend.memory.persistent import persistent_memory

        persistent_memory.record(
            situation=f"orchestrator: {ac_step[:120]}",
            strategy_tried=f"browser_use_agent:{instruction[:80]}",
            worked=True,
            ac_step=ac_step,
            ticket_id=ticket_id,
        )
        logger.info("[%s] memory_log: persistent_memory.record OK", run_id)
    except Exception as mem_exc:
        logger.warning(
            "[%s] memory_log: persistent_memory.record failed (non-fatal): %s",
            run_id,
            mem_exc,
        )

    return {}  # No state mutations — side-effect only


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------


def route_after_verifier(
    state: OrchestratorState,
) -> Literal["memory_log", "debugger"]:
    """
    Conditional edge: read ``_route`` written by ``verifier_node``.

    Routes
    ------
    ``"memory_log"`` → ``memory_log_node`` → END  (AC verified)
    ``"debugger"``   → ``debugger_node``   → END  (AC not verified)
    <anything else>  → ``"debugger"``             (safety default)
    """
    route = state.get("_route", "")
    run_id = state.get("run_id", "")
    if route == "memory_log":
        logger.info("[%s] Routing: Verifier → memory_log → END (AC verified)", run_id)
        return "memory_log"
    logger.info("[%s] Routing: Verifier → debugger (AC not verified or ambiguous)", run_id)
    return "debugger"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_orchestrator_graph() -> "StateGraph":
    """
    Assemble and compile the four-node regression orchestrator.

    Topology
    --------
    ::

        START ──► commander ──► surfer ──► verifier ──► [is_verified=True] ──► memory_log ──► END
                                                    ╰──► [is_verified=False] ─► debugger   ──► END

    Node Summary
    ------------
    commander   Translates raw AC step → precise browser instruction (LLM).
    surfer      Executes instruction via browser-use Agent; always advances to verifier.
    verifier    LLM-as-a-Judge: compares AC to browser evidence → pass/fail verdict.
    memory_log  Persists verified-pass to SQLite + PersistentMemory (side-effect only).
    debugger    RAG lookup + LLM refactoring recommendation on failure.

    Returns
    -------
    langgraph.graph.StateGraph
        Compiled graph ready for ``await graph.ainvoke(initial_state)``.

    Raises
    ------
    RuntimeError
        If langgraph is not installed.

    Example
    -------
    >>> from backend.engine.graph_orchestrator import build_orchestrator_graph, make_orchestrator_state
    >>> graph = build_orchestrator_graph()
    >>> result = await graph.ainvoke(
    ...     make_orchestrator_state(
    ...         ac_step="Verify 'New Request +' button is visible on the dashboard",
    ...         ticket_id="VC2-1234",
    ...         role_name="account_executive",
    ...     )
    ... )
    >>> print(result["verification_result"]["is_verified"])  # True / False
    >>> print(result["fix_recommendation"])                  # Non-empty on failure
    """
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError("graph_orchestrator: langgraph is not installed. Run: pip install langgraph>=0.2.0")

    logger.info("graph_orchestrator: building orchestrator StateGraph …")
    graph = StateGraph(OrchestratorState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("commander", commander_node)
    graph.add_node("surfer", surfer_node)
    graph.add_node("verifier", verifier_node)  # from verifier_node.py
    graph.add_node("memory_log", memory_log_node)
    graph.add_node("debugger", debugger_node)

    # ── Entry point ───────────────────────────────────────────────────────
    graph.set_entry_point("commander")

    # ── Sequential edges ──────────────────────────────────────────────────
    graph.add_edge("commander", "surfer")
    graph.add_edge("surfer", "verifier")  # Surfer ALWAYS flows to Verifier

    # ── Conditional: verifier → memory_log (pass) or debugger (fail) ──────
    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            "memory_log": "memory_log",
            "debugger": "debugger",
        },
    )

    # ── Terminal edges ────────────────────────────────────────────────────
    graph.add_edge("memory_log", END)  # Verified pass → done
    graph.add_edge("debugger", END)  # Failure analysed → done

    compiled = graph.compile()
    logger.info(
        "graph_orchestrator: StateGraph compiled — nodes: commander → surfer → verifier → [memory_log | debugger] → END"
    )
    return compiled


# ---------------------------------------------------------------------------
# Convenience factory for initial state
# ---------------------------------------------------------------------------


def make_orchestrator_state(
    ac_step: str,
    target_url: str = "",
    ticket_id: str = "",
    run_id: str = "",
    role_name: str = "",
) -> OrchestratorState:
    """
    Create a fully initialised ``OrchestratorState`` dict.

    Args
    ----
    ac_step : str
        The Acceptance Criteria step to regression-test.
    target_url : str
        Base URL of the application under test.
        Defaults to ``settings.target_url``.
    ticket_id : str
        Jira ticket ID for attribution (optional).
    run_id : str
        Unique run ID.  Auto-generated if empty.
    role_name : str
        vProMedia role key or alias for authenticated sessions
        (e.g. ``"account_executive"``).  Empty string = anonymous.

    Returns
    -------
    OrchestratorState
        Ready-to-use initial state dict.

    Example
    -------
    >>> state = make_orchestrator_state(
    ...     ac_step="Verify 'New Request +' button is visible",
    ...     role_name="account_executive",
    ...     ticket_id="VC2-1234",
    ... )
    >>> graph = build_orchestrator_graph()
    >>> result = await graph.ainvoke(state)
    """
    return OrchestratorState(
        ac_step=ac_step,
        target_element_types=[],  # FEAT-025
        browser_result={},
        verification_result={},
        error_log="",
        fix_recommendation="",
        _route="",
        run_id=run_id or f"orch-{uuid.uuid4().hex[:8]}",
        ticket_id=ticket_id,
        target_url=target_url or settings.target_url,
        role_name=role_name,
        auth_state_path="",
    )
