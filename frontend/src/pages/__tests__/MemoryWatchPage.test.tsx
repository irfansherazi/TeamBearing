/**
 * MemoryWatchPage tests
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryWatchPage } from "../MemoryWatchPage";
import { authenticatedFetch } from "../../api_client";

vi.mock("../../api_client", () => ({
  authenticatedFetch: vi.fn(),
}));

type WsHandler = ((event: { data: string }) => void) | null;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: WsHandler = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    return;
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MemoryWatchPage />
    </MemoryRouter>
  );
}

const renderCases = [
  {
    description: "renders the Memory Watch heading",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByRole("heading", { name: /memory watch/i })).toBeInTheDocument();
    },
  },
  {
    description: "renders Flow, Environment, and Cycles fields",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByLabelText(/^flow$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^environment$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^cycles$/i)).toBeInTheDocument();
    },
  },
  {
    description: "defaults env to qa and cycles to 5",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByLabelText(/^environment$/i)).toHaveValue("qa");
      expect(screen.getByLabelText(/^cycles$/i)).toHaveValue(5);
    },
  },
];

describe("MemoryWatchPage — initial render", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
  });

  renderCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      setup();
      renderPage();
      expectations();
    });
  });
});

describe("MemoryWatchPage — Run", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.mocked(authenticatedFetch).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs flow, env, and cycles then streams a heap sample", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ run_id: "mw-1", websocket_url: "/ws/mw-1" }),
    } as Response);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /run memory check/i }));

    await waitFor(() => {
      expect(authenticatedFetch).toHaveBeenCalled();
    });
    const postCall = vi.mocked(authenticatedFetch).mock.calls.find(
      ([url, options]) =>
        String(url).includes("/memory-watch/run") &&
        !String(url).includes("stop") &&
        (options as { method?: string } | undefined)?.method === "POST"
    );
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      flow: "po-open-spot",
      env: "qa",
      cycles: 5,
    });

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });
    const ws = MockWebSocket.instances[0];
    ws.onmessage?.({
      data: JSON.stringify({
        type: "terminal_log",
        line: 'MEMORY_WATCH_SAMPLE {"cycle":0,"label":"baseline","usedMb":42,"deltaMb":0,"gcRuns":3,"status":"watching"}',
      }),
    });

    expect(await screen.findByText("42.00")).toBeInTheDocument();
  });
});
