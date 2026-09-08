"""
vQA — HTML Audit Report Generator
====================================
Module: backend/engine/reporter.py

Generates the final HTML audit report from the ``detailed_execution_log``
and uploads it (along with the session video) to S3.

Report Contents
---------------
The HTML report is a self-contained, single-file document that includes:

  1. **Header** — Jira ticket ID, summary, role tested, timestamp, status
  2. **Session video** — embedded ``.webm`` player (links to S3 URL)
  3. **AC step table** — each AC step with pass/fail/skip status
  4. **Step-by-step gallery** — screenshot + LLM reasoning for every action
  5. **Bug registry** — issues classified as [UI], [LOGIC], [API], [QA], [MEM]
  6. **RBAC violation log** — any detected permission boundary breaches
  7. **UX friction log** — non-blocking observations about the UI
  8. **Run metadata** — total duration, iterations, retries, artifact URLs

Styling
-------
The report uses inline CSS for a dark-themed, premium look that renders
correctly in any browser (including S3 static hosting) without external
stylesheets or JavaScript.

Architecture Context
--------------------
``reporter_node`` is the final node in the LangGraph graph.  It:
  1. Closes the browser context (which finalises the .webm video)
  2. Uploads the video to S3
  3. Renders the HTML report from the execution log
  4. Uploads the report to S3
  5. Returns the S3 URLs in the state

Dependencies
------------
  - ``backend/browser/context.py``  — close browser + retrieve video
  - ``backend/storage/s3.py``       — upload video + report
  - ``backend/engine/state.py``     — VQAState, ExecutionStep
  - ``backend/config.py``           — S3 settings

See Also
--------
  - ``backend/engine/evaluator.py`` — routes to reporter when run is done
  - ``backend/engine/graph.py``     — reporter is the terminal node
"""

import json
import logging
from datetime import datetime, timezone

from backend.browser.context import get_manager, unregister_manager
from backend.engine.failure_analyzer import FailureAnalysis, run_failure_analysis
from backend.engine.state import ExecutionStep, VQAState
from backend.engine.state_tracker import remove_tracker as _remove_state_tracker
from backend.jira.client import post_jira_comment
from backend.memory.persistent import persistent_memory
from backend.storage.s3 import upload_error_context, upload_report, upload_video


def _generate_error_context_md(context: dict) -> str:
    """Generate a human-readable Markdown summary of the failure lessons."""
    lines = [
        f"# vQA Failure Lesson: {context.get('ticket', '?')}",
        f"**Run ID:** {context.get('run_id', '?')}",
        f"**Classification:** {context.get('overall_classification', '?')}",
        "",
        "## Lessons Learned",
    ]
    for step in context.get("failed_steps", []):
        lesson = step.get("lesson")
        if not lesson:
            continue

        lines += [
            f"### Step {step.get('index', 0) + 1}: {step.get('text', '?')}",
            f"**Visual Observation:** {step.get('visual_observation', '?')}",
            f"**Diagnosis:** {lesson.get('diagnosis', '?')}",
            f"**Suggestion:** {lesson.get('suggestion', '?')}",
        ]
        if lesson.get("suggested_selector"):
            lines.append(f"**Suggested Selector:** `{lesson.get('suggested_selector')}`")
        lines.append(f"**Confidence:** {lesson.get('confidence', 0.0) * 100:.0f}%")
        lines.append("")

    lines += ["---", "_This context is machine-readable and used for vQA self-healing._"]
    return "\n".join(lines)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML template components
# ---------------------------------------------------------------------------


def _render_header(state: VQAState, duration_ms: int) -> str:
    """
    Render the report header section with run metadata.

    Args
    ----
    state : VQAState
        Current state.
    duration_ms : int
        Total run duration in milliseconds.

    Returns
    -------
    str
        HTML string for the header section.
    """
    ticket = state.get("jira_ticket", {})
    role = state.get("role_context", {})
    ac_steps = ticket.get("acceptance_criteria_steps", [])
    completed = state.get("ac_steps_completed", [])
    total_steps = len(state.get("detailed_execution_log", []))
    bugs = state.get("bug_log", [])

    # Determine overall status.
    # Use set-based coverage check: every index 0..N-1 must appear in completed.
    # Raw len() is unreliable because operator.add can produce duplicates when the
    # verifier and evaluator both append the same index on the final AC step.
    _completed_set = set(completed)

    # TASK-054: Use the explicit state field (TD-002)
    coverage_gap_indices = set(state.get("ac_steps_coverage_gap", []))
    # TASK-101: Exclude failed deferred verification rechecks
    dvf_indices = {entry["ac_step_index"] for entry in state.get("deferred_verification_failures", [])}
    # Effective completion excludes any step that has a COVERAGE_GAP entry or a failed deferred verification.
    _effective_completed = _completed_set - coverage_gap_indices - dvf_indices
    all_passed = (
        len(ac_steps) > 0
        and len(coverage_gap_indices) == 0
        and len(dvf_indices) == 0
        and all(i in _effective_completed for i in range(len(ac_steps)))
    )
    _unique_completed = sum(1 for i in range(len(ac_steps)) if i in _effective_completed)
    status_text = "PASSED ✓" if all_passed else "FAILED ✗"
    status_color = "#10b981" if all_passed else "#ef4444"

    return f"""
    <div class="header">
        <div class="header-top">
            <h1>🔬 vQA Audit Report</h1>
            <span class="status-badge" style="background: {status_color};">
                {status_text}
            </span>
        </div>
        <div class="meta-grid">
            <div class="meta-item">
                <span class="meta-label">Jira Ticket</span>
                <span class="meta-value">{ticket.get("ticket_id", "N/A")}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Summary</span>
                <span class="meta-value">{ticket.get("summary", "N/A")[:80]}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Role</span>
                <span class="meta-value">{role.get("role_name", "N/A")}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Duration</span>
                <span class="meta-value">{duration_ms / 1000:.1f}s</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">AC Steps</span>
                <span class="meta-value">{_unique_completed}/{len(ac_steps)} passed</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Browser Actions</span>
                <span class="meta-value">{total_steps}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Bugs Found</span>
                <span class="meta-value">{len(bugs)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Run ID</span>
                <span class="meta-value" style="font-size: 0.75rem;">{state.get("run_id", "N/A")}</span>
            </div>
        </div>
    </div>
    """


def _render_video_section(video_url: str) -> str:
    """
    Render the embedded session video player.

    Args
    ----
    video_url : str
        S3 URL of the .webm recording.

    Returns
    -------
    str
        HTML string with a <video> tag.
    """
    if not video_url:
        return (
            '<div class="section"><h2>🎬 Session Recording</h2><p class="muted">No video recording available.</p></div>'
        )

    return f"""
    <div class="section">
        <h2>🎬 Session Recording</h2>
        <video controls width="100%" style="border-radius: 8px; max-height: 600px;">
            <source src="{video_url}" type="video/webm">
            Your browser does not support .webm video.
            <a href="{video_url}">Download recording</a>
        </video>
    </div>
    """


def _render_ac_table(state: VQAState) -> str:
    """
    Render the Acceptance Criteria completion table.

    FEAT-001: Includes per-step quality badges from the AC quality gate
    assessment (green dot = good, amber = fair, red = poor).

    Args
    ----
    state : VQAState
        Current state with AC steps and completion data.

    Returns
    -------
    str
        HTML string for the AC step table.
    """
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    completed = set(state.get("ac_steps_completed", []))

    if not ac_steps:
        return '<div class="section"><h2>📋 Acceptance Criteria</h2><p class="muted">No AC steps parsed.</p></div>'

    # TASK-054: Use the explicit state field (TD-002)
    coverage_gap_indices = set(state.get("ac_steps_coverage_gap", []))
    # TASK-101: Exclude failed deferred verification rechecks and add badge for success rechecks
    dvf_indices = {entry["ac_step_index"] for entry in state.get("deferred_verification_failures", [])}
    dvs_indices = {entry["ac_step_index"] for entry in state.get("deferred_verification_successes", [])}

    # FEAT-001: Build per-step quality badge lookup
    quality_result = state.get("ac_quality_result")
    step_scores = quality_result.get("step_scores", []) if quality_result else []

    rows = []
    skipped = set(state.get("ac_steps_skipped", []))
    for i, step in enumerate(ac_steps):
        # TASK-101: Re-verified badge
        reverified_badge = ""
        if i in dvs_indices:
            reverified_badge = ' <span class="reverified-badge" style="background: #059669; color: #ffffff; padding: 0.125rem 0.4rem; border-radius: 0.25rem; font-size: 0.75rem; margin-left: 0.5rem; display: inline-flex; align-items: center; font-weight: 500;">🔁 Re-verified</span>'

        if reverified_badge:
            step = f"{step}{reverified_badge}"

        if i in coverage_gap_indices:
            # TASK-048: COVERAGE_GAP takes priority — step was never executed.
            icon = "✗"
            status_class = "fail"
        elif i in dvf_indices:
            # TASK-101: Failed deferred verification re-checks override completed status
            icon = "✗"
            status_class = "fail"
        elif i in completed:
            icon = "✓"
            status_class = "pass"
        elif i in skipped:
            icon = "⊘"
            status_class = "skip"
            step = f"{step} <span class='muted'>(budget exceeded)</span>"
        else:
            icon = "✗"
            status_class = "fail"

        # FEAT-001: Per-step quality badge
        quality_badge = ""
        if i < len(step_scores):
            s_score = step_scores[i].get("score", 5)
            if s_score >= 7:
                badge_class = "badge-good"
                badge_title = f"Quality: {s_score}/10 (good)"
            elif s_score >= 4:
                badge_class = "badge-fair"
                badge_title = f"Quality: {s_score}/10 (fair)"
            else:
                badge_class = "badge-poor"
                badge_title = f"Quality: {s_score}/10 (poor)"
            quality_badge = f'<span class="quality-step-badge {badge_class}" title="{badge_title}"></span>'

        rows.append(f"""
            <tr class="{status_class}">
                <td>{i + 1}</td>
                <td>{quality_badge}{step}</td>
                <td class="status-cell">{icon}</td>
            </tr>
        """)

    return f"""
    <div class="section">
        <h2>📋 Acceptance Criteria</h2>
        <table>
            <thead>
                <tr><th>#</th><th>Step</th><th>Status</th></tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_execution_log(steps: list[ExecutionStep]) -> str:
    """
    Render the step-by-step execution gallery with screenshots and LLM reasoning.

    FEAT-037: Steps where ``cv_fallback=True`` receive a ``🎯 CV Fallback`` badge
    in the step header, along with the resolved mark_id and coordinates when
    available.

    Args
    ----
    steps : list[ExecutionStep]
        The detailed execution log.

    Returns
    -------
    str
        HTML string for the execution gallery.
    """
    if not steps:
        return '<div class="section"><h2>🔧 Execution Log</h2><p class="muted">No steps recorded.</p></div>'

    cards = []
    for step in steps:
        success = step.get("success", False)
        status_icon = "✓" if success else "✗"
        status_class = "pass" if success else "fail"
        screenshot = step.get("screenshot_url", "")
        reasoning = step.get("llm_reasoning", "")
        error = step.get("error_message", "")
        retry = step.get("self_heal_attempt", 0)

        screenshot_html = ""
        if screenshot:
            screenshot_html = (
                f'<img src="{screenshot}" alt="Step {step.get("step_index", "?")} screenshot" loading="lazy" />'
            )

        error_html = ""
        if error:
            error_html = f'<div class="error-msg">❌ {error}</div>'

        retry_html = ""
        if retry > 0:
            retry_html = f'<span class="retry-badge">Retry #{retry}</span>'

        # FEAT-037: CV Fallback badge — shown when executor used SoM coordinate click.
        cv_badge_html = ""
        if step.get("cv_fallback"):
            mark_id = step.get("cv_mark_id", "?")
            coords = step.get("cv_coords", {})
            coords_str = ""
            if coords:
                coords_str = f" ({coords.get('x', '?')},{coords.get('y', '?')})"
            cv_badge_html = f'<span class="cv-fallback-badge">🎯 CV Fallback mark:{mark_id}{coords_str}</span>'

        # FEAT-118 Phase 5: Execution Layer Attribution badge.
        # Maps execution_layer value → (label, CSS class) for the step header.
        _LAYER_BADGE: dict[str, tuple[str, str]] = {
            "reflex": ("⚡ Reflex", "execution-layer-badge layer-reflex"),
            "bedrock_planner": ("🤖 Bedrock", "execution-layer-badge layer-bedrock"),
            "cv_fallback": ("🎯 CV", "execution-layer-badge layer-cv"),
            "hitl": ("👤 HITL", "execution-layer-badge layer-hitl"),
        }
        attribution_badge_html = ""
        _layer = step.get("execution_layer")
        if _layer and _layer in _LAYER_BADGE:
            _label, _cls = _LAYER_BADGE[_layer]
            attribution_badge_html = f'<span class="{_cls}">{_label}</span>'

        cards.append(f"""
        <div class="step-card {status_class}">
            <div class="step-header">
                <span class="step-num">Step {step.get("step_index", "?")}</span>
                <span class="step-action">{step.get("action_type", "?")}</span>
                <span class="step-locator">{step.get("locator_value", "")}</span>
                {retry_html}
                {cv_badge_html}
                {attribution_badge_html}
                <span class="step-status">{status_icon}</span>
            </div>
            {screenshot_html}
            <div class="step-reasoning">
                <strong>LLM Reasoning:</strong> {reasoning}
            </div>
            {error_html}
            <div class="step-time">{step.get("timestamp", "")}</div>
        </div>
        """)

    return f"""
    <div class="section">
        <h2>🔧 Execution Log ({len(steps)} steps)</h2>
        <div class="steps-grid">
            {"".join(cards)}
        </div>
    </div>
    """


def _render_bug_log(bugs: list[dict]) -> str:
    """
    Render the bug registry section.

    Args
    ----
    bugs : list[dict]
        Bug entries from ``state.bug_log``.

    Returns
    -------
    str
        HTML string for the bug log section.
    """
    if not bugs:
        return '<div class="section"><h2>🐛 Bug Registry</h2><p class="muted">No bugs detected. ✓</p></div>'

    rows = []
    for i, bug in enumerate(bugs, 1):
        severity_class = bug.get("severity", "LOW").lower()
        rows.append(f"""
            <tr class="{severity_class}">
                <td>{i}</td>
                <td><span class="bug-type">[{bug.get("type", "?")}]</span></td>
                <td>{bug.get("description", "")}</td>
                <td>{bug.get("severity", "LOW")}</td>
            </tr>
        """)

    return f"""
    <div class="section">
        <h2>🐛 Bug Registry ({len(bugs)} issues)</h2>
        <table>
            <thead>
                <tr><th>#</th><th>Type</th><th>Description</th><th>Severity</th></tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_failure_analysis_section(failure_analysis: "FailureAnalysis | None") -> str:
    """
    Render the LLM failure triage section in the HTML report.

    Args
    ----
    failure_analysis : FailureAnalysis | None
        The result from run_failure_analysis, or None if the run passed.

    Returns
    -------
    str
        HTML string for the triage section, or empty string if no analysis.
    """
    if not failure_analysis:
        return ""

    overall = failure_analysis.get("overall", "unknown")
    summary = failure_analysis.get("summary", "")
    steps = failure_analysis.get("steps", [])

    overall_class = f"triage-{overall.replace('_', '-')}"
    overall_label = {
        "product_bug": "🐛 Product Bug",
        "agent_issue": "🤖 Agent Issue",
        "mixed": "⚡ Mixed",
        "unknown": "❓ Unknown",
    }.get(overall, overall)

    step_cards = []
    for step in steps:
        cls = step.get("classification", "unknown").replace("_", "-")
        if cls == "passed":
            continue
        label_text = {"product-bug": "Product Bug", "agent-issue": "Agent Issue"}.get(cls, cls)
        confidence = step.get("confidence", "")
        step_cards.append(f"""
        <div class="triage-step {cls}">
            <div class="triage-step-label {cls}">
                {label_text}
                <span class="triage-badge-confidence">({confidence})</span>
            </div>
            <div class="triage-step-ac">{step.get("ac_step", "")}</div>
            <div class="triage-step-reason">{step.get("reason", "")}</div>
        </div>
        """)

    return f"""
    <div class="triage-section">
        <div class="triage-title">🔍 Failure Analysis</div>
        <span class="triage-overall {overall_class}">{overall_label}</span>
        <p class="triage-summary">{summary}</p>
        {"".join(step_cards) if step_cards else '<p class="muted">No per-step classifications available.</p>'}
    </div>
    """


def _render_metrics_section(run_metrics: dict) -> str:
    """
    Render the LLM usage & cost metrics section.

    Args
    ----
    run_metrics : dict
        Metrics dict from ``RunMetrics.to_dict()``.

    Returns
    -------
    str
        HTML string for the metrics section.
    """
    if not run_metrics:
        return ""

    return f"""
    <div class="section">
        <h2>📊 Cost & Performance</h2>
        <div class="meta-grid">
            <div class="meta-item">
                <span class="meta-label">LLM Calls</span>
                <span class="meta-value">{run_metrics.get("llm_calls", 0)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Heavy Calls (Sonnet)</span>
                <span class="meta-value">{run_metrics.get("llm_calls_heavy", 0)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Escalations</span>
                <span class="meta-value">{run_metrics.get("escalations", 0)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Input Tokens</span>
                <span class="meta-value">{run_metrics.get("total_input_tokens", 0):,}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Output Tokens</span>
                <span class="meta-value">{run_metrics.get("total_output_tokens", 0):,}</span>
            </div>
            {_render_vision_row(run_metrics.get("vision_token_usage", {}))}
            <div class="meta-item">
                <span class="meta-label">Estimated Cost</span>
                <span class="meta-value">${run_metrics.get("estimated_cost_usd", 0):.4f}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Avg Latency</span>
                <span class="meta-value">{run_metrics.get("avg_latency_ms", 0)}ms</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Total LLM Time</span>
                <span class="meta-value">{run_metrics.get("total_llm_time_ms", 0) / 1000:.1f}s</span>
            </div>
        </div>
    </div>
    """


def _render_vision_row(vision: dict | None) -> str:
    """Helper to render vision-specific tokens if present (Phase 5)."""
    if not vision or (vision.get("input", 0) == 0 and vision.get("output", 0) == 0):
        return ""

    return f"""
            <div class="meta-item" style="border-left: 3px solid #7c3aed; padding-left: 0.75rem;">
                <span class="meta-label">Vision Tokens</span>
                <span class="meta-value">{vision.get('input', 0):,} in / {vision.get('output', 0):,} out</span>
            </div>
            <div class="meta-item" style="border-left: 3px solid #7c3aed; padding-left: 0.75rem;">
                <span class="meta-label">Vision Cost</span>
                <span class="meta-value">${vision.get('cost_usd', 0.0):.4f}</span>
            </div>
    """


def _render_recovery_log(recovery_actions: list[dict]) -> str:
    """
    Render the recovery actions log section.

    Args
    ----
    recovery_actions : list[dict]
        Recovery entries from ``state.recovery_action_log``.

    Returns
    -------
    str
        HTML string for the recovery log section.
    """
    valid_actions = [r for r in recovery_actions if r and r.get("recovery_type")]
    if not valid_actions:
        return ""

    rows = []
    for i, recovery in enumerate(valid_actions, 1):
        target = (
            recovery.get("container_injected")
            or recovery.get("parent_target")
            or recovery.get("dismiss_method")
            or "N/A"
        )
        wait = recovery.get("wait_ms", "N/A")
        rows.append(f"""
            <tr>
                <td>{i}</td>
                <td><span class="recovery-type-badge">{recovery.get("recovery_type")}</span></td>
                <td>{target}</td>
                <td>{wait}</td>
            </tr>
        """)

    return f"""
    <div class="section">
        <h2>🛠️ Recovery Actions ({len(rows)})</h2>
        <p class="muted" style="margin-bottom: 1rem;">
            These actions were automatically applied by the Recovery Router to fix common browser errors without burning retry budget.
        </p>
        <table>
            <thead>
                <tr><th>#</th><th>Type</th><th>Target / Method</th><th>Wait (ms)</th></tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_dvf_section(dvf_entries: list[dict]) -> str:
    """
    FEAT-023: Render the Deferred Verification Failures (DVF) section.

    Displays an amber warning table listing all deferred assertions that were
    auto-satisfied by the verifier but never re-checked.  This gives human
    reviewers visibility into which pass/fail verdicts were soft-assertions.

    Args
    ----
    dvf_entries : list[dict]
        Deferred verification failure entries from ``state.deferred_verification_failures``.

    Returns
    -------
    str
        HTML string for the DVF section, or empty string if no entries.
    """
    if not dvf_entries:
        return ""

    rows = []
    for i, entry in enumerate(dvf_entries, 1):
        ac_step = entry.get("ac_step_index", "?")
        bypass_type = entry.get("bypass_type", "?")
        bypass_pattern = entry.get("bypass_pattern", "?")
        consumed_at = entry.get("consumed_at_step", "?")
        backtracked = "✓" if entry.get("backtracked", False) else "✗"
        verification = entry.get("verification", {})
        v_type = verification.get("type", "?")

        rows.append(f"""
            <tr>
                <td>{i}</td>
                <td>AC {ac_step + 1 if isinstance(ac_step, int) else ac_step}</td>
                <td><span class="dvf-type-badge">{bypass_type}</span></td>
                <td class="dvf-pattern">{bypass_pattern}</td>
                <td>{v_type}</td>
                <td>Step {consumed_at + 1 if isinstance(consumed_at, int) else consumed_at}</td>
                <td>{backtracked}</td>
            </tr>
        """)

    return f"""
    <div class="section dvf-section" style="border-color: #f59e0b;">
        <h2>⚠️ Deferred Verification Warnings ({len(dvf_entries)})</h2>
        <p class="muted" style="margin-bottom: 1rem;">
            These assertions were auto-satisfied by the verifier due to transient selectors or sparse datasets.
            They were queued for deferred re-check but could not be re-verified against a live page.
            Review these steps manually for correctness.
        </p>
        <table>
            <thead>
                <tr>
                    <th>#</th><th>AC Step</th><th>Bypass Type</th>
                    <th>Pattern</th><th>Verification</th><th>Consumed At</th><th>Backtracked</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_ac_quality_section(ac_quality_result: dict | None) -> str:
    """
    FEAT-001: Render the AC Quality Gate assessment banner.

    Shown between the video and AC table sections. Displays:
    - Overall grade badge (GOOD/FAIR/POOR)
    - Per-dimension bar chart breakdown
    - Warning list for dimensions that scored 0

    Args
    ----
    ac_quality_result : dict | None
        Serialized ACQualityResult from state, or None if scorer didn't run.

    Returns
    -------
    str
        HTML string for the quality section.
    """
    if not ac_quality_result:
        return ""

    grade = ac_quality_result.get("quality_grade", "unknown")
    score = ac_quality_result.get("overall_score", 0)
    dims = ac_quality_result.get("dimension_scores", {})
    warnings = ac_quality_result.get("warnings", [])

    grade_class = f"quality-{grade}" if grade in ("good", "fair", "poor") else "quality-fair"
    grade_icon = {"good": "✅", "fair": "⚠️", "poor": "❌"}.get(grade, "❓")

    # Dimension display names
    dim_labels = {
        "specificity": "Component Specificity",
        "observable_outcome": "Observable Outcome",
        "actionability": "Actionability",
        "precondition_clarity": "Precondition Clarity",
        "scope_atomicity": "Scope Atomicity",
    }

    dim_html = ""
    for dim_key, label in dim_labels.items():
        dim_score = dims.get(dim_key, 0)
        dim_html += f"""
            <div class="quality-dim">
                <div class="quality-dim-label">{label}
                    <span class="quality-dim-score">{dim_score}/2</span>
                </div>
                <div class="quality-bar">
                    <div class="quality-bar-fill quality-bar-{dim_score}"></div>
                </div>
            </div>
        """

    warning_html = ""
    if warnings:
        warning_items = "".join(
            f'<div class="quality-warning">⚠ {w}</div>'
            for w in warnings[:8]  # cap at 8 to avoid report bloat
        )
        remaining = len(warnings) - 8
        if remaining > 0:
            warning_items += f'<div class="quality-warning muted">...and {remaining} more warnings</div>'
        warning_html = f'<div class="quality-warnings"><strong>Quality Issues:</strong>{warning_items}</div>'

    return f"""
    <div class="quality-section">
        <div class="quality-header">
            <h2>{grade_icon} AC Quality Assessment</h2>
            <span class="quality-grade {grade_class}">{grade.upper()} ({score}/10)</span>
        </div>
        <div class="quality-dims">
            {dim_html}
        </div>
        {warning_html}
    </div>
    """


def _render_ac_enrichment_section(ac_enrichment_result: dict | None) -> str:
    """
    FEAT-002: Render the Domain Enrichment banner.

    Shown after the quality gate section. Displays which domains were
    detected and which KB articles contributed context.

    Args
    ----
    ac_enrichment_result : dict | None
        Serialized EnrichmentResult from state, or None.

    Returns
    -------
    str
        HTML string for the enrichment banner.
    """
    if not ac_enrichment_result:
        return ""

    if not ac_enrichment_result.get("enrichment_applied", False):
        return ""

    domains = ac_enrichment_result.get("detected_domains", [])
    articles = ac_enrichment_result.get("kb_articles_used", [])
    char_count = ac_enrichment_result.get("enrichment_char_count", 0)

    domain_tags = " ".join(f'<span class="enrichment-domain-tag">{d}</span>' for d in domains)
    article_list = ", ".join(articles) if articles else "(none)"

    return f"""
    <div class="enrichment-section">
        <div class="enrichment-header">
            <span class="enrichment-icon">🧠</span>
            <span class="enrichment-title">Domain Enrichment Applied</span>
            <span class="enrichment-chars">+{char_count} chars injected</span>
        </div>
        <div class="enrichment-body">
            <div class="enrichment-domains">{domain_tags}</div>
            <div class="enrichment-articles">KB: {article_list}</div>
        </div>
    </div>
    """


# _FULL_DUMP_BASELINE_CHARS is the estimated char count injected per planner call
# when using the old static full-dump strategy (entire selector_registry.json content).
# Used to calculate chars saved in the RAG stats section (AC-OBSERVABILITY-1).
_FULL_DUMP_BASELINE_CHARS = 51_000  # ~373 selectors × ~137 chars avg per entry


def _render_cv_fallback_section(cv_fallback_results: list[dict] | None) -> str:
    """
    FEAT-037: Render the CV Fallback summary section.

    Shown after the execution log when the CV fallback was invoked at least
    once during the run.  Displays:
    - Total invocation count
    - Success rate (percentage)
    - Estimated total cost (USD)
    - Per-invocation table (step, mark_id, coords, verdict)

    Args
    ----
    cv_fallback_results : list[dict] | None
        Entries from ``VQAState.cv_fallback_results``.  Each entry is a dict
        with keys: step_idx, mark_id, x, y, success, cost_estimate.

    Returns
    -------
    str
        HTML string for the CV fallback section, or empty string if no results.
    """
    if not cv_fallback_results:
        return ""

    total = len(cv_fallback_results)
    successes = sum(1 for r in cv_fallback_results if r.get("success", False))
    success_rate = int(successes / total * 100) if total else 0
    total_cost = sum(r.get("cost_estimate", 0.0) for r in cv_fallback_results)

    rows = []
    for i, entry in enumerate(cv_fallback_results, 1):
        verdict_icon = "✓" if entry.get("success") else "✗"
        verdict_class = "pass" if entry.get("success") else "fail"
        rows.append(f"""
            <tr class="{verdict_class}">
                <td>{i}</td>
                <td>Step {entry.get("step_idx", "?")}</td>
                <td>{entry.get("mark_id", "?")}</td>
                <td>({entry.get("x", "?")}, {entry.get("y", "?")})</td>
                <td>${entry.get("cost_estimate", 0.0):.4f}</td>
                <td class="status-cell">{verdict_icon}</td>
            </tr>
        """)

    return f"""
    <div class="section cv-fallback-section">
        <h2>🎯 CV Fallback Summary ({total} invocations)</h2>
        <div class="meta-grid" style="margin-bottom: 1rem;">
            <div class="meta-item">
                <span class="meta-label">Invocations</span>
                <span class="meta-value">{total}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Success Rate</span>
                <span class="meta-value">{success_rate}%</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Est. Cost (CV Vision)</span>
                <span class="meta-value">${total_cost:.4f}</span>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th><th>Step</th><th>Mark ID</th>
                    <th>Coords (x, y)</th><th>Cost</th><th>Result</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_rag_stats_section(rag_selector_stats: list[dict]) -> str:
    """
    FEAT-042 (Phase 4): Render the "🎯 RAG Selector Stats" footer section.

    Shows per-run retrieval telemetry for the RAG-driven selector injection:
    - Average, min, and max entries retrieved per step
    - Average retrieval latency
    - Total chars saved vs. the static full-dump baseline

    Args
    ----
    rag_selector_stats : list[dict]
        Per-planner-call stats from ``state.rag_selector_stats``.
        Each entry must have: step_id, entries_retrieved, chars_injected,
        retrieval_latency_ms.

    Returns
    -------
    str
        HTML string for the RAG stats section, or empty string if no stats.
    """
    if not rag_selector_stats:
        return ""

    total_steps = len(rag_selector_stats)
    total_entries = sum(s.get("entries_retrieved", 0) for s in rag_selector_stats)
    min_entries = min(s.get("entries_retrieved", 0) for s in rag_selector_stats)
    max_entries = max(s.get("entries_retrieved", 0) for s in rag_selector_stats)
    avg_entries = total_entries / total_steps if total_steps else 0

    total_chars = sum(s.get("chars_injected", 0) for s in rag_selector_stats)
    avg_chars = total_chars / total_steps if total_steps else 0
    avg_latency = sum(s.get("retrieval_latency_ms", 0) for s in rag_selector_stats) / total_steps if total_steps else 0

    # Chars saved vs. full-dump baseline (AC-OBSERVABILITY-1)
    baseline_total = _FULL_DUMP_BASELINE_CHARS * total_steps
    chars_saved = max(0, baseline_total - total_chars)
    pct_saved = (chars_saved / baseline_total * 100) if baseline_total else 0

    return f"""
    <div class="section rag-stats-section" style="border-color: #0ea5e9;">
        <h2>🎯 RAG Selector Stats</h2>
        <p class="muted" style="margin-bottom: 1rem;">
            Per-run retrieval telemetry for the RAG-driven selector injection (FEAT-042).
            Replaces static full-dump injection (~{_FULL_DUMP_BASELINE_CHARS:,} chars/call) with
            dynamic budget-capped retrieval.
        </p>
        <div class="meta-grid">
            <div class="meta-item">
                <span class="meta-label">Steps with RAG</span>
                <span class="meta-value">{total_steps}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Avg Selectors/Step</span>
                <span class="meta-value">{avg_entries:.1f} (min {min_entries}, max {max_entries})</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Avg Chars Injected</span>
                <span class="meta-value">{avg_chars:.0f} chars</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Avg Retrieval Latency</span>
                <span class="meta-value">{avg_latency:.1f}ms</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Total Chars Saved</span>
                <span class="meta-value" style="color: #86efac;">
                    {chars_saved:,} chars ({pct_saved:.1f}% reduction vs. baseline)
                </span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Total Chars Injected</span>
                <span class="meta-value">{total_chars:,} chars</span>
            </div>
        </div>
    </div>
    """


def _render_persona_switch_section(persona_switch_history: list[dict] | None) -> str:
    """
    FEAT-054 (Phase 5): Render the Persona Switch Timeline section.

    Shown after the execution log when the run included at least one
    ``PERSONA_SWITCH`` step.  Displays a table with one row per switch:
    - Switch #
    - From persona (role_key before switch)
    - To persona (role_key after switch)
    - Raw persona name from Jira AC (e.g. "Demo Prod dir")
    - Timestamp of the switch (ISO-8601 UTC)
    - Credentials source: ``stored`` | ``initial_actor`` | ``hitl``
    - Duration of the switch in milliseconds

    Args
    ----
    persona_switch_history : list[dict] | None
        Entries from ``VQAState.persona_switch_history``.  Each entry has:
        ``from``, ``to``, ``persona_name``, ``timestamp``, ``method``,
        ``duration_ms``.

    Returns
    -------
    str
        HTML string for the persona switch timeline section,
        or empty string if there were no persona switches.
    """
    if not persona_switch_history:
        return ""

    total = len(persona_switch_history)

    # Method badge colour mapping
    _method_colors = {
        "stored": ("#10b981", "#022c22"),        # green — cached auth state
        "initial_actor": ("#818cf8", "#1e1b4b"),  # purple — "as yourself"
        "hitl": ("#f59e0b", "#1c1208"),           # amber — operator-supplied creds
    }

    rows = []
    for i, entry in enumerate(persona_switch_history, 1):
        from_role = entry.get("from", "?")
        to_role = entry.get("to", "?")
        persona_name = entry.get("persona_name", "")
        timestamp = entry.get("timestamp", "")
        method = entry.get("method", "?")
        duration_ms = entry.get("duration_ms", None)

        # Format duration
        if duration_ms is not None:
            if duration_ms >= 1000:
                duration_str = f"{duration_ms / 1000:.1f}s ({duration_ms} ms)"
            else:
                duration_str = f"{duration_ms} ms"
        else:
            duration_str = "N/A"

        # Method badge
        bg_color, text_color = _method_colors.get(method, ("#64748b", "#0f172a"))
        method_badge = (
            f'<span class="persona-method-badge" '
            f'style="background:{bg_color}; color:{text_color}">{method}</span>'
        )

        rows.append(f"""
            <tr>
                <td style="text-align:center; font-weight:700; color:#818cf8">{i}</td>
                <td><code class="persona-role-code">{from_role}</code></td>
                <td style="text-align:center; color:#94a3b8; font-size:1.1rem">→</td>
                <td><code class="persona-role-code">{to_role}</code></td>
                <td style="color:#e2e8f0">{persona_name or '<span class="muted">—</span>'}</td>
                <td style="color:#94a3b8; font-size:0.8rem; font-family:monospace">{timestamp}</td>
                <td>{method_badge}</td>
                <td style="color:#94a3b8; font-size:0.85rem">{duration_str}</td>
            </tr>
        """)

    return f"""
    <div class="section persona-switch-section">
        <h2>🔄 Persona Switch Timeline ({total} switch{'es' if total != 1 else ''})</h2>
        <p class="muted" style="margin-bottom: 1rem;">
            Mid-test auth context switches detected (FEAT-054).  Each row shows one
            persona switch: the outgoing role, the incoming role, credentials source,
            and wall-clock duration for the full logout + re-authentication cycle.
        </p>
        <table>
            <thead>
                <tr>
                    <th style="text-align:center">#</th>
                    <th>From</th>
                    <th style="text-align:center"></th>
                    <th>To</th>
                    <th>Persona Name (Jira AC)</th>
                    <th>Timestamp</th>
                    <th>Method</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody>
                {""  .join(rows)}
            </tbody>
        </table>
    </div>
    """


def _render_critic_pass_section(critic_verdicts: list[dict] | None) -> str:
    """
    Render the Critic Pass section of the HTML audit report.

    Shows one row per critic verdict emitted during the run (one per retry cycle).
    Handles three display states:
      - verdict="pass"               → green PASS badge
      - verdict="mismatch"           → amber MISMATCH badge with reason codes
      - critic_skipped=True          → grey SKIPPED (API error) badge
      - exhausted retries (mismatch, retry_count==2) → amber MISMATCH + RETRIES EXHAUSTED note

    Args
    ----
    critic_verdicts : list[dict] | None
        List of CriticVerdict.model_dump() dicts accumulated during the run.
        Each entry has verdict, reason_codes, feedback_summary, retry_count, critic_skipped.

    Returns
    -------
    str
        HTML string for the Critic Pass section.
    """
    if not critic_verdicts:
        return ""  # No critic activity — section omitted (static runs / no test_plan)

    rows: list[str] = []
    for v in critic_verdicts:
        verdict = v.get("verdict", "pass")
        skipped = v.get("critic_skipped", False)
        retry = v.get("retry_count", 0)
        reasons = v.get("reason_codes") or []
        summary = v.get("feedback_summary", "")

        if skipped:
            badge = '<span class="badge badge-skip">SKIPPED (API error)</span>'
            detail = ""
        elif verdict == "pass":
            badge = '<span class="badge badge-pass">PASS</span>'
            detail = ""
        else:
            exhausted = retry >= 2
            badge = (
                '<span class="badge badge-warn">MISMATCH'
                + (" — RETRIES EXHAUSTED" if exhausted else "")
                + "</span>"
            )
            codes_html = ", ".join(f"<code>{c}</code>" for c in reasons) if reasons else "(none)"
            detail = f"<div class='critic-reasons'>Reason codes: {codes_html}</div>"
            if summary:
                escaped_summary = summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                detail += f"<div class='critic-summary'>{escaped_summary}</div>"

        rows.append(
            f"""<tr>
                <td>{badge}</td>
                <td class="retry-count">{retry}</td>
                <td>{detail}</td>
            </tr>"""
        )

    rows_html = "\n".join(rows)
    return f"""
    <div class="section critic-pass-section">
        <h2>Critic Pass (Pre-Execution LLM Evaluator)</h2>
        <p class="section-desc">The critic audited the compiled TestPlan against the raw AC text before browser execution.</p>
        <table class="critic-table">
            <thead>
                <tr><th>Verdict</th><th>Retry</th><th>Detail</th></tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
    """


def _render_full_report(
    state: VQAState,
    video_url: str,
    duration_ms: int,
    failure_analysis: "FailureAnalysis | None" = None,
) -> str:
    """
    Assemble the complete HTML audit report.

    Args
    ----
    state : VQAState
        Final graph state with all execution data.
    video_url : str
        S3 URL of the uploaded session video.
    duration_ms : int
        Total run duration in milliseconds.

    Returns
    -------
    str
        Complete, self-contained HTML document string.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    steps = state.get("detailed_execution_log", [])
    bugs = state.get("bug_log", [])
    recovery_actions = state.get("recovery_action_log", [])
    dvf_entries = state.get("deferred_verification_failures", [])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>vQA Audit — {state["jira_ticket"].get("ticket_id", "N/A")} — {state.get("role_context", {}).get("role_name", "N/A")}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a; color: #e2e8f0; line-height: 1.6;
            padding: 2rem; max-width: 1400px; margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #334155);
            border-radius: 12px; padding: 2rem; margin-bottom: 2rem;
            border: 1px solid #475569;
        }}
        .header-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }}
        .header h1 {{ font-size: 1.75rem; color: #f1f5f9; }}
        .status-badge {{
            padding: 0.5rem 1.25rem; border-radius: 6px; font-weight: 700;
            font-size: 0.9rem; color: white; text-transform: uppercase;
        }}
        .meta-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }}
        .meta-item {{ background: #1e293b; padding: 0.75rem 1rem; border-radius: 8px; }}
        .meta-label {{ display: block; font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }}
        .meta-value {{ display: block; font-size: 0.95rem; color: #f1f5f9; font-weight: 500; }}
        .section {{
            background: #1e293b; border-radius: 12px; padding: 1.5rem;
            margin-bottom: 1.5rem; border: 1px solid #334155;
        }}
        .section h2 {{ color: #f1f5f9; margin-bottom: 1rem; font-size: 1.25rem; }}
        .muted {{ color: #64748b; font-style: italic; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 0.75rem; background: #334155; color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; }}
        td {{ padding: 0.75rem; border-bottom: 1px solid #334155; }}
        tr.pass td {{ color: #86efac; }}
        tr.fail td {{ color: #fca5a5; }}
        tr.skip td {{ color: #fde68a; }}
        .status-cell {{ font-size: 1.25rem; text-align: center; }}
        .steps-grid {{ display: flex; flex-direction: column; gap: 1rem; }}
        .step-card {{
            background: #0f172a; border-radius: 8px; padding: 1rem;
            border-left: 4px solid #475569;
        }}
        .step-card.pass {{ border-left-color: #10b981; }}
        .step-card.fail {{ border-left-color: #ef4444; }}
        .step-header {{
            display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem;
            flex-wrap: wrap;
        }}
        .step-num {{ font-weight: 700; color: #818cf8; }}
        .step-action {{
            background: #334155; padding: 0.2rem 0.6rem; border-radius: 4px;
            font-size: 0.8rem; font-weight: 600; color: #e2e8f0;
        }}
        .step-locator {{ color: #94a3b8; font-size: 0.85rem; font-family: monospace; }}
        .step-status {{ margin-left: auto; font-size: 1.25rem; }}
        .step-card img {{
            width: 100%; max-height: 400px; object-fit: contain;
            border-radius: 6px; margin: 0.5rem 0; background: #000;
        }}
        .step-reasoning {{ color: #cbd5e1; font-size: 0.85rem; margin: 0.5rem 0; }}
        .error-msg {{ color: #fca5a5; font-size: 0.85rem; margin: 0.5rem 0; }}
        .step-time {{ color: #64748b; font-size: 0.75rem; }}
        .retry-badge {{
            background: #f59e0b; color: #000; padding: 0.15rem 0.5rem;
            border-radius: 4px; font-size: 0.7rem; font-weight: 700;
        }}
        .recovery-type-badge {{ background: #6366f1; color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.75rem; }}
        .bug-type {{ font-weight: 700; font-family: monospace; }}
        tr.critical td {{ color: #fca5a5; }}
        tr.high td {{ color: #fdba74; }}
        .footer {{ text-align: center; color: #64748b; padding: 2rem 0; font-size: 0.8rem; }}
        /* Failure analysis */
        .triage-section {{ background: #1e1b2e; border: 1px solid #7c3aed; border-radius: 8px; padding: 1.5rem; margin: 2rem 0; }}
        .triage-title {{ color: #c4b5fd; font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem; }}
        .triage-overall {{ display: inline-block; padding: 4px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 700; margin-bottom: 1rem; }}
        .triage-product-bug {{ background: rgba(239,68,68,0.2); color: #fca5a5; border: 1px solid #ef4444; }}
        .triage-agent-issue {{ background: rgba(245,158,11,0.2); color: #fde68a; border: 1px solid #f59e0b; }}
        .triage-mixed {{ background: rgba(139,92,246,0.2); color: #c4b5fd; border: 1px solid #7c3aed; }}
        .triage-unknown {{ background: rgba(100,116,139,0.2); color: #94a3b8; border: 1px solid #475569; }}
        .triage-summary {{ color: #cbd5e1; font-size: 0.9rem; line-height: 1.6; margin-bottom: 1.25rem; }}
        .triage-step {{ border-left: 3px solid #374151; padding: 0.6rem 1rem; margin-bottom: 0.5rem; border-radius: 0 6px 6px 0; background: rgba(0,0,0,0.2); }}
        .triage-step.product-bug {{ border-left-color: #ef4444; }}
        .triage-step.agent-issue {{ border-left-color: #f59e0b; }}
        .triage-step-label {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 2px; }}
        .triage-step-label.product-bug {{ color: #fca5a5; }}
        .triage-step-label.agent-issue {{ color: #fde68a; }}
        .triage-step-ac {{ color: #e2e8f0; font-size: 0.85rem; margin-bottom: 4px; }}
        .triage-step-reason {{ color: #94a3b8; font-size: 0.8rem; }}
        .triage-badge-confidence {{ font-size: 0.65rem; color: #64748b; margin-left: 6px; }}
        /* FEAT-001: AC Quality Gate styles */
        .quality-section {{
            background: linear-gradient(135deg, #1e293b, #1a2332);
            border-radius: 12px; padding: 1.5rem;
            margin-bottom: 1.5rem; border: 1px solid #334155;
        }}
        .quality-header {{ display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }}
        .quality-grade {{
            padding: 0.4rem 1rem; border-radius: 6px; font-weight: 700;
            font-size: 0.85rem; color: white; text-transform: uppercase;
        }}
        .quality-good {{ background: #10b981; }}
        .quality-fair {{ background: #f59e0b; }}
        .quality-poor {{ background: #ef4444; }}
        .quality-dims {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.75rem; margin-top: 0.75rem;
        }}
        .quality-dim {{
            background: #0f172a; border-radius: 6px; padding: 0.6rem 0.8rem;
        }}
        .quality-dim-label {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; margin-bottom: 4px; }}
        .quality-bar {{ height: 6px; background: #334155; border-radius: 3px; overflow: hidden; }}
        .quality-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
        .quality-bar-0 {{ width: 0; background: #ef4444; }}
        .quality-bar-1 {{ width: 50%; background: #f59e0b; }}
        .quality-bar-2 {{ width: 100%; background: #10b981; }}
        .quality-dim-score {{ font-size: 0.75rem; color: #e2e8f0; float: right; }}
        .quality-warnings {{ margin-top: 1rem; }}
        .quality-warning {{ color: #fca5a5; font-size: 0.8rem; padding: 0.3rem 0; border-bottom: 1px solid #1e293b; }}
        .quality-step-badge {{
            display: inline-block; width: 12px; height: 12px;
            border-radius: 50%; margin-right: 6px; vertical-align: middle;
        }}
        .badge-good {{ background: #10b981; }}
        .badge-fair {{ background: #f59e0b; }}
        .badge-poor {{ background: #ef4444; }}
        /* FEAT-002: AC Enrichment styles */
        .enrichment-section {{
            background: linear-gradient(135deg, #1a2332, #1e2d3d);
            border-radius: 12px; padding: 1rem 1.5rem;
            margin-bottom: 1.5rem; border: 1px solid #2563eb40;
        }}
        .enrichment-header {{ display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }}
        .enrichment-icon {{ font-size: 1.25rem; }}
        .enrichment-title {{ font-weight: 600; color: #93c5fd; font-size: 0.9rem; }}
        .enrichment-chars {{ font-size: 0.75rem; color: #64748b; margin-left: auto; }}
        .enrichment-body {{ display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }}
        .enrichment-domain-tag {{
            background: #1e3a5f; color: #93c5fd; padding: 0.2rem 0.6rem;
            border-radius: 4px; font-size: 0.75rem; font-weight: 600;
        }}
        .enrichment-articles {{ color: #94a3b8; font-size: 0.8rem; }}
        /* FEAT-023: DVF amber warning styles */
        .dvf-section {{ border-color: #f59e0b !important; }}
        .dvf-type-badge {{
            background: #f59e0b; color: #000; padding: 0.25rem 0.5rem;
            border-radius: 4px; font-weight: 600; font-size: 0.75rem;
        }}
        .dvf-pattern {{ font-family: monospace; color: #fde68a; font-size: 0.85rem; }}
        /* FEAT-037: CV Fallback badge styles */
        .cv-fallback-badge {{
            background: linear-gradient(135deg, #7c3aed, #6d28d9);
            color: #ede9fe; padding: 0.15rem 0.6rem;
            border-radius: 4px; font-size: 0.7rem; font-weight: 700;
            border: 1px solid #8b5cf6;
        }}
        .cv-fallback-section {{ border-color: #7c3aed !important; }}
        /* FEAT-118 Phase 5: Execution Layer Attribution badge styles */
        .execution-layer-badge {{
            padding: 0.15rem 0.5rem; border-radius: 4px;
            font-size: 0.7rem; font-weight: 700;
            display: inline-flex; align-items: center; gap: 0.15rem;
        }}
        .layer-reflex {{ background: #065f46; color: #6ee7b7; border: 1px solid #059669; }}
        .layer-bedrock {{ background: #1e3a5f; color: #93c5fd; border: 1px solid #3b82f6; }}
        .layer-cv {{ background: #4c1d95; color: #ddd6fe; border: 1px solid #7c3aed; }}
        .layer-hitl {{ background: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; }}
        /* FEAT-042: RAG Selector Stats section */
        .rag-stats-section {{
            border-color: #0ea5e9 !important;
        }}
        .rag-stats-section h2 {{ color: #7dd3fc; }}
        /* FEAT-054: Persona Switch Timeline section */
        .persona-switch-section {{
            border-color: #818cf8 !important;
        }}
        .persona-switch-section h2 {{ color: #c4b5fd; }}
        .persona-role-code {{
            background: #1e293b; color: #a5b4fc;
            padding: 0.15rem 0.5rem; border-radius: 4px;
            font-size: 0.82rem; font-family: monospace;
            border: 1px solid #334155;
        }}
        .persona-method-badge {{
            display: inline-block; padding: 0.2rem 0.55rem;
            border-radius: 4px; font-size: 0.72rem; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.04em;
        }}
    </style>
</head>
<body>
    {_render_header(state, duration_ms)}
    {_render_video_section(video_url)}
    {_render_ac_quality_section(state.get("ac_quality_result"))}
    {_render_ac_enrichment_section(state.get("ac_enrichment_result"))}
    {_render_critic_pass_section(state.get("run_metrics", {}).get("critic_verdicts"))}
    {_render_ac_table(state)}
    {_render_persona_switch_section(state.get("persona_switch_history", []))}
    {_render_recovery_log(recovery_actions)}
    {_render_dvf_section(dvf_entries)}
    {_render_failure_analysis_section(failure_analysis)}
    {_render_execution_log(steps)}
    {_render_bug_log(bugs)}
    {_render_metrics_section(state.get("run_metrics", {}))}
    {_render_cv_fallback_section(state.get("cv_fallback_results", []))}
    {_render_rag_stats_section(state.get("rag_selector_stats", []))}
    <div class="footer">
        Generated by vQA · {timestamp} · vCreative Engineering<br>
        AWS Bedrock + LangGraph + Playwright
    </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def reporter_node(state: VQAState) -> dict:
    """
    LangGraph node: terminal node — close browser, upload video, generate report.

    This is the FINAL node in the graph.  It:
    1. Closes the Playwright browser context (finalises the .webm video)
    2. Uploads the session video to S3
    3. Renders the HTML audit report
    4. Uploads the report to S3
    5. Returns the artifact URLs in the state

    Args
    ----
    state : VQAState
        The final LangGraph state with all execution data.

    Returns
    -------
    dict
        Partial state update containing:
        - ``s3_video_url``: S3 URL of the uploaded video
        - ``s3_report_url``: S3 URL of the uploaded HTML report
        - ``final_html_report``: the raw HTML string
        - ``browser_session_active``: False
    """
    run_id: str = state["run_id"]
    ticket_id: str = state["jira_ticket"].get("ticket_id", "")
    role_key: str = state.get("role_context", {}).get("role_key", "")

    # Determine if the run passed so we know whether to run failure analysis.
    # Use set-based coverage: every index 0..N-1 must be present.
    # Raw len() is unreliable because operator.add can duplicate indices when
    # verifier and evaluator both mark the same final step complete.
    ac_steps = state["jira_ticket"].get("acceptance_criteria_steps", [])
    completed = state.get("ac_steps_completed", [])
    _rn_completed_set = set(completed)
    coverage_gap_indices = set(state.get("ac_steps_coverage_gap", []))
    dvf_indices = {entry["ac_step_index"] for entry in state.get("deferred_verification_failures", [])}
    _effective_completed = _rn_completed_set - coverage_gap_indices - dvf_indices
    all_passed = (
        len(ac_steps) > 0
        and len(coverage_gap_indices) == 0
        and len(dvf_indices) == 0
        and all(i in _effective_completed for i in range(len(ac_steps)))
    )

    logger.info(
        "[%s] Reporter: closing browser and generating report (passed=%s)...",
        run_id,
        all_passed,
    )

    # ── Step 1: Close browser + retrieve video ────────────────────
    video_url: str = ""
    try:
        manager = get_manager(run_id)
        video_path = await manager.close()

        if video_path and video_path.exists():
            video_url = await upload_video(
                video_path=video_path,
                run_id=run_id,
                ticket_id=ticket_id,
            )
            logger.info("[%s] Video uploaded: %s", run_id, video_url)
        else:
            logger.warning("[%s] No video file to upload", run_id)

        unregister_manager(run_id)
        _remove_state_tracker(run_id)

    except KeyError:
        logger.warning("[%s] No BrowserManager registered — skipping video", run_id)
    except Exception as e:
        logger.error("[%s] Error during browser close/upload: %s", run_id, str(e), exc_info=True)

    # ── Step 2: Calculate run duration ────────────────────────────
    log = state.get("detailed_execution_log", [])
    duration_ms = 0
    if log:
        try:
            first_ts = log[0].get("timestamp", "")
            last_ts = log[-1].get("timestamp", "")
            if first_ts and last_ts:
                from datetime import datetime

                t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                duration_ms = int((t2 - t1).total_seconds() * 1000)
        except Exception:
            pass

    # ── Step 3: Failure analysis (only on failure, best-effort) ─────────
    failure_analysis = None
    if not all_passed:
        failure_analysis = await run_failure_analysis(state)
        logger.info(
            "[%s] Failure analysis: overall=%s",
            run_id,
            failure_analysis.get("overall", "?"),
        )

    # ── Step 3b: Snapshot run metrics from registry ─────────────────
    final_run_metrics = {}
    try:
        from backend.engine.metrics import remove_run_metrics

        final_run_metrics = remove_run_metrics(run_id)
    except Exception as e:
        logger.warning("[%s] Failed to snapshot run metrics: %s", run_id, e)

    # ── Step 3c: Persist critic_verdicts into run_metrics ─────────────
    # critic-pass-llm-evaluator: surface critic_result (the final state after
    # all retry cycles) in run_metrics.critic_verdicts so GET /status/{run_id}
    # exposes it in the API response and the report renderer can access it.
    # critic_result is the last verdict written by critic_node; if the critic
    # looped (mismatch + retry), retry_count reflects how many cycles occurred.
    critic_result = state.get("critic_result")
    if critic_result:
        # Wrap in a list — future phases may accumulate multiple verdicts;
        # for now there is one verdict per run (one critic pass, possibly retried).
        final_run_metrics["critic_verdicts"] = [critic_result]
        logger.info(
            "[%s] reporter: persisted critic_verdicts into run_metrics "
            "(verdict=%s retry_count=%d skipped=%s)",
            run_id,
            critic_result.get("verdict"),
            critic_result.get("retry_count", 0),
            critic_result.get("critic_skipped", False),
        )

    # Merge into state for the report renderer
    state_for_report = {**state, "run_metrics": final_run_metrics}

    # ── Step 4: Render HTML report ───────────────────────────────
    html_report: str = _render_full_report(state_for_report, video_url, duration_ms, failure_analysis)

    # ── Step 5: Upload report to S3 ───────────────────────────────
    report_url: str = ""
    try:
        report_url = await upload_report(
            html_content=html_report,
            run_id=run_id,
            ticket_id=ticket_id,
            role_key=role_key,
        )
        logger.info("[%s] Report uploaded: %s", run_id, report_url)

        # ── Step 5b: Upload error context (JSON/MD) ───────────────
        if failure_analysis and failure_analysis.get("error_context"):
            ctx = failure_analysis["error_context"]
            json_str = json.dumps(ctx, indent=2)
            md_str = _generate_error_context_md(ctx)

            json_url, md_url = await upload_error_context(
                json_content=json_str,
                md_content=md_str,
                run_id=run_id,
                ticket_id=ticket_id,
            )
            logger.info("[%s] Failure context uploaded: %s", run_id, json_url)
            # Optionally store these URLs in state if needed
    except Exception as e:
        logger.error("[%s] Failed to upload artifacts: %s", run_id, str(e), exc_info=True)

    # ── Step 6: Post Jira comment on failure ────────────────────────
    if not all_passed and failure_analysis and ticket_id:
        comment_body = failure_analysis.get("jira_comment", "")
        if comment_body:
            # Append report URL to comment if we have it
            if report_url and report_url not in comment_body:
                comment_body += f"\n\nFull report: {report_url}"
            await post_jira_comment(ticket_id, comment_body)

    # ── Step 6b: Webhook notification (Phase 5B) ──────────────────────
    try:
        from backend.config import settings as _wh_settings
        from backend.engine.webhooks import send_completion_webhook

        _wh_url = state.get("webhook_url", "") or _wh_settings.webhook_url
        if _wh_url:
            completed = state.get("completed_ac_steps", [])
            ac_steps = state.get("ac_steps", [])
            await send_completion_webhook(
                webhook_url=_wh_url,
                webhook_format=getattr(_wh_settings, "webhook_format", "generic"),
                run_id=run_id,
                ticket_id=ticket_id,
                status="passed" if all_passed else "failed",
                ac_total=len(ac_steps),
                ac_passed=len(completed) if isinstance(completed, list) else 0,
                report_url=report_url,
                video_url=video_url,
                cost_usd=final_run_metrics.get("estimated_cost_usd", 0.0),
                duration_ms=duration_ms,
                role=role_key,
            )
    except Exception as e:
        logger.warning("[%s] Webhook notification failed: %s", run_id, e)

    # ── Step 6c: Record run in history (Phase 5C) ──────────────────────
    try:
        from backend.storage.run_history import run_history as _rh

        completed = state.get("completed_ac_steps", [])
        ac_steps = state.get("ac_steps", [])
        _rh.record_run(
            run_id=run_id,
            ticket_id=ticket_id,
            role=role_key,
            status="passed" if all_passed else "failed",
            duration_ms=duration_ms,
            ac_total=len(ac_steps),
            ac_passed=len(completed) if isinstance(completed, list) else 0,
            cost_usd=final_run_metrics.get("estimated_cost_usd", 0.0),
            report_url=report_url,
            video_url=video_url,
            profile=state.get("active_profile", "vsuite"),
        )

        # ── Regression detection (Phase 6E) ────────────────────────────
        is_regression = _rh.detect_regression(
            ticket_id=ticket_id,
            current_run_id=run_id,
            current_status="passed" if all_passed else "failed",
        )
        if is_regression:
            state["is_regression"] = True
            logger.warning(
                "[%s] 🚨 REGRESSION: %s was passing, now failing",
                run_id,
                ticket_id,
            )
    except Exception as e:
        logger.warning("[%s] Run history recording failed: %s", run_id, e)

    # ── Step 7: Persist learned patterns to cross-run memory ──────────
    # Records which locator strategies worked/failed so future runs can
    # inject proven patterns as few-shot examples in the planner prompt.
    try:
        patterns_recorded = 0
        for step in log:
            action_type = step.get("action_type", "")
            if action_type in ("wait", "scroll", "done"):
                continue  # Skip non-informative actions

            payload = step.get("action_payload", {})
            strategy = payload.get("strategy", "")
            role = payload.get("role", "")
            name = payload.get("name", "")

            if not strategy or not name:
                continue

            strategy_key = f"{strategy}:{role}:{name}"
            ac_idx = step.get("ac_step_index", 0)
            ac_text = ""
            if ac_idx < len(ac_steps):
                ac_text = ac_steps[ac_idx]

            situation = f"{action_type} on '{name}'"
            if role:
                situation = f"{action_type} {role}('{name}')"

            # Check if this step had a fallback (executor tried alternative)
            fallback = step.get("executor_fallback", "")
            strategy_fix = fallback if fallback and step.get("success") else ""

            persistent_memory.record(
                situation=situation,
                strategy_tried=strategy_key,
                worked=step.get("success", False),
                strategy_fix=strategy_fix,
                ac_step=ac_text,
                ticket_id=ticket_id,
            )
            patterns_recorded += 1

        logger.info(
            "[%s] Persistent memory: recorded %d patterns (total: %d)",
            run_id,
            patterns_recorded,
            persistent_memory.entry_count,
        )
    except Exception as e:
        logger.warning(
            "[%s] Failed to persist learned patterns: %s",
            run_id,
            str(e),
        )

    # ── Step 8: Auto-propose KB updates from proven patterns (Phase 4E) ──
    kb_proposals: list[dict] = []
    try:
        kb_proposals = persistent_memory.propose_kb_updates(min_success_count=3)
        if kb_proposals:
            logger.info(
                "[%s] KB update proposals: %d patterns proven 3+ times",
                run_id,
                len(kb_proposals),
            )
            for proposal in kb_proposals[:5]:  # Log top 5
                logger.info(
                    "[%s]   KB proposal: '%s' → %s (%dx)",
                    run_id,
                    proposal.get("situation", "?"),
                    proposal.get("strategy", "?"),
                    proposal.get("success_count", 0),
                )
    except Exception as e:
        logger.warning(
            "[%s] Failed to generate KB proposals: %s",
            run_id,
            str(e),
        )

    # ── Step 9: FEAT-009 — Extract cross-run self-heal patterns ──────
    # Scans the execution log for failure→success selector transitions
    # and persists them to knowledge/selector_corrections.json so that
    # future runs can skip known-bad selectors immediately.
    try:
        from backend.memory.pattern_store import extract_patterns

        pattern_count = extract_patterns(log, ticket_id=ticket_id)
        if pattern_count > 0:
            logger.info(
                "[%s] Cross-run patterns: extracted %d new self-heal corrections",
                run_id,
                pattern_count,
            )
    except Exception as e:
        logger.warning(
            "[%s] Failed to extract cross-run patterns: %s",
            run_id,
            str(e),
        )

    logger.info(
        "[%s] Reporter complete. Video: %s | Report: %s",
        run_id,
        video_url or "(none)",
        report_url or "(none)",
    )

    return {
        "s3_video_url": video_url,
        "s3_report_url": report_url,
        "final_html_report": html_report,
        "browser_session_active": False,
        "run_metrics": final_run_metrics,
        "kb_update_proposals": kb_proposals,
    }
