/**
 * vReview — AppNav Component
 * ==========================
 * Module: frontend/src/components/AppNav.tsx
 *
 * Left navigation rail with:
 * - Brand logo + name
 * - AI Review group: Run review, History, Review rules
 * - Memory Watch
 * - Health status dot in footer
 * - Logout button in footer
 *
 * Responsive behavior:
 * - > 1024px: 248px wide, icon + label
 * - 768px–1024px: 64px icon-only (labels hidden via CSS)
 * - < 768px: bottom tab bar (via CSS grid on AppShell)
 *
 * Design tokens sourced from index.css.
 */

import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { useExecution } from "../hooks/useExecution";
import { useEffect } from "react";

type NavIconName = "run" | "history" | "rules" | "memory";

interface NavItemProps {
  to: string;
  icon: NavIconName;
  label: string;
  title: string;
  id: string;
}

/**
 * Line icon used in the left rail.
 *
 * @param props - Which glyph to draw
 * @returns An SVG icon
 */
function NavIcon({ name }: { name: NavIconName }): ReactNode {
  const common = {
    className: "app-nav-glyph",
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "run":
      return (
        <svg {...common}>
          <polygon points="8 5 19 12 8 19 8 5" />
        </svg>
      );
    case "history":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8.5" />
          <polyline points="12 8 12 12 15.5 14" />
        </svg>
      );
    case "rules":
      return (
        <svg {...common}>
          <rect x="5" y="3.5" width="14" height="17" rx="2" />
          <line x1="8.5" y1="8" x2="15.5" y2="8" />
          <line x1="8.5" y1="12" x2="15.5" y2="12" />
          <line x1="8.5" y1="16" x2="13" y2="16" />
        </svg>
      );
    case "memory":
      return (
        <svg {...common}>
          <path d="M2.8 12s3.6-6.5 9.2-6.5S21.2 12 21.2 12 17.6 18.5 12 18.5 2.8 12 2.8 12z" />
          <circle cx="12" cy="12" r="2.6" />
        </svg>
      );
    default: {
      const exhaustive: never = name;
      return exhaustive;
    }
  }
}

function AppNavLink({ to, icon, label, title, id }: NavItemProps) {
  return (
    <li>
      <NavLink
        id={id}
        to={to}
        end={to === "/"}
        title={title}
        className={({ isActive }) =>
          `app-nav-link${isActive ? " active" : ""}`
        }
      >
        <span className="app-nav-icon" aria-hidden="true">
          <NavIcon name={icon} />
        </span>
        <span className="app-nav-link-label">{label}</span>
      </NavLink>
    </li>
  );
}

/**
 * AppNav — Left navigation rail component.
 *
 * Renders inside <AppShell> as the persistent sidebar.
 * Uses react-router-dom NavLink for active state management.
 */
export function AppNav() {
  const { logout } = useAuth();
  const { healthResponse, checkHealth } = useExecution();

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const healthStatus = healthResponse
    ? (healthResponse.status === "ok" ? "ok" : "error")
    : "warning";

  const healthLabel = healthResponse
    ? (healthResponse.status === "ok" ? "All Systems Go" : "Degraded")
    : "Connecting…";

  return (
    <nav className="app-nav" aria-label="Main navigation">
      <div className="app-nav-brand">
        <span className="app-nav-name">vReview</span>
      </div>

      <ul className="app-nav-links" role="list">
        <li className="app-nav-group">
          <p className="app-nav-group-label" id="nav-ai-review-heading">
            AI Review
          </p>
          <ul
            className="app-nav-group-items"
            role="list"
            aria-labelledby="nav-ai-review-heading"
          >
            <AppNavLink
              id="nav-run-review"
              to="/"
              icon="run"
              label="Run review"
              title="Run review"
            />
            <AppNavLink
              id="nav-history"
              to="/history"
              icon="history"
              label="History"
              title="History"
            />
            <AppNavLink
              id="nav-review-rules"
              to="/review-rules"
              icon="rules"
              label="Review rules"
              title="Review rules"
            />
          </ul>
        </li>
        <AppNavLink
          id="nav-memory-watch"
          to="/memory"
          icon="memory"
          label="Memory Watch"
          title="Memory Watch"
        />
      </ul>

      <div className="app-nav-footer">
        <div className="nav-health" aria-label={`System status: ${healthLabel}`}>
          <span className={`health-dot health-dot--${healthStatus}`} />
          <span className="nav-health-label">{healthLabel}</span>
        </div>
        <button
          id="nav-logout-btn"
          className="nav-logout-btn"
          onClick={logout}
          aria-label="Logout"
          type="button"
        >
          Logout
        </button>
        {healthResponse?.build_number && (
          <div className="nav-build-number">
            Build: {healthResponse.build_number}
          </div>
        )}
      </div>
    </nav>
  );
}
