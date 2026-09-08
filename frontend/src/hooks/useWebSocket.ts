/**
 * vQA — WebSocket Hook
 * =====================
 * Module: frontend/src/hooks/useWebSocket.ts
 *
 * Custom React hook for real-time WebSocket log streaming from the
 * vQA backend.  Connects to `/ws/{run_id}` and provides:
 *
 * - Real-time step messages as they arrive
 * - Connection state tracking (connecting → connected → closed)
 * - Auto-reconnection on connection loss
 * - Terminal message handling (completed/failed)
 *
 * Architecture Context:
 * The backend broadcasts WSStepMessage after each browser action
 * and WSTerminalMessage when the run completes.  This hook manages
 * the WebSocket lifecycle and provides typed message arrays to
 * consuming components (ExecutionLog, Dashboard).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  WSAcProgressMessage,
  WSAcStep,
  HitlActionRecord,
  WSGhostCredentialsMessage,
  WSHitlActionRecordedMessage,
  WSHitlDialogMessage,
  WSHitlScreenshotMessage,
  WSHumanTakeoverMessage,
  WSMessage,
  WSPersonaCredentialsMessage,
  WSScreenshotMessage,
  WSStepMessage,
  WSTerminalMessage,
  WSThinkingMessage,
  WSTriageMessage,
} from "../types";
import { WS_BASE_URL } from "../types";


/** WebSocket connection state */
export type WSConnectionState = "idle" | "connecting" | "connected" | "closed" | "error";

/** Return type of useWebSocket hook */
export interface UseWebSocketReturn {
  connectionState: WSConnectionState;
  steps: WSStepMessage[];
  acProgress: WSAcStep[];
  terminalMessage: WSTerminalMessage | null;
  latestScreenshot: string;
  screenshotAcStep: number;
  screenshotAcTotal: number;
  /** Real-time HITL screencast frame (JPEG) */
  hitlScreenshot: string;
  /** Echoed human actions captured during takeover */
  hitlActions: HitlActionRecord[];
  /** Intercepted browser dialog */
  hitlDialog: WSHitlDialogMessage | null;
  /** Whether the agent is currently reasoning (between steps) */
  isThinking: boolean;
  /** The current reasoning text */
  thinkingText: string;
  thinkingAcStep: number;
  thinkingAcTotal: number;
  /** Failure triage analysis (null if run passed) */
  triageMessage: WSTriageMessage | null;
  /** Human takeover request from agent (null when not stuck) */
  humanTakeoverMessage: WSHumanTakeoverMessage | null;
  /** Persona HITL credential request (null when not needed) */
  personaCredentialsMessage: WSPersonaCredentialsMessage | null;
  /** Ghost Login admin credential request (null when not needed) */
  ghostCredentialsMessage: WSGhostCredentialsMessage | null;
  /** The raw WebSocket instance (null when idle) — share with child components */
  wsSocket: WebSocket | null;
  connect: (runId: string) => void;
  disconnect: () => void;
  /** Clear all run state (steps, log, terminal, screenshots) without touching the socket */
  resetState: () => void;
}


/**
 * Custom hook for real-time WebSocket log streaming.
 *
 * Connects to the backend WebSocket at `/ws/{run_id}` and collects
 * incoming messages into typed arrays.
 *
 * @returns {UseWebSocketReturn} Connection state, step messages,
 *          terminal message, and connect/disconnect functions.
 *
 * @example
 * ```tsx
 * const { connectionState, steps, terminalMessage, connect } = useWebSocket();
 *
 * // Connect when a run starts
 * useEffect(() => {
 *   if (runId) connect(runId);
 * }, [runId]);
 *
 * // Render steps
 * return steps.map(step => <StepCard key={step.step_index} step={step} />);
 * ```
 */
export function useWebSocket(): UseWebSocketReturn {
  const [connectionState, setConnectionState] = useState<WSConnectionState>("idle");
  const [steps, setSteps] = useState<WSStepMessage[]>([]);
  const [acProgress, setAcProgress] = useState<WSAcStep[]>([]);
  const [terminalMessage, setTerminalMessage] = useState<WSTerminalMessage | null>(null);
  const [latestScreenshot, setLatestScreenshot] = useState<string>("");
  const [screenshotAcStep, setScreenshotAcStep] = useState<number>(0);
  const [screenshotAcTotal, setScreenshotAcTotal] = useState<number>(0);
  const [hitlScreenshot, setHitlScreenshot] = useState<string>("");
  const [hitlActions, setHitlActions] = useState<HitlActionRecord[]>([]);
  const [hitlDialog, setHitlDialog] = useState<WSHitlDialogMessage | null>(null);
  const [isThinking, setIsThinking] = useState<boolean>(false);
  const [thinkingText, setThinkingText] = useState<string>("");
  const [thinkingAcStep, setThinkingAcStep] = useState<number>(0);
  const [thinkingAcTotal, setThinkingAcTotal] = useState<number>(0);
  const [triageMessage, setTriageMessage] = useState<WSTriageMessage | null>(null);
  const [humanTakeoverMessage, setHumanTakeoverMessage] = useState<WSHumanTakeoverMessage | null>(null);
  const [personaCredentialsMessage, setPersonaCredentialsMessage] = useState<WSPersonaCredentialsMessage | null>(null);
  const [ghostCredentialsMessage, setGhostCredentialsMessage] = useState<WSGhostCredentialsMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  /**
   * Connect to the WebSocket for a specific run.
   *
   * @param runId - The run ID to subscribe to.
   */
  const connect = useCallback((runId: string) => {
    // Close any existing connection first
    if (wsRef.current) {
      wsRef.current.close();
    }

    // Reset state for new run
    setSteps([]);
    setAcProgress([]);
    setTerminalMessage(null);
    setLatestScreenshot("");
    setScreenshotAcStep(0);
    setScreenshotAcTotal(0);
    setHitlScreenshot("");
    setHitlActions([]);
    setHitlDialog(null);
    setIsThinking(false);
    setThinkingText("");
    setThinkingAcStep(0);
    setThinkingAcTotal(0);
    setTriageMessage(null);
    setHumanTakeoverMessage(null);
    setPersonaCredentialsMessage(null);
    setGhostCredentialsMessage(null);
    setConnectionState("connecting");

    const url = `${WS_BASE_URL}/ws/${runId}`;
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setConnectionState("connected");
      console.log(`[WS] Connected to ${url}`);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);

        if (msg.type === "step") {
          // Clear thinking state when step arrives
          setIsThinking(false);
          setSteps(prev => [...prev, msg as WSStepMessage]);
        } else if (msg.type === "ac_progress") {
          setAcProgress((msg as WSAcProgressMessage).steps);
        } else if (msg.type === "thinking") {
          const tm = msg as WSThinkingMessage;
          setIsThinking(true);
          setThinkingText(tm.text);
          setThinkingAcStep(tm.ac_step);
          setThinkingAcTotal(tm.ac_total);
        } else if (msg.type === "screenshot") {
          const ss = msg as WSScreenshotMessage;
          setLatestScreenshot(ss.screenshot_b64);
          setScreenshotAcStep(ss.ac_step);
          setScreenshotAcTotal(ss.ac_total);
        } else if (msg.type === "hitl_screenshot_update") {
          setHitlScreenshot((msg as WSHitlScreenshotMessage).data);
        } else if (msg.type === "hitl_action_recorded") {
          setHitlActions((prev) => [...prev, (msg as WSHitlActionRecordedMessage).action]);
        } else if (msg.type === "hitl_dialog_opened") {
          setHitlDialog(msg as WSHitlDialogMessage);
        } else if (msg.type === "triage") {
          setTriageMessage(msg as WSTriageMessage);
        } else if (msg.type === "human_takeover") {
          setHumanTakeoverMessage(msg as WSHumanTakeoverMessage);
        } else if (msg.type === "HITL_PERSONA_CREDENTIALS_REQUIRED") {
          setPersonaCredentialsMessage(msg as WSPersonaCredentialsMessage);
        } else if (msg.type === "GHOST_CREDENTIALS_REQUIRED") {
          setGhostCredentialsMessage(msg as WSGhostCredentialsMessage);
        } else if (msg.type === "completed" || msg.type === "failed") {
          setIsThinking(false);
          setTerminalMessage(msg as WSTerminalMessage);
          setConnectionState("closed");
          ws.close();
        }
      } catch (err) {
        console.error("[WS] Failed to parse message:", err);
      }
    };

    ws.onerror = (event) => {
      console.error("[WS] Connection error:", event);
      setConnectionState("error");
    };

    ws.onclose = () => {
      setConnectionState("closed");
      console.log("[WS] Connection closed");
    };

    wsRef.current = ws;
  }, []);

  /**
   * Clear all run state without closing the socket.
   * Call this when the user selects a new ticket so the log is wiped
   * before the next execution starts.
   */
  const resetState = useCallback(() => {
    setSteps([]);
    setAcProgress([]);
    setTerminalMessage(null);
    setLatestScreenshot("");
    setScreenshotAcStep(0);
    setScreenshotAcTotal(0);
    setHitlScreenshot("");
    setHitlActions([]);
    setHitlDialog(null);
    setIsThinking(false);
    setThinkingText("");
    setThinkingAcStep(0);
    setThinkingAcTotal(0);
    setTriageMessage(null);
    setHumanTakeoverMessage(null);
    setPersonaCredentialsMessage(null);
    setGhostCredentialsMessage(null);
    setConnectionState("idle");
  }, []);

  /**
   * Manually disconnect the WebSocket.
   */
  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionState("idle");
  }, []);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    connectionState,
    steps,
    acProgress,
    terminalMessage,
    latestScreenshot,
    screenshotAcStep,
    screenshotAcTotal,
    hitlScreenshot,
    hitlActions,
    hitlDialog,
    isThinking,
    thinkingText,
    thinkingAcStep,
    thinkingAcTotal,
    triageMessage,
    humanTakeoverMessage,
    personaCredentialsMessage,
    ghostCredentialsMessage,
    wsSocket: wsRef.current,
    connect,
    disconnect,
    resetState,
  };
}
