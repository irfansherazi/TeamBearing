/**
 * vQA — Reports History Panel
 * ============================
 * Displays past audit runs from S3, with search/filter and actions to
 * open the HTML report, watch the session video, or re-run the ticket.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../types";
import { authenticatedFetch } from "../api_client";

interface ReportRecord {
  run_id: string;
  ticket_id: string;
  role: string;
  role_label: string;
  timestamp: string;
  timestamp_display: string;
  label: string;
  report_url: string;
  video_url: string;
}

interface ReportsHistoryProps {
  onRerun?: (ticketId: string, role: string) => void;
  /** Trigger a refresh (increment to reload) */
  refreshTick?: number;
}

const ROLE_COLORS: Record<string, string> = {
  account_executive: "#6366f1",
  gm_gsm: "#0ea5e9",
  traffic_manager: "#10b981",
  production_director: "#f59e0b",
  billing: "#ec4899",
  producer: "#8b5cf6",
};

export function ReportsHistory({ onRerun, refreshTick = 0 }: ReportsHistoryProps) {
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const lastTick = useRef(refreshTick);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/reports`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: ReportRecord[] = await r.json();
      setReports(data);
    } catch (e) {
      setError("Could not load reports from S3");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh when a new run completes
  useEffect(() => {
    if (refreshTick !== lastTick.current) {
      lastTick.current = refreshTick;
      // Brief delay to let S3 propagate
      setTimeout(load, 3000);
    }
  }, [refreshTick, load]);

  // Unique roles for filter
  const allRoles = Array.isArray(reports) ? Array.from(new Set(reports.map((r) => r.role))) : [];

  const filtered = Array.isArray(reports) ? reports.filter((r) => {
    const q = search.toLowerCase();
    const matchesSearch =
      !q ||
      r.ticket_id.toLowerCase().includes(q) ||
      r.role_label.toLowerCase().includes(q) ||
      r.timestamp_display.includes(q);
    const matchesRole = roleFilter === "all" || r.role === roleFilter;
    return matchesSearch && matchesRole;
  }) : [];

  return (
    <div className="panel reports-history-panel">
      <div className="panel-header">
        <h2>📋 Previous Reports</h2>
        <div className="reports-header-actions">
          <span className="panel-badge">{Array.isArray(reports) ? reports.length : 0} runs</span>
          <button
            className="reports-refresh-btn"
            onClick={load}
            disabled={loading}
            title="Refresh from S3"
          >
            {loading ? <span className="spinner-xs" /> : "↻"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="reports-filters">
        <div className="reports-search-wrapper">
          <span className="reports-search-icon">🔍</span>
          <input
            type="text"
            placeholder="Search by ticket or role…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="form-input reports-search-input"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="form-select reports-role-filter"
        >
          <option value="all">All Roles</option>
          {allRoles.map((r) => (
            <option key={r} value={r}>
              {Array.isArray(reports) ? reports.find((rep) => rep.role === r)?.role_label ?? r : r}
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      <div className="reports-content">
        {error ? (
          <div className="reports-empty reports-error">{error}</div>
        ) : loading && (!reports || (Array.isArray(reports) && reports.length === 0)) ? (
          <div className="reports-empty">
            <span className="spinner" /> Loading reports…
          </div>
        ) : filtered.length === 0 ? (
          <div className="reports-empty">
            {search || roleFilter !== "all" ? "No reports match your filter" : "No previous reports found"}
          </div>
        ) : (
          <ul className="reports-list">
            {filtered.map((report) => (
              <ReportRow
                key={report.run_id}
                report={report}
                onRerun={onRerun}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ReportRow({
  report,
  onRerun,
}: {
  report: ReportRecord;
  onRerun?: (ticketId: string, role: string) => void;
}) {
  const roleColor = ROLE_COLORS[report.role] ?? "#6b778c";

  return (
    <li className="report-row">
      <div className="report-row-main">
        {/* Ticket badge */}
        <a
          className="report-ticket-badge"
          href={`https://vcreative.atlassian.net/browse/${report.ticket_id}`}
          target="_blank"
          rel="noreferrer"
          title={`Open ${report.ticket_id} in Jira`}
        >
          {report.ticket_id}
        </a>

        {/* Role tag */}
        <span
          className="report-role-tag"
          style={{ borderColor: roleColor, color: roleColor }}
        >
          {report.role_label}
        </span>

        {/* Timestamp */}
        <span className="report-timestamp">{report.timestamp_display}</span>

        {/* Actions */}
        <div className="report-actions">
          <a
            href={report.report_url}
            target="_blank"
            rel="noreferrer"
            className="report-action-btn report-action-open"
            title="Open HTML audit report"
          >
            📄 Report
          </a>
          <a
            href={report.video_url}
            target="_blank"
            rel="noreferrer"
            className="report-action-btn report-action-video"
            title="Watch session recording"
          >
            🎬 Video
          </a>
          {onRerun && (
            <button
              className="report-action-btn report-action-rerun"
              onClick={() => onRerun(report.ticket_id, report.role)}
              title="Re-run this ticket with same role"
            >
              ▶ Re-run
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
