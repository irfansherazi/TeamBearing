/**
 * vReview — AI Review History Page
 * ================================
 * Module: frontend/src/pages/AiReviewHistoryPage.tsx
 *
 * Compact list of saved reviews. Click a row to open details + checklist.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { authenticatedFetch } from "../api_client";
import { AiReviewResultsPanel } from "../components/AiReviewResultsPanel";
import {
  appBadgeClass,
  formatAppLabel,
  formatReviewCommand,
  formatReviewCounts,
  formatReviewWhen,
  historyOutcomeClass,
  historyOutcomeLabel,
  parseChangedFiles,
  toChecklistRows,
  toHistoryOutcome,
  type AiReviewHistoryDetail,
  type AiReviewHistoryItem,
} from "../lib/aiReviewHistory";
import type { AiReviewTableRow } from "../lib/aiReviewTable";
import { API_BASE_URL } from "../types";

/**
 * History list for saved AI Review runs, with a click-through detail view.
 *
 * @returns The History page
 */
export function AiReviewHistoryPage() {
  const [history, setHistory] = useState<AiReviewHistoryItem[]>([]);
  const [detail, setDetail] = useState<AiReviewHistoryDetail | null>(null);
  const [rows, setRows] = useState<AiReviewTableRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const destroyedRef = useRef(false);

  /**
   * Load the history list. No-ops after unmount.
   *
   * @returns void
   */
  const loadHistory = useCallback(() => {
    authenticatedFetch(`${API_BASE_URL}/ai-review/history`)
      .then(async (response) => {
        if (destroyedRef.current) {
          return [] as AiReviewHistoryItem[];
        }
        if (!response.ok) {
          return [] as AiReviewHistoryItem[];
        }
        return response.json() as Promise<AiReviewHistoryItem[]>;
      })
      .then((items) => {
        if (destroyedRef.current) {
          return;
        }
        setHistory(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (destroyedRef.current) {
          return;
        }
        setHistory([]);
      });
  }, []);

  useEffect(() => {
    destroyedRef.current = false;
    loadHistory();
    return () => {
      destroyedRef.current = true;
    };
  }, [loadHistory]);

  /**
   * Open a saved review's detail + checklist.
   *
   * @param reviewId - History row id
   * @returns void
   */
  const handleOpenHistory = (reviewId: string) => {
    setLoadError(null);
    authenticatedFetch(`${API_BASE_URL}/ai-review/history/${reviewId}`)
      .then(async (response) => {
        if (destroyedRef.current) {
          return null;
        }
        if (!response.ok) {
          throw new Error("Could not load that review");
        }
        return response.json() as Promise<AiReviewHistoryDetail>;
      })
      .then((nextDetail) => {
        if (destroyedRef.current || nextDetail === null) {
          return;
        }
        setDetail(nextDetail);
        setRows(toChecklistRows(nextDetail.rows ?? []));
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (destroyedRef.current) {
          return;
        }
        setLoadError(err instanceof Error ? err.message : "Could not load that review");
      });
  };

  /**
   * Return from the detail view to the compact list.
   *
   * @returns void
   */
  const handleBackToList = () => {
    setDetail(null);
    setRows([]);
    setLoadError(null);
  };

  /**
   * Open a history row from keyboard when the row is focused.
   *
   * @param event - Keyboard event on a history row
   * @param reviewId - History row id
   * @returns void
   */
  const handleHistoryKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, reviewId: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleOpenHistory(reviewId);
    }
  };

  if (detail) {
    const outcome = toHistoryOutcome(detail);
    const files = parseChangedFiles(detail.log_text ?? "");
    return (
      <div className="ai-review-page">
        <div className="panel ai-review-history">
          <div className="panel-header">
            <div className="ai-review-history-header">
              <button
                id="ai-review-history-back"
                type="button"
                className="btn-back"
                onClick={handleBackToList}
              >
                Back
              </button>
              <h2>Review {detail.review_id}</h2>
            </div>
            <span className={historyOutcomeClass(outcome)}>{historyOutcomeLabel(outcome)}</span>
          </div>
          <div className="ai-review-detail-body">
            {loadError ? (
              <p className="ai-review-error" id="ai-review-history-error">
                {loadError}
              </p>
            ) : null}
            <dl className="ai-review-detail-meta">
              <div className="ai-review-detail-field ai-review-detail-field--wide">
                <dt>Command</dt>
                <dd id="ai-review-detail-command">{formatReviewCommand(detail)}</dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>App</dt>
                <dd>
                  <span className={appBadgeClass(detail.app)}>{formatAppLabel(detail.app)}</span>
                </dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>When</dt>
                <dd>{formatReviewWhen(detail.started_at)}</dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>Branch</dt>
                <dd className="ai-review-detail-mono">{detail.branch}</dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>Base</dt>
                <dd className="ai-review-detail-mono">{detail.base}</dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>Commits</dt>
                <dd className="ai-review-detail-mono">{detail.commits ? detail.commits : "—"}</dd>
              </div>
              <div className="ai-review-detail-field">
                <dt>Result</dt>
                <dd>{formatReviewCounts(detail)}</dd>
              </div>
              <div className="ai-review-detail-field ai-review-detail-field--wide">
                <dt>Files reviewed</dt>
                <dd>
                  {files.length === 0 ? (
                    "No files listed in the saved log."
                  ) : (
                    <ul className="ai-review-file-list">
                      {files.map((file) => (
                        <li key={file}>{file}</li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>
            </dl>
          </div>
        </div>

        <AiReviewResultsPanel
          rows={rows}
          logLines={[]}
          emptyMessage="No checklist rows were saved for this review."
          emptyLogMessage=""
          showLog={false}
        />
      </div>
    );
  }

  return (
    <div className="ai-review-page">
      <div className="panel ai-review-history">
        <div className="panel-header">
          <h2>History</h2>
        </div>
        <div className="ai-review-history-body">
          {loadError ? (
            <p className="ai-review-error" id="ai-review-history-error">
              {loadError}
            </p>
          ) : null}
          <table className="step-table ai-review-history-table">
            <thead>
              <tr>
                <th>Review ID</th>
                <th>When</th>
                <th>App</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr>
                  <td colSpan={4}>No saved reviews yet.</td>
                </tr>
              ) : (
                history.map((item) => {
                  const outcome = toHistoryOutcome(item);
                  return (
                    <tr
                      key={item.review_id}
                      id={`ai-review-hist-${item.review_id}`}
                      className="ai-review-hist-row"
                      role="button"
                      aria-label={`Open review ${item.review_id}`}
                      tabIndex={0}
                      onClick={() => handleOpenHistory(item.review_id)}
                      onKeyDown={(event) => handleHistoryKeyDown(event, item.review_id)}
                    >
                      <td className="ai-review-hist-id">{item.review_id}</td>
                      <td className="ai-review-hist-when">{formatReviewWhen(item.started_at)}</td>
                      <td>
                        <span className={appBadgeClass(item.app)}>{formatAppLabel(item.app)}</span>
                      </td>
                      <td>
                        <span className={historyOutcomeClass(outcome)}>
                          {historyOutcomeLabel(outcome)}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
