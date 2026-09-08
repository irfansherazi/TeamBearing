import React, { useEffect, useRef, useState } from "react";
import type { CodegenStartResponse, CodegenDoneEvent, CodegenTransformations } from "../types";
import { API_BASE_URL, WS_BASE_URL } from "../types";
import { authenticatedFetch } from "../api_client";

function formatTransformations(t: CodegenTransformations): string {
  const parts: string[] = [];
  if (t.auth_applied) parts.push("Auth fixture");
  if (t.date_helpers > 0) parts.push(`${t.date_helpers} date helper${t.date_helpers !== 1 ? "s" : ""}`);
  if (t.nav_helpers > 0) parts.push(`${t.nav_helpers} nav helper${t.nav_helpers !== 1 ? "s" : ""}`);
  if (t.captcha_helpers > 0) parts.push(`${t.captcha_helpers} CAPTCHA helper${t.captcha_helpers !== 1 ? "s" : ""}`);
  if (t.fragile_warnings > 0) parts.push(`${t.fragile_warnings} ⚠️ FRAGILE`);
  return parts.length > 0 ? parts.join(" · ") : "None";
}

interface RecordDemoModalProps {
  ticketId: string;
  ticketSummary: string;
  targetUrl: string;
  onClose: () => void;
}

type Phase = "starting" | "recording" | "saving" | "confirm_pr" | "submitting_pr" | "done" | "error";

function closeWs(wsRef: React.MutableRefObject<WebSocket | null>) {
  const ws = wsRef.current;
  if (!ws) return;
  ws.onclose = null;
  ws.onerror = null;
  wsRef.current = null;
  ws.close();
}

export function RecordDemoModal({
  ticketId,
  ticketSummary,
  targetUrl,
  onClose,
}: RecordDemoModalProps) {
  const [phase, setPhase] = useState<Phase>("starting");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [result, setResult] = useState<CodegenDoneEvent | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [novncUrl, setNovncUrl] = useState<string | null>(null);
  const [latestScreenshot, setLatestScreenshot] = useState<string>("");
  const [pendingPrInfo, setPendingPrInfo] = useState<{test_file: string; test_path: string; lines: number} | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Latest-value refs for unmount cancel without dep-based effects
  const sessionIdRef = useRef<string | null>(null);
  const phaseRef = useRef<Phase>("starting");
  sessionIdRef.current = sessionId;
  phaseRef.current = phase;

  // Start playwright codegen session on mount
  useEffect(() => {
    const controller = new AbortController();

    (async () => {
      try {
        const res = await authenticatedFetch(`${API_BASE_URL}/codegen/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            ticket_id: ticketId,
            ticket_summary: ticketSummary,
            target_url: targetUrl,
          }),
        });
        if (!res.ok) throw new Error(`Failed to start session: ${res.status}`);
        const data: CodegenStartResponse = await res.json();

        setSessionId(data.session_id);
        if (data.novnc_url) setNovncUrl(data.novnc_url);
        setPhase("recording");

        const ws = new WebSocket(`${WS_BASE_URL}/ws/codegen/${data.session_id}`);
        wsRef.current = ws;

        ws.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          if (msg.type === "saving") {
            setPhase("saving");
          } else if (msg.type === "ready_for_pr") {
            setPendingPrInfo({ test_file: msg.test_file, test_path: msg.test_path, lines: msg.lines });
            setPhase("confirm_pr");
          } else if (msg.type === "recording_done") {
            const { type: _, ...done } = msg;
            setResult(done as CodegenDoneEvent);
            setPhase("done");
          } else if (msg.type === "error") {
            if (wsRef.current === ws) wsRef.current = null;
            setErrorMessage(msg.message ?? "An unknown error occurred.");
            setPhase("error");
          } else if (msg.type === "hitl_screenshot" && msg.data) {
            // Fallback screenshot stream when noVNC isn't available (local dev)
            setLatestScreenshot(msg.data);
          }
        };
        ws.onerror = () => {
          if (!controller.signal.aborted && wsRef.current === ws) {
            wsRef.current = null;
            setErrorMessage("Action stream connection failed.");
            setPhase("error");
          }
        };
        ws.onclose = () => {
          if (!controller.signal.aborted && wsRef.current === ws) {
            wsRef.current = null;
            setPhase((prev) => (prev === "recording" ? "error" : prev));
            setErrorMessage((prev) =>
              prev ?? "Stream closed unexpectedly. Check if the test was saved."
            );
          }
        };
      } catch (err) {
        if (controller.signal.aborted) return;
        setErrorMessage(err instanceof Error ? err.message : String(err));
        setPhase("error");
      }
    })();

    return () => {
      controller.abort();
      closeWs(wsRef);
    };
  }, []);

  // Cancel the backend session on true unmount (if still recording)
  useEffect(() => {
    return () => {
      const sid = sessionIdRef.current;
      const ph = phaseRef.current;
      if (sid && (ph === "recording" || ph === "starting")) {
        authenticatedFetch(`${API_BASE_URL}/codegen/${sid}/cancel`, { method: "POST" });
      }
    };
  }, []);

  return (
    <div className="record-demo-overlay">
      <div className="record-demo-modal">

        {/* ── Starting ── */}
        {phase === "starting" && (
          <div className="record-demo-centered">
            <span className="spinner" />
            <p>Launching Playwright browser…</p>
          </div>
        )}

        {/* ── Recording ── */}
        {phase === "recording" && (
          <>
            <div className="record-demo-header">
              <span className="record-demo-title">
                Recording
                <span className="record-dot" />
              </span>
              <span className="record-demo-ticket-id">{ticketId}</span>
            </div>

            {/* ── Live browser pane (noVNC iframe or screenshot fallback) ── */}
            {(novncUrl || latestScreenshot) && (
              <div className="record-demo-vnc-pane">
                {novncUrl ? (
                  <iframe
                    src={novncUrl}
                    title="Live Playwright Browser"
                    className="record-demo-vnc-iframe"
                    allow="clipboard-read; clipboard-write"
                  />
                ) : (
                  <img
                    src={`data:image/png;base64,${latestScreenshot}`}
                    alt="Live browser screenshot"
                    className="record-demo-vnc-screenshot"
                  />
                )}
              </div>
            )}

            <div className="record-demo-body record-demo-instructions">
              <div className="record-demo-instruction-card">
                <div className="record-demo-instruction-title">Playwright is recording your steps</div>
                <p>
                  Perform the test steps for <strong>{ticketSummary}</strong>, then click{" "}
                  <strong>Finish Recording</strong>. vQA will save the test and prompt you to open a
                  pull request.
                </p>
                {novncUrl ? (
                  <p className="record-demo-novnc-hint">
                    The live browser is embedded above — interact with it directly.
                  </p>
                ) : (
                  <p className="record-demo-novnc-hint">
                    A browser window has opened on your screen.
                  </p>
                )}
                <ul className="record-demo-checklist">
                  <li>Every click, navigation, and form fill is captured</li>
                  <li>The generated TypeScript test is saved to <code>playwright/tests/</code></li>
                  <li>A pull request is opened automatically</li>
                </ul>
              </div>
            </div>
            <div className="record-demo-footer">
              <button type="button" className="btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={!sessionId}
                onClick={async () => {
                  if (!sessionId) return;
                  await authenticatedFetch(`${API_BASE_URL}/codegen/${sessionId}/finish`, { method: "POST" });
                }}
              >
                Finish Recording
              </button>
            </div>
          </>
        )}

        {/* ── Saving / committing ── */}
        {(phase === "saving" || phase === "submitting_pr") && (
          <div className="record-demo-centered">
            <span className="spinner" />
            <p>{phase === "submitting_pr" ? "Submitting pull request…" : "Saving test…"}</p>
          </div>
        )}

        {/* ── Confirm PR ── */}
        {phase === "confirm_pr" && pendingPrInfo && (
          <>
            <div className="record-demo-header">
              <span className="record-demo-title">Test Recorded</span>
              <span className="record-demo-ticket-id">{ticketId}</span>
            </div>
            <div className="record-demo-body">
              <div className="record-demo-instruction-card">
                <div className="record-demo-instruction-title">Submit a pull request?</div>
                <p>
                  The recorded test has been saved to{" "}
                  <code>{pendingPrInfo.test_path}</code> ({pendingPrInfo.lines} lines).
                </p>
                <p>Would you like to open a pull request on GitHub?</p>
              </div>
            </div>
            <div className="record-demo-footer">
              <button
                type="button"
                className="btn-secondary"
                onClick={async () => {
                  if (!sessionId) return;
                  await authenticatedFetch(`${API_BASE_URL}/codegen/${sessionId}/skip-pr`, { method: "POST" });
                }}
              >
                Save without PR
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={async () => {
                  if (!sessionId) return;
                  setPhase("submitting_pr");
                  await authenticatedFetch(`${API_BASE_URL}/codegen/${sessionId}/confirm-pr`, { method: "POST" });
                }}
              >
                Submit PR
              </button>
            </div>
          </>
        )}

        {/* ── Done ── */}
        {phase === "done" && result && (
          <>
            <div className="record-demo-header">
              <span className="record-demo-title record-demo-title--success">
                ✓ Test Saved
              </span>
            </div>
            <div className="record-demo-body record-demo-done">
              <div className="record-demo-result-card">
                <div className="record-demo-result-row">
                  <span className="record-demo-result-label">Test file</span>
                  <code className="record-demo-result-value">{result.test_path}</code>
                </div>
                <div className="record-demo-result-row">
                  <span className="record-demo-result-label">Commit</span>
                  <code className="record-demo-result-value">{result.commit_hash}</code>
                </div>
                <div className="record-demo-result-row">
                  <span className="record-demo-result-label">Pull Request</span>
                  <a className="record-demo-result-value" href={result.pr_url} target="_blank" rel="noreferrer">{result.pr_url}</a>
                </div>
                <div className="record-demo-result-row">
                  <span className="record-demo-result-label">Lines generated</span>
                  <span className="record-demo-result-value">{result.lines}</span>
                </div>
                <div className="record-demo-result-row">
                  <span className="record-demo-result-label">Run recorded</span>
                  <span className="record-demo-result-value record-demo-passed">Passed ✓</span>
                </div>
                {result.transformations && (
                  <div className="record-demo-result-row">
                    <span className="record-demo-result-label">Transformations</span>
                    <span className="record-demo-result-value">{formatTransformations(result.transformations)}</span>
                  </div>
                )}
              </div>
            </div>
            <div className="record-demo-footer">
              <button type="button" className="btn-primary" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}

        {/* ── Error ── */}
        {phase === "error" && (
          <>
            <div className="record-demo-header">
              <span className="record-demo-title">Recording Error</span>
            </div>
            <div className="record-demo-body">
              <div className="record-demo-error">{errorMessage}</div>
            </div>
            <div className="record-demo-footer">
              <button type="button" className="btn-secondary" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}

      </div>
    </div>
  );
}
