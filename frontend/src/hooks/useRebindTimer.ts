/**
 * vQA — useRebindTimer
 * =====================
 * Module: frontend/src/hooks/useRebindTimer.ts
 *
 * Schedules a call to POST /api/session/rebind at `next_rebind_by` (ISO-8601
 * timestamp returned by /api/session/start and updated after each rebind).
 * On success, updates the session context with the new rebind deadline.
 * On 404/410 (session terminated), triggers the provided onTerminated callback.
 *
 * Design decisions (per-user-session-isolation ADR-11):
 * - The timer fires at `next_rebind_by - REBIND_LEAD_SECONDS` to give a
 *   comfortable margin before the JWT actually expires.
 * - On network failure (not 404/410), the timer retries after RETRY_DELAY_MS.
 * - The hook cleans up its timer on unmount so it does not leak.
 */

import { useCallback, useEffect, useRef } from "react";
import { rebindSession } from "../api/session";

const REBIND_LEAD_SECONDS = 30; // call rebind this many seconds before deadline
const RETRY_DELAY_MS = 10_000; // 10s retry on transient network failure

export interface UseRebindTimerOptions {
  /** ISO-8601 deadline from the backend (next_rebind_by from session start/rebind) */
  nextRebindBy: string | null;
  /** The current JWT token to send in Authorization: Bearer */
  token: string | null;
  /** Called with the new next_rebind_by from a successful rebind */
  onRebindSuccess: (newNextRebindBy: string) => void;
  /** Called when rebind returns 404/410 (session no longer exists) */
  onTerminated: () => void;
}

/**
 * Schedules POST /api/session/rebind to fire at `nextRebindBy - 30s`.
 * Re-schedules whenever `nextRebindBy` changes (after each successful rebind).
 */
export function useRebindTimer({
  nextRebindBy,
  token,
  onRebindSuccess,
  onTerminated,
}: UseRebindTimerOptions): void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scheduleRebind = useCallback(
    (deadline: string) => {
      if (!token) return;

      const deadlineMs = new Date(deadline).getTime();
      const fireAtMs = deadlineMs - REBIND_LEAD_SECONDS * 1000;
      const delayMs = Math.max(0, fireAtMs - Date.now());

      clearTimer();
      timerRef.current = setTimeout(async () => {
        try {
          const result = await rebindSession(token);
          onRebindSuccess(result.next_rebind_by);
        } catch (err: unknown) {
          const status = (err as { status?: number }).status;
          if (status === 404 || status === 410) {
            // Session terminated — notify the caller (SessionProvider will handle logout).
            onTerminated();
          } else {
            // Transient failure — retry after RETRY_DELAY_MS.
            timerRef.current = setTimeout(async () => {
              try {
                const result = await rebindSession(token);
                onRebindSuccess(result.next_rebind_by);
              } catch {
                onTerminated(); // Give up on second failure.
              }
            }, RETRY_DELAY_MS);
          }
        }
      }, delayMs);
    },
    [token, onRebindSuccess, onTerminated, clearTimer],
  );

  useEffect(() => {
    if (nextRebindBy) {
      scheduleRebind(nextRebindBy);
    }
    return clearTimer;
  }, [nextRebindBy, scheduleRebind, clearTimer]);
}
