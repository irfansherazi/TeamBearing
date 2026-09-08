/**
 * Parse PASS/FAIL rows from vsuitePlatform `npm run ai:review` markdown output.
 */

export type AiReviewStatus = "PASS" | "FAIL" | "N/A" | "SKIP";

export interface AiReviewTableRow {
  item: string;
  status: AiReviewStatus;
  evidence: string;
}

const HEADER_ITEMS = new Set(["check", "item", "id", "review", "review item"]);

/**
 * Parse one markdown table line into a review row.
 *
 * @param line - A single stdout line
 * @returns The row, or null when the line is not a results row
 */
export function parseReviewTableRow(line: string): AiReviewTableRow | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) {
    return null;
  }
  const cells = trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
  if (cells.length < 3) {
    return null;
  }
  const item = cells[0];
  let statusRaw = cells[1].toUpperCase().replace(/\s/g, "");
  const evidence = cells.slice(2).join(" | ").trim();
  if (item.startsWith("-") || item.includes("---")) {
    return null;
  }
  if (HEADER_ITEMS.has(item.toLowerCase())) {
    return null;
  }
  if (statusRaw === "NA") {
    statusRaw = "N/A";
  }
  if (statusRaw !== "PASS" && statusRaw !== "FAIL" && statusRaw !== "N/A" && statusRaw !== "SKIP") {
    return null;
  }
  if (!/^[A-Za-z][A-Za-z0-9._-]*$/.test(item)) {
    return null;
  }
  return { item, status: statusRaw, evidence };
}

/**
 * Merge a newly parsed row into the table, replacing an existing item id.
 *
 * @param rows - Current table rows
 * @param next - Newly parsed row
 * @returns Updated row list
 */
export function upsertReviewRow(
  rows: AiReviewTableRow[],
  next: AiReviewTableRow
): AiReviewTableRow[] {
  const index = rows.findIndex((row) => row.item === next.item);
  if (index < 0) {
    return [...rows, next];
  }
  const updated = [...rows];
  updated[index] = next;
  return updated;
}
