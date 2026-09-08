---
legacy_id: fair-quality-gate-hitl-pre-parse-guardrail
---
# fair-quality-gate-hitl-pre-parse-guardrail: FAIR Quality Gate HITL Pre-Parse Guardrail

**Status**: ARCHIVE_COMPLETE
**Complexity**: Level 2
**Roadmap Link**: FEAT-077
**Branch**: feature/FEAT-077-fair-quality-gate-guardrail
**Worktree**: .worktrees/FEAT-077
**Pillar**: P1 — Jira Ingestion
**Gap ID**: P1-C
**Estimated Effort**: ~3h
**Created**: 2026-06-03

---

## Description

The AC quality gate currently passes FAIR-graded tickets silently into autonomous runs, even though FAIR-grade tickets require 3+ HITL escalations on average. This feature adds a pre-parse guardrail: when `quality_grade == "fair"`, the system sets `awaiting_pre_parse_guidance = True` on VQAState and surfaces a warning panel in the UI **before** the run proceeds.

The operator can supply `pre_parse_guidance` text or explicitly approve the run despite the FAIR grade. GOOD and POOR grades are unaffected — only FAIR triggers the guardrail.

---

## Acceptance Criteria

- **AC-ENTRY-1**: When a user initiates a run with a FAIR-grade ticket, they are redirected to a warning panel before the run starts (or before `ac_parser_node` runs).
- **AC-HAPPY-1**: When `quality_grade == "fair"`, `VQAState.awaiting_pre_parse_guidance` is set to `True` before execution starts.
- **AC-HAPPY-2**: A warning panel is surfaced in the UI listing the specific FAIR-grade deficiencies detected by the quality gate.
- **AC-HAPPY-3**: The operator can enter `pre_parse_guidance` text directly in the warning panel and click "Proceed" to continue.
- **AC-HAPPY-4**: The operator can click "Proceed Anyway" to bypass the guardrail without guidance text (approved override is logged at INFO level).
- **AC-EDGE-1**: GOOD and POOR grades are unaffected — only FAIR triggers the guardrail.
- **AC-EDGE-2**: When the operator provides guidance and proceeds, the `pre_parse_guidance` text is available to `ac_parser_node`'s Stage 1 BDD Normalizer.
- **AC-EDGE-3**: The FAIR guardrail does not trigger on re-runs that already have a `pre_parse_guidance` value set (i.e., the second kick does not double-block).

---

## Clarifications Needed

_None — requirements are clear from FEAT-077 specification._

---

## Implementation Roadmap

### 1. State Definition (`backend/engine/state.py`)
- Add `awaiting_pre_parse_guidance: bool` and `pre_parse_guidance_approved: bool` fields to the `VQAState` TypedDict.
- Initialize both fields to `False` in `make_initial_state`.

### 2. Schema and Endpoint Updates (`backend/api/schemas.py` & `backend/api/routes.py`)
- Add `awaiting_pre_parse_guidance` and `ac_quality` (optionally) to `StatusResponse` schemas so the HTTP query can retrieve pre-parse status.
- Add optional `pre_parse_guidance` and `pre_parse_guidance_approved` fields to the `ResumeRequest` model.
- Define `WSPreParseGuidanceMessage` class (type: `"pre_parse_guidance_required"`).
- Implement `_broadcast_pre_parse_guidance_required` helper in `routes.py` to stream pre-parse warning events.

### 3. Guardrail Interception (`backend/engine/ac_parser.py`)
- Define a module-level variable `_pre_parse_events: dict[str, asyncio.Event] = {}` to manage suspended parser nodes.
- Inside `ac_parser_node`, immediately after calculating `quality_result = score_ac_quality(raw_ac)`:
  - If `quality_result.quality_grade == "fair"`, `pre_parse_guidance` is empty, and `state.get("pre_parse_guidance_approved")` is not `True`:
    - Update `_run_states[run_id]["status"] = "paused"`.
    - Set state fields: `awaiting_pre_parse_guidance = True` and `ac_quality_result = quality_result.to_dict()`.
    - Broadcast `"pre_parse_guidance_required"` over WebSockets with the deficiencies warnings list.
    - Set `_pre_parse_events[run_id] = asyncio.Event()` and block with `await _pre_parse_events[run_id].wait()`.
  - When resumed:
    - Pop `updates` from `_resume_data`.
    - Save updated `pre_parse_guidance` and `pre_parse_guidance_approved` into the state.
    - Log the operator actions at `INFO` level (either logging approved bypass override or the custom pre-parse guidance text).
    - Clear the event from `_pre_parse_events`.
    - Proceed to Stage 1 BDD Normalization with the newly supplied pre-parse guidance context merged.

### 4. Resume Integration (`backend/api/routes.py`)
- Update `POST /run/{run_id}/resume` to check for `_pre_parse_events` and set the event after storing incoming parameters in `_resume_data`.

### 5. UI warning panel (`frontend/src/`)
- Declare `WSPreParseGuidanceMessage` in `types/index.ts`.
- In `hooks/useWebSocket.ts`, intercept `"pre_parse_guidance_required"` and set `preParseGuidanceRequest` state.
- In `RunningView.tsx` / `RunTestView.tsx`, render a warning panel listing the deficiencies and allowing the operator to type guidance or click "Proceed Anyway".

---

## Test Strategy

### 1. Backend Integration Tests (`tests/test_task_096_pre_parse_guardrail.py`)
- **Test Fair Grade Blocks**: Assert that running a ticket with FAIR ACs triggers the guardrail, sets `awaiting_pre_parse_guidance = True` and status to `"paused"`.
- **Test Proceed with Guidance**: Verify that submitting guidance text unblocks execution, logs the guidance, and merges it into BDD Normalizer.
- **Test Proceed Anyway**: Verify that clicking "Proceed Anyway" unblocks execution, logs approved bypass override at `INFO` level, and completes parsing.
- **Test Good/Poor Grades**: Assert that GOOD tickets run silently without blocking and POOR tickets hard-reject as before.
- **Test No Double-Blocking**: Assert that runs initiated with pre-existing `pre_parse_guidance` or `pre_parse_guidance_approved` skip the guardrail block entirely.

### 2. Frontend Component Verification
- Verify that the warning panel displays specific warnings correctly and triggers the `/resume` request appropriately.

---

## Creative Phases

_None required — Level 2, journey is clear._

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: ARCHIVE
**Current Step**: IDLE
**Build Started**: 2026-06-03T15:22:00Z
**Completed**: 2026-06-03T15:47:00Z
**Merge Commit**: 003bdd4 → main
**Can Resume**: NO

---

## Session Log

### 2026-06-03 — Planning Session Completed
- Provisioned fair-quality-gate-hitl-pre-parse-guardrail from FEAT-077 (Level 2)
- Codebase analysis complete
- Key files identified: `ac_parser.py`, `state.py`, `routes.py`, `schemas.py`, `RunningView.tsx`, `useWebSocket.ts`, `types/index.ts`
- Confirmed existing patterns: HITL asyncio.Event pause (human_takeover), _pause_events/_resume_data dicts, WS broadcast helpers
- Guardrail placement: after `score_ac_quality()` call at line ~859 in `ac_parser.py`, before Stage 1 BDD normalization
- State fields confirmed: `awaiting_pre_parse_guidance: bool`, `pre_parse_guidance: str` (already in VQAState via make_initial_state)
- `pre_parse_guidance` already exists in `VQAState` and `make_initial_state` — no new state field needed for guidance text
- `awaiting_pre_parse_guidance: bool` is the only new VQAState field required
- **Status**: PLANNING_COMPLETE — ready for `/vc-build fair-quality-gate-hitl-pre-parse-guardrail`
