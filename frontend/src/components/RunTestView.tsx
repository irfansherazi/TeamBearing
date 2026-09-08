/**
 * vQA — RunTestView Component
 * ===========================
 * Module: frontend/src/components/RunTestView.tsx
 *
 * This component manages the "Run a Test" workflow using a state machine
 * with 4 primary modes:
 *
 * 1. SELECT   — User picks a ticket and configures the run.
 * 2. REVIEW   — User reviews and edits the parsed AC steps.
 * 3. RUNNING  — The test is executing live; results stream in.
 * 4. COMPLETE — Final results are shown with summary and triage.
 *
 * Migrated from Dashboard.tsx as part of the TASK-065 UI/UX Overhaul.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { RoleKey, WSGhostCredentialsMessage, WSHumanTakeoverMessage, WSPersonaCredentialsMessage, WSTriageMessage, PlaywrightTest } from "../types";
import { useExecution } from "../hooks/useExecution";
import { useWebSocket } from "../hooks/useWebSocket";
import { useProductContext } from "../context/ProductContext";
import { ErrorBoundary } from "./ErrorBoundary";
import { TakeoverPanel } from "./TakeoverPanel";
import PersonaCredentialPanel from "./PersonaCredentialPanel";
import GhostCredentialPanel from "./GhostCredentialPanel";
import CustomCredentialPanel from "./CustomCredentialPanel";

import { SelectView } from "./SelectView";
import { ReviewView } from "./ReviewView";
import { RunningView } from "./RunningView";
import { CompleteView } from "./CompleteView";
import { RecordDemoModal } from "./RecordDemoModal";
import { SaveAsTestDialog } from "./SaveAsTestDialog";
import { API_BASE_URL } from "../types";
import { authenticatedFetch, VITE_API_KEY } from "../api_client";
import type { StepRow } from "./StepTable";

type UIMode = 'select' | 'review' | 'running' | 'paused' | 'complete';

interface RunConfig {
  role: RoleKey;
  targetUrl: string;
  expectLoginFailure: boolean;
  useCustomCreds: boolean;
  customEmail?: string;
  customPassword?: string;
  preParseGuidance?: string;
}

function mapRoleToPlaywrightUser(role: RoleKey): string {
  switch (role) {
    case "account_executive":
    case "sales_manager":
    case "sales_assistant":
    case "vpromotions_user":
      return "DemoSalesExec";
    case "production_manager":
    case "producer":
      return "DemoProdMan";
    case "gm_gsm":
      return "DemoGM";
    case "digital_director":
      return "DemoDigitalDir";
    case "demo_prod_director":
    case "dubber":
      return "DemoProdDirector";
    default:
      return "DemoSalesExec";
  }
}

function mapUrlToPlaywrightEnv(targetUrl: string): "prod" | "test" | "smoke" | "qa" {
  if (targetUrl.includes("two-test")) {
    return "test";
  } else if (targetUrl.includes("two-dev")) {
    return "qa";
  } else if (targetUrl.includes("qa.vcreative") || targetUrl.includes("qa-")) {
    return "qa";
  } else if (targetUrl.includes("smoke")) {
    return "smoke";
  } else if (targetUrl.includes("vcreative.net") && !targetUrl.includes("two-")) {
    return "prod";
  }
  return "test"; // fallback
}

export function RunTestView() {
  const { activeSlug: productSlug } = useProductContext();

  const {
    isLoading,
    error,
    executeResponse,
    startComputerUseExecution,
    checkHealth,
    checkTicketCredentials,
    pauseExecution,
    resumeExecution,
    resetRun,
  } = useExecution();

  const {
    acProgress,
    terminalMessage,
    latestScreenshot,
    isThinking,
    thinkingText,
    thinkingAcStep,
    thinkingAcTotal,
    triageMessage,
    humanTakeoverMessage,
    personaCredentialsMessage,
    ghostCredentialsMessage,
    wsSocket,
    connect: wsConnect,
    resetState: wsReset,
  } = useWebSocket();

  const [uiMode, setUiMode] = useState<UIMode>('select');
  const [selectedTicket, setSelectedTicket] = useState<{id: string, summary: string} | null>(null);
  const [runConfig, setRunConfig] = useState<RunConfig | null>(null);
  const [previewSteps, setPreviewSteps] = useState<StepRow[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [parseQuality, setParseQuality] = useState<string | null>(null);
  const [rawAc, setRawAc] = useState<string>("");
  const [showRecordDemoModal, setShowRecordDemoModal] = useState(false);
  // Post-CU-run prompt: "save this run as a Playwright test?" opens after
  // a Computer-Use loop returns terminal_status="done". Static-Playwright
  // runs don't set this — there's nothing to codegen from those.
  const [showSaveAsTestDialog, setShowSaveAsTestDialog] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string>("");
  const [novncUrl, setNovncUrl] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const [activeTriage, setActiveTriage] = useState<WSTriageMessage | null>(null);
  const [activeTakeover, setActiveTakeover] = useState<WSHumanTakeoverMessage | null>(null);
  const [activePersonaCredentials, setActivePersonaCredentials] = useState<WSPersonaCredentialsMessage | null>(null);
  const [activeGhostCredentials, setActiveGhostCredentials] = useState<WSGhostCredentialsMessage | null>(null);
  const [showCustomCredsPrompt, setShowCustomCredsPrompt] = useState(false);

  // Ghost Login pre-flight credential gate (GHOST_LOGIN AC step → admin impersonation)
  const [hasGhostLogin, setHasGhostLogin] = useState(false);
  const [ghostAdminEmail, setGhostAdminEmail] = useState("");
  const [ghostAdminPassword, setGhostAdminPassword] = useState("");

  // Ghost description credential gate ("ghost" in Jira description → override test login creds)
  const [hasGhostDescription, setHasGhostDescription] = useState(false);
  const [ghostEmail, setGhostEmail] = useState("");
  const [ghostPassword, setGhostPassword] = useState("");

  // Jira comment awaiting user confirmation
  const [pendingJiraComment, setPendingJiraComment] = useState<{ticketId: string; comment: string} | null>(null);

  // True while a static Playwright test is running — prevents acProgress from
  // overwriting the Jira AC steps we fetched for display.
  const isStaticRunRef = useRef(false);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  // State transitions based on execution events
  useEffect(() => {
    if (terminalMessage) {
      // Update step results from the terminal message.
      // For static Playwright runs, acProgress events don't fire so steps
      // remain 'waiting'. Derive final results from the terminal outcome.
      setPreviewSteps(prev => {
        const hasAnyResults = prev.some(s => s.result === 'passed' || s.result === 'failed');
        if (hasAnyResults) {
          // AI agent flow already populated results via acProgress — keep them
          return prev;
        }
        // Static test flow: mark steps based on terminal message
        const isSuccess = terminalMessage.type === 'completed';
        const passedCount = terminalMessage.ac_steps_passed ?? (isSuccess ? prev.length : 0);
        return prev.map((step, idx) => ({
          ...step,
          result: (idx < passedCount ? 'passed' : (isSuccess ? 'passed' : 'failed')) as StepRow['result']
        }));
      });
      setUiMode('complete');

      // Save-as-Playwright-test prompt: only for successful Computer-Use runs.
      // Static Playwright runs are already Playwright tests, so nothing to save;
      // failed/stuck CU runs would produce a broken spec, so the backend rejects
      // those with 409 anyway. Gate on both conditions here to avoid showing
      // the modal in cases where Save would just fail.
      if (
        terminalMessage.type === 'completed' &&
        activeRunId &&
        !isStaticRunRef.current
      ) {
        setShowSaveAsTestDialog(true);
      }
    }
  }, [terminalMessage, activeRunId]);

  useEffect(() => {
    if (triageMessage) {
      setActiveTriage(triageMessage);
    }
  }, [triageMessage]);

  useEffect(() => {
    if (humanTakeoverMessage) {
      setActiveTakeover(humanTakeoverMessage);
    }
  }, [humanTakeoverMessage]);

  useEffect(() => {
    if (personaCredentialsMessage) {
      setActivePersonaCredentials(personaCredentialsMessage);
    }
  }, [personaCredentialsMessage]);

  useEffect(() => {
    if (ghostCredentialsMessage) {
      setActiveGhostCredentials(ghostCredentialsMessage);
    }
  }, [ghostCredentialsMessage]);

  useEffect(() => {
    if (acProgress.length > 0 && !isStaticRunRef.current) {
      setPreviewSteps(acProgress.map(ac => {
        // Map backend statuses to frontend result badges
        let result: StepRow['result'] = 'waiting';
        if (ac.status === 'passed') result = 'passed';
        else if (ac.status === 'failed') result = 'failed';
        else if (ac.status === 'in_progress') result = 'running';
        else if (ac.status === 'awaiting_human') result = 'running';
        else if (ac.status === 'skipped') result = 'skipped';
        else if (ac.status === 'pending') result = 'waiting';

        // If this is the active thinking step, inject the thinking text
        const isActiveThinkingStep = isThinking && (ac.index === thinkingAcStep - 1);

        return {
          id: `ac-${ac.index}`,
          text: ac.text,
          source: 'jira',
          result,
          reasoning: ac.error || (isActiveThinkingStep ? thinkingText : '')
        };
      }));
    }
  }, [acProgress, isThinking, thinkingText, thinkingAcStep]);

  const handlePreviewSteps = useCallback(async (ticketId: string, guidance?: string) => {
    setPreviewLoading(true);
    try {
      const params = new URLSearchParams({ ticket_id: encodeURIComponent(ticketId) });
      if (guidance?.trim()) {
        params.set("pre_parse_guidance", guidance.trim());
      }
      if (productSlug) {
        params.set("product", productSlug);
      }
      const res = await authenticatedFetch(`${API_BASE_URL}/preview-steps?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Preview failed");
      }
      const data = await res.json();
      setPreviewSteps(data.steps.map((s: string, i: number) => ({
        id: `step-${i}-${Date.now()}`,
        text: s,
        source: 'jira' as const,
        result: 'waiting'
      })));
      setParseQuality(data.parse_quality || null);
      setRawAc(data.acceptance_criteria || "");
      setHasGhostLogin(!!data.has_ghost_login);
      if (!data.has_ghost_login) {
        setGhostAdminEmail("");
        setGhostAdminPassword("");
      }
      setHasGhostDescription(!!data.has_ghost_description);
      if (!data.has_ghost_description) {
        setGhostEmail("");
        setGhostPassword("");
      }
      if (data.pending_jira_comment) {
        setPendingJiraComment({ ticketId, comment: data.pending_jira_comment });
      }
    } catch (err: unknown) {
      console.error("Preview failed:", err);
    } finally {
      setPreviewLoading(false);
    }
  }, [productSlug]);

  const handleTicketSelected = useCallback((ticket: { id: string, summary: string }, config: RunConfig) => {
    setSelectedTicket(ticket);
    setRunConfig(config);
    setUiMode('review');
    handlePreviewSteps(ticket.id, config.preParseGuidance);
  }, [handlePreviewSteps]);

  const handleStaticTestSelected = useCallback(async (
    ticket: { id: string, summary: string },
    test: PlaywrightTest,
    config: RunConfig
  ) => {
    setSelectedTicket(ticket);
    setRunConfig(config);
    setLocalError(null);
    isStaticRunRef.current = true;

    if (test.step_names && test.step_names.length > 0) {
      // Recorded test has canonical step names — use them directly, no LLM fetch needed.
      setPreviewSteps(test.step_names.map((step, i) => ({
        id: `static-step-${i}-${Date.now()}`,
        text: step,
        source: 'jira' as const,
        result: 'waiting'
      })));
    } else {
      setPreviewSteps([]);
      // No step names in index — fall back to fetching AC steps from Jira.
      authenticatedFetch(`${API_BASE_URL}/preview-steps?ticket_id=${encodeURIComponent(ticket.id)}${productSlug ? `&product=${encodeURIComponent(productSlug)}` : ''}`)
        .then(res => res.ok ? res.json() : null)
        .then(data => {
          setPreviewSteps(prev => {
            const hasResults = prev.some(s => s.result === 'passed' || s.result === 'failed');
            if (hasResults) return prev;
            if (data?.steps?.length > 0) {
              return data.steps.map((s: string, i: number) => ({
                id: `ac-step-${i}-${Date.now()}`,
                text: s,
                source: 'jira' as const,
                result: 'waiting' as const
              }));
            }
            if (data && ticket.summary) {
              return [{ id: `summary-0-${Date.now()}`, text: ticket.summary, source: 'jira' as const, result: 'waiting' as const }];
            }
            return prev;
          });
        })
        .catch(() => { /* keep empty steps */ });
    }

    const env = mapUrlToPlaywrightEnv(config.targetUrl);
    const user = mapRoleToPlaywrightUser(config.role);

    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/playwright/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          test_id: test.id,
          env,
          user,
          browser: "chromium"
        })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }

      const data = await response.json();
      setActiveRunId(data.run_id);
      setNovncUrl(data.novnc_url || null);
      setUiMode('running');
      wsConnect(data.run_id);
    } catch (err) {
      console.error("Failed to run static test:", err);
      setLocalError(err instanceof Error ? err.message : "Failed to execute static Playwright test");
    }
  }, [wsConnect]);

  const handleStartTest = useCallback(async (guidance?: string) => {
    if (!selectedTicket || !runConfig) return;

    setLocalError(null);

    if (guidance !== undefined) {
      setRunConfig((prev) => prev ? { ...prev, preParseGuidance: guidance } : prev);
    }

    // ── Computer-Use path (always) ────────────────────────────────────
    // All ticket runs use POST /execute-cu (screenshot→Claude→tool loop).
    // Credential priority: explicit ghost-login admin creds → ghost-description
    // creds → user-supplied custom creds → Test-As role registry (backend fallback
    // via `user_role`).
    let adminEmail = "";
    let adminPassword = "";
    if (hasGhostLogin && ghostAdminEmail.trim()) {
      adminEmail = ghostAdminEmail.trim();
      adminPassword = ghostAdminPassword;
    } else if (hasGhostDescription && ghostEmail.trim()) {
      adminEmail = ghostEmail.trim();
      adminPassword = ghostPassword;
    } else if (runConfig.useCustomCreds && runConfig.customEmail) {
      adminEmail = runConfig.customEmail;
      adminPassword = runConfig.customPassword || "";
    }

    const cuResponse = await startComputerUseExecution({
      jira_ticket_id: selectedTicket.id.toUpperCase(),
      target_url: runConfig.targetUrl,
      admin_email: adminEmail,
      admin_password: adminPassword,
      user_role: runConfig.role,
      product: productSlug,
      override_steps: previewSteps.map(s => s.text).filter(t => t.trim() !== ''),
    });
    if (cuResponse) {
      setActiveRunId(cuResponse.run_id);
      setUiMode('running');
      wsConnect(cuResponse.run_id);
    }
  }, [selectedTicket, runConfig, previewSteps, startComputerUseExecution, productSlug, wsConnect, hasGhostLogin, ghostAdminEmail, ghostAdminPassword, hasGhostDescription, ghostEmail, ghostPassword]);

  const handleResetAll = useCallback(() => {
    // Cancel any in-progress run on the server (fire-and-forget)
    if (activeRunId) {
      authenticatedFetch(`${API_BASE_URL}/run/${activeRunId}/cancel`, { method: "POST" }).catch(() => {});
    }
    wsReset();
    resetRun();
    isStaticRunRef.current = false;
    setUiMode('select');
    setSelectedTicket(null);
    setRunConfig(null);
    setPreviewSteps([]);
    setActiveTriage(null);
    setActiveTakeover(null);
    setActivePersonaCredentials(null);
    setActiveGhostCredentials(null);
    setShowCustomCredsPrompt(false);
    setActiveRunId("");
    setNovncUrl(null);
    setLocalError(null);
    setHasGhostLogin(false);
    setGhostAdminEmail("");
    setGhostAdminPassword("");
  }, [wsReset, resetRun, activeRunId]);

  const handleRunAgain = useCallback(() => {
    wsReset();
    resetRun();
    isStaticRunRef.current = false;
    setUiMode('review');
    // Reset step results for the new run
    setPreviewSteps(prev => prev.map(s => ({ ...s, result: 'waiting', reasoning: '' })));
    setActiveTriage(null);
    setActiveTakeover(null);
    setActivePersonaCredentials(null);
    setActiveGhostCredentials(null);
    setGhostAdminEmail("");
    setGhostAdminPassword("");
  }, [wsReset, resetRun]);

  const handleStopTest = useCallback(async (): Promise<void> => {
    const runId = activeRunId;
    if (runId) {
      try {
        await authenticatedFetch(`${API_BASE_URL}/run/${runId}/cancel`, { method: "POST" });
      } catch (err) {
        console.error("Failed to cancel run:", err);
      }
    }
    // Wait for the terminal message from the backend to transition to 'complete' mode.
  }, [activeRunId]);

  const handlePauseTest = useCallback(async (): Promise<boolean> => {
    const runId = activeRunId;
    if (runId) {
      const ok = await pauseExecution(runId);
      if (ok) {
        setUiMode('paused');
        return true;
      }
    }
    return false;
  }, [activeRunId, pauseExecution]);

  const handleResumeTest = useCallback(async () => {
    const runId = activeRunId;
    if (runId) {
      // Inject updated steps if any were edited during pause
      const overrideSteps = previewSteps.map(s => s.text).filter(t => t.trim() !== '');
      const ok = await resumeExecution(runId, overrideSteps);
      if (ok) {
        setUiMode('running');
      }
    }
  }, [activeRunId, resumeExecution, previewSteps]);

  const handleEditStep = (id: string, text: string) => {
    setPreviewSteps(prev => prev.map(s => s.id === id ? { ...s, text } : s));
  };

  const handleRemoveStep = (id: string) => {
    setPreviewSteps(prev => prev.filter(s => s.id !== id));
  };

  const handleReorderSteps = (draggedId: string, overId: string) => {
    setPreviewSteps(prev => {
      const draggedIdx = prev.findIndex(s => s.id === draggedId);
      const overIdx = prev.findIndex(s => s.id === overId);
      const updated = [...prev];
      const [moved] = updated.splice(draggedIdx, 1);
      updated.splice(overIdx, 0, moved);
      return updated;
    });
  };

  const handleAddStep = (text: string) => {
    setPreviewSteps(prev => [...prev, { 
      id: `user-${Date.now()}`, 
      text, 
      source: 'user_added',
      result: 'waiting'
    }]);
  };

  const handleTriageRerun = (guidance: string) => {
    setActiveTriage(null);
    handleStartTest(guidance);
  };

  const handleFalsePositive = useCallback((index: number) => {
    const runId = executeResponse?.run_id;
    if (runId && wsSocket && wsSocket.readyState === WebSocket.OPEN) {
      console.log(`[RunTestView] Sending verifier_correction for step ${index + 1}`);
      wsSocket.send(JSON.stringify({
        type: "verifier_correction",
        run_id: runId,
        ac_step_index: index,
        reason: "User manually marked as SATISFIED (False Positive override)"
      }));
    }
  }, [executeResponse, wsSocket]);

  return (
    <div className="run-test-view">
      {(error || localError) && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{error || localError}</span>
        </div>
      )}

      {showCustomCredsPrompt && (
        <CustomCredentialPanel
          onSave={(email, password) => {
            setRunConfig((prev) =>
              prev
                ? { ...prev, useCustomCreds: true, customEmail: email, customPassword: password }
                : prev
            );
            setShowCustomCredsPrompt(false);
            setLocalError(null);
            handleStartTest();
          }}
          onDismiss={() => setShowCustomCredsPrompt(false)}
        />
      )}

      <ErrorBoundary onReset={handleResetAll}>
        {uiMode === 'select' && (
          <SelectView
            onTicketSelected={handleTicketSelected}
            onStaticTestSelected={handleStaticTestSelected}
            isLoading={isLoading}
            onCheckCredentials={checkTicketCredentials}
          />
        )}
        
        {uiMode === 'review' && selectedTicket && (
          <ReviewView
            key={selectedTicket.id}
            ticket={selectedTicket}
            config={runConfig!}
            steps={previewSteps}
            isLoading={previewLoading || isLoading}
            parseQuality={parseQuality}
            rawAc={rawAc}
            onEditStep={handleEditStep}
            onRemoveStep={handleRemoveStep}
            onReorderSteps={handleReorderSteps}
            onAddStep={handleAddStep}
            onStartTest={handleStartTest}
            onBack={handleResetAll}
            onRecordDemo={() => setShowRecordDemoModal(true)}
            hasGhostDescription={hasGhostDescription}
            ghostEmail={ghostEmail}
            ghostPassword={ghostPassword}
            onGhostEmailChange={setGhostEmail}
            onGhostPasswordChange={setGhostPassword}
            hasGhostLogin={hasGhostLogin}
            ghostAdminEmail={ghostAdminEmail}
            ghostAdminPassword={ghostAdminPassword}
            onGhostAdminEmailChange={setGhostAdminEmail}
            onGhostAdminPasswordChange={setGhostAdminPassword}
          />
        )}

        {uiMode === 'running' && selectedTicket && (
          <RunningView
            ticket={selectedTicket}
            config={runConfig!}
            steps={previewSteps}
            runId={activeRunId}
            isThinking={isThinking}
            thinkingText={thinkingText}
            thinkingAcStep={thinkingAcStep}
            thinkingAcTotal={thinkingAcTotal}
            terminalMessage={terminalMessage}
            onStopTest={handleStopTest}
            onPauseTest={handlePauseTest}
            onFalsePositive={handleFalsePositive}
            novncUrl={novncUrl}
            latestScreenshot={latestScreenshot}
          />
        )}

        {uiMode === 'paused' && selectedTicket && (
          <ReviewView
            key={`paused-${selectedTicket.id}`}
            ticket={selectedTicket}
            config={runConfig!}
            steps={previewSteps}
            isLoading={isLoading}
            onEditStep={handleEditStep}
            onRemoveStep={handleRemoveStep}
            onReorderSteps={handleReorderSteps}
            onAddStep={handleAddStep}
            onStartTest={handleResumeTest}
            onBack={handleResetAll}
            actionLabel="Resume Test"
            isPaused={true}
          />
        )}

        {uiMode === 'complete' && selectedTicket && (
          <CompleteView
            ticket={selectedTicket}
            config={runConfig!}
            steps={previewSteps}
            runId={activeRunId}
            triageMessage={activeTriage}
            overallResult={terminalMessage?.type ?? null}
            onRunAgain={handleRunAgain}
            onNewRun={handleResetAll}
            onViewReport={() => {
              const token = VITE_API_KEY ? `?token=${encodeURIComponent(VITE_API_KEY)}` : '';
              window.open(`${API_BASE_URL}/runs/${activeRunId}/report${token}`, '_blank');
            }}
            onCopyLink={() => {
              const token = VITE_API_KEY ? `?token=${encodeURIComponent(VITE_API_KEY)}` : '';
              navigator.clipboard.writeText(`${API_BASE_URL}/runs/${activeRunId}/report${token}`);
            }}
            onTriageRerun={handleTriageRerun}
            onDismissTriage={() => setActiveTriage(null)}
          />
        )}

        {/* Global Overlays (HITL, Credentials) */}
        {activeTakeover && (
          <div className="takeover-overlay">
            <TakeoverPanel
              runId={activeRunId}
              acStep={activeTakeover.ac_step}
              acStepIndex={activeTakeover.ac_step_index}
              errorMessage={activeTakeover.error_message}
              screenshotB64={latestScreenshot}
              vncUrl={activeTakeover.novnc_url}
              onDone={() => setActiveTakeover(null)}
            />
          </div>
        )}

        {activePersonaCredentials && (
          <PersonaCredentialPanel
            message={activePersonaCredentials}
            onSubmitted={() => setActivePersonaCredentials(null)}
            onDismiss={() => setActivePersonaCredentials(null)}
          />
        )}

        {activeGhostCredentials && (
          <GhostCredentialPanel
            message={activeGhostCredentials}
            onSubmitted={() => setActiveGhostCredentials(null)}
            onDismiss={() => setActiveGhostCredentials(null)}
          />
        )}

        {showRecordDemoModal && selectedTicket && runConfig && (
          <RecordDemoModal
            ticketId={selectedTicket.id}
            ticketSummary={selectedTicket.summary}
            targetUrl={runConfig.targetUrl}
            onClose={() => setShowRecordDemoModal(false)}
          />
        )}

        {showSaveAsTestDialog && selectedTicket && activeRunId && (
          <SaveAsTestDialog
            runId={activeRunId}
            ticketId={selectedTicket.id}
            ticketSummary={selectedTicket.summary}
            product={productSlug}
            onClose={() => setShowSaveAsTestDialog(false)}
          />
        )}

        {pendingJiraComment && (
          <div className="record-demo-overlay">
            <div className="record-demo-modal">
              <div className="record-demo-header">
                <span className="record-demo-title">Post comment to Jira?</span>
                <span className="record-demo-ticket-id">{pendingJiraComment.ticketId}</span>
              </div>
              <div className="record-demo-body">
                <div className="record-demo-instruction-card">
                  <div className="record-demo-instruction-title">vQA wants to post this comment</div>
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem", color: "var(--color-text-secondary)", margin: "0.5rem 0 0" }}>
                    {pendingJiraComment.comment}
                  </pre>
                </div>
              </div>
              <div className="record-demo-footer">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setPendingJiraComment(null)}
                >
                  Skip
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={async () => {
                    await authenticatedFetch(
                      `${API_BASE_URL}/jira/${pendingJiraComment.ticketId}/post-comment`,
                      {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ comment: pendingJiraComment.comment }),
                      }
                    );
                    setPendingJiraComment(null);
                  }}
                >
                  Post to Jira
                </button>
              </div>
            </div>
          </div>
        )}
      </ErrorBoundary>
    </div>
  );
}
