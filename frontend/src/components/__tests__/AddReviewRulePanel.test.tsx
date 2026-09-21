/**
 * AddReviewRulePanel tests
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AddReviewRulePanel } from "../AddReviewRulePanel";
import { authenticatedFetch } from "../../api_client";

vi.mock("../../api_client", () => ({
  authenticatedFetch: vi.fn(),
}));

const sections = [
  {
    name: "Code Quality",
    rules: [{ id: "CQ-01", plain: "Conventions.", rule: "Follow conventions." }],
  },
];

function renderPanel(onSaved = vi.fn()) {
  return render(
    <AddReviewRulePanel app="platform" sections={sections} onSaved={onSaved} />
  );
}

/**
 * Expand the Add rule accordion so the form is on screen.
 *
 * @returns void
 */
function openAddForm() {
  fireEvent.click(screen.getByRole("button", { name: /add rule/i }));
}

describe("AddReviewRulePanel", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  const openCases = [
    {
      description: "shows a collapsed Add rule accordion",
      setup: () => undefined,
      expectations: () => {
        expect(screen.getByRole("heading", { name: /add rule/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /add rule/i })).toHaveAttribute(
          "aria-expanded",
          "false"
        );
        expect(screen.queryByRole("button", { name: /check idea/i })).toBeNull();
      },
    },
  ];

  openCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      setup();
      renderPanel();
      expectations();
    });
  });

  it("rejects through the API and shows the reason", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          verdict: "reject",
          reason: "No. That is not a valid review rule.",
          overlap_ids: [],
          proposal_id: null,
          assigned_id: null,
          section: "Code Quality",
          suggested_section: "Code Quality",
          suggested_id: null,
          suggestions: [],
        }),
    } as Response);
    renderPanel();
    openAddForm();
    fireEvent.change(screen.getByLabelText(/rule description/i), {
      target: { value: "the lazy dog jumps over the brown fox" },
    });
    fireEvent.click(screen.getByRole("button", { name: /check idea/i }));
    expect(
      await screen.findByText(/not a valid review rule/i)
    ).toBeInTheDocument();
  });

  it("lets the user pick a suggested wording and save", async () => {
    const onSaved = vi.fn();
    vi.mocked(authenticatedFetch).mockImplementation((url: string, options?: RequestInit) => {
      const path = String(url);
      if (path.includes("/rules/propose")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verdict: "accept",
              reason: "Clear check.",
              overlap_ids: [],
              proposal_id: "rp-abcd1234",
              assigned_id: "CQ-34",
              section: "Code Quality",
              suggested_section: "Code Quality",
              suggested_id: "CQ-34",
              suggestions: [
                {
                  id: "CQ-34",
                  wording: "Empty catch blocks must log or rethrow.",
                  plain: "Do not swallow errors.",
                },
              ],
            }),
        } as Response);
      }
      if (path.endsWith("/rules") && options?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: "CQ-34",
              section: "Code Quality",
              plain: "Do not swallow errors.",
              rule: "Empty catch blocks must log or rethrow.",
              app: "platform",
            }),
        } as Response);
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) } as Response);
    });
    renderPanel(onSaved);
    openAddForm();
    fireEvent.change(screen.getByLabelText(/rule description/i), {
      target: { value: "Do not leave empty catch blocks in changed code." },
    });
    fireEvent.click(screen.getByRole("button", { name: /check idea/i }));
    expect(await screen.findByText(/suggested wording for cq-34\./i)).toBeInTheDocument();
    expect(screen.getByText(/empty catch blocks must log or rethrow/i)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText(/pick one/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save this rule/i }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("lets the user save under the suggested section instead", async () => {
    const onSaved = vi.fn();
    vi.mocked(authenticatedFetch).mockImplementation((url: string, options?: RequestInit) => {
      const path = String(url);
      if (path.includes("/rules/propose")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verdict: "accept",
              reason: "Clear check.",
              overlap_ids: [],
              proposal_id: "rp-section",
              assigned_id: "CQ-34",
              section: "Code Quality",
              suggested_section: "Functionality",
              suggested_id: "F-12",
              suggestions: [
                {
                  id: "CQ-34",
                  wording: "Do not put email in analytics user properties.",
                  plain: "Keep PII out of analytics.",
                },
              ],
            }),
        } as Response);
      }
      if (path.endsWith("/rules") && options?.method === "POST") {
        const body = JSON.parse(String(options.body ?? "{}")) as {
          use_suggested_section?: boolean;
        };
        expect(body.use_suggested_section).toBe(true);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: "F-12",
              section: "Functionality",
              plain: "Keep PII out of analytics.",
              rule: "Do not put email in analytics user properties.",
              app: "platform",
            }),
        } as Response);
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) } as Response);
    });
    renderPanel(onSaved);
    openAddForm();
    fireEvent.change(screen.getByLabelText(/rule description/i), {
      target: { value: "Do not send email in analytics user properties." },
    });
    fireEvent.click(screen.getByRole("button", { name: /check idea/i }));
    expect(
      await screen.findByText(/functionality check, not code quality/i)
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /save under functionality instead/i })
    );
    expect(screen.getByText(/suggested wording for f-12\./i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save this rule/i }));
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("puts Cancel next to Check idea and closes the accordion", () => {
    renderPanel();
    openAddForm();
    const checkIdea = screen.getByRole("button", { name: /check idea/i });
    const cancel = screen.getByRole("button", { name: /cancel/i });
    expect(checkIdea.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/rule description/i), {
      target: { value: "A temporary idea to clear." },
    });
    fireEvent.click(cancel);
    expect(screen.queryByRole("button", { name: /check idea/i })).toBeNull();
    expect(screen.getByRole("button", { name: /add rule/i })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
  });
});
