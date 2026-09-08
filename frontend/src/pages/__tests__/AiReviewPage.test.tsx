/**
 * AiReviewPage Tests — Slice 2 (run command + live table)
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AiReviewPage } from "../AiReviewPage";
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

const renderCases = [
  {
    description: "renders the AI Review heading",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByRole("heading", { name: /ai review/i })).toBeInTheDocument();
    },
  },
  {
    description: "renders Branch, Commits, and Base branch fields",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByLabelText(/^app$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^branch$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/commits \(optional\)/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/base branch/i)).toBeInTheDocument();
    },
  },
  {
    description: "defaults Base branch to Develop",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByLabelText(/base branch/i)).toHaveValue("Develop");
    },
  },
  {
    description: "shows empty results until a review is run",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByText(/no review run yet/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/review log/i)).toHaveTextContent(/live log will appear here/i);
    },
  },
  {
    description: "does not render the History table on this page",
    setup: () => undefined,
    expectations: () => {
      expect(screen.queryByRole("heading", { name: /^history$/i })).toBeNull();
    },
  },
];

describe("AiReviewPage — initial render", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);
  });

  renderCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      setup();
      render(<AiReviewPage />);
      expectations();
    });
  });
});

describe("AiReviewPage — Run review", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.mocked(authenticatedFetch).mockReset();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const gatingCases = [
    {
      description: "disables Run review when branch is empty",
      setup: () => ({ branch: "" }),
      expectations: () => {
        expect(screen.getByRole("button", { name: /run review/i })).toBeDisabled();
      },
    },
    {
      description: "enables Run review when branch is filled",
      setup: () => ({ branch: "Syed/TD-260" }),
      expectations: () => {
        expect(screen.getByRole("button", { name: /run review/i })).not.toBeDisabled();
      },
    },
  ];

  gatingCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      const { branch } = setup();
      render(<AiReviewPage />);
      fireEvent.change(screen.getByLabelText(/^branch$/i), { target: { value: branch } });
      expectations();
    });
  });

  it("POSTs branch, commits, and base then streams log rows into the table", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ run_id: "ar-1", websocket_url: "/ws/ar-1" }),
    } as Response);

    render(<AiReviewPage />);
    fireEvent.change(screen.getByLabelText(/^branch$/i), {
      target: { value: "feature/demo" },
    });
    fireEvent.change(screen.getByLabelText(/commits \(optional\)/i), {
      target: { value: "abc123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run review/i }));

    await waitFor(() => {
      expect(authenticatedFetch).toHaveBeenCalled();
    });
    const postCall = vi.mocked(authenticatedFetch).mock.calls.find(
      ([url, options]) =>
        String(url).includes("/ai-review/run") &&
        !String(url).includes("stop") &&
        (options as { method?: string } | undefined)?.method === "POST"
    );
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      app: "platform",
      branch: "feature/demo",
      commits: "abc123",
      base: "Develop",
    });

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });
    const ws = MockWebSocket.instances[0];
    ws.onmessage?.({
      data: JSON.stringify({
        type: "terminal_log",
        line: "| CQ-01 | FAIL | stray indent |",
      }),
    });

    expect(await screen.findByText("CQ-01")).toBeInTheDocument();
    const failBadge = screen.getByText("FAIL");
    expect(failBadge).toBeInTheDocument();
    expect(failBadge).toHaveClass("ai-review-status-fail");
    expect(screen.getByLabelText(/review log/i)).toHaveTextContent(/CQ-01/);
  });

  it("shows the API error when the run cannot start", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: "Branch contains unsupported characters" }),
    } as Response);

    render(<AiReviewPage />);
    fireEvent.change(screen.getByLabelText(/^branch$/i), {
      target: { value: "feature/demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run review/i }));

    expect(await screen.findByText(/unsupported characters/i)).toBeInTheDocument();
  });
});
