/**
 * Memory Watch parser tests
 */

import { describe, it, expect } from "vitest";
import {
  formatFlowLabel,
  getFlowPreviewSteps,
  isFixedRitualFlow,
  memoryOutcomeLabel,
  parseMemoryChecklistFromLog,
  parseMemorySampleLine,
  parseMemoryVerdictLine,
  summarizeMemoryWatchFailure,
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
  it("labels qo-open-close-snapshot", () => {
    expect(formatFlowLabel("qo-open-close-snapshot")).toContain("Quick Order");
  });
});

describe("getFlowPreviewSteps", () => {
  const stepCases = [
    {
      description: "returns the Quick Order ritual steps",
      setup: () => "qo-open-close-snapshot",
      expectations: (result: string[]) => {
        expect(result[0]).toMatch(/screen recording/i);
        expect(result.some((step) => /suzan goritz/i.test(step))).toBe(true);
      },
    },
    {
      description: "returns empty for an unknown flow",
      setup: () => "not-a-flow",
      expectations: (result: string[]) => {
        expect(result).toEqual([]);
      },
    },
  ];

  stepCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(getFlowPreviewSteps(setup()));
    });
  });
});

describe("isFixedRitualFlow", () => {
  it("is true for the Quick Order snapshot ritual", () => {
    expect(isFixedRitualFlow("qo-open-close-snapshot")).toBe(true);
    expect(isFixedRitualFlow("po-open-spot")).toBe(false);
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
        flow: "qo-open-close-snapshot",
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

describe("summarizeMemoryWatchFailure", () => {
  it("returns null for an empty log", () => {
    expect(summarizeMemoryWatchFailure("")).toBeNull();
  });

  it("identifies a login failure over an earlier setup warning", () => {
    const log = [
      "⚠️ STORAGE_DIR does not exist: /storage/qa",
      "⚠️ No available users detected. Proceeding without storage state.",
      "🔍 Current session state: no-selection",
      "    Error: expect(locator).toBeVisible() failed",
      "        at login (../utils/loginHelper.mjs:182:46)",
    ].join("\n");
    const summary = summarizeMemoryWatchFailure(log);
    expect(summary?.phase).toBe("Login / session");
    expect(summary?.reason).toBe("expect(locator).toBeVisible() failed");
  });

  it("identifies a dead-target page timeout", () => {
    const log = [
      "  x  3 [chromium] › memory-watch.test.ts (retry #2)",
      "Test timeout of 90000ms exceeded while setting up \"page\".",
    ].join("\n");
    expect(summarizeMemoryWatchFailure(log)?.phase).toBe("Page load / connection");
  });

  it("falls back to a plain Cannot-prefixed line when there is no Error: marker", () => {
    const log = [
      "⚠️ STORAGE_DIR does not exist: /storage/qa",
      "Cannot use({ video }) in a describe group, because it forces a new worker.",
    ].join("\n");
    const summary = summarizeMemoryWatchFailure(log);
    expect(summary?.reason).toBe(
      "Cannot use({ video }) in a describe group, because it forces a new worker."
    );
  });

  it("returns null when the log has no recognizable failure signal", () => {
    const log = "Running 1 test using 1 worker\nAll good, nothing to see here.";
    expect(summarizeMemoryWatchFailure(log)).toBeNull();
  });
});
