/**
 * vReview — Memory Watch Page
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { authenticatedFetch } from "../api_client";
import { MemoryWatchResultsPanel } from "../components/MemoryWatchResultsPanel";
import {
  parseReviewTableRow,
  upsertReviewRow,
  type AiReviewTableRow,
} from "../lib/aiReviewTable";
import {
  FLOW_OPTIONS,
  parseMemorySampleLine,
  parseMemoryVerdictLine,
  upsertMemorySample,
  type MemoryWatchEnv,
  type MemoryWatchFlowId,
  type MemoryWatchSample,
  type MemoryWatchVerdict,
} from "../lib/memoryWatch";
import { API_BASE_URL, WS_BASE_URL } from "../types";

type RunStatus = "idle" | "running" | "completed" | "failed";

interface MemoryWatchRunResponse {
  run_id: string;
  websocket_url: string;
}

/**
 * Memory Watch form that starts a heap check and shows live results.
 *
 * @returns The Memory Watch page
 */
export function MemoryWatchPage() {
  const [flow, setFlow] = useState<MemoryWatchFlowId>("po-open-spot");
  const [env, setEnv] = useState<MemoryWatchEnv>("qa");
  const [cycles, setCycles] = useState("5");
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [rows, setRows] = useState<AiReviewTableRow[]>([]);
  const [samples, setSamples] = useState<MemoryWatchSample[]>([]);
  const [verdict, setVerdict] = useState<MemoryWatchVerdict | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLPreElement | null>(null);
  const runStatusRef = useRef<RunStatus>("idle");
  const destroyedRef = useRef(false);
  const videoObjectUrlRef = useRef<string | null>(null);

  const cycleCount = Number.parseInt(cycles, 10);
  const canRun =
    Number.isFinite(cycleCount) &&
    cycleCount >= 1 &&
    cycleCount <= 20 &&
    runStatus !== "running";

  const setRunStatusSafe = useCallback((status: RunStatus) => {
    runStatusRef.current = status;
    setRunStatus(status);
  }, []);

  const closeSocket = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const revokeVideo = useCallback(() => {
    if (videoObjectUrlRef.current) {
      URL.revokeObjectURL(videoObjectUrlRef.current);
      videoObjectUrlRef.current = null;
    }
  }, []);

  useEffect(() => {
    destroyedRef.current = false;
    return () => {
      destroyedRef.current = true;
      closeSocket();
      revokeVideo();
    };
  }, [closeSocket, revokeVideo]);

  useEffect(() => {
    const node = logEndRef.current;
    if (node && typeof node.scrollTo === "function") {
      node.scrollTo({ top: node.scrollHeight });
    }
  }, [logLines]);

  /**
   * Fetch the run's webm as a blob URL so auth headers are included.
   *
   * @param nextRunId - Finished run id
   * @returns void
   */
  const loadVideo = useCallback(
    (nextRunId: string) => {
      authenticatedFetch(`${API_BASE_URL}/memory-watch/history/${nextRunId}/video`)
        .then(async (response) => {
          if (destroyedRef.current || !response.ok) {
            return null;
          }
          return response.blob();
        })
        .then((blob) => {
          if (destroyedRef.current || blob === null || blob.size === 0) {
            return;
          }
          revokeVideo();
          const objectUrl = URL.createObjectURL(blob);
          videoObjectUrlRef.current = objectUrl;
          setVideoUrl(objectUrl);
        })
        .catch(() => undefined);
    },
    [revokeVideo]
  );

  /**
   * Open a WebSocket to /ws/{runId} and append log lines / samples.
   *
   * @param nextRunId - Run id returned by POST /memory-watch/run
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
            const sample = parseMemorySampleLine(msg.line);
            if (sample) {
              setSamples((prev) => upsertMemorySample(prev, sample));
            }
            const nextVerdict = parseMemoryVerdictLine(msg.line);
            if (nextVerdict) {
              setVerdict(nextVerdict);
            }
            const parsed = parseReviewTableRow(msg.line);
            if (parsed) {
              setRows((prev) => upsertReviewRow(prev, parsed));
            }
          } else if (msg.type === "completed") {
            setRunStatusSafe("completed");
            loadVideo(nextRunId);
            ws.close();
          } else if (msg.type === "failed") {
            setRunStatusSafe("failed");
            loadVideo(nextRunId);
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
    [closeSocket, loadVideo, setRunStatusSafe]
  );

  /**
   * POST /memory-watch/run then stream stdout over WebSocket.
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
    revokeVideo();
    setRunError(null);
    setLogLines([]);
    setRows([]);
    setSamples([]);
    setVerdict(null);
    setVideoUrl(null);
    setRunId(null);
    setRunStatusSafe("running");

    const body = {
      flow,
      env,
      cycles: cycleCount,
    };

    authenticatedFetch(`${API_BASE_URL}/memory-watch/run`, {
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
        return response.json() as Promise<MemoryWatchRunResponse>;
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
        setRunError(err instanceof Error ? err.message : "Failed to start Memory Watch");
      });
  };

  /**
   * Ask the backend to stop the subprocess, then close the socket.
   *
   * @returns void
   */
  const handleStop = () => {
    if (runId) {
      authenticatedFetch(`${API_BASE_URL}/memory-watch/run/${runId}/stop`, {
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
          <h2>Memory Watch</h2>
          <span className="panel-badge">HEAP + VIDEO</span>
        </div>

        <form onSubmit={handleSubmit} className="execution-form">
          <div className="form-group">
            <label htmlFor="mw-flow">Flow</label>
            <select
              id="mw-flow"
              className="form-input"
              value={flow}
              onChange={(e) => setFlow(e.target.value as MemoryWatchFlowId)}
              disabled={runStatus === "running"}
            >
              {FLOW_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="mw-env">Environment</label>
            <select
              id="mw-env"
              className="form-input"
              value={env}
              onChange={(e) => {
                const next = e.target.value;
                if (next === "qa" || next === "test" || next === "smoke") {
                  setEnv(next);
                }
              }}
              disabled={runStatus === "running"}
            >
              <option value="qa">qa</option>
              <option value="test">test</option>
              <option value="smoke">smoke</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="mw-cycles">Cycles</label>
            <input
              id="mw-cycles"
              type="number"
              min={1}
              max={20}
              className="form-input"
              value={cycles}
              onChange={(e) => setCycles(e.target.value)}
              disabled={runStatus === "running"}
            />
          </div>

          {runError ? (
            <p className="ai-review-error" id="mw-error">
              {runError}
            </p>
          ) : null}

          <div className="ai-review-actions">
            <button id="mw-run-btn" type="submit" className="btn-primary" disabled={!canRun}>
              {runStatus === "running" ? "Running…" : "Run memory check"}
            </button>
            {runStatus === "running" ? (
              <button
                id="mw-stop-btn"
                type="button"
                className="btn-secondary"
                onClick={handleStop}
              >
                Stop
              </button>
            ) : null}
            <Link id="mw-history-link" className="btn-secondary" to="/memory/history">
              History
            </Link>
          </div>
        </form>
      </div>

      <MemoryWatchResultsPanel
        samples={samples}
        rows={rows}
        verdict={verdict}
        logLines={logLines}
        logEndRef={logEndRef}
        videoUrl={videoUrl}
        emptyMessage="No memory check yet."
        emptyLogMessage="Live log will appear here."
      />
    </div>
  );
}
