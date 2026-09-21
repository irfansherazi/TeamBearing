/**
 * ReviewRulesPage Tests
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ReviewRulesPage } from "../ReviewRulesPage";
import { authenticatedFetch } from "../../api_client";

vi.mock("../../api_client", () => ({
  authenticatedFetch: vi.fn(),
}));

const platformPayload = {
  app: "platform",
  label: "vsuitePlatform",
  source: "standards/platform/pr-review-checklist.md",
  sections: [
    {
      name: "Code Quality",
      rules: [
        {
          id: "CQ-01",
          plain: "Changed code should match how this team already names, formats, and structures files.",
          rule: "Code follows team conventions (naming, formatting, structure).",
        },
        {
          id: "CQ-02",
          plain: "No leftover commented-out code or unused dead code.",
          rule: "No commented-out or dead code.",
        },
      ],
    },
  ],
};

const vcapiPayload = {
  app: "vcapi",
  label: "vcapi",
  source: "standards/vcapi/pr-review-checklist.md",
  sections: [
    {
      name: "Code Quality",
      rules: [
        {
          id: "CQ-05",
          plain: "No console.log inside NestJS services or controllers.",
          rule: "No console.log / debugger inside NestJS services or controllers.",
        },
      ],
    },
  ],
};

const renderCases = [
  {
    description: "renders the Review rules heading",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByRole("heading", { name: /review rules/i })).toBeInTheDocument();
    },
  },
  {
    description: "renders App, Search, Category, and Add rule accordion",
    setup: () => undefined,
    expectations: () => {
      expect(screen.getByLabelText(/^app$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^search$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^category$/i)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: /add rule/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /add rule/i })).toHaveAttribute(
        "aria-expanded",
        "false"
      );
      expect(screen.queryByRole("button", { name: /check idea/i })).toBeNull();
    },
  },
];

describe("ReviewRulesPage — initial render", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(platformPayload),
    } as Response);
  });

  renderCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      setup();
      render(<ReviewRulesPage />);
      expectations();
    });
  });
});

describe("ReviewRulesPage — loaded rules", () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockReset();
  });

  it("shows CQ-01 with a plain-language explanation", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(platformPayload),
    } as Response);
    render(<ReviewRulesPage />);
    expect(await screen.findByText("CQ-01")).toBeInTheDocument();
    expect(
      screen.getByText(/match how this team already names/i)
    ).toBeInTheDocument();
    expect(screen.getByText("CQ-02")).toBeInTheDocument();
  });

  it("filters rules when the search box is used", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(platformPayload),
    } as Response);
    render(<ReviewRulesPage />);
    await screen.findByText("CQ-01");
    fireEvent.change(screen.getByLabelText(/^search$/i), {
      target: { value: "CQ-02" },
    });
    expect(screen.getByText("CQ-02")).toBeInTheDocument();
    expect(screen.queryByText("CQ-01")).toBeNull();
  });

  it("loads vcapi rules when the app select changes", async () => {
    vi.mocked(authenticatedFetch).mockImplementation((url: string) => {
      const path = String(url);
      if (path.includes("app=vcapi")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(vcapiPayload),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(platformPayload),
      } as Response);
    });
    render(<ReviewRulesPage />);
    await screen.findByText("CQ-01");
    fireEvent.change(screen.getByLabelText(/^app$/i), {
      target: { value: "vcapi" },
    });
    expect(await screen.findByText("CQ-05")).toBeInTheDocument();
    expect(screen.queryByText("CQ-01")).toBeNull();
  });

  it("shows an error when the rules request fails", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
    } as Response);
    render(<ReviewRulesPage />);
    expect(
      await screen.findByText(/could not load review rules/i)
    ).toBeInTheDocument();
  });
});
