/**
 * ssoKeepalive.ts
 * Minimal SSO keepalive module for the React frontend.
 *
 * Periodically calls POST /auth/ssoRefresh to prevent session expiry.
 * Framework-agnostic: token read/write and logout are injected via config.
 *
 * Usage:
 *   const keepalive = createSsoKeepalive({
 *     getToken: () => authStorage.getSsoToken(),
 *     setToken: (t) => authStorage.setSsoToken(t),
 *     onSessionInvalid: () => logout(),
 *   });
 *   keepalive.start();   // begin 15s interval
 *   keepalive.stop();    // clear interval
 *   keepalive.refreshNow(); // one-shot refresh
 */

export interface SsoKeepaliveConfig {
  /** Returns the current SSO token, or null if none exists. */
  getToken: () => string | null;
  /** Persists a new SSO token (e.g., writes to cookie via authStorage). */
  setToken: (token: string) => void;
  /** Called when the session is definitively invalid (401, 403, or missing token in response). */
  onSessionInvalid: () => void;
  /** Refresh interval in milliseconds. Default: 15 000 (15 seconds). */
  intervalMs?: number;
  /** vcAPI base URL. Default: import.meta.env.VITE_VCAPI_URL */
  baseUrl?: string;
}

export interface SsoKeepalive {
  /** Start the periodic refresh. No-op if already running. */
  start: () => void;
  /** Stop the periodic refresh. Safe to call multiple times. */
  stop: () => void;
  /** Execute a single refresh immediately (does not affect the interval timer). */
  refreshNow: () => Promise<void>;
}

/**
 * Creates an SSO keepalive instance.
 *
 * Only one interval timer can be active at a time per instance.
 * The module ignores all response fields except `ssoToken`.
 */
export function createSsoKeepalive(config: SsoKeepaliveConfig): SsoKeepalive {
  const {
    getToken,
    setToken,
    onSessionInvalid,
    intervalMs = 15_000,
    baseUrl = import.meta.env.VITE_VCAPI_URL,
  } = config;

  let timerId: ReturnType<typeof setInterval> | null = null;

  /**
   * Perform a single SSO refresh call.
   *
   * - On success with valid ssoToken → update stored token.
   * - On 401/403 or success with no ssoToken → call onSessionInvalid, stop timer.
   * - On network/other errors → silently skip (retry on next interval).
   */
  async function doRefresh(): Promise<void> {
    const token = getToken();
    if (!token) {
      // No token to refresh — skip silently
      return;
    }

    try {
      const response = await fetch(`${baseUrl}/auth/ssoRefresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ spotIdsVisible: [] }),
      });

      // Session definitively invalid — force logout
      if (response.status === 401 || response.status === 403) {
        stop();
        onSessionInvalid();
        return;
      }

      // Non-auth HTTP error (500, 502, etc.) — keep token, retry next interval
      if (!response.ok) {
        console.warn(`[ssoKeepalive] refresh failed with status ${response.status}, will retry`);
        return;
      }

      // Parse the response — we only care about ssoToken
      const data = await response.json();

      if (data.ssoToken && typeof data.ssoToken === 'string' && data.ssoToken.length > 0) {
        if (data.ssoToken !== token) {
          setToken(data.ssoToken);
        }
      } else {
        // Successful response but no valid token — session is invalid
        stop();
        onSessionInvalid();
      }
    } catch (err) {
      // Network error, CORS error, etc. — keep token, retry next interval
      console.warn('[ssoKeepalive] refresh request failed, will retry:', err);
    }
  }

  function start(): void {
    // Prevent duplicate timers
    if (timerId !== null) {
      return;
    }
    timerId = setInterval(doRefresh, intervalMs);
  }

  function stop(): void {
    if (timerId !== null) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  async function refreshNow(): Promise<void> {
    await doRefresh();
  }

  return { start, stop, refreshNow };
}
