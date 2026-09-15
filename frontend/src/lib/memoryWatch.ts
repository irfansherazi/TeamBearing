/**
 * Memory Watch log parsers and labels for the dashboard.
 */

import {
  parseReviewTableRow,
  type AiReviewTableRow,
} from "./aiReviewTable";

export type MemoryWatchFlowId =
  | "qo-open-close-snapshot"
  | "po-open-spot"
  | "po-search-panel"
  | "ai-intake-open-close"
  | "sidebar-open-close";

export type MemoryWatchEnv = "local" | "qa" | "test" | "smoke";

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
  { id: "qo-open-close-snapshot", label: "Production Orders — Quick Order open/close snapshots" },
  { id: "po-open-spot", label: "Production Orders — open and close spot" },
  { id: "po-search-panel", label: "Production Orders — open and close search" },
  { id: "ai-intake-open-close", label: "AI Intake — open and leave" },
  { id: "sidebar-open-close", label: "Production Orders — open and close sidebar" },
];

export const ENV_OPTIONS: { id: MemoryWatchEnv; label: string }[] = [
  { id: "local", label: "local (localhost:4200)" },
  { id: "qa", label: "qa" },
  { id: "test", label: "test" },
  { id: "smoke", label: "smoke" },
];

const FLOW_PREVIEW_STEPS: Record<MemoryWatchFlowId, string[]> = {
  "qo-open-close-snapshot": [
    "Start screen recording",
    "Ghost in as Demo Prod Dir",
    "Open a 1-spot Quick Order",
    "Close the order without making changes",
    "Clear the console",
    "Force garbage collection",
    "Take a snapshot",
    "Open a 5-spot or larger Quick Order",
    "Close without changes, clear console, GC, snapshot",
    "Ghost in as Suzan Goritz (wide-orbit clients)",
    "Repeat the 1-spot and 5-spot snapshot steps",
  ],
  "po-open-spot": [
    "Open Production Orders",
    "Open the first spot",
    "Return to the list",
    "Force GC and take a snapshot",
    "Repeat for the cycle count",
  ],
  "po-search-panel": [
    "Open Production Orders",
    "Open the search panel",
    "Close the search panel",
    "Force GC and take a snapshot",
    "Repeat for the cycle count",
  ],
  "ai-intake-open-close": [
    "Open AI Intake",
    "Leave back to Production Orders",
    "Force GC and take a snapshot",
    "Repeat for the cycle count",
  ],
  "sidebar-open-close": [
    "Open Production Orders",
    "Open the Quick Order sidebar",
    "Close without saving",
    "Force GC and take a snapshot",
    "Repeat for the cycle count",
  ],
};

/**
 * True when value is a Memory Watch flow id.
 *
 * @param value - Raw select value
 * @returns Whether the id is known
 */
export function isMemoryWatchFlowId(value: string): value is MemoryWatchFlowId {
  return FLOW_OPTIONS.some((option) => option.id === value);
}

/**
 * True when value is a Memory Watch env id.
 *
 * @param value - Raw select value
 * @returns Whether the env is known
 */
export function isMemoryWatchEnv(value: string): value is MemoryWatchEnv {
  return ENV_OPTIONS.some((option) => option.id === value);
}

/**
 * True when the flow is the fixed Quick Order snapshot ritual (no cycle repeats).
 *
 * @param flowId - Recipe id
 * @returns Whether cycles should be hidden
 */
export function isFixedRitualFlow(flowId: string): boolean {
  return flowId === "qo-open-close-snapshot";
}

/**
 * Steps shown on the dashboard before a run.
 *
 * @param flowId - Recipe id
 * @returns Ordered step labels
 */
export function getFlowPreviewSteps(flowId: string): string[] {
  switch (flowId) {
    case "qo-open-close-snapshot":
    case "po-open-spot":
    case "po-search-panel":
    case "ai-intake-open-close":
    case "sidebar-open-close":
      return FLOW_PREVIEW_STEPS[flowId];
    default:
      return [];
  }
}

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

export interface MemoryWatchFailureSummary {
  phase: string;
  reason: string;
}

/**
 * Phase detectors, checked in order. First match wins.
 * Ordered from most specific failure signal (where the code actually threw,
 * per stack trace / hard error text) to weakest (a background warning that
 * doesn't by itself fail the run) — a warning like a missing storage dir is
 * printed on nearly every run and must not outrank the real failure site.
 */
const FAILURE_PHASE_PATTERNS: { phase: string; pattern: RegExp }[] = [
  { phase: "Login / session", pattern: /at login \(|loginHelper\.mjs|Session expired or not logged in|Falling back to manual login/i },
  { phase: "Ghost login", pattern: /ghost picker|ghostLogin|Could not ghost as/i },
  { phase: "Quick Order flow steps", pattern: /Quick Order details did not open|No 1-spot Quick Order|No 5-spot or larger Quick Order|openMatchingQuickOrder/i },
  { phase: "Flow steps", pattern: /FLOW error|runFlowCycle/i },
  { phase: "Heap capture", pattern: /HeapProfiler|captureMetrics/i },
  { phase: "Page load / connection", pattern: /exceeded while setting up "page"|net::ERR_CONNECTION|ERR_CONNECTION_REFUSED/i },
  { phase: "Test environment setup", pattern: /STORAGE_DIR does not exist|No available users detected/i },
];

/** First line matching this is taken as the human-readable failure reason. */
const FAILURE_REASON_MARKER = /^(Error:|Cannot\s|TypeError:|ReferenceError:|SyntaxError:)/;

/**
 * Best-effort human summary of why a saved run has no samples/rows: which
 * phase it likely died in, and a short reason pulled from the raw log.
 * Returns null when the log doesn't look like a failure at all.
 *
 * @param logText - Full saved log for the run
 * @returns Phase + reason, or null
 */
export function summarizeMemoryWatchFailure(logText: string): MemoryWatchFailureSummary | null {
  const trimmed = (logText || "").trim();
  if (!trimmed) {
    return null;
  }

  let phase = "Unknown";
  for (const { phase: candidate, pattern } of FAILURE_PHASE_PATTERNS) {
    if (pattern.test(trimmed)) {
      phase = candidate;
      break;
    }
  }

  const lines = trimmed.split(/\r?\n/);
  let reason = "";
  for (let i = 0; i < lines.length; i++) {
    const candidateLine = lines[i].trim();
    if (!FAILURE_REASON_MARKER.test(candidateLine)) {
      continue;
    }
    reason = candidateLine.replace(/^Error:\s*/, "").trim();
    if (!reason) {
      const next = lines.slice(i + 1).find((candidate) => candidate.trim().length > 0);
      reason = next ? next.trim() : "";
    }
    if (reason) {
      break;
    }
  }

  if (!reason && phase === "Unknown") {
    return null;
  }

  if (reason.length > 220) {
    reason = `${reason.slice(0, 217)}...`;
  }

  return {
    phase,
    reason: reason || "No further detail was captured before the run stopped.",
  };
}
