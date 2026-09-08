/**
 * vQA — Execution Log Component
 * ================================
 * Module: frontend/src/components/ExecutionLog.tsx
 *
 * Displays the real-time execution log as a scrolling list of
 * action cards.  Reasoning is always visible beneath each step.
 * A "Cancel Test" button stops the run early and generates a partial report.
 */

import { useEffect, useRef, useState } from "react";
import type { WSStepMessage, WSTerminalMessage } from "../types";
import { API_BASE_URL } from "../types";
import type { WSConnectionState } from "../hooks/useWebSocket";
import { ThinkingCard } from "./ThinkingCard";
import { authenticatedFetch, VITE_API_KEY } from "../api_client";


interface ExecutionLogProps {
  runId: string | null;
  runLabel?: string | null;
  steps: WSStepMessage[];
  terminalMessage: WSTerminalMessage | null;
  connectionState: WSConnectionState;
  isThinking: boolean;
  thinkingText: string;
  thinkingAcStep: number;
  thinkingAcTotal: number;
}

export function ExecutionLog({
  runId,
  runLabel,
  steps,
  terminalMessage,
  connectionState,
  isThinking,
  thinkingText,
  thinkingAcStep,
  thinkingAcTotal,
}: ExecutionLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [cancelling, setCancelling] = useState(false);

  // Auto-scroll to bottom when new steps arrive or thinking changes
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps.length, isThinking]);

  // Reset cancelling state when a new run starts
  useEffect(() => {
    setCancelling(false);
  }, [runId]);


  async function handleCancel() {
    if (!runId || cancelling) return;
    setCancelling(true);
    try {
      await authenticatedFetch(`${API_BASE_URL}/run/${runId}/cancel`, { method: "POST" });
    } catch {
      setCancelling(false);
    }
  }

  return (
    <div className="panel execution-log">
      <div className="panel-header">
        <div className="log-title-block">
          <h2>📋 Execution Log</h2>
          {runLabel && (
            <span className="log-run-label">{runLabel}</span>
          )}
        </div>
        <div className="log-meta">
          <span className="step-count">{steps.length} steps</span>
          <ConnectionBadge state={connectionState} />
          {runId && !terminalMessage && (
            <button
              className={`cancel-btn ${cancelling ? "cancel-btn-pending" : ""}`}
              onClick={handleCancel}
              disabled={cancelling}
              title="Stop the test after the current step and generate a partial report"
            >
              {cancelling ? "⏳ Cancelling…" : "⏹ Cancel Test"}
            </button>
          )}
        </div>
      </div>

      <div className="log-scroll" ref={scrollRef}>
        {steps.length === 0 && !terminalMessage && !isThinking && (
          <div className="log-empty">
            <p>Waiting for execution steps...</p>
            <p className="log-empty-hint">
              Steps will appear here in real-time as the agent interacts with the browser
            </p>
          </div>
        )}

        {Array.isArray(steps) && steps.map((step) => (
          <StepCard key={step.step_index} step={step} />
        ))}

        {/* Live thinking strip — shown while agent is planning */}
        <ThinkingCard
          text={thinkingText}
          acStep={thinkingAcStep}
          acTotal={thinkingAcTotal}
          isThinking={isThinking}
        />

        {terminalMessage && (
          <TerminalCard message={terminalMessage} />
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Individual step card with always-visible reasoning */
function StepCard({ step }: { step: WSStepMessage }) {
  const statusIcon = step.success ? "✓" : "✗";
  const statusClass = step.success ? "success" : "failure";

  return (
    <div className={`step-card ${statusClass}`}>
      <div className="step-card-header">
        <span className="step-card-num">#{step.step_index}</span>
        <span className={`step-card-status ${statusClass}`}>{statusIcon}</span>
        <span className="step-card-action">{step.action_type}</span>
        {step.locator && (
          <code className="step-card-locator">{step.locator}</code>
        )}
        <span className="step-card-time">
          {new Date(step.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {/* Reasoning — always visible */}
      {step.llm_reasoning && (
        <div className="step-card-reasoning">
          <span className="reasoning-brain">🧠</span>
          {step.llm_reasoning}
        </div>
      )}

      {step.screenshot_url && (
        <a
          href={step.screenshot_url}
          target="_blank"
          rel="noopener noreferrer"
          className="step-card-screenshot-link"
        >
          📷 View Screenshot
        </a>
      )}

      {!step.success && (
        <div className="step-card-error">Step failed</div>
      )}
    </div>
  );
}


/** Terminal status card (completion or failure) */
function TerminalCard({ message }: { message: WSTerminalMessage }) {
  const isSuccess = message.type === "completed";
  const [isAccepting, setIsAccepting] = useState(false);
  const [isAccepted, setIsAccepted] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  /**
   * Report availability state:
   *  - "checking"  : probing the backend (only when report_url is empty)
   *  - "available" : local backend report exists and is serveable
   *  - "unavailable": backend returned 404 / error (server restart, reporter failed)
   *  - "s3"        : S3 URL provided — always use that directly
   */
  const [reportState, setReportState] = useState<"checking" | "available" | "unavailable" | "s3">(
    message.report_url ? "s3" : "checking"
  );

  // Probe backend when no S3 URL is present
  useEffect(() => {
    if (message.report_url || !message.run_id) {
      return; // S3 URL present — no need to probe
    }
    const probe = async () => {
      try {
        const resp = await authenticatedFetch(`${API_BASE_URL}/runs/${message.run_id}/report`, { method: "HEAD" });
        setReportState(resp.ok ? "available" : "unavailable");
      } catch {
        setReportState("unavailable");
      }
    };
    probe();
  }, [message.run_id, message.report_url]);

  const stepsLabel =
    message.ac_steps_total > 0
      ? `${message.ac_steps_passed}/${message.ac_steps_total} AC steps passed`
      : null;

  const handleAccept = async () => {
    if (isAccepting || isAccepted) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      const resp = await authenticatedFetch(`${API_BASE_URL}/runs/${message.run_id}/accept`, {
        method: "POST",
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to accept run");
      }
      setIsAccepted(true);
    } catch (err) {
      setAcceptError(err instanceof Error ? err.message : "Accept failed");
    } finally {
      setIsAccepting(false);
    }
  };

  const tokenSuffix = VITE_API_KEY ? `?token=${encodeURIComponent(VITE_API_KEY)}` : '';
  const reportUrl = reportState === "s3"
    ? message.report_url
    : `${API_BASE_URL}/runs/${message.run_id}/report${tokenSuffix}`;

  return (
    <div className={`terminal-card ${isSuccess ? "success" : "failure"}`}>
      <div className="terminal-icon">
        {isSuccess ? "🎉" : "❌"}
      </div>
      <div className="terminal-content">
        <div className="terminal-header-row">
          <h3>{isSuccess ? "All Tests Passed" : "Test Run Failed"}</h3>
          {isSuccess && (
            <button
              className={`terminal-accept-btn ${isAccepted ? "accepted" : ""}`}
              onClick={handleAccept}
              disabled={isAccepting || isAccepted}
              title="Save this successful run as a deterministic Playwright test for future re-runs"
            >
              {isAccepting ? (
                <>
                  <span className="spinner-xs" /> Saving…
                </>
              ) : isAccepted ? (
                "⭐ Saved as Playwright Test"
              ) : (
                "💾 Save as Playwright Test"
              )}
            </button>
          )}
        </div>

        {stepsLabel && (
          <p style={{ fontSize: "0.9rem", marginBottom: "0.4rem", opacity: 0.85 }}>
            {stepsLabel}
            {message.bugs_found > 0 && ` · ${message.bugs_found} bug${message.bugs_found > 1 ? "s" : ""} found`}
          </p>
        )}

        {message.error && (
          <p className="terminal-error">{message.error}</p>
        )}

        {acceptError && (
          <p className="terminal-error" style={{ marginTop: "0.5rem" }}>
            ⚠️ {acceptError}
          </p>
        )}

        <div className="terminal-links">
          {/* Report link — disabled with tooltip if report is unavailable */}
          {reportState === "s3" || reportState === "available" ? (
            <a
              href={reportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="terminal-link report"
            >
              📄 View Audit Report
            </a>
          ) : reportState === "checking" ? (
            <span className="terminal-link report terminal-link--disabled" title="Checking report availability…">
              📄 View Audit Report
            </span>
          ) : (
            <span
              className="terminal-link report terminal-link--disabled"
              title="Report not available — the server may have restarted since this run completed, or the report was not generated. Check S3 for archived reports."
            >
              📄 View Audit Report (unavailable)
            </span>
          )}
          {message.video_url && (
            <a
              href={message.video_url}
              target="_blank"
              rel="noopener noreferrer"
              className="terminal-link video"
            >
              🎬 Download Video
            </a>
          )}
        </div>
      </div>
    </div>
  );
}


/** WebSocket connection state badge */
function ConnectionBadge({ state }: { state: WSConnectionState }) {
  const labels: Record<WSConnectionState, string> = {
    idle: "Idle",
    connecting: "Connecting...",
    connected: "Connected",
    closed: "Closed",
    error: "Error",
  };

  const classes: Record<WSConnectionState, string> = {
    idle: "badge-idle",
    connecting: "badge-connecting",
    connected: "badge-connected",
    closed: "badge-closed",
    error: "badge-error",
  };

  return (
    <span className={`connection-badge ${classes[state]}`}>
      {state === "connected" && <span className="live-dot" />}
      {labels[state]}
    </span>
  );
}
