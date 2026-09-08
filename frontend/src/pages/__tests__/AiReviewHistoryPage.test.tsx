/**
 * AiReviewHistoryPage Tests
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AiReviewHistoryPage } from "../AiReviewHistoryPage";
import { authenticatedFetch } from "../../api_client";

vi.mock("../../api_client", () => ({
  authenticatedFetch: vi.fn(),
}));

const historyItem = {
  review_id: "ar-abc12345",
  status: "completed",
  app: "platform",
  branch: "Syed/VC2-9167",
  base: "Develop",
  commits: "",
  pass_count: 18,
  fail_count: 4,
  skip_count: 2,
  started_at: "2026-08-27T11:00:00+00:00",
  finished_at: "2026-08-27T11:05:00+00:00",
};

const renderCases = [
  {
    description: "renders the History heading",
    setup: () => {
      vi.mocked(authenticatedFetch).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    },
    expectations: () => {
      expect(screen.getByRole("heading", { name: /^history$/i })).toBeInTheDocument();
    },
  },
  {
    description: "shows empty history until a review is saved",
    setup: () => {
      vi.mocked(authenticatedFetch).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    },
    expectations: () => {
      expect(screen.getByText(/no saved reviews yet/i)).toBeInTheDocument();
    },
  },
];

describe("AiReviewHistoryPage — initial render", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  renderCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      setup();
      render(<AiReviewHistoryPage />);
      expectations();
    });
  });
});

describe("AiReviewHistoryPage — saved reviews", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  it("renders compact list columns without branch or commit hashes", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([historyItem]),
    } as Response);
    render(<AiReviewHistoryPage />);
    expect(await screen.findByText("ar-abc12345")).toBeInTheDocument();
    expect(screen.getByText("vsuitePlatform")).toBeInTheDocument();
    expect(screen.getByText("Fail")).toBeInTheDocument();
    expect(screen.queryByText("Syed/VC2-9167")).toBeNull();
    expect(screen.queryByText("18 PASS / 4 FAIL / 2 SKIP")).toBeNull();
  });

  it("opens a history row into details and the checklist table", async () => {
    vi.mocked(authenticatedFetch).mockImplementation((url: string) => {
      const path = String(url);
      if (path.endsWith("/ai-review/history")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([historyItem]),
        } as Response);
      }
      if (path.endsWith("/ai-review/history/ar-abc12345")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...historyItem,
              rows: [{ item: "CQ-01", status: "FAIL", evidence: "indent" }],
              log_text: "Files reviewed (1): src/foo.ts\nChecklist Results:\n",
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    });
    render(<AiReviewHistoryPage />);
    fireEvent.click(await screen.findByText("ar-abc12345"));
    expect(await screen.findByText("CQ-01")).toBeInTheDocument();
    expect(screen.getByText(/npm run ai:review/i)).toBeInTheDocument();
    expect(screen.getByText("Syed/VC2-9167")).toBeInTheDocument();
    expect(screen.getByText("src/foo.ts")).toBeInTheDocument();
    expect(screen.queryByLabelText(/review log/i)).toBeNull();
  });

  it("returns to the list from the detail Back button", async () => {
    vi.mocked(authenticatedFetch).mockImplementation((url: string) => {
      const path = String(url);
      if (path.endsWith("/ai-review/history")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([historyItem]),
        } as Response);
      }
      if (path.endsWith("/ai-review/history/ar-abc12345")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...historyItem,
              rows: [{ item: "CQ-01", status: "FAIL", evidence: "indent" }],
              log_text: "",
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    });
    render(<AiReviewHistoryPage />);
    fireEvent.click(await screen.findByText("ar-abc12345"));
    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /^history$/i })).toBeInTheDocument();
    });
  });
});
