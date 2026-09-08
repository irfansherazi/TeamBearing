/**
 * TriagePanel — Failure Analysis Display + Guidance Input
 * =========================================================
 * Shown when a test run fails and the LLM triage analysis is available.
 *
 * Displays:
 *  - Overall classification badge (Product Bug / Jira Unclear / Mixed)
 *  - Executive summary for the product team
 *  - Per-step breakdown with color-coded badges + reasoning
 *  - Guidance text input for providing additional context
 *  - Action buttons: Re-run with Guidance | Post to Jira | Dismiss
 */

import { useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { API_BASE_URL } from "../types";
import type { WSTriageMessage } from "../types";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const OVERALL_CONFIG = {
  product_bug: {
    icon: "🐛",
    label: "Product Bug",
    cls: "triage-badge-product-bug",
    desc: "The application doesn't behave as specified in the acceptance criteria.",
  },
  agent_issue: {
    icon: "📝",
    label: "Jira Card Unclear",
    cls: "triage-badge-agent-issue",
    desc: "The Jira AC is ambiguous or missing detail — the agent couldn't interpret it.",
  },
  mixed: {
    icon: "⚠️",
    label: "Mixed (Bug + Clarity)",
    cls: "triage-badge-mixed",
    desc: "Some steps failed due to product bugs, others due to unclear acceptance criteria.",
  },
  unknown: {
    icon: "❓",
    label: "Could Not Determine",
    cls: "triage-badge-unknown",
    desc: "The analysis could not confidently classify the failure.",
  },
} as const;

const STEP_CONFIG = {
  product_bug: { icon: "🐛", label: "Product Bug", cls: "triage-step-product-bug" },
  agent_issue: { icon: "📝", label: "Jira Unclear", cls: "triage-step-agent-issue" },
  passed: { icon: "✅", label: "Passed", cls: "triage-step-passed" },
} as const;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TriagePanelProps {
  triage: WSTriageMessage;
  runId: string;
  /** Called when user clicks "Re-run with Guidance" */
  onRerun: (guidance: string) => void;
  /** Called when user clicks "Dismiss" */
  onDismiss: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TriagePanel({ triage, runId, onRerun, onDismiss }: TriagePanelProps) {
  const [guidance, setGuidance] = useState("");
  const [posting, setPosting] = useState(false);
  const [posted, setPosted] = useState(false);
  const [postError, setPostError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const overall = OVERALL_CONFIG[triage.overall] ?? OVERALL_CONFIG.unknown;

  // Post triage to Jira
  const handlePostToJira = async () => {
    setPosting(true);
    setPostError("");
    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/run/${runId}/post-to-jira`, {
        method: "POST",
      });
      if (res.ok) {
        setPosted(true);
      } else {
        const data = await res.json().catch(() => ({}));
        setPostError(data.detail ?? "Failed to post to Jira");
      }
    } catch {
      setPostError("Network error — could not reach the API");
    } finally {
      setPosting(false);
    }
  };

  return (
    <div className="triage-panel">
      {/* Header */}
      <div className="triage-panel-header">
        <div className="triage-panel-title-row">
          <span className="triage-panel-icon">🔍</span>
          <h3 className="triage-panel-title">Failure Triage</h3>
          <button className="triage-dismiss-btn" onClick={onDismiss} title="Dismiss">
            ×
          </button>
        </div>

        {/* Overall badge */}
        <div className={`triage-overall-badge ${overall.cls}`}>
          <span className="triage-overall-icon">{overall.icon}</span>
          <span className="triage-overall-label">{overall.label}</span>
        </div>

        {/* Summary */}
        <p className="triage-summary">{triage.summary}</p>
      </div>

      {/* Per-step breakdown */}
      {Array.isArray(triage.steps) && triage.steps.length > 0 && (
        <div className="triage-steps">
          <div className="triage-steps-label">Failed Step Analysis</div>
          {triage.steps.map((step, i) => {
            const cfg = STEP_CONFIG[step.classification] ?? STEP_CONFIG.agent_issue;
            return (
              <div key={i} className={`triage-step-row ${cfg.cls}`}>
                <div className="triage-step-header">
                  <span className="triage-step-badge">
                    {cfg.icon} {cfg.label}
                  </span>
                  <span className="triage-step-confidence">{step.confidence} confidence</span>
                  <span className="triage-step-num">Step {step.ac_index + 1}</span>
                </div>
                <div className="triage-step-ac">{step.ac_step}</div>
                <div className="triage-step-reason">{step.reason}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Guidance input */}
      <div className="triage-guidance">
        <label className="triage-guidance-label" htmlFor="triage-guidance-input">
          💬 Provide guidance for re-run
          <span className="triage-guidance-hint">
            Explain how to complete this test step — the agent will use this on the next run
          </span>
        </label>
        <textarea
          id="triage-guidance-input"
          ref={textareaRef}
          className="triage-guidance-textarea"
          rows={4}
          placeholder={
            overall.cls === "triage-badge-agent-issue" || overall.cls === "triage-badge-mixed"
              ? "e.g. To create a new order, click 'New Request +' in the top-left sidebar, then select Radio Commercial from the Ad Type dropdown..."
              : "e.g. This step requires the user to be logged in as an Account Executive. The inline edit button appears on hover over the spot title cell..."
          }
          value={guidance}
          onChange={(e) => setGuidance(e.target.value)}
        />
      </div>

      {/* Action buttons */}
      <div className="triage-actions">
        <button
          className="triage-btn triage-btn-rerun"
          onClick={() => onRerun(guidance)}
          title="Re-run the test with your guidance injected into the agent context"
        >
          ▶ Re-run with Guidance
        </button>

        {posted ? (
          <span className="triage-posted-badge">✓ Posted to Jira</span>
        ) : (
          <button
            className="triage-btn triage-btn-jira"
            onClick={handlePostToJira}
            disabled={posting}
            title="Post the failure analysis as a comment to the Jira ticket"
          >
            {posting ? <span className="spinner-xs" /> : null}
            {posting ? "Posting…" : "Post to Jira"}
          </button>
        )}

        <button className="triage-btn triage-btn-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </div>

      {postError && <div className="triage-post-error">⚠ {postError}</div>}
    </div>
  );
}
