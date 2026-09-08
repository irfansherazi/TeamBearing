/**
 * AI Review history formatter tests
 */

import { describe, it, expect } from "vitest";
import {
  appBadgeClass,
  formatAppLabel,
  formatReviewCommand,
  formatReviewCounts,
  formatReviewWhen,
  historyOutcomeClass,
  historyOutcomeLabel,
  historyStatusClass,
  parseChangedFiles,
  toChecklistRows,
  toHistoryOutcome,
  toHistoryStatus,
} from "../aiReviewHistory";

const countCases = [
  {
    description: "formats PASS FAIL SKIP counts",
    setup: () => ({ pass_count: 18, fail_count: 4, skip_count: 2 }),
    expectations: (result: string) => {
      expect(result).toBe("18 PASS / 4 FAIL / 2 SKIP");
    },
  },
  {
    description: "formats zeros",
    setup: () => ({ pass_count: 0, fail_count: 0, skip_count: 0 }),
    expectations: (result: string) => {
      expect(result).toBe("0 PASS / 0 FAIL / 0 SKIP");
    },
  },
];

describe("formatReviewCounts", () => {
  countCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(formatReviewCounts(setup()));
    });
  });
});

const whenCases = [
  {
    description: "returns the raw string when the date is invalid",
    setup: () => "not-a-date",
    expectations: (result: string) => {
      expect(result).toBe("not-a-date");
    },
  },
  {
    description: "formats a valid ISO timestamp to a locale string",
    setup: () => "2026-08-27T11:00:00+00:00",
    expectations: (result: string) => {
      expect(result.length).toBeGreaterThan(0);
      expect(result).not.toBe("2026-08-27T11:00:00+00:00");
    },
  },
];

describe("formatReviewWhen", () => {
  whenCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(formatReviewWhen(setup()));
    });
  });
});

const appLabelCases = [
  {
    description: "labels platform as vsuitePlatform",
    setup: () => "platform",
    expectations: (result: string) => {
      expect(result).toBe("vsuitePlatform");
    },
  },
  {
    description: "labels vcapi as vcapi",
    setup: () => "vcapi",
    expectations: (result: string) => {
      expect(result).toBe("vcapi");
    },
  },
];

describe("formatAppLabel", () => {
  appLabelCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(formatAppLabel(setup()));
    });
  });
});

const appBadgeCases = [
  {
    description: "uses the vcapi badge class for vcapi",
    setup: () => "vcapi",
    expectations: (result: string) => {
      expect(result).toContain("ai-review-app-badge--vcapi");
    },
  },
  {
    description: "uses the platform badge class otherwise",
    setup: () => "platform",
    expectations: (result: string) => {
      expect(result).toContain("ai-review-app-badge--platform");
    },
  },
];

describe("appBadgeClass", () => {
  appBadgeCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(appBadgeClass(setup()));
    });
  });
});

const commandCases = [
  {
    description: "builds the npm command without commits",
    setup: () => ({
      app: "vcapi",
      branch: "Syed/VC2-9357",
      base: "develop",
      commits: "",
    }),
    expectations: (result: string) => {
      expect(result).toBe(
        "npm run ai:review -- --app=vcapi --branch=Syed/VC2-9357 --base=develop"
      );
    },
  },
  {
    description: "appends commits when present",
    setup: () => ({
      app: "platform",
      branch: "feat/x",
      base: "Develop",
      commits: "abc123",
    }),
    expectations: (result: string) => {
      expect(result).toContain("--commits=abc123");
    },
  },
];

describe("formatReviewCommand", () => {
  commandCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(formatReviewCommand(setup()));
    });
  });
});

const fileCases = [
  {
    description: "parses Files reviewed comma list from a saved log",
    setup: () =>
      "REVIEW ONLY\nFiles reviewed (2): src/a.ts, src/b.ts\nChecklist Results:",
    expectations: (result: string[]) => {
      expect(result).toEqual(["src/a.ts", "src/b.ts"]);
    },
  },
  {
    description: "parses Changed files bullets from a saved log",
    setup: () =>
      "Scope\nChanged files (2):\n- src/a.ts\n- src/b.ts\n\nNext section",
    expectations: (result: string[]) => {
      expect(result).toEqual(["src/a.ts", "src/b.ts"]);
    },
  },
  {
    description: "returns empty when the log has no file list",
    setup: () => "saved log line",
    expectations: (result: string[]) => {
      expect(result).toEqual([]);
    },
  },
];

describe("parseChangedFiles", () => {
  fileCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(parseChangedFiles(setup()));
    });
  });
});

const outcomeCases = [
  {
    description: "completed with no fails is Pass",
    setup: () => ({ status: "completed", fail_count: 0 }),
    expectations: (result: string) => {
      expect(result).toBe("pass");
      expect(historyOutcomeLabel("pass")).toBe("Pass");
      expect(historyOutcomeClass("pass")).toBe("ai-review-run-status-completed");
    },
  },
  {
    description: "completed with fails is Fail",
    setup: () => ({ status: "completed", fail_count: 4 }),
    expectations: (result: string) => {
      expect(result).toBe("fail");
    },
  },
  {
    description: "running stays Running",
    setup: () => ({ status: "running", fail_count: 0 }),
    expectations: (result: string) => {
      expect(result).toBe("running");
    },
  },
];

describe("toHistoryOutcome", () => {
  outcomeCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(toHistoryOutcome(setup()));
    });
  });
});

const statusCases = [
  {
    description: "maps completed to the green class",
    setup: () => "completed" as const,
    expectations: (result: string) => {
      expect(result).toBe("ai-review-run-status-completed");
    },
  },
  {
    description: "maps unknown API status to failed",
    setup: () => "nope",
    expectations: (result: string) => {
      expect(toHistoryStatus(result)).toBe("failed");
    },
  },
];

describe("history status helpers", () => {
  it(statusCases[0].description, () => {
    expect(historyStatusClass(statusCases[0].setup())).toBe(
      "ai-review-run-status-completed"
    );
  });
  it(statusCases[1].description, () => {
    statusCases[1].expectations(statusCases[1].setup());
  });
});

describe("toChecklistRows", () => {
  it("keeps known statuses and drops unknown ones", () => {
    const rows = toChecklistRows([
      { item: "CQ-01", status: "FAIL", evidence: "a" },
      { item: "XX", status: "WEIRD", evidence: "b" },
      { item: "PH-01", status: "SKIP" },
    ]);
    expect(rows).toEqual([
      { item: "CQ-01", status: "FAIL", evidence: "a" },
      { item: "PH-01", status: "SKIP", evidence: "" },
    ]);
  });
});
