/**
 * vQA — CompleteView Component
 * ============================
 * Module: frontend/src/components/CompleteView.tsx
 *
 * COMPLETE mode: Final results are shown.
 * StepTable with all result badges.
 * Summary row (passed/failed/skipped).
 * Actions: Run Again, View Full Report, Copy Link.
 * Inline triage for failed runs.
 *
 * Featured in Phase 6 of the TASK-065 UI/UX Overhaul.
 */

import { StepTable } from './StepTable';
import type { StepRow } from './StepTable';
import { TriagePanel } from './TriagePanel';
import type { WSTriageMessage } from '../types';

interface CompleteViewProps {
  ticket: { id: string, summary: string };
  config: { role: string, targetUrl: string };
  steps: StepRow[];
  runId: string;
  triageMessage?: WSTriageMessage | null;
  /** Overall run result from WSTerminalMessage.type — overrides step-level derivation */
  overallResult?: 'completed' | 'failed' | null;
  onRunAgain: () => void;
  onNewRun: () => void;
  onViewReport: () => void;
  onCopyLink: () => void;
  onTriageRerun: (guidance: string) => void;
  onDismissTriage: () => void;
}

export function CompleteView({
  ticket,
  config,
  steps,
  runId,
  triageMessage,
  overallResult,
  onRunAgain,
  onNewRun,
  onViewReport,
  onCopyLink,
  onTriageRerun,
  onDismissTriage
}: CompleteViewProps) {

  const passedCount = steps.filter(s => s.result === 'passed').length;
  const failedCount = steps.filter(s => s.result === 'failed').length;
  const skippedCount = steps.filter(s => s.result === 'skipped' || s.result === 'waiting').length;

  // Use terminal message overall result when available (catches failures outside named steps)
  const isSuccess = overallResult
    ? overallResult === 'completed'
    : failedCount === 0;

  return (
    <div className="complete-view">
      {/* Top Bar */}
      <div className="view-top-bar">
        <div className="top-bar-left">
          <div className={`status-indicator ${isSuccess ? 'success' : 'failure'}`}>
            <span className="status-label">
              {isSuccess ? '✅ PASSED' : '❌ FAILED'}
            </span>
          </div>
          <div className="ticket-info-mini">
            <span className="ticket-id">{ticket.id}</span>
            <span className="separator">·</span>
            <span className="config-summary">{config.role} · {config.targetUrl.replace('https://', '')}</span>
          </div>
        </div>
        
        <div className="top-bar-right">
          <button className="execute-btn primary" onClick={onViewReport}>
            View Report
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="view-content">
        <h1 className="view-title">{ticket.summary || 'Test Results'}</h1>
        
        <StepTable
          mode="complete"
          steps={steps}
        />

        {/* Summary Row */}
        <div className="summary-row">
          <div className="summary-stats">
            <span className="stat-passed">{passedCount} passed</span>
            <span className="stat-failed">{failedCount} failed</span>
            <span className="stat-skipped">{skippedCount} skipped</span>
          </div>
          <div className="summary-actions">
            <button className="btn-link" onClick={onCopyLink}>📎 Copy Link</button>
          </div>
        </div>

        {/* Complete Actions */}
        <div className="view-actions-footer">
          <div className="footer-left">
            <button className="btn-secondary" onClick={onRunAgain} title="Run again with same ticket and configuration">
              ↩ Run Again
            </button>
            <button className="btn-secondary" onClick={onNewRun} style={{ marginLeft: '12px' }}>
              ✨ Start New Run
            </button>
          </div>
          <div className="footer-right">
             <button className="execute-btn primary large" onClick={onViewReport}>
              📋 View Full Report
            </button>
          </div>
        </div>

        {/* Inline Triage Panel */}
        {triageMessage && (
          <div className="inline-triage-container">
            <h2 className="section-title">Failure Analysis</h2>
            <TriagePanel
              triage={triageMessage}
              runId={runId}
              onRerun={onTriageRerun}
              onDismiss={onDismissTriage}
            />
          </div>
        )}
      </div>
    </div>
  );
}
