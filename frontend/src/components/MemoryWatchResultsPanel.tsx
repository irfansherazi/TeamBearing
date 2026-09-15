import type { RefObject } from "react";
import type { AiReviewTableRow } from "../lib/aiReviewTable";
import type {
  MemoryWatchFailureSummary,
  MemoryWatchSample,
  MemoryWatchVerdict,
} from "../lib/memoryWatch";

interface MemoryWatchResultsPanelProps {
  samples: MemoryWatchSample[];
  rows: AiReviewTableRow[];
  verdict: MemoryWatchVerdict | null;
  logLines: string[];
  logEndRef?: RefObject<HTMLPreElement | null>;
  videoUrl?: string | null;
  emptyMessage: string;
  emptyLogMessage: string;
  showLog?: boolean;
  /** Best-effort phase/reason parsed from the log when the run died with no structured results. */
  failureSummary?: MemoryWatchFailureSummary | null;
  /** Collapse the raw log behind a disclosure — for saved/finished runs, not a live stream. */
  collapsibleLog?: boolean;
}

/**
 * Heap table, checklist, optional video, and live log for Memory Watch.
 *
 * @param props - Samples, rows, log, and optional video URL
 * @returns Results panel
 */
export function MemoryWatchResultsPanel({
  samples,
  rows,
  verdict,
  logLines,
  logEndRef,
  videoUrl,
  emptyMessage,
  emptyLogMessage,
  showLog = true,
  failureSummary,
  collapsibleLog = false,
}: MemoryWatchResultsPanelProps) {
  const hasStructuredResults = samples.length > 0 || rows.length > 0 || verdict !== null;
  const logContent = (
    <pre ref={logEndRef} className="ai-review-log" aria-label="Memory Watch log">
      {logLines.length > 0 ? logLines.join("\n") : emptyLogMessage}
    </pre>
  );

  return (
    <div className="panel ai-review-results">
      <div className="panel-header">
        <h2>Results</h2>
        {verdict ? (
          <span className={verdict.pass ? "ai-review-status-pass" : "ai-review-status-fail"}>
            {verdict.pass ? "PASS" : "FAIL"}
          </span>
        ) : null}
      </div>
      <div className="ai-review-results-body">
        {verdict?.reason ? <p className="memory-watch-verdict">{verdict.reason}</p> : null}
        {failureSummary ? (
          <div className="memory-watch-failure-card" id="mw-failure-summary">
            <p className="memory-watch-failure-phase">Failed at: {failureSummary.phase}</p>
            <p className="memory-watch-failure-reason">{failureSummary.reason}</p>
          </div>
        ) : null}
        <table className="step-table">
          <thead>
            <tr>
              <th>Cycle</th>
              <th>Step</th>
              <th>Used heap (MB)</th>
              <th>Δ from start</th>
              <th>GC</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {samples.length === 0 ? (
              <tr>
                <td colSpan={6}>{emptyMessage}</td>
              </tr>
            ) : (
              samples.map((sample) => (
                <tr key={`mw-cycle-${sample.cycle}`} id={`mw-cycle-${sample.cycle}`}>
                  <td>{sample.cycle === 0 ? "0 (start)" : String(sample.cycle)}</td>
                  <td>{sample.label || "—"}</td>
                  <td>{sample.usedMb.toFixed(2)}</td>
                  <td>
                    {sample.cycle === 0
                      ? "—"
                      : `${sample.deltaMb >= 0 ? "+" : ""}${sample.deltaMb.toFixed(2)}`}
                  </td>
                  <td>{sample.gcRuns}</td>
                  <td>{sample.status}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {rows.length > 0 ? (
          <table className="step-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Status</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.item} id={`mw-row-${row.item}`}>
                  <td>{row.item}</td>
                  <td>{row.status}</td>
                  <td>{row.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {videoUrl ? (
          <video
            id="mw-recording"
            className="memory-watch-video"
            controls
            src={videoUrl}
          />
        ) : null}
        {showLog ? (
          collapsibleLog ? (
            <details className="memory-watch-log-details" open={!hasStructuredResults && !failureSummary}>
              <summary>Raw log</summary>
              {logContent}
            </details>
          ) : (
            logContent
          )
        ) : null}
      </div>
    </div>
  );
}
