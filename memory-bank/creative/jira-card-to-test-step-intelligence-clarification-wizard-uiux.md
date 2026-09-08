# UI/UX Decision: Clarification Wizard Modal

**Created**: 2026-07-14
**Status**: DECIDED
**Decision Type**: UI/UX

---

## User Context

### Target Users

- **Primary**: QA Lead / Automation Engineer — owns the regression suite; selects multi-path Jira cards and needs to control which navigation paths get tested without being forced through unnecessary friction for simple tickets.
- **Secondary**: Product Manager — verifying tickets self-service; wants to resolve ambiguous terms quickly before a run starts so the generated steps are accurate, but cannot tolerate a complex setup dialog that slows them down.

### User Goals

1. Understand which navigation paths the backend detected in the Jira card and make a quick decision about which to include in this run.
2. Resolve surfaced ambiguities (e.g., vague terms like "correct total") with a short free-text clarification before execution begins.
3. Proceed to the step editor with minimal friction; single-path cards must never encounter the wizard.

### Use Cases

| Use Case | User | Goal | Frequency |
|----------|------|------|-----------|
| Multi-path ticket — select subset of paths | QA Lead | Include 2 of 3 detected paths; run focused regression | Common (any multi-path card) |
| Ambiguous-term ticket — clarify before run | PM or QA Lead | Provide plain-English resolution for vague AC language | Occasional |
| Single-path clean ticket — skip wizard | PM or QA Lead | Proceed straight to step editor, zero extra clicks | Dominant (most tickets) |
| Multi-path + ambiguities — combined review | QA Lead | Toggle paths AND resolve ambiguities in one pass | Occasional |
| Dismiss wizard without changes | Any user | Preserve unmodified steps from preview | Occasional (user decides all defaults are fine) |

### Constraints

- **Devices**: Desktop-only UI (vQA is an internal engineering tool; no mobile requirement established in productBrief.md). Min width 1024px assumed.
- **Accessibility**: WCAG 2.1 AA — `role="dialog"`, `aria-modal="true"`, focus trap, visible focus indicators, keyboard-navigable checkboxes and text fields.
- **Existing Patterns**:
  - Modal overlay: `RecordDemoModal.tsx` (`.record-demo-overlay` / `.record-demo-modal` structure with header + body + footer sections)
  - Full-screen takeover: `TakeoverPanel.tsx` (backdrop-blur overlay pattern for high-visibility modal moments)
  - CSS class conventions: `btn-primary`, `btn-secondary` for primary/secondary actions
  - Mode-Centric Progressive Disclosure (systemPatterns.md): 4-mode state machine (SELECT → REVIEW → RUNNING → COMPLETE) — wizard sits at the SELECT→REVIEW transition
  - `ExecutionPanel.tsx` already manages `preParseGuidance` string state and passes it to `/preview-steps`
  - No PrimeNG component library in frontend — raw React + custom CSS

---

## User Flow

### Flow Diagram

```
[User selects Jira ticket in ExecutionPanel]
          |
          v
[autoPreview() fires → GET /preview-steps resolves]
          |
          +--[detected_paths.length == 1 AND ambiguities.length == 0]--> [Step editor renders normally, no wizard]
          |
          +--[detected_paths.length >= 2 OR ambiguities.length > 0]----> [ClarificationWizardModal opens]
                    |
                    v
          [User sees: path checklist (all checked by default)]
          [User sees: ambiguity fields (if any)]
                    |
                    +--[User toggles paths / fills ambiguities]--> [local state updates, no API call yet]
                    |
                    +--[User clicks "Confirm"]--> [wizard closes; pre_parse_guidance string built;
                    |                              previewSteps filtered by included paths;
                    |                              step editor renders]
                    |
                    +--[User clicks "Skip"]--> [wizard closes; unmodified previewSteps rendered;
                                               no pre_parse_guidance injected]
```

### Flow Description

1. **Entry**: `autoPreview()` resolves with a `PreviewStepsResponse` that includes `detected_paths: string[]` and `ambiguities: string[]`. `ExecutionPanel` checks trigger threshold and sets `showWizard = true` if met.
2. **Wizard opens**: Modal renders with focus trapped inside. All paths pre-checked. Ambiguity inputs are empty.
3. **Path selection**: User unchecks one or more paths. Visual feedback: unchecked row fades to 50% opacity. A summary count badge updates ("2 of 3 paths included").
4. **Ambiguity resolution**: If ambiguities exist, each renders as a labeled read-only term + a text input for the resolution. Fields are optional — leaving them empty is valid.
5. **Confirm**: Modal closes. Wizard selections are serialized to `pre_parse_guidance`. The `ExecutionPanel` re-calls `autoPreview()` with the guidance string, which causes the backend to re-parse using the included paths and resolutions. Step editor renders the updated steps.
6. **Skip / Dismiss**: Modal closes. `previewSteps` state is unchanged (the unfiltered steps from the initial preview remain). No `pre_parse_guidance` is set.

### Error States

| Error | Cause | User Recovery |
|-------|-------|---------------|
| All paths deselected | User unchecks every path | "Confirm" button disabled; inline message: "Select at least one path to continue." |
| Preview re-fetch fails after Confirm | Network error on second `autoPreview()` call | Standard `previewError` state in `ExecutionPanel` shows; wizard is already closed; user can re-run preview |
| Ambiguity field exceeds length | User types very long resolution text | `maxLength` attribute enforced on textarea; no blocking error |

---

## Trigger Threshold Decision

**Decision: Rule B — show wizard when `len(detected_paths) >= 2` OR `len(ambiguities) > 0`**

### Rationale for Rule B over Rule A

Rule A (paths only) would silently drop single-path tickets that still carry vague language. The ambiguity pre-check (systemPatterns.md: "Ambiguity Pre-Check, FEAT-058") already exists in the backend and is designed to surface untestable requirements. If the backend detects a vague term on a single-path card, a PM self-verifying a ticket has no way to resolve it before the run — they would get a degraded test without any warning.

Rule B costs nothing for the dominant case (single-path, no ambiguities → wizard never appears, per AC-D3-ENTRY-2). For the minority case of a single-path ambiguous card it saves one retry cycle. The wizard is presented as lightweight (described below), so the extra trigger condition does not increase friction in practice.

---

## Options Explored

### Option 1: Vertical Checklist (Layout A)

- **Approach**: Each detected navigation path appears as a single row containing a checkbox and the path text (e.g., "HDah > Module Abilities > Edit Module"). Ambiguity sections appear below the path list, each as a label + single-line text input. No expansion or drag behavior.
- **Wireframe/Layout**:
  ```
  ┌──────────────────────────────────────────────────────────┐
  │  Review Navigation Paths                    [2 of 3 paths]│
  ├──────────────────────────────────────────────────────────┤
  │  Select the paths to include in this test run:            │
  │                                                           │
  │  [x]  HDah > Module Abilities > Edit Module               │
  │  [x]  HDah > Module Abilities > Delete Module             │
  │  [ ]  HDah > Reports > Usage                              │
  │                                                           │
  │  ── Clarify Ambiguous Terms ───────────────────────────── │
  │  "correct total"                                          │
  │  [What should the correct total be?              ]        │
  │                                                           │
  ├──────────────────────────────────────────────────────────┤
  │  [Skip — use all paths]          [Confirm Selection]      │
  └──────────────────────────────────────────────────────────┘
  ```
- **User Flow**: Open modal → scan path list → uncheck unwanted rows → optionally fill ambiguity inputs → click Confirm.
- **Pros**:
  - Directly mirrors the existing `StepTable` row-per-item pattern — visual consistency with the rest of `ExecutionPanel`
  - Minimal cognitive load: checkboxes are universally understood; no need to learn a new interaction
  - Fastest to implement — no accordion state, no drag-and-drop library
  - Accessible by default: native `<input type="checkbox">` + `<label>` elements are screen-reader friendly
  - Modal height is compact and predictable; 2–5 paths renders comfortably without scrolling
- **Cons**:
  - No step preview — user cannot see what steps each path would generate before committing
  - No reordering capability — path execution order is backend-determined
  - For a ticket with 8+ paths the list could require scrolling (edge case for this codebase)
- **Usability**: High — zero learning curve, immediately familiar
- **Accessibility**: High — native form elements, straightforward keyboard navigation
- **Implementation Complexity**: Low

---

### Option 2: Expandable Accordion with Step Preview (Layout B)

- **Approach**: Each detected navigation path appears as a collapsible accordion row. The header row contains a checkbox and the path label. Expanding a row shows a preview list of the 2–4 steps that would be generated for that path, drawn from the already-fetched `previewSteps` data partitioned by path.
- **Wireframe/Layout**:
  ```
  ┌──────────────────────────────────────────────────────────┐
  │  Review Navigation Paths                    [3 of 3 paths]│
  ├──────────────────────────────────────────────────────────┤
  │  [x]  HDah > Module Abilities > Edit Module       [▼]    │
  │       ┌─────────────────────────────────────────────┐   │
  │       │ • Navigate to HDah > Module Abilities        │   │
  │       │ • Click Edit on the target module            │   │
  │       │ • Verify edit form opens                     │   │
  │       └─────────────────────────────────────────────┘   │
  │  [x]  HDah > Module Abilities > Delete Module     [▶]    │
  │  [ ]  HDah > Reports > Usage                      [▶]    │
  │                                                           │
  ├──────────────────────────────────────────────────────────┤
  │  [Skip — use all paths]          [Confirm Selection]      │
  └──────────────────────────────────────────────────────────┘
  ```
- **User Flow**: Open modal → expand paths of interest → review step previews → check/uncheck → click Confirm.
- **Pros**:
  - Gives expert QA users a preview of what each path will generate — reduces the chance of a surprise step list
  - Step preview panels can reuse the same step rendering logic as `StepTable`
- **Cons**:
  - Requires the backend to partition `previewSteps` by detected path in the response — additional schema complexity (step-to-path mapping)
  - Accordion open/close state adds implementation surface area (2–3× more code than Option 1)
  - The step preview data is speculative pre-confirmation; showing it could confuse users who do not realize these are provisional
  - Accordion disclosure is a less common pattern in this codebase (no existing accordion component) — increases implementation risk
  - Adds height to the modal; expanded accordions could push the footer offscreen, requiring scroll
- **Usability**: Medium — valuable for power users, but adds cognitive work for PMs who just want to quickly confirm
- **Accessibility**: Medium — accordion patterns require `aria-expanded`, `aria-controls`, and keyboard expand/collapse — non-trivial to implement correctly without a library
- **Implementation Complexity**: High

---

### Option 3: Two-Column Include / Exclude with Drag-to-Reorder (Layout C)

- **Approach**: Two columns side by side — "Include" and "Exclude". Paths are drag-and-drop cards between columns. Reorder within Include column to set execution priority.
- **Wireframe/Layout**:
  ```
  ┌──────────────────────────────────────────────────────────┐
  │  Review Navigation Paths                                  │
  ├────────────────────────┬─────────────────────────────────┤
  │  Include (drag to add) │  Exclude (drag to remove)       │
  │  ┌──────────────────┐  │                                  │
  │  │ Edit Module      │  │                                  │
  │  │ Delete Module    │  │  ┌──────────────────┐           │
  │  └──────────────────┘  │  │ Usage Report      │          │
  │                        │  └──────────────────┘           │
  ├────────────────────────┴─────────────────────────────────┤
  │  [Skip]                              [Confirm Selection]  │
  └──────────────────────────────────────────────────────────┘
  ```
- **User Flow**: Open modal → drag unwanted paths to Exclude column → optionally reorder Include column → Confirm.
- **Pros**:
  - Makes inclusion/exclusion visually explicit — no ambiguity about which paths are in vs. out
  - Supports execution ordering if the backend can honor path order in `pre_parse_guidance`
- **Cons**:
  - Drag-and-drop is the highest-friction interaction for keyboard and screen reader users — WCAG compliance requires a non-drag alternative (adding even more UI surface)
  - No drag-and-drop library is currently in the frontend dependencies — would require adding one (e.g., `@dnd-kit/core`) or hand-rolling, significantly increasing scope
  - The backend does not currently have path-ordering support; the reorder feature has no backend consumer
  - Overkill for the median use case: the user just wants to exclude one path, not choreograph 5 cards
  - PM users (less technical) would find this interaction pattern unexpected for a pre-run configuration dialog
- **Usability**: Low for the target users — drag metaphor is powerful but unexpected in this context
- **Accessibility**: Low — drag-and-drop is notoriously difficult to make fully accessible
- **Implementation Complexity**: High

---

## Evaluation Matrix

| Criteria | Option 1: Vertical Checklist | Option 2: Accordion + Preview | Option 3: Two-Column Drag |
|----------|------------------------------|-------------------------------|---------------------------|
| Usability | High | Medium | Low |
| Accessibility | High | Medium | Low |
| Consistency with existing patterns | High | Medium | Low |
| Responsiveness / compactness | High | Medium (can overflow) | Low (two columns need wide viewport) |
| Performance | High (zero extra data) | Medium (step partitioning needed) | High (local only) |
| Implementation effort | Low | High | High |
| **Total** | **6/6** | **3.5/6** | **1.5/6** |

---

## Decision

**Chosen**: Option 1 — Vertical Checklist

**Trigger Threshold**: Rule B — wizard appears when `len(detected_paths) >= 2` OR `len(ambiguities) > 0`

### Rationale

Option 1 wins on every axis that matters for this user base and codebase. The primary personas (QA Lead and PM) share a priority of speed and accuracy: they need to make a quick inclusion decision, not a deep architectural review. The vertical checklist maps directly onto the familiar `StepTable` row pattern already used in `ExecutionPanel`, providing zero learning curve. It is the only option that satisfies WCAG AA out of the box with native form elements, respects the Mode-Centric Progressive Disclosure principle by keeping the wizard compact and interstitial rather than making it a second full workflow, and can be implemented without new dependencies.

Option 2 (accordion) is attractive to power users but introduces speculative step preview data that could be confusing before the user has confirmed their path selection — the preview content would change after confirmation anyway. It also requires a step-to-path partitioning scheme in the backend schema that is not yet designed. That complexity is deferred appropriately.

Option 3 (drag-and-drop) has no place in a keyboard-centric internal engineering tool and fails both the accessibility and "minimal friction" acceptance criteria (AC-D3-ENTRY-2).

### Trade-offs Accepted

- **No step preview per path**: Users cannot see the generated steps for each path before confirming. This is acceptable because: (a) the full step list is visible immediately after confirmation in the step editor, where users can still edit it; (b) showing provisional step previews before confirmation would add complexity without improving decision quality for the typical 2–3 path case.
- **Accordion deferred**: If advanced users eventually need per-path step previews, Option 2 can be layered on top of the Option 1 checklist in a future iteration. The state shape and component structure designed here supports that extension.
- **Re-fetch on Confirm**: Confirming the wizard triggers a second call to `autoPreview()` with `pre_parse_guidance` injected. This adds ~10–30 seconds of latency after confirmation. This is acceptable because: (a) the backend needs to re-parse with the guidance applied; (b) the existing `previewLoading` state in `ExecutionPanel` already shows a spinner during preview fetch, so the user receives feedback; (c) the alternative (client-side path filtering without re-fetch) would produce inaccurate steps because path filtering affects the LLM normalization prompt, not just the final step list.

---

## Design Specifications

### Layout

- **Desktop (>1024px)**: Centered modal, max-width 560px (matching `RecordDemoModal` sizing convention). Positioned with a semi-transparent overlay covering `ExecutionPanel`. Modal has three sections: header, scrollable body, sticky footer.
- **Tablet (640–1024px)**: Same layout; modal fills 90% of viewport width. Not a priority for this internal tool.
- **Mobile (<640px)**: Out of scope per productBrief.md (internal desktop-only tool).

### Key Components

| Component | Purpose | Behavior |
|-----------|---------|----------|
| Modal overlay div | Backdrop blur, click-outside trap | `position: fixed`, `inset: 0`, `background: rgba(0,0,0,0.5)`, click on overlay does NOT dismiss (must use Skip/Confirm to prevent accidental dismissal) |
| Modal container div | `role="dialog"`, `aria-modal="true"`, `aria-labelledby` | Focus trapped on mount via `useEffect` + `querySelectorAll` on focusable elements |
| Path count badge | Shows "N of M paths included" | Updates reactively as user toggles checkboxes |
| Path row (`<label>` + `<input type="checkbox">`) | Per-path include/exclude toggle | Checked by default; unchecked row dims to 50% opacity via CSS class |
| "Select at least one" inline message | Prevents zero-path confirmation | Renders below path list only when all checkboxes are unchecked; `role="alert"` |
| Ambiguity section | Rendered only when `ambiguities.length > 0` | Horizontal rule separator, section heading, one label + text input per ambiguity |
| "Skip" button (`btn-secondary`) | Dismiss without changes | Calls `onSkip()` prop; closes modal; leaves `previewSteps` unmodified |
| "Confirm" button (`btn-primary`) | Apply selections | Disabled when zero paths checked; calls `onConfirm(selectedPaths, resolutions)` |

### Interactions

| Trigger | Action | Feedback |
|---------|--------|----------|
| Modal mounts | Focus moves to first focusable element (first checkbox) | Screen reader announces dialog label |
| User unchecks a path | Row opacity drops to 50% | Path count badge decrements: "1 of 3 paths included" |
| All paths unchecked | Confirm button disabled | Inline `role="alert"` message: "Select at least one path to continue." |
| Re-check a path | Row returns to full opacity | Path count badge increments |
| User fills ambiguity field | Local state updates | No visual aside from standard input value |
| Click "Confirm" (valid) | `onConfirm` fires; modal closes; `ExecutionPanel` starts re-fetch with guidance | Modal unmounts; existing `previewLoading` spinner in `ExecutionPanel` activates |
| Click "Skip" | `onSkip` fires; modal closes | Modal unmounts; original `previewSteps` remain rendered |
| Press Escape | Same as "Skip" | Modal closes; `keydown` handler on modal container |
| Tab / Shift+Tab | Cycles through focusable elements within modal only | Focus never leaves modal while open |

### Responsive Behavior

| Breakpoint | Changes |
|------------|---------|
| > 1024px | Full 560px centered modal |
| 640–1024px | Modal width 90vw |
| < 640px | Not in scope |

### Accessibility Requirements

- [x] Keyboard navigation support — Tab/Shift+Tab cycles within modal; Escape dismisses via Skip behavior; Space toggles checkboxes; Enter activates buttons
- [x] Screen reader compatibility — `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to modal title; `role="alert"` on validation message
- [x] Color contrast compliance (WCAG AA) — use existing `btn-primary` / `btn-secondary` classes which already comply; dimmed unchecked rows at 50% opacity must still meet 3:1 contrast for large text (path text at ~16px)
- [x] Focus indicators visible — rely on existing global focus-ring CSS; do not suppress `outline`
- [x] Error messages accessible — "Select at least one path" renders in a `role="alert"` span that screen readers announce immediately on state change

---

## Implementation Guidelines

### For Developers

1. **Component location**: `frontend/src/components/ClarificationWizardModal.tsx`. No sub-directory needed — the component is a self-contained single file matching `RecordDemoModal.tsx` convention.

2. **Props interface**:
   ```typescript
   interface ClarificationWizardModalProps {
     detectedPaths: string[];          // from PreviewStepsResponse.detected_paths
     ambiguities: string[];            // from PreviewStepsResponse.ambiguities
     onConfirm: (selectedPaths: string[], resolutions: Record<string, string>) => void;
     onSkip: () => void;
   }
   ```

3. **Internal state shape**:
   ```typescript
   // All paths checked by default on mount
   const [checkedPaths, setCheckedPaths] = useState<Set<string>>(
     () => new Set(detectedPaths)
   );
   const [resolutions, setResolutions] = useState<Record<string, string>>(
     () => Object.fromEntries(ambiguities.map(a => [a, ""]))
   );
   ```

4. **`pre_parse_guidance` serialization** (in `ExecutionPanel.tsx`, not in the modal itself):
   ```typescript
   function buildGuidance(selectedPaths: string[], resolutions: Record<string, string>): string {
     const parts: string[] = [];
     // List excluded paths explicitly so backend can suppress them
     const excluded = detectedPaths.filter(p => !selectedPaths.includes(p));
     for (const p of excluded) {
       parts.push(`Exclude path: ${p}`);
     }
     // Append resolutions for ambiguous terms
     for (const [term, resolution] of Object.entries(resolutions)) {
       if (resolution.trim()) {
         parts.push(`Clarification — "${term}": ${resolution.trim()}`);
       }
     }
     return parts.join("\n");
   }
   ```

5. **`ExecutionPanel.tsx` wiring** — at the `autoPreview()` result handler (lines 256–265), after `setPreviewSteps(...)`:
   ```typescript
   // New fields from extended PreviewStepsResponse schema
   const shouldShowWizard =
     (data.detected_paths?.length ?? 0) >= 2 ||
     (data.ambiguities?.length ?? 0) > 0;
   if (shouldShowWizard) {
     setWizardPaths(data.detected_paths ?? []);
     setWizardAmbiguities(data.ambiguities ?? []);
     setShowWizard(true);
   }
   // else: wizard stays hidden, step editor renders normally
   ```

6. **Focus trap** — implement as a `useEffect` on mount. Use `querySelectorAll('button, input, textarea, [tabindex]:not([tabindex="-1"])')` within the modal container ref. Attach a `keydown` listener that intercepts Tab/Shift+Tab and wraps focus. This is the same pattern needed for `TakeoverPanel` and is consistent with the `role="dialog"` + `aria-modal` contract.

7. **CSS classes** — follow `RecordDemoModal.tsx` conventions:
   - Overlay: `wizard-overlay` (full-screen fixed backdrop, same as `.record-demo-overlay`)
   - Modal container: `wizard-modal` (white card, border-radius, box-shadow, max-width 560px)
   - Header: `wizard-header` (title + path count badge)
   - Body: `wizard-body` (scrollable if needed, max-height 60vh)
   - Path row: `wizard-path-row` / `wizard-path-row--excluded` (50% opacity when unchecked)
   - Ambiguity section: `wizard-ambiguity-section`
   - Footer: `wizard-footer` (flex row, space-between for Skip and Confirm)

8. **Disambiguation of "Skip" semantics**: "Skip" means "use unmodified steps from the initial preview". It does NOT trigger a second `autoPreview()` call. Document this in a code comment at the call site.

9. **`PreviewStepsResponse` TypeScript type extension** (in `frontend/src/types/index.ts`):
   ```typescript
   interface PreviewStepsResponse {
     steps: string[];
     acceptance_criteria?: string;
     parse_quality?: string;
     parse_quality_reason?: string;
     // New in jira-card-to-test-step-intelligence / FEAT-113:
     detected_paths?: string[];
     ambiguities?: string[];
   }
   ```
   Mark both as optional with `?` so the existing single-path flow degrades gracefully without backend changes during development.

### Component Structure

```
frontend/src/components/
└── ClarificationWizardModal.tsx    (self-contained; no sub-directory)
```

No separate test file is required at the component level — the task's test strategy specifies 2 unit tests for `pre_parse_guidance` serialization logic, which should be co-located with `ExecutionPanel` or in a `utils/` test file rather than a React component test.

### Recommended Libraries / Patterns

- No new libraries required. Native `<input type="checkbox">`, `<textarea>`, and `<button>` elements with semantic HTML fully satisfy the design.
- Focus trap is implemented inline (20–30 lines) — no `focus-trap-react` or `@radix-ui/react-dialog` needed. This keeps the dependency footprint consistent with the rest of the frontend.

---

## Validation Checklist

- [x] Meets all user goals — paths are togglable; ambiguities are resolvable; single-path cards bypass wizard entirely
- [x] Accessible per WCAG 2.1 AA — native form elements, `role="dialog"`, `aria-modal`, focus trap, keyboard navigation, `role="alert"` for validation
- [x] Consistent with existing patterns — `RecordDemoModal` overlay structure; `btn-primary` / `btn-secondary`; inline CSS class conventions
- [x] Respects Guiding Principles in systemPatterns.md — Mode-Centric Progressive Disclosure (wizard is the SELECT→REVIEW gate, not a full mode); Component-Driven State Display (checklist rows mirror StepTable pattern)
- [x] Responsive across target devices — desktop-only per productBrief.md constraints
- [x] Performance acceptable — no additional API calls on wizard open; one `autoPreview()` re-fetch only on Confirm
- [x] Implementation feasible — no new dependencies, no new backend routes; single 150–200 line component file

---

## Next Steps

1. **Backend first (Phase 1 / Phase 2 prerequisite)**: Extend `PreviewStepsResponse` in `backend/api/schemas.py` to include `detected_paths: list[str]` and `ambiguities: list[str]`. The `ac_parser_node` must populate these fields. The UI can be developed against a stub/mock of these fields independently.
2. **Implement `ClarificationWizardModal.tsx`**: Follow the component structure, props interface, and CSS class conventions above. Wire into `ExecutionPanel.tsx` at the `autoPreview()` result handler.
3. **Extend `frontend/src/types/index.ts`**: Add optional `detected_paths` and `ambiguities` fields to `PreviewStepsResponse` to unblock frontend development before backend is complete.
4. **Implement `buildGuidance()` utility**: Either inline in `ExecutionPanel.tsx` or extracted to `frontend/src/utils/wizardGuidance.ts`. Write the 2 unit tests specified in the task's test strategy against this function.
5. **Manual UAT** via `/banyan-uat` after Phase 3 implementation: walk the wizard open/toggle/confirm/skip flow with a real multi-path Jira card; verify zero wizard appearance on a single-path card.
