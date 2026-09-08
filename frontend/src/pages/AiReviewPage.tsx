/**
 * vReview — AI Review Page
 * ========================
 * Module: frontend/src/pages/AiReviewPage.tsx
 *
 * Starts an AI Review run, streams the PASS/FAIL table plus live log.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { authenticatedFetch } from "../api_client";
import { AiReviewResultsPanel } from "../components/AiReviewResultsPanel";
import {
  parseReviewTableRow,
  upsertReviewRow,
  type AiReviewTableRow,
} from "../lib/aiReviewTable";
import { API_BASE_URL, WS_BASE_URL } from "../types";

const DEFAULT_BASE_BRANCH = "Develop";

type ReviewApp = "platform" | "vcapi";

const APP_DEFAULT_BASE: Record<ReviewApp, string> = {
  platform: "Develop",
  vcapi: "develop",
};

type RunStatus = "idle" | "running" | "completed" | "failed";

interface AiReviewRunResponse {
  run_id: string;
  websocket_url: string;
}

/**
 * AI Review form that starts a review run and shows live results.
 *
 * @returns The AI Review page
 */
export function AiReviewPage() {
  const [branch, setBranch] = useState("");
  const [commits, setCommits] = useState("");
  const [app, setApp] = useState<ReviewApp>("platform");
  const [base, setBase] = useState(DEFAULT_BASE_BRANCH);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [rows, setRows] = useState<AiReviewTableRow[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLPreElement | null>(null);
  const runStatusRef = useRef<RunStatus>("idle");
  const destroyedRef = useRef(false);

  const canRun = branch.trim().length > 0 && runStatus !== "running";

  const setRunStatusSafe = useCallback((status: RunStatus) => {
    runStatusRef.current = status;
    setRunStatus(status);
  }, []);

  const closeSocket = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    destroyedRef.current = false;
    return () => {
      destroyedRef.current = true;
      closeSocket();
    };
  }, [closeSocket]);

  useEffect(() => {
    const node = logEndRef.current;
    if (node && typeof node.scrollTo === "function") {
      node.scrollTo({ top: node.scrollHeight });
    }
  }, [logLines]);

  /**
   * Open a WebSocket to /ws/{runId} and append log lines / table rows.
   *
   * @param nextRunId - Run id returned by POST /ai-review/run
   * @returns void
   */
  const connectStream = useCallback(
    (nextRunId: string) => {
      closeSocket();
      const ws = new WebSocket(`${WS_BASE_URL}/ws/${nextRunId}`);
      wsRef.current = ws;

      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(event.data) as {
            type?: string;
            line?: string;
          };
          if (msg.type === "terminal_log" && msg.line) {
            setLogLines((prev) => [...prev, msg.line]);
            const parsed = parseReviewTableRow(msg.line);
            if (parsed) {
              setRows((prev) => upsertReviewRow(prev, parsed));
            }
          } else if (msg.type === "completed") {
            setRunStatusSafe("completed");
            ws.close();
          } else if (msg.type === "failed") {
            setRunStatusSafe("failed");
            ws.close();
          }
        } catch {
          setLogLines((prev) => [...prev, event.data]);
        }
      };

      ws.onerror = () => {
        setRunStatusSafe("failed");
        setRunError("WebSocket connection error");
      };

      ws.onclose = () => {
        if (runStatusRef.current === "running") {
          setRunStatusSafe("failed");
        }
      };
    },
    [closeSocket, setRunStatusSafe]
  );

  /**
   * POST /ai-review/run then stream stdout over WebSocket.
   *
   * @param event - Form submit event
   * @returns void
   */
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canRun) {
      return;
    }

    closeSocket();
    setRunError(null);
    setLogLines([]);
    setRows([]);
    setRunId(null);
    setRunStatusSafe("running");

    const body = {
      app,
      branch: branch.trim(),
      commits: commits.trim(),
      base: base.trim() || APP_DEFAULT_BASE[app],
    };

    authenticatedFetch(`${API_BASE_URL}/ai-review/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (response) => {
        if (destroyedRef.current) {
          return null;
        }
        if (!response.ok) {
          const payload = (await response.json().catch(() => ({ detail: "Unknown error" }))) as {
            detail?: string;
          };
          throw new Error(payload.detail ?? `HTTP ${response.status}`);
        }
        return response.json() as Promise<AiReviewRunResponse>;
      })
      .then((data) => {
        if (destroyedRef.current || data === null) {
          return;
        }
        setRunId(data.run_id);
        connectStream(data.run_id);
      })
      .catch((err: unknown) => {
        if (destroyedRef.current) {
          return;
        }
        setRunStatusSafe("failed");
        setRunError(err instanceof Error ? err.message : "Failed to start review");
      });
  };

  /**
   * Ask the backend to stop the subprocess, then close the socket.
   *
   * @returns void
   */
  const handleStop = () => {
    if (runId) {
      authenticatedFetch(`${API_BASE_URL}/ai-review/run/${runId}/stop`, {
        method: "POST",
      }).catch(() => undefined);
    }
    closeSocket();
    setRunStatusSafe("failed");
  };

  return (
    <div className="ai-review-page">
      <div className="panel select-card">
        <div className="panel-header">
          <h2>AI Review</h2>
          <span className="panel-badge">vSUITE STANDARDS</span>
        </div>

        <form onSubmit={handleSubmit} className="execution-form">
          <div className="form-group">
            <label htmlFor="ai-review-app">App</label>
            <select
              id="ai-review-app"
              className="form-input"
              value={app}
              onChange={(e) => {
                const nextApp = e.target.value === "vcapi" ? "vcapi" : "platform";
                setApp(nextApp);
                setBase(APP_DEFAULT_BASE[nextApp]);
              }}
              disabled={runStatus === "running"}
            >
              <option value="platform">vsuitePlatform</option>
              <option value="vcapi">vcapi</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="ai-review-branch">Branch</label>
            <input
              id="ai-review-branch"
              type="text"
              className="form-input"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="feature/my-branch"
              autoComplete="off"
              disabled={runStatus === "running"}
            />
          </div>

          <div className="form-group">
            <label htmlFor="ai-review-commits">Commits (optional)</label>
            <input
              id="ai-review-commits"
              type="text"
              className="form-input"
              value={commits}
              onChange={(e) => setCommits(e.target.value)}
              placeholder="abc123,def456"
              autoComplete="off"
              disabled={runStatus === "running"}
            />
          </div>

          <div className="form-group">
            <label htmlFor="ai-review-base">Base branch</label>
            <input
              id="ai-review-base"
              type="text"
              className="form-input"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder={APP_DEFAULT_BASE[app]}
              autoComplete="off"
              disabled={runStatus === "running"}
            />
          </div>

          {runError ? (
            <p className="ai-review-error" id="ai-review-error">
              {runError}
            </p>
          ) : null}

          <div className="ai-review-actions">
            <button
              id="ai-review-run-btn"
              type="submit"
              className="btn-primary"
              disabled={!canRun}
            >
              {runStatus === "running" ? "Running…" : "Run review"}
            </button>
            {runStatus === "running" ? (
              <button
                id="ai-review-stop-btn"
                type="button"
                className="btn-secondary"
                onClick={handleStop}
              >
                Stop
              </button>
            ) : null}
          </div>
        </form>
      </div>

      <AiReviewResultsPanel
        rows={rows}
        logLines={logLines}
        logEndRef={logEndRef}
        emptyMessage="No review run yet."
        emptyLogMessage="Live log will appear here."
      />
    </div>
  );
}
