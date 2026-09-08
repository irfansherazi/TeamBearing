import React, { useState } from "react";
import type { PlaywrightSuiteReportResponse, PlaywrightSuiteResult, PlaywrightHealPromptResponse } from "../types";
import { authenticatedFetch } from "../api_client";
import { API_BASE_URL } from "../types";

interface SuiteResultsPanelProps {
  report: PlaywrightSuiteReportResponse;
  elapsedTimeMs?: number;
  onBack: () => void;
  onStop?: () => void;
  label?: string;
}

export function SuiteResultsPanel({ report, elapsedTimeMs, onBack, onStop, label }: SuiteResultsPanelProps) {
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [isHealing, setIsHealing] = useState(false);
  const [healPrompt, setHealPrompt] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(true);
  const [copiedNotification, setCopiedNotification] = useState(false);

  const toggleRow = (testId: string) => {
    setExpandedRows((prev) => ({
      ...prev,
      [testId]: !prev[testId],
    }));
  };

  const handleHealTests = async () => {
    setIsHealing(true);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/playwright/heal-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: report.suite_run_id }),
      });
      if (!response.ok) {
        throw new Error(`Failed to generate heal prompt: ${response.statusText}`);
      }
      const data: PlaywrightHealPromptResponse = await response.json();
      setHealPrompt(data.prompt);
      setIsModalOpen(true);
    } catch (err) {
      console.error("Error healing tests:", err);
      alert(err instanceof Error ? err.message : "Failed to generate AI healing prompt.");
    } finally {
      setIsHealing(false);
    }
  };

  // Calculate elapsed time from report started_at / completed_at if elapsedTimeMs not provided
  const getElapsedDisplay = () => {
    if (elapsedTimeMs !== undefined) {
      return `${(elapsedTimeMs / 1000).toFixed(1)}s`;
    }
    if (!report.completed_at) {
      return "Running...";
    }
    const start = new Date(report.started_at).getTime();
    const end = new Date(report.completed_at).getTime();
    return `${((end - start) / 1000).toFixed(1)}s`;
  };

  const activeDigest = report.failure_digest || (
    report.results
      ? report.results
          .filter((r) => r.status === "FAIL")
          .map((r) => ({
            test_id: r.test_id,
            name: r.name,
            error_summary: r.error_snippet ? r.error_snippet.split("\n")[0].substring(0, 120) : "No error snippet"
          }))
      : []
  );

  const handleCopySummary = () => {
    if (activeDigest.length === 0) return;

    const formattedText = activeDigest
      .map((entry, idx) => `${idx + 1}. ${entry.name}: ${entry.error_summary}`)
      .join("\n");

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(formattedText)
        .then(() => {
          setCopiedNotification(true);
          setTimeout(() => setCopiedNotification(false), 2000);
        })
        .catch((err) => {
          console.error("Clipboard API failed, falling back", err);
          fallbackCopyText(formattedText);
        });
    } else {
      fallbackCopyText(formattedText);
    }
  };

  const fallbackCopyText = (text: string) => {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
      document.execCommand("copy");
      setCopiedNotification(true);
      setTimeout(() => setCopiedNotification(false), 2000);
    } catch (err) {
      console.error("Fallback copy failed", err);
    }
    document.body.removeChild(textArea);
  };

  const showHealButton = (report.status === "completed" || report.status === "failed") && report.failed > 0;

  return (
    <div className="pw-suite-results-panel" style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Header Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 600 }}>
          {label ?? "Suite Run"}: <span style={{ fontFamily: "monospace", fontSize: "1rem", color: "var(--text-secondary)" }}>{report.suite_run_id}</span>
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {showHealButton && (
            <button
              onClick={handleHealTests}
              disabled={isHealing}
              data-testid="heal-tests-btn"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.5rem 1rem",
                background: "rgba(139, 92, 246, 0.15)",
                border: "1px solid rgba(139, 92, 246, 0.4)",
                borderRadius: "6px",
                color: "#c084fc",
                fontWeight: 500,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              {isHealing ? (
                <>
                  <span className="pw-spinner" style={{ border: "2px solid rgba(139, 92, 246, 0.3)", borderTop: "2px solid #c084fc", width: "12px", height: "12px", display: "inline-block" }} />
                  Generating...
                </>
              ) : (
                "🩹 Heal Tests"
              )}
            </button>
          )}
          {report.status === "running" && onStop && (
            <button
              onClick={onStop}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.5rem 1rem",
                background: "rgba(239, 68, 68, 0.15)",
                border: "1px solid rgba(239, 68, 68, 0.4)",
                borderRadius: "6px",
                color: "#f87171",
                fontWeight: 500,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              ⏹ Stop Suite
            </button>
          )}
          <button
            className="pw-btn-ghost"
            onClick={onBack}
            style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.5rem 1rem", border: "1px solid var(--border)", borderRadius: "4px", cursor: "pointer", background: "transparent" }}
          >
            ← Return to Library
          </button>
        </div>
      </div>

      {/* Overall Suite Outcome Banner */}
      {(report.status === "completed" || report.status === "failed") && report.outcome && (
        <div
          data-testid="overall-outcome-banner"
          style={{
            padding: "1rem 1.5rem",
            background: report.outcome === "PASS" ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)",
            border: `1px solid ${report.outcome === "PASS" ? "var(--success, #10b981)" : "var(--error, #ef4444)"}`,
            borderRadius: "8px",
            color: report.outcome === "PASS" ? "var(--success, #10b981)" : "var(--error, #ef4444)",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 700, fontSize: "1.1rem" }}>
            <span>{report.outcome === "PASS" ? "✅ SUITE RUN PASSED" : "❌ SUITE RUN FAILED"}</span>
          </div>
          {report.fail_reason && (
            <div style={{ fontSize: "0.85rem", color: "var(--text-primary, #fff)", background: "rgba(0,0,0,0.15)", padding: "0.5rem 0.75rem", borderRadius: "4px", borderLeft: "3px solid var(--error, #ef4444)", fontFamily: "monospace" }}>
              {report.fail_reason}
            </div>
          )}
        </div>
      )}

      {/* KPI Cards Summary */}
      <div className="pw-kpi-summary" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "1rem" }}>
        <div style={{ padding: "1rem", background: "var(--bg-surface, #1e1e2e)", border: "1px solid var(--border, #2e2e3e)", borderRadius: "8px", textAlign: "center" }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Total Tests</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700 }} data-testid="kpi-total">{report.total}</div>
        </div>
        <div style={{ padding: "1rem", background: "var(--bg-surface, #1e1e2e)", border: "1px solid var(--border, #2e2e3e)", borderRadius: "8px", textAlign: "center" }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Passed</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--success, #10b981)" }} data-testid="kpi-passed">{report.passed}</div>
        </div>
        <div style={{ padding: "1rem", background: "var(--bg-surface, #1e1e2e)", border: "1px solid var(--border, #2e2e3e)", borderRadius: "8px", textAlign: "center" }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Failed</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: report.failed > 0 ? "var(--error, #ef4444)" : "var(--text-secondary)" }} data-testid="kpi-failed">{report.failed}</div>
        </div>
        <div style={{ padding: "1rem", background: "var(--bg-surface, #1e1e2e)", border: "1px solid var(--border, #2e2e3e)", borderRadius: "8px", textAlign: "center" }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>Elapsed Time</div>
          <div style={{ fontSize: "1.8rem", fontWeight: 700 }} data-testid="kpi-duration">{getElapsedDisplay()}</div>
        </div>
      </div>

      {/* Progress Status Indicator */}
      {report.status === "running" && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "1rem", background: "rgba(59, 130, 246, 0.1)", border: "1px solid #3b82f6", borderRadius: "8px" }}>
          <span className="pw-spinner" style={{ border: "2px solid rgba(59, 130, 246, 0.3)", borderTop: "2px solid #3b82f6", width: "16px", height: "16px" }} />
          <span style={{ fontSize: "0.9rem", color: "#3b82f6", fontWeight: 500 }}>Suite execution in progress... Running {report.results.length} / {report.total} tests</span>
        </div>
      )}

      {/* Failure Summary Panel (AC-3, AC-4) */}
      {(report.status === "completed" || report.status === "failed") && report.failed > 0 && activeDigest.length > 0 && (
        <div 
          className="pw-failure-summary-panel"
          style={{
            background: "var(--bg-surface, #1e1e2e)",
            border: "1px solid var(--error, #ef4444)",
            borderRadius: "8px",
            padding: "1rem",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem"
          }}
          data-testid="failure-summary-panel"
        >
          <div 
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              cursor: "pointer",
              borderBottom: isSummaryExpanded ? "1px solid var(--border, #2e2e3e)" : "none",
              paddingBottom: isSummaryExpanded ? "0.5rem" : "0",
              userSelect: "none"
            }}
            onClick={() => setIsSummaryExpanded(!isSummaryExpanded)}
            data-testid="failure-summary-header"
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 700, fontSize: "1.1rem" }}>
              <span>{isSummaryExpanded ? "▼" : "▶"}</span>
              <span>❌ Failure Summary</span>
              <span style={{ fontSize: "0.85rem", padding: "0.15rem 0.4rem", background: "var(--error, #ef4444)", color: "#fff", borderRadius: "4px" }}>
                {activeDigest.length}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }} onClick={(e) => e.stopPropagation()}>
              {copiedNotification && (
                <span style={{ fontSize: "0.85rem", color: "var(--success, #10b981)", fontWeight: 500 }} data-testid="copied-badge">
                  Copied!
                </span>
              )}
              <button
                onClick={handleCopySummary}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.25rem",
                  padding: "0.35rem 0.75rem",
                  background: "var(--bg-header, #2e2e3e)",
                  border: "1px solid var(--border, #3e3e4e)",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "0.85rem",
                  color: "var(--text, #cdd6f4)"
                }}
                data-testid="copy-summary-btn"
              >
                📋 Copy Failure Summary
              </button>
            </div>
          </div>

          {isSummaryExpanded && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.5rem", maxHeight: "300px", overflowY: "auto" }} data-testid="failure-summary-list">
              {activeDigest.map((entry, idx) => (
                <div 
                  key={entry.test_id}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    padding: "0.5rem 0.75rem",
                    background: "rgba(239, 68, 68, 0.05)",
                    borderLeft: "3px solid var(--error, #ef4444)",
                    borderRadius: "0 4px 4px 0"
                  }}
                  data-testid={`failure-item-${entry.test_id}`}
                >
                  <div style={{ fontSize: "0.9rem", fontWeight: 600 }}>
                    #{idx + 1} — {entry.name} ({entry.test_id})
                  </div>
                  <div style={{ fontSize: "0.85rem", color: "var(--text-secondary, #a6adc8)", fontFamily: "monospace", marginTop: "0.25rem" }}>
                    {entry.error_summary}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Results Table */}
      <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: "8px", background: "var(--bg-surface)" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ background: "var(--bg-header)", borderBottom: "1px solid var(--border)" }}>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600 }}>Test Name</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600, width: "100px" }}>Status</th>
              <th style={{ padding: "0.75rem 1rem", fontWeight: 600, width: "120px" }}>Duration</th>
            </tr>
          </thead>
          <tbody>
            {report.results.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: "2rem", textAlign: "center", color: "var(--text-secondary)" }}>
                  Waiting for tests to complete...
                </td>
              </tr>
            ) : (
              report.results.map((result: PlaywrightSuiteResult) => {
                const isFailed = result.status === "FAIL";
                const isRunning = result.status === "RUNNING";
                const isPending = result.status === "PENDING";
                const isExpanded = !!expandedRows[result.test_id];

                let badgeBg = "rgba(16, 185, 129, 0.1)";
                let badgeColor = "var(--success, #10b981)";
                if (isFailed) {
                  badgeBg = "rgba(239, 68, 68, 0.1)";
                  badgeColor = "var(--error, #ef4444)";
                } else if (isRunning) {
                  badgeBg = "rgba(59, 130, 246, 0.1)";
                  badgeColor = "#3b82f6";
                } else if (isPending) {
                  badgeBg = "rgba(156, 163, 175, 0.1)";
                  badgeColor = "var(--text-secondary, #9ca3af)";
                }

                return (
                  <React.Fragment key={result.test_id}>
                    <tr
                      onClick={isFailed ? () => toggleRow(result.test_id) : undefined}
                      style={{
                        borderBottom: "1px solid var(--border)",
                        cursor: isFailed ? "pointer" : "default",
                        background: isFailed ? "rgba(239, 68, 68, 0.03)" : "transparent",
                        transition: "background 0.2s",
                      }}
                      className={isFailed ? "hover-highlight" : ""}
                    >
                      <td style={{ padding: "0.75rem 1rem", fontWeight: 500 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          {isFailed && (
                            <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)", transition: "transform 0.2s", transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block" }}>
                              ▶
                            </span>
                          )}
                          <span>{result.name}</span>
                          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontFamily: "monospace" }}>({result.test_id})</span>
                        </div>
                      </td>
                      <td style={{ padding: "0.75rem 1rem" }}>
                        <span
                          className={`pw-badge-${result.status.toLowerCase()}`}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.25rem",
                            padding: "0.25rem 0.5rem",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            background: badgeBg,
                            color: badgeColor,
                          }}
                        >
                          {isRunning && (
                            <span className="pw-spinner" style={{ border: "1px solid rgba(59, 130, 246, 0.3)", borderTop: "1px solid #3b82f6", width: "8px", height: "8px", display: "inline-block" }} />
                          )}
                          {result.status}
                        </span>
                      </td>
                      <td style={{ padding: "0.75rem 1rem", fontFamily: "monospace" }}>
                        {isPending || isRunning ? "-" : `${(result.duration_ms / 1000).toFixed(2)}s`}
                      </td>
                    </tr>
                    {isFailed && isExpanded && (
                      <tr style={{ background: "rgba(239, 68, 68, 0.05)" }}>
                        <td colSpan={3} style={{ padding: "1rem", borderBottom: "1px solid var(--border)" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                            <strong style={{ fontSize: "0.8rem", color: "var(--error)" }}>Error Output snippet:</strong>
                            <pre
                              style={{
                                margin: 0,
                                padding: "0.75rem",
                                background: "rgba(0,0,0,0.2)",
                                borderRadius: "4px",
                                fontSize: "0.8rem",
                                fontFamily: "monospace",
                                whiteSpace: "pre-wrap",
                                overflowX: "auto",
                                color: "var(--text-primary, #fff)",
                                borderLeft: "3px solid var(--error, #ef4444)",
                              }}
                              data-testid="error-snippet"
                            >
                              {result.error_snippet || "No standard error details captured."}
                            </pre>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {isModalOpen && healPrompt && (
        <HealTestsModal prompt={healPrompt} onClose={() => setIsModalOpen(false)} />
      )}
    </div>
  );
}

interface HealTestsModalProps {
  prompt: string;
  onClose: () => void;
}

export function HealTestsModal({ prompt, onClose }: HealTestsModalProps) {
  const [copySuccess, setCopySuccess] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Clipboard copy failed, using fallback selection:", err);
    }
  };

  return (
    <div
      className="heal-modal-overlay"
      data-testid="heal-modal"
      onClick={onClose}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(9, 13, 22, 0.8)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        className="heal-modal-container"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#111827",
          border: "1px solid #374151",
          borderRadius: "12px",
          width: "90%",
          maxWidth: "750px",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7)",
          padding: "1.5rem",
          gap: "1rem",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #374151", paddingBottom: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, color: "#c084fc", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            🩹 AI Test Healing Prompt
          </h3>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              color: "#9ca3af",
              fontSize: "1.2rem",
              cursor: "pointer",
              padding: "0.25rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            data-testid="modal-close-x"
          >
            ✕
          </button>
        </div>

        {/* Instructions */}
        <p style={{ margin: 0, fontSize: "0.85rem", color: "#9ca3af" }}>
          Copy the compiled context-rich prompt below and paste it into Claude, Gemini, or your preferred AI coding assistant to automatically generate healed test code.
        </p>

        {/* Monospace area */}
        <textarea
          readOnly
          value={prompt}
          onClick={(e) => {
            (e.target as HTMLTextAreaElement).select();
          }}
          data-testid="heal-prompt-textarea"
          style={{
            background: "#030712",
            border: "1px solid #1f2937",
            borderRadius: "8px",
            padding: "1rem",
            fontFamily: "monospace",
            fontSize: "0.85rem",
            color: "#e5e7eb",
            height: "300px",
            resize: "none",
            outline: "none",
            width: "100%",
            boxSizing: "border-box",
          }}
        />

        {/* Footer actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", borderTop: "1px solid #374151", paddingTop: "0.75rem" }}>
          <button
            onClick={onClose}
            className="pw-btn-ghost"
            style={{
              padding: "0.5rem 1rem",
              border: "1px solid #475569",
              borderRadius: "6px",
              background: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
            }}
          >
            Close
          </button>
          <button
            onClick={handleCopy}
            style={{
              padding: "0.5rem 1.25rem",
              borderRadius: "6px",
              border: "none",
              background: copySuccess ? "#10b981" : "#8b5cf6",
              color: "#ffffff",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              transition: "background-color 0.2s",
            }}
            data-testid="copy-prompt-btn"
          >
            {copySuccess ? "✅ Copied!" : "📋 Copy Prompt"}
          </button>
        </div>
      </div>
    </div>
  );
}
