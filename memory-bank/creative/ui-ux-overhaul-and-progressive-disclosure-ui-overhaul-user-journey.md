# Creative: User Journey — UI/UX Overhaul & Progressive Disclosure
## ui-ux-overhaul-and-progressive-disclosure | FEAT-050 | Phase: CREATIVE

**Design Date**: 2026-05-28
**Designer**: Inline Orchestrator
**Type**: User Journey Map

---

## Decision

**Chosen**: Option A — Mode-Centric Progressive Disclosure with Left Nav Rail

The vQA UI adopts a **4-mode state machine** (SELECT → REVIEW → RUNNING → COMPLETE) rendered in a persistent shell. The left nav rail replaces the top tab bar. Each mode is a distinct "moment" that shows the user only what matters right now — reducing cognitive load at every stage.

---

## Persona Profiles

### Primary: Product Manager / QA Analyst
- **Goal**: Validate a Jira ticket's AC against a live environment without needing engineering help
- **Frustrations**: Doesn't understand terms like "Execution Mode", "HITL", "Run ID"; gets lost in dense config forms
- **Mental model**: "I pick a ticket, review the steps, hit Start, and watch it go."
- **Success signal**: Test passes or fails with a clear explanation; result is shareable

### Secondary: QA Lead / Automation Engineer
- **Goal**: Run tests with specific configurations; inspect agent reasoning; triage failures at the step level
- **Frustrations**: Cannot quickly jump between advanced config and the live execution view; raw terminal log is hard to parse for step-level failures
- **Mental model**: "I want structured step rows, not terminal noise."
- **Success signal**: Step table shows exactly which AC step failed and why; guidance input lets me re-run immediately

### Tertiary: DevOps / Developer
- **Goal**: Debug a specific step failure; access raw execution logs; understand agent reasoning
- **Frustrations**: Agent reasoning (thinking text) is hidden; raw log is buried
- **Mental model**: "Give me all the data, but don't drown me in it by default."
- **Success signal**: Raw log and Agent Reasoning are one click away, not visible by default

---

## Journey Map: Primary Path (PM Validates a Ticket)

### Stage 1: Entry — Initial Load
**Trigger**: PM wants to validate VC2-7612 "Upload file exceeding size limit" on Staging

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 1 | Opens vQA URL | App loads; left nav rail shows 4 items; main area shows SELECT mode centered card | Oriented |
| 2 | Sees "Start a New Test" card | Clean card: ticket search, "Test As" dropdown, "Environment" dropdown, collapsed "Advanced Settings" | Confident |
| 3 | Reads "Test As" label (not "User Role") | Understands: this is who they're testing as | Clear |
| 4 | Reads "Environment" label (not "Target URL") | Understands: pick your environment | Clear |

**Key UX moment**: First impression must communicate "this is easy". The SELECT card must feel like a search form, not a developer config panel. PM-first language is the primary differentiator here.

---

### Stage 2: Ticket Selection
**State**: SELECT mode, card visible

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 5 | Types "VC2-7612" in ticket search | Combobox autocompletes with matching Jira ticket titles | Efficient |
| 6 | Selects "VC2-7612 — Upload file exceeding size limit" | Ticket is confirmed; AC parsing begins automatically (no extra button click) | Smooth |
| 7 | Selects "Account Executive" from "Test As" | Dropdown updates | Easy |
| 8 | Leaves "Environment" as "Staging" (default) | No change needed | Fast |
| 9 | _(optionally)_ Clicks "▸ Advanced Settings" | Accordion expands showing: Custom Credentials, Run Mode toggle, Failed Login Testing, Guidance textarea | Empowered |
| 10 | Leaves Advanced Settings collapsed | Nothing changes; defaults are sensible | Confident |

**Key UX moment**: Auto-trigger on ticket selection (no "Preview" button click) reduces a step that confused PMs. The system transitions immediately after a valid ticket is chosen.

---

### Stage 3: Step Review (REVIEW mode)
**State**: Transitioned automatically from SELECT after AC parsing completes

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 11 | Sees REVIEW mode with step table | H1 shows "Upload file exceeding size limit"; breadcrumb shows "VC2-7612 · Account Executive · Staging"; step table populated with 8 rows | Informed |
| 12 | Reads step 3: "Select a file larger than the limit" | Step text is clear and plain English | Confident |
| 13 | Notices quality badge: "● GOOD — 8/10" in top bar | Hovers to see "Steps cover the main flow; consider adding an edge case for concurrent uploads" | Aware |
| 14 | Thinks: "I should add a step about the error message text" | Sees the sticky input row at bottom: `✦ Add anything — 'also check the error message'` | Invited |
| 15 | Types: "make sure the error message shows the correct file size limit" | Presses Enter; loading shimmer appears in input row | In progress |
| 16 | LLM returns a new step | "Verify the error message displays the maximum allowed file size" animates into the table tagged `✚ You` | Delighted |
| 17 | Notices step 3 text is slightly off; clicks on it | Step cell becomes editable inline; cursor placed at end | In control |
| 18 | Edits text, presses Enter | Cell reverts to display mode; step updated | Seamless |
| 19 | Satisfied with the 9-step list | Clicks "▶ Start Test" in the top bar | Ready |

**Key UX moment**: The natural-language input at the bottom of the step table is the single most important PM-facing interaction in REVIEW mode. It must feel like a sticky note or chat prompt, not a form field. The `✚ You` source tag shows the PM their contribution is reflected.

---

### Stage 4: Live Execution (RUNNING mode)
**State**: Test started; main area shows step table with live status badges

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 20 | Sees RUNNING mode | Status badge in top bar: "● EXECUTING"; step table visible with rows 1–9; "Stop Test" button prominent | Engaged |
| 21 | Watches step 1 badge turn ✅ Passed | Badge animates in (scale from 0.8 + fade); next step shows ⏳ Running | Tracking |
| 22 | Steps 2, 3 complete → ✅ | Step rows lock as passed; row 4 starts ⏳ | Confident |
| 23 | Clicks "▸ Agent Reasoning" accordion | Expands to show Claude's thinking for current step: "Locating the file upload field using the label text..." | Curious |
| 24 | Collapses Agent Reasoning | Accordion collapses; step table is primary again | Back to watching |
| 25 | _(power user)_ Clicks "▸ Live Log" accordion | Raw ExecutionLog terminal text appears | Deep detail |
| 26 | All 9 steps complete | RUNNING mode transitions to COMPLETE mode | Satisfied |

**Key UX moment**: The ⏳ Running animation (amber pulse) on the current step provides a heartbeat signal — the user knows the test is alive and processing. Without this, silence feels like a crash.

---

### Stage 5: Results Review (COMPLETE mode)
**State**: Test finished; all result badges populated

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 27 | _(Pass scenario)_ Sees status badge: "✅ PASSED · 2m 34s" | Step table shows all 9 ✅; summary: "9 passed · 0 failed · 0 skipped" | Relieved/Happy |
| 28 | Clicks "📋 View Full Report" | Opens S3 report link in new tab | Done |
| 29 | Clicks "📎 Copy Report Link" | Link copied to clipboard; brief toast "Link copied!" | Sharing |
| 30 | Wants to run again with different user | Clicks "↩ Run Again" | Resets to SELECT with ticket pre-filled |

**Failure sub-path:**

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| 27F | _(Fail scenario)_ Sees "❌ FAILED · 1m 52s" | Steps 8 and 9 show ❌; summary: "7 passed · 2 failed · 0 skipped" | Concerned |
| 28F | Reads inline triage below step table | "Classification: Product Bug — Step 8 failed because the error message text did not match the expected file size limit. The page showed '10MB' but the AC expects '5MB'." | Understanding |
| 29F | Sees "Guidance input + Re-run with Guidance" | Types: "The limit was recently changed to 10MB. Accept both values." | Problem-solving |
| 30F | Clicks "Re-run with Guidance" | Transitions back to RUNNING mode with guidance injected | Iterating |

---

## Journey Map: Secondary Path (QA Lead — Nav & History)

### Stage B: Reviewing Past Tests
**Trigger**: QA lead wants to review results from yesterday's runs

| Step | User Action | System Response | Emotion |
|------|-------------|-----------------|---------|
| B1 | Clicks "📋 Test History" in left nav | Main area transitions to ReportsArchive view | Oriented |
| B2 | _(Mid-run scenario)_ Clicks nav during active test | Confirmation dialog: "A test is currently running. Navigate away?" | Warned |
| B3 | Confirms navigation | Test is cancelled; nav proceeds | Decided |

---

## Option Analysis

### Option A (Chosen): Mode-Centric Progressive Disclosure with Left Nav Rail
- **Pros**: Each mode shows only what's relevant; left nav is always visible; PM-first language reduces friction; natural-language step input is a differentiator
- **Cons**: Four distinct modes require careful state management; mode transitions must be smooth to feel cohesive
- **Mitigation**: Single `uiMode` state string in `RunTestView`; CSS animations handle transitions

### Option B: Persistent Multi-Panel (Config always visible)
- **Pros**: Less state management complexity
- **Cons**: Config panel takes space during RUNNING mode where it's irrelevant; causes visual noise
- **Rejected**: Contradicts progressive disclosure principle

### Option C: Wizard-Style (Multi-step form with "Next" buttons)
- **Pros**: Explicit progression; harder to skip steps
- **Cons**: Breaks the PM's mental model ("just pick and go"); wizard chrome adds unnecessary friction
- **Rejected**: Wrong metaphor for test execution

---

## UX Principles Applied

1. **Progressive Disclosure**: Each mode shows only the controls relevant to the current moment
2. **PM-First Language**: No developer jargon in any visible label
3. **Auto-Trigger on Selection**: Picking a ticket immediately starts preview — no extra "Go" button
4. **Natural Language Input**: Step addition feels conversational, not form-like
5. **Structural Feedback**: Step table with live badges is more scannable than terminal output
6. **Inline Triage**: Failure analysis appears where it belongs (below the step table) — not as a separate screen

---

## Handoff Notes for UI/UX Design

- The step table is the **single shared component** across REVIEW, RUNNING, and COMPLETE modes — its props must support all three modes cleanly
- Natural-language input row uses the existing `/preview-steps` endpoint with `pre_parse_guidance` payload — no new API needed
- HITL (`humanTakeoverMessage`) renders as a **modal overlay** over the step table — it must not replace the table
- The "A test is running" nav-away guard needs `beforeunload` equivalent — use a React Router `<Prompt>` or equivalent
- Quality badge on REVIEW mode maps to the existing AC quality score (GOOD/FAIR/POOR) — display logic TBD in build phase
