/**
 * Phase 6: useSessionWebSocket Tests
 * ====================================
 * Module: frontend/src/hooks/useSessionWebSocket.test.ts
 *
 * Tests the session WS control channel hook:
 *
 *   1. Opens /ws/session/{sessionId} on mount.
 *   2. Responds to "ping" messages with "pong".
 *   3. Calls onTerminated on "session_terminated" message.
 *   4. Calls onDisconnected on unexpected close.
 *   5. Closes the WS on unmount.
 *
 * Acceptance Criteria Coverage:
 *   AC-ERROR-6 — heartbeat timeout → session terminated
 *   AC-ERROR-4 — WS disconnects without clean teardown trigger
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSessionWebSocket } from "./useSessionWebSocket";

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sentMessages: string[] = [];
  closed = false;
  closeCode?: number;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close(code?: number, _reason?: string) {
    this.closed = true;
    this.closeCode = code;
    if (this.onclose) this.onclose();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSessionWebSocket", () => {
  let originalWebSocket: typeof WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
    vi.clearAllMocks();
  });

  it("opens a WebSocket to /ws/session/{sessionId}", () => {
    renderHook(() =>
      useSessionWebSocket({
        sessionId: "sess-abc-123",
        onTerminated: vi.fn(),
        onDisconnected: vi.fn(),
      }),
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/session/sess-abc-123");
  });

  it("responds to ping messages with pong", () => {
    renderHook(() =>
      useSessionWebSocket({
        sessionId: "sess-ping-test",
        onTerminated: vi.fn(),
        onDisconnected: vi.fn(),
      }),
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "ping" }) });
    });

    expect(ws.sentMessages).toHaveLength(1);
    expect(JSON.parse(ws.sentMessages[0])).toEqual({ type: "pong" });
  });

  it("calls onTerminated on session_terminated message", () => {
    const onTerminated = vi.fn();
    renderHook(() =>
      useSessionWebSocket({
        sessionId: "sess-term-test",
        onTerminated,
        onDisconnected: vi.fn(),
      }),
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "session_terminated", reason: "jwt_expired" }),
      });
    });

    expect(onTerminated).toHaveBeenCalledWith("jwt_expired");
  });

  it("calls onDisconnected on unexpected close", () => {
    const onDisconnected = vi.fn();
    const { result: _result } = renderHook(() =>
      useSessionWebSocket({
        sessionId: "sess-disc-test",
        onTerminated: vi.fn(),
        onDisconnected,
      }),
    );

    const ws = MockWebSocket.instances[0];
    act(() => {
      // Simulate unexpected close (no session_terminated message first).
      if (ws.onclose) ws.onclose();
    });

    expect(onDisconnected).toHaveBeenCalled();
  });

  it("closes the WebSocket and does not fire callbacks on unmount", () => {
    const onDisconnected = vi.fn();
    const { unmount } = renderHook(() =>
      useSessionWebSocket({
        sessionId: "sess-unmount-test",
        onTerminated: vi.fn(),
        onDisconnected,
      }),
    );

    act(() => {
      unmount();
    });

    const ws = MockWebSocket.instances[0];
    expect(ws.closed).toBe(true);
    // onDisconnected should NOT fire on a clean unmount.
    expect(onDisconnected).not.toHaveBeenCalled();
  });
});
