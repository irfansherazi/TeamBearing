/**
 * vQA — ThemeToggle Component
 * ============================
 * Module: frontend/src/components/ThemeToggle.tsx
 *
 * Sun/moon icon button for toggling between light and dark themes.
 * Placed in the AppNav footer area (above or below logout button).
 *
 * Behavior:
 * - In dark mode: shows ☀️ sun icon ("Switch to light mode")
 * - In light mode: shows 🌙 moon icon ("Switch to dark mode")
 * - Clicking immediately toggles data-theme on <html> and persists to localStorage
 * - Label is hidden at ≤1024px (icon-only) matching existing nav behavior
 * - aria-label updates dynamically for screen reader accessibility
 *
 * Implemented as part of TASK-081 (FEAT-061: Light/Dark Mode Toggle).
 */

import { useTheme } from '../hooks/useTheme';

/**
 * ThemeToggle — Icon button for switching between light and dark mode.
 *
 * Uses the useTheme hook as its single source of truth.
 * The data-theme attribute on <html> is set by the hook, making the
 * change immediate and all-encompassing without prop drilling.
 */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      id="theme-toggle-btn"
      className="theme-toggle-btn"
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      type="button"
    >
      <span aria-hidden="true" style={{ fontSize: '16px' }}>
        {isDark ? '☀️' : '🌙'}
      </span>
      <span className="theme-toggle-label">
        {isDark ? 'Light' : 'Dark'}
      </span>
    </button>
  );
}
