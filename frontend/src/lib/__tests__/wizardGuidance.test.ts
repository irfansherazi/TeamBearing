import { describe, it, expect } from "vitest";
import { buildGuidance } from "../wizardGuidance";

describe("buildGuidance", () => {
  it("emits one Exclude line per deselected path and one Clarification line per non-empty resolution", () => {
    const allPaths = [
      "HDah > Module Abilities > Edit Module",
      "HDah > Module Abilities > Delete Module",
      "HDah > Reports > Usage",
    ];
    const selectedPaths = [
      "HDah > Module Abilities > Edit Module",
      "HDah > Module Abilities > Delete Module",
    ];
    const resolutions: Record<string, string> = {
      "correct total": "The sum of all line items in the invoice",
    };

    const result = buildGuidance(allPaths, selectedPaths, resolutions);

    expect(result).toContain("Exclude path: HDah > Reports > Usage");
    expect(result).not.toContain("Exclude path: HDah > Module Abilities > Edit Module");
    expect(result).not.toContain("Exclude path: HDah > Module Abilities > Delete Module");
    expect(result).toContain(
      'Clarification — "correct total": The sum of all line items in the invoice'
    );
  });

  it("returns an empty string when all paths are selected and no resolutions are provided", () => {
    const allPaths = ["HDah > Module Abilities > Edit Module"];
    const selectedPaths = ["HDah > Module Abilities > Edit Module"];
    const resolutions: Record<string, string> = {};

    const result = buildGuidance(allPaths, selectedPaths, resolutions);

    expect(result).toBe("");
  });

  it("ignores ambiguity resolutions that are blank or whitespace-only", () => {
    const allPaths = ["Path A"];
    const selectedPaths = ["Path A"];
    const resolutions: Record<string, string> = {
      "vague term": "   ",
      "another term": "",
    };

    const result = buildGuidance(allPaths, selectedPaths, resolutions);

    expect(result).toBe("");
  });

  it("trims whitespace from resolution values before serializing", () => {
    const allPaths = ["Path A"];
    const selectedPaths = ["Path A"];
    const resolutions: Record<string, string> = {
      "sort direction": "  ascending  ",
    };

    const result = buildGuidance(allPaths, selectedPaths, resolutions);

    expect(result).toBe('Clarification — "sort direction": ascending');
  });

  it("handles multiple excluded paths and multiple resolutions with correct newline separation", () => {
    const allPaths = ["Path A", "Path B", "Path C"];
    const selectedPaths = ["Path A"];
    const resolutions: Record<string, string> = {
      "term one": "resolution one",
      "term two": "resolution two",
    };

    const result = buildGuidance(allPaths, selectedPaths, resolutions);
    const lines = result.split("\n");

    expect(lines).toContain("Exclude path: Path B");
    expect(lines).toContain("Exclude path: Path C");
    expect(lines).toContain('Clarification — "term one": resolution one');
    expect(lines).toContain('Clarification — "term two": resolution two');
    expect(lines.length).toBe(4);
  });
});
