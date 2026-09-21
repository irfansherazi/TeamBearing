/**
 * vReview — AppShell Component
 * ============================
 * Module: frontend/src/components/AppShell.tsx
 *
 * Top-level layout grid:
 * - Left: AppNav rail
 * - Right: <main> scrollable workspace (page title + shared tools)
 *
 * All protected routes render inside AppShell via router.tsx.
 */

import type { ReactNode } from "react";
import { AppNav } from "./AppNav";
import { AppWorkspaceTools } from "./AppPage";
import { SessionProvider } from "../context/SessionContext";

interface AppShellProps {
  /** Page content rendered in the scrollable main area */
  children: ReactNode;
}

/**
 * AppShell — root layout wrapper for all authenticated pages.
 *
 * Wraps every protected route in a consistent two-column grid:
 * left nav rail + scrollable main content area.
 *
 * @param props - Page content for the main column
 * @returns The authenticated app chrome
 */
export function AppShell({ children }: AppShellProps) {
  return (
    <SessionProvider>
      <div className="app-shell">
        <AppNav />
        <main className="app-main" id="main-content">
          <div className="app-workspace">
            <AppWorkspaceTools />
            {children}
          </div>
        </main>
      </div>
    </SessionProvider>
  );
}
