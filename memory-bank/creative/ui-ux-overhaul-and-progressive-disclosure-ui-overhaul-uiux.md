# Creative: UI/UX Design — UI/UX Overhaul & Progressive Disclosure
## ui-ux-overhaul-and-progressive-disclosure | FEAT-050 | Phase: CREATIVE

**Design Date**: 2026-05-28
**Designer**: Inline Orchestrator
**Type**: UI/UX Design

---

## Decision

**Chosen**: Option A — Deep Purple Shell with 4-Mode State Machine + Shared StepTable

The UI adopts a **deep purple dark theme**, a permanent **left nav rail** replacing the top tab bar, and a **mode state machine** (`select` → `review` → `running` → `complete`) that progressively reveals only the controls relevant to each moment. A **shared `StepTable` component** is used across REVIEW, RUNNING, and COMPLETE modes with mode-aware props.

---

## Design System — Updated Tokens

The current indigo/navy palette shifts to a richer deep purple. All new tokens are additive; existing tokens are overridden.

```css
/* === vQA Design Tokens v2 — index.css === */

/* Backgrounds */
--bg-primary:    hsl(250, 28%, 7%);    /* Deep purple-black — main shell */
--bg-secondary:  hsl(248, 22%, 11%);   /* Panel backgrounds, nav rail */
--bg-tertiary:   hsl(246, 18%, 16%);   /* Card backgrounds, inputs */
--bg-hover:      hsl(246, 18%, 19%);   /* Hover states */
--bg-overlay:    hsla(250, 28%, 4%, 0.85); /* Modal backdrops */

/* Borders */
--border:        hsl(246, 15%, 22%);
--border-focus:  hsl(262, 80%, 65%);   /* Purple focus ring */
--border-subtle: hsl(246, 15%, 18%);

/* Accent */
--accent:        hsl(262, 80%, 65%);   /* Purple (replaces indigo #58a6ff) */
--accent-muted:  hsl(262, 60%, 45%);
--accent-glow:   hsla(262, 80%, 65%, 0.15);
--accent-hover:  hsl(262, 80%, 72%);

/* Text */
--text-primary:   hsl(240, 20%, 92%);
--text-secondary: hsl(240, 10%, 60%);
--text-muted:     hsl(240, 8%, 45%);
--text-on-accent: hsl(0, 0%, 100%);

/* Status Badges */
--status-pass:          hsl(152, 60%, 45%);
--status-pass-bg:       hsla(152, 60%, 45%, 0.12);
--status-pass-border:   hsla(152, 60%, 45%, 0.3);
--status-fail:          hsl(0, 75%, 58%);
--status-fail-bg:       hsla(0, 75%, 58%, 0.12);
--status-fail-border:   hsla(0, 75%, 58%, 0.3);
--status-running:       hsl(38, 90%, 55%);
--status-running-bg:    hsla(38, 90%, 55%, 0.12);
--status-skip:          hsl(215, 16%, 50%);
--status-skip-bg:       hsla(215, 16%, 50%, 0.1);
--status-waiting:       hsl(240, 8%, 38%);

/* Transitions */
--transition-fast:   150ms ease;
--transition-smooth: 300ms ease;
--transition-enter:  250ms cubic-bezier(0.16, 1, 0.3, 1); /* spring-like */
```

---

## App Shell Layout

### Grid Structure

```css
.app-shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  grid-template-rows: 1fr;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-primary);
}

/* Responsive: collapse nav at 1024px */
@media (max-width: 1024px) {
  .app-shell {
    grid-template-columns: 64px 1fr;
  }
}

/* Responsive: bottom tab bar at 768px */
@media (max-width: 768px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr auto;
  }
  .app-nav { /* becomes bottom bar */ }
}
```

### Main Content Area

```css
.app-main {
  overflow-y: auto;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.app-main-inner {
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  padding: 0 24px 48px;
}
```

---

## Left Navigation Rail

### Visual Specification

```
┌──────────────────────┐
│  🔬  vQA             │  ← Brand (64px height, padding 16px 20px)
├──────────────────────┤
│  ▌ ▶  Run a Test     │  ← Active link (2px left border, accent)
│    📋 Test History    │
│    📊 Analytics       │
│    🎭 Playwright Suite│
├──────────────────────┤  ← spacer (flex-grow: 1)
│  ● All Systems Go    │  ← Health indicator
│  [Logout]            │  ← Logout button
└──────────────────────┘
```

### CSS

```css
.app-nav {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

.app-nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border);
  min-height: 64px;
}

.app-nav-logo { font-size: 22px; }

.app-nav-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}

.app-nav-links {
  list-style: none;
  padding: 12px 0;
  margin: 0;
  flex: 1;
}

.app-nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  border-left: 2px solid transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.app-nav-link:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.app-nav-link.active {
  border-left-color: var(--accent);
  background: var(--accent-glow);
  color: var(--text-primary);
}

.app-nav-icon { font-size: 18px; width: 20px; flex-shrink: 0; }

.app-nav-footer {
  border-top: 1px solid var(--border);
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Icon-only mode at 1024px */
@media (max-width: 1024px) {
  .app-nav-name, .app-nav-link-label { display: none; }
  .app-nav-link { padding: 12px; justify-content: center; }
  .app-nav-link[title]:hover::after { /* tooltip */ }
}

/* Bottom tab bar at 768px */
@media (max-width: 768px) {
  .app-nav {
    flex-direction: row;
    border-right: none;
    border-top: 1px solid var(--border);
    order: 2;
  }
  .app-nav-brand, .app-nav-footer { display: none; }
  .app-nav-links { display: flex; flex-direction: row; padding: 0; }
  .app-nav-link { flex: 1; flex-direction: column; gap: 4px; padding: 8px 4px; font-size: 11px; border-left: none; border-top: 2px solid transparent; }
  .app-nav-link.active { border-top-color: var(--accent); border-left: none; }
}
```

### Health Dot

```css
.health-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.health-dot--ok      { background: var(--status-pass); box-shadow: 0 0 6px var(--status-pass); }
.health-dot--warning { background: var(--status-running); }
.health-dot--error   { background: var(--status-fail); }
```

---

## Top Bar (Inside Main Content Area)

Shared across all modes. Content changes per mode.

```css
.mode-topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 56px;
}

.topbar-breadcrumb {
  font-size: 13px;
  color: var(--text-secondary);
  flex: 1;
}

.topbar-status { /* status badge in top-right corner */
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.topbar-action { /* primary action button */
  flex-shrink: 0;
}
```

---

## Mode 1: SELECT View

### Visual Layout

```
┌─────────────────────────────────────────────────────────┐
│                                                          │
│              Start a New Test                            │
│                                                          │
│  Jira Ticket                                             │
│  [ 🔍 Search by ticket ID or title...               ▼ ] │
│                                                          │
│  Test As                  Environment                    │
│  [ Account Executive  ▼ ] [ Staging             ▼ ]     │
│                                                          │
│  ▸ Advanced Settings                                     │
│                                                          │
│                        [ ▶ Start Test ]                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### CSS

```css
.select-view {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 80px 24px;
}

.select-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 36px;
  width: 100%;
  max-width: 560px;
}

.select-card-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 28px;
}

.select-field-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

@media (max-width: 600px) {
  .select-field-group { grid-template-columns: 1fr; }
}

.field-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.field-select, .field-combobox {
  width: 100%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
  padding: 9px 12px;
  transition: border-color var(--transition-fast);
  appearance: none;
}
.field-select:focus, .field-combobox:focus {
  outline: none;
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

/* Advanced Settings accordion */
.advanced-settings {
  margin-top: 20px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 16px;
}

.advanced-settings summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  user-select: none;
}
.advanced-settings summary::before {
  content: '▸';
  transition: transform var(--transition-fast);
}
.advanced-settings[open] summary::before {
  transform: rotate(90deg);
}

.advanced-settings-body {
  padding-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* CTA area */
.select-cta {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}
```

---

## Shared: Step Table Component

The single most critical shared component. Props control behavior by mode.

### Interface

```tsx
interface StepRow {
  index: number;            // 1-based display number
  text: string;             // step description
  source: 'jira' | 'user_added';
  result?: 'passed' | 'failed' | 'running' | 'skipped' | 'waiting';
  reasoning?: string;       // agent's thinking for this step
}

interface StepTableProps {
  steps: StepRow[];
  mode: 'review' | 'running' | 'complete';
  onEdit?: (index: number, newText: string) => void;
  onReorder?: (fromIndex: number, toIndex: number) => void;
  onDelete?: (index: number) => void;
  onAddNaturalLanguage?: (input: string) => Promise<void>;
  isAddingStep?: boolean; // shows shimmer in add row
}
```

### Visual — REVIEW Mode

```
┌─────────────────────────────────────────────────────────────┐
│  #  │  Test Step                                │  Source   │
├─────┼───────────────────────────────────────────┼───────────┤
│  1  │  Navigate to the file upload page         │ ⟠ Jira ⋮⋮ ✕│
│  2  │  Locate the file upload field             │ ⟠ Jira ⋮⋮ ✕│
│  3  │  Select a file larger than the size limit │ ⟠ Jira ⋮⋮ ✕│
│  4  │  Verify the error message displays limit  │ ✚ You  ⋮⋮ ✕│
├─────┴───────────────────────────────────────────────────────┤
│ ✦  Add anything — 'also check the error message'      [ ↵ ] │
└─────────────────────────────────────────────────────────────┘
```

### Visual — RUNNING / COMPLETE Mode

```
┌──────┬──────────────────────────┬──────────────────────┬──────────┐
│  #   │  Action                  │  Expectation         │  Result  │
├──────┼──────────────────────────┼──────────────────────┼──────────┤
│  1   │  Navigate to upload page │  Page loads OK       │ ✅ Passed │
│  2   │  Locate upload field     │  Field is visible    │ ✅ Passed │
│  3   │  Select oversized file   │  File selected       │ ⏳ Running│
│  4   │  Attempt upload          │  Upload starts       │  ─ Wait  │
└──────┴──────────────────────────┴──────────────────────┴──────────┘
```

### CSS

```css
.step-table-wrapper {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.step-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.step-table thead th {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

.step-table tbody tr {
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--transition-fast);
}

.step-table tbody tr:hover {
  background: var(--bg-hover);
}

.step-table tbody tr:last-child {
  border-bottom: none;
}

.step-table td {
  padding: 12px 14px;
  color: var(--text-primary);
  vertical-align: top;
}

/* Step number column */
.step-col-num {
  width: 40px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}

/* Editable step text (REVIEW mode) */
.step-text-editable {
  cursor: text;
  border-radius: 4px;
  padding: 2px 4px;
  margin: -2px -4px;
  transition: background var(--transition-fast);
}
.step-text-editable:hover { background: var(--bg-tertiary); }

.step-text-input {
  width: 100%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-focus);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 14px;
  padding: 4px 8px;
  outline: none;
  box-shadow: 0 0 0 2px var(--accent-glow);
}

/* Source badge */
.step-source-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  white-space: nowrap;
}
.step-source-badge--jira { 
  color: var(--accent); 
  background: var(--accent-glow); 
}
.step-source-badge--user {
  color: hsl(152, 60%, 45%);
  background: hsla(152, 60%, 45%, 0.1);
}

/* Drag handle */
.step-drag-handle {
  cursor: grab;
  color: var(--text-muted);
  opacity: 0;
  transition: opacity var(--transition-fast);
  font-size: 16px;
}
.step-table tbody tr:hover .step-drag-handle { opacity: 1; }

/* Delete button */
.step-delete-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all var(--transition-fast);
  font-size: 14px;
}
.step-table tbody tr:hover .step-delete-btn { opacity: 1; }
.step-delete-btn:hover { 
  background: var(--status-fail-bg);
  color: var(--status-fail);
}

/* Natural language add row */
.step-add-row td {
  padding: 0;
}
.step-add-input-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border);
}
.step-add-icon {
  color: var(--accent);
  font-size: 16px;
  flex-shrink: 0;
}
.step-add-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 14px;
}
.step-add-input::placeholder { color: var(--text-muted); font-style: italic; }
.step-add-submit {
  background: var(--accent-glow);
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: 5px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--transition-fast);
}
.step-add-submit:hover {
  background: var(--accent);
  color: var(--text-on-accent);
}

/* Loading shimmer (while LLM processes) */
.step-add-shimmer {
  height: 18px;
  border-radius: 4px;
  background: linear-gradient(
    90deg,
    var(--bg-tertiary) 25%,
    var(--bg-hover) 50%,
    var(--bg-tertiary) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.2s ease infinite;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Step entry animation (newly added steps) */
@keyframes step-in {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.step-row--new { animation: step-in 250ms var(--transition-enter) both; }
```

### Result Badges

```css
.result-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
  border: 1px solid transparent;
}

.result-badge--passed {
  color: var(--status-pass);
  background: var(--status-pass-bg);
  border-color: var(--status-pass-border);
}

.result-badge--failed {
  color: var(--status-fail);
  background: var(--status-fail-bg);
  border-color: var(--status-fail-border);
}

.result-badge--running {
  color: var(--status-running);
  background: var(--status-running-bg);
  animation: badge-pulse 1.4s ease-in-out infinite;
}

@keyframes badge-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.result-badge--waiting {
  color: var(--status-waiting);
  background: transparent;
  border-color: transparent;
}
```

---

## Mode 2: REVIEW View

### Layout

```css
.review-view {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.review-topbar {
  /* extends .mode-topbar */
}

.review-content {
  padding: 32px 24px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.review-title {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
  line-height: 1.3;
}

.review-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 24px;
}
```

### Quality Badge

```css
.quality-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  cursor: default;
}
.quality-badge--good    { color: var(--status-pass); background: var(--status-pass-bg); }
.quality-badge--fair    { color: var(--status-running); background: var(--status-running-bg); }
.quality-badge--poor    { color: var(--status-fail); background: var(--status-fail-bg); }

/* Tooltip on hover */
.quality-badge[data-tooltip]:hover::after {
  content: attr(data-tooltip);
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-primary);
  max-width: 260px;
  white-space: normal;
  z-index: 100;
  box-shadow: 0 4px 16px hsla(0,0%,0%,0.4);
}
```

### Bottom Actions

```css
.review-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  margin-top: 8px;
}

.btn-back {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 9px 18px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-back:hover {
  border-color: var(--border-focus);
  color: var(--text-primary);
}
```

---

## Mode 3: RUNNING View

### Layout

```css
.running-view {
  display: flex;
  flex-direction: column;
}

.running-content {
  padding: 32px 24px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Accordions */
.accordion {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.accordion-header {
  background: var(--bg-secondary);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  user-select: none;
  border: none;
  width: 100%;
  text-align: left;
  transition: background var(--transition-fast);
}
.accordion-header:hover { background: var(--bg-hover); color: var(--text-primary); }
.accordion-header[aria-expanded="true"] { color: var(--text-primary); }

.accordion-arrow {
  transition: transform var(--transition-fast);
  font-size: 12px;
  color: var(--text-muted);
}
.accordion-header[aria-expanded="true"] .accordion-arrow {
  transform: rotate(90deg);
}

.accordion-body {
  padding: 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-primary);
}

/* Agent Reasoning content */
.agent-reasoning-text {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

/* Live Log (terminal-style) */
.live-log-terminal {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  background: hsl(250, 28%, 5%);
  color: var(--text-primary);
  padding: 12px 16px;
  border-radius: 4px;
  max-height: 320px;
  overflow-y: auto;
  line-height: 1.6;
}

/* Stop Test button */
.btn-stop {
  background: hsla(0, 75%, 58%, 0.1);
  border: 1px solid var(--status-fail-border);
  color: var(--status-fail);
  padding: 9px 18px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-stop:hover {
  background: var(--status-fail-bg);
}
```

---

## Mode 4: COMPLETE View

### Layout

```css
.complete-content {
  padding: 32px 24px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Summary row */
.step-summary {
  display: flex;
  gap: 20px;
  padding: 12px 0;
  font-size: 14px;
  color: var(--text-secondary);
}
.step-summary-item { display: flex; align-items: center; gap: 6px; }
.step-summary-count { font-weight: 700; font-size: 16px; }
.step-summary-count--pass  { color: var(--status-pass); }
.step-summary-count--fail  { color: var(--status-fail); }
.step-summary-count--skip  { color: var(--status-skip); }

/* Result actions */
.complete-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* Failure triage block */
.triage-block {
  border: 1px solid var(--status-fail-border);
  background: var(--status-fail-bg);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.triage-classification {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--status-fail);
  margin-bottom: 4px;
}
.triage-description {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}
.triage-guidance-input {
  width: 100%;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
  padding: 9px 12px;
  resize: vertical;
  min-height: 72px;
}
.triage-guidance-input:focus {
  border-color: var(--border-focus);
  outline: none;
  box-shadow: 0 0 0 3px var(--accent-glow);
}
```

---

## Buttons System

```css
/* Primary CTA — "Start Test" */
.btn-primary {
  background: var(--accent);
  border: none;
  color: var(--text-on-accent);
  padding: 10px 22px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all var(--transition-fast);
}
.btn-primary:hover { background: var(--accent-hover); transform: translateY(-1px); }
.btn-primary:active { transform: translateY(0); }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

/* Secondary */
.btn-secondary {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 9px 18px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.btn-secondary:hover { border-color: var(--border-focus); background: var(--bg-hover); }
```

---

## Mode Transitions

All mode transitions use a fade + translate animation:

```css
.mode-enter {
  animation: mode-in 300ms var(--transition-enter) both;
}
@keyframes mode-in {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

---

## Option Analysis

### Option A (Chosen): Shared StepTable + Deep Purple Shell
- **Pros**: One table component for all modes; deep purple is distinct from existing navy; all mode transitions handled via single `uiMode` state; modal overlays for HITL/PersonaCredential
- **Cons**: StepTable must handle 3 modes via props — careful typing required
- **Chosen**: Best separation of concerns; most reuse

### Option B: Separate components per mode, no shared table
- **Pros**: Simpler individual component logic
- **Cons**: Code duplication; harder to maintain consistent step row styling
- **Rejected**: DRY violation

### Option C: Keep existing top-tab navigation, add progressive panels
- **Pros**: Less structural change
- **Cons**: Conflicts with design direction (left nav rail); cramped side panel remains
- **Rejected**: Does not fulfill the design vision

---

## Responsive Summary

| Breakpoint | Nav | Content |
|---|---|---|
| > 1024px | 220px left rail (icon + label) | 900px max-width centered |
| 768–1024px | 64px icon-only rail (labels as tooltips) | Full width |
| < 768px | Bottom tab bar (4 icons) | Full width, smaller padding |

---

## Accessibility Checklist

- [ ] Left nav: `role="navigation"`, `aria-label="Main navigation"`, active link has `aria-current="page"`
- [ ] Nav links: `role="link"`, keyboard focusable
- [ ] Step table: `role="table"`, headers have `scope="col"`, `aria-label="Test steps"`
- [ ] Step rows: each editable row has `aria-label="Step N: [text]"` for screen readers
- [ ] Natural language input: `aria-label="Add a step in plain language"`, `aria-describedby` points to placeholder explanation
- [ ] Result badges: use `aria-label` not just emoji/icon (e.g., `aria-label="Passed"`, `aria-label="Running"`)
- [ ] Stop Test button: `aria-label="Stop the current test run"`
- [ ] Mode transitions: `aria-live="polite"` region wraps the main content area for mode announcements
- [ ] Accordions: `aria-expanded`, `aria-controls` linkage

---

## Micro-Animation Summary

| Element | Animation | Duration |
|---|---|---|
| Mode transition (any) | Fade + slide up | 300ms ease |
| New step added | Fade + slide down | 250ms spring |
| Step shimmer (loading) | Horizontal gradient sweep | 1.2s infinite |
| Result badge appear (passing) | Scale + fade in | 200ms ease |
| Result badge pulse (running) | Opacity pulse | 1.4s infinite |
| Nav active state change | Border + background | 150ms ease |
| Stop button hover | Background tint | 150ms ease |
| Primary button hover | translateY(-1px) | 150ms ease |
| Accordion open/close | Arrow rotate + height | 250ms ease |
