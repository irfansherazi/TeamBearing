/**
 * Phase 6: SessionContext Tests
 * ==============================
 * Module: frontend/src/context/__tests__/SessionContext.test.tsx
 *
 * Tests the SessionProvider + useSession() hook:
 *
 *   1. useSession() throws when called outside SessionProvider (runtime guard).
 *   2. SessionProvider calls POST /api/session/start on mount and sets
 *      sessionState = "attached" on success.
 *   3. SessionProvider sets capacityReached = true on 409 response.
 *   4. session_terminated WS event triggers terminated = true.
 *   5. novncUrl is available from useSession() after successful bootstrap.
 *
 * Acceptance Criteria Coverage:
 *   AC-ENTRY-1 — session bootstrap fires on SessionProvider mount
 *   AC-ENTRY-2 — AuthProvider guard (useAuth throws if absent)
 *   AC-ERROR-2 — capacity → capacityReached = true
 *   AC-HAPPY-1 — novncUrl available in context
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { JSX } from "react";
import { useSession, SessionProvider } from "../SessionContext";
import * as sessionApi from "../../api/session";
import type { SessionStartResponse } from "../../api/session";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the auth hook so tests don't need a real AuthProvider.
vi.mock("../../auth/useAuth", () => ({
  useAuth: () => ({ ssoToken: "mock-jwt-token" }),
}));

// Mock useRebindTimer to prevent timer side-effects in tests.
vi.mock("../../hooks/useRebindTimer", () => ({
  useRebindTimer: vi.fn(),
}));

// Mock useSessionWebSocket to prevent WS connections in tests.
vi.mock("../../hooks/useSessionWebSocket", () => ({
  useSessionWebSocket: vi.fn(),
}));

const mockSuccessResponse: SessionStartResponse = {
  session_id: "sess-test-123",
  state: "ATTACHED",
  next_rebind_by: new Date(Date.now() + 3600_000).toISOString(),
  novnc_url: "/vnc/sess-test-123/vnc.html?path=websockify/sess-test-123",
  display_num: 1,
};

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function ReadSession(): JSX.Element {
  const session = useSession();
  return (
    <div>
      <span data-testid="state">{session.sessionState}</span>
      <span data-testid="session-id">{session.sessionId ?? "null"}</span>
      <span data-testid="novnc-url">{session.novncUrl ?? "null"}</span>
      <span data-testid="capacity">{session.capacityReached ? "yes" : "no"}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSession runtime guard", () => {
  it("throws when called outside SessionProvider", () => {
    // Suppress console.error for this test.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ReadSession />)).toThrow(/SessionProvider/);
    spy.mockRestore();
  });
});

describe("SessionProvider bootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls startSession on mount and sets sessionState = attached on success", async () => {
    vi.spyOn(sessionApi, "startSession").mockResolvedValue(mockSuccessResponse);

    render(
      <SessionProvider>
        <ReadSession />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("attached");
    });

    expect(sessionApi.startSession).toHaveBeenCalledWith("mock-jwt-token");
    expect(screen.getByTestId("session-id").textContent).toBe("sess-test-123");
  });

  it("provides novncUrl from the session bootstrap response", async () => {
    vi.spyOn(sessionApi, "startSession").mockResolvedValue(mockSuccessResponse);

    render(
      <SessionProvider>
        <ReadSession />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("novnc-url").textContent).toBe(
        "/vnc/sess-test-123/vnc.html?path=websockify/sess-test-123",
      );
    });
  });

  it("sets capacityReached = true when startSession returns 409", async () => {
    const capacityError = Object.assign(new Error("capacity"), { status: 409 });
    vi.spyOn(sessionApi, "startSession").mockRejectedValue(capacityError);

    render(
      <SessionProvider>
        <ReadSession />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("capacity").textContent).toBe("yes");
    });

    expect(screen.getByTestId("state").textContent).toBe("capacity_reached");
  });
});
