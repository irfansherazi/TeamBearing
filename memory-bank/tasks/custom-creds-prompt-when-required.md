---
slug: custom-creds-prompt-when-required
legacy_id:
feature:
status: COMPLETE
---

# custom-creds-prompt-when-required: Prompt for Custom credentials when Computer-Use loop needs them

**Complexity**: Level 1
**Status**: COMPLETE
**Roadmap**: N/A
**Branch**: task/custom-creds-prompt-when-required
**Worktree**: N/A (Level 1 uses direct branch, not worktree)
**Reflection**: memory-bank/reflection/custom-creds-prompt-when-required-reflection.md
**Archived**: memory-bank/archive/custom-creds-prompt-when-required-archive.md
**Completed**: 2026-08-12

## Task Description

Currently, when starting a Computer-Use run without admin credentials, the user sees the warning:

> ⚠️ Computer-Use loop requires admin credentials. Enable 'Ghost Login' or 'Custom credentials' and enter an email + password before starting.

But in `RunTestView.tsx` (the screen where the warning surfaces) there is nowhere to enter Custom credentials — the `useCustomCreds` / `customEmail` / `customPassword` inputs only live in `SelectView.tsx`. If the user reaches this error, they must navigate back to re-configure, which is easy to miss.

**Fix**: Ensure that if Custom credentials are required (i.e. the pre-flight check at `RunTestView.tsx:400-405` blocks the run and no Ghost path is available), a Custom Credentials prompt pops up in place — mirroring the existing `GhostCredentialPanel` pattern.

## Implementation Notes

**Where the gap is**:
- `frontend/src/components/RunTestView.tsx:373-420` — `handleStartTest` selects credentials in this priority: ghost-login → ghost-description → custom → error. Error path shows a `localError` toast but no input to resolve it.
- `frontend/src/components/RunTestView.tsx:674-680` — existing pattern: `GhostCredentialPanel` renders when `activeGhostCredentials` is set (triggered by a WS message). A `CustomCredentialPanel` slot alongside it is the natural home for the new UI.
- `frontend/src/components/SelectView.tsx:102-104, 525-548` — where `useCustomCreds`, `customEmail`, `customPassword` are currently entered.
- `runConfig` shape is defined at `RunTestView.tsx:43-45` and already carries `useCustomCreds`, `customEmail`, `customPassword`.

**Proposed shape** (to refine during build):
1. New small component `CustomCredentialPanel.tsx` (or inline modal in RunTestView) with email + password inputs and Save/Cancel — modelled on `GhostCredentialPanel.tsx`.
2. New state `showCustomCredsPrompt` in RunTestView.
3. In `handleStartTest` (line 400), when the "requires admin credentials" branch is entered AND no ghost path is available, set `showCustomCredsPrompt = true` instead of just showing the toast (or show both — toast + open panel).
4. On save: write `customEmail` / `customPassword` / `useCustomCreds: true` into `runConfig`, close the panel, and auto-retry the start.
5. Consider also surfacing an "Enter Custom credentials" button in the existing error toast so the user has an explicit way in when the pop-up is dismissed.

**Test surface**: mirror `GhostCredentialPanel.test.tsx` — happy path, dismiss, retry-after-save.

**Related prior work**: `feature/FEAT-116-ghost-login-credential-prompt` (merged; TASK-125 archived) shipped the Ghost side of this pattern. This task is the Custom-credentials sibling gap.

## Out of Scope

- Reworking `SelectView.tsx` credential UI.
- Backend / Computer-Use loop credential handling changes.
- Ghost Login flow.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Phase Number**: 1 of 1
**Is Multi-Phase**: NO
**Build Started**: 2026-08-12T00:00:00Z
**Can Resume**: NO

### Current Build Step
**Step**: Archive complete
**Status**: COMPLETE

### Completed Steps
- Step 0.5 Git Setup: COMPLETE — on task/custom-creds-prompt-when-required (project root)
- Step 0.6 Phase Gate: COMPLETE — Level 1, no creative phases required
- Step 1 Read Task Context: COMPLETE — single phase, Level 1
- Step 2 Load Context: COMPLETE — Level 1 rules loaded
- Step 3 TDD Agent: COMPLETE — 5 tests in CustomCredentialPanel.test.tsx (RED→GREEN); CustomCredentialPanel.tsx + RunTestView.tsx wired
- Step 7 Integration Verify: COMPLETE — 5/5 new tests pass; 170/176 suite (4 pre-existing failures, unrelated)
- Step 8 Code Review: COMPLETE — TypeScript clean, mirrors GhostCredentialPanel pattern exactly
- Step 11 Git Completion: COMPLETE — committed + pushed
- Reflect Step 1 Verify Prerequisites: COMPLETE — BUILD_COMPLETE, in sync with origin/main
- Reflect Step 2 Load Complexity Context: COMPLETE — Level 1 reflection rules loaded
- Reflect Step 3 Reflection Agent: COMPLETE — Output: memory-bank/reflection/custom-creds-prompt-when-required-reflection.md (206 lines; Task Quality: Partial Success, Ecosystem: Moderately Effective)
- Reflect Step 4 Git Commit: COMPLETE
- Reflect Step 5 Report Completion: COMPLETE
- Archive Step 3 Create Archive Doc: COMPLETE — memory-bank/archive/custom-creds-prompt-when-required-archive.md
- Archive Step 4B Consolidate Learnings: COMPLETE — 2 bullets appended to browser-patterns.md (spa-storage-state-inject-then-reload, angular-dev-server-wait-until); frontmatter updated (evidence_count 5→6, derived_from appended)
- Archive Step 4C UX Freshness: COMPLETE — advisory only, no refresh needed (CustomCredentialPanel mirrors existing pattern)
- Archive Step 4D Mark Task Complete: COMPLETE — status: COMPLETE, archive link recorded
- Archive Step 5 Git Operations: COMPLETE — pushed feature branch, PR opened to main

### Guard & Recovery Log
(no failures)
