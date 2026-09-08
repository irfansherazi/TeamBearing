# Creative: UI/UX Design — Playwright Standard Library Dashboard
## playwright-standard-library-integration-full-runtime-wiring | FEAT-052 | Phase: CREATIVE

**Design Date**: 2026-05-27  
**Designer**: Inline Orchestrator  
**Type**: UI/UX Design

---

## Decision

**Chosen**: Option A — Three-Panel Progressive Disclosure with Integrated Tab in Dashboard Header

The Playwright Dashboard is integrated as a **4th tab** in the existing `Dashboard.tsx` header nav (`▶ Run Test | 📚 Reports Archive | 📊 Analytics | 🎭 Playwright`). The tab content uses a **three-panel split**: left panel (Test Browser), right upper panel (Config), right lower panel (Terminal). Progressive disclosure means the right side is empty until a test is selected, and the terminal is hidden until a run starts.

---

## Design System Constraints

The design must **match** the existing vQA dark-mode aesthetic:

```css
/* Existing design tokens from index.css */
--bg-primary: #0d1117       /* deep dark background */
--bg-secondary: #161b22     /* card/panel background */
--bg-tertiary: #21262d      /* input/control background */
--accent: #58a6ff           /* blue accent */
--accent-success: #3fb950   /* green for pass */
--accent-error: #f85149     /* red for fail */
--accent-warning: #d29922   /* amber for warning */
--text-primary: #c9d1d9
--text-secondary: #8b949e
--border: #30363d
--border-active: #58a6ff
--transition-fast: 150ms ease
--transition-smooth: 250ms ease
```

**Typography**: Existing font family (`Inter`, `system-ui`). Terminal uses `'JetBrains Mono', 'Fira Code', monospace`.

---

## Layout Specification

### Dashboard Tab Bar (Modified)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🔬 vQA   Autonomous QA Agent                                    ● All Systems│
│ ─────────────────────────────────────────────────────────────────────────── │
│ [▶ Run Test] [📚 Reports Archive] [📊 Analytics] [🎭 Playwright]    [Logout] │
└─────────────────────────────────────────────────────────────────────────────┘
```

The existing `Tab` type is extended: `type Tab = "run" | "archive" | "analytics" | "playwright"`.

---

### Playwright Page Layout (Three-Panel)

```
┌──────────────────────────────┬─────────────────────────────────────────────┐
│  🔍 Search tests...          │                                              │
├──────────────────────────────│                                              │
│  📁 QA (25 tests)  ▾        │    [Select a test to configure and run]     │
│  ────────────────────────── │                                              │
│  🎭 qa-321-sorting-list...   │    ← Empty state illustration               │
│     QA-321 • 8 steps         │                                              │
│  🎭 qa-280-compact-view...   │                                              │
│     QA-280 • 12 steps        │                                              │
│  🎭 qa-291-approvals...      │                                              │
│     QA-291 • 6 steps         │                                              │
│  ...                         │                                              │
├──────────────────────────────│                                              │
│  📁 VC2 (14 tests)  ▾       │                                              │
│  📁 Other (1 test)  ▾       │                                              │
└──────────────────────────────┴─────────────────────────────────────────────┘
```

After test selection:
```
┌──────────────────────────────┬─────────────────────────────────────────────┐
│  🔍 [321              ] ✕   │  ┌──────────────────────────────────────── │
├──────────────────────────────│  │ qa-321-sorting-list-and-compact.test    │
│  📁 QA (1 match)  ▾         │  │ QA-321                                  │
│  ────────────────────────── │  │ Tests list sorting and compact view     │
│ ▶ 🎭 qa-321-sorting-list... │  │                                          │
│     QA-321 • 8 steps ✅      │  │ Steps: 8                                │
│                              │  └──────────────────────────────────────── │
│                              │                                              │
│                              │  ┌── Configuration ──────────────────────  │
│                              │  │  Environment   [ test  ▾]               │
│                              │  │  User          [ DemoSalesExec  ▾]      │
│                              │  │  Browser       [ chromium  ▾]            │
│                              │  │                                          │
│                              │  │  [    🚀 Run Test    ]                  │
│                              │  └──────────────────────────────────────── │
└──────────────────────────────┴─────────────────────────────────────────────┘
```

After run starts:
```
┌──────────────────────────────┬─────────────────────────────────────────────┐
│  🔍 [321              ] ✕   │  ┌── Test Started ─ Streaming Output ──── │
├──────────────────────────────│  │ ● Test started — streaming output below  │
│  📁 QA (1 match)  ▾         │  ├──────────────────────────────────────── │
│  ────────────────────────── │  │                                          │
│ ▶ 🎭 qa-321-sorting... ⟳   │  │ Running Chromium                        │
│     QA-321 • 8 steps         │  │                                          │
│                              │  │ > npx playwright test...                │
│  [■ Cancel Run]              │  │ ✓ [chromium] › Sort by Name (1.2s)      │
│                              │  │ ✓ [chromium] › Sort by Status (0.8s)   │
│                              │  │ ✓ [chromium] › Compact View (2.1s)     │
│                              │  │ ...                                      │
│                              │  │                                          │
│                              │  └──────────────────────────────────────── │
└──────────────────────────────┴─────────────────────────────────────────────┘
```

---

## Component Specifications

### TestBrowserPanel

```
Dimensions: width 320px (fixed), full height, scrollable
Background: var(--bg-secondary)
Border-right: 1px solid var(--border)

Search Field:
  - Full-width input with magnifier icon
  - Placeholder: "Search tests, JIRA keys..."
  - Debounce: 100ms
  - Clear button (✕) appears when value non-empty
  - Background: var(--bg-tertiary)
  - Border: 1px solid var(--border); focus: var(--border-active)

Group Headers:
  - Sticky positioning (stays visible while scrolling)
  - Icon: 📁 (collapsed) / 📂 (expanded)
  - Text: "QA (25 tests)"
  - Font: var(--text-secondary), 12px, uppercase, 600 weight
  - Click to collapse/expand
  - Arrow indicator (▶ / ▼)

Test Cards:
  - Height: 56px
  - Padding: 10px 12px
  - Two-line layout:
    - Line 1: test filename (text-primary, 13px, truncated with ellipsis)
    - Line 2: JIRA keys + step count (text-secondary, 11px)
  - States:
    - Default: bg transparent, hover: bg var(--bg-tertiary)
    - Selected: bg rgba(88,166,255,0.08), border-left: 3px solid var(--accent)
    - Running: selected + spinning 🔄 icon replaces 🎭
  - Transition: all var(--transition-fast)
  - Cursor: pointer
  - Role: button, tabIndex: 0 (keyboard accessible)
```

### TestConfigPanel

```
Appears: When test is selected (slide-in animation from right, 250ms)
Width: calc(100% - 320px)
Upper section: ~180px height

Test Detail Card:
  - Header: test filename in monospace, 14px
  - JIRA key badge(s): pill shape, var(--accent) color, 11px
  - Description: text-secondary, 13px, 2-line clamp
  - Step count: "8 steps" in muted text

Configuration Grid:
  - Three labeled dropdowns in a row (or column on narrow screens)
  - Label: var(--text-secondary), 12px, uppercase
  - Select: height 36px, var(--bg-tertiary) bg, var(--border) border
    Options styled to match existing ExecutionPanel selects
  - Auth warning: amber inline notice if selected env has expired sessions
    "⚠ 3 sessions expired in prod — consider refreshing auth first"

Run Button:
  - Size: 160px × 40px (primary call-to-action)
  - States:
    - Idle:    bg var(--accent), text white, "🚀 Run Test"
    - Loading: bg var(--accent-muted), spinner + "Starting…"
    - Running: bg var(--accent-error)/20%, text var(--accent-error), "■ Running…"
    - Disabled (no test): opacity 0.4, cursor not-allowed
  - Border-radius: 6px
  - id="playwright-run-btn" (for UAT)
```

### RunControlPanel (Terminal)

```
Appears: After run starts (slide-down below config panel, 200ms)
Height: calc(100vh - [header] - [config] - [tabs])
Min-height: 300px

Terminal Header:
  - Background: var(--bg-tertiary)
  - Left: "● Terminal Output" label (text-secondary, 12px uppercase)
  - Right: Pass/fail badge after completion
    - PASS: green pill "✅ PASSED" (var(--accent-success))
    - FAIL: red pill "❌ FAILED (exit 1)" (var(--accent-error))
    - Truncated warning: "⚠ Older lines truncated — showing last 500"

Terminal Body:
  - Font: 'JetBrains Mono', 'Fira Code', monospace, 13px
  - Background: #010409 (near-black, like GitHub's terminal)
  - Text color: #c9d1d9 (default)
  - ANSI color codes: rendered (use ansi-to-html or ansi-regex)
    - stdout lines: default text color
    - ✓ passing lines: var(--accent-success)
    - ✗ failing lines: var(--accent-error)
    - stderr lines: slight amber tint (var(--accent-warning))
  - Padding: 12px 16px
  - Overflow-y: auto; scroll-behavior: smooth
  - Auto-scroll: pinned to bottom unless user scrolls up (intersection observer)
  - Line selection: user-select: text (allows copying)
  - Line format: "[HH:MM:SS] <line content>"
```

### StorageManagerPanel (Tab 2)

```
Tab: "🗂 Storage Manager" (second tab inside /playwright page)
Layout: Full width card

Status Matrix:
  - Table: 13 rows (users) × 4 columns (envs) + 1 header row
  - Column headers: prod | test | smoke | qa (with Refresh Auth button per column)
  - Row headers: user display names (left-aligned, 13px, text-secondary)
  - Cells: colored badge pill
    - 🟢 valid:   bg rgba(63,185,80,0.15), text var(--accent-success)
    - 🟡 expired: bg rgba(210,153,34,0.15), text var(--accent-warning)
    - 🔴 missing: bg rgba(248,81,73,0.15), text var(--accent-error)
    - ⟳ loading: spinner gray
  - Min cell width: 80px; text: "valid" / "expired" / "missing" (13px)

Refresh Auth Button (per environment column):
  - id="playwright-auth-refresh-btn-{env}" (for UAT)
  - Size: compact, 110px × 28px
  - States:
    - Idle: "🔄 Refresh Auth" (text-secondary, var(--bg-tertiary) bg)
    - Loading: "⟳ Generating…" (spinner)
    - Success: "✅ Done" (green, 2s then revert)
    - Error: "❌ Failed" (red, 5s then revert)
  - Tooltip: "Regenerate auth sessions for all 13 users in [env]"

Success Banner:
  - Appears below table after success
  - Green alert: "✅ Storage states regenerated for test: 13/13 users"
  - Auto-dismiss after 8 seconds
```

---

## Option Analysis

### Option A (Chosen): 4th Dashboard Tab + Three-Panel Split
- **Pros**: No new page routes needed; auth context preserved; existing header reused; feels native
- **Cons**: Extends `Dashboard.tsx` state management (one more tab branch)
- **Chosen**: Best balance of integration and scope

### Option B: Standalone `/playwright` Route
- **Pros**: Clean separation; own URL
- **Cons**: Would duplicate header, auth, and nav; harder to share WebSocket context
- **Rejected**: Unnecessary duplication for internal tooling page

### Option C: Inline Panel in Run Test Tab
- **Pros**: Minimal routing change
- **Cons**: Clutters the primary Run Test experience; Storage Manager has no room
- **Rejected**: Wrong information architecture

---

## Responsive Behavior

| Breakpoint | Behavior |
|-----------|----------|
| > 1200px | Three-panel split, full search, all dropdowns in a row |
| 900–1200px | Test browser collapses to 260px; config dropdowns stack 2-column |
| < 900px | Single column: test browser → config → terminal stacked vertically |

---

## Accessibility Checklist

- [ ] Test cards: `role="button"`, `tabIndex`, `aria-selected`, `aria-label="<test-id> selected"`
- [ ] Search: `aria-label="Search tests"`, `aria-live="polite"` for result count updates
- [ ] Terminal: `role="log"`, `aria-live="polite"` for streaming lines (capped at 1 announcement per 500ms)
- [ ] Status badges: `aria-label="valid"` etc. (not just color)
- [ ] Run button: `aria-disabled` when no test selected, `aria-busy` when running
- [ ] Group headers: `role="button"`, `aria-expanded`

---

## ANSI Color Rendering

Playwright uses ANSI escape codes for pass/fail colors. Implementation:

```typescript
// Use ansi-to-html package (already lightweight, no dom dependency)
import AnsiToHtml from 'ansi-to-html';
const converter = new AnsiToHtml({ escapeXML: true });

function renderLine(line: string): string {
    return converter.toHtml(line);
}
// Render as: <span dangerouslySetInnerHTML={{ __html: renderLine(line) }} />
// Note: escapeXML: true prevents XSS from log content
```

---

## Micro-Animations

| Element | Animation | Duration |
|---------|-----------|----------|
| Config panel appears | Slide in from right + fade | 250ms ease |
| Terminal appears | Slide down + fade | 200ms ease |
| Test card selection | Border-left + background | 150ms ease |
| Run button state change | Color transition | 150ms ease |
| Storage badge update | Fade through on refresh | 300ms ease |
| New terminal line | No animation (performance) | — |
| Pass/fail badge | Scale-in from 0 + fade | 200ms ease |
