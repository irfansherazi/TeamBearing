/**
 * vQA — Live Browser Component
 * ==============================
 * Module: frontend/src/components/LiveBrowser.tsx
 *
 * Displays the live browser view by streaming screenshots from the backend
 * via WebSocket (WSScreenshotMessage). This approach works on all platforms
 * (macOS, Linux, Windows, Docker) without requiring Xvfb or noVNC.
 *
 * Session isolation: when the caller is inside a <SessionProvider> and a
 * session is attached, we render the caller's *own* per-session noVNC URL
 * (session.novncUrl) rather than whatever URL happens to live on the run
 * status. This closes the "user B attaches to user A's browser" bug at
 * the render seam. The vncUrl prop remains for the legacy singleton path
 * (SESSION_ISOLATION_ENABLED=false) and for tests that render without a
 * SessionProvider.
 */

import { useOptionalSession } from "../context/SessionContext";

interface LiveBrowserProps {
  /** Latest base64 PNG screenshot from the planner (empty string if none yet) */
  latestScreenshot: string;
  /** AC step currently being executed */
  acStep: number;
  /** Total number of AC steps */
  acTotal: number;
  /** Whether a test run is currently active */
  isRunning: boolean;
  /** Legacy noVNC URL (from run status). Only used when no SessionProvider is mounted. */
  vncUrl?: string | null;
}

export function LiveBrowser({
  latestScreenshot,
  acStep,
  acTotal,
  isRunning,
  vncUrl,
}: LiveBrowserProps) {
  // Prefer the session-scoped noVNC URL when a SessionProvider is mounted
  // and the session is attached. Falls back to the legacy prop otherwise.
  const session = useOptionalSession();
  const effectiveVncUrl =
    session && session.sessionState === "attached" && session.novncUrl
      ? session.novncUrl
      : vncUrl ?? null;
  // State 1: No run active
  if (!isRunning && !latestScreenshot && !effectiveVncUrl) {
    return (
      <div className="panel live-browser">
        <div className="panel-header">
          <h2>🖥️ Live Browser</h2>
        </div>
        <div className="browser-placeholder">
          <div className="placeholder-icon">🌐</div>
          <p className="placeholder-text">
            Start a test execution to see the live browser stream
          </p>
          <p className="placeholder-hint">
            Screenshots are streamed in real-time as the agent navigates
          </p>
        </div>
      </div>
    );
  }

  // State 2: Run started but no screenshot yet AND no VNC URL (browser still launching)
  if (isRunning && !latestScreenshot && !effectiveVncUrl) {
    return (
      <div className="panel live-browser">
        <div className="panel-header">
          <h2>🖥️ Live Browser</h2>
          <span className="live-indicator">
            <span className="live-dot" /> Starting...
          </span>
        </div>
        <div className="browser-placeholder">
          <div className="placeholder-icon spinning">⚙️</div>
          <p className="placeholder-text">Launching browser...</p>
          <p className="placeholder-hint">First screenshot will appear momentarily</p>
        </div>
      </div>
    );
  }

  // State 3: Screenshot available — show live view
  const progressLabel = acTotal > 0
    ? `Step ${acStep} / ${acTotal}`
    : "Running...";

  return (
    <div className="panel live-browser">
      <div className="panel-header">
        <h2>🖥️ Live Browser</h2>
        <div className="browser-controls">
          <span className="live-indicator">
            <span className="live-dot" /> LIVE
          </span>
          <span className="ac-progress-badge">{progressLabel}</span>
        </div>
      </div>
      <div className="browser-frame screenshot-stream">
        {effectiveVncUrl ? (
          <iframe
            src={effectiveVncUrl}
            title="Live Browser Stream"
            className="browser-vnc-frame"
            style={{
              width: "100%",
              height: "100%",
              minHeight: "500px",
              border: "none",
              backgroundColor: "#000",
            }}
          />
        ) : (
          <img
            src={`data:image/png;base64,${latestScreenshot}`}
            alt="Live browser screenshot"
            className="screenshot-img"
          />
        )}
      </div>
    </div>
  );
}
