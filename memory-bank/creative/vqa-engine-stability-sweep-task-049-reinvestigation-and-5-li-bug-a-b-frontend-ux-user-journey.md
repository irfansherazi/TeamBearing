# vqa-engine-stability-sweep-task-049-reinvestigation-and-5-li: Bug A & Bug B Frontend UX — User Journey Design

**Task**: vqa-engine-stability-sweep-task-049-reinvestigation-and-5-li — vQA Engine Stability Sweep  
**Creative Phase**: User Journey Design  
**Component**: Bug A (Audit Report link graceful degradation) + Bug B (CopilotSidebar completion banner)  
**Date**: 2026-05-22  
**Author**: User Journey Design Agent (inline)

---

## Journey Scope

This document maps the complete end-to-end operator experience for two frontend UX regressions:

- **Bug A**: The "📄 View Audit Report" link in `ExecutionLog.tsx` opens a blank tab with a raw JSON 404 when `report_url` is empty (post-server-restart scenario)
- **Bug B**: The CopilotSidebar completion banner (`CopilotSidebar.tsx`) says "✓ All N steps passed" even when a step is `awaiting_human` or `skipped`

---

## Bug A — "View Audit Report" Graceful Degradation

### Current Journey (Broken)

```
[Run completes] → [S3 upload fails or server restarts] → [report_url = ""]
        │
        ↓
[Operator views ExecutionLog TerminalCard]
        │
        ↓
[reportUrl = message.report_url || `${API_BASE_URL}/runs/${run_id}/report`]  ← fallback to in-memory route
        │
        ↓
[Operator clicks "📄 View Audit Report"]
        │
        ↓
[New tab opens → 404 JSON: {"detail": "Run not found"}]  ← broken UX / confusing
        │
        ↓
[Operator has no recourse — unclear if bug or expected]
```

**Pain Points:**
1. Fallback URL (`/runs/{id}/report`) requires in-memory `_run_states[run_id]` to still exist — invalid after server restart
2. Raw JSON error is non-human-readable and un-actionable
3. The link is an `<a>` tag — there's no visual signal that it might fail
4. No tooltip explains the situation

### Desired Journey (Fixed)

```
[Run completes] → [S3 upload fails or server restarts] → [report_url = ""]
        │
        ↓
[Operator views ExecutionLog TerminalCard]
        │
        ↓
        ├─[report_url is non-empty]─────────────────────────────────────────────────────►
        │   └─ Render: <a href={report_url} ...>📄 View Audit Report</a>                │
        │      (existing behavior — unchanged)                                          │
        │                                                                               ▼
        │                                                            [Operator clicks → opens S3 report ✅]
        │
        └─[report_url is empty/falsy]────────────────────────────────────────────────────►
            └─ Render: <span/button aria-disabled="true" class="terminal-link report report--disabled"
                        title="Report not available — server was restarted after this run">
                        📄 View Audit Report</span>
               (visually disabled — muted color, not-allowed cursor, no href)

            [Operator hovers] → Tooltip: "Report not available — server was restarted after this run"
            [Operator clicks] → Nothing (aria-disabled, no action)
```

### UX Specification — Bug A

**Decision** (from planning): The `<a>` tag becomes a `<span>` or `<button>` with `aria-disabled="true"` and a CSS `disabled` class when `message.report_url` is empty (falsy). The backend fallback URL is NOT used.

#### Component: `ExecutionLog.tsx`

**Current code (L206):**
```tsx
// Current — uses fallback that 404s after restart
const reportUrl = message.report_url || `${API_BASE_URL}/runs/${message.run_id}/report`;
// ...
<a
  href={reportUrl}
  target="_blank"
  rel="noopener noreferrer"
  className="terminal-link report"
>
  📄 View Audit Report
</a>
```

**Target code:**
```tsx
// Remove fallback — treat missing report_url as "not available"
const hasReport = Boolean(message.report_url);

// Conditional render:
{hasReport ? (
  <a
    href={message.report_url}
    target="_blank"
    rel="noopener noreferrer"
    className="terminal-link report"
    id="link-view-audit-report"
  >
    📄 View Audit Report
  </a>
) : (
  <span
    className="terminal-link report report--disabled"
    aria-disabled="true"
    title="Report not available — server was restarted after this run"
    id="link-view-audit-report-disabled"
    role="link"
  >
    📄 View Audit Report
  </span>
)}
```

**CSS additions:**
```css
.terminal-link.report--disabled {
  opacity: 0.45;
  cursor: not-allowed;
  text-decoration: none;
  pointer-events: auto;  /* allow hover for tooltip */
  color: var(--text-muted, #888);
}
```

#### Accessibility Notes
- `aria-disabled="true"` signals to screen readers the element is not interactive
- `role="link"` on `<span>` preserves semantic meaning for screen readers
- `title` attribute provides tooltip text — works for mouse users; for keyboard/screen-reader users the `aria-label` conveys the same info
- The disabled span is NOT focusable by default (`<span>` has no tab index) — acceptable for this use case

#### Edge Cases
| Scenario | Behavior |
|----------|----------|
| `report_url` = `""` | Disabled span with tooltip |
| `report_url` = `null` | Disabled span with tooltip |
| `report_url` = `undefined` | Disabled span with tooltip |
| `report_url` = valid S3 URL | Active `<a>` link (existing behavior) |
| `report_url` = `/runs/.../report` (old fallback) | Should no longer occur post-fix; if it does, treated as a valid URL |

---

## Bug B — CopilotSidebar Completion Banner

### Current Journey (Broken)

```
[vQA run executes 3 AC steps]
[Step 1: passed] [Step 2: awaiting_human] [Step 3: passed]
        │
        ↓
[Run completes (state.isComplete = true)]
        │
        ↓
[failedCount = steps.filter(s => s.status === "failed").length]
[failedCount = 0  ← awaiting_human not counted as non-passing]
        │
        ↓
[Banner renders: "✓ All 3 steps passed"]  ← WRONG — Step 2 is awaiting_human!
        │
        ↓
[Operator believes run passed cleanly]
[Doesn't know a step needs manual review]
        │
        ↓
[Ticket is marked as passed incorrectly — human review step missed]
```

**Pain Points:**
1. `failedCount` only counts `"failed"` — `awaiting_human` and `skipped` are silently ignored
2. Banner CSS class stays `copilot-complete--pass` (green) — false positive signal
3. Both render paths (inline L307 and sidebar L409) have the same bug
4. The operator may close the browser or mark the ticket complete without reviewing the awaiting step

### Desired Journey (Fixed)

```
[vQA run executes 3 AC steps]
[Step 1: passed] [Step 2: awaiting_human] [Step 3: passed]
        │
        ↓
[Run completes (state.isComplete = true)]
        │
        ↓
[passedCount = 2]
[failedCount = 0]
[warningCount = 1  ← awaiting_human + skipped]
        │
        ┌──────────────────────────┬─────────────────────────────┐
        │                          │                             │
[warningCount > 0]          [failedCount > 0]          [both = 0]
        │                          │                             │
        ▼                          ▼                             ▼
[Banner: WARN]             [Banner: FAIL]               [Banner: PASS]
"2/3 passed ·              "${passedCount}/${total}      "✓ All 3 steps
 1 needs review"            passed · N failed"            passed"
CSS: copilot-complete       CSS: copilot-complete         CSS: copilot-complete
     --warn (yellow)             --fail (red)                  --pass (green)
```

**Note**: The priority order for mixed states: if ANY step failed, show FAIL banner (red). If no failures but some awaiting_human/skipped, show WARN banner (yellow). Only show PASS banner when ALL steps are `passed`.

### UX Specification — Bug B

#### Component: `CopilotSidebar.tsx`

**Shared computed values** (replace/extend existing `failedCount` line at ~L191):
```tsx
// Before (broken):
const failedCount = state.steps.filter((s) => s.status === "failed").length;

// After (fixed):
const totalSteps = state.steps.length;
const passedCount = state.steps.filter((s) => s.status === "passed").length;
const failedCount = state.steps.filter((s) => s.status === "failed").length;
const warningCount = state.steps.filter(
  (s) => s.status === "awaiting_human" || s.status === "skipped"
).length;

// Derived banner state:
const bannerVariant = failedCount > 0 ? "fail" : warningCount > 0 ? "warn" : "pass";
const bannerText =
  bannerVariant === "pass"
    ? `✓ All ${totalSteps} steps passed`
    : bannerVariant === "warn"
    ? `${passedCount}/${totalSteps} passed · ${warningCount} need${warningCount === 1 ? "s" : ""} review`
    : `${passedCount}/${totalSteps} passed · ${failedCount} failed`;
```

**Both render paths updated to use `bannerVariant` and `bannerText`:**
```tsx
{state.isComplete && !state.awaitingHuman && totalSteps > 0 && (
  <div className={`copilot-complete copilot-complete--${bannerVariant}`}>
    {bannerText}
  </div>
)}
```

This single JSX pattern replaces both the **inline** (L307–311) and **sidebar** (L409–413) banner instances.

**Note**: `passedCount` is already used for the progress bar at L190 — no duplicate computation, just extend the existing block.

#### CSS additions:
```css
.copilot-complete--warn {
  background: var(--warning-bg, #fff3cd);
  color: var(--warning-text, #856404);
  border-left: 4px solid var(--warning-border, #ffc107);
}
```

(`.copilot-complete--pass` and `.copilot-complete--fail` already exist.)

#### State Machine for Banner

```
Steps statuses → Banner
─────────────────────────────────────────────────────────────
All "passed"                           → PASS  (green)
≥1 "failed", any others               → FAIL  (red)
0 "failed", ≥1 "awaiting_human"/"skipped" → WARN (yellow)
```

#### Accessibility Notes
- Banner `role` should be `status` or `alert` for screen reader announcement
- WARN banner should use `aria-live="polite"` — not urgent, but needs announcement
- FAIL banner should use `aria-live="assertive"` — requires immediate attention

---

## Cross-Bug: Interaction Between A and B

These two bugs can co-occur in the same run:
```
Run: 3 steps, 2 passed, 1 awaiting_human, S3 upload failed

Banner (Bug B): "2/3 passed · 1 needs review"  [WARN - yellow]
Report link (Bug A): [disabled span] "📄 View Audit Report"  [muted, tooltip]
```

The combined UX clearly communicates to the operator:
1. The run is NOT fully clean (banner is yellow, not green)
2. The audit report is not available (link is disabled with tooltip)
3. The operator knows to manually review the awaiting step AND knows the report is unavailable

This is a coherent, honest UI state — far better than the current "✓ All 3 steps passed" + broken link experience.

---

## Test Coverage Map

| Test | Component | Assertion |
|------|-----------|-----------|
| `test_report_link_disabled_when_no_url` | `ExecutionLog.tsx` | Link renders as `<span aria-disabled>` when `report_url` is `""` |
| `test_report_link_active_when_url_present` | `ExecutionLog.tsx` | Link renders as `<a href={url}>` when `report_url` is valid |
| `test_banner_awaiting_human_not_all_passed` | `CopilotSidebar.tsx` | Banner shows "2/3 passed · 1 needs review", class `--warn` |
| `test_banner_skipped_not_all_passed` | `CopilotSidebar.tsx` | Banner shows "1/2 passed · 1 needs review" with `skipped` step |
| `test_banner_all_passed_when_all_passed` | `CopilotSidebar.tsx` | Banner shows "✓ All N steps passed", class `--pass` |
| `test_banner_fail_takes_priority_over_warn` | `CopilotSidebar.tsx` | Banner shows FAIL text/class when both failed + awaiting_human present |
| `test_banner_both_render_paths` | `CopilotSidebar.tsx` | Inline AND sidebar render paths both use `bannerVariant`/`bannerText` |

---

## Decision Summary

| Bug | Component | Change | Chosen Approach |
|-----|-----------|--------|-----------------|
| A | `ExecutionLog.tsx` | Replace `<a>` + fallback URL with conditional `<span aria-disabled>` | Render disabled span with tooltip when `report_url` is falsy |
| B | `CopilotSidebar.tsx` | Add `warningCount`; derive `bannerVariant` and `bannerText`; update both render paths | Three-state banner: PASS / WARN / FAIL |
