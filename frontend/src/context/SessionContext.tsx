/**
 * vQA — SessionContext
 * =====================
 * Module: frontend/src/context/SessionContext.tsx
 *
 * Provides per-user session isolation to all descendants.  Must be mounted
 * INSIDE AuthProvider (the runtime guard throws if AuthProvider is absent).
 *
 *   <AuthProvider>
 *     <SessionProvider>
 *       <AppShell />       ← all children can call useSession()
 *     </SessionProvider>
 *   </AuthProvider>
 *
 * Session lifecycle:
 *   1. On mount, calls POST /api/session/start with the current JWT.
 *   2. On 200: stores session, starts useRebindTimer + useSessionWebSocket.
 *   3. On 409 (capacity): sets capacityReached = true.
 *   4. On session_terminated WS event: sets terminated = true → redirect /login.
 *   5. useRebindTimer fires at next_rebind_by – 30s; on failure triggers terminated.
 *
 * Kill switch: when SESSION_ISOLATION_ENABLED=false the backend does not enforce
 * session cookies.  SessionProvider still runs (so the context is always
 * available to consumers) but operates in "legacy" mode where sessionId is null.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type JSX,
} from "react";
import { startSession } from "../api/session";
import type { SessionStartResponse } from "../api/session";
import { useRebindTimer } from "../hooks/useRebindTimer";
import { useSessionWebSocket } from "../hooks/useSessionWebSocket";
import { useAuth } from "../auth/useAuth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SessionState =
  | "bootstrapping"
  | "attached"
  | "capacity_reached"
  | "terminated"
  | "error";

export interface SessionContextValue {
  /** The session ID from the backend, or null while bootstrapping / legacy mode */
  sessionId: string | null;
  /** Current session lifecycle state */
  sessionState: SessionState;
  /** Per-session noVNC URL: /vnc/<session_id>/vnc.html?path=websockify/<session_id> */
  novncUrl: string | null;
  /** Xvfb display number assigned to this session */
  displayNum: number;
  /** True when the backend has returned 409 (all slots in use) */
  capacityReached: boolean;
  /** True when the session has been terminated (JWT expired, admin, drain) */
  terminated: boolean;
  /** Non-null after a bootstrap or network error */
  error: string | null;
  /** Retry bootstrapping after a failure or capacity rejection */
  retry: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

/**
 * useSession — reads the SessionContextValue.
 * Throws if called outside a <SessionProvider>.
 */
export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (ctx === undefined) {
    throw new Error(
      "useSession must be called inside a <SessionProvider>. " +
        "Ensure <SessionProvider> is mounted between <AuthProvider> and the component that calls useSession().",
    );
  }
  return ctx;
}

/**
 * useOptionalSession — same as useSession but returns undefined when
 * called outside a <SessionProvider>. Use in leaf components that must
 * render in both isolated-session and legacy-singleton contexts (and in
 * unit tests that render the component without a provider).
 */
export function useOptionalSession(): SessionContextValue | undefined {
  return useContext(SessionContext);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface SessionProviderProps {
  children: React.ReactNode;
}

export function SessionProvider({ children }: SessionProviderProps): JSX.Element {
  // Runtime guard: AuthProvider must be an ancestor.
  const auth = useAuth(); // throws if AuthProvider is absent — guards correct mount order

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionState, setSessionState] = useState<SessionState>("bootstrapping");
  const [novncUrl, setNovncUrl] = useState<string | null>(null);
  const [displayNum, setDisplayNum] = useState<number>(0);
  const [capacityReached, setCapacityReached] = useState<boolean>(false);
  const [terminated, setTerminated] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [nextRebindBy, setNextRebindBy] = useState<string | null>(null);

  // Track whether the component is mounted to avoid state updates after unmount.
  const mountedRef = useRef<boolean>(true);
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Bootstrap
  // ---------------------------------------------------------------------------

  const bootstrap = useCallback(async () => {
    const currentToken = auth.ssoToken;
    if (!currentToken) return;
    if (!mountedRef.current) return;

    setSessionState("bootstrapping");
    setCapacityReached(false);
    setTerminated(false);
    setError(null);

    try {
      const data: SessionStartResponse = await startSession(currentToken);
      if (!mountedRef.current) return;
      setSessionId(data.session_id);
      sessionIdRef.current = data.session_id;
      setNovncUrl(data.novnc_url);
      setDisplayNum(data.display_num);
      setNextRebindBy(data.next_rebind_by);
      setSessionState("attached");
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      const status = (err as { status?: number }).status;
      if (status === 409) {
        setCapacityReached(true);
        setSessionState("capacity_reached");
      } else {
        setError((err as Error).message ?? "Session start failed");
        setSessionState("error");
      }
    }
  }, [auth.ssoToken]);

  // Bootstrap on mount. Skip when a session is already attached so SSO token
  // rotation (every 15s) does not tear down /ws/session and reload the page.
  useEffect(() => {
    if (sessionIdRef.current) {
      return;
    }
    void bootstrap();
  }, [bootstrap]);

  // ---------------------------------------------------------------------------
  // Rebind timer
  // ---------------------------------------------------------------------------

  const handleRebindSuccess = useCallback((newNextRebindBy: string) => {
    if (mountedRef.current) {
      setNextRebindBy(newNextRebindBy);
    }
  }, []);

  const handleTerminated = useCallback(() => {
    if (mountedRef.current) {
      setTerminated(true);
      setSessionState("terminated");
    }
  }, []);

  useRebindTimer({
    nextRebindBy,
    token: auth.ssoToken,
    onRebindSuccess: handleRebindSuccess,
    onTerminated: handleTerminated,
  });

  // ---------------------------------------------------------------------------
  // Session WebSocket (control channel)
  // ---------------------------------------------------------------------------

  const handleWsTerminated = useCallback((reason: string) => {
    if (mountedRef.current) {
      setTerminated(true);
      setSessionState("terminated");
      // Log for observability; the toast/redirect is the consumer's responsibility.
      console.warn(`[SessionContext] session_terminated from WS: ${reason}`);
    }
  }, []);

  const handleWsDisconnected = useCallback(() => {
    // Non-clean disconnect — do not auto-terminate; the rebind timer handles expiry.
    // Just log for diagnostic purposes.
    console.warn("[SessionContext] session WS disconnected unexpectedly");
  }, []);

  useSessionWebSocket({
    sessionId,
    onTerminated: handleWsTerminated,
    onDisconnected: handleWsDisconnected,
  });

  // ---------------------------------------------------------------------------
  // Context value
  // ---------------------------------------------------------------------------

  const value: SessionContextValue = {
    sessionId,
    sessionState,
    novncUrl,
    displayNum,
    capacityReached,
    terminated,
    error,
    retry: bootstrap,
  };

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
}
