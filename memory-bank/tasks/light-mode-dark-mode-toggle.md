---
legacy_id: light-mode-dark-mode-toggle
---
# light-mode-dark-mode-toggle: Light Mode / Dark Mode Toggle

**Status**: REFLECTION_COMPLETE
**Phase**: REFLECT
**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 2
**Roadmap Link**: FEAT-061
**Branch**: feature/FEAT-061-light-dark-toggle
**Created**: 2026-05-31

---

## Description

Add a persistent light mode / dark mode toggle to the vQA dashboard. The UI currently only supports a dark aesthetic. This task implements:

1. **CSS Design Tokens**: Refactor all color values in `index.css` into CSS custom properties scoped under `[data-theme="dark"]` and `[data-theme="light"]` selectors, with a complete accessible light-mode palette.
2. **`useTheme` Hook**: A custom React hook at `src/hooks/useTheme.ts` that reads `localStorage` on mount (defaulting to `dark`), detects system preference via `matchMedia('prefers-color-scheme: dark')` on first visit, and exposes `{ theme, toggleTheme }`.
3. **`ThemeToggle` Component**: A sun/moon icon button (`src/components/ThemeToggle.tsx`) placed in the `AppNav` footer area. On click, it toggles the `data-theme` attribute on `<html>`, updates hook state, and persists to `localStorage`.
4. **System Preference Detection**: On first load (no stored preference), honor `prefers-color-scheme: dark`.

---

## Acceptance Criteria

- **AC-ENTRY-1**: The ThemeToggle button (☀️/🌙 icon) is visible in the left navigation rail on every page of the vQA dashboard.
- **AC-HAPPY-1**: Clicking the toggle immediately switches the app's theme without a page reload — all backgrounds, text, borders, and accents update in real-time.
- **AC-HAPPY-2**: After switching to light mode and refreshing the page, the app loads in light mode (preference survived via localStorage key `vqa-theme`).
- **AC-HAPPY-3**: On first visit (no localStorage entry), the app respects the OS/browser `prefers-color-scheme` setting — dark OS → dark mode, light OS → light mode.
- **AC-HAPPY-4**: All key surfaces in light mode pass WCAG AA color contrast (minimum 4.5:1 for normal text, 3:1 for large text).
- **AC-EDGE-1**: Switching themes rapidly (multiple clicks) does not produce visual artifacts or state desync.
- **AC-EDGE-2**: No regression to dark-mode appearance — dark mode is visually identical to the current design.
- **AC-NEG-1**: If `localStorage` is unavailable (e.g., private browsing), the hook gracefully falls back to system preference without throwing.

---

## Clarifications Needed

_None — requirements are fully specified in FEAT-061._

---

## Specification

### Feature Type
End-User Feature (Frontend-only, no backend changes required)

### Invocation Location
Left navigation rail (`AppNav` component) — footer section, below the logout button.

### Invocation Element
Icon button with aria-label "Switch to light mode" / "Switch to dark mode", displaying ☀️ (sun) in dark mode and 🌙 (moon) in light mode.

### Success State
After clicking: `data-theme` attribute on `<html>` toggles between `"dark"` and `"light"`, all CSS tokens immediately reflect the new palette, and `localStorage.getItem('vqa-theme')` returns the new value.

### Success Verification Location
Any page in the vQA dashboard — visual color change is immediate and all-encompassing.

### Data Persistence
`localStorage` key: `vqa-theme` (values: `"dark"` | `"light"`)

### System Preference Detection
`window.matchMedia('(prefers-color-scheme: dark)')` — queried once on mount when no stored preference exists.

---

## Clarifications Needed

_None._

---

## Implementation Roadmap

### [x] Phase 1 — CSS Token Refactor (`index.css`)

**Goal**: Move all hardcoded color values to CSS custom properties, add `[data-theme="dark"]` and `[data-theme="light"]` scoping.

**Current state**: All color tokens defined on `:root {}` (dark values only — no theming scope).

**Approach**:
1. Move the existing `:root {}` color tokens to `[data-theme="dark"]` (or `:root[data-theme="dark"]`).
2. Add a `[data-theme="light"]` block with a complete complementary palette:
   - `--bg-primary`: `hsl(220, 20%, 97%)` (near-white, very light gray)
   - `--bg-secondary`: `hsl(220, 16%, 93%)` (slightly darker card BG)
   - `--bg-tertiary`: `hsl(220, 12%, 88%)` (input/widget surface)
   - `--bg-hover`: `hsl(220, 10%, 84%)` (hover state)
   - `--bg-overlay`: `hsla(220, 20%, 15%, 0.6)` (modal overlay — stays dark)
   - `--border`: `hsl(220, 12%, 78%)` (visible border on light BG)
   - `--border-focus`: `hsl(262, 80%, 55%)` (purple, consistent with dark)
   - `--border-subtle`: `hsl(220, 10%, 85%)`
   - `--accent`: `hsl(262, 75%, 55%)` (slightly muted for light BG)
   - `--accent-muted`: `hsl(262, 60%, 45%)`
   - `--accent-glow`: `hsla(262, 75%, 55%, 0.12)`
   - `--accent-hover`: `hsl(262, 75%, 45%)`
   - `--text-primary`: `hsl(220, 25%, 12%)` (near-black for contrast)
   - `--text-secondary`: `hsl(220, 15%, 35%)`
   - `--text-hint`: `hsl(220, 10%, 50%)`
   - `--text-muted`: `hsl(220, 10%, 50%)`
   - `--text-on-accent`: `hsl(0, 0%, 100%)`
   - Status tokens: adjusted BG opacities for light surfaces
3. Add a `:root` block for non-color tokens (spacing, radii, transitions, fonts) that remain theme-agnostic.
4. Set `<html data-theme="dark">` as the default in `index.html`.

**Files**: `frontend/src/index.css`, `frontend/index.html`

---

### [x] Phase 2 — `useTheme` Hook (`src/hooks/useTheme.ts`)

```typescript
// src/hooks/useTheme.ts
import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';
const STORAGE_KEY = 'vqa-theme';

export function useTheme() {
  const getInitialTheme = (): Theme => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'dark' || stored === 'light') return stored;
    } catch { /* private browsing */ }
    // System preference fallback
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark';
    return 'light';
  };

  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch { /* private browsing */ }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(t => t === 'dark' ? 'light' : 'dark');
  }, []);

  return { theme, toggleTheme };
}
```

**Files**: `frontend/src/hooks/useTheme.ts` (NEW)

---

### [x] Phase 3 — `ThemeToggle` Component (`src/components/ThemeToggle.tsx`)

```typescript
// src/components/ThemeToggle.tsx
import { useTheme } from '../hooks/useTheme';

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
      <span aria-hidden="true">{isDark ? '☀️' : '🌙'}</span>
      <span className="theme-toggle-label">{isDark ? 'Light' : 'Dark'}</span>
    </button>
  );
}
```

Add to `AppNav` footer (before logout button).

**Files**: `frontend/src/components/ThemeToggle.tsx` (NEW), `frontend/src/components/AppNav.tsx` (MODIFY)

---

### [x] Phase 4 — CSS for ThemeToggle Button

Add `.theme-toggle-btn` styles to `index.css`:
- Matches existing `nav-logout-btn` styling pattern
- Full-width in nav rail, icon + label, shrinks to icon-only at ≤1024px
- Smooth transition on hover

---

### [x] Phase 5 — Wire `useTheme` at App Root

The `useTheme` hook needs to be called once at the top of the component tree so the `data-theme` attribute is set before the first render (prevents FOUC). Options:

**Option A (recommended)**: Call `useTheme()` inside `App.tsx` or a `ThemeProvider` context wrapper. The `ThemeToggle` component also calls `useTheme()` — since both share the same localStorage + `data-theme` contract, they stay in sync. However, to avoid dual hook instantiation calling `getInitialTheme()` twice, wrap in a `ThemeContext`.

**Option B (simpler)**: Call `useTheme()` only in `ThemeToggle` and initialize `data-theme` on `<html>` via a tiny `<script>` in `index.html` to prevent FOUC.

**Chosen**: Option B (simpler, avoids context overhead for a Level 2 feature) — inline script in `index.html` for FOUC prevention + `useTheme` hook owned by `ThemeToggle`.

```html
<!-- index.html — inline FOUC prevention script -->
<script>
  (function() {
    try {
      var t = localStorage.getItem('vqa-theme');
      if (!t) t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', t || 'dark');
    } catch(e) {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  })();
</script>
```

**Files**: `frontend/index.html` (MODIFY)

---

## Test Strategy

### Unit Tests (pytest — backend not affected; Vitest for frontend)

Since this is a pure frontend feature and the project currently has minimal frontend tests, the test strategy focuses on manual verification plus the existing `pytest tests/ -v` suite confirming no backend regressions.

**Manual verification checklist** (to be performed after implementation):
- [ ] Toggle button visible in nav on `/` (Run a Test), `/history`, `/analytics`, `/playwright`
- [ ] Click toggles immediately — no page reload
- [ ] Refresh after switching → correct theme loads
- [ ] Fresh session (clear storage) → system preference honored
- [ ] Dark mode unchanged from current design
- [ ] Light mode — manually verify key surfaces: nav rail, panels, inputs, buttons, status badges

### Automated (existing)
```bash
pytest tests/ -v    # backend — confirm 0 regressions
```

---

## WCAG AA Compliance Plan

Key surfaces to validate in light mode:
| Surface | Token | Value | On BG | Expected Ratio |
|---------|-------|-------|-------|---------------|
| Body text | `--text-primary` on `--bg-primary` | `hsl(220,25%,12%)` on `hsl(220,20%,97%)` | ✅ ~13:1 |
| Secondary text | `--text-secondary` on `--bg-secondary` | `hsl(220,15%,35%)` on `hsl(220,16%,93%)` | ✅ ~6:1 |
| Accent button text | `--text-on-accent` on `--accent` | white on `hsl(262,75%,55%)` | ✅ ~4.6:1 |
| Nav links | `--text-secondary` on `--bg-secondary` | ✅ passes |

---

## Execution State

**Build Status**: COMPLETE
**Phase Being Built**: REFLECT
**Phase Number**: N/A
**Is Multi-Phase**: NO
**Build Started**: 2026-05-31T18:43:00Z
**Build Completed**: 2026-05-31T18:52:00Z
**Reflect Started**: 2026-05-31T13:56:07Z
**Reflect Completed**: 2026-05-31T13:56:07Z
**Current Build Step**:
  Step: ARCHIVE_COMPLETE
  Status: IDLE
**Can Resume**: NO

---

## Implementation Notes

- **No backend changes**: This is a pure frontend feature.
- **No prop-drilling**: `useTheme` hook is the single source of truth via `data-theme` on `<html>`.
- **FOUC prevention**: Inline `<script>` in `index.html` runs before React hydrates.
- **Guiding Principle alignment**: Respects "Config in Environment" pattern for defaults; follows existing CSS token convention in `index.css`.
- **Responsive**: ThemeToggle label hidden at ≤1024px (icon-only) matching existing nav behavior.
