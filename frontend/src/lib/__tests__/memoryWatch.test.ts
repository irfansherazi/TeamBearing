/**
 * Memory Watch parser tests
 */

import { describe, it, expect } from "vitest";
import {
  formatFlowLabel,
  memoryOutcomeLabel,
  parseMemoryChecklistFromLog,
  parseMemorySampleLine,
  parseMemoryVerdictLine,
  upsertMemorySample,
} from "../memoryWatch";

const sampleCases = [
  {
    description: "parses a sample line",
    setup: () =>
      'MEMORY_WATCH_SAMPLE {"cycle":1,"label":"cycle-1","usedMb":48.2,"deltaMb":6.1,"gcRuns":3,"status":"watching"}',
    expectations: (result: ReturnType<typeof parseMemorySampleLine>) => {
      expect(result?.cycle).toBe(1);
      expect(result?.usedMb).toBe(48.2);
    },
  },
  {
    description: "returns null for a log line",
    setup: () => "not a sample",
    expectations: (result: ReturnType<typeof parseMemorySampleLine>) => {
      expect(result).toBeNull();
    },
  },
];

describe("parseMemorySampleLine", () => {
  sampleCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(parseMemorySampleLine(setup()));
    });
  });
});

const verdictCases = [
  {
    description: "parses a pass verdict",
    setup: () =>
      'MEMORY_WATCH_VERDICT {"pass":true,"growthMb":8.1,"overCap":false,"strictlyIncreasing":false,"reason":"ok"}',
    expectations: (result: ReturnType<typeof parseMemoryVerdictLine>) => {
      expect(result?.pass).toBe(true);
      expect(result?.growthMb).toBe(8.1);
    },
  },
];

describe("parseMemoryVerdictLine", () => {
  verdictCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(parseMemoryVerdictLine(setup()));
    });
  });
});

describe("upsertMemorySample", () => {
  it("replaces the same cycle", () => {
    const first = {
      cycle: 0,
      label: "baseline",
      usedMb: 40,
      deltaMb: 0,
      gcRuns: 3,
      status: "watching",
    };
    const second = { ...first, usedMb: 41 };
    const result = upsertMemorySample([first], second);
    expect(result).toHaveLength(1);
    expect(result[0].usedMb).toBe(41);
  });
});

describe("formatFlowLabel", () => {
  it("labels po-open-spot", () => {
    expect(formatFlowLabel("po-open-spot")).toContain("Production Orders");
  });
});

describe("parseMemoryChecklistFromLog", () => {
  it("reads HEAP PASS from markdown", () => {
    const rows = parseMemoryChecklistFromLog("| HEAP | PASS | +8 MB |\n| FLOW | PASS | ok |");
    expect(rows[0].item).toBe("HEAP");
    expect(rows[0].status).toBe("PASS");
  });
});

describe("memoryOutcomeLabel", () => {
  it("returns PASS when verdict_pass is true", () => {
    expect(
      memoryOutcomeLabel({
        run_id: "mw-abcd1234",
        status: "completed",
        flow: "po-open-spot",
        env: "qa",
        cycles: 5,
        verdict_pass: true,
        growth_mb: 8,
        started_at: "2026-09-07T00:00:00+00:00",
        finished_at: "2026-09-07T00:10:00+00:00",
      })
    ).toBe("PASS");
  });
});
