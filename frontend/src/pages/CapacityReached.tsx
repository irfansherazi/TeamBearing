/**
 * vQA — CapacityReached
 * ======================
 * Module: frontend/src/pages/CapacityReached.tsx
 *
 * Full-page state rendered when POST /api/session/start returns 409 (all
 * MAX_CONCURRENT_SESSIONS slots are occupied).  Auto-retries every 15s ± 2s
 * jitter.  Provides a "Retry now" button for impatient users.
 */

import { useCallback, useEffect, useState, type JSX } from "react";
import { useSession } from "../context/SessionContext";

const RETRY_INTERVAL_SECONDS = 15;
const JITTER_SECONDS = 2;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CapacityReached(): JSX.Element {
  const { retry } = useSession();
  const [countdown, setCountdown] = useState<number>(RETRY_INTERVAL_SECONDS);

  const scheduleRetry = useCallback(() => {
    const jitter = Math.random() * JITTER_SECONDS;
    const interval = Math.round((RETRY_INTERVAL_SECONDS + jitter) * 10) / 10;
    setCountdown(Math.round(interval));
    return interval;
  }, []);

  // Countdown timer — decrements every second, triggers retry at 0.
  useEffect(() => {
    const interval = scheduleRetry();
    let remaining = Math.round(interval);

    const tick = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining);
      if (remaining <= 0) {
        clearInterval(tick);
        retry();
      }
    }, 1000);

    return () => clearInterval(tick);
  }, [retry, scheduleRetry]);

  const handleRetryNow = useCallback(() => {
    retry();
  }, [retry]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        gap: "24px",
        padding: "32px",
        textAlign: "center",
        fontFamily: "system-ui, sans-serif",
      }}
      data-testid="capacity-reached-page"
    >
      <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0 }}>
        vQA is at capacity
      </h1>
      <p style={{ color: "#6b7280", maxWidth: "480px", margin: 0 }}>
        All browser sessions are currently in use. You will be automatically
        placed into an active session when one becomes available.
      </p>
      <p style={{ color: "#374151", fontWeight: 500, margin: 0 }}>
        Retrying in{" "}
        <span data-testid="countdown" style={{ fontVariantNumeric: "tabular-nums" }}>
          {countdown}s
        </span>
      </p>
      <button
        onClick={handleRetryNow}
        data-testid="retry-now-button"
        style={{
          padding: "10px 24px",
          backgroundColor: "#2563eb",
          color: "#fff",
          border: "none",
          borderRadius: "6px",
          cursor: "pointer",
          fontWeight: 600,
          fontSize: "0.95rem",
        }}
      >
        Retry now
      </button>
    </div>
  );
}
