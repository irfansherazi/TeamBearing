/**
 * vQA — RunningView Component
 * ===========================
 * Module: frontend/src/components/RunningView.tsx
 *
 * RUNNING mode: The test is executing live.
 * Shows the StepTable with real-time status badges.
 * Includes Agent Reasoning and Live Log accordions (collapsed by default).
 *
 * Featured in Phase 6 of the TASK-065 UI/UX Overhaul.
 */

import { useState } from 'react';
import { StepTable } from './StepTable';
import type { StepRow } from './StepTable';
import { ExecutionLog } from './ExecutionLog';
import { LiveBrowser } from './LiveBrowser';
import type { WSTerminalMessage } from '../types';

interface RunningViewProps {
  ticket: { id: string, summary: string };
  config: { role: string, targetUrl: string };
  steps: StepRow[];
  runId: string;
  isThinking: boolean;
  thinkingText: string;
  thinkingAcStep: number;
  thinkingAcTotal: number;
  terminalMessage: WSTerminalMessage | null;
  onStopTest: () => Promise<void>;
  onPauseTest: () => Promise<boolean>;
  onFalsePositive?: (index: number) => void;
  /** noVNC URL for live browser iframe (null if not in interactive mode) */
  novncUrl?: string | null;
  /** Latest base64 screenshot from the planner */
  latestScreenshot?: string;
}

export function RunningView({
  ticket,
  config,
  steps,
  runId,
  isThinking,
  thinkingText,
  thinkingAcStep,
  thinkingAcTotal,
  terminalMessage,
  onStopTest,
  onPauseTest,
  onFalsePositive,
  novncUrl,
  latestScreenshot,
}: RunningViewProps) {
  const [isStopping, setIsStopping] = useState(false);
  const [isPausing, setIsPausing] = useState(false);
  const [pauseError, setPauseError] = useState<string | null>(null);

  const handleStop = async () => {
    if (isStopping) return;
    setIsStopping(true);
    await onStopTest();
    // stays disabled until terminal message arrives and switches mode
  };

  const handlePause = async () => {
    if (isPausing || isStopping) return;
    setIsPausing(true);
    setPauseError(null);
    const ok = await onPauseTest();
    if (!ok) {
      setPauseError('Pause request failed — the run may have already ended.');
      setIsPausing(false);
    }
    // on success the parent switches uiMode → 'paused' and unmounts this component
  };

  return (
    <div className="running-view">
      {pauseError && (
        <div className="error-banner" style={{ marginBottom: '8px' }}>
          <span className="error-icon">⚠️</span>
          <span className="error-text">{pauseError}</span>
        </div>
      )}
      {/* Top Bar */}
      <div className="view-top-bar">
        <div className="top-bar-left">
          <div className="status-indicator">
            <span className="live-dot" />
            <span className="status-label">{isStopping ? 'STOPPING…' : 'EXECUTING'}</span>
          </div>
          <div className="ticket-info-mini">
            <span className="ticket-id">{ticket.id}</span>
            <span className="separator">·</span>
            <span className="config-summary">{config.role} · {config.targetUrl.replace('https://', '')}</span>
          </div>
        </div>

        <div className="top-bar-right">
          <button
            className="execute-btn secondary"
            onClick={handlePause}
            disabled={isPausing || isStopping}
            style={{ marginRight: '8px' }}
          >
            {isPausing ? '⏳ Pausing…' : '⏸ Pause'}
          </button>
          <button
            className="execute-btn danger"
            onClick={handleStop}
            disabled={isStopping || isPausing}
          >
            {isStopping ? '⏳ Stopping…' : '⏹ Stop Test'}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="view-content">
        <h1 className="view-title">{ticket.summary || 'Test in Progress'}</h1>

        {/* Live Browser Stream */}
        <LiveBrowser
          latestScreenshot={latestScreenshot || ""}
          acStep={thinkingAcStep}
          acTotal={thinkingAcTotal}
          isRunning={true}
          vncUrl={novncUrl}
        />
        
        <StepTable
          mode="running"
          steps={steps}
          onFalsePositive={onFalsePositive}
        />

        {/* Agent Reasoning Accordion */}
        <details className="view-accordion reasoning-accordion" open={isThinking}>
          <summary>
            <span className="accordion-icon">🧠</span>
            Agent Reasoning
            {isThinking && <span className="thinking-dots"><span>.</span><span>.</span><span>.</span></span>}
          </summary>
          <div className="accordion-content">
            <p className="thinking-text">
              {thinkingText || 'Waiting for agent to share thoughts...'}
              {isThinking && <span className="thinking-cursor" />}
            </p>
          </div>
        </details>

        {/* Live Log Accordion */}
        <details className="view-accordion log-accordion">
          <summary>
            <span className="accordion-icon">📜</span>
            Live Log
          </summary>
          <div className="accordion-content log-container">
            <ExecutionLog
              runId={runId}
              runLabel={ticket.id}
              steps={[]} // steps handled by StepTable now
              terminalMessage={terminalMessage}
              connectionState="connected"
              isThinking={isThinking}
              thinkingText={thinkingText}
              thinkingAcStep={thinkingAcStep}
              thinkingAcTotal={thinkingAcTotal}
            />
          </div>
        </details>
      </div>
    </div>
  );
}
