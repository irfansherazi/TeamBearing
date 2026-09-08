/**
 * vReview — Memory Watch History Page
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { authenticatedFetch } from "../api_client";
import { MemoryWatchResultsPanel } from "../components/MemoryWatchResultsPanel";
import {
  formatFlowLabel,
  formatMemoryWhen,
  memoryOutcomeLabel,
  memoryRunStatusClass,
  parseMemoryChecklistFromLog,
  type MemoryWatchHistoryDetail,
  type MemoryWatchHistoryItem,
  type MemoryWatchSample,
  type MemoryWatchVerdict,
} from "../lib/memoryWatch";
import type { AiReviewTableRow } from "../lib/aiReviewTable";
import { API_BASE_URL } from "../types";

/**
 * History list for saved Memory Watch runs, with a click-through detail view.
 *
 * @returns The Memory Watch history page
 */
export function MemoryWatchHistoryPage() {
  const [history, setHistory] = useState<MemoryWatchHistoryItem[]>([]);
  const [detail, setDetail] = useState<MemoryWatchHistoryDetail | null>(null);
  const [rows, setRows] = useState<AiReviewTableRow[]>([]);
  const [samples, setSamples] = useState<MemoryWatchSample[]>([]);
  const [verdict, setVerdict] = useState<MemoryWatchVerdict | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const destroyedRef = useRef(false);
  const videoObjectUrlRef = useRef<string | null>(null);

  const revokeVideo = useCallback(() => {
    if (videoObjectUrlRef.current) {
      URL.revokeObjectURL(videoObjectUrlRef.current);
      videoObjectUrlRef.current = null;
    }
  }, []);

  /**
   * Load the history list. No-ops after unmount.
   *
   * @returns void
   */
  const loadHistory = useCallback(() => {
    authenticatedFetch(`${API_BASE_URL}/memory-watch/history`)
      .then(async (response) => {
        if (destroyedRef.current) {
          return [] as MemoryWatchHistoryItem[];
        }
        if (!response.ok) {
          return [] as MemoryWatchHistoryItem[];
        }
        return response.json() as Promise<MemoryWatchHistoryItem[]>;
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
      revokeVideo();
    };
  }, [loadHistory, revokeVideo]);

  /**
   * Open a saved run's heap table and log.
   *
   * @param runId - Dashboard run id
   * @returns void
   */
  const openDetail = (runId: string) => {
    authenticatedFetch(`${API_BASE_URL}/memory-watch/history/${runId}`)
      .then(async (response) => {
        if (destroyedRef.current) {
          return null;
        }
        if (!response.ok) {
          return null;
        }
        return response.json() as Promise<MemoryWatchHistoryDetail>;
      })
      .then((item) => {
        if (destroyedRef.current || item === null) {
          return;
        }
        setDetail(item);
        setSamples(item.samples ?? []);
        setRows(
          item.rows?.length
            ? item.rows
            : parseMemoryChecklistFromLog(item.log_text || "")
        );
        if (item.verdict_pass === null) {
          setVerdict(null);
        } else {
          setVerdict({
            pass: Boolean(item.verdict_pass),
            growthMb: Number(item.growth_mb ?? 0),
            reason: "",
          });
        }
        revokeVideo();
        setVideoUrl(null);
        authenticatedFetch(`${API_BASE_URL}/memory-watch/history/${runId}/video`)
          .then(async (response) => {
            if (destroyedRef.current || !response.ok) {
              return null;
            }
            return response.blob();
          })
          .then((blob) => {
            if (destroyedRef.current || blob === null || blob.size === 0) {
              return;
            }
            const objectUrl = URL.createObjectURL(blob);
            videoObjectUrlRef.current = objectUrl;
            setVideoUrl(objectUrl);
          })
          .catch(() => undefined);
      })
      .catch(() => undefined);
  };

  /**
   * Return to the compact list.
   *
   * @returns void
   */
  const handleBackToList = () => {
    setDetail(null);
    setRows([]);
    setSamples([]);
    setVerdict(null);
    revokeVideo();
    setVideoUrl(null);
  };

  /**
   * Open detail from keyboard on a list row.
   *
   * @param event - Keyboard event
   * @param runId - Dashboard run id
   * @returns void
   */
  const handleRowKey = (event: KeyboardEvent<HTMLTableRowElement>, runId: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDetail(runId);
    }
  };

  if (detail) {
    return (
      <div className="ai-review-history">
        <div className="panel ai-review-history-body">
          <div className="ai-review-history-header">
            <button
              id="mw-hist-back"
              type="button"
              className="btn-secondary"
              onClick={handleBackToList}
            >
              Back
            </button>
            <h2>Memory Watch {detail.run_id}</h2>
          </div>
          <dl className="ai-review-detail-meta">
            <div className="ai-review-detail-field">
              <dt>Flow</dt>
              <dd>{formatFlowLabel(detail.flow)}</dd>
            </div>
            <div className="ai-review-detail-field">
              <dt>Env</dt>
              <dd>{detail.env}</dd>
            </div>
            <div className="ai-review-detail-field">
              <dt>Cycles</dt>
              <dd>{detail.cycles}</dd>
            </div>
          </dl>
        </div>
        <MemoryWatchResultsPanel
          samples={samples}
          rows={rows}
          verdict={verdict}
          logLines={detail.log_text ? detail.log_text.split("\n") : []}
          videoUrl={videoUrl}
          emptyMessage="No heap samples saved."
          emptyLogMessage="No log saved."
        />
      </div>
    );
  }

  return (
    <div className="ai-review-history">
      <div className="panel ai-review-history-body">
        <div className="ai-review-history-header">
          <h2>Memory Watch history</h2>
          <Link id="mw-hist-new" className="btn-secondary" to="/memory">
            New check
          </Link>
        </div>
        {history.length === 0 ? (
          <p>No saved Memory Watch runs yet.</p>
        ) : (
          <table className="ai-review-history-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>When</th>
                <th>Flow</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map((item) => (
                <tr
                  key={item.run_id}
                  className="ai-review-hist-row"
                  role="button"
                  tabIndex={0}
                  aria-label={`Open ${item.run_id}`}
                  onClick={() => openDetail(item.run_id)}
                  onKeyDown={(event) => handleRowKey(event, item.run_id)}
                >
                  <td className="ai-review-hist-id">{item.run_id}</td>
                  <td className="ai-review-hist-when">{formatMemoryWhen(item.started_at)}</td>
                  <td>{formatFlowLabel(item.flow)}</td>
                  <td>
                    <span className={memoryRunStatusClass(item.status)}>
                      {memoryOutcomeLabel(item)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
