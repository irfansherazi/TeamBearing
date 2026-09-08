"""
vQA — LangGraph State Schema
=============================
Module: backend/engine/state.py

Defines the ``VQAState`` TypedDict — the single shared data contract
that flows between every node in the vQA LangGraph state machine.

Architecture Context
--------------------
LangGraph passes state through nodes as an immutable snapshot.  Each
node returns a *partial* update dict; LangGraph merges it back into the
full state using the ``Annotated`` reducer functions declared here:

    Annotated[list[T], operator.add]
        → the returned list is APPENDED to the existing list.
        → used for audit logs, screenshots, bug logs (grow-only).

    Annotated[dict, _merge_dicts]
        → the returned dict is MERGED (shallow) into the existing dict.
        → used for report_sections (accumulate across roles).

    Plain field (no Annotated)
        → the node's returned value OVERWRITES the existing value.
        → used for scalar state like current_page_url, retry_count.

Sub-Types
---------
This file defines three TypedDicts that compose into VQAState:

    ExecutionStep       — one granular browser action in the audit log
    RoleContext         — credentials + permissions for the active role
    JiraTicketContext   — parsed Jira ticket data driving the run

Data Flow
---------
    jira_fetch_node     → populates jira_ticket
    ac_parser_node      → populates jira_ticket.acceptance_criteria_steps
                            + test_plan (structured plan)
                            + structured_step_index (initialized to 0)
    setup_role_node     → populates role_context
    login_node          → populates browser_session_active, current_page_url
    planner_node        → populates planned_action, current_screenshot_b64,
                          current_accessibility_tree
    executor_node       → appends to detailed_execution_log + screenshots
    evaluator_node      → updates retry_count, ac_step_index, ac_steps_completed
    reporter_node       → populates s3_video_url, s3_report_url,
                          final_html_report

See Also
--------
    backend/engine/graph.py     — StateGraph wiring that uses VQAState
    backend/engine/planner.py   — reads current_screenshot_b64, writes planned_action
    backend/engine/executor.py  — reads planned_action, appends ExecutionStep
"""

import json
import operator
import time
from datetime import datetime, timezone
import os
import sqlite3
from typing import Annotated, Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Reducer helper
# ---------------------------------------------------------------------------


def _merge_dicts(a: dict, b: dict) -> dict:
    """
    Shallow-merge two dicts, with ``b`` values overriding ``a``.

    Used as the LangGraph reducer for ``report_sections`` so that each
    node can contribute its own section without knowing about others.

    Args
    ----
    a : dict
        The existing accumulated dict from previous nodes.
    b : dict
        The partial update returned by the current node.

    Returns
    -------
    dict
        Merged result: all keys from ``a`` plus all keys from ``b``;
        where keys overlap, ``b``'s value wins.

    Example
    -------
    >>> _merge_dicts({"login": "ok"}, {"quick_order": "pass"})
    {'login': 'ok', 'quick_order': 'pass'}
    """
    return {**a, **b}


def _deduplicated_add(a: list[int], b: list[int]) -> list[int]:
    """
    BUG-003 fix: Append-merge two int lists with deduplication.

    Used as the LangGraph reducer for ``ac_steps_completed`` to prevent
    duplicate step indices. The old ``operator.add`` reducer allowed both
    the verifier and evaluator to append the same step index, inflating
    completion counts and causing incorrect pass/fail reporting in the
    reporter and WebSocket status updates.

    Args
    ----
    a : list[int]
        The existing accumulated list from previous nodes.
    b : list[int]
        The partial update returned by the current node.

    Returns
    -------
    list[int]
        Combined list with no duplicate indices, preserving order.
    """
    seen = set(a)
    result = list(a)
    for item in b:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# ExecutionStep — one granular browser action
# ---------------------------------------------------------------------------


class ExecutionStep(TypedDict, total=False):
    """
    A single granular browser action recorded in the audit trail.

    An ``ExecutionStep`` is appended to ``VQAState.detailed_execution_log``
    by the ``executor_node`` after every browser interaction — whether it
    succeeds or fails.  This provides the raw material for the HTML audit
    report and enables post-mortem debugging.

    All fields are optional (``total=False``) because the executor builds
    the entry incrementally; some data (e.g. ``screenshot_url``) is only
    available after the S3 upload completes.

    Attributes
    ----------
    step_index : int
        Zero-based sequential index of this step within the run.
        Used to order steps in the audit report.

    ac_step_index : int
        Which Acceptance Criteria step this browser action belongs to.
        Multiple ``ExecutionStep`` entries may map to the same AC step
        (e.g. fill + click to complete one AC requirement).

    timestamp : str
        ISO-8601 datetime string (UTC) when the action was dispatched.
        Example: ``"2026-04-01T21:15:30.123Z"``

    action_type : str
        The category of browser action performed.
        One of: ``"navigate"``, ``"click"``, ``"fill"``, ``"select"``,
        ``"check"``, ``"screenshot"``, ``"verify"``, ``"wait"``.

    action_payload : dict
        The raw JSON action object returned by the LLM planner.
        Preserved verbatim so we can trace exactly what Claude decided.
        Example: ``{"action": "click", "role": "button", "name": "Submit"}``

    locator_strategy : str
        The Playwright locator method used to find the element.
        One of: ``"get_by_role"``, ``"get_by_text"``, ``"get_by_label"``,
        ``"get_by_placeholder"``, ``"css"``, ``"xpath"``.

    locator_value : str
        Human-readable description of the locator argument(s).
        Example: ``"role=button, name='Submit All'"``

    data_input : str | None
        The value typed or filled into the element, if any.
        ``None`` for click/navigate actions that don't supply text.

    screenshot_url : str
        Presigned or public S3 URL of the post-action screenshot.
        Embedded in the HTML audit report for visual verification.

    accessibility_tree_snippet : str
        The relevant ARIA subtree fragment at the time of the action.
        Stored for debugging cases where the screenshot is ambiguous.

    success : bool
        ``True`` if Playwright completed the action without raising an
        exception, ``False`` if a ``TimeoutError`` or other error occurred.

    error_message : str | None
        The exception message if ``success`` is ``False``.
        ``None`` when the action succeeded.

    self_heal_attempt : int
        How many times the agent retried this specific action.
        ``0`` = first attempt. ``1``, ``2``, ``3`` = retry iterations.
        Exceeding ``settings.max_retries`` causes the run to be marked FAILED.

    llm_reasoning : str
        The textual reasoning the LLM provided for choosing this action.
        Surfaced verbatim in the audit report under "Why did the agent do this?"
    """

    step_index: int
    ac_step_index: int
    timestamp: str
    action_type: str
    action_payload: dict
    locator_strategy: str
    locator_value: str
    data_input: str | None
    screenshot_url: str
    accessibility_tree_snippet: str
    success: bool
    error_message: str | None
    self_heal_attempt: int
    llm_reasoning: str
    llm_observation: str  # ReAct: what the agent saw before deciding
    llm_thought: str  # ReAct: why the agent chose this action
    # ── Amnesic Loop Comparison (FEAT-062) ──────────────────────────
    # Page state captured IMMEDIATELY after this action sub-step.
    # Used by evaluator to detect stagnant loops.
    post_url: str
    post_element_count: int | None
    # ── T3-e: Execution Layer Attribution (FEAT-118 Phase 5) ────────
    # Which deterministic layer produced (or was responsible for) this step.
    # One of: "reflex" | "bedrock_planner" | "cv_fallback" | "hitl"
    # Omitted (None) for legacy steps where attribution was not tracked.
    execution_layer: str  # Literal["reflex", "bedrock_planner", "cv_fallback", "hitl"]


# ---------------------------------------------------------------------------
# RoleContext — active user role
# ---------------------------------------------------------------------------


class RoleContext(TypedDict, total=False):
    """
    Credentials and permission context for the currently executing user role.

    Populated by ``setup_role_node`` from two sources:

    1. ``backend/engine/roles.py`` — login credentials loaded from env vars.
    2. AWS Bedrock Roles KB (``JXMMTMTI06``) — permission matrix via RAG.

    The entire ``RoleContext`` is injected into the LLM system prompt so
    the planner knows what the role can and cannot do, which affects:
      - Which UI elements are expected to be visible / hidden
      - Whether RBAC violations should be flagged during evaluation
      - How to interpret ambiguous page states

    Attributes
    ----------
    role_name : str
        Human-readable display name.
        Example: ``"Account Executive"``

    role_key : str
        Machine-readable key matching the API ``role`` parameter.
        Example: ``"account_executive"``

    login_email : str
        Email address for this role's test account.
        Loaded from env: ``ROLE_EMAIL_AE``, ``ROLE_EMAIL_PRODUCER``, etc.

    login_password : str
        Password for this role's test account.
        Loaded from env: ``ROLE_DEFAULT_PASSWORD``.
        NEVER logged or included in audit reports.

    permissions : dict
        Boolean permission flags from the Roles KB.
        Example::

            {
                "enter_requests": True,
                "view_own_drafts": True,
                "view_all_drafts": False,
                "approve_scripts": True,
            }

    constraints : list[str]
        Plain-English constraint strings injected into the LLM system prompt.
        The planner uses these to avoid navigating to restricted areas and
        to identify RBAC violations.
        Example::

            [
                "Can create Quick Orders (QO)",
                "Cannot access 'View All Spots'",
                "Can approve scripts for own clients only",
            ]
    """

    role_name: str
    role_key: str
    login_email: str
    login_password: str
    permissions: dict
    constraints: list[str]


# ---------------------------------------------------------------------------
# JiraTicketContext — parsed Jira ticket data
# ---------------------------------------------------------------------------


class JiraTicketContext(TypedDict, total=False):
    """
    Parsed Jira ticket data that drives the entire test execution.

    Populated by ``jira_fetch_node`` (raw fields) and ``ac_parser_node``
    (parsed AC steps).  This replaces the legacy Knowledge Base approach
    where test requirements were stored in Bedrock — Jira IS the test plan.

    Attributes
    ----------
    ticket_id : str
        The Jira issue key.
        Example: ``"VC2-8967"``

    summary : str
        The Jira issue title / summary field.
        Used as the test run title in the HTML audit report header.

    description : str
        Full description text extracted from the Jira issue body.
        Cleaned of Atlassian Document Format (ADF) markup.
        Provided to the LLM as supplementary planning context.

    acceptance_criteria : str
        Raw text content of ``customfield_10031`` (Acceptance Criteria).
        This is the PRIMARY source of truth for what the agent tests.

    acceptance_criteria_steps : list[str]
        Structured list of discrete, testable steps parsed from
        ``acceptance_criteria`` by the ``ac_parser_node`` LLM call.

        Example::

            [
                "Verify login as Account Executive (JWT in localStorage)",
                "Click the 'New Request +' button",
                "Select 'Radio Commercial' from the ad type selector",
                "Fill client field with 'Bob'",
                "Verify the Quick Order form is visible and populated",
                "Verify 'Submit All' button is enabled",
            ]

        Each item in this list becomes a goal for one iteration of the
        planner → executor → evaluator inner loop.
    """

    ticket_id: str
    summary: str
    description: str
    acceptance_criteria: str
    acceptance_criteria_steps: list[str]
    # Attachment metadata (added in TASK-047)
    attachments: list[dict]
    # Credential fields extracted from the ticket description:
    override_login_email: str
    override_login_password: str
    # "complete" = both email+password found, skip pre-login
    # "partial"  = only email or only password found, prompt user
    # "none"     = no credentials in ticket, use role KB
    credential_status: Literal["complete", "partial", "none"]


# ---------------------------------------------------------------------------
# VQAState — root LangGraph state
# ---------------------------------------------------------------------------


class VQAState(TypedDict):
    """
    Root LangGraph state for the vQA autonomous agent.

    This TypedDict is the single shared data contract that flows through
    every node in the StateGraph.  Think of it as the agent's "working
    memory": it accumulates observations, decisions, actions, and
    artifacts across the entire run lifecycle.

    Reducer Annotations
    -------------------
    Fields annotated with ``Annotated[list[T], operator.add]`` use an
    *append* reducer — each node's partial return is concatenated onto
    the existing list rather than overwriting it.

    Fields annotated with ``Annotated[dict, _merge_dicts]`` use a
    *shallow-merge* reducer — each node's partial return is merged into
    the existing dict.

    Plain (unannotated) fields are simply overwritten by whichever node
    returns them last.

    Attributes
    ----------
    ── Execution Identity ─────────────────────────────────────────────

    run_id : str
        UUID-based unique identifier for this execution run.
        Used as a path component in S3 keys and as the WebSocket room ID.
        Example: ``"run-a1b2c3d4-e5f6-..."``

    execution_mode : Literal["interactive", "headless"]
        Controls whether Playwright uses a virtual display (Xvfb) or
        runs fully headless.  Set from the ``/execute`` request body.

    ── Jira Context ───────────────────────────────────────────────────

    jira_ticket : JiraTicketContext
        All data fetched and parsed from the Jira ticket.

    ── Role Execution ─────────────────────────────────────────────────

    role_context : RoleContext
        Credentials and permission context for the *currently executing*
        role.  Replaced by setup_role_node on each role iteration.

    role_queue : list[str]
        Ordered list of role keys still to be tested.
        Consumed from the front by setup_role_node.
        Example: ``["account_executive", "producer"]``

    ── Browser State ──────────────────────────────────────────────────

    target_url : str
        The base URL of the application under test.
        Example: ``"https://two-test.vcreative.net"``

    current_page_url : str
        The browser's current URL after the most recent navigation.
        Updated by executor_node after each action.

    navigation_history : list[str]
        Rolling buffer of the last 3 navigation-type actions or URLs.
        Used to prevent redundant re-navigation to the same page.

    current_screenshot_b64 : str
        Base-64 encoded PNG of the current page state.
        Re-captured before every call to the planner LLM.
        NOT stored in state between runs (only used in the live loop).

    current_accessibility_tree : str
        JSON string of the current Playwright accessibility tree snapshot.
        Produced by ``backend/browser/accessibility.py``.
        Provided alongside the screenshot to ground LLM reasoning.

    browser_session_active : bool
        ``True`` while a Playwright BrowserContext is open.
        Set by login_node; cleared by reporter_node after video is saved.

    ── Planning ───────────────────────────────────────────────────────

    planner_iteration : int
        Incremented on every pass through the see-think-act loop.
        Compared against ``max_planner_iterations`` as a safety cap.

    max_planner_iterations : int
        Maximum number of planner→executor→evaluator cycles allowed.
        Initialised from ``settings.max_planner_iterations`` (default 500).

    planned_action : dict
        The JSON action object returned by the LLM on the most recent
        planner pass.  Read by executor_node to dispatch the browser action.
        Example::

            {
                "action": "click",
                "strategy": "get_by_role",
                "role": "button",
                "name": "Submit All",
                "reasoning": "Form is complete; Submit All button is enabled."
            }

    ac_step_index : int
        Zero-based index into ``jira_ticket.acceptance_criteria_steps``
        indicating which AC step the agent is currently working on.

    ac_steps_completed : list[int]
        Indices of AC steps that have been fully validated.
        When ``len(ac_steps_completed) == len(acceptance_criteria_steps)``,
        the run is complete.

    ── Execution Log ──────────────────────────────────────────────────

    detailed_execution_log : Annotated[list[ExecutionStep], operator.add]
        The granular audit trail — one ``ExecutionStep`` per browser action.
        Uses the ``operator.add`` reducer so entries are never overwritten.
        This is the source of truth for the HTML audit report.

    ── Self-Healing / Reflexion ───────────────────────────────────────

    recovery_attempted_types : set[str]
        Set of recovery types (by string value) that have been attempted for the current AC step failure.

    recovery_action_log : list[dict]
        Log of recovery actions taken by the Recovery Router.
        Each entry is a dict with 'type', 'action', and 'success'.

    retry_count : int
        How many times the current AC step has been retried.
        Reset to 0 by evaluator_node when a new AC step begins.
        When it reaches ``max_retries``, the step is marked FAILED.

    max_retries : int
        Per-step retry cap.  Initialised from ``settings.max_retries`` (default 3).

    last_error : str
        The most recent exception message from a failed executor action.
        Fed back to the planner to enable self-healing (the LLM sees the
        error and attempts a different locator or action).

    agent_critique : str
        Free-text critique generated by the evaluator when an action
        fails.  More descriptive than ``last_error``; includes suggestions
        for alternative strategies.

    long_term_memory : Annotated[list[str], operator.add]
        Observations accumulated across the current run that may inform
        later steps (e.g. "The client dropdown requires a 500ms wait after
        typing before options appear").
        Grows across the run; never reset mid-run.

    ── Output Artifacts ───────────────────────────────────────────────

    screenshots : Annotated[list[str], operator.add]
        S3 URLs of every post-action screenshot taken during the run.
        Accumulated using the append reducer.

    s3_video_url : str
        S3 URL of the full-session ``.webm`` recording.
        Set by reporter_node after upload; empty string until then.

    s3_report_url : str
        S3 URL of the final HTML audit report.
        Set by reporter_node after upload; empty string until then.

    ── Legacy Compatibility ────────────────────────────────────────────
    (Retained for parity with vProMediaRegressionAgent reporter format)

    bug_log : Annotated[list[dict], operator.add]
        Structured bug entries: each dict has ``type`` (UI/LOGIC/API/QA/MEM),
        ``description``, ``severity``, and ``screenshot_url``.

    ux_friction_log : Annotated[list[dict], operator.add]
        Non-blocking UX observations noted by the evaluator.
        Rendered as a separate section in the HTML report.

    report_sections : Annotated[dict, _merge_dicts]
        Keyed HTML fragments contributed by different nodes.
        reporter_node assembles these into the final HTML document.

    final_html_report : str
        The complete rendered HTML audit report string.
        Uploaded to S3 by reporter_node; also returned via /status.
    """

    # ── Execution Identity ────────────────────────────────────────────
    run_id: str
    execution_mode: Literal["interactive", "headless"]
    active_profile: str  # AppProfile name (e.g. "vsuite") for runtime resolution
    active_product: str  # Product slug (e.g. "vpromedia", "vtrade") from product registry
    execution_engine: Literal["ai", "static"]
    playwright_test_id: str | None
    static_execution_pid: int | None

    # DR-008: Wall-clock circuit breaker — set to time.time() at run initialization.
    # The evaluator checks elapsed = time.time() - run_started_at on every tick.
    run_started_at: float

    # ── Jira Context ─────────────────────────────────────────────────
    jira_ticket: JiraTicketContext

    # ── Role Execution ───────────────────────────────────────────────
    role_context: RoleContext
    role_queue: list[str]

    # ── Browser State ────────────────────────────────────────────────
    target_url: str
    current_page_url: str
    navigation_history: list[str]
    current_screenshot_b64: str
    current_accessibility_tree: str
    browser_session_active: bool

    # ── Deterministic Page State (from PageStateTracker) ─────────────
    # XML-formatted snapshot of the page's view, overlays, sort state,
    # and spinner visibility.  Produced by the executor's post-action
    # tracker refresh (~10-15ms overhead).  Injected into the planner
    # prompt at the highest priority position so the LLM trusts it over
    # its visual interpretation of the screenshot.
    # See backend/engine/state_tracker.py for the PageStateTracker class.
    page_state_snapshot: str

    # ── Planning ─────────────────────────────────────────────────────
    planner_iteration: int
    max_planner_iterations: int
    planned_action: dict
    ac_step_index: int
    # ReAct fields — populated by planner, persisted in ExecutionStep for audit
    llm_observation: str  # What the agent saw before deciding (ReAct: Observe)
    llm_thought: str  # Why the agent chose the action (ReAct: Think)
    # operator.add so completed step indices accumulate across evaluator calls
    ac_steps_completed: Annotated[list[int], _deduplicated_add]

    # ── Global Run Context (pre-loaded by preflight scanner) ────────────
    # Populated by ac_parser_node after steps are finalised. Contains
    # pre-loaded KB articles for every theme detected across ALL AC steps,
    # plus PrimeNG component gotchas (forbidden patterns + Angular quirks)
    # for every component the run will interact with.
    #
    # Injected at the top of every planner prompt — gives the agent domain
    # context from Iteration 1 without waiting for a failure to occur.
    # Built by backend/kb/preflight.py::build_global_context().
    global_run_context: str

    # ── Structured Test Plan (populated by two-stage AC parser) ───────
    # The compiled TestPlan from the structured AC parser, stored as a
    # dict (via .model_dump()) for JSON serialization.  Contains typed
    # steps with preconditions, target components, and programmatic
    # verification assertions.  None until ac_parser runs.
    # See backend/engine/schemas.py for the TestPlan Pydantic model.
    test_plan: dict | None

    # ── Pinned TestPlan (Lock B — deterministic replay) ───────────────
    # When non-None, ac_parser_node short-circuits at its very top and
    # injects this plan verbatim — no LLM call, no cache lookup.
    # Populated by execute_single() in routes.py when the caller supplies
    # plan_id (Phase 4 wiring).  None for all runs that do not opt in.
    # The load-bearing invariant: _stage_1_normalize.call_count == 0
    # and _stage_2_compile.call_count == 0 whenever this field is set.
    pinned_plan: dict | None

    # Opaque id of the persisted pinned plan (mirrors plan_id from
    # ExecuteRequest), used for structured logging (SET / HIT / MISS).
    # None when pinned_plan is None.
    pinned_plan_id: str | None

    # ── Multi-Actor Test Plan (FEAT-068 / TASK-089) ──────────────────
    # Holistic plan for scenarios involving multiple actors.
    # Produced by the Pre-Flight BDD Compiler.
    multi_actor_test_plan: dict | None

    # Current position in the structured test plan's steps list.
    # Independent of ac_step_index (which tracks the legacy string steps).
    # Both advance together via dual-write in the parser.
    structured_step_index: int

    # FEAT-057: Current sub-step index for compound steps.
    # Reset to 0 when ac_step_index advances.
    current_sub_step_index: int

    # ── Per-Step Budgeting (FEAT-021) ─────────────────────────────────
    # Note: These fields are required from state initialization to ensure
    # the evaluator's budget logic operates correctly on the first step.
    ac_step_iteration_budget: int  # max iterations allowed for current AC step
    ac_step_iterations_used: int  # iterations consumed on current AC step
    ac_steps_skipped: Annotated[list[int], _deduplicated_add]  # steps that timed out

    # ── ARIA Tree Pruning (FEAT-025) ──────────────────────────────────
    # List of ARIA roles relevant to the current step (e.g. ['button']).
    # Mirrored from test_plan.steps[structured_step_index] for easy access.
    target_element_types: list[str]

    # Set to "degraded" if structured AC parsing failed and the system fell back
    # to the legacy flat-list parser. parse_quality_reason contains the exception.
    # Planner injects a warning when this is "degraded" so the LLM reasons more carefully.
    parse_quality: str
    parse_quality_reason: str

    # ── AC Quality Gate (FEAT-001) ────────────────────────────────────
    # Structured quality assessment from the pre-parse quality scorer.
    # Contains overall_score (0-10), dimension_scores, quality_grade
    # ("good"/"fair"/"poor"), warnings, and per-step breakdowns.
    # None until ac_parser_node runs. Consumed by reporter_node to
    # render the quality banner and per-step badges in the HTML report.
    ac_quality_result: dict | None
    # Visual context from Jira attachments (added in TASK-047)
    visual_context: str
    # ── AC Enrichment (FEAT-002) ──────────────────────────────────────
    # Structured enrichment result from the domain-aware AC enricher.
    # Contains detected_domains, kb_articles_used, enrichment_applied,
    # and enrichment_char_count.
    # None until ac_parser_node runs. Consumed by reporter_node to
    # show which domain context was injected into the AC before parsing.
    ac_enrichment_result: dict | None

    # ── Graph routing (evaluator / verifier → conditional edge) ──────
    # MUST be declared here or LangGraph silently discards it.
    # route_after_evaluator() reads this to decide planner/setup_role/reporter.
    _next_node: str

    # Verdict from the step_verifier_node: "satisfied", "not_yet", "failed", or ""
    _verifier_verdict: str

    # Normalized confidence score (0–100) returned by the verifier alongside the verdict.
    # 0–39 = low confidence (HITL candidate if retries are exhausted)
    # 40–69 = mid-range confidence (lightweight retry with alternate strategy)
    # 70–100 = high confidence (treat as VERIFIED even on ambiguous AC steps)
    # Reset to 0.0 when ac_step_index advances.
    # Read by evaluator_node confidence-gated HITL logic (FEAT-060 Phase 4B).
    _verifier_confidence: float

    # Counts consecutive NOT_YET verdicts from the step_verifier_node on the
    # CURRENT ac_step_index. Reset to 0 when the step is satisfied or ac_step_index
    # advances. When this reaches 3, the verifier escalates to the evaluator
    # instead of looping back to the planner indefinitely.
    verifier_not_yet_count: int

    # Total NOT_YET verdicts across ALL evaluator↔verifier cycles for the
    # current AC step. Unlike verifier_not_yet_count (reset per cycle),
    # this tracks the LIFETIME count. Hard-capped at 9 to prevent infinite
    # NOT_YET loops regardless of resets.
    verifier_total_not_yet_count: int

    # ── Execution Log (append-only via operator.add) ─────────────────
    detailed_execution_log: Annotated[list[ExecutionStep], operator.add]

    # ── Self-Healing ─────────────────────────────────────────────────
    recovery_attempted_types: set[str]
    recovery_action_log: list[dict]
    retry_count: int
    max_retries: int
    last_error: str
    agent_critique: str
    long_term_memory: Annotated[list[str], operator.add]

    # ── Debugger (Phase 3C) ──────────────────────────────────────────
    # When retry_count crosses human_takeover_threshold, the evaluator
    # routes to the debugger node ONCE before falling back to human_takeover.
    debugger_attempted: bool
    debug_fix_recommendation: str

    # ── Observability (Phase 3D) ─────────────────────────────────────
    # Per-run LLM usage metrics (populated by RunMetrics.to_dict()).
    run_metrics: dict

    # ── Cross-Run Learning (Phase 4E) ────────────────────────────────
    # Auto-generated KB update proposals from proven patterns.
    kb_update_proposals: list[dict]

    # Tracks how many times each specific locator has failed on the
    # CURRENT ac_step_index. Keyed by "strategy:role:name".
    # Unlike retry_count this does NOT reset when a wait/scroll succeeds —
    # it only resets when ac_step_index advances.
    # Used by the evaluator to inject hard-block critiques and escalate.
    ac_step_fail_counts: dict

    # ── Playwright-only action failure counter (Fix 1 — granularity split) ────
    # Incremented ONLY when the Playwright executor returns success=False.
    # Deliberately separate from ac_step_fail_counts which tracks per-locator
    # key failures and is also written by the verifier path.
    # Budget: >= 5 Playwright failures on the same AC step → human_takeover.
    # Reset to 0 when ac_step_index advances OR when the verifier verdict
    # is "satisfied" (i.e. a previous action succeeded completely).
    ac_step_action_fail_count: int

    # Tracks consecutive vision-mode failures (FEAT-049 / TASK-054)
    vision_mode_fail_count: int

    # Hardware-level wait flags for problematic components (FEAT-049 / TASK-054)
    _force_wait_before_next_action: bool
    _force_wait_ms: int

    # Indices that were never executed (COVERAGE_GAP).
    # Populated by evaluator_node if a step was skipped/never executed.
    # reporter_node uses this to render the step as FAILED in the summary.
    # (TASK-054: TD-002)
    ac_steps_coverage_gap: list[int]

    # Total actions dispatched on the CURRENT AC step — incremented on EVERY action
    # (success=True or success=False).  Unlike ac_step_action_fail_count which only
    # counts Playwright failures, this catches the case where the agent intersperses
    # "successful" wrong actions (clicking Settings, scrolling) between failures,
    # resetting the consecutive failure counter and evading escalation.
    # Budget: >= 15 total actions on the same step → human_takeover.
    # Reset to 0 when ac_step_index advances (evaluator clears on "done" or "satisfied").
    current_ac_step_action_count: int

    # ── Hard Circuit Breaker (identical-action deduplication) ─────────────
    # Tracks the number of times each unique (action, selector_key) pair has
    # been dispatched on the current AC step WITHOUT a Verifier SUCCESS.
    # Keyed by: "{ac_step_index}::{action}|{strategy}|{role}|{name}|..."
    # Reset to {} when ac_step_index advances (evaluator clears on "done").
    # When a key reaches _CIRCUIT_BREAKER_MAX (3) the executor raises a
    # fatal failure, routing to human_takeover immediately.
    action_repeat_counts: dict

    failure_type: str
    """
    Terminal failure classification set by the evaluator when routing to
    human_takeover or reporter.

    One of:
      "APP_DEFECT"   — Agent executed the action; app response was wrong.
      "AGENT_STUCK"  — Agent could not find/interact with the target element.
      "ENV_BLOCKER"  — Network failure, navigation error, wrong environment.
      ""             — Not yet classified (run is in progress).

    Surfaced in the reporter for at-a-glance triage without reading the full log.
    """

    # ── Structured Failure Diary (per AC step) ────────────────────────
    # Populated by evaluator_node on every failed action. Cleared when
    # ac_step_index advances. Injected into the planner system prompt
    # so the LLM sees the COMPLETE history of what was tried and why
    # each attempt failed — preventing it from repeating the same
    # failing locator on every retry.
    #
    # Each entry is a dict with these keys:
    #   attempt   : int   — 1-based failure count on this AC step
    #   action    : str   — the action type that failed (e.g. "click")
    #   locator   : str   — "strategy:role:name" composite key
    #   error     : str   — classified error (e.g. "STRICT_MODE (8 matches)")
    #   suggestion: str   — targeted recovery hint for the LLM
    #
    # NOTE: This is NOT annotated with operator.add — it is a plain list
    # that evaluator_node overwrites with the full updated diary on each
    # failure so entries are never duplicated across retry cycles.
    ac_step_failure_diary: list[dict]

    # ── Action History Buffer (FEAT-020) ──────────────────────────────
    # Rolling window of the last 5 failed actions, maintained by the
    # evaluator for injection into the planner's system prompt as a
    # <past_actions> XML block.  Prevents the planner from repeating
    # ineffective strategies ("amnesic retry loops").
    #
    # Each entry is a dict with these keys:
    #   action    : str — action type that failed (e.g. "click")
    #   strategy  : str — locator strategy used (e.g. "get_by_role")
    #   target    : str — element name/text targeted
    #   error_type: str — classified error from _classify_error()
    #   iteration : int — planner_iteration at time of failure
    #
    # NOTE: Plain list (NOT annotated with operator.add) — evaluator
    # overwrites the full buffer on each failure (append-then-slice).
    # Cleared to [] when ac_step_index advances.
    action_history_buffer: list[dict]

    # ── Deferred Verification Queue (FEAT-023 / TASK-005) ─────────────
    # Queued "soft assertions" created by the verifier when it auto-satisfies
    # a transient selector or sparse dataset bypass.  Instead of blindly
    # trusting the bypass, the assertion is re-checked N steps later.
    #
    # Each entry is a dict with these keys:
    #   ac_step_index    : int  — the AC step that was auto-satisfied
    #   verification     : dict — the original verification assertion dict
    #   bypass_type      : str  — 'transient_selector' | 'sparse_dataset'
    #   bypass_pattern   : str  — the matched transient pattern or 'sparse_dataset'
    #   enqueued_at_step : int  — ac_step_index when the entry was created
    #   check_after_step : int  — ac_step_index at which re-check fires
    #
    # NOTE: Plain list (NOT annotated with operator.add) — evaluator
    # overwrites the full queue on each update.
    deferred_verification_queue: list[dict]

    # ── Deferred Verification Failures (FEAT-023 / TASK-005) ──────────
    # Records of deferred re-checks that FAILED.  Consumed by the reporter
    # to render amber DVF badges in the audit report.
    #
    # Each entry is a dict with these keys:
    #   ac_step_index : int  — the AC step that was originally auto-satisfied
    #   bypass_type   : str  — 'transient_selector' | 'sparse_dataset'
    #   reason        : str  — why the re-check failed
    #   backtracked   : bool — whether the evaluator attempted a backtrack
    #
    # NOTE: Plain list (NOT annotated with operator.add) — evaluator
    # overwrites the full list on each update.
    deferred_verification_failures: list[dict]

    # ── Deferred Verification Successes (TASK-101) ────────────────────
    # Records of deferred re-checks that PASSED. Consumed by the reporter
    # to render green 'Re-verified' badges in the audit report.
    #
    # Each entry is a dict with these keys:
    #   ac_step_index : int  — the AC step that was originally auto-satisfied
    #   bypass_type   : str  — 'transient_selector' | 'sparse_dataset'
    #   reason        : str  — why the re-check passed / satisfied
    #
    # NOTE: Plain list (NOT annotated with operator.add) — evaluator
    # overwrites the full list on each update.
    deferred_verification_successes: list[dict]

    # Pre-confirmed AC steps provided by the user after reviewing the
    # parsed plan. When non-empty, ac_parser_node uses these verbatim
    # instead of calling the LLM.
    override_ac_steps: list[str]

    # Set by the executor when a fallback strategy (force click or get_by_text)
    # was used instead of the primary locator. The evaluator reads this to
    # record a long_term_memory observation. Cleared after each planner call.
    last_executor_fallback: str

    # Set to True when the evaluator routes to human_takeover_node.
    # The human_takeover_node resets it to False after the user completes
    # or skips the stuck step.
    awaiting_human_takeover: bool

    # ── Transient Observation Cache ────────────────────────────────
    # Text scraped from the page immediately after click/press_key actions,
    # before the LLM call. Injected into the planner prompt so the agent can
    # verify ephemeral UI (toasters, alerts, banners) that may disappear
    # within seconds — faster than the LLM round-trip.
    transient_page_text: str

    # ── Persona Tracking (run-scoped dynamic memory) ─────────────────
    # Generic actor-tracking dictionary for multi-role integration tests.
    # Sub-keys:
    #   "initial_actor": {"email": "...", "role_key": "...", "role_name": "..."}
    #   "dynamic_actors": {"voicer": "Demo Voice Talent", "editor": "Demo Editor", ...}
    # Uses _merge_dicts reducer so nodes can update individual sub-keys
    # without overwriting the entire dict.
    run_memory: Annotated[dict, _merge_dicts]

    # ── Persona Switch State (FEAT-054 / TASK-063) ────────────────────
    # Tracks the active persona role_key across mid-test auth context switches.
    # Set by login_node (initial value = role_context.role_key) and
    # updated by persona_switch_node on every PERSONA_SWITCH step.
    # Empty string until login_node runs.
    current_persona: str

    # Audit log of all persona switches in this run.
    # Append-only via operator.add — entries are NEVER overwritten.
    # Each entry schema:
    #   {
    #     "from":         str  — role_key before the switch
    #     "to":           str  — role_key after the switch
    #     "persona_name": str  — raw name from Jira AC (e.g. "Demo Prod dir")
    #     "timestamp":    str  — ISO-8601 UTC
    #     "method":       str  — "stored" | "initial_actor" | "hitl"
    #     "duration_ms":  int  — wall-clock ms for the full switch
    #   }
    persona_switch_history: Annotated[list[dict], operator.add]

    # In-memory-only ephemeral credentials for unknown personas supplied via HITL.
    # Keyed by persona_name (the raw string from the Jira AC).
    # SECURITY: This field is NEVER serialized to disk, NEVER passed to AuthManager,
    # and is discarded when the run completes (cleared by reporter teardown).
    # NOT annotated with operator.add — plain dict, last write wins.
    ephemeral_persona_creds: dict

    # Set to True by ghost_login_node once the admin browser session is
    # established and the browser is on the target product URL. The graph's
    # GHOST_LOGIN router uses this to send the step to the planner instead of
    # re-running the node once admin auth is done — the planner handles the
    # ghost-panel DOM interaction as a normal step.
    ghost_admin_authenticated: bool

    # ── State Snapshot Verification ───────────────────────────────
    dom_snapshot_before: str
    pre_action_state: dict  # TASK-054: URL, ARIA snapshot, and element count before action

    # ── Structural DOM Failure Diagnosis ──────────────────────────────
    # Written by executor_node on action failure, read by evaluator_node.
    # Contains a structured prefix like:
    #   DOM_ABSENT: 'Submit All' not found anywhere in DOM
    #   DOM_HIDDEN: 'Submit All' in DOM (×1) but not visible
    #   DOM_PRESENT_VISIBLE: 'Submit All' visible (×3) — likely strict mode
    # The evaluator prepends this to agent_critique so the LLM gets a
    # principled reason for the failure, not just "Timeout 15000ms exceeded".
    # Cleared by evaluator_node after use (set to "").
    dom_failure_diagnosis: str

    # ── Output Artifacts ─────────────────────────────────────────────
    screenshots: Annotated[list[str], operator.add]
    s3_video_url: str
    s3_report_url: str

    # ── Runtime Credential Injection ─────────────────────────────────
    # Credentials supplied by the user at execute-time (e.g. to fill a
    # partial credential found in the Jira ticket).
    # These take highest priority over ticket + KB credentials.
    injected_login_email: str
    injected_login_password: str

    # ── User Guidance ─────────────────────────────────────────────────
    # User-provided guidance text from the triage panel after a failed run.
    # Injected into the planner system prompt to steer re-runs.
    user_guidance: str
    # Pre-parse guidance the user provides BEFORE the AC parser runs.
    # Injected into the Stage 1 BDD Normalizer prompt so the LLM generates
    # more accurate steps given extra context (e.g. known UI quirks).
    pre_parse_guidance: str

    # ── FAIR Guardrail (TASK-096 / FEAT-077) ─────────────────────────
    # Set to True by ac_parser_node when quality_grade == "fair" AND the
    # operator has not yet supplied guidance or approved the bypass.
    # Cleared to False once the operator acts (provides guidance or clicks
    # "Proceed Anyway").  The graph loop blocks on an asyncio.Event while
    # this is True — preserving run state without a full LangGraph checkpoint.
    awaiting_pre_parse_guidance: bool

    # Set to True by the operator clicking "Proceed Anyway" in the UI.
    # When True, ac_parser_node logs the bypass at INFO level and skips
    # the guardrail pause — allowing FAIR-grade tickets to proceed without
    # additional context.  Does NOT affect the quality_grade in the report.
    pre_parse_guidance_approved: bool

    # When True, ac_parser_node is being invoked from the /preview-steps
    # route (no browser, no WebSocket). Execution-time HITL gates (e.g.
    # GHOST_LOGIN credential wait) are skipped — they are an execution
    # concern, not a parsing concern.  The preview returns the full
    # structured plan so the UI can prompt for credentials before /execute.
    is_preview: bool

    # ── Request Metadata (for dynamic URL building) ───────────────────
    # Stored from the /execute request headers (Host, X-Forwarded-Proto)
    # so we can rebuild the noVNC URL during human takeover broadcast.
    # Essential for Phase 1 VNC Stream integration to support remote hosts.
    request_host: str
    request_protocol: str

    # ── Failed Login Testing ─────────────────────────────────────────
    # When True, login_node skips authentication and leaves the browser
    # on the login page. AC steps drive the login attempt and verify failure.
    expect_login_failure: bool

    # ── Auth Gate Retry Cap ───────────────────────────────────────────
    # Counts how many times AUTH_GATE_BLOCKED has re-routed to login_node.
    # When this reaches 2, the evaluator routes to reporter (FAIL) instead
    # of retrying — preventing an infinite re-auth loop when credentials
    # are wrong or the account doesn't exist on the target environment.
    auth_gate_retry_count: int

    # ── Legacy Compatibility ──────────────────────────────────────────
    bug_log: Annotated[list[dict], operator.add]
    ux_friction_log: Annotated[list[dict], operator.add]
    report_sections: Annotated[dict, _merge_dicts]
    final_html_report: str
    #: Failure triage from the LLM analyzer (None if run passed)
    failure_analysis: dict | None

    # ── HITL Override (Fix 2 — structured HITL payload) ──────────────────
    # Written by human_takeover_node after the human completes a takeover.
    # The planner reads this at the TOP of its prompt assembly (before any
    # other context) and injects a MANDATORY OVERRIDE block when present.
    # Cleared (set to None) by planner_node after injecting into the prompt.
    #
    # Structure:
    #   ac_step          : str          — the AC step the human completed
    #   completed_index  : int          — ac_step_index of the completed step
    #   next_step_index  : int          — ac_step_index the planner should start
    #   action_sequence  : list[dict]   — captured Playwright actions (may be [])
    #   explanation      : str          — human-typed explanation (may be "")
    #   is_hard_override : bool         — True = actions captured, execute verbatim
    hitl_override: dict | None

    # ── Verifier Correction (TASK-083) ──────────────────────────────────
    # Written via WebSocket when a user manually overrides a verifier verdict
    # (e.g. clicking "False Positive" in the UI).
    # If this matches the current ac_step_index, the verifier will return
    # SATISFIED immediately with the user's provided reasoning.
    # Cleared by verifier_node after use.
    verifier_correction: dict | None

    # ── Set-of-Marks Visual DOM Mapping ──────────────────────────────────
    # Populated by capture_set_of_marks() when the planner activates SoM mode.
    # Maps str(box_id) → css_selector for all visible interactive elements
    # in the annotated screenshot. The executor reads this to resolve
    # {"action": "click", "box_id": N} actions to concrete CSS selectors.
    # Reset to {} whenever the planner advances to a new AC step or refreshes.
    #
    # Example: {"1": "button#submit-order", "12": "p-select.po-col-duedaysCol"}
    som_element_map: dict

    # Force SoM mode on every planner iteration for this run.
    # Can be set via the /execute request body or escalated internally
    # by the planner loop detector.
    use_som: bool

    # ── Vision-Language Model (VLM) Navigation ────────────────────────────
    # Controls the planner's observation strategy:
    #   "dom"             — Default: screenshot + accessibility tree + DOM text
    #   "som_css"         — Current SoM: annotated screenshot → box_id → CSS selector
    #   "som_coordinates" — New: annotated screenshot → mark_id → (x,y) coordinate click
    # Configurable per-run via the /execute request body.  Auto-escalated to
    # "som_coordinates" when the agent is stuck in deep loops.
    vision_mode: str

    # Maps str(mark_id) → {"x": float, "y": float, "selector": str, "tag": str, "text": str}
    # Populated by draw_marks_and_snapshot() in vision_utils.py when
    # vision_mode == "som_coordinates".  The executor reads this to resolve
    # coordinate_action and vision-mode primeng_dropdown actions.
    # Reset to {} whenever the planner captures a new annotated screenshot.
    mark_coordinate_map: dict

    # ── Recipe Idempotent-Skip Signal ─────────────────────────────────
    # Set to True by executor_node when a recipe's idempotency pre-check
    # determined the target state was already correct (e.g.
    # compact_view_navigate found div.po-table-wrapper.compact already visible).
    # The evaluator detects this flag to advance the AC step directly,
    # bypassing the verifier entirely.
    # Always reset to False after use.
    _recipe_already_satisfied: bool

    # ── Supervisor-Worker Architecture (Phase 1) ─────────────────────
    # These fields support the hierarchical multi-agent platform.
    # They are additive — the existing planner→executor→evaluator loop
    # continues to work unchanged when these fields are empty/default.

    # Global Variable Memory — cross-step data sharing for multi-part
    # and cross-role workflows.  Populated by Workers via the
    # Extract_And_Store_Variable tool.  Read by the Supervisor for
    # token interpolation (e.g. replacing <ORDER_ID> with "VC-12345"
    # in subsequent AC steps).
    # Keys: uppercase snake_case tokens (e.g. "ORDER_ID", "SPOT_NAME").
    # Values: runtime strings scraped from the live UI.
    # Uses _merge_dicts reducer so Workers can add keys independently
    # without overwriting each other's entries.
    global_variables: Annotated[dict, _merge_dicts]

    # Supervisor Intent Queue — structured Intent objects emitted by
    # supervisor_node.  Each dict follows the SupervisorIntent schema:
    #   {
    #     "intent_id": "intent-001",
    #     "worker_type": "form",           # form | table | verify | navigate | auth
    #     "target": "Quick Order Form",    # UI surface / component name
    #     "action": "fill",                # abstract verb (fill, click_row, verify, navigate)
    #     "data": {"field": "value", ...}, # worker-specific payload
    #     "preconditions": ["ORDER_ID"],   # global_variables keys required before dispatch
    #   }
    # Append-only via operator.add so intents accumulate across the run.
    supervisor_intents: Annotated[list[dict], operator.add]

    # Active Actor — the role_key of the currently active browser actor.
    # Set by switch_actor() on BrowserManager and read by executor_node
    # to resolve which BrowserContext/Page to use for Playwright calls.
    # Empty string = use the default (primary) context created by login_node.
    active_actor: str

    # ── CV Fallback Tracking (FEAT-037 / TASK-028) ────────────────────
    # Rolling count of CV fallback invocations in this run.
    # Incremented by executor when CvFallbackResolver.resolve() is called.
    # Used for cost reporting (estimate: $0.003/invocation) and the ≤5%
    # rate gate in future phases.  Plain int — last write wins (executor
    # is the sole writer; overwriting is safe).
    cv_fallback_invocations: int

    # Per-invocation result records for the audit report and per-step guard.
    # Each entry: {step_idx: int, mark_id: int|None, x: float, y: float,
    #              success: bool, cost_estimate: float}
    # Uses Annotated[list, operator.add] so records accumulate across
    # evaluator↔executor cycles without overwriting (same pattern as
    # detailed_execution_log and bug_log).
    cv_fallback_results: Annotated[list, operator.add]

    # ── T3-d Determinism Budget Assertion (FEAT-118) ─────────────────────
    # Set by ac_parser_node when ACParseDriftError is raised.
    # Shape: {baseline_step_count: int, current_step_count: int, delta: int} | None
    # Surfaced in GET /status/{run_id} and the WebSocket state stream.
    ac_parse_drift: dict | None

    # ── T3-c Reflex Layer (FEAT-118) ──────────────────────────────────────
    # Number of times reflex.attempt_short_circuit() was invoked this run.
    # Mirrors cv_fallback_invocations pattern for dashboard observability.
    reflex_invocations: int

    # Per-hit records: [{signature: str, ac_step: int}, ...]
    # Accumulated across evaluator retry cycles (same operator.add pattern
    # as cv_fallback_results and detailed_execution_log).
    reflex_hits: Annotated[list, operator.add]

    # ── CV Vision Diagnostic (FEAT-117 / T2-c) ────────────────────────────
    # Set by executor when CvFallbackResolver.resolve() returns mark_id=None.
    # Contains: {target_text: str, n_marks: int, options: list[str]}
    # Consumed by planner._build_cv_diagnostic_fragment() to inject a recovery
    # prompt fragment on the next planner turn.  Plain field (last write wins)
    # — reset to None by evaluator when the AC step advances.
    cv_vision_diagnostic: dict | None

    # ── Exploration Mode (FEAT-040) ───────────────────────────────────────
    # ExplorationRunner fires inside evaluator_node after debugger intervention
    # and before HITL escalation.  These fields track per-run and per-step
    # exploration state so the runner can guard against re-entry.

    # Flag: set to True by evaluator_node after ExplorationRunner has been
    # invoked for the current AC step (success OR failure).  Reset to False
    # when ac_step_index advances so exploration can fire again on the next
    # stuck element.
    exploration_attempted: bool

    # Accumulated list of ExplorationOutcome dicts — one per episode.
    # Uses operator.add reducer so episodes from multiple AC steps accumulate
    # across the run without overwriting each other.
    # Each dict follows the ExplorationOutcome TypedDict in schemas.py.
    exploration_outcomes: Annotated[list[dict], operator.add]

    # ── Smart Replay (FEAT-043 / TASK-031) ───────────────────────────────
    # Set by replay_check_node after attempting deterministic replay.
    # replay_succeeded=True → replay executed all stored actions → route to reporter
    # replay_failed=True    → replay failed mid-sequence → route to planner (fallback)
    # Both False            → no accepted test found → route to planner (normal AI run)
    replay_succeeded: bool
    replay_failed: bool

    # ── RAG Selector Stats (FEAT-042) ─────────────────────────────────────
    # Per-planner-call retrieval telemetry for the RAG-driven selector injection.
    # Populated by planner_node on each SelectorRAG.query() call.
    # Each dict has: {step_id, entries_retrieved, chars_injected, retrieval_latency_ms}
    # Uses operator.add reducer so stats accumulate across all planner calls.
    # Consumed by reporter_node (Phase 4) to render the RAG Selector Stats footer.
    rag_selector_stats: Annotated[list[dict], operator.add]

    # ── Parallel Execution (FEAT-060 Phase 3) ─────────────────────────────
    # Set by RunOrchestrator when PARALLEL_TICKETS_ENABLED=true.
    # batch_id links this run to the parent BatchRunReport for status polling.
    # None for single-ticket (sequential) runs.
    batch_id: str | None

    # Parallel step groups from DependencyAnalyzer (Phase 3A).
    # Built by ac_parser_node when PARALLEL_STEPS_ENABLED=true.
    # Format: [[0, 2], [1], [3, 4]] = steps 0+2 parallel, then 1, then 3+4.
    # None until ac_parser_node runs. When None, evaluator treats all steps
    # as sequential (fallback to [[i] for i in range(n)]).
    parallel_step_groups: list[list[int]] | None

    # Current index into parallel_step_groups (which group is active).
    # Advanced by evaluator_node when an entire group completes.
    # 0 for sequential (non-parallel) runs.
    parallel_group_index: int

    # Speculative plan cache from SpeculativePlanner (Phase 3C).
    # Populated by planner_node via SpeculativePlanner.start_prefetch().
    # Contains the pre-generated plan for step N+1 while step N executes.
    # Cleared to {} after use or on step failure (poison signal).
    speculative_plan_cache: dict

    # All-pass flag set by evaluator_node when every AC step in
    # ac_steps_completed has been verified. Used by RunOrchestrator
    # to determine RunResult.status.
    all_ac_steps_passed: bool

    # ── Critic Pass LLM Evaluator (critic-pass-llm-evaluator) ─────────────────
    # critic_result: the most recent CriticVerdict dict written by critic_node.
    #   None until the critic fires. Shape: CriticVerdict.model_dump().
    #   Key fields: verdict ("pass"/"mismatch"), reason_codes, feedback_summary,
    #   retry_count (0-2), critic_skipped (True when API error or feature disabled).
    #   Persisted in run_metrics.critic_verdicts list by reporter_node (Phase 3).
    critic_result: dict | None

    # critic_feedback: structured feedback for the ac_parser retry.
    #   None when verdict="pass" or retries exhausted.
    #   Shape: {"reason_codes": [...], "guidance": "<feedback_summary text>"}.
    #   Read by ac_parser_node at the top of _stage_1_normalize (Phase 2).
    #   Cleared to None by route_after_critic when routing to setup_role.
    critic_feedback: dict | None


# ---------------------------------------------------------------------------
# FactStore — persistent run-scoped variables
# ---------------------------------------------------------------------------


class FactStore:
    """
    SQLite-backed key-value store for vQA facts.

    Facts are dynamic variables (e.g. "order_id", "invoice_number") scraped
    from the UI during a run and shared across steps or actors.
    They are scoped by ``run_id`` to ensure isolation between concurrent tests.

    Architecture Context
    --------------------
    This class implements Layer 2 (Omniscient Blackboard) of the vQA Engine.
    It provides a durable alternative to ``global_variables`` in ``VQAState``,
    allowing data to survive browser context crashes or node-level retries.
    """

    def __init__(self, db_path: str = "storage/blackboard.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create the facts table if it doesn't exist."""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    run_id TEXT,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (run_id, key)
                )
                """
            )

    def set(self, run_id: str, key: str, value: Any):
        """Store a fact, overwriting if it already exists for this run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO facts (run_id, key, value) VALUES (?, ?, ?)",
                (run_id, key, str(value)),
            )

    def get(self, run_id: str, key: str) -> str | None:
        """Retrieve a fact by key for a specific run."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM facts WHERE run_id = ? AND key = ?", (run_id, key)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def list(self, run_id: str) -> dict[str, str]:
        """Retrieve all facts for a specific run."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT key, value FROM facts WHERE run_id = ?", (run_id,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


class ActorRegistry:
    """
    SQLite-backed registry for multi-actor credentials and storage states.

    Maintains auth context (cookies, localStorage) and credentials for
    multiple roles within a single run, enabling seamless context switching.
    """

    def __init__(self, db_path: str = "storage/blackboard.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create the actors table if it doesn't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actors (
                    run_id TEXT,
                    role_key TEXT,
                    credentials TEXT,
                    storage_state TEXT,
                    PRIMARY KEY (run_id, role_key)
                )
                """
            )

    def set_credentials(self, run_id: str, role_key: str, credentials: dict):
        """Store credentials for an actor."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO actors (run_id, role_key, credentials)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id, role_key) DO UPDATE SET
                credentials = excluded.credentials
                """,
                (run_id, role_key, json.dumps(credentials)),
            )

    def get_credentials(self, run_id: str, role_key: str) -> dict | None:
        """Retrieve credentials for an actor."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT credentials FROM actors WHERE run_id = ? AND role_key = ?",
                (run_id, role_key),
            )
            row = cursor.fetchone()
            return json.loads(row[0]) if row and row[0] else None

    def set_storage_state(self, run_id: str, role_key: str, storage_state: dict):
        """Store Playwright storage state (cookies/localStorage) for an actor."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO actors (run_id, role_key, storage_state)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id, role_key) DO UPDATE SET
                storage_state = excluded.storage_state
                """,
                (run_id, role_key, json.dumps(storage_state)),
            )

    def get_storage_state(self, run_id: str, role_key: str) -> dict | None:
        """Retrieve Playwright storage state for an actor."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT storage_state FROM actors WHERE run_id = ? AND role_key = ?",
                (run_id, role_key),
            )
            row = cursor.fetchone()
            return json.loads(row[0]) if row and row[0] else None


class VisualSnapshotDiff:
    """
    SQLite-backed engine for capturing and diffing visual snapshots.

    Stores ARIA trees and screenshot references to detect UI mutations
    between execution steps.
    """

    def __init__(self, db_path: str = "storage/blackboard.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create the snapshots table if it doesn't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    run_id TEXT,
                    step_index INTEGER,
                    aria_tree TEXT,
                    screenshot_b64 TEXT,
                    PRIMARY KEY (run_id, step_index)
                )
                """
            )

    def capture(self, run_id: str, step_index: int, aria_tree: str, screenshot_b64: str):
        """Capture a visual snapshot for a specific step."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshots (run_id, step_index, aria_tree, screenshot_b64)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, step_index, aria_tree, screenshot_b64),
            )

    def get_snapshot(self, run_id: str, step_index: int) -> dict | None:
        """Retrieve a snapshot for a specific step."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT aria_tree, screenshot_b64 FROM snapshots WHERE run_id = ? AND step_index = ?",
                (run_id, step_index),
            )
            row = cursor.fetchone()
            if row:
                return {"aria_tree": row[0], "screenshot_b64": row[1]}
            return None

    def diff_aria(self, run_id: str, step_a: int, step_b: int) -> dict:
        """
        Compare ARIA trees between two steps.
        Returns a simple diff (added/removed lines).
        """
        snap_a = self.get_snapshot(run_id, step_a)
        snap_b = self.get_snapshot(run_id, step_b)

        if not snap_a or not snap_b:
            return {"error": "One or both snapshots missing"}

        lines_a = set(snap_a["aria_tree"].splitlines())
        lines_b = set(snap_b["aria_tree"].splitlines())

        return {
            "added": list(lines_b - lines_a),
            "removed": list(lines_a - lines_b),
            "changed": len(lines_a ^ lines_b) > 0,
        }


# Initial state factory
# ---------------------------------------------------------------------------


def make_initial_state(
    run_id: str,
    jira_ticket_id: str,
    role: str,
    target_url: str,
    mode: Literal["interactive", "headless"],
    max_retries: int = 3,
    max_planner_iterations: int = 500,
    vision_mode: str = "dom",
    execution_engine: Literal["ai", "static"] = "ai",
    playwright_test_id: str | None = None,
) -> VQAState:
    """
    Create a fresh ``VQAState`` with sensible default values.

    Called by the FastAPI ``/execute`` route handler before invoking the
    LangGraph graph.  All list fields are initialised to empty lists and
    all string fields to empty strings so nodes can safely append/read
    without checking for ``None``.

    Args
    ----
    run_id : str
        Unique identifier for this execution run (UUID).
    jira_ticket_id : str
        The Jira issue key to fetch (e.g. ``"VC2-8967"``).
    role : str
        Role key to test as (e.g. ``"account_executive"``).
        Must match a key in ``backend/engine/roles.py``.
    target_url : str
        Base URL of the application under test.
    mode : "interactive" | "headless"
        Execution mode.
    max_retries : int
        Per-step self-heal retry cap (default 3).
    max_planner_iterations : int
        See-think-act loop safety cap (default 500).
        Each AC step typically needs 3-10 browser actions, so
        50 steps × 10 actions = 500 is a safe ceiling.

    Returns
    -------
    VQAState
        A fully initialised (but mostly empty) state dict ready to be
        passed to ``graph.invoke()``.

    Example
    -------
    >>> state = make_initial_state(
    ...     run_id="run-abc123",
    ...     jira_ticket_id="VC2-8967",
    ...     role="account_executive",
    ...     target_url="https://two-test.vcreative.net",
    ...     mode="headless",
    ...     vision_mode="som_coordinates",
    ... )
    >>> state["run_id"]
    'run-abc123'
    """
    return VQAState(
        # ── Identity ─────────────────────────────────────────────────
        run_id=run_id,
        execution_mode=mode,
        execution_engine=execution_engine,
        playwright_test_id=playwright_test_id,
        static_execution_pid=None,
        run_started_at=time.time(),  # DR-008: wall-clock circuit breaker
        active_profile="vsuite",  # Default; overridden by routes.py after creation
        active_product="vpromedia",  # Default; overridden by routes.py when product is specified
        # ── Jira (will be populated by jira_fetch_node) ───────────────
        jira_ticket=JiraTicketContext(
            ticket_id=jira_ticket_id,
            summary="",
            description="",
            acceptance_criteria="",
            acceptance_criteria_steps=[],
            attachments=[],
            override_login_email="",
            override_login_password="",
            credential_status="none",
        ),
        # ── Role (role_queue seeds setup_role_node) ───────────────────
        role_context=RoleContext(),
        role_queue=[role],
        # ── Browser ───────────────────────────────────────────────────
        target_url=target_url,
        current_page_url="",
        navigation_history=[],
        current_screenshot_b64="",
        current_accessibility_tree="",
        browser_session_active=False,
        # ── Planning ──────────────────────────────────────────────────
        planner_iteration=0,
        max_planner_iterations=max_planner_iterations,
        planned_action={},
        ac_step_index=0,
        ac_steps_completed=[],
        # ── Structured test plan (populated by ac_parser) ─────────────
        test_plan=None,
        # ── Pinned TestPlan (Lock B — Phase 4 routes wiring injects values)
        pinned_plan=None,
        pinned_plan_id=None,
        multi_actor_test_plan=None,
        structured_step_index=0,
        current_sub_step_index=0,
        # ── Per-Step Budgeting (FEAT-021) ─────────────────────────────────
        ac_step_iteration_budget=0,
        ac_step_iterations_used=0,
        ac_steps_skipped=[],
        target_element_types=[],  # FEAT-025
        parse_quality="ok",
        parse_quality_reason="",
        visual_context="",
        # ── Global run context (pre-loaded by preflight before loop) ─────
        global_run_context="",
        # ── Audit log (starts empty; executor appends to it) ──────────
        detailed_execution_log=[],
        # ── Self-healing ──────────────────────────────────────────────
        recovery_attempted_types=set(),
        recovery_action_log=[],
        retry_count=0,
        max_retries=max_retries,
        last_error="",
        agent_critique="",
        long_term_memory=[],
        # ── Debugger (Phase 3C) ──────────────────────────────────────
        debugger_attempted=False,
        debug_fix_recommendation="",
        # ── Observability (Phase 3D) ─────────────────────────────────
        run_metrics={},
        # ── Cross-Run Learning (Phase 4E) ────────────────────────────
        kb_update_proposals=[],
        ac_step_fail_counts={},
        ac_step_action_fail_count=0,  # Fix 1: Playwright-only failure counter
        ac_steps_coverage_gap=[],  # TD-002
        vision_mode_fail_count=0,
        _force_wait_before_next_action=False,
        _force_wait_ms=0,
        current_ac_step_action_count=0,  # Task 3: Total action budget per AC step
        ac_step_failure_diary=[],
        action_history_buffer=[],  # FEAT-020: rolling failed-action buffer
        deferred_verification_queue=[],  # FEAT-023: queued soft assertions
        deferred_verification_failures=[],  # FEAT-023: failed deferred re-checks
        deferred_verification_successes=[],  # TASK-101: passed deferred re-checks
        action_repeat_counts={},  # Circuit breaker: identical-action deduplication
        failure_type="",  # Set by evaluator on terminal failure (REC 5)
        override_ac_steps=[],
        last_executor_fallback="",
        awaiting_human_takeover=False,
        hitl_override=None,  # Fix 2: structured HITL payload
        # ── Set-of-Marks visual DOM mapping ──────────────────────────────
        som_element_map={},  # {box_id_str: css_selector}
        use_som=False,  # Escalated to True on deep loops
        # ── Vision-Language Model (VLM) Navigation ────────────────────────
        vision_mode=vision_mode,  # Configurable per-run via /execute
        mark_coordinate_map={},  # Populated by draw_marks_and_snapshot()
        # ── Artifacts (filled in by reporter_node) ────────────────────
        screenshots=[],
        s3_video_url="",
        s3_report_url="",
        # ── Legacy ────────────────────────────────────────────────────
        bug_log=[],
        ux_friction_log=[],
        report_sections={},
        final_html_report="",
        failure_analysis=None,
        user_guidance="",
        pre_parse_guidance="",
        # ── FAIR Guardrail (TASK-096 / FEAT-077) ─────────────────────────
        awaiting_pre_parse_guidance=False,
        pre_parse_guidance_approved=False,
        is_preview=False,  # overridden by /preview-steps route
        request_host="",  # Populated by /execute or /execute-batch
        request_protocol="",  # Populated by /execute or /execute-batch
        # ── Runtime credential injection ──────────────────────────────
        injected_login_email="",
        injected_login_password="",
        # ── Failed login testing ───────────────────────────────────────
        expect_login_failure=False,
        # ── Auth gate retry cap ────────────────────────────────────────
        auth_gate_retry_count=0,
        # ── Graph routing ─────────────────────────────────────────────
        _next_node="",
        _verifier_verdict="",
        _verifier_confidence=0.0,  # FEAT-060 Phase 4B: confidence-gated HITL
        verifier_not_yet_count=0,
        verifier_total_not_yet_count=0,
        # ── Recipe idempotent-skip signal ─────────────────────────────
        _recipe_already_satisfied=False,
        # ── Persona tracking ─────────────────────────────────────────────
        run_memory={},
        # ── Persona Switch State (FEAT-054 / TASK-063) ────────────────────
        current_persona="",
        persona_switch_history=[],
        ephemeral_persona_creds={},
        ghost_admin_authenticated=False,
        # ── Transient observation cache ───────────────────────────────
        transient_page_text="",
        # ── State Snapshot Verification ───────────────────────────────
        dom_snapshot_before="",
        pre_action_state={},  # TASK-054
        # ── DOM failure diagnosis (executor → evaluator pipeline) ─────
        dom_failure_diagnosis="",
        # ── Supervisor-Worker Architecture (Phase 1) ─────────────────
        global_variables={},
        supervisor_intents=[],
        active_actor="",
        # ── CV Fallback Tracking (FEAT-037 / TASK-028) ────────────────
        cv_fallback_invocations=0,
        cv_fallback_results=[],
        # ── T3-d Determinism Budget Assertion (FEAT-118) ─────────────
        ac_parse_drift=None,
        # ── T3-c Reflex Layer (FEAT-118) ──────────────────────────────
        reflex_invocations=0,
        reflex_hits=[],
        # ── CV Vision Diagnostic (FEAT-117 / T2-c) ────────────────────────────
        cv_vision_diagnostic=None,
        # ── Exploration Mode (FEAT-040) ───────────────────────────────────────
        exploration_attempted=False,
        exploration_outcomes=[],
        # ── Smart Replay (FEAT-043 / TASK-031) ───────────────────────────────
        replay_succeeded=False,
        replay_failed=False,
        # ── RAG Selector Stats (FEAT-042) ─────────────────────────────────────
        rag_selector_stats=[],
        # ── Parallel Execution (FEAT-060 Phase 3) ─────────────────────────────
        batch_id=None,
        parallel_step_groups=None,
        parallel_group_index=0,
        speculative_plan_cache={},
        all_ac_steps_passed=False,
        # ── Critic Pass LLM Evaluator (critic-pass-llm-evaluator) ─────────────
        critic_result=None,
        critic_feedback=None,
    )

