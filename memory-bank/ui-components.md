# UI Components Library

> **Purpose**: Canonical index of reusable frontend components in `frontend/src/components/`.
> Reference this file when building new features to avoid duplication.
> Update whenever a new reusable component is introduced or significantly refactored.
>
> **Last updated**: 2026-05-29 (post TASK-065 UI/UX overhaul)

---

## Shell & Layout

### `Dashboard`
- **File**: `frontend/src/components/Dashboard.tsx`
- **Type**: Page-level container
- **Purpose**: Top-level app shell. Owns the three-tab layout (Run Test / Reports Archive / Analytics), global execution state, WebSocket lifecycle, and logout. All business logic flows through this component.
- **Key State**: `activeTab`, `isRunning`, `activeTriage`, `activeTakeover`, `activePersonaCredentials`, `pendingGuidance`
- **Hooks consumed**: `useExecution()`, `useWebSocket()`, `useAuth()`
- **Sub-components rendered**: `ExecutionPanel`, `ExecutionLog`, `CopilotSidebar`, `TakeoverPanel`, `PersonaCredentialPanel`, `TriagePanel`, `ReportsHistory`, `ReportsArchive`, `AnalyticsDashboard`, `HealthBadge`
- **Navigation tabs**:
  - `run` — Execution control + live monitoring
  - `archive` — Historical S3 reports browser
  - `analytics` — Aggregated pass rate / cost metrics
  - `/playwright` (route link) — Static Playwright test runner
- **Design Pattern**: Tab-based progressive disclosure — only one tab's content is rendered at a time
- **Added**: Pre-TASK-065 (existed as monolithic component); retained post-TASK-065 as primary shell

---

## Execution & Control

### `ExecutionPanel`
- **File**: `frontend/src/components/ExecutionPanel.tsx`
- **Type**: Feature component (large — 43 KB)
- **Purpose**: Primary test launch control. Handles Jira ticket selection, credential checks, role picker, URL/mode config, AC step preview + inline editing, pre-parse and pre-execute guidance inputs.
- **Props**:
  ```typescript
  onExecute: (request: ExecuteRequest) => void
  isLoading: boolean
  isRunning: boolean
  onCheckCredentials: (ticketId: string) => Promise<CredentialCheckResponse | null>
  rerunTicket?: { ticketId: string; role: string } | null
  pendingGuidance?: string
  onGuidanceConsumed?: () => void
  onNewRun?: () => void
  ```
- **Key UX Features**: Jira ticket dropdown with search + status/priority badges; credential completeness indicator; step preview editor with add/remove/edit; two-moment guidance system
- **Sub-components**: `CredentialPrompt` (inline partial-credential input)
- **Reuse guidance**: Do NOT add new execution config fields here without a corresponding backend field in `ExecuteRequest`. Keep guidance inputs decoupled from ticket selection.

### `CredentialPrompt`
- **File**: `frontend/src/components/CredentialPrompt.tsx`
- **Type**: Micro-component
- **Purpose**: Inline single-field credential form shown when a Jira ticket has partial credentials (email or password only). Displayed within `ExecutionPanel`.
- **Props**:
  ```typescript
  missingField: "email" | "password"
  foundEmail: string
  onChange: (value: string) => void
  value: string
  ```
- **Reuse guidance**: Standalone — can be dropped into any form that needs a single missing-credential prompt.

---

## Live Monitoring

### `ExecutionLog`
- **File**: `frontend/src/components/ExecutionLog.tsx`
- **Type**: Feature component
- **Purpose**: Real-time scrolling feed of agent actions. Displays step cards (action + reasoning + pass/fail), thinking animations, terminal summary messages, and WebSocket connection status.
- **Props**:
  ```typescript
  runId: string | null
  runLabel?: string | null
  steps: WSStepMessage[]
  terminalMessage: WSTerminalMessage | null
  connectionState: WSConnectionState
  isThinking: boolean
  thinkingText: string
  thinkingAcStep: number
  thinkingAcTotal: number
  ```
- **Sub-components**: `ThinkingCard`, StepCard (inline), TerminalCard (inline), ConnectionBadge (inline)
- **Behavior**: Auto-scrolls to latest step; shows "Cancel Test" button during active run.

### `CopilotSidebar`
- **File**: `frontend/src/components/CopilotSidebar.tsx`
- **Type**: Feature component (two render modes)
- **Purpose**: AC step progress tracker. Shows each step's status (pending → in_progress → passed/failed/skipped/awaiting_human) with a progress bar and per-step error messages. Provides Resume/Skip controls during human takeover.
- **Props**:
  ```typescript
  runId: string
  ticketId: string
  ws: WebSocket | null
  inline?: boolean   // true = full-width (default), false = narrow sidebar (legacy)
  onResumed?: () => void
  ```
- **WebSocket messages handled**: `ac_progress`, `copilot_ready`, `completed`, `failed`
- **Reuse guidance**: Always use `inline={true}` for new layouts. The narrow sidebar mode (`inline={false}`) is legacy and may be removed in a future cleanup.

### `ThinkingCard`
- **File**: `frontend/src/components/ThinkingCard.tsx`
- **Type**: Micro-component / animation
- **Purpose**: Animated display of agent reasoning text between execution steps. Features typewriter text reveal, pulsing brain emoji, and animated gradient border.
- **Props**:
  ```typescript
  text: string
  acStep: number
  acTotal: number
  isThinking: boolean
  ```
- **Reuse guidance**: Standalone — can be reused anywhere a "thinking" animation with text is needed.

### `LiveBrowser`
- **File**: `frontend/src/components/LiveBrowser.tsx`
- **Type**: Display component
- **Purpose**: Renders base64 PNG screenshots streamed from the agent. Three states: idle (placeholder), starting (spinner), running (live screenshot).
- **Props**:
  ```typescript
  latestScreenshot: string   // base64 PNG
  acStep: number
  acTotal: number
  isRunning: boolean
  ```
- **Status**: Superseded by `TakeoverPanel` when human intervention is active. May be re-surfaced if a "watch mode" panel is added.

---

## Human-in-the-Loop (HITL)

### `TakeoverPanel`
- **File**: `frontend/src/components/TakeoverPanel.tsx`
- **Type**: Feature component (complex — two sub-modes)
- **Purpose**: Full human takeover surface. Replaces `CopilotSidebar` when agent is stuck. Offers two intervention modes:
  - **Normal HITL**: Click to inject mouse/keyboard/scroll actions into the running browser
  - **Click-to-Teach**: Auto-capture element selector + write "why" text → save to Knowledge Base
- **Props**:
  ```typescript
  runId: string
  acStep: string
  acStepIndex: number
  errorMessage: string
  screenshotB64: string
  onDone: () => void
  ```
- **API calls**: `POST /run/{runId}/interact`, `POST /run/{runId}/teach/capture-click`, `POST /run/{runId}/teach`
- **Reuse guidance**: Do not extract sub-modes into separate components — the mode toggle (Normal / Click-to-Teach) is intentionally co-located for minimal UI surface.

### `PersonaCredentialPanel`
- **File**: `frontend/src/components/PersonaCredentialPanel.tsx`
- **Type**: HITL overlay component
- **Purpose**: Shown when the agent needs credentials for an unknown persona during execution. Operator provides email/password inline; dashboard posts them back to the backend to resume the run.
- **Props**: `message: WSPersonaCredentialsMessage`, `onSubmitted: () => void`, `onDismiss: () => void`

---

## Post-Run Analysis

### `TriagePanel`
- **File**: `frontend/src/components/TriagePanel.tsx`
- **Type**: Feature component
- **Purpose**: Failure analysis and re-run guidance. Shown after LLM triage arrives. Displays overall classification (Product Bug / Jira Unclear / Mixed), per-step breakdowns with confidence, executive summary, guidance input, and actions (Re-run / Post to Jira / Dismiss).
- **Props**:
  ```typescript
  triage: WSTriageMessage
  runId: string
  onRerun: (guidance: string) => void
  onDismiss: () => void
  ```
- **API calls**: `POST /run/{runId}/post-to-jira`
- **Reuse guidance**: Pattern should be reused for any post-run analysis panel — owns the guidance → re-run feedback loop.

---

## History & Reporting

### `ReportsHistory`
- **File**: `frontend/src/components/ReportsHistory.tsx`
- **Type**: Data display component
- **Purpose**: Compact recent-reports panel shown on the Run tab. Displays past runs from S3 with search + role filter; per-row actions: Open Report, Watch Video, Re-run.
- **Props**:
  ```typescript
  onRerun?: (ticketId: string, role: string) => void
  refreshTick?: number   // increment to reload; Dashboard increments after run completes
  ```
- **API**: `GET /reports`

### `ReportsArchive`
- **File**: `frontend/src/components/ReportsArchive.tsx`
- **Type**: Feature component (two view modes)
- **Purpose**: Full-width archive browser on the Archive tab. Two view modes:
  - **Grouped by Ticket** — collapsible ticket cards with role dot indicators and run counts
  - **Timeline** — chronological run rows
- **Props**: `onRerun?: (ticketId: string, role: string) => void`
- **API**: `GET /reports`

---

## Analytics

### `AnalyticsDashboard`
- **File**: `frontend/src/components/AnalyticsDashboard.tsx`
- **Type**: Standalone analytics component
- **Purpose**: Aggregated test metrics over selectable time windows (7/14/30/90 days). Features pass rate ring, stat cards, most-tested tickets table, and recent runs list.
- **Props**: None (standalone; fetches its own data)
- **API**: `GET /runs/analytics?days={days}`, `GET /runs/history?limit=20`
- **Implementation note**: Uses pure SVG for the circular progress ring — no charting library dependency. Preserve this constraint.

---

## Utility Components

### `ErrorBoundary`
- **File**: `frontend/src/components/ErrorBoundary.tsx`
- **Type**: React class component (error boundary)
- **Purpose**: Catches render errors in child subtrees; renders a fallback UI with an `onReset` callback. Used in `Dashboard` to wrap each tab's content tree.
- **Props**: `onReset: () => void`, `children: ReactNode`
- **Reuse guidance**: Wrap any independently-resettable section of the UI in an `ErrorBoundary`.

### `HealthBadge` (inline in Dashboard)
- **Location**: `frontend/src/components/Dashboard.tsx` (bottom of file, not exported)
- **Purpose**: Displays backend health status (All Systems Go / Degraded / Connecting). Color-coded by status.
- **Note**: Currently co-located in `Dashboard.tsx`. If needed elsewhere, extract to its own file.

---

## Pages (Route-Level Wrappers)

These are thin page shells in `frontend/src/pages/` that wrap components for routing purposes.

| Page | Route | Wraps |
|------|-------|-------|
| `HomePage` | `/` | `Dashboard` |
| `LoginPage` | `/login` | Auth login form |
| `MfaPage` | `/mfa` | TOTP/SMS challenge |
| `ProtectedPage` | `/protected` | Debug/session info |
| `PlaywrightPage` | `/playwright` | Static Playwright test runner |

---

## Design Tokens & Conventions

- **CSS Variables**: Defined in `frontend/src/index.css`. All components consume `var(--accent)`, `var(--bg-primary)`, `var(--border)`, `var(--text-primary)`, etc. — never use hardcoded hex colors.
- **Transitions**: Use `var(--transition-fast)` (150ms) for hover states, `var(--transition-base)` (300ms) for panel animations.
- **Purple palette**: `--accent: #7c3aed` is the primary brand color. All interactive elements should derive from this.
- **Tab isolation**: Each tab renders its own `ErrorBoundary` so one tab crash does not take down the others.

---

## Adding a New Component

1. Create the `.tsx` file in `frontend/src/components/`
2. Add an entry to this file under the appropriate section
3. If it introduces a new design pattern, add a pattern entry to `memory-bank/systemPatterns.md`
4. If it introduces new API calls, update `memory-bank/c4/components/c4-component-react-dashboard.md` (REST/WebSocket tables)
