/**
 * reviewRules helper tests
 */

import { describe, it, expect } from "vitest";
import {
  countReviewRules,
  filterReviewRuleSections,
  isReviewRuleCodeQuery,
  reviewRuleSectionDiffers,
  reviewRuleSectionId,
  reviewRuleWordingLegend,
  type ReviewRuleSection,
} from "../reviewRules";

const sections: ReviewRuleSection[] = [
  {
    name: "Code Quality",
    rules: [
      { id: "CQ-01", plain: "Follow team conventions.", rule: "Code follows team conventions." },
      { id: "CQ-02", plain: "No leftover commented code.", rule: "No commented-out or dead code." },
      {
        id: "CQ-22",
        plain: "New HTML controls have a unique hyphenated id.",
        rule: 'have a unique hyphen-separated id (e.g. id="example-of-id")',
      },
    ],
  },
  {
    name: "Functionality",
    rules: [
      { id: "F-01", plain: "No accidental feature changes.", rule: "No unintended functionality changes." },
      { id: "F-02", plain: "No unexpected side effects.", rule: "No side effects introduced." },
    ],
  },
  {
    name: "Documentation",
    rules: [
      {
        id: "D-01",
        plain: "The code is readable on its own.",
        rule: "Code is self-explanatory or properly commented.",
      },
    ],
  },
];

const filterCases = [
  {
    description: "returns all sections when the query is blank",
    setup: () => ({ query: "  ", expectedIds: ["CQ-01", "CQ-02", "CQ-22", "F-01", "F-02", "D-01"] }),
    expectations: (result: ReviewRuleSection[], expectedIds: string[]) => {
      const ids = result.flatMap((section) => section.rules.map((rule) => rule.id));
      expect(ids).toEqual(expectedIds);
    },
  },
  {
    description: "matches a checklist id",
    setup: () => ({ query: "cq-02", expectedIds: ["CQ-02"] }),
    expectations: (result: ReviewRuleSection[], expectedIds: string[]) => {
      const ids = result.flatMap((section) => section.rules.map((rule) => rule.id));
      expect(ids).toEqual(expectedIds);
    },
  },
  {
    description: "F- matches only Functionality codes, not of-id or self-explanatory",
    setup: () => ({ query: "F-", expectedIds: ["F-01", "F-02"] }),
    expectations: (result: ReviewRuleSection[], expectedIds: string[]) => {
      const ids = result.flatMap((section) => section.rules.map((rule) => rule.id));
      expect(ids).toEqual(expectedIds);
    },
  },
  {
    description: "matches a section heading and keeps every rule in it",
    setup: () => ({ query: "functionality", expectedIds: ["F-01", "F-02"] }),
    expectations: (result: ReviewRuleSection[], expectedIds: string[]) => {
      expect(result).toHaveLength(1);
      const ids = result.flatMap((section) => section.rules.map((rule) => rule.id));
      expect(ids).toEqual(expectedIds);
    },
  },
  {
    description: "word search still matches official wording",
    setup: () => ({ query: "self-explanatory", expectedIds: ["D-01"] }),
    expectations: (result: ReviewRuleSection[], expectedIds: string[]) => {
      const ids = result.flatMap((section) => section.rules.map((rule) => rule.id));
      expect(ids).toEqual(expectedIds);
    },
  },
];

describe("filterReviewRuleSections", () => {
  filterCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      const { query, expectedIds } = setup();
      const result = filterReviewRuleSections(sections, query);
      expectations(result, expectedIds);
    });
  });
});

describe("isReviewRuleCodeQuery", () => {
  const cases = [
    { description: "treats F- as a code query", setup: () => "F-", expectations: (result: boolean) => expect(result).toBe(true) },
    { description: "treats cq-01 as a code query", setup: () => "cq-01", expectations: (result: boolean) => expect(result).toBe(true) },
    { description: "does not treat self-explanatory as a code query", setup: () => "self-explanatory", expectations: (result: boolean) => expect(result).toBe(false) },
    { description: "does not treat a word search as a code query", setup: () => "timers", expectations: (result: boolean) => expect(result).toBe(false) },
  ];

  cases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(isReviewRuleCodeQuery(setup().trim().toLowerCase()));
    });
  });
});

describe("countReviewRules", () => {
  it("sums rules across sections", () => {
    expect(countReviewRules(sections)).toBe(6);
  });
});

describe("reviewRuleSectionId", () => {
  it("slugifies a heading", () => {
    expect(reviewRuleSectionId("Code Quality")).toBe("code-quality");
  });
});

describe("reviewRuleSectionDiffers", () => {
  const cases = [
    {
      description: "is false when the AI keeps the same section",
      setup: () => ({ picked: "Code Quality", suggested: "Code Quality" }),
      expectations: (result: boolean) => expect(result).toBe(false),
    },
    {
      description: "is true when the AI recommends another section",
      setup: () => ({ picked: "Code Quality", suggested: "Functionality" }),
      expectations: (result: boolean) => expect(result).toBe(true),
    },
  ];

  cases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      const { picked, suggested } = setup();
      expectations(reviewRuleSectionDiffers(picked, suggested));
    });
  });
});

describe("reviewRuleWordingLegend", () => {
  const cases = [
    {
      description: "names the code with no pick-one prompt",
      setup: () => "CQ-34",
      expectations: (result: string) => expect(result).toBe("Suggested wording for CQ-34."),
    },
    {
      description: "uses the Functionality code when that is the assigned id",
      setup: () => "F-12",
      expectations: (result: string) => expect(result).toBe("Suggested wording for F-12."),
    },
  ];

  cases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
      expectations(reviewRuleWordingLegend(setup()));
    });
  });
});
