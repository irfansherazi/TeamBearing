/**
 * CopilotSidebar — AC Step Tracker + HITL Takeover Panel
 * =========================================================
 * Can render in two modes:
 *   inline={true}  → full-width panel card (used in main content where LiveBrowser was)
 *   inline={false} → narrow sidebar column (legacy, not used currently)
 */

import React, { useEffect, useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import "./CopilotSidebar.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AcStepStatus =
  | "pending"
  | "in_progress"
  | "passed"
  | "failed"
  | "skipped"
  | "awaiting_human";

export interface AcStep {
  index: number;
  text: string;
  status: AcStepStatus;
  error: string;
  humanSelector: string;
}

interface CopilotState {
  steps: AcStep[];
  awaitingHuman: boolean;
  awaitingStepIndex: number;
  awaitingStepText: string;
  awaitingError: string;
  instructions: string;
  isComplete: boolean;
}

interface CopilotSidebarProps {
  runId: string;
  ticketId: string;
  ws: WebSocket | null;
  /** When true, renders as a full-width panel card instead of a narrow sidebar */
  inline?: boolean;
  onResumed?: () => void;
}

// ---------------------------------------------------------------------------
// Status maps
// ---------------------------------------------------------------------------

const STATUS_ICON: Record<AcStepStatus, string> = {
  pending: "○",
  in_progress: "◎",
  passed: "✓",
  failed: "✗",
  skipped: "⏭",
  awaiting_human: "⚠",
};

const STATUS_LABEL: Record<AcStepStatus, string> = {
  pending: "Pending",
  in_progress: "Running",
  passed: "Passed",
  failed: "Failed",
  skipped: "Skipped",
  awaiting_human: "Needs You",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const CopilotSidebar: React.FC<CopilotSidebarProps> = ({
  runId,
  ticketId,
  ws,
  inline = false,
  onResumed,
}) => {
  const [state, setState] = useState<CopilotState>({
    steps: [],
    awaitingHuman: false,
    awaitingStepIndex: -1,
    awaitingStepText: "",
    awaitingError: "",
    instructions: "",
    isComplete: false,
  });

  const [resuming, setResuming] = useState(false);
  // Captured browser actions recorded via the JS event listener in the Playwright browser
  const [capturedActions, setCapturedActions] = useState<Array<{
    event_type: string;
    best_selector: string;
    strategy: string;
    value: string;
    timestamp: string;
  }>>([]);
  // Explanation text (required when no actions were captured)
  const [hitlExplanation, setHitlExplanation] = useState("");
  // Whether the user has been prompted to add an explanation
  const [needsExplanation, setNeedsExplanation] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  const actionsEndRef = useRef<HTMLDivElement>(null);

  // ── WebSocket message handler ─────────────────────────────────────────────
  useEffect(() => {
    if (!ws) return;

    const handler = (evt: MessageEvent) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(evt.data as string);
      } catch {
        return;
      }

      switch (msg.type) {
        case "ac_progress": {
          const raw = (msg.steps as Array<Record<string, unknown>>) ?? [];
          const steps: AcStep[] = raw.map((s) => ({
            index: s.index as number,
            text: s.text as string,
            status: s.status as AcStepStatus,
            error: (s.error as string) ?? "",
            humanSelector: (s.human_selector as string) ?? "",
          }));
          setState((prev) => ({ ...prev, steps }));
          break;
        }
        case "copilot_ready": {
          // Reset captured actions when a new HITL starts
          setCapturedActions([]);
          setHitlExplanation("");
          setNeedsExplanation(false);
          setState((prev) => ({
            ...prev,
            awaitingHuman: true,
            awaitingStepIndex: msg.ac_step_index as number,
            awaitingStepText: msg.ac_step_text as string,
            awaitingError: msg.error_message as string,
            instructions: (msg.instructions as string) ?? "",
          }));
          break;
        }
        case "hitl_action_recorded": {
          // Real-time action echoed from the Playwright browser's JS event listener
          const action = msg.action as Record<string, unknown>;
          if (action) {
            setCapturedActions((prev) => [
              ...prev,
              {
                event_type: (action.event_type as string) ?? "action",
                best_selector: (action.best_selector as string) ?? "",
                strategy: (action.strategy as string) ?? "",
                value: (action.value as string) ?? "",
                timestamp: (action.timestamp as string) ?? new Date().toISOString(),
              },
            ]);
            // Scroll to bottom of actions feed
            setTimeout(() => actionsEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
          }
          break;
        }
        case "completed":
        case "failed": {
          setState((prev) => ({ ...prev, awaitingHuman: false, isComplete: true }));
          break;
        }
        default:
          break;
      }
    };

    ws.addEventListener("message", handler);
    return () => ws.removeEventListener("message", handler);
  }, [ws]);

  // Auto-scroll active step into view (sidebar mode only)
  useEffect(() => {
    if (inline || !listRef.current) return;
    const active = listRef.current.querySelector(
      ".ac-step--in_progress, .ac-step--awaiting_human"
    );
    if (active) active.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [state.steps, inline]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const handleResume = async () => {
    // If no browser actions were captured, we need an explanation
    if (capturedActions.length === 0 && !hitlExplanation.trim()) {
      setNeedsExplanation(true);
      return;
    }
    setNeedsExplanation(false);
    setResuming(true);
    try {
      const explanation = hitlExplanation.trim() ||
        `Human completed step via headed browser. Captured ${capturedActions.length} action(s): ` +
        capturedActions.map(a => `${a.event_type} on '${a.best_selector.slice(0, 40)}'`).join(", ");

      const res = await authenticatedFetch(`/runs/${runId}/human-takeover/done`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ explanation }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        if (errBody.error === "explanation_required") {
          setNeedsExplanation(true);
          setResuming(false);
          return;
        }
      }
      setCapturedActions([]);
      setHitlExplanation("");
      setNeedsExplanation(false);
      setState((prev) => ({ ...prev, awaitingHuman: false }));
      onResumed?.();
    } catch (err) {
      console.error("[CopilotSidebar] Resume failed:", err);
    } finally {
      setResuming(false);
    }
  };

  const handleSkip = async () => {
    try {
      // POST to the dedicated /skip alias route
      await authenticatedFetch(`/runs/${runId}/human-takeover/skip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      setCapturedActions([]);
      setHitlExplanation("");
      setNeedsExplanation(false);
      setState((prev) => ({ ...prev, awaitingHuman: false }));
    } catch (err) {
      console.error("[CopilotSidebar] Skip failed:", err);
    }
  };

  // ── Computed ──────────────────────────────────────────────────────────────
  const totalSteps = state.steps.length;
  const passedCount = state.steps.filter((s) => s.status === "passed").length;
  const failedCount = state.steps.filter((s) => s.status === "failed").length;
  // Bug B fix: count awaiting_human + skipped as "needs review" (warning) steps.
  // The previous code only counted "failed" — so runs with awaiting_human or
  // skipped steps incorrectly showed "✓ All N steps passed" (green banner).
  const warningCount = state.steps.filter(
    (s) => s.status === "awaiting_human" || s.status === "skipped"
  ).length;

  // Three-state banner: fail (red) > warn (yellow) > pass (green)
  const bannerVariant = failedCount > 0 ? "fail" : warningCount > 0 ? "warn" : "pass";
  const bannerText =
    bannerVariant === "pass"
      ? `✓ All ${totalSteps} steps passed`
      : bannerVariant === "warn"
      ? `${passedCount}/${totalSteps} passed · ${warningCount} need${warningCount === 1 ? "s" : ""} review`
      : `${passedCount}/${totalSteps} passed · ${failedCount} failed`;

  // ── Inline (full-width panel) render ─────────────────────────────────────
  if (inline) {
    return (
      <div className="copilot-panel panel" aria-label="AC Step Tracker">
        {/* Header row */}
        <div className="copilot-panel__header panel-header">
          <div className="copilot-panel__title-group">
            <span className="copilot-panel__icon">🤖</span>
            <h2>AC Steps</h2>
            {ticketId && <span className="copilot-header__ticket">{ticketId}</span>}
          </div>
          <div className="copilot-panel__meta">
            {totalSteps > 0 && (
              <>
                <div className="copilot-inline-bar">
                  <div
                    className="copilot-inline-bar__fill"
                    style={{ width: `${(passedCount / totalSteps) * 100}%` }}
                  />
                </div>
                <span className="copilot-panel__count">
                  {passedCount}/{totalSteps} passed
                  {failedCount > 0 && ` · ${failedCount} failed`}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Step pills — horizontal wrap grid */}
        {totalSteps === 0 ? (
          <div className="copilot-panel__empty">
            <span className="copilot-panel__empty-icon">⏳</span>
            <p>Waiting for run to start — AC steps will appear here once the agent begins.</p>
          </div>
        ) : (
          <ol className="copilot-inline-steps" ref={listRef}>
            {state.steps.map((step) => (
              <li
                key={step.index}
                className={`copilot-inline-step copilot-inline-step--${step.status}`}
                title={`${STATUS_LABEL[step.status]}: ${step.text}${step.error ? `\n\nError: ${step.error}` : ""}`}
              >
                <span className="copilot-inline-step__num">{step.index + 1}</span>
                <span className="copilot-inline-step__icon" aria-hidden="true">
                  {STATUS_ICON[step.status]}
                </span>
                <span className="copilot-inline-step__text">{step.text}</span>
                {step.error && (
                  <span className="copilot-inline-step__err">
                    {step.error.slice(0, 80)}{step.error.length > 80 ? "…" : ""}
                  </span>
                )}
                {step.humanSelector && (
                  <code className="copilot-inline-step__sel">👤 {step.humanSelector}</code>
                )}
              </li>
            ))}
          </ol>
        )}

        {/* Takeover alert */}
        {state.awaitingHuman && (
          <div className="copilot-takeover" role="alertdialog" aria-label="Human takeover required">

            {/* ── Top alert bar ── */}
            <div className="copilot-takeover__badge">🤚 Agent Needs Help — Step {state.awaitingStepIndex + 1}</div>

            {/* ── Step to complete ── */}
            <div className="copilot-takeover__step-card">
              <div className="copilot-takeover__step-label">
                👇 Complete this step in the <strong>Playwright browser</strong> on your desktop:
              </div>
              <p className="copilot-takeover__step-text">
                {state.awaitingStepText}
              </p>
            </div>

            {state.awaitingError && (
              <p className="copilot-takeover__error">
                <strong>Why the agent failed:</strong> {state.awaitingError}
              </p>
            )}

            {/* ── Real-time captured actions feed ── */}
            <div className="copilot-hitl-actions">
              <div className="copilot-hitl-actions__header">
                {capturedActions.length > 0 ? (
                  <span className="copilot-hitl-actions__captured">
                    ✅ {capturedActions.length} action{capturedActions.length !== 1 ? "s" : ""} captured
                  </span>
                ) : (
                  <span className="copilot-hitl-actions__waiting">
                    ⏳ Waiting for your actions in the browser...
                  </span>
                )}
              </div>
              {capturedActions.length > 0 && (
                <ul className="copilot-hitl-actions__list">
                  {capturedActions.map((action, i) => (
                    <li key={i} className="copilot-hitl-actions__item">
                      <span className="copilot-hitl-actions__type">
                        {action.event_type === "click" ? "🖱 click" : action.event_type === "change" ? "✏️ fill" : action.event_type === "keyup" ? "⌨️ type" : action.event_type}
                      </span>
                      <span className="copilot-hitl-actions__selector">
                        {action.best_selector.slice(0, 60)}{action.best_selector.length > 60 ? "…" : ""}
                      </span>
                      {action.value && (
                        <span className="copilot-hitl-actions__value">= "{action.value.slice(0, 30)}"</span>
                      )}
                    </li>
                  ))}
                  <div ref={actionsEndRef} />
                </ul>
              )}
            </div>

            {/* ── Explanation textarea (shown when needed) ── */}
            {(needsExplanation || capturedActions.length === 0) && (
              <div className="copilot-hitl-explanation">
                <label className="copilot-hitl-explanation__label">
                  💬 What did you do?
                  {needsExplanation && capturedActions.length === 0 && (
                    <span className="copilot-hitl-explanation__required"> — required (no actions captured)</span>
                  )}
                </label>
                <textarea
                  className="copilot-hitl-explanation__input"
                  rows={2}
                  placeholder='e.g. "Clicked the search panel open button then searched for They Beta Boys"'
                  value={hitlExplanation}
                  onChange={(e) => setHitlExplanation(e.target.value)}
                  disabled={resuming}
                />
              </div>
            )}

            <p className="copilot-takeover__instructions">
              {state.instructions ||
                "Interact directly in the Playwright browser on your desktop. Your actions are recorded automatically."}
            </p>
            <div className="copilot-takeover__actions copilot-takeover__actions--row">
              <button
                id="btn-resume-agent"
                className="copilot-btn copilot-btn--primary"
                onClick={handleResume}
                disabled={resuming}
              >
                {resuming ? "Resuming…" : "✅ Done — Resume Agent"}
              </button>
              <button
                id="btn-skip-step"
                className="copilot-btn copilot-btn--secondary"
                onClick={handleSkip}
                disabled={resuming}
              >
                ⏭ Skip Step
              </button>
            </div>
          </div>
        )}


        {/* Completion banner */}
        {state.isComplete && !state.awaitingHuman && totalSteps > 0 && (
          <div className={`copilot-complete copilot-complete--${bannerVariant}`}>
            {bannerText}
          </div>
        )}
      </div>
    );
  }

  // ── Sidebar (narrow column) render ───────────────────────────────────────
  return (
    <aside className="copilot-sidebar" aria-label="Copilot — AC Step Tracker">
      <header className="copilot-header">
        <div className="copilot-header__brand">
          <span className="copilot-header__icon">🤖</span>
          <span className="copilot-header__title">Copilot</span>
        </div>
        {ticketId && <span className="copilot-header__ticket">{ticketId}</span>}
      </header>

      {totalSteps > 0 && (
        <div className="copilot-progress" aria-label="AC step progress">
          <div className="copilot-progress__bar-container">
            <div
              className="copilot-progress__bar"
              style={{ width: `${(passedCount / totalSteps) * 100}%` }}
            />
          </div>
          <span className="copilot-progress__label">
            {passedCount}/{totalSteps} passed
            {failedCount > 0 && ` · ${failedCount} failed`}
          </span>
        </div>
      )}

      {totalSteps === 0 ? (
        <p className="copilot-empty">Waiting for AC steps to be parsed…</p>
      ) : (
        <ol className="copilot-step-list" ref={listRef}>
          {state.steps.map((step) => (
            <li
              key={step.index}
              className={`ac-step ac-step--${step.status}`}
              aria-label={`Step ${step.index + 1}: ${STATUS_LABEL[step.status]}`}
            >
              <span className="ac-step__icon" title={STATUS_LABEL[step.status]} aria-hidden="true">
                {STATUS_ICON[step.status]}
              </span>
              <div className="ac-step__body">
                <p className="ac-step__text">{step.text}</p>
                {step.error && (
                  <p className="ac-step__error" title={step.error}>
                    {step.error.slice(0, 120)}{step.error.length > 120 ? "…" : ""}
                  </p>
                )}
                {step.humanSelector && (
                  <code className="ac-step__selector" title="Human-captured selector">
                    👤 {step.humanSelector}
                  </code>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {state.awaitingHuman && (
        <div className="copilot-takeover" role="alertdialog" aria-label="Human takeover required">
          <div className="copilot-takeover__badge">⚠ Agent Stuck</div>
          <p className="copilot-takeover__step-text">
            <strong>Step {state.awaitingStepIndex + 1}:</strong> {state.awaitingStepText}
          </p>
          {state.awaitingError && (
            <p className="copilot-takeover__error">{state.awaitingError}</p>
          )}
          <p className="copilot-takeover__instructions">
            {state.instructions ||
              "The headed browser is open on your screen. Complete this step manually, then click Resume Agent."}
          </p>
          <div className="copilot-takeover__actions">
            <button
              id="btn-resume-agent"
              className="copilot-btn copilot-btn--primary"
              onClick={handleResume}
              disabled={resuming}
            >
              {resuming ? "Resuming…" : "✅ Resume Agent"}
            </button>
            <button
              id="btn-skip-step"
              className="copilot-btn copilot-btn--secondary"
              onClick={handleSkip}
              disabled={resuming}
            >
              ⏭ Skip Step
            </button>
          </div>
        </div>
      )}

      {state.isComplete && !state.awaitingHuman && totalSteps > 0 && (
        <div className={`copilot-complete copilot-complete--${bannerVariant}`}>
          {bannerText}
        </div>
      )}
    </aside>
  );
};

export default CopilotSidebar;
