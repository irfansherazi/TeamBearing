/**
 * Memory Watch log parsers and labels for the dashboard.
 */

import {
  parseReviewTableRow,
  type AiReviewTableRow,
} from "./aiReviewTable";

export type MemoryWatchFlowId =
  | "po-open-spot"
  | "po-search-panel"
  | "ai-intake-open-close"
  | "sidebar-open-close";

export type MemoryWatchEnv = "qa" | "test" | "smoke";

export interface MemoryWatchSample {
  cycle: number;
  label: string;
  usedMb: number;
  deltaMb: number;
  gcRuns: number;
  status: string;
}

export interface MemoryWatchVerdict {
  pass: boolean;
  growthMb: number;
  overCap?: boolean;
  strictlyIncreasing?: boolean;
  reason: string;
}

export interface MemoryWatchHistoryItem {
  run_id: string;
  status: string;
  flow: string;
  env: string;
  cycles: number;
  verdict_pass: boolean | null;
  growth_mb: number | null;
  started_at: string;
  finished_at: string | null;
}

export interface MemoryWatchHistoryDetail extends MemoryWatchHistoryItem {
  samples: MemoryWatchSample[];
  rows: AiReviewTableRow[];
  log_text: string;
  report_dir: string;
  video_file: string;
}

export const FLOW_OPTIONS: { id: MemoryWatchFlowId; label: string }[] = [
  { id: "po-open-spot", label: "Production Orders — open and close spot" },
  { id: "po-search-panel", label: "Production Orders — open and close search" },
  { id: "ai-intake-open-close", label: "AI Intake — open and leave" },
  { id: "sidebar-open-close", label: "Production Orders — open and close sidebar" },
];

const SAMPLE_PREFIX = "MEMORY_WATCH_SAMPLE ";
const VERDICT_PREFIX = "MEMORY_WATCH_VERDICT ";

/**
 * Label for a flow recipe id.
 *
 * @param flowId - Recipe id
 * @returns Display label
 */
export function formatFlowLabel(flowId: string): string {
  const found = FLOW_OPTIONS.find((item) => item.id === flowId);
  return found?.label ?? flowId;
}

/**
 * Parse one MEMORY_WATCH_SAMPLE line.
 *
 * @param line - Raw log line
 * @returns Sample, or null
 */
export function parseMemorySampleLine(line: string): MemoryWatchSample | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith(SAMPLE_PREFIX)) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed.slice(SAMPLE_PREFIX.length)) as MemoryWatchSample;
    if (typeof parsed.cycle !== "number" || typeof parsed.usedMb !== "number") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Parse one MEMORY_WATCH_VERDICT line.
 *
 * @param line - Raw log line
 * @returns Verdict, or null
 */
export function parseMemoryVerdictLine(line: string): MemoryWatchVerdict | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith(VERDICT_PREFIX)) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed.slice(VERDICT_PREFIX.length)) as MemoryWatchVerdict;
    if (typeof parsed.pass !== "boolean") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Merge a sample into the list by cycle number.
 *
 * @param samples - Current samples
 * @param next - Newly parsed sample
 * @returns Updated list
 */
export function upsertMemorySample(
  samples: MemoryWatchSample[],
  next: MemoryWatchSample
): MemoryWatchSample[] {
  const index = samples.findIndex((item) => item.cycle === next.cycle);
  if (index < 0) {
    return [...samples, next].sort((left, right) => left.cycle - right.cycle);
  }
  const updated = [...samples];
  updated[index] = next;
  return updated;
}

/**
 * Parse checklist rows from a saved log.
 *
 * @param logText - Full log
 * @returns Checklist rows
 */
export function parseMemoryChecklistFromLog(logText: string): AiReviewTableRow[] {
  const rows: AiReviewTableRow[] = [];
  for (const line of logText.split(/\r?\n/)) {
    const parsed = parseReviewTableRow(line);
    if (parsed) {
      const index = rows.findIndex((row) => row.item === parsed.item);
      if (index < 0) {
        rows.push(parsed);
      } else {
        rows[index] = parsed;
      }
    }
  }
  return rows;
}

/**
 * Format a history timestamp for the list.
 *
 * @param value - ISO timestamp
 * @returns Locale string, or the raw value
 */
export function formatMemoryWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

/**
 * CSS class for a Memory Watch run status badge.
 *
 * @param status - running / completed / failed / stopped
 * @returns CSS class
 */
export function memoryRunStatusClass(status: string): string {
  switch (status) {
    case "completed":
      return "ai-review-run-status-completed";
    case "failed":
      return "ai-review-run-status-failed";
    case "running":
      return "ai-review-run-status-running";
    case "stopped":
      return "ai-review-run-status-stopped";
    default:
      return "ai-review-run-status-stopped";
  }
}

/**
 * Outcome label from verdict_pass and run status.
 *
 * @param item - History list item
 * @returns PASS / FAIL / RUNNING / STOPPED
 */
export function memoryOutcomeLabel(item: MemoryWatchHistoryItem): string {
  if (item.status === "running") {
    return "RUNNING";
  }
  if (item.status === "stopped") {
    return "STOPPED";
  }
  if (item.verdict_pass === true) {
    return "PASS";
  }
  return "FAIL";
}
