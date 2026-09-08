/** Formats a test ID / filename into a human-readable display name */
export function getTestDisplayName(test: { id: string; file: string; display_name?: string }): string {
  if (test.display_name) return test.display_name;

  // Suffixes and path segments cleaning
  const filename = test.file ? (test.file.split("/").pop() || "") : "";
  const nameToFormat = filename || test.id || "";
  const clean = nameToFormat
    .replace(/\.(test|spec)?\.(ts|js)$/, "")
    .replace(/\.(test|spec|ts|js)$/, "");

  // Match Ticket patterns like qa-172-sales
  const qaMatch = clean.match(/^qa[-_]?(\d+)[-_]?(.*)$/i);
  if (qaMatch) {
    const num = qaMatch[1];
    const rest = qaMatch[2];
    const formattedRest = rest
      .split(/[-_]+/)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
    return `QA-${num} ${formattedRest} Test`;
  }

  // Fallback: camelCase, hyphens, underscores, capitalization, and append "Test"
  let formatted = clean.replace(/([a-z])([A-Z])/g, "$1 $2");
  formatted = formatted.replace(/[-_]+/g, " ");
  formatted = formatted
    .split(/\s+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

  if (!formatted.toLowerCase().endsWith("test")) {
    formatted = `${formatted} Test`;
  }
  return formatted;
}
