/**
 * vQA — useTheme Hook
 * ====================
 * Module: frontend/src/hooks/useTheme.ts
 *
 * Manages light/dark theme preference with:
 * - localStorage persistence (key: 'vqa-theme')
 * - System preference detection via prefers-color-scheme
 * - Graceful fallback when localStorage is unavailable (private browsing)
 * - Real-time data-theme attribute sync on <html> element
 *
 * Implemented as part of TASK-081 (FEAT-061: Light/Dark Mode Toggle).
 */

import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';
const STORAGE_KEY = 'vqa-theme';

/**
 * Reads the initial theme preference from localStorage.
 * Falls back to system preference, then defaults to 'dark'.
 * Wrapped in try/catch to gracefully handle private browsing environments
 * where localStorage access throws a SecurityError.
 */
function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {
    /* Private browsing — localStorage is unavailable */
  }
  // System preference detection (first visit only)
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

/**
 * useTheme — Custom hook for managing the application color theme.
 *
 * @returns {{ theme: 'dark' | 'light', toggleTheme: () => void }}
 *
 * @example
 * const { theme, toggleTheme } = useTheme();
 * // theme: current theme string ('dark' | 'light')
 * // toggleTheme: call to switch between themes
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  // Sync data-theme attribute and persist to localStorage whenever theme changes
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* Private browsing — ignore write failure */
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return { theme, toggleTheme };
}
