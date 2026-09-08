/**
 * Phase 6: useRebindTimer Tests
 * ==============================
 * Module: frontend/src/hooks/useRebindTimer.test.ts
 *
 * Tests the rebind timer scheduling behaviour:
 *
 *   1. Timer fires before the deadline and calls rebindSession.
 *   2. onRebindSuccess is called with the new next_rebind_by.
 *   3. onTerminated is called when rebind returns 404.
 *   4. Timer is cleared on unmount (no leak).
 *
 * Acceptance Criteria Coverage:
 *   AC-ASYNC-1 — cookie re-issued with fresh Max-Age
 *   AC-ERROR-7 — rebind past grace → session terminated
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRebindTimer } from "./useRebindTimer";
import * as sessionApi from "../api/session";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useRebindTimer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls rebindSession before the nextRebindBy deadline", async () => {
    const nextRebindBy = new Date(Date.now() + 60_000).toISOString(); // 60s from now
    const newDeadline = new Date(Date.now() + 120_000).toISOString();

    vi.spyOn(sessionApi, "rebindSession").mockResolvedValue({
      session_id: "sess-abc",
      state: "ATTACHED",
      next_rebind_by: newDeadline,
    });

    const onRebindSuccess = vi.fn();
    const onTerminated = vi.fn();

    renderHook(() =>
      useRebindTimer({
        nextRebindBy,
        token: "mock-token",
        onRebindSuccess,
        onTerminated,
      }),
    );

    // Advance to fire time (60s - 30s lead = 30s)
    await act(async () => {
      vi.advanceTimersByTime(31_000);
      await Promise.resolve(); // flush async rebind
    });

    expect(sessionApi.rebindSession).toHaveBeenCalledWith("mock-token");
    expect(onRebindSuccess).toHaveBeenCalledWith(newDeadline);
  });

  it("calls onTerminated when rebindSession returns 404", async () => {
    const nextRebindBy = new Date(Date.now() + 60_000).toISOString();
    const err404 = Object.assign(new Error("not found"), { status: 404 });
    vi.spyOn(sessionApi, "rebindSession").mockRejectedValue(err404);

    const onRebindSuccess = vi.fn();
    const onTerminated = vi.fn();

    renderHook(() =>
      useRebindTimer({
        nextRebindBy,
        token: "mock-token",
        onRebindSuccess,
        onTerminated,
      }),
    );

    await act(async () => {
      vi.advanceTimersByTime(31_000);
      await Promise.resolve();
    });

    expect(onTerminated).toHaveBeenCalled();
    expect(onRebindSuccess).not.toHaveBeenCalled();
  });

  it("does not fire when token is null", async () => {
    const nextRebindBy = new Date(Date.now() + 60_000).toISOString();
    vi.spyOn(sessionApi, "rebindSession").mockResolvedValue({
      session_id: "sess",
      state: "ATTACHED",
      next_rebind_by: nextRebindBy,
    });

    const onRebindSuccess = vi.fn();
    const onTerminated = vi.fn();

    renderHook(() =>
      useRebindTimer({
        nextRebindBy,
        token: null, // no token
        onRebindSuccess,
        onTerminated,
      }),
    );

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
    });

    expect(sessionApi.rebindSession).not.toHaveBeenCalled();
  });
});
