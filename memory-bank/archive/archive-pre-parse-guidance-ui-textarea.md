# Archive: pre-parse-guidance-ui-textarea — Pre-Parse Guidance UI Textarea

**Archived**: 2026-06-03  
**Status**: COMPLETE  
**Complexity**: Level 2  
**Feature**: FEAT-084 (Pre-Parse Guidance UI Textarea)  
**Branch**: `feature/FEAT-084-pre-parse-guidance-ui`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/main

---

## What Was Built

We built and integrated the frontend UI for the existing `pre_parse_guidance` parameter of the VQA state engine. This parameter allows operators to supply critical pre-parse instructions directly to the stage 1 parser.

### Key Design Decisions
- **Unmount State Isolation via React Keys**: Keying the `ReviewView` instantiations in `RunTestView.tsx` using `selectedTicket.id` was used to handle local editing state cleanup. This ensures that React completely discards the old DOM/state and mounts a fresh form for any new ticket, avoiding cross-ticket state bleeding.
- **Robust Local Props Synchronizer**: In addition to component keys, stateful prop synchronization inside `ReviewView` allows external updates to the `config.preParseGuidance` object (e.g. from parent state refetches) to update the textarea value dynamically.
- **Flexbox Spacing for Labels & Counters**: Laid out the input label and character counter in a flex container with `justify-content: space-between` to keep the UI clean, modern, and aligned with design guidelines.

---

## Implementation Summary

### Files Changed (3 files, +161 net lines added, -7 lines deleted)

| File | Change |
|------|--------|
| `frontend/src/components/ReviewView.tsx` | Added stateful pre-parse guidance textarea, character limit counter (2000-char cap), dynamic synchronization, and update handler. |
| `frontend/src/components/RunTestView.tsx` | Updated `handleStartTest` and component props mapping to pass guidance in execution payload. |
| `frontend/src/components/__tests__/ReviewView.test.tsx` | Added 5 brand-new unit tests covering mounting, character counting, state mapping, and callback execution. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Tests written | 5 brand-new unit tests |
| Tests passing | 65/65 (100%) in frontend suite |
| Dependent tests passing | 60/60 (100%) |
| Regressions introduced | 0 |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| AC-ENTRY-1 | ✅ PASS | Textarea renders below the `StepTable` in `ReviewView`, with label "Additional Context (Pre-Parse Guidance)" and high-clarity placeholder text. |
| AC-HAPPY-1 | ✅ PASS | Clicking "Start Test" passes the typed textarea value to `onStartTest` which `RunTestView` POSTs under the `pre_parse_guidance` field of `ExecuteRequest`. |
| AC-HAPPY-2 | ✅ PASS | Textarea is successfully pre-populated with `config.preParseGuidance` on load and resets properly without state bleeding when switching between tickets. |
| AC-ERROR-1 | ✅ PASS | Text length is capped at 2000 characters. Dynamic character counter updates in real time and enforces input truncation. |

---

## Rule Consolidation (Archive Phase)

No rules were pruned because `frontend-patterns.md` remains well below its size threshold.

**Files amended in reflection**:
- `memory-bank/agent-rules/_learned/frontend-patterns.md` (+2 rules: `keyed-local-state-isolation`, `form-label-counter-alignment`)

---

## Retrospective Notes

See full reflection at [reflection-pre-parse-guidance-ui-textarea.md](../reflection/reflection-pre-parse-guidance-ui-textarea.md).

**Key Learnings**:
- **Key inputs to isolate local state when switching active items**: Keying components at the call-site with unique IDs (e.g. `key={selectedTicket.id}`) is a robust, declarative way to discard old local component state on change.
- **Space-between flex headers for labels and limit counters**: Aligning counters and labels with `justify-content: space-between` prevents layout line-wrapping and keeps character limits clean on modern high-signal interfaces.

---

## Next Work

- **intelligent-ingestion-and-pre-flight-verification: Intelligent Ingestion & Pre-Flight Verification (FEAT-070)** — Hybrid LLM-in-the-Loop Enricher and negative path synthesis.
