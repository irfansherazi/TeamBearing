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
 * - > 1024px: 220px wide, icon + label
 * - 768px–1024px: 64px icon-only (labels hidden via CSS)
 * - < 768px: bottom tab bar (via CSS grid on AppShell)
 *
 * Design tokens sourced from index.css (Phase 1 — TASK-065).
 */

import { NavLink } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { useExecution } from '../hooks/useExecution';
import { useEffect } from 'react';
import { ThemeToggle } from './ThemeToggle';

interface NavItemProps {
  to: string;
  icon: string;
  label: string;
  title: string;
}

function AppNavLink({ to, icon, label, title }: NavItemProps) {
  return (
    <li>
      <NavLink
        to={to}
        end={to === '/'}
        title={title}
        className={({ isActive }) =>
          `app-nav-link${isActive ? ' active' : ''}`
        }
      >
        <span className="app-nav-icon" aria-hidden="true">{icon}</span>
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

  // Check health on mount
  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const healthStatus = healthResponse
    ? (healthResponse.status === 'ok' ? 'ok' : 'error')
    : 'warning';

  const healthLabel = healthResponse
    ? (healthResponse.status === 'ok' ? 'All Systems Go' : 'Degraded')
    : 'Connecting…';

  return (
    <nav className="app-nav" aria-label="Main navigation">
      {/* Brand */}
      <div className="app-nav-brand">
        <span className="app-nav-logo" aria-hidden="true">🔎</span>
        <span className="app-nav-name">vReview</span>
      </div>

      {/* Navigation Links */}
      <ul className="app-nav-links" role="list">
        <li className="app-nav-group">
          <p className="app-nav-group-label" id="nav-ai-review-heading">AI Review</p>
          <ul
            className="app-nav-group-items"
            role="list"
            aria-labelledby="nav-ai-review-heading"
          >
            <AppNavLink
              to="/"
              icon="🔎"
              label="Run review"
              title="Run review"
            />
            <AppNavLink
              to="/history"
              icon="📋"
              label="History"
              title="History"
            />
            <AppNavLink
              to="/review-rules"
              icon="📘"
              label="Review rules"
              title="Review rules"
            />
          </ul>
        </li>
        <li className="app-nav-group">
          <p className="app-nav-group-label" id="nav-memory-watch-heading">Memory Watch</p>
          <ul
            className="app-nav-group-items"
            role="list"
            aria-labelledby="nav-memory-watch-heading"
          >
            <AppNavLink
              to="/memory"
              icon="🧠"
              label="Memory Watch"
              title="Memory Watch"
            />
          </ul>
        </li>
      </ul>

      {/* Footer: health + theme toggle + logout */}
      <div className="app-nav-footer">
        <div className="nav-health" aria-label={`System status: ${healthLabel}`}>
          <span className={`health-dot health-dot--${healthStatus}`} />
          <span className="nav-health-label">{healthLabel}</span>
        </div>
        <ThemeToggle />
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
