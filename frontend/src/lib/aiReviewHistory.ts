/**
 * Types and formatters for AI Review history list/detail.
 */

import type { AiReviewStatus, AiReviewTableRow } from "./aiReviewTable";

export type AiReviewRunHistoryStatus =
  | "running"
  | "completed"
  | "failed"
  | "stopped";

export interface AiReviewHistoryItem {
  review_id: string;
  status: AiReviewRunHistoryStatus;
  app: string;
  branch: string;
  base: string;
  commits: string;
  pass_count: number;
  fail_count: number;
  skip_count: number;
  started_at: string;
  finished_at: string | null;
}

export interface AiReviewHistoryDetail extends AiReviewHistoryItem {
  rows: AiReviewTableRow[];
  log_text: string;
}

export type HistoryOutcome = "pass" | "fail" | "running" | "stopped";

const CHECKLIST_STATUSES = new Set<AiReviewStatus>(["PASS", "FAIL", "N/A", "SKIP"]);

/**
 * Format PASS / FAIL / SKIP counts for the history Result column.
 *
 * @param item - History row counts
 * @returns Display string
 */
export function formatReviewCounts(item: {
  pass_count: number;
  fail_count: number;
  skip_count: number;
}): string {
  return `${item.pass_count} PASS / ${item.fail_count} FAIL / ${item.skip_count} SKIP`;
}

/**
 * Format a stored ISO timestamp for the history When column.
 *
 * @param iso - started_at from the API
 * @returns Locale datetime, or the raw string when unparseable
 */
export function formatReviewWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Display name for a review target app.
 *
 * @param app - API app id
 * @returns Label for the UI
 */
export function formatAppLabel(app: string): string {
  const key = (app ?? "platform").trim().toLowerCase();
  switch (key) {
    case "vcapi":
      return "vcapi";
    case "platform":
    case "vsuite":
    case "vsuiteplatform":
      return "vsuitePlatform";
    default:
      return app || "vsuitePlatform";
  }
}

/**
 * CSS class for an app badge so platform and vcapi are easy to tell apart.
 *
 * @param app - API app id
 * @returns CSS class name
 */
export function appBadgeClass(app: string): string {
  const key = (app ?? "platform").trim().toLowerCase();
  return key === "vcapi"
    ? "ai-review-app-badge ai-review-app-badge--vcapi"
    : "ai-review-app-badge ai-review-app-badge--platform";
}

/**
 * Rebuild the npm command that produced this review.
 *
 * @param item - Saved run fields
 * @returns Command string
 */
export function formatReviewCommand(item: {
  app: string;
  branch: string;
  base: string;
  commits: string;
}): string {
  const parts = [
    "npm run ai:review --",
    `--app=${item.app || "platform"}`,
    `--branch=${item.branch}`,
    `--base=${item.base}`,
  ];
  if (item.commits) {
    parts.push(`--commits=${item.commits}`);
  }
  return parts.join(" ");
}

/**
 * Pull changed-file paths from a saved ai:review log.
 *
 * @param logText - Captured stdout
 * @returns File paths in log order
 */
export function parseChangedFiles(logText: string): string[] {
  if (!logText) {
    return [];
  }
  const reportMatch = logText.match(/Files reviewed \(\d+\):\s*(.*)/);
  if (reportMatch) {
    const raw = (reportMatch[1] ?? "").trim();
    if (!raw || raw === "(none)") {
      return [];
    }
    return raw
      .split(",")
      .map((file) => file.trim())
      .filter((file) => file.length > 0 && !file.startsWith("Checklist"));
  }
  const lines = logText.split(/\r?\n/);
  const start = lines.findIndex((line) => /^Changed files \(\d+\):/.test(line.trim()));
  if (start < 0) {
    return [];
  }
  const files: string[] = [];
  for (const line of lines.slice(start + 1)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("- ")) {
      break;
    }
    const path = trimmed.slice(2).trim();
    if (path) {
      files.push(path);
    }
  }
  return files;
}

/**
 * Overall Pass/Fail (or in-progress) for the history list.
 *
 * @param item - Saved run status and fail count
 * @returns Outcome used on the list badge
 */
export function toHistoryOutcome(item: {
  status: string;
  fail_count: number;
}): HistoryOutcome {
  const status = toHistoryStatus(item.status);
  switch (status) {
    case "running":
      return "running";
    case "stopped":
      return "stopped";
    case "completed":
      return item.fail_count > 0 ? "fail" : "pass";
    case "failed":
      return "fail";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

/**
 * Short label for a list/detail outcome badge.
 *
 * @param outcome - Pass/Fail/Running/Stopped
 * @returns Display label
 */
export function historyOutcomeLabel(outcome: HistoryOutcome): string {
  switch (outcome) {
    case "pass":
      return "Pass";
    case "fail":
      return "Fail";
    case "running":
      return "Running";
    case "stopped":
      return "Stopped";
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
}

/**
 * CSS class for a Pass/Fail outcome badge.
 *
 * @param outcome - Pass/Fail/Running/Stopped
 * @returns CSS class name
 */
export function historyOutcomeClass(outcome: HistoryOutcome): string {
  switch (outcome) {
    case "pass":
      return "ai-review-run-status-completed";
    case "fail":
      return "ai-review-run-status-failed";
    case "running":
      return "ai-review-run-status-running";
    case "stopped":
      return "ai-review-run-status-stopped";
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
}

/**
 * CSS class for a saved-run status badge.
 *
 * @param status - History run status
 * @returns CSS class name
 */
export function historyStatusClass(status: AiReviewRunHistoryStatus): string {
  switch (status) {
    case "completed":
      return "ai-review-run-status-completed";
    case "failed":
      return "ai-review-run-status-failed";
    case "running":
      return "ai-review-run-status-running";
    case "stopped":
      return "ai-review-run-status-stopped";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

/**
 * Coerce an API status string to a known history status.
 *
 * @param value - Raw status from the API
 * @returns Known status, or failed when unrecognized
 */
export function toHistoryStatus(value: string): AiReviewRunHistoryStatus {
  switch (value) {
    case "running":
    case "completed":
    case "failed":
    case "stopped":
      return value;
    default:
      return "failed";
  }
}

/**
 * Keep checklist rows whose status the results table can render.
 *
 * @param rows - Saved checklist rows
 * @returns Typed checklist rows
 */
export function toChecklistRows(
  rows: Array<{ item: string; status: string; evidence?: string }>
): AiReviewTableRow[] {
  return rows.flatMap((row) => {
    if (!CHECKLIST_STATUSES.has(row.status as AiReviewStatus)) {
      return [];
    }
    return [
      {
        item: row.item,
        status: row.status as AiReviewStatus,
        evidence: row.evidence ?? "",
      },
    ];
  });
}
