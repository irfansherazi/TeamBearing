import type { RefObject } from "react";
import type { AiReviewStatus, AiReviewTableRow } from "../lib/aiReviewTable";

interface AiReviewResultsPanelProps {
  rows: AiReviewTableRow[];
  logLines: string[];
  logEndRef?: RefObject<HTMLPreElement | null>;
  emptyMessage: string;
  emptyLogMessage: string;
  showLog?: boolean;
}

/**
 * CSS class for a PASS/FAIL/N/A/SKIP cell.
 *
 * @param status - Review row status
 * @returns CSS class name
 */
function reviewStatusClass(status: AiReviewStatus): string {
  switch (status) {
    case "PASS":
      return "ai-review-status-pass";
    case "FAIL":
      return "ai-review-status-fail";
    case "N/A":
      return "ai-review-status-na";
    case "SKIP":
      return "ai-review-status-na";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

/**
 * Results table and log for a live or saved AI Review run.
 *
 * @param props - Rows, log lines, empty-state copy, and optional log visibility
 * @returns Results panel
 */
export function AiReviewResultsPanel({
  rows,
  logLines,
  logEndRef,
  emptyMessage,
  emptyLogMessage,
  showLog = true,
}: AiReviewResultsPanelProps) {
  return (
    <div className="app-card ai-review-results">
      <div className="app-card-intro panel-header">
        <h2 className="app-card-title">Results</h2>
      </div>
      <div className="ai-review-results-body">
        <table className="step-table ai-review-results-table">
          <thead>
            <tr>
              <th className="ai-review-col-item">Item</th>
              <th className="ai-review-col-status">Status</th>
              <th className="ai-review-col-evidence">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={3}>{emptyMessage}</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.item} id={`ai-review-row-${row.item}`}>
                  <td className="ai-review-col-item">{row.item}</td>
                  <td className="ai-review-col-status">
                    <span className={reviewStatusClass(row.status)}>{row.status}</span>
                  </td>
                  <td className="ai-review-col-evidence">{row.evidence}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {showLog ? (
          <pre
            ref={logEndRef}
            className="ai-review-log"
            aria-label="Review log"
          >
            {logLines.length > 0 ? logLines.join("\n") : emptyLogMessage}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
