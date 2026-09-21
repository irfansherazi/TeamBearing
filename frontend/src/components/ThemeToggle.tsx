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

interface ThemeToggleProps {
  compact?: boolean;
}

/**
 * ThemeToggle — Icon button for switching between light and dark mode.
 *
 * @param props - compact hides the Light/Dark text for the page header
 * @returns Theme switch control
 */
export function ThemeToggle({ compact = false }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      id={compact ? "theme-toggle-header-btn" : "theme-toggle-btn"}
      className={`theme-toggle-btn${compact ? " theme-toggle-btn--icon" : ""}`}
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      type="button"
    >
      <span aria-hidden="true" className="theme-toggle-glyph">
        {isDark ? "☀" : "☾"}
      </span>
      {compact ? null : (
        <span className="theme-toggle-label">{isDark ? "Light" : "Dark"}</span>
      )}
    </button>
  );
}
