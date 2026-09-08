/**
 * vQA — AppShell Component
 * =========================
 * Module: frontend/src/components/AppShell.tsx
 *
 * Top-level layout grid:
 * - Left: AppNav rail (220px / 64px collapsed / bottom tabs on mobile)
 * - Right: <main> scrollable content area
 *
 * All protected routes render inside AppShell via router.tsx.
 * Children are rendered inside the main content area.
 *
 * CSS grid layout is defined in index.css under .app-shell.
 * Design: TASK-065 creative doc — Option A Deep Purple Shell.
 */

import type { ReactNode } from 'react';
import { AppNav } from './AppNav';
import { SessionProvider } from '../context/SessionContext';
import { SessionStatusIndicator } from './SessionStatusIndicator';

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
 * @example
 * ```tsx
 * // In router.tsx:
 * <AppShell>
 *   <Dashboard />
 * </AppShell>
 * ```
 */
export function AppShell({ children }: AppShellProps) {
  return (
    // SessionProvider is mounted here so it is always inside AuthProvider
    // (AppShell only renders for authenticated routes) and always above
    // every page that needs useSession().
    <SessionProvider>
      <div className="app-shell">
        <AppNav />
        <main className="app-main" id="main-content">
          {children}
        </main>
        {/* Session status dot — positioned fixed in top-right corner */}
        <SessionStatusIndicator
          className="session-status-dot"
        />
      </div>
    </SessionProvider>
  );
}
