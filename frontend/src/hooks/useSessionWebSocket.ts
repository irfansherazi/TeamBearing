/**
 * vQA — useSessionWebSocket
 * ==========================
 * Module: frontend/src/hooks/useSessionWebSocket.ts
 *
 * Long-lived WebSocket client for the per-session control channel at
 * /ws/session/{session_id}.  Authenticated by the HttpOnly vqa_session cookie
 * in the WS handshake (the JWT is NOT carried on the WS — ADR-10).
 *
 * Server sends:
 *   { type: "ping" }                          — heartbeat ping (15s interval)
 *   { type: "session_terminated", reason: string } — tear-down event
 *   { type: "session_state_update", state: string } — optional state changes
 *
 * Client responds to "ping" with { type: "pong" }.
 *
 * On "session_terminated", the hook calls `onTerminated(reason)`.
 * On close / error, the hook calls `onDisconnected()`.
 */

import { useEffect, useRef } from "react";

const WS_BASE = window.location.origin.replace(/^http/, "ws");

export interface UseSessionWebSocketOptions {
  sessionId: string | null;
  /** Called when the server sends session_terminated */
  onTerminated: (reason: string) => void;
  /** Called when the WS closes or errors without a clean session_terminated message */
  onDisconnected: () => void;
}

/**
 * Opens /ws/session/{sessionId} and keeps the connection alive by responding to
 * server pings.  Cleans up on unmount or when sessionId changes.
 */
export function useSessionWebSocket({
  sessionId,
  onTerminated,
  onDisconnected,
}: UseSessionWebSocketOptions): void {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    const ws = new WebSocket(`${WS_BASE}/ws/session/${sessionId}`);
    wsRef.current = ws;
    let cleanClose = false;

    ws.onmessage = (event: MessageEvent) => {
      let msg: { type: string; reason?: string; state?: string };
      try {
        msg = JSON.parse(event.data as string) as typeof msg;
      } catch {
        return; // ignore malformed messages
      }

      if (msg.type === "ping") {
        ws.send(JSON.stringify({ type: "pong" }));
      } else if (msg.type === "session_terminated") {
        cleanClose = true;
        onTerminated(msg.reason ?? "unknown");
        ws.close(1000, "session_terminated");
      }
      // session_state_update is informational; no action needed here.
    };

    ws.onerror = () => {
      if (!cleanClose) {
        onDisconnected();
      }
    };

    ws.onclose = () => {
      if (!cleanClose) {
        onDisconnected();
      }
    };

    return () => {
      cleanClose = true;
      ws.close(1000, "unmount");
      wsRef.current = null;
    };
  }, [sessionId, onTerminated, onDisconnected]);
}
