---
slug: heal-qa192-followup
status: QUARANTINED
derived_from: heal-playwright-tests-round4
quarantined_on: 2026-08-10
---

# heal-qa192-followup: Fix QA-192 Revise Blog Post Button

## Problem

`playwright/tests/vpromedia/qa-192-recorded.test.ts` quarantined in `heal-playwright-tests-round4` Rev Phase 1.

**Root cause:** In the `Revise spot with internal cause` step, the blog text `Post` button (`getByRole('button', { name: 'Post', exact: true })`) remains `disabled` even after the blog textarea is filled. Multiple approaches failed:
- `page.fill()` — button stays disabled
- `page.type()` + `Tab` blur — button stays disabled
- `page.evaluate()` setting value + dispatching native `input`, `change`, `blur` events — button stays disabled

The Angular Revise drawer's form validation (`ngModel` dirty/valid state) is not triggered by Playwright's synthetic input events. The Angular model likely requires the form to detect a real user keydown sequence or a specific `(ngModelChange)` event chain.

**What DOES work:** Copy and Extend steps pass correctly (floater mounts with `click({ force: true })` on the native checkbox; Extend drawer date/finish flow works). The issue is isolated to the Revise drawer's blog textarea.

## Evidence

Across 7 test runs with 3 retries each: `Post` button consistently `disabled`.
approveSpot equivalent: `toBeEnabled` consistently fails at `input#complete-job-<id>-Dubber`.

## Fix Required

Options:
1. Use `page.keyboard.type()` with `page.focus()` explicitly on the textarea (separate from `textarea.click()`), then verify the Angular `[(ngModel)]` model picks up the keystrokes.
2. Investigate the Angular component's form binding. The textarea may bind to `[(ngModel)]` with a validator; use Playwright DevTools (or `PWDEBUG=1`) to inspect the component's binding and find the event that enables the Post button.
3. If the textarea is inside a nested Angular reactive form, use the component's `formControl.setValue()` via page.evaluate instead of DOM events.

## Note

The Copy and Extend portions of QA-192 work correctly. Only the Revise step needs this fix.
