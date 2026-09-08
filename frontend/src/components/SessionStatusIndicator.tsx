/**
 * vQA — SessionStatusIndicator
 * =============================
 * Module: frontend/src/components/SessionStatusIndicator.tsx
 *
 * A small status dot rendered in the header that reflects the current session
 * lifecycle state.  Colour semantics:
 *   green  — attached (normal operation)
 *   yellow — bootstrapping / capacity_reached (transitional)
 *   red    — terminated / error (action required)
 *   grey   — no session context (legacy / pre-auth mode)
 *
 * Does not throw if useSession() is unavailable — renders grey and is silent.
 */

import type { JSX } from "react";
import { useSession } from "../context/SessionContext";
import type { SessionState } from "../context/SessionContext";

// ---------------------------------------------------------------------------
// Colour map
// ---------------------------------------------------------------------------

const STATE_COLORS: Record<SessionState | "unknown", string> = {
  attached: "#22c55e",        // green-500
  bootstrapping: "#eab308",   // yellow-500
  capacity_reached: "#eab308",
  terminated: "#ef4444",      // red-500
  error: "#ef4444",
  unknown: "#9ca3af",         // gray-400
};

const STATE_LABELS: Record<SessionState | "unknown", string> = {
  attached: "Session active",
  bootstrapping: "Connecting session…",
  capacity_reached: "At capacity — waiting for a slot",
  terminated: "Session terminated",
  error: "Session error",
  unknown: "No session",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SessionStatusIndicatorProps {
  /** Optional className override for the outer <span> wrapper */
  className?: string;
}

export function SessionStatusIndicator({ className }: SessionStatusIndicatorProps): JSX.Element {
  let state: SessionState | "unknown" = "unknown";
  let novncUrl: string | null = null;

  try {
    const session = useSession();
    state = session.sessionState;
    novncUrl = session.novncUrl;
  } catch {
    // useSession threw — we're outside SessionProvider (legacy mode). Render grey.
  }

  const color = STATE_COLORS[state];
  const label = STATE_LABELS[state];

  return (
    <span
      className={className}
      title={label}
      aria-label={label}
      data-testid="session-status-indicator"
      data-state={state}
      data-novnc-url={novncUrl ?? ""}
      style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}
    >
      <span
        style={{
          display: "inline-block",
          width: "10px",
          height: "10px",
          borderRadius: "50%",
          backgroundColor: color,
          flexShrink: 0,
        }}
      />
    </span>
  );
}
