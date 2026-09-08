# Creative: User Journey — Playwright Standard Library Dashboard
## playwright-standard-library-integration-full-runtime-wiring | FEAT-052 | Phase: CREATIVE

**Design Date**: 2026-05-27  
**Designer**: Inline Orchestrator  
**Type**: User Journey Map

---

## Decision

**Chosen**: Option A — Single-Page Tabbed Dashboard with Progressive Context Reveal

The `/playwright` page uses a **two-tab layout** (Test Library | Storage Manager) inside the existing `Dashboard.tsx` tab bar. A vertical three-panel split (test browser → config panel → terminal) progressively reveals context as the user selects and launches tests. This mirrors how the existing Run Test tab works, making the mental model instantly familiar to vQA users.

---

## Persona Profiles

### Primary: QA Lead / Automation Engineer
- **Goal**: Run a specific Playwright test with a known env/user combination, watch it pass/fail in real time
- **Frustrations**: Tab-hopping between terminals; not knowing which auth sessions are expired
- **Mental model**: Test suite as a library, runtime as a terminal

### Secondary: DevOps / Release Manager
- **Goal**: Refresh all 13 user sessions before a release window
- **Frustrations**: Re-running auth scripts manually; no visibility into which sessions are expired
- **Mental model**: Session health grid, batch actions

---

## Journey Map: Primary Path (Run a Test)

### Stage 1: Discovery & Navigation
**Trigger**: User needs to verify a QA ticket against production playwright test library

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| 1 | Opens vQA dashboard | Dashboard loads at `/` (Run Test tab) | Neutral |
| 2 | Sees **"🎭 Playwright"** tab in header nav | Tab is visible, no badge | Curious |
| 3 | Clicks Playwright tab | Navigates to `/playwright`; page begins loading | Anticipating |
| 4 | Page renders | "Playwright Test Library" heading; 40 tests appear in left panel grouped by JIRA prefix | Oriented |

**Key UX moment**: The 40-test list must appear within 300ms of navigation (data is fetched from a cached index, not on-the-fly scanning).

---

### Stage 2: Test Discovery & Selection
**State**: Test Browser panel populated, no test selected

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| 5 | Scans QA group header | Collapsed group expands showing 25+ QA tests | Impressed by scope |
| 6 | Types `"321"` in search box | List filters to single result in real-time (< 100ms debounce) | Efficient |
| 7 | Clicks test card `qa-321-sorting...` | Card highlights with accent border; Configuration panel slides into view | Confident |
| 8 | Reads test metadata (JIRA keys, step count, description) | Metadata visible in card + expanded detail pane | Informed |

**Key UX moment**: Grouping by JIRA prefix (QA, VC2, Other) gives instant spatial orientation. The search should support all metadata fields (id, description, jira_keys).

---

### Stage 3: Configuration & Launch
**State**: Test selected, Configuration panel visible

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| 9 | Reviews pre-selected defaults (env=test, user=DemoSalesExec, browser=chromium) | Defaults match most common use case | Efficient |
| 10 | Changes env to `prod` | Dropdown updates; auth warning appears if `prod` sessions are expired | Alert |
| 11 | Clicks **"Run Test"** | Button enters loading state "🚀 Starting…"; `POST /playwright/run` fires | Excited |
| 12 | Receives `{run_id, status: "started"}` | Terminal panel slides in below config; "Test started — streaming output below" banner | Engaged |

**Key UX moment**: The auth session warning (amber badge) before launching in `prod` prevents surprise failures. It cross-references Storage Manager data.

---

### Stage 4: Real-Time Monitoring
**State**: Test running, terminal streaming

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| 13 | Watches terminal fill with Playwright output | Lines stream in real-time via WebSocket; ANSI color codes rendered | Engaged |
| 14 | Sees "✓ [chromium] › sorting › sort by name" lines | Green checkmarks for passing steps | Relieved |
| 15 | _(if failure)_ Sees red FAILED line | Red text; error details visible | Alert |
| 16 | Test completes | ✅ **PASSED** badge appears in terminal header (or ❌ FAILED with exit code) | Satisfied/Debugging |

**Key UX moment**: Last 500 lines windowed. If test emits 800 lines, oldest lines drop gracefully — the user can see "⚠ Older lines truncated (keeping last 500)" as a terminal header annotation.

---

### Stage 5: Post-Run Actions
**State**: Test complete, badge showing

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| 17 | (Pass) Closes test; wants to run next test | Clicks different card; config panel resets to defaults | Efficient |
| 18 | (Fail) Wants to investigate | Scrolls terminal; can copy line via click | Problem-solving |
| 19 | Wants to re-run same test with different env | Changes env dropdown; clicks Run again | Iterating |

---

## Journey Map: Secondary Path (Storage Manager)

### Stage A: Session Health Check
**Trigger**: Release prep; user suspects some sessions are expired

| Step | User Action | System Response | Emotion |
|------|------------|-----------------|---------|
| A1 | Clicks "Storage Manager" tab | 13×4 matrix loads | Oriented |
| A2 | Scans grid | Color-coded: 🟢 valid, 🟡 expired, 🔴 missing | Informed |
| A3 | Identifies `prod` column has 5 amber cells | Auth sessions older than 24h | Concerned |
| A4 | Clicks **"Refresh Auth"** for prod | Button spins "Generating…"; `POST /playwright/storage/generate` called | Action |
| A5 | Progress bar / status updates | "Generating storage states for prod: 7/13 users…" | Tracking |
| A6 | Completes | Banner "✅ Storage states regenerated for prod: 13/13 users"; grid refreshes | Relieved |

---

## Option Analysis

### Option A (Chosen): Single-Page Tabbed Dashboard with Progressive Panels
- **Pros**: Familiar vQA pattern; no context switching; progressive disclosure matches existing Run Test tab
- **Cons**: Three panels can feel cramped on 1200px-wide screens
- **Mitigation**: Collapsible test browser panel (min-width: 280px); terminal takes remaining space

### Option B: Separate Route with Full-Width Terminal
- **Pros**: Maximum terminal real estate
- **Cons**: Users lose the test browser context; difficult to re-run with config changes
- **Rejected**: Config panel and test browser disappear while test runs

### Option C: Modal-Based Test Launch
- **Pros**: Minimal routing changes
- **Cons**: Modal is too constrained for streaming terminal; poor accessibility
- **Rejected**: Not suitable for long-running test output

---

## UX Principles Applied

1. **Progressive Disclosure**: Config panel only appears after test selection; terminal only after launch
2. **Context Persistence**: Test browser stays visible during runs (shows which test is active)
3. **Error Prevention**: Auth session warnings prevent launches into expired sessions
4. **Recovery**: Re-run is a single click from completed state; config is preserved
5. **Feedback Loops**: Every state transition has immediate visual feedback (loading spinners, badge states, streaming text)

---

## Handoff Notes for Architecture & UI/UX

- The test browser panel must support **keyboard navigation** (arrow keys to cycle tests; Enter to select)
- The WebSocket connection for terminal streaming reuses the existing `useWebSocket` hook with a new `terminal_log` message handler
- Storage Manager grid loads data lazily (only when the user switches to that tab)
- The Playwright tab must be added to the existing `Dashboard.tsx` tab bar, NOT as a separate page — keeping the vQA header/auth context consistent
- All test run state (selected test, config, terminal lines) is **ephemeral** (in React component state only; no server-side persistence in Phase 1)
