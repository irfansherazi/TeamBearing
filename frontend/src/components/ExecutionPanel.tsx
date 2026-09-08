/**
 * vQA — Execution Panel Component
 * =================================
 * Module: frontend/src/components/ExecutionPanel.tsx
 *
 * The main control panel where users:
 *   1. SELECT a Jira Ticket from a searchable dropdown (loaded from board)
 *   2. See credential status badge (complete/partial/none)
 *   3. Fill in any missing credential (if partial)
 *   4. Select a User Role from the dropdown (ignored if ticket has full creds)
 *   5. Choose execution mode (interactive / headless)
 *   6. Click "Preview Steps" → review & edit parsed AC steps
 *   7. Click "Confirm & Execute" to start with pre-confirmed steps
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { CredentialCheckResponse, ExecuteRequest, ExecutionMode, PreviewStep, PreviewStepsResponse, RoleKey, SyncACResponse } from "../types";
import { ALL_ROLES, API_BASE_URL, ROLE_DISPLAY_NAMES } from "../types";
import { CredentialPrompt } from "./CredentialPrompt";
import { RecordDemoModal } from "./RecordDemoModal";
import { ClarificationWizardModal } from "./ClarificationWizardModal";
import { buildGuidance } from "../lib/wizardGuidance";
import { authenticatedFetch } from "../api_client";
import { useProductContext } from "../context/ProductContext";

interface JiraTicketSummary {
  id: string;
  summary: string;
  status: string;
  priority: string;
  issue_type: string;
}

interface ExecutionPanelProps {
  onExecute: (request: ExecuteRequest) => void;
  isLoading: boolean;
  isRunning: boolean;
  onCheckCredentials: (ticketId: string) => Promise<CredentialCheckResponse | null>;
  /** Pre-fill from history re-run */
  rerunTicket?: { ticketId: string; role: string } | null;
  /** Guidance text pre-filled from TriagePanel re-run */
  pendingGuidance?: string;
  /** Called after guidance is consumed so Dashboard can reset it */
  onGuidanceConsumed?: () => void;
  /** Called when the user selects a new ticket or clears the current one */
  onNewRun?: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  "In Progress": "#0052cc",
  "To Do": "#6b778c",
  "Done": "#36b37e",
  "In Review": "#ff8b00",
  "Blocked": "#de350b",
  "Testing": "#6554c0",
};

const PRIORITY_ICONS: Record<string, string> = {
  "Highest": "🔴",
  "High": "🟠",
  "Medium": "🟡",
  "Low": "🔵",
  "Lowest": "⚪",
};

export function ExecutionPanel({ onExecute, isLoading, isRunning, onCheckCredentials, rerunTicket, pendingGuidance = "", onGuidanceConsumed, onNewRun }: ExecutionPanelProps) {
  const { activeSlug: productSlug } = useProductContext();

  // Ticket selector state
  const [tickets, setTickets] = useState<JiraTicketSummary[]>([]);
  const [ticketsLoading, setTicketsLoading] = useState(true);
  const [ticketsError, setTicketsError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState<JiraTicketSummary | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Form state
  const [role, setRole] = useState<RoleKey>("account_executive");
  const [mode, setMode] = useState<ExecutionMode>("interactive");
  const [targetUrl, setTargetUrl] = useState("https://two-test.vcreative.net");

  // Credential state
  const [credCheck, setCredCheck] = useState<CredentialCheckResponse | null>(null);
  const [credCheckLoading, setCredCheckLoading] = useState(false);
  const [missingFieldValue, setMissingFieldValue] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Step Preview / Confirmation state ─────────────────────────────────
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [parseQuality, setParseQuality] = useState<string | null>(null);
  const [parseQualityReason, setParseQualityReason] = useState<string | null>(null);
  // null = not yet previewed, PreviewStep[] = steps shown for review
  const [previewSteps, setPreviewSteps] = useState<PreviewStep[] | null>(null);
  // After user confirms (edits applied), these are the locked-in steps
  const [confirmedSteps, setConfirmedSteps] = useState<PreviewStep[] | null>(null);
  // Raw AC text from Jira (cached from preview response for sync dialog)
  const [rawAcText, setRawAcText] = useState("");

  // ── Jira Sync Dialog state ────────────────────────────────────────────
  const [showSyncDialog, setShowSyncDialog] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncToast, setSyncToast] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // ── Drag-and-drop state ───────────────────────────────────────────────
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);

  // ── Quick-add input ───────────────────────────────────────────────────
  const [quickAddText, setQuickAddText] = useState("");

  // ── Guidance inputs (two moments) ──────────────────────────────────────
  // Moment 1: provided before the AI generates ACs (→ sent to /preview-steps)
  const [preParseGuidance, setPreParseGuidance] = useState("");
  // Moment 2: provided after reviewing ACs, before execution (→ sent as user_guidance)
  // ── Failed Login Testing ────────────────────────────────────────────
  const [expectLoginFailure, setExpectLoginFailure] = useState(false);
  const [preExecuteGuidance, setPreExecuteGuidance] = useState("");

  // ── Custom Credentials ──────────────────────────────────────────────
  const [useCustomCreds, setUseCustomCreds] = useState(false);
  const [customEmail, setCustomEmail] = useState("");
  const [customPassword, setCustomPassword] = useState("");

  // ── Codegen Demo Recording ───────────────────────────────────────────
  const [showRecordDemoModal, setShowRecordDemoModal] = useState(false);
  const [demoSuccessBanner, setDemoSuccessBanner] = useState<string | null>(null);

  // ── Clarification Wizard (TASK-122 / FEAT-113) ───────────────────────
  const [showWizard, setShowWizard] = useState(false);
  const [wizardPaths, setWizardPaths] = useState<string[]>([]);
  const [wizardAmbiguities, setWizardAmbiguities] = useState<string[]>([]);

  // ── Load board tickets on mount ────────────────────────────────────
  useEffect(() => {
    setTicketsLoading(true);
    authenticatedFetch(`${API_BASE_URL}/tickets`)
      .then(async (r) => {
        if (!r.ok) {
          const errorData = await r.json().catch(() => ({ detail: "Unknown error" }));
          throw new Error(errorData.detail || `Server error: ${r.status}`);
        }
        return r.json();
      })
      .then((data: JiraTicketSummary[]) => {
        setTickets(data);
        setTicketsLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load tickets:", err);
        setTicketsError(err instanceof Error ? err.message : "Could not load board tickets");
        setTicketsLoading(false);
      });
  }, []);

  // ── Close dropdown on outside click ───────────────────────────────
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Debounced credential check when ticket is selected ─────────────
  const runCredCheck = useCallback(
    (ticketId: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      setCredCheck(null);
      setMissingFieldValue("");
      if (ticketId.length >= 3) {
        setCredCheckLoading(true);
        debounceRef.current = setTimeout(async () => {
          const result = await onCheckCredentials(ticketId);
          setCredCheck(result);
          setCredCheckLoading(false);
        }, 500);
      }
    },
    [onCheckCredentials],
  );

  // Pre-fill from history re-run (must be AFTER runCredCheck is declared)
  useEffect(() => {
    if (!rerunTicket) return;
    const synthetic: JiraTicketSummary = {
      id: rerunTicket.ticketId,
      summary: "",
      status: "",
      priority: "",
      issue_type: "",
    };
    setSelectedTicket(synthetic);
    setRole(rerunTicket.role as RoleKey);
    runCredCheck(rerunTicket.ticketId);
  }, [rerunTicket, runCredCheck]);

  // Reset preview and notify Dashboard when ticket changes
  // Auto-trigger preview when a ticket is selected (mandatory gate)
  useEffect(() => {
    setPreviewSteps(null);
    setConfirmedSteps(null);
    setPreviewError(null);
    setPreParseGuidance("");
    setPreExecuteGuidance("");
    setRawAcText("");
    setShowSyncDialog(false);
    setSyncToast(null);
    setQuickAddText("");
    setShowRecordDemoModal(false);
    if (selectedTicket?.id) {
      onNewRun?.();
      // Auto-trigger preview (mandatory AC gate)
      autoPreview(selectedTicket.id);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTicket?.id]);

  // Auto-prompt codegen when AC parsing is degraded
  useEffect(() => {
    if (parseQuality === "degraded" && previewSteps !== null && selectedTicket) {
      setShowRecordDemoModal(true);
    }
  }, [parseQuality, previewSteps, selectedTicket]);

  const handleSelectTicket = (ticket: JiraTicketSummary) => {
    setSelectedTicket(ticket);
    setSearchQuery("");
    setIsDropdownOpen(false);
    runCredCheck(ticket.id);
  };

  const handleClearTicket = () => {
    setSelectedTicket(null);
    setSearchQuery("");
    setCredCheck(null);
    setMissingFieldValue("");
    setPreviewSteps(null);
    setConfirmedSteps(null);
    onNewRun?.();
    setTimeout(() => searchRef.current?.focus(), 50);
  };

  // ── Preview Steps (auto-triggered on ticket select) ────────────────
  const autoPreview = async (ticketId: string) => {
    setPreviewLoading(true);
    setPreviewError(null);
    setParseQuality(null);
    setParseQualityReason(null);
    setPreviewSteps(null);
    setConfirmedSteps(null);
    setShowWizard(false);
    try {
      const params = new URLSearchParams({ ticket_id: encodeURIComponent(ticketId) });
      if (preParseGuidance.trim()) {
        params.set("pre_parse_guidance", preParseGuidance.trim());
      }
      if (productSlug) {
        params.set("product", productSlug);
      }
      const res = await authenticatedFetch(`${API_BASE_URL}/preview-steps?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Preview failed");
      }
      const data: PreviewStepsResponse = await res.json();
      setPreviewSteps(data.steps.map((s) => ({ text: s, source: 'jira' as const })));
      setRawAcText(data.acceptance_criteria || "");
      setParseQuality(data.parse_quality || null);
      setParseQualityReason(data.parse_quality_reason || null);

      // Show clarification wizard when multiple paths detected or ambiguities surfaced
      const paths = data.detected_paths ?? [];
      const ambigs = data.ambiguities ?? [];
      const shouldShowWizard = paths.length >= 2 || ambigs.length > 0;
      if (shouldShowWizard) {
        setWizardPaths(paths);
        setWizardAmbiguities(ambigs);
        setShowWizard(true);
      }
    } catch (err: unknown) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  // Manual re-parse (e.g. after changing pre-parse guidance)
  const handlePreviewSteps = async () => {
    const ticketId = selectedTicket?.id;
    if (!ticketId) return;
    await autoPreview(ticketId);
  };

  // ── Clarification Wizard handlers ────────────────────────────────────
  const handleWizardConfirm = async (
    selectedPaths: string[],
    resolutions: Record<string, string>
  ) => {
    setShowWizard(false);
    const guidance = buildGuidance(wizardPaths, selectedPaths, resolutions);
    if (guidance) {
      setPreParseGuidance(guidance);
    }
    const ticketId = selectedTicket?.id;
    if (!ticketId) return;
    // Re-fetch preview with guidance injected so backend re-parses with path exclusions
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewSteps(null);
    setConfirmedSteps(null);
    try {
      const params = new URLSearchParams({ ticket_id: encodeURIComponent(ticketId) });
      const effectiveGuidance = guidance || preParseGuidance.trim();
      if (effectiveGuidance) {
        params.set("pre_parse_guidance", effectiveGuidance);
      }
      if (productSlug) {
        params.set("product", productSlug);
      }
      const res = await authenticatedFetch(`${API_BASE_URL}/preview-steps?${params.toString()}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Preview failed");
      }
      const data: PreviewStepsResponse = await res.json();
      setPreviewSteps(data.steps.map((s) => ({ text: s, source: 'jira' as const })));
      setRawAcText(data.acceptance_criteria || "");
      setParseQuality(data.parse_quality || null);
      setParseQualityReason(data.parse_quality_reason || null);
    } catch (err: unknown) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  // "Skip" closes the wizard and keeps the unmodified steps from the initial preview
  const handleWizardSkip = () => {
    setShowWizard(false);
  };

  const handleStepChange = (idx: number, value: string) => {
    if (!previewSteps) return;
    const updated = [...previewSteps];
    updated[idx] = { ...updated[idx], text: value };
    setPreviewSteps(updated);
  };

  const handleInsertStep = (afterIdx: number) => {
    if (!previewSteps) return;
    const updated = [...previewSteps];
    updated.splice(afterIdx + 1, 0, { text: "", source: 'user_added' });
    setPreviewSteps(updated);
  };

  const handleRemoveStep = (idx: number) => {
    if (!previewSteps) return;
    const updated = previewSteps.filter((_, i) => i !== idx);
    setPreviewSteps(updated);
  };

  const handleQuickAdd = () => {
    if (!quickAddText.trim() || !previewSteps) return;
    setPreviewSteps([...previewSteps, { text: quickAddText.trim(), source: 'user_added' }]);
    setQuickAddText("");
  };

  // ── Drag-and-drop reordering ──────────────────────────────────────────
  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setDropIdx(idx);
  };
  const handleDragEnd = () => {
    if (dragIdx !== null && dropIdx !== null && dragIdx !== dropIdx && previewSteps) {
      const updated = [...previewSteps];
      const [moved] = updated.splice(dragIdx, 1);
      updated.splice(dropIdx, 0, moved);
      setPreviewSteps(updated);
    }
    setDragIdx(null);
    setDropIdx(null);
  };

  // ── Confirm steps → check for user-added → maybe show sync dialog ────
  const handleConfirmSteps = () => {
    if (!previewSteps) return;
    const valid = previewSteps.filter((s) => s.text.trim());
    const hasUserAdded = valid.some((s) => s.source === 'user_added');
    setConfirmedSteps(valid);
    setPreviewSteps(null);
    if (hasUserAdded) {
      setShowSyncDialog(true);
    }
  };

  const handleDismissPreview = () => {
    setPreviewSteps(null);
    setConfirmedSteps(null);
    setParseQuality(null);
    setParseQualityReason(null);
  };

  // ── Jira Sync ─────────────────────────────────────────────────────────
  const handleSyncToJira = async () => {
    if (!confirmedSteps || !selectedTicket?.id) return;
    const addedSteps = confirmedSteps.filter((s) => s.source === 'user_added').map((s) => s.text);
    if (addedSteps.length === 0) return;
    setSyncLoading(true);
    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/ticket/${selectedTicket.id}/sync-ac`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ added_steps: addedSteps, original_ac_text: rawAcText }),
      });
      const data: SyncACResponse = await res.json();
      if (data.synced) {
        setSyncToast({ type: 'success', text: `${data.added_count} new ACs synced to ${selectedTicket.id} ✅` });
      } else {
        setSyncToast({ type: 'error', text: `⚠️ Jira sync failed: ${data.error}` });
      }
    } catch {
      setSyncToast({ type: 'error', text: `⚠️ Jira sync failed — steps saved locally only` });
    } finally {
      setSyncLoading(false);
      setShowSyncDialog(false);
      setTimeout(() => setSyncToast(null), 5000);
    }
  };

  const handleSkipSync = () => {
    setShowSyncDialog(false);
  };

  // ── Filtered ticket list ───────────────────────────────────────────
  const filteredTickets = Array.isArray(tickets) ? (searchQuery.trim()
    ? tickets.filter(
        (t) =>
          t.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.summary.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : tickets) : [];

  // ── Credential status ──────────────────────────────────────────────
  const isPartial = credCheck?.status === "partial";
  const missingField = isPartial ? (credCheck?.email_found ? "password" : "email") : null;
  const partialBlocked = isPartial && !missingFieldValue.trim();
  const customCredsBlocked = useCustomCreds && (!customEmail.trim() || !customPassword.trim());

  const ticketId = selectedTicket?.id ?? "";
  // ── MANDATORY GATE: Execute REQUIRES confirmed steps ──────────────
  const isDisabled = isLoading || isRunning ||
    (!ticketId || partialBlocked || customCredsBlocked || previewLoading || !!previewSteps || showSyncDialog || !confirmedSteps || confirmedSteps.length === 0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isDisabled) return;

    const req: ExecuteRequest = {
      jira_ticket_id: ticketId.toUpperCase(),
      role,
      target_url: targetUrl,
      mode,
      execution_engine: "ai",
    };

    // Failed login testing mode
    if (expectLoginFailure) {
      req.expect_login_failure = true;
    }

    // Custom credentials take priority over everything (role creds, ticket creds)
    if (useCustomCreds && customEmail.trim() && customPassword.trim()) {
      req.override_email = customEmail.trim();
      req.override_password = customPassword.trim();
    } else if (credCheck?.status !== "complete") {
      if (isPartial && missingField && missingFieldValue.trim()) {
        if (missingField === "email") {
          req.override_email = missingFieldValue.trim();
        } else {
          req.override_password = missingFieldValue.trim();
        }
      }
    }

    // pre_parse_guidance feeds the AC parser (step generation LLM call)
    if (preParseGuidance.trim()) {
      req.pre_parse_guidance = preParseGuidance.trim();
    }

    // user_guidance feeds the planner on EVERY step — combine all three sources:
    //   (1) pendingGuidance  — from TriagePanel re-run flow
    //   (2) preParseGuidance — "Context for AI" textarea (always-visible)
    //   (3) preExecuteGuidance — "Notes for agent" inside Preview Steps editor
    // This ensures the always-visible textarea actually affects agent execution.
    const combinedGuidance = [
      pendingGuidance,
      preParseGuidance.trim(),
      preExecuteGuidance.trim(),
    ].filter(Boolean).join("\n\n");
    if (combinedGuidance) {
      req.user_guidance = combinedGuidance;
      onGuidanceConsumed?.();
    }

    // Inject pre-confirmed steps (skips LLM parsing)
    if (Array.isArray(confirmedSteps) && confirmedSteps.length > 0) {
      req.override_steps = confirmedSteps.map((s) => s.text);
    }

    onExecute(req);
  };

  // ── Demo recording — modal closes itself; banner shown on next tick ──
  const handleDemoClose = () => {
    setShowRecordDemoModal(false);
    setDemoSuccessBanner("Demo recorded — Playwright test saved and committed.");
    setTimeout(() => setDemoSuccessBanner(null), 6000);
  };

  // ── Credential status badge ────────────────────────────────────────
  const renderCredBadge = () => {
    if (credCheckLoading) return <span className="cred-badge cred-checking">🔍 Checking ticket...</span>;
    if (!credCheck || credCheck.status === "none") return <span className="cred-badge cred-none">ℹ️ Using role credentials</span>;
    if (credCheck.status === "complete") return <span className="cred-badge cred-complete">✅ Credentials in ticket</span>;
    if (credCheck.status === "partial") return <span className="cred-badge cred-partial">⚠️ Partial — input required</span>;
    return null;
  };

  return (
    <div className="panel execution-panel">
      <div className="panel-header">
        <h2>🎯 New Test Execution</h2>
        <span className="panel-badge">vQA Agent</span>
      </div>

      <form onSubmit={handleSubmit} className="execution-form">
        {/* ── Jira Ticket Selector ─────────────────────────────── */}
        <div className="form-group">
            <label htmlFor="ticket-search">Jira Ticket</label>

            <div className="ticket-combobox" ref={dropdownRef}>
              {/* Selected chip or search input */}
              {selectedTicket ? (
                <div className="ticket-selected-chip">
                  <span className="chip-id">{selectedTicket.id}</span>
                  <span className="chip-summary">{selectedTicket.summary}</span>
                  <button
                    type="button"
                    className="chip-clear"
                    onClick={handleClearTicket}
                    disabled={isRunning}
                    aria-label="Clear selection"
                  >
                    ✕
                  </button>
                  {renderCredBadge()}
                </div>
              ) : (
                <div className="ticket-search-wrapper">
                  <span className="ticket-search-icon">🔍</span>
                  <input
                    id="ticket-search"
                    ref={searchRef}
                    type="text"
                    placeholder={ticketsLoading ? "Loading tickets…" : "Search by ID or title…"}
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setIsDropdownOpen(true);
                    }}
                    onFocus={() => setIsDropdownOpen(true)}
                    className="form-input ticket-search-input"
                    disabled={isRunning}
                    autoComplete="off"
                    autoFocus
                  />
                  {ticketsLoading && <span className="ticket-search-spinner" />}
                </div>
              )}

              {/* Dropdown list */}
              {isDropdownOpen && !selectedTicket && (
                <div className="ticket-dropdown">
                  {ticketsError ? (
                    <div className="ticket-dropdown-error">{ticketsError}</div>
                  ) : filteredTickets.length === 0 ? (
                    <div className="ticket-dropdown-empty">
                      {searchQuery ? `No tickets matching "${searchQuery}"` : "No open tickets found"}
                    </div>
                  ) : (
                    <ul className="ticket-list" role="listbox">
                      {filteredTickets.map((ticket) => (
                        <li
                          key={ticket.id}
                          className="ticket-list-item"
                          role="option"
                          onClick={() => handleSelectTicket(ticket)}
                          onKeyDown={(e) => e.key === "Enter" && handleSelectTicket(ticket)}
                          tabIndex={0}
                        >
                          <div className="ticket-list-row">
                            <span className="ticket-list-id">{ticket.id}</span>
                            {ticket.priority && (
                              <span className="ticket-list-priority" title={ticket.priority}>
                                {PRIORITY_ICONS[ticket.priority] ?? ""}
                              </span>
                            )}
                            <span
                              className="ticket-list-status"
                              style={{ color: STATUS_COLORS[ticket.status] ?? "#6b778c" }}
                            >
                              {ticket.status}
                            </span>
                          </div>
                          <div className="ticket-list-summary">{ticket.summary}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <span className="form-hint">
              {ticketsLoading
                ? "Loading from QA board…"
                : `${tickets.length} open tickets from vcreative.atlassian.net/jira/software/c/projects/QA`}
            </span>
          </div>

        {selectedTicket && (
          <div className="form-group guidance-group guidance-group--pre-parse">
            <label htmlFor="pre-parse-guidance" className="guidance-label">
              <span className="guidance-label-icon">🧠</span>
              Context for the AI Agent
              <span className="guidance-label-optional">(optional)</span>
            </label>
            <textarea
              id="pre-parse-guidance"
              className="guidance-textarea"
              value={preParseGuidance}
              rows={3}
              disabled={isRunning || !!previewSteps}
              placeholder={`Describe anything the agent needs to know — e.g.:\n• "This ticket tests the Compact view. There are no column headers — use the Sort By dropdown for all sorting."
• "The Submitted On column is inside the Due / Days dropdown in List View."
• "After navigating to Compact view, verify by checking for the Sort By button — not column headers."`}
              onChange={(e) => setPreParseGuidance(e.target.value)}
            />
            <span className="form-hint guidance-hint">
              ⚡ <strong>Active on every step</strong> — injected into the agent&apos;s planner prompt as highest-priority instructions. Also used when generating test steps.
            </span>
          </div>
        )}

        {/* ── Partial credential prompt ──────────────────────────── */}
        {isPartial && missingField && (
          <CredentialPrompt
            missingField={missingField}
            foundEmail={credCheck?.email ?? ""}
            value={missingFieldValue}
            onChange={setMissingFieldValue}
          />
        )}

        {/* ── Custom Credentials Toggle ───────────────────────────── */}
        <div className="form-group">
          <label className="custom-creds-toggle-label">
            <input
              type="checkbox"
              className="custom-creds-checkbox"
              checked={useCustomCreds}
              onChange={(e) => {
                setUseCustomCreds(e.target.checked);
                if (!e.target.checked) {
                  setCustomEmail("");
                  setCustomPassword("");
                }
              }}
              disabled={isRunning}
            />
            <span className="custom-creds-toggle-icon">🔑</span>
            Use Custom Credentials
          </label>
          {useCustomCreds && (
            <div className="custom-creds-panel">
              <div className="custom-creds-fields">
                <div className="form-group custom-creds-field-group">
                  <label htmlFor="custom-email">Email</label>
                  <input
                    id="custom-email"
                    type="email"
                    placeholder="you@example.com"
                    value={customEmail}
                    onChange={(e) => setCustomEmail(e.target.value)}
                    className="form-input"
                    disabled={isRunning}
                    autoComplete="off"
                  />
                </div>
                <div className="form-group custom-creds-field-group">
                  <label htmlFor="custom-password">Password</label>
                  <input
                    id="custom-password"
                    type="password"
                    placeholder="Password"
                    value={customPassword}
                    onChange={(e) => setCustomPassword(e.target.value)}
                    className="form-input"
                    disabled={isRunning}
                    autoComplete="new-password"
                  />
                </div>
              </div>
              <span className="form-hint">
                Overrides role credentials for this run only. Not stored.
              </span>
            </div>
          )}
        </div>

        {/* ── Role Selector ──────────────────────────────────────── */}
        <div className={`form-group ${(credCheck?.status === "complete" || useCustomCreds) ? "form-group-dimmed" : ""}`}>
          <label htmlFor="role-select">
            User Role
            {useCustomCreds ? (
              <span className="role-override-note"> (overridden by custom credentials)</span>
            ) : credCheck?.status === "complete" ? (
              <span className="role-override-note"> (overridden by ticket)</span>
            ) : null}
          </label>
          <select
            id="role-select"
            value={role}
            onChange={(e) => setRole(e.target.value as RoleKey)}
            className="form-select"
            disabled={isRunning || credCheck?.status === "complete" || useCustomCreds}
          >
            {ALL_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_DISPLAY_NAMES[r]}
              </option>
            ))}
          </select>
          <span className="form-hint">
            {useCustomCreds
              ? `Using custom credentials — role RBAC constraints still apply`
              : credCheck?.status === "complete"
              ? `Using ${credCheck.email} from the ticket instead`
              : "The agent will login as this role and enforce its permission constraints"}
          </span>
        </div>

        {/* ── Target URL ─────────────────────────────────────────── */}
        <div className="form-group">
          <label htmlFor="target-url">Target URL</label>
          <input
            id="target-url"
            type="url"
            placeholder="https://two-test.vcreative.net"
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            className="form-input"
            disabled={isRunning}
          />
        </div>

        {/* ── Mode Toggle ────────────────────────────────────────── */}
        <div className="form-group">
          <label>Execution Mode</label>
          <div className="mode-toggle">
            <button
              type="button"
              className={`mode-btn ${mode === "interactive" ? "active" : ""}`}
              onClick={() => setMode("interactive")}
              disabled={isRunning}
            >
              <span className="mode-icon">🖥️</span>
              <span className="mode-label">Interactive</span>
              <span className="mode-desc">Live browser stream</span>
            </button>
            <button
              type="button"
              className={`mode-btn ${mode === "headless" ? "active" : ""}`}
              onClick={() => setMode("headless")}
              disabled={isRunning}
            >
              <span className="mode-icon">⚡</span>
              <span className="mode-label">Headless</span>
              <span className="mode-desc">API-only, faster</span>
            </button>
          </div>
        </div>

        {/* ── Failed Login Toggle ─────────────────────────────────── */}
        <div className="form-group">
          <label className="failed-login-toggle-label">
            <input
              type="checkbox"
              className="failed-login-checkbox"
              checked={expectLoginFailure}
              onChange={(e) => setExpectLoginFailure(e.target.checked)}
              disabled={isRunning}
            />
            <span className="failed-login-toggle-icon">🔐</span>
            Test Failed Login
          </label>
          {expectLoginFailure && (
            <div className="failed-login-hint">
              <span className="failed-login-hint-icon">ℹ️</span>
              The agent will <strong>NOT</strong> auto-login. The browser starts on the blank login
              form. Your AC steps must include the login actions with the expected (invalid) credentials
              and verify the error indicators (toast, URL stays on /login, no JWT).
            </div>
          )}
        </div>

        {/* ── Sync Toast ─────────────────────────────────────────── */}
        {syncToast && (
          <div className={`sync-toast sync-toast--${syncToast.type}`}>
            {syncToast.text}
          </div>
        )}

        {/* ── Mandatory AC Gate Banner ──────────────────────────────── */}
        {selectedTicket && previewLoading && (
          <div className="ac-gate-banner ac-gate-banner--loading">
            <span className="spinner" /> Parsing acceptance criteria…
          </div>
        )}
        {selectedTicket && previewError && !previewSteps && !confirmedSteps && (
          <div className="ac-gate-banner ac-gate-banner--error">
            <span>⚠️ {previewError}</span>
            <button type="button" className="ac-gate-retry-btn" onClick={handlePreviewSteps}>
              🔄 Retry
            </button>
          </div>
        )}

        {/* ── Confirmed Steps Badge ───────────────────────────────── */}
        {confirmedSteps && confirmedSteps.length > 0 && !showSyncDialog && (
          <div className="preview-confirmed-badge">
            <span className="badge-icon">✅</span>
            <span className="badge-text">
              {confirmedSteps.length} steps confirmed — LLM parsing will be skipped
            </span>
            <button
              type="button"
              className="badge-edit-btn"
              onClick={() => {
                setPreviewSteps(confirmedSteps);
                setConfirmedSteps(null);
              }}
            >
              Edit
            </button>
            <button
              type="button"
              className="badge-clear-btn"
              onClick={handleDismissPreview}
            >
              ✕
            </button>
          </div>
        )}

        {/* ── Jira Sync Confirmation Dialog ─────────────────────────── */}
        {showSyncDialog && confirmedSteps && (
          <div className="sync-dialog-overlay">
            <div className="sync-dialog">
              <div className="sync-dialog-header">
                <span className="sync-dialog-icon">📤</span>
                <span className="sync-dialog-title">Sync to Jira — {selectedTicket?.id}</span>
              </div>
              <p className="sync-dialog-desc">
                {Array.isArray(confirmedSteps) ? confirmedSteps.filter((s) => s.source === 'user_added').length : 0} new ACs will be added. Preview the updated Acceptance Criteria field:
              </p>

              {rawAcText && (
                <div className="sync-dialog-section">
                  <div className="sync-dialog-section-label">Current ACs (from Jira)</div>
                  <div className="sync-dialog-ac-box sync-dialog-ac-existing">{rawAcText}</div>
                </div>
              )}

              <div className="sync-dialog-section">
                <div className="sync-dialog-section-label">New ACs (added by you)</div>
                <div className="sync-dialog-ac-box sync-dialog-ac-new">
                  {Array.isArray(confirmedSteps) && confirmedSteps.filter((s) => s.source === 'user_added').map((s, i) => (
                    <div key={i} className="sync-dialog-new-step">✚ {s.text}</div>
                  ))}
                </div>
              </div>

              <div className="sync-dialog-actions">
                <button
                  type="button"
                  className="sync-dialog-confirm-btn"
                  onClick={handleSyncToJira}
                  disabled={syncLoading}
                >
                  {syncLoading ? <><span className="spinner" /> Syncing…</> : '✅ Update Jira'}
                </button>
                <button
                  type="button"
                  className="sync-dialog-skip-btn"
                  onClick={handleSkipSync}
                  disabled={syncLoading}
                >
                  Skip — run without sync
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Step Preview Editor ─────────────────────────────────── */}
        {previewSteps !== null && (
          <div className="step-preview-panel">
            <div className="step-preview-header">
              <span className="step-preview-title">📋 Review & Confirm Acceptance Criteria</span>
              <span className="step-preview-hint">
                Drag to reorder, edit inline, or add new steps. You must confirm before running.
              </span>
            </div>

            {previewError && (
              <div className="step-preview-error">⚠️ {previewError}</div>
            )}

            {parseQuality === "rejected" && (
              <div className="step-preview-warning rejected">
                <strong>⚠️ AC Quality Gate Rejected</strong>
                <p>{parseQualityReason}</p>
                <div className="hint">The agent cannot run with these requirements. Add more specific steps manually below or refine the Jira ticket.</div>
              </div>
            )}

            {parseQuality === "degraded" && (
              <div className="step-preview-warning poor">
                <strong>⚠️ Degraded AC Parsing</strong>
                <p>{parseQualityReason || "The structured parser failed and fell back to basic parsing — steps may be incomplete or inaccurate."}</p>
                <div className="hint">Steps were recovered but structured data is unavailable. Please review and refine them, or record a demo to show the agent exactly what to test.</div>
                <button
                  type="button"
                  className="btn-record-demo"
                  onClick={() => setShowRecordDemoModal(true)}
                  disabled={isRunning}
                >
                  Record Demo
                </button>
              </div>
            )}

            {(parseQuality === "poor" || parseQuality === "fair") && (
              <div className="step-preview-warning poor">
                <strong>⚠️ Low Quality Acceptance Criteria</strong>
                <p>{parseQualityReason}</p>
                <div className="hint">The steps below were generated but may be too vague to succeed. Please refine them, or record a demo to show the agent exactly what to test.</div>
                <button
                  type="button"
                  className="btn-record-demo"
                  onClick={() => setShowRecordDemoModal(true)}
                  disabled={isRunning}
                >
                  Record Demo
                </button>
              </div>
            )}

            <ol className="step-preview-list">
              {Array.isArray(previewSteps) && previewSteps.map((step, idx) => (
                <li key={idx}>
                  {/* Drop target line above */}
                  {dropIdx === idx && dragIdx !== null && dragIdx !== idx && (
                    <div className="step-drop-indicator" />
                  )}
                  <div
                    className={`step-preview-item ${step.source === 'user_added' ? 'step-user-added' : ''} ${dragIdx === idx ? 'step-dragging' : ''}`}
                    draggable
                    onDragStart={() => handleDragStart(idx)}
                    onDragOver={(e) => handleDragOver(e, idx)}
                    onDragEnd={handleDragEnd}
                  >
                    <span className="step-grip" title="Drag to reorder">≡</span>
                    <span className="step-num">{idx + 1}</span>
                    {step.source === 'user_added' && <span className="step-source-badge">NEW</span>}
                    <textarea
                      className="step-edit-input"
                      value={step.text}
                      rows={2}
                      onChange={(e) => handleStepChange(idx, e.target.value)}
                      placeholder="Describe the acceptance criteria…"
                    />
                    <div className="step-item-actions">
                      <button
                        type="button"
                        className="step-remove-btn"
                        title="Remove step"
                        onClick={() => handleRemoveStep(idx)}
                        disabled={previewSteps.length <= 1}
                      >
                        🗑
                      </button>
                    </div>
                  </div>
                  {/* Inline insert button between steps */}
                  <div className="step-insert-row">
                    <button
                      type="button"
                      className="step-insert-btn"
                      onClick={() => handleInsertStep(idx)}
                      title="Insert step here"
                    >
                      ＋ Insert step here
                    </button>
                  </div>
                </li>
              ))}
            </ol>

            {/* Quick-add row at bottom */}
            <div className="step-quick-add">
              <input
                type="text"
                className="step-quick-add-input"
                value={quickAddText}
                onChange={(e) => setQuickAddText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleQuickAdd(); } }}
                placeholder="＋ Add a new acceptance criteria…"
              />
              <button
                type="button"
                className="step-quick-add-btn"
                onClick={handleQuickAdd}
                disabled={!quickAddText.trim()}
              >
                Add Step
              </button>
            </div>

            {/* Moment 2: Pre-Execute Notes */}
            <div className="guidance-group guidance-group--pre-execute">
              <label htmlFor="pre-execute-guidance" className="guidance-label">
                <span className="guidance-label-icon">🧠</span>
                Notes for the agent
                <span className="guidance-label-optional">(optional)</span>
              </label>
              <textarea
                id="pre-execute-guidance"
                className="guidance-textarea"
                value={preExecuteGuidance}
                rows={2}
                placeholder="e.g. 'In Compact view there are no column headers. Click \u201cSort By\u201d dropdown and select the column to sort.' The agent will use this on every step."
                onChange={(e) => setPreExecuteGuidance(e.target.value)}
              />
              <span className="form-hint guidance-hint">
                Injected into the agent's planner prompt for every test step. Use this to share UI quirks or interaction patterns you know.
              </span>
            </div>


            <div className="step-preview-footer">
              <button
                type="button"
                className="step-confirm-btn"
                onClick={handleConfirmSteps}
                disabled={previewSteps.every((s) => !s.text.trim())}
              >
                ✅ Confirm {previewSteps.filter((s) => s.text.trim()).length} Steps
              </button>
              <button
                type="button"
                className="step-dismiss-btn"
                onClick={handleDismissPreview}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ── Demo success banner ─────────────────────────────────── */}
        {demoSuccessBanner && (
          <div className="demo-success-banner">{demoSuccessBanner}</div>
        )}

        {/* ── Execute Button ──────────────────────────────────────── */}
        <div className="execute-btn-row">
          <button
            type="button"
            className="preview-steps-btn"
            disabled={!ticketId || isRunning || previewLoading || !!previewSteps}
            onClick={handlePreviewSteps}
            title="Re-parse steps from Jira (e.g. after updating guidance)"
          >
            {previewLoading ? (
              <><span className="spinner" /> Parsing…</>
            ) : (
              "🔄 Re-parse Steps"
            )}
          </button>

          <button type="submit" className="execute-btn" disabled={isDisabled}>
            {isLoading ? (
              <>
                <span className="spinner" /> Starting...
              </>
            ) : isRunning ? (
              "🔄 Test Running..."
            ) : partialBlocked ? (
              "⚠️ Enter Missing Credential"
            ) : customCredsBlocked ? (
              "⚠️ Enter Email & Password"
            ) : previewLoading ? (
              "🔍 Parsing steps…"
            ) : previewSteps ? (
              "⏸ Confirm Steps First"
            ) : showSyncDialog ? (
              "📤 Sync decision pending…"
            ) : confirmedSteps && confirmedSteps.length > 0 ? (
              `▶ Execute (${confirmedSteps.length} confirmed steps)`
            ) : (
              "🔒 Select ticket to begin"
            )}
          </button>
        </div>
      </form>

      {showRecordDemoModal && selectedTicket && (
        <RecordDemoModal
          ticketId={selectedTicket.id}
          ticketSummary={selectedTicket.summary}
          targetUrl={targetUrl}
          onClose={handleDemoClose}
        />
      )}

      {showWizard && (
        <ClarificationWizardModal
          detectedPaths={wizardPaths}
          ambiguities={wizardAmbiguities}
          onConfirm={handleWizardConfirm}
          onSkip={handleWizardSkip}
        />
      )}
    </div>
  );
}
