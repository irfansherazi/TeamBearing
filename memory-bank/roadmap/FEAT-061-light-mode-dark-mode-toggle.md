---
legacy_id: FEAT-061
version: next
linked_tasks: [light-mode-dark-mode-toggle]
status: complete
---

### FEAT-061: Light Mode / Dark Mode Toggle
- **Version**: next
- **Status**: complete
- **Priority**: medium
- **Complexity**: Level 2
- **Description**: Add a persistent light mode / dark mode toggle to the vQA dashboard. The UI currently only supports a dark aesthetic; this feature introduces a full light-mode color palette and a toggle control (sun/moon icon button) that lets users switch themes on demand. Theme preference is persisted in `localStorage` and restored on app load. Key requirements:
    1. **CSS Design Tokens**: Refactor all hardcoded color values in the frontend into a set of CSS custom properties (e.g., `--bg-primary`, `--text-primary`, `--surface`, `--accent`) scoped under `[data-theme="dark"]` and `[data-theme="light"]` selectors. Define a complete, accessible light-mode palette that matches the app's existing design language.
    2. **Theme Toggle Component**: Build a `ThemeToggle` React component (icon button — ☀️ / 🌙) placed in the top navigation bar. On click, it toggles the `data-theme` attribute on `<html>`, updates a `useTheme` hook state, and writes the preference to `localStorage`.
    3. **Persistence Hook**: Implement a `useTheme` custom hook that reads from `localStorage` on mount (defaulting to `dark`) and exposes `{ theme, toggleTheme }`. The hook is the single source of truth; no prop-drilling needed.
    4. **System Preference Detection**: On first load (no stored preference), detect `prefers-color-scheme: dark` via `matchMedia` and default accordingly.
- **Acceptance Criteria**:
    - Toggle button visible in the navbar on all pages
    - Switching themes applies immediately without page reload
    - Preference survives page refresh (localStorage persistence)
    - System preference is honored on first visit
    - Light mode passes WCAG AA color contrast on all key surfaces
    - No regressions to dark-mode appearance
- **Linked Tasks**: light-mode-dark-mode-toggle
- **Branch**: feature/FEAT-061-light-dark-toggle
- **Created**: 2026-05-31
- **Completed**: 2026-05-31 ✅
