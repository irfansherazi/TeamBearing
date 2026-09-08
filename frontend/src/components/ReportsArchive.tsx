/**
 * vQA — Reports Archive Component
 * =================================
 * Full-width browsable view of ALL historical audit runs from S3.
 * Grouped by Jira ticket, with stats per ticket and expandable run list.
 */

import { useCallback, useEffect, useState } from "react";
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

interface TicketGroup {
  ticket_id: string;
  runs: ReportRecord[];
  latestRun: ReportRecord;
  rolesSeen: string[];
}

interface ReportsArchiveProps {
  onRerun?: (ticketId: string, role: string) => void;
}

const ROLE_COLORS: Record<string, string> = {
  account_executive: "#6366f1",
  gm_gsm: "#0ea5e9",
  traffic_manager: "#10b981",
  production_director: "#f59e0b",
  billing: "#ec4899",
  producer: "#8b5cf6",
};

function relativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(isoDate).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function groupByTicket(reports: ReportRecord[]): TicketGroup[] {
  const map = new Map<string, ReportRecord[]>();
  for (const r of reports) {
    if (!map.has(r.ticket_id)) map.set(r.ticket_id, []);
    map.get(r.ticket_id)!.push(r);
  }
  return Array.from(map.entries()).map(([ticket_id, runs]) => ({
    ticket_id,
    runs,
    latestRun: runs[0],
    rolesSeen: Array.from(new Set(runs.map((r) => r.role))),
  }));
}

export function ReportsArchive({ onRerun }: ReportsArchiveProps) {
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [expandedTickets, setExpandedTickets] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"grouped" | "timeline">("grouped");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/reports`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setReports(await r.json());
    } catch {
      setError("Could not load reports from S3");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggleTicket = (ticketId: string) => {
    setExpandedTickets((prev) => {
      const next = new Set(prev);
      next.has(ticketId) ? next.delete(ticketId) : next.add(ticketId);
      return next;
    });
  };

  const allRoles = Array.isArray(reports) ? Array.from(new Set(reports.map((r) => r.role))) : [];

  const filteredReports = Array.isArray(reports) ? reports.filter((r) => {
    const q = search.toLowerCase();
    const matchSearch =
      !q ||
      r.ticket_id.toLowerCase().includes(q) ||
      r.role_label.toLowerCase().includes(q) ||
      r.timestamp_display.includes(q);
    const matchRole = roleFilter === "all" || r.role === roleFilter;
    return matchSearch && matchRole;
  }) : [];

  const groups = groupByTicket(filteredReports);

  return (
    <div className="archive-container">
      {/* ── Archive Header ──────────────────────────────────────── */}
      <div className="archive-header">
        <div className="archive-header-left">
          <h2 className="archive-title">📚 Reports Archive</h2>
          <span className="archive-count">
            {filteredReports.length} runs across {groups.length} tickets
          </span>
        </div>
        <div className="archive-header-right">
          {/* View toggle */}
          <div className="archive-view-toggle">
            <button
              className={`archive-view-btn ${view === "grouped" ? "active" : ""}`}
              onClick={() => setView("grouped")}
              title="Group by ticket"
            >
              ⊞ Grouped
            </button>
            <button
              className={`archive-view-btn ${view === "timeline" ? "active" : ""}`}
              onClick={() => setView("timeline")}
              title="Chronological timeline"
            >
              ≡ Timeline
            </button>
          </div>
          <button
            className="archive-refresh-btn"
            onClick={load}
            disabled={loading}
            title="Reload from S3"
          >
            {loading ? <span className="spinner-xs" /> : "↻ Refresh"}
          </button>
        </div>
      </div>

      {/* ── Filters ─────────────────────────────────────────────── */}
      <div className="archive-filters">
        <div className="archive-search-wrapper">
          <span className="archive-search-icon">🔍</span>
          <input
            type="text"
            placeholder="Search by ticket ID, role, or date…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="form-input archive-search-input"
          />
          {search && (
            <button className="archive-clear-btn" onClick={() => setSearch("")}>✕</button>
          )}
        </div>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="form-select archive-role-filter"
        >
          <option value="all">All Roles</option>
          {allRoles.map((r) => (
            <option key={r} value={r}>
              {Array.isArray(reports) ? reports.find((rep) => rep.role === r)?.role_label ?? r : r}
            </option>
          ))}
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────────────── */}
      {error ? (
        <div className="archive-state archive-error">⚠️ {error}</div>
      ) : loading && (!reports || (Array.isArray(reports) && reports.length === 0)) ? (
        <div className="archive-state">
          <span className="spinner" /> Loading archive…
        </div>
      ) : filteredReports.length === 0 ? (
        <div className="archive-state archive-empty">
          No reports match your filter
        </div>
      ) : view === "grouped" ? (
        <GroupedView
          groups={groups}
          expandedTickets={expandedTickets}
          onToggle={toggleTicket}
          onRerun={onRerun}
        />
      ) : (
        <TimelineView reports={filteredReports} onRerun={onRerun} />
      )}
    </div>
  );
}

// ── Grouped View ────────────────────────────────────────────────────

function GroupedView({
  groups,
  expandedTickets,
  onToggle,
  onRerun,
}: {
  groups: TicketGroup[];
  expandedTickets: Set<string>;
  onToggle: (id: string) => void;
  onRerun?: (ticketId: string, role: string) => void;
}) {
  return (
    <div className="archive-groups">
      {groups.map((group) => (
        <TicketGroupCard
          key={group.ticket_id}
          group={group}
          expanded={expandedTickets.has(group.ticket_id)}
          onToggle={() => onToggle(group.ticket_id)}
          onRerun={onRerun}
        />
      ))}
    </div>
  );
}

function TicketGroupCard({
  group,
  expanded,
  onToggle,
  onRerun,
}: {
  group: TicketGroup;
  expanded: boolean;
  onToggle: () => void;
  onRerun?: (ticketId: string, role: string) => void;
}) {
  return (
    <div className={`archive-ticket-group ${expanded ? "expanded" : ""}`}>
      {/* Group header — click to expand */}
      <button className="archive-group-header" onClick={onToggle}>
        <div className="archive-group-left">
          <a
            href={`https://vcreative.atlassian.net/browse/${group.ticket_id}`}
            target="_blank"
            rel="noreferrer"
            className="archive-ticket-link"
            onClick={(e) => e.stopPropagation()}
          >
            {group.ticket_id}
          </a>
          <div className="archive-group-roles">
            {group.rolesSeen.map((role) => (
              <span
                key={role}
                className="archive-role-dot"
                style={{ background: ROLE_COLORS[role] ?? "#6b778c" }}
                title={group.runs.find((r) => r.role === role)?.role_label}
              />
            ))}
          </div>
        </div>

        <div className="archive-group-meta">
          <span className="archive-group-count">{group.runs.length} run{group.runs.length !== 1 ? "s" : ""}</span>
          <span className="archive-group-latest">Last: {relativeTime(group.latestRun.timestamp)}</span>
          <span className="archive-group-chevron">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>

      {/* Expanded run list */}
      {expanded && (
        <div className="archive-run-list">
          {group.runs.map((run) => (
            <ArchiveRunRow key={run.run_id} run={run} onRerun={onRerun} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Timeline View ───────────────────────────────────────────────────

function TimelineView({
  reports,
  onRerun,
}: {
  reports: ReportRecord[];
  onRerun?: (ticketId: string, role: string) => void;
}) {
  return (
    <div className="archive-timeline">
      {reports.map((run) => (
        <ArchiveRunRow key={run.run_id} run={run} onRerun={onRerun} showTicket />
      ))}
    </div>
  );
}

// ── Shared run row ──────────────────────────────────────────────────

function ArchiveRunRow({
  run,
  onRerun,
  showTicket = false,
}: {
  run: ReportRecord;
  onRerun?: (ticketId: string, role: string) => void;
  showTicket?: boolean;
}) {
  const roleColor = ROLE_COLORS[run.role] ?? "#6b778c";

  return (
    <div className="archive-run-row">
      {showTicket && (
        <a
          href={`https://vcreative.atlassian.net/browse/${run.ticket_id}`}
          target="_blank"
          rel="noreferrer"
          className="archive-run-ticket"
        >
          {run.ticket_id}
        </a>
      )}
      <span
        className="archive-run-role"
        style={{ color: roleColor, borderColor: roleColor }}
      >
        {run.role_label}
      </span>
      <span className="archive-run-ts">{run.timestamp_display}</span>
      <span className="archive-run-rel">{relativeTime(run.timestamp)}</span>

      <div className="archive-run-actions">
        <a
          href={run.report_url}
          target="_blank"
          rel="noreferrer"
          className="report-action-btn report-action-open"
          title="Open HTML audit report"
        >
          📄 Report
        </a>
        <a
          href={run.video_url}
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
            onClick={() => onRerun(run.ticket_id, run.role)}
            title="Re-run with same ticket and role"
          >
            ▶ Re-run
          </button>
        )}
      </div>
    </div>
  );
}
