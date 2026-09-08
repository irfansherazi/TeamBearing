/**
 * vQA — Analytics Dashboard Component (Phase 6A)
 * ================================================
 * Module: frontend/src/components/AnalyticsDashboard.tsx
 *
 * Consumes the Phase 5C endpoints:
 *   GET /runs/analytics  — aggregated stats
 *   GET /runs/history    — paginated run list
 *
 * Renders:
 *   1. Summary stat cards (pass rate, total runs, avg cost, avg duration)
 *   2. SVG bar chart showing daily pass/fail trend
 *   3. Top tickets table
 *   4. Recent runs list
 */

import { useCallback, useEffect, useState } from 'react';
import { API_BASE_URL } from '../types';
import { authenticatedFetch } from "../api_client";

import "./AnalyticsDashboard.css";


// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Analytics {
  period_days: number;
  total_runs: number;
  passed: number;
  failed: number;
  pass_rate: number;
  total_cost_usd: number;
  avg_cost_usd: number;
  avg_duration_ms: number;
  total_ac_steps: number;
  total_ac_passed: number;
  top_tickets: { ticket_id: string; runs: number; passes: number }[];
}

interface RunItem {
  run_id: string;
  ticket_id: string;
  role: string;
  status: string;
  duration_ms: number;
  ac_total: number;
  ac_passed: number;
  cost_usd: number;
  report_url: string;
  video_url: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60000);
  const secs = Math.round((ms % 60000) / 1000);
  return `${mins}m ${secs}s`;
}

function formatCost(usd: number): string {
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function timeAgo(isoStr: string): string {
  const date = new Date(isoStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Sparkline Bar Chart (pure SVG)
// ---------------------------------------------------------------------------

interface SparkBarProps {
  passed: number;
  failed: number;
  total: number;
}

function PassRateRing({ passed, failed: _failed, total }: SparkBarProps) {
  const passRate = total > 0 ? (passed / total) * 100 : 0;
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const passArc = (passRate / 100) * circumference;

  return (
    <svg viewBox="0 0 120 120" className="analytics-ring">
      {/* Background track */}
      <circle
        cx="60" cy="60" r={radius}
        fill="none"
        stroke="var(--ring-bg, rgba(255,255,255,0.06))"
        strokeWidth="10"
      />
      {/* Pass arc */}
      <circle
        cx="60" cy="60" r={radius}
        fill="none"
        stroke={passRate >= 80 ? "var(--color-pass)" : passRate >= 50 ? "var(--color-warn)" : "var(--color-fail)"}
        strokeWidth="10"
        strokeDasharray={`${passArc} ${circumference - passArc}`}
        strokeDashoffset={circumference * 0.25}
        strokeLinecap="round"
        style={{ transition: "stroke-dasharray 0.8s ease" }}
      />
      {/* Center text */}
      <text x="60" y="56" textAnchor="middle" className="ring-pct">
        {passRate.toFixed(0)}%
      </text>
      <text x="60" y="72" textAnchor="middle" className="ring-label">
        pass rate
      </text>
    </svg>
  );
}


// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AnalyticsDashboard() {
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodDays, setPeriodDays] = useState(30);

  const fetchData = useCallback(async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const [analyticsRes, runsRes] = await Promise.all([
        authenticatedFetch(`${API_BASE_URL}/runs/analytics?days=${days}`),
        authenticatedFetch(`${API_BASE_URL}/runs/history?limit=20`),
      ]);
      if (!analyticsRes.ok || !runsRes.ok) throw new Error("Failed to fetch analytics");
      const analyticsData: Analytics = await analyticsRes.json();
      const runsData = await runsRes.json();
      setAnalytics(analyticsData);
      setRuns(runsData.runs ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(periodDays);
  }, [fetchData, periodDays]);

  if (loading && !analytics) {
    return (
      <div className="analytics-loading">
        <div className="analytics-spinner" />
        <p>Loading analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="analytics-error">
        <span className="analytics-error-icon">⚠️</span>
        <p>{error}</p>
        <button onClick={() => fetchData(periodDays)} className="analytics-retry-btn">
          Retry
        </button>
      </div>
    );
  }

  if (!analytics) return null;

  const acPassRate = analytics.total_ac_steps > 0
    ? ((analytics.total_ac_passed / analytics.total_ac_steps) * 100).toFixed(1)
    : "0";

  return (
    <div className="analytics-dashboard">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="analytics-header">
        <div className="analytics-header-left">
          <h2>📊 Analytics</h2>
          <span className="analytics-subtitle">
            Last {analytics.period_days} days
          </span>
        </div>
        <div className="analytics-header-right">
          <div className="period-selector">
            {[7, 14, 30, 90].map((d) => (
              <button
                key={d}
                className={`period-btn ${periodDays === d ? "active" : ""}`}
                onClick={() => setPeriodDays(d)}
              >
                {d}d
              </button>
            ))}
          </div>
          <button
            className="analytics-refresh-btn"
            onClick={() => fetchData(periodDays)}
            title="Refresh"
          >
            🔄
          </button>
        </div>
      </div>

      {/* ── Stat Cards ──────────────────────────────────────────── */}
      <div className="analytics-cards">
        <div className="stat-card stat-card--primary">
          <div className="stat-card__ring">
            <PassRateRing
              passed={analytics.passed}
              failed={analytics.failed}
              total={analytics.total_runs}
            />
          </div>
          <div className="stat-card__details">
            <span className="stat-card__value">{analytics.passed}/{analytics.total_runs}</span>
            <span className="stat-card__label">Runs Passed</span>
          </div>
        </div>

        <div className="stat-card">
          <span className="stat-card__icon">🧪</span>
          <span className="stat-card__value">{analytics.total_runs}</span>
          <span className="stat-card__label">Total Runs</span>
        </div>

        <div className="stat-card">
          <span className="stat-card__icon">💰</span>
          <span className="stat-card__value">{formatCost(analytics.total_cost_usd)}</span>
          <span className="stat-card__label">Total Cost</span>
          <span className="stat-card__sub">avg {formatCost(analytics.avg_cost_usd)}/run</span>
        </div>

        <div className="stat-card">
          <span className="stat-card__icon">⏱️</span>
          <span className="stat-card__value">{formatDuration(analytics.avg_duration_ms)}</span>
          <span className="stat-card__label">Avg Duration</span>
        </div>

        <div className="stat-card">
          <span className="stat-card__icon">✅</span>
          <span className="stat-card__value">{acPassRate}%</span>
          <span className="stat-card__label">AC Step Pass Rate</span>
          <span className="stat-card__sub">{analytics.total_ac_passed}/{analytics.total_ac_steps} steps</span>
        </div>
      </div>

      {/* ── Two Column Layout ───────────────────────────────────── */}
      <div className="analytics-grid">
        {/* ── Top Tickets ─────────────────────────────────────── */}
        <div className="analytics-section">
          <h3>🎯 Most Tested Tickets</h3>
          {!Array.isArray(analytics?.top_tickets) || analytics.top_tickets.length === 0 ? (
            <p className="analytics-empty">No ticket data yet</p>
          ) : (
            <table className="analytics-table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Runs</th>
                  <th>Passed</th>
                  <th>Rate</th>
                </tr>
              </thead>
              <tbody>
                {analytics.top_tickets.map((t) => {
                  const rate = t.runs > 0 ? ((t.passes / t.runs) * 100).toFixed(0) : "0";
                  return (
                    <tr key={t.ticket_id}>
                      <td className="ticket-cell">{t.ticket_id}</td>
                      <td>{t.runs}</td>
                      <td>{t.passes}</td>
                      <td>
                        <span className={`rate-badge ${Number(rate) >= 80 ? "pass" : Number(rate) >= 50 ? "warn" : "fail"}`}>
                          {rate}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Recent Runs ─────────────────────────────────────── */}
        <div className="analytics-section">
          <h3>🕐 Recent Runs</h3>
          {!Array.isArray(runs) || runs.length === 0 ? (
            <p className="analytics-empty">No runs recorded yet</p>
          ) : (
            <div className="recent-runs-list">
              {runs.map((run) => (
                <div key={run.run_id} className={`run-row run-row--${run.status}`}>
                  <span className={`run-status-dot run-status-dot--${run.status}`} />
                  <div className="run-row__info">
                    <span className="run-row__ticket">{run.ticket_id}</span>
                    <span className="run-row__role">{run.role}</span>
                  </div>
                  <div className="run-row__stats">
                    <span className="run-row__ac">
                      {run.ac_passed}/{run.ac_total} AC
                    </span>
                    <span className="run-row__duration">{formatDuration(run.duration_ms)}</span>
                    <span className="run-row__cost">{formatCost(run.cost_usd)}</span>
                  </div>
                  <div className="run-row__actions">
                    {run.report_url && (
                      <a href={run.report_url} target="_blank" rel="noopener noreferrer" className="run-link" title="View Report">
                        📄
                      </a>
                    )}
                    {run.video_url && (
                      <a href={run.video_url} target="_blank" rel="noopener noreferrer" className="run-link" title="Watch Recording">
                        🎬
                      </a>
                    )}
                  </div>
                  <span className="run-row__time">{timeAgo(run.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
