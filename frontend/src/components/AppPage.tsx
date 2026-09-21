/**
 * vReview — shared page header used by every workspace screen.
 */

import type { ReactNode } from "react";
import { ThemeToggle } from "./ThemeToggle";

interface AppPageProps {
  title: string;
  subtitle?: string;
  badge?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Theme control shared across every page.
 *
 * @returns Header tool buttons
 */
export function AppWorkspaceTools() {
  return (
    <div className="app-workspace-tools">
      <ThemeToggle compact />
    </div>
  );
}

/**
 * Page title row plus body. Tools sit in AppShell so every route matches.
 *
 * @param props - Title, optional subtitle/badge/actions, and page body
 * @returns The page frame
 */
export function AppPage({ title, subtitle, badge, actions, children }: AppPageProps) {
  return (
    <div className="app-page">
      <header className="app-page-header">
        <div className="app-page-heading">
          <div className="app-page-title-row">
            <h1 className="app-page-title">{title}</h1>
            {badge ? <div className="app-page-badge">{badge}</div> : null}
          </div>
          {subtitle ? <p className="app-page-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="app-page-actions">{actions}</div> : null}
      </header>
      <div className="app-page-body">{children}</div>
    </div>
  );
}
