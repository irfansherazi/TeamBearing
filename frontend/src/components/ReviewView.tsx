/**
 * vQA — ReviewView Component
 * ===========================
 * Module: frontend/src/components/ReviewView.tsx
 *
 * REVIEW mode: The user reviews and edits the parsed AC steps.
 * Top bar shows ticket info, quality badge, and "Start Test" button.
 * Main area shows the StepTable in review mode.
 *
 * Featured in Phase 6 of the TASK-065 UI/UX Overhaul.
 */

import { useState } from 'react';
import { StepTable } from './StepTable';
import type { StepRow } from './StepTable';

interface ReviewViewProps {
  ticket: { id: string, summary: string };
  config: { role: string, targetUrl: string, preParseGuidance?: string };
  steps: StepRow[];
  isLoading: boolean;
  parseQuality?: string | null;
  rawAc?: string;
  onRecordDemo?: () => void;
  onEditStep: (id: string, text: string) => void;
  onRemoveStep: (id: string) => void;
  onReorderSteps: (draggedId: string, overId: string) => void;
  onAddStep: (text: string) => void;
  onStartTest: (guidance: string) => void;
  onBack: () => void;
  actionLabel?: string;
  isPaused?: boolean;
  hasGhostDescription?: boolean;
  ghostEmail?: string;
  ghostPassword?: string;
  onGhostEmailChange?: (email: string) => void;
  onGhostPasswordChange?: (password: string) => void;
  hasGhostLogin?: boolean;
  ghostAdminEmail?: string;
  ghostAdminPassword?: string;
  onGhostAdminEmailChange?: (email: string) => void;
  onGhostAdminPasswordChange?: (password: string) => void;
}

export function ReviewView({
  ticket,
  config,
  steps,
  isLoading,
  parseQuality,
  rawAc,
  onRecordDemo,
  onEditStep,
  onRemoveStep,
  onReorderSteps,
  onAddStep,
  onStartTest,
  onBack,
  actionLabel = 'Start Test',
  isPaused = false,
  hasGhostDescription = false,
  ghostEmail = '',
  ghostPassword = '',
  onGhostEmailChange,
  onGhostPasswordChange,
  hasGhostLogin = false,
  ghostAdminEmail = '',
  ghostAdminPassword = '',
  onGhostAdminEmailChange,
  onGhostAdminPasswordChange,
}: ReviewViewProps) {
  
  const [prevTicketId, setPrevTicketId] = useState(ticket.id);
  const [prevPreParseGuidance, setPrevPreParseGuidance] = useState(config?.preParseGuidance || '');
  const [guidance, setGuidance] = useState(config?.preParseGuidance || '');
  const [showAc, setShowAc] = useState(false);

  const currentPreParseGuidance = config?.preParseGuidance || '';

  if (ticket.id !== prevTicketId || currentPreParseGuidance !== prevPreParseGuidance) {
    setPrevTicketId(ticket.id);
    setPrevPreParseGuidance(currentPreParseGuidance);
    setGuidance(currentPreParseGuidance);
  }

  const adminCredsRequired = hasGhostLogin && !isPaused;
  const adminCredsReady = !adminCredsRequired || (ghostAdminEmail.trim() !== '' && ghostAdminPassword.trim() !== '');
  // Suppress ghost-description gate when a GHOST_LOGIN step is present — the admin credentials gate takes precedence.
  const descCredsRequired = hasGhostDescription && !isPaused && !adminCredsRequired;
  const descCredsReady = !descCredsRequired || (ghostEmail.trim() !== '' && ghostPassword.trim() !== '');

  const handleStart = () => {
    onStartTest(guidance);
  };

  const qualityLabel = parseQuality?.toUpperCase() || 'UNKNOWN';
  const qualityClass = `quality-${parseQuality || 'unknown'}`;

  return (
    <div className={`review-view ${isPaused ? 'paused-mode' : ''}`}>
      {/* Top Bar */}
      <div className="view-top-bar">
        <div className="top-bar-left">
          <button className="back-btn" onClick={onBack} title="Change Ticket">
            ←
          </button>
          <div className="ticket-info-mini">
            <span className="ticket-id">{ticket.id}</span>
            <span className="separator">·</span>
            <span className="config-summary">{config.role} · {config.targetUrl.replace('https://', '')}</span>
          </div>
        </div>
        
        <div className="top-bar-right">
          {isPaused ? (
            <div className="paused-indicator">⏸ PAUSED</div>
          ) : (
            <div className={`quality-badge ${qualityClass}`}>
              ● {qualityLabel}
            </div>
          )}
          <button
            className="execute-btn primary"
            onClick={handleStart}
            disabled={isLoading || steps.length === 0 || !descCredsReady || !adminCredsReady}
            title={!descCredsReady || !adminCredsReady ? 'Enter required credentials below to unlock' : undefined}
          >
            {isLoading ? 'Wait...' : actionLabel}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="view-content">
        <h1 className="view-title">
          {isPaused ? 'Modify Steps & Resume' : (ticket.summary || 'Acceptance Criteria Review')}
        </h1>

        {!isPaused && parseQuality === 'degraded' && (
          <div className="step-preview-warning poor">
            <strong>⚠️ Degraded AC Parsing</strong>
            <p>The structured parser failed and fell back to basic parsing — steps may be incomplete or inaccurate.</p>
            <div className="hint">Steps were recovered but structured data is unavailable. Please review and refine them, or record a demo to show the agent exactly what to test.</div>
            {onRecordDemo && (
              <button type="button" className="btn-record-demo" onClick={onRecordDemo}>
                Record Demo
              </button>
            )}
          </div>
        )}

        {!isPaused && (parseQuality === 'poor' || parseQuality === 'fair') && (
          <div className="step-preview-warning poor">
            <strong>⚠️ Low Quality Acceptance Criteria</strong>
            <p>The steps below were generated but may be too vague to succeed.</p>
            <div className="hint">Please refine them, or record a demo to show the agent exactly what to test.</div>
            {onRecordDemo && (
              <button type="button" className="btn-record-demo" onClick={onRecordDemo}>
                Record Demo
              </button>
            )}
          </div>
        )}

        {rawAc && (
          <div className="review-ac-accordion">
            <button
              type="button"
              className="review-ac-toggle"
              onClick={() => setShowAc((v) => !v)}
            >
              <span>{showAc ? '▾' : '▸'} Jira Acceptance Criteria</span>
              <span className="review-ac-toggle-hint">{showAc ? 'hide' : 'show original'}</span>
            </button>
            {showAc && (
              <pre className="review-ac-text">{rawAc}</pre>
            )}
          </div>
        )}

        {descCredsRequired && (
          <div className="ghost-creds-gate">
            <div className="ghost-creds-gate__header">
              <span className="ghost-creds-gate__icon" aria-hidden="true">👻</span>
              <span className="ghost-creds-gate__title">Login Credentials Required</span>
              <span className="ghost-creds-gate__badge">Ghost detected in description</span>
            </div>
            <p className="ghost-creds-gate__desc">
              &ldquo;Ghost&rdquo; was detected in the Jira description. Provide the login credentials for this test — they will override stored role credentials and skip the preflight auth check.
            </p>
            <div className="ghost-creds-gate__fields">
              <div className="form-group">
                <label htmlFor="ghost-desc-email" className="ghost-creds-gate__label">Email</label>
                <input
                  id="ghost-desc-email"
                  type="email"
                  className="form-input"
                  value={ghostEmail}
                  onChange={(e) => onGhostEmailChange?.(e.target.value)}
                  placeholder="user@vpromedia.com"
                  autoComplete="username"
                />
              </div>
              <div className="form-group">
                <label htmlFor="ghost-desc-password" className="ghost-creds-gate__label">Password</label>
                <input
                  id="ghost-desc-password"
                  type="password"
                  className="form-input"
                  value={ghostPassword}
                  onChange={(e) => onGhostPasswordChange?.(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
              </div>
            </div>
            {descCredsReady && (
              <p className="ghost-creds-gate__ready">✅ Login credentials set — Start Test is unlocked</p>
            )}
          </div>
        )}

        {adminCredsRequired && (
          <div className="ghost-creds-gate">
            <div className="ghost-creds-gate__header">
              <span className="ghost-creds-gate__icon" aria-hidden="true">👤</span>
              <span className="ghost-creds-gate__title">Admin Credentials Required</span>
              <span className="ghost-creds-gate__badge">Ghost Login step detected</span>
            </div>
            <p className="ghost-creds-gate__desc">
              This test plan contains a Ghost Login step. Provide Admin credentials now so the agent can impersonate the target user without pausing mid-run.
            </p>
            <div className="ghost-creds-gate__fields">
              <div className="form-group">
                <label htmlFor="ghost-admin-email" className="ghost-creds-gate__label">Admin Email</label>
                <input
                  id="ghost-admin-email"
                  type="email"
                  className="form-input"
                  value={ghostAdminEmail}
                  onChange={(e) => onGhostAdminEmailChange?.(e.target.value)}
                  placeholder="admin@vpromedia.com"
                  autoComplete="username"
                />
              </div>
              <div className="form-group">
                <label htmlFor="ghost-admin-password" className="ghost-creds-gate__label">Password</label>
                <input
                  id="ghost-admin-password"
                  type="password"
                  className="form-input"
                  value={ghostAdminPassword}
                  onChange={(e) => onGhostAdminPasswordChange?.(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
              </div>
            </div>
            {adminCredsReady && (
              <p className="ghost-creds-gate__ready">✅ Admin credentials set — Start Test is unlocked</p>
            )}
          </div>
        )}

        <StepTable
          mode="review"
          steps={steps}
          onEdit={onEditStep}
          onRemove={onRemoveStep}
          onReorder={onReorderSteps}
          onAddStep={onAddStep}
        />

        {!isPaused && (
          <div className="form-group review-guidance-group" style={{ marginTop: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <label htmlFor="pre-parse-guidance" style={{ margin: 0, fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Additional Context (Pre-Parse Guidance)
              </label>
              <span 
                className="char-counter" 
                style={{ 
                  fontSize: '0.75rem', 
                  color: 'var(--text-hint)' 
                }}
              >
                {guidance.length}/2000 characters
              </span>
            </div>
            <textarea
              id="pre-parse-guidance"
              className="guidance-textarea"
              placeholder="e.g. This ticket tests Compact view. There are no column headers — use the Sort By dropdown for all sorting."
              value={guidance}
              onChange={(e) => setGuidance(e.target.value)}
              maxLength={2000}
              rows={3}
            />
          </div>
        )}

        <div className="view-actions-footer">
          <button className="btn-secondary" onClick={onBack}>
            ← Change Ticket
          </button>
          <div className="view-actions-footer-right">
            {!isPaused && onRecordDemo && (
              <button type="button" className="btn-record-demo" onClick={onRecordDemo}>
                Record a Demo
              </button>
            )}
            <button
              className="execute-btn primary large"
              onClick={handleStart}
              disabled={isLoading || steps.length === 0 || !descCredsReady}
              title={!descCredsReady ? 'Enter required credentials above to unlock' : undefined}
            >
              {isPaused ? '▶ Resume Test' : '▶ Start Test'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
