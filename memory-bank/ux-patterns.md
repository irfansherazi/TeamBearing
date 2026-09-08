# UX Patterns

<!--
  CROSS-FILE CONSISTENCY GUARDRAIL (read before editing)

  This file is the canonical source for COMPONENT-USAGE and BEHAVIORAL-UI rules
  (AlertDialog vs Dialog, Drawer vs Modal, Tabs vs Sections, Toast placement,
  empty-state requirements, mobile adaptation). Anything else MUST live where it
  belongs and be REFERENCED here, not restated:

    | Topic                                          | Canonical source                  |
    |------------------------------------------------|-----------------------------------|
    | Tech stack, component library version, E2E fw  | techContext.md                    |
    | Design tokens (color, spacing, typography)     | frontend/src/index.css            |
    | Architecture patterns, error conventions       | systemPatterns.md                 |
    | Testing patterns, what's deliberately untested | systemPatterns.md                 |
    | Persona definitions, user roles, NFRs          | productBrief.md                   |

  REFERENCE syntax — write `see frontend/src/index.css → Design Tokens`, NOT inline copies.
  The /vc-uat synthesizer follows references when checking conformance; a
  missing reference target itself becomes a finding.

  Why: duplicate facts drift. When ux-patterns.md, systemPatterns.md, and
  techContext.md disagree on the spacing scale, UAT findings become noise and
  trust in the file collapses. Reference once; layer behavior on top.

  ALLOWED: "Form field heights: 40px (≡ --space-10 from frontend/src/index.css → Design
  Tokens). Not 36px or 44px." — references the canonical source AND adds a
  UX-specific behavioral rule.

  FORBIDDEN: copy-pasting the spacing scale into this file.
-->

**Last Updated**: 2026-06-04
**Source(s)**: hand-written
**Source hashes**: { }

---

## Dialogs & Modals

### Rule: Confirmation dialogs use `AlertDialog` for destructive actions
- When: deleting, archiving, or anything destructive/irreversible (e.g., deleting run history, clearing HITL memory)
- Not: plain `Dialog` (no `role="alertdialog"`)
- Reference: `see frontend/src/components/TakeoverPanel.tsx` or `see techContext.md → Component Structure`

### Rule: Modals close on ESC and outside-click
- Exception: in-progress async operation (loading spinner visible on executing test runs)

## Drawer vs Modal

### Rule: Side drawer for contextual detail/inspector panels (≥ 768px)
- Examples: `CopilotSidebar` (AC step tracker panel showing live status of steps)
- Anti-pattern: full-screen modal when user needs to reference the list behind it

### Rule: Bottom sheet / drawer for compound forms on mobile (≤ 640px)
- Dismissal: tap outside or explicit close button

## Tabs vs Sections

### Rule: Tabs for switching between mutually exclusive views of the same resource
- Examples: `Dashboard` tab navigation (Run Test / Reports Archive / Analytics)
- Anti-pattern: tabs for "steps" in a wizard — use step indicators instead

### Rule: Sections (accordion or sectioned scroll) for viewing all related info at once

## Forms

### Layout
- Single column on mobile (max-width: `640px`); up to 2-column on desktop (e.g., `ExecutionPanel` layout)
- Required indicator: `*` after label, color not-red-alone
- Field heights: `see frontend/src/index.css → Design Tokens v3`

### Validation
- Inline, below field
- Red only on submit attempt or blur after touch
- Do not block typing

### Errors
- Error banner top of form for server errors
- Field-level for client-side validation
- Retry action always available

## Empty States

### Rule: Always provide an empty-state view with one primary CTA
- Examples: empty run list view → "Run Test" or "New Ticket" CTA

## Toasts & Banners

### Rule: Toast top-right, auto-dismiss after duration
- Examples: toast notification on successful login or SSO redirection

### Rule: Banner full-width, persistent until dismissed, only for page-wide state
- Examples: `GlobalHitlBanner` (full-width banner visible when an operator takeover is pending)

## Loading States

### Rule: Skeleton for content areas (cards, tables)
- Examples: card lists or analytics trends during fetch

### Rule: Spinner for explicit async actions (submit, save)
- Examples: button states in `LoginPage` ("Logging in...") or `ExecutionPanel` ("Running...")

### Rule: Never show raw JSON or "undefined" during load
- Examples: intermediate states in the `ExecutionLog` or step cards must use animated typing effects (see `ThinkingCard`)

## Mobile Adaptation

### Breakpoint: `see frontend/src/index.css → @media (max-width: 640px)`
### Rule: Tables → card list on mobile (e.g., report archives, run history)
### Rule: Multi-column forms → single column
### Rule: Right-side inspectors → bottom drawers

## Tokens

> Tokens (color, spacing, typography) are NOT defined here. Reference the canonical source in index.css.
>
> - Color: `see frontend/src/index.css → Design Tokens v3 → [data-theme="dark"]` and `[data-theme="light"]` (curated deep purple palette)
> - Spacing: `see frontend/src/index.css → Design Tokens v3` (xs, sm, md, lg, xl space system)
> - Radii: `see frontend/src/index.css → Design Tokens v3` (sm, md, lg radius system)
> - Typography: `see frontend/src/index.css → Design Tokens v3` (Inter font family for sans, JetBrains Mono for mono)

---

## Conflicts Requiring Resolution

(none)
