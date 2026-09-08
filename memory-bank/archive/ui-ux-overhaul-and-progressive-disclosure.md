# ui-ux-overhaul-and-progressive-disclosure: UI/UX Overhaul & Progressive Disclosure

**Status**: REFLECTION_COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 3
**Roadmap Link**: FEAT-050
**Branch**: feature/FEAT-050-ui-ux-overhaul
**Created**: 2026-05-28
**Updated**: 2026-05-29 (rev 6: Reflection complete)

---

## Design Direction

### What We're Building Toward

The inspiration screenshots show a professional test management tool (Qase-style). The core visual patterns to adopt:

1. **Narrow left nav rail** — icon + label, vertically stacked, always visible
2. **Large centered main content area** — test runs feel like a document, not a form
3. **Table-based test step display** — steps shown as structured rows (Step # | Description | Expected | Result badge) rather than a raw scrolling log
4. **Prominent test title** — the ticket summary is an H1 heading when a run is active, not a small chip
5. **Deep dark purple aesthetic** — richer than current navy (`hsl(250, 30%, 8%)` base), purple accent instead of indigo
6. **Clean status badges** — ✅ Passed / ❌ Failed / ⏳ Running — large, readable, color-coded

### What the Current UI Gets Wrong

| Problem | Today | After This Feature |
|---------|-------|-------------------|
| Config panel is cramped | 380px left sidebar with a dense form | Form lives in the centered main area, full-width card |
| Steps buried in a log | Raw terminal-style `ExecutionLog` | Structured table with step rows + status badges |
| No visible test title | Small chip in the sidebar | Large H1 heading in the main area |
| Tabs at the top | Horizontal tab bar in the header | Vertical left nav rail — always present |
| Developer jargon everywhere | "Execution Mode", "User Role", "HITL" | "Run Mode", "Test As", "Manual Control" |
| Everything visible at once | AC steps + log + config shown simultaneously | Progressive: show only what's relevant to the current moment |

---

## Layout Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  ┌──────────┐  ┌────────────────────────────────────────────────┐│
│  │          │  │  ← breadcrumb / test title bar                 ││
│  │  🔬 vQA  │  ├────────────────────────────────────────────────┤│
│  │          │  │                                                 ││
│  │  ▶ Run   │  │        MAIN CONTENT AREA                        ││
│  │          │  │        max-width: 900px, centered               ││
│  │  📋 Hist │  │                                                 ││
│  │          │  │   [content changes based on current mode]       ││
│  │  📊 Ana  │  │                                                 ││
│  │          │  │                                                 ││
│  │  🎭 Play │  │                                                 ││
│  │          │  │                                                 ││
│  │  ───────  │  │                                                 ││
│  │  ● Sys   │  │                                                 ││
│  │  Logout  │  │                                                 ││
│  └──────────┘  └────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### Dimensions
- **Left nav rail**: 220px (with labels) / 64px icon-only below 1024px
- **Main content area**: takes remaining width, scrolls independently
- **Content inner max-width**: 900px, `margin: 0 auto`
- **Top bar** (inside main): breadcrumb + action buttons (e.g., Stop Test)

---

## Color System Update

The current navy palette shifts to a deeper purple to match the inspiration aesthetic:

```css
/* NEW design tokens (replaces current --bg-primary etc.) */
--bg-primary:   hsl(250, 28%, 7%);    /* Deep purple-black */
--bg-secondary: hsl(248, 22%, 11%);   /* Panel background */
--bg-tertiary:  hsl(246, 18%, 16%);   /* Card/input background */
--bg-hover:     hsl(246, 18%, 19%);

--border:       hsl(246, 15%, 22%);
--border-focus: hsl(262, 80%, 65%);   /* Purple focus */

--accent:       hsl(262, 80%, 65%);   /* Purple accent (replaces indigo) */
--accent-glow:  hsla(262, 80%, 65%, 0.2);

/* Status badges — bolder, more legible */
--status-pass:     hsl(152, 60%, 45%);
--status-pass-bg:  hsla(152, 60%, 45%, 0.12);
--status-pass-border: hsla(152, 60%, 45%, 0.3);
--status-fail:     hsl(0, 75%, 58%);
--status-fail-bg:  hsla(0, 75%, 58%, 0.12);
--status-fail-border: hsla(0, 75%, 58%, 0.3);
--status-running:  hsl(38, 90%, 55%);
--status-skip:     hsl(215, 16%, 50%);
```

---

## UI Modes — "Run a Test" View

### Mode 1: SELECT — "Start a New Test"

The main content area shows a single centered card:

```
┌────────────────────────────────────────────────────┐
│  Start a New Test                                   │
│                                                     │
│  Jira Ticket                                        │
│  [ 🔍 Search by ticket ID or title...           ▼ ] │
│                                                     │
│  Test As                    Environment             │
│  [ Account Executive    ▼ ] [ Staging           ▼ ] │
│                                                     │
│  ▸ Advanced Settings                                │
│                                                     │
│  [ ▶ Start Test ]                                   │
└────────────────────────────────────────────────────┘
```

- Ticket search auto-triggers step preview on selection — no separate "Preview" button click needed
- "Advanced Settings" is a `<details>` accordion — hidden by default, contains: Custom Credentials, Run Mode (Interactive/Fast), Failed Login Testing, Guidance textarea
- Two-column grid for dropdowns on wider viewports, stacks on mobile

### Mode 2: REVIEW — "Review Your Test Steps"

Triggered automatically after AC preview loads. Full-width in the main area.

#### Natural Language Step Input (Primary Interaction)

Product people don't think in structured test steps — they think in notes. The primary input in REVIEW mode is a **free-text "anything" field** at the bottom of the step list. The user types whatever comes to mind naturally, hits Enter (or clicks ✦ Add), and the LLM converts it into one or more properly structured steps and inserts them into the table.

**Examples of what a PM might type:**

| PM types... | LLM produces... |
|------------|----------------|
| `"also check the error message says the right file size limit"` | Step: "Verify the error message displays the maximum allowed file size" |
| `"make sure they can't upload again after a failure"` | Step: "Verify the upload button is disabled or the form resets after a failed upload attempt" |
| `"test that it works for both jpg and pdf"` | Two steps: "Select an oversized JPG file" + "Select an oversized PDF file" |
| `"basically just redo step 2 but with a different file type"` | New step inserted after step 2: "Locate the upload field and select a different file type..." |

The field should feel like a **chat input or sticky note** — not a form field. Placeholder text should reinforce this: `"Add anything — 'also check the error message' or 'what if they try a PDF?'"`.

#### Layout

```
Top bar:
  ← VC2-7612 · Account Executive · Staging    [● GOOD — 8/10]  [▶ Start Test]

Content:
  [H1] Upload file exceeding size limit
  VC2-7612 · Account Executive · Staging

  ┌──────────────────────────────────────────────────────────┐
  │  #   Test Step                        Source             │
  ├──────────────────────────────────────────────────────────┤
  │  1   Navigate to the file upload page ⟠ Jira  ⋮⋮  ✕     │
  │  2   Locate the file upload field     ⟠ Jira  ⋮⋮  ✕     │
  │  3   Select a file larger than limit  ⟠ Jira  ⋮⋮  ✕     │
  ├──────────────────────────────────────────────────────────┤
  │  ✦  Add anything — "also check the error message"  [↵]  │
  └──────────────────────────────────────────────────────────┘

  [← Change Ticket]                         [▶ Start Test]
```

#### Interaction Details

- **Free-text input row** is always visible at the bottom of the table — it is the primary CTA, not a secondary button
- Pressing `Enter` (or `Shift+Enter` to add a newline) submits the input to the existing `/preview-steps` endpoint with `pre_parse_guidance` carrying the typed text — the LLM returns new step(s) which animate into the table
- A **loading shimmer** appears in the input row while the LLM processes — step(s) then fade in at the bottom of the list
- If the input produces **multiple steps**, a subtle "✦ 2 steps added" toast confirms what happened
- Newly added steps are tagged `✚ You` in the Source column so the user can see what they contributed
- **Inline editing**: clicking any existing step text turns it into an editable field — user edits, blur/Enter saves. No "edit mode" toggle needed.
- **Drag to reorder**: drag handle (⋮⋮) visible on hover — drag a row to change order
- **Delete**: ✕ on hover — removes a step with a brief fade-out animation
- AC quality badge in the top bar: GOOD (green) / FAIR (amber) / POOR (red) with a short plain-English explanation on hover

### Mode 3: RUNNING — "Test in Progress"

The main area becomes a live test execution view, inspired directly by the inspiration screenshots:

```
Top bar:
  VC2-7612 · Account Executive · Staging     [● EXECUTING]    [■ Stop Test]

Content:
  [H1] Upload file exceeding size limit
  Started 2:47 PM · Staging · Account Executive

  ┌──────────────────────────────────────────────────────────────────┐
  │  #   Action                    Expectation             Result     │
  ├──────────────────────────────────────────────────────────────────┤
  │  1   Navigate to upload page   Page loads successfully  ✅ Passed │
  │  2   Locate upload field       Field is visible         ✅ Passed │
  │  3   Select oversized file     File is selected         ⏳ Running│
  │  4   Attempt to upload         Upload process starts    ─ Waiting │
  │  5   Verify error message      Error message visible    ─ Waiting │
  └──────────────────────────────────────────────────────────────────┘

  Agent Reasoning (collapsible)  ▸
  ───────────────────────────────
  Live log (collapsible, collapsed by default)  ▸
```

- **Table** replaces the raw `ExecutionLog` as the primary view — each AC step is a row
- `Result` column updates in real-time as the agent progresses
- ✅ Passed (green badge), ❌ Failed (red badge), ⏳ Running (amber pulse), ─ Waiting (dim)
- **Agent Reasoning** accordion — expands to show Claude's thinking for the current step (maps to `thinkingText`)
- **Live Log** accordion — the raw `ExecutionLog` terminal output, collapsed by default (power users can expand)
- **"Stop Test"** button in the top-right — prominent, red-tinted
- HITL: when `humanTakeoverMessage` arrives, a modal overlay covers the table with the takeover panel

### Mode 4: COMPLETE — "Test Results"

```
Top bar:
  VC2-7612 · Account Executive · Staging     [✅ PASSED · 2m 34s]  [📋 View Report]

Content:
  [H1] Upload file exceeding size limit

  ┌──────────────────────────────────────────────────────────────────┐
  │  #   Action                    Expectation             Result     │
  ├──────────────────────────────────────────────────────────────────┤
  │  1   Navigate to upload page   Page loads successfully  ✅ Passed │
  │  2   Locate upload field       Field is visible         ✅ Passed │
  │  3   Select oversized file     File is selected         ✅ Passed │
  │  4   Attempt to upload         Upload process starts    ✅ Passed │
  │  5   Verify error message      Error message visible    ❌ Failed │
  │  6   Verify error text         Correct limit shown      ❌ Failed │
  └──────────────────────────────────────────────────────────────────┘

  Summary: 4 passed · 2 failed · 0 skipped

  [↩ Run Again]    [📋 View Full Report]    [📎 Copy Report Link]

  ── If failed: Failure Analysis (inline) ──────────────────────────
  Classification: Product Bug
  Step 5 failed because the error message text did not match…
  [Guidance input + Re-run with Guidance button]
```

- The step table remains visible — now fully complete with all result badges populated
- Summary row below the table: "N passed · N failed · N skipped"
- Three actions: Run Again (resets to SELECT, pre-fills ticket) | View Full Report (S3 link) | Copy Link
- Triage content renders **inline** below — not a floating overlay
- No `ReportsHistory` auto-revealed; user navigates to "Test History" via left nav

---

## Left Navigation Rail

```tsx
<nav className="app-nav">
  <div className="app-nav-brand">
    <span className="app-nav-logo">🔬</span>
    <span className="app-nav-name">vQA</span>
  </div>

  <ul className="app-nav-links">
    <NavLink icon="▶" label="Run a Test" to="/" />
    <NavLink icon="📋" label="Test History" to="/history" />
    <NavLink icon="📊" label="Analytics" to="/analytics" />
    <NavLink icon="🎭" label="Playwright Suite" to="/playwright" />
  </ul>

  <div className="app-nav-footer">
    <div className="nav-health">
      <span className={`health-dot health-dot--${status}`} />
      <span className="nav-health-label">All Systems Go</span>
    </div>
    <button className="nav-logout-btn">Logout</button>
  </div>
</nav>
```

### Active State
- Active link: `2px left border` in `var(--accent)` + subtle background `var(--accent-glow)` + text `var(--text-primary)`
- Inactive: `var(--text-secondary)`, no background

### Collapse Behavior
- `> 1024px`: 220px wide, shows icon + label
- `768px–1024px`: 64px wide, icon only (labels appear as tooltips)
- `< 768px`: hidden — replaced by a bottom tab bar (4 icons)

---

## PM-First Language Reference

| Current (Dev-Facing) | New (PM-Facing) |
|----------------------|-----------------|
| User Role | Test As |
| Target URL | Environment |
| Execution Mode | Run Mode (in Advanced Settings) |
| Interactive | Live View |
| Headless | Fast Mode |
| Confirm & Execute | Start Test |
| Preview Steps | Review Test Steps |
| HITL Takeover | Manual Control Needed |
| Coverage Gap | Step Skipped |
| Run ID | (hidden from main UI) |
| AC Steps | Test Steps |
| Reports Archive | Test History |
| Context for AI Agent | Notes for the Agent (in Advanced) |

---

## Acceptance Criteria

- [ ] **AC-ENTRY-1**: Left nav rail visible on all pages with 4 items: "Run a Test" (default active), "Test History", "Analytics", "Playwright Suite"
- [ ] **AC-ENTRY-2**: On initial load, main area shows SELECT mode: centered card with Jira ticket search, "Test As" dropdown, "Environment" dropdown, collapsed "Advanced Settings"
- [ ] **AC-ENTRY-3**: "Advanced Settings" accordion hides: Custom Credentials, Run Mode toggle, Failed Login Testing checkbox, Guidance textarea — all collapsed by default
- [ ] **AC-HAPPY-1**: Selecting a Jira ticket auto-triggers AC parsing, transitions to REVIEW mode showing the step table
- [ ] **AC-HAPPY-2**: REVIEW mode shows ticket title as H1, step table with editable rows, AC quality badge, "Start Test" CTA in top bar
- [ ] **AC-HAPPY-3**: Clicking "Start Test" transitions to RUNNING mode; main area shows step table with live status badges; raw log is collapsed
- [ ] **AC-HAPPY-4**: Step result badges update in real-time: ✅ Passed, ❌ Failed, ⏳ Running (animated), ─ Waiting
- [ ] **AC-HAPPY-5**: On completion, COMPLETE mode shows fully populated step table + summary row + "View Full Report" and "Run Again" actions
- [ ] **AC-HAPPY-6**: Clicking "Test History" navigates to `ReportsArchive` rendered in the main content area
- [ ] **AC-EDGE-1**: HITL takeover appears as a modal overlay on the step table (not replacing the layout)
- [ ] **AC-EDGE-2**: PersonaCredentialPanel appears as modal overlay
- [ ] **AC-EDGE-3**: Failed run → Triage content renders inline below the step table in COMPLETE mode
- [ ] **AC-EDGE-4**: Clicking another nav item during a run shows a confirmation dialog: "A test is currently running. Are you sure you want to leave?"
- [ ] **AC-NFR-1**: All mode transitions use CSS animation (300ms, `--transition-smooth`)
- [ ] **AC-NFR-2**: No new npm dependencies
- [ ] **AC-NFR-3**: Responsive: nav collapses to icon-only at 1024px, bottom tabs at 768px
- [ ] **AC-NFR-4**: Color tokens updated to deep purple palette per spec

---

## Implementation Plan

### Phase 1: Design Token Update (`index.css`)

Update CSS custom properties:
- `--bg-primary` → `hsl(250, 28%, 7%)` (deeper purple-black)
- `--accent` → `hsl(262, 80%, 65%)` (purple, away from indigo)
- Add `--status-pass`, `--status-fail`, `--status-running`, `--status-skip` tokens
- Add `.status-badge` utility class family

### Phase 2: App Shell + Left Nav

New files:
- `frontend/src/components/AppShell.tsx` — grid layout with `<AppNav>` + `<main>`
- `frontend/src/components/AppNav.tsx` — left rail with nav links, health, logout

Modify:
- `frontend/src/router.tsx` — wrap all protected routes in `AppShell`
- Remove header nav tabs from `Dashboard.tsx`

CSS additions:
- `.app-shell`, `.app-nav`, `.app-nav-link`, `.app-nav-link.active`, `.app-nav-footer`
- Responsive collapse media queries

### Phase 3: RunTestView + Mode State Machine

New file: `frontend/src/components/RunTestView.tsx`
- Owns `uiMode: 'select' | 'review' | 'running' | 'complete'`
- Moves execution logic from `Dashboard.tsx` here
- Renders `<SelectView>`, `<ReviewView>`, `<RunningView>`, `<CompleteView>` conditionally

### Phase 4: SelectView

New file: `frontend/src/components/SelectView.tsx`
- Centered card, max-width 560px
- Ticket combobox (full-width)
- "Test As" + "Environment" two-column row
- `<details>` Advanced Settings with all power-user controls
- Auto-triggers preview on ticket selection

### Phase 5: Step Table Component

New file: `frontend/src/components/StepTable.tsx`
- Reused across REVIEW, RUNNING, COMPLETE modes
- Props: `steps[]`, `mode: 'review' | 'running' | 'complete'`, `onEdit?`, `onReorder?`
- In REVIEW: editable cells, drag handles, delete buttons
- In RUNNING: read-only, `result` column shows live badges
- In COMPLETE: read-only, all results populated

```tsx
interface StepRow {
  index: number;
  text: string;
  source: 'jira' | 'user_added';
  result?: 'passed' | 'failed' | 'running' | 'skipped' | 'waiting';
  reasoning?: string;
}
```

### Phase 6: ReviewView, RunningView, CompleteView

- **ReviewView** (`ReviewView.tsx`): `StepTable` in review mode + top bar with quality badge + "Start Test" CTA
- **RunningView** (`RunningView.tsx`): `StepTable` in running mode + Agent Reasoning accordion + collapsed Live Log accordion
- **CompleteView** (`CompleteView.tsx`): `StepTable` in complete mode + summary row + actions + inline triage

### Phase 7: Wire Step Results to WebSocket

In `RunningView`, subscribe to `steps` from `useWebSocket()` and map to `StepRow.result`:
- WebSocket step messages contain `ac_step_index` and `status` — use these to update the step table in real-time
- `thinkingText` / `thinkingAcStep` → drive the Agent Reasoning accordion

---

## Files Affected

### New Files
| File | Purpose |
|------|---------|
| `frontend/src/components/AppShell.tsx` | Top-level layout shell |
| `frontend/src/components/AppNav.tsx` | Left navigation rail |
| `frontend/src/components/RunTestView.tsx` | "Run a Test" page with mode state machine |
| `frontend/src/components/SelectView.tsx` | SELECT mode — centered ticket picker card |
| `frontend/src/components/ReviewView.tsx` | REVIEW mode — step table + confirm |
| `frontend/src/components/RunningView.tsx` | RUNNING mode — live step table |
| `frontend/src/components/CompleteView.tsx` | COMPLETE mode — results + triage |
| `frontend/src/components/StepTable.tsx` | Shared step table (review/running/complete modes) |
| `frontend/src/components/TestHistoryView.tsx` | Thin wrapper: ReportsArchive in new shell |

### Modified Files
| File | Change |
|------|--------|
| `frontend/src/router.tsx` | Wrap routes in AppShell; add `/history` route |
| `frontend/src/index.css` | New color tokens + app shell layout + nav + step table styles |
| `frontend/src/components/Dashboard.tsx` | Strip down or remove — logic migrates to RunTestView |
| `frontend/src/components/ExecutionPanel.tsx` | Extract form logic to SelectView; keep hooks/state |

### Preserved (Behavior Unchanged)
- All auth components (`src/auth/`)
- `ExecutionLog.tsx` (used inside collapsed accordion in RunningView)
- `CopilotSidebar.tsx` (may be phased into StepTable inline)
- `TakeoverPanel.tsx` (modal overlay, unchanged)
- `PersonaCredentialPanel.tsx` (modal overlay, unchanged)
- `ReportsArchive.tsx`, `AnalyticsDashboard.tsx`
- All hooks: `useExecution`, `useWebSocket`

---

## Test Strategy

### Manual Verification (UAT)
1. Load app → left nav visible, SELECT mode shown in centered main area
2. Open "Advanced Settings" → see power-user options; collapse → hidden
3. Select a ticket → transitions to REVIEW mode, step table visible, ticket title as H1
4. Start test → RUNNING mode, step table with live badges updating
5. Watch ⏳ Running badge animate, ✅ Passed badges appear row by row
6. Expand "Agent Reasoning" accordion → see Claude's current thinking
7. Run completes → COMPLETE mode, summary row, "View Full Report" button
8. Failed run → triage inline below step table
9. "Test History" nav → ReportsArchive in main area
10. Resize window → nav collapses appropriately

### Regression Checks
- Auth / login flow unchanged
- Playwright Library route (`/playwright`) unchanged
- WebSocket step streaming works
- HITL takeover modal appears over step table
- PersonaCredentialPanel modal works
- Batch mode unaffected (backend only)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE
**Current Step**: Step 5 - Report Completion - COMPLETE
**Step Started**: 2026-05-29T14:30:00-05:00
**Can Resume**: NO
**Worktree**: .worktrees/FEAT-050

### Implementation Roadmap
- [x] Phase 1: Design Token Update (`index.css`) — COMPLETE
- [x] Phase 2: App Shell + Left Nav — COMPLETE
- [x] Phase 3: RunTestView + Mode State Machine — COMPLETE
- [x] Phase 4: SelectView — COMPLETE
- [x] Phase 5: Step Table Component — COMPLETE
- [x] Phase 6: ReviewView, RunningView, CompleteView — COMPLETE
- [x] Phase 7: Wire Step Results to WebSocket — COMPLETE

### Active Sub-Agents
- User Journey Design: COMPLETE, Agent ID: inline-orchestrator
- UI/UX Design: COMPLETE, Agent ID: inline-orchestrator

### Completed Steps
- User Journey Creative Design: COMPLETE (2026-05-28T21:07:00-05:00) - Output: memory-bank/creative/ui-ux-overhaul-and-progressive-disclosure-ui-overhaul-user-journey.md
- UI/UX Creative Design: COMPLETE (2026-05-28T21:09:00-05:00) - Output: memory-bank/creative/ui-ux-overhaul-and-progressive-disclosure-ui-overhaul-uiux.md
- Phase 1 Build (Design Tokens + CSS): COMPLETE (2026-05-28T16:20:00-05:00) - Build PASS, Lint pre-existing errors only
- Phase 2 Build (App Shell + Left Nav): COMPLETE (2026-05-28T21:28:00-05:00) - 31/31 tests PASS, Build PASS, 0 new lint errors
  - New: AppNav.tsx, AppShell.tsx (+ 12 tests each)
  - Modified: router.tsx (wrapped routes in AppShell, added /history, /analytics routes)
  - CSS: AppShell + AppNav styles appended to index.css
- Phase 3 Build (RunTestView + Mode State Machine): COMPLETE (2026-05-29T10:30:00-05:00) - Build PASS, Logic migrated from Dashboard.tsx
  - New: RunTestView.tsx (state machine + placeholders)
  - Modified: HomePage.tsx (switched to RunTestView)
  - CSS: Added .run-test-view and transition styles
- Phase 4 Build (SelectView): COMPLETE (2026-05-29T11:15:00-05:00) - Build PASS, Centered card design
  - New: SelectView.tsx (ticket pick, configuration grid, advanced settings details)
  - CSS: Added .select-card, .form-grid-2, .advanced-settings styles
- Phase 5 Build (Step Table Component): COMPLETE (2026-05-29T11:45:00-05:00) - Build PASS, Reusable component
  - New: StepTable.tsx (review/running/complete modes, drag-drop, inline edit)
  - CSS: Added .step-table, .status-badge, .quick-add-form styles
