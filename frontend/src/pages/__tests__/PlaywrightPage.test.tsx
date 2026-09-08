import { describe, it, expect } from "vitest";
import { getTestDisplayName } from "../../lib/testFormatting";

describe("PlaywrightPage — getTestDisplayName formatting utility", () => {
  it("formats standard QA ticket files with .test suffix correctly (e.g., qa-172-sales.test.ts)", () => {
    const testObj = {
      id: "qa-172-sales.test",
      file: "tests/qa-172-sales.test.ts",
    };
    expect(getTestDisplayName(testObj)).toBe("QA-172 Sales Test");
  });

  it("formats standard QA ticket files (e.g., qa-175-lockout.test.ts)", () => {
    const testObj = {
      id: "qa-175-lockout.test",
      file: "tests/qa-175-lockout.test.ts",
    };
    expect(getTestDisplayName(testObj)).toBe("QA-175 Lockout Test");
  });

  it("formats QA ticket files with multiple hyphens (e.g., qa-185-saved-searches-sharing.test.ts)", () => {
    const testObj = {
      id: "qa-185-saved-searches-sharing.test",
      file: "tests/qa-185-saved-searches-sharing.test.ts",
    };
    expect(getTestDisplayName(testObj)).toBe("QA-185 Saved Searches Sharing Test");
  });

  it("handles non-Jira files with underscores and suffixes nicely (e.g., email_check_validation.test.ts)", () => {
    const testObj = {
      id: "email_check_validation.test",
      file: "tests/email_check_validation.test.ts",
    };
    expect(getTestDisplayName(testObj)).toBe("Email Check Validation Test");
  });

  it("handles camelCase utilities and files without 'test' suffixes nicely (e.g., filePreWashUtility.ts)", () => {
    const testObj = {
      id: "filePreWashUtility",
      file: "tests/filePreWashUtility.ts",
    };
    expect(getTestDisplayName(testObj)).toBe("File Pre Wash Utility Test");
  });

  it("respects pre-defined display_name if present in the metadata", () => {
    const testObj = {
      id: "custom-test-id",
      file: "tests/some_file.ts",
      display_name: "My Custom Awesome Test",
    };
    expect(getTestDisplayName(testObj)).toBe("My Custom Awesome Test");
  });

  it("handles files without path prefixes or file properties gracefully using id", () => {
    const testObj = {
      id: "qa-123-simple",
      file: "",
    };
    expect(getTestDisplayName(testObj)).toBe("QA-123 Simple Test");
  });
});
