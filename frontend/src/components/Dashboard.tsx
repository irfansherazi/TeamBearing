/**
 * vQA — Dashboard Component
 * ===========================
 * Three-tab layout:
 *
 *   ▶ Run Test    — execution panel + live browser + execution log + recent results
 *   📚 Archive    — full S3 reports history browser (grouped by ticket or timeline)
 *   📊 Analytics  — pass rate, cost trends, top tickets (Phase 6A)
 *
 * On failed runs: a TriagePanel appears with the failure analysis and
 * guidance input. The user can re-run with guidance or post to Jira.
 */

import { useCallback, useEffect, useState } from "react";
import type { ExecuteRequest, WSHumanTakeoverMessage, WSPersonaCredentialsMessage, WSTriageMessage } from "../types";
import { useExecution } from "../hooks/useExecution";
import { useWebSocket } from "../hooks/useWebSocket";
import { ExecutionPanel } from "./ExecutionPanel";
import { ExecutionLog } from "./ExecutionLog";
import { ReportsHistory } from "./ReportsHistory";
import { ReportsArchive } from "./ReportsArchive";
import { TriagePanel } from "./TriagePanel";
import { TakeoverPanel } from "./TakeoverPanel";
import PersonaCredentialPanel from "./PersonaCredentialPanel";
import CopilotSidebar from "./CopilotSidebar";
import { AnalyticsDashboard } from "./AnalyticsDashboard";
import { GlobalHitlBanner } from "./GlobalHitlBanner";
import { useAuth } from "../auth/useAuth";
import { ErrorBoundary } from "./ErrorBoundary";
import { ProductSelector } from "./ProductSelector";

type Tab = "run" | "archive" | "analytics";

export function Dashboard() {
  const { logout } = useAuth();
  const {
    isLoading,
    error,
    executeResponse,
    healthResponse,
    startExecution,
    checkHealth,
    checkTicketCredentials,
    resetRun,
  } = useExecution();

  const {
    connectionState,
    steps,
    terminalMessage,
    latestScreenshot,
    isThinking,
    thinkingText,
    thinkingAcStep,
    thinkingAcTotal,
    triageMessage,
    humanTakeoverMessage,
    hitlScreenshot,
    hitlActions,
    hitlDialog,
    personaCredentialsMessage,
    wsSocket,
    connect: wsConnect,
    resetState: wsReset,
  } = useWebSocket();

  const [activeTab, setActiveTab] = useState<Tab>("run");
  const [isRunning, setIsRunning] = useState(false);
  const [rerunTicket, setRerunTicket] = useState<{ ticketId: string; role: string } | null>(null);
  const [reportsTick, setReportsTick] = useState(0);
  const [activeTriage, setActiveTriage] = useState<WSTriageMessage | null>(null);
  const [activeTakeover, setActiveTakeover] = useState<WSHumanTakeoverMessage | null>(null);
  const [activePersonaCredentials, setActivePersonaCredentials] = useState<WSPersonaCredentialsMessage | null>(null);
  const [showTakeoverModal, setShowTakeoverModal] = useState(false);

  // Pending re-run guidance (set when user clicks "Re-run with Guidance" from triage)
  const [pendingGuidance, setPendingGuidance] = useState("");

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  useEffect(() => {
    if (terminalMessage) {
      setIsRunning(false);
      setReportsTick((t) => t + 1);
    }
  }, [terminalMessage]);

  // Show triage panel when we receive a triage message
  useEffect(() => {
    if (triageMessage) {
      setActiveTriage(triageMessage);
    }
  }, [triageMessage]);

  // Show takeover panel when agent gets stuck
  useEffect(() => {
    if (humanTakeoverMessage) {
      setActiveTakeover(humanTakeoverMessage);
      setShowTakeoverModal(true);
    }
  }, [humanTakeoverMessage]);

  // Show persona credential panel when agent needs credentials for unknown persona
  useEffect(() => {
    if (personaCredentialsMessage) {
      setActivePersonaCredentials(personaCredentialsMessage);
    }
  }, [personaCredentialsMessage]);

  // Fired when the user picks a new ticket or clears the current one.
  // Resets all run state so the log/report area goes back to idle.
  const handleNewRun = useCallback(() => {
    if (isRunning) return; // don't wipe a live run mid-execution
    wsReset();
    resetRun();
    setIsRunning(false);
    setActiveTriage(null);
    setActiveTakeover(null);
    setActivePersonaCredentials(null);
    setPendingGuidance("");
  }, [isRunning, wsReset, resetRun]);

  const handleExecute = useCallback(
    async (request: ExecuteRequest) => {
      setRerunTicket(null);
      setActiveTriage(null);
      setPendingGuidance("");
      const response = await startExecution(request);
      if (response) {
        setIsRunning(true);
        wsConnect(response.run_id);
      }
    },
    [startExecution, wsConnect],
  );

  const handleRerun = useCallback(
    (ticketId: string, role: string) => {
      setRerunTicket({ ticketId, role });
      setActiveTriage(null);
      setActiveTab("run");
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [],
  );

  // Called from TriagePanel "Re-run with Guidance" button
  const handleTriageRerun = useCallback(
    (guidance: string) => {
      if (!executeResponse) return;
      // Store guidance for ExecutionPanel to inject on next run
      setPendingGuidance(guidance);
      setActiveTriage(null);
      // Trigger re-run by setting rerunTicket — ExecutionPanel will pick this up
      // We don't have the ticket/role stored, but ExecutionPanel pre-fills from last run
      setRerunTicket(null); // let ExecutionPanel re-use its current values
      setActiveTab("run");
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [executeResponse],
  );

  const activeRunLabel = executeResponse?.run_label ?? executeResponse?.run_id ?? null;

  return (
    <div className="dashboard">
      <GlobalHitlBanner
        isVisible={!!activeTakeover}
        stepText={activeTakeover?.ac_step ?? ""}
        onClick={() => setShowTakeoverModal(true)}
      />

      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="dashboard-header">
        <div className="header-left">
          <h1 className="app-title">
            <span className="app-icon">🔬</span>
            vQA
          </h1>
          <span className="app-subtitle">Autonomous QA Agent</span>
        </div>

        {/* Product Selector — between header-left and dashboard-tabs (Creative Q1) */}
        <ProductSelector />

        {/* Tab navigation */}
        <nav className="dashboard-tabs">
          <button
            className={`dash-tab ${activeTab === "run" ? "active" : ""}`}
            onClick={() => setActiveTab("run")}
          >
            ▶ Run Test
            {isRunning && <span className="dash-tab-dot" />}
          </button>
          <button
            className={`dash-tab ${activeTab === "archive" ? "active" : ""}`}
            onClick={() => setActiveTab("archive")}
          >
            📚 Reports Archive
          </button>
          <button
            className={`dash-tab ${activeTab === "analytics" ? "active" : ""}`}
            onClick={() => setActiveTab("analytics")}
          >
            📊 Analytics
          </button>
        </nav>

        <div className="header-right">
          {activeRunLabel && activeTab === "run" && (
            <div className="active-run-label">
              <span className="active-run-dot" />
              {activeRunLabel}
            </div>
          )}
          <HealthBadge health={healthResponse} />
          <button 
            onClick={logout}
            className="health-badge"
            style={{ 
              marginLeft: '10px',
              cursor: 'pointer',
              border: '1px solid var(--border)',
              background: 'var(--bg-tertiary)',
              color: 'var(--text-secondary)',
              transition: 'all var(--transition-fast)'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.color = 'var(--text-primary)';
              e.currentTarget.style.borderColor = 'var(--accent)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.color = 'var(--text-secondary)';
              e.currentTarget.style.borderColor = 'var(--border)';
            }}
          >
            Logout
          </button>
        </div>
      </header>

      {/* ── Error Banner ───────────────────────────────────────────── */}
      {error && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{error}</span>
        </div>
      )}

      {/* ── Tab: Run Test ──────────────────────────────────────────── */}
      {activeTab === "run" && (
        <ErrorBoundary onReset={() => window.location.reload()}>
          <div className="dashboard-grid">
            <div className="dashboard-sidebar">
              <ExecutionPanel
                onExecute={handleExecute}
                isLoading={isLoading}
                isRunning={isRunning}
                onCheckCredentials={checkTicketCredentials}
                rerunTicket={rerunTicket}
                pendingGuidance={pendingGuidance}
                onGuidanceConsumed={() => setPendingGuidance("")}
                onNewRun={handleNewRun}
              />
            </div>

            <div className="dashboard-main">
              {/* ── AC Steps Progress (replaces LiveBrowser) ─────── */}
              <CopilotSidebar
                runId={executeResponse?.run_id ?? ""}
                ticketId={executeResponse?.run_label?.split(" · ")[0] ?? ""}
                ws={wsSocket}
                inline={true}
                onResumed={() => {
                  setActiveTakeover(null);
                  setShowTakeoverModal(false);
                }}
              />
              <ExecutionLog
                runId={executeResponse?.run_id || null}
                runLabel={activeRunLabel}
                steps={steps}
                terminalMessage={terminalMessage}
                connectionState={connectionState}
                isThinking={isThinking}
                thinkingText={thinkingText}
                thinkingAcStep={thinkingAcStep}
                thinkingAcTotal={thinkingAcTotal}
              />

            </div>
          </div>

          {/* Triage Panel — shown after failure analysis arrives */}
          {activeTriage && executeResponse && (
            <div className="dashboard-triage">
              <TriagePanel
                triage={activeTriage}
                runId={executeResponse.run_id}
                onRerun={handleTriageRerun}
                onDismiss={() => setActiveTriage(null)}
              />
            </div>
          )}

          {/* Persona Credential Panel — shown when HITL needs creds for unknown persona */}
          {activePersonaCredentials && (
            <div className="dashboard-persona-creds" role="region" aria-label="Persona credential input">
              <PersonaCredentialPanel
                message={activePersonaCredentials}
                onSubmitted={() => setActivePersonaCredentials(null)}
                onDismiss={() => setActivePersonaCredentials(null)}
              />
            </div>
          )}

          {/* Recent results — only shown on Run tab */}
          <div className="dashboard-reports">
            <ReportsHistory onRerun={handleRerun} refreshTick={reportsTick} />
          </div>

          {/* HITL Takeover Modal (TASK-085) */}
          {showTakeoverModal && activeTakeover && executeResponse && (
            <div className="takeover-overlay" onClick={() => setShowTakeoverModal(false)}>
              <div onClick={(e) => e.stopPropagation()}>
                <TakeoverPanel
                  runId={executeResponse.run_id}
                  acStep={activeTakeover.ac_step}
                  acStepIndex={activeTakeover.ac_step_index}
                  errorMessage={activeTakeover.error_message}
                  screenshotB64={latestScreenshot}
                  hitlScreenshot={hitlScreenshot}
                  hitlActions={hitlActions}
                  hitlDialog={hitlDialog}
                  vncUrl={activeTakeover.novnc_url}
                  onDone={() => {
                    setActiveTakeover(null);
                    setShowTakeoverModal(false);
                  }}
                  onMinimize={() => setShowTakeoverModal(false)}
                />
              </div>
            </div>
          )}
        </ErrorBoundary>
      )}

      {/* ── Tab: Reports Archive ────────────────────────────────────── */}
      {activeTab === "archive" && (
        <ErrorBoundary onReset={() => setActiveTab("run")}>
          <div className="dashboard-archive">
            <ReportsArchive onRerun={handleRerun} />
          </div>
        </ErrorBoundary>
      )}

      {/* ── Tab: Analytics (Phase 6A) ──────────────────────────────── */}
      {activeTab === "analytics" && (
        <ErrorBoundary onReset={() => setActiveTab("run")}>
          <div className="dashboard-archive">
            <AnalyticsDashboard />
          </div>
        </ErrorBoundary>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Sub-component: Health Badge
// ---------------------------------------------------------------------------

interface HealthBadgeProps {
  health: {
    status: string;
    checks: { jira: string; s3: string; bedrock: string };
  } | null;
}

function HealthBadge({ health }: HealthBadgeProps) {
  if (!health) return <span className="health-badge offline">● Connecting…</span>;
  const isOk = health.status === "ok";
  return (
    <span className={`health-badge ${isOk ? "healthy" : "degraded"}`}>
      {isOk ? "● All Systems Go" : "● Degraded"}
    </span>
  );
}
