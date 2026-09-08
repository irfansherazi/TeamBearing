/**
 * MemoryWatchHistoryPage tests
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryWatchHistoryPage } from "../MemoryWatchHistoryPage";
import { authenticatedFetch } from "../../api_client";

vi.mock("../../api_client", () => ({
  authenticatedFetch: vi.fn(),
}));

const historyItem = {
  run_id: "mw-abc12345",
  status: "completed",
  flow: "po-open-spot",
  env: "qa",
  cycles: 5,
  verdict_pass: true,
  growth_mb: 8,
  started_at: "2026-09-07T11:00:00+00:00",
  finished_at: "2026-09-07T11:10:00+00:00",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <MemoryWatchHistoryPage />
    </MemoryRouter>
  );
}

describe("MemoryWatchHistoryPage — initial render", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  it("renders the Memory Watch history heading", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);
    renderPage();
    expect(
      await screen.findByRole("heading", { name: /memory watch history/i })
    ).toBeInTheDocument();
  });

  it("shows empty history until a run is saved", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);
    renderPage();
    expect(await screen.findByText(/no saved memory watch runs yet/i)).toBeInTheDocument();
  });
});

describe("MemoryWatchHistoryPage — saved runs", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  it("renders a compact list row", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([historyItem]),
    } as Response);
    renderPage();
    expect(await screen.findByText("mw-abc12345")).toBeInTheDocument();
    expect(screen.getByText(/production orders/i)).toBeInTheDocument();
  });

  it("opens detail from a row click", async () => {
    vi.mocked(authenticatedFetch).mockImplementation((url: string) => {
      const href = String(url);
      if (href.endsWith("/memory-watch/history")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([historyItem]),
        } as Response);
      }
      if (href.includes("/video")) {
        return Promise.resolve({
          ok: false,
          json: () => Promise.resolve({}),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...historyItem,
            samples: [
              {
                cycle: 0,
                label: "baseline",
                usedMb: 42,
                deltaMb: 0,
                gcRuns: 3,
                status: "watching",
              },
            ],
            rows: [{ item: "HEAP", status: "PASS", evidence: "+8 MB" }],
            log_text: "| HEAP | PASS | +8 MB |",
            report_dir: "",
            video_file: "",
          }),
      } as Response);
    });
    renderPage();
    fireEvent.click(await screen.findByText("mw-abc12345"));
    expect(await screen.findByText("HEAP")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back/i })).toBeInTheDocument();
  });
});
