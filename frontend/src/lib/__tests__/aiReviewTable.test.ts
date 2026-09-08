/**
 * parseReviewTableRow / upsertReviewRow unit tests
 */

import { describe, it, expect } from "vitest";
import { parseReviewTableRow, upsertReviewRow } from "../aiReviewTable";

const parseCases = [
  {
    description: "parses a FAIL checklist row",
    setup: () => "| CQ-01 | FAIL | stray indent |",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result).toEqual({
        item: "CQ-01",
        status: "FAIL",
        evidence: "stray indent",
      });
    },
  },
    {
    description: "parses a PASS row",
    setup: () => "| CQ-05 | PASS | no console.log |",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result?.status).toBe("PASS");
      expect(result?.item).toBe("CQ-05");
    },
  },
  {
    description: "parses a SKIP row",
    setup: () => "| PH-01 | SKIP | no PR yet |",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result).toEqual({
        item: "PH-01",
        status: "SKIP",
        evidence: "no PR yet",
      });
    },
  },
  {
    description: "skips markdown separator",
    setup: () => "|---|---|---|",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result).toBeNull();
    },
  },
  {
    description: "skips header row",
    setup: () => "| Check | PASS / FAIL | Evidence |",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result).toBeNull();
    },
  },
  {
    description: "ignores non-table lines",
    setup: () => "Running review...",
    expectations: (result: ReturnType<typeof parseReviewTableRow>) => {
      expect(result).toBeNull();
    },
  },
];

describe("parseReviewTableRow", () => {
  parseCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(parseReviewTableRow(setup()));
    });
  });
});

describe("upsertReviewRow", () => {
  it("appends a new item and replaces an existing one", () => {
    const first = { item: "CQ-01", status: "FAIL" as const, evidence: "a" };
    const second = { item: "CQ-02", status: "PASS" as const, evidence: "b" };
    const updated = { item: "CQ-01", status: "PASS" as const, evidence: "fixed" };
    const afterInsert = upsertReviewRow(upsertReviewRow([], first), second);
    expect(afterInsert).toHaveLength(2);
    const afterReplace = upsertReviewRow(afterInsert, updated);
    expect(afterReplace).toHaveLength(2);
    expect(afterReplace[0]).toEqual(updated);
  });
});
