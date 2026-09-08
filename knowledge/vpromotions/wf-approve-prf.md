# vPromotions — Approve a Pending PRF
# ====================================
# Source: vsuiteHotfix codebase.

## WORKFLOW: Approve a pending PRF from the calendar event card
KEYWORDS: approve prf, approve pending prf, prf approval, calendar approve event, yes approve, calendar-approve-event, event conflict modal, station approval, cat_app_process
---
Applies when the user has an approval role (SALES_MANAGER,
PROMOTIONS_DIRECTOR, OTHER, GM — event_approval.js.html.twig:57-84) and
the calendar surfaces a PRF whose event card renders the approval action.

This is a SINGLE CLICK on the calendar — no drawer opens. The PRF form
is NOT involved.

PRECONDITIONS:
- Home tab fully rendered (wf-auth-and-sso).
- Calendar events loaded — signalled by any `.fc-event` present.
- Approve links are appended into an event's `actions` HTML at
  fullcal.js.html.twig:619 and :780 based on
  `can_see_approve_buttons(prf.status_code_id, prf.created_by, prf)`
  (fullcal.js.html.twig:292). If not present, the current role/status
  combination is not eligible — PRECONDITION_MISSING (not vQA's failure).

STEPS:

1. Locate the target PRF's event card.
   `.fc-event` matching the target PRF (identify by title text or by
   `data-prf-id` when present — event.js.html.twig:40 sets
   `record.DT_RowId = record.id`).
   Inside eligible cards:
      <a class="calendar-approve-event" data-prf-id="<id>">Yes</a>
   (fullcal.js.html.twig:619). If not present, treat as PRECONDITION_MISSING.

2. Click the approve link.
   Locate: `a.calendar-approve-event[data-prf-id='<id>']` — SCOPE by
   `data-prf-id`. "Yes" appears on every eligible PRF card; unscoped
   matches multiple.
   Delegate: event_approval.js.html.twig:14.
   Sequence:
      a. The link is immediately disabled (event_approval.js.html.twig:15).
      b. `caldata_raw[prf_id]` is inspected to compute `newStatus`
         (branch by cat_app_process, custom_approval_process, or role-based
         default — see status transitions table below).
      c. `get_event_conflicts` runs (imported at event_approval.js.html.twig:11).
      d. If conflicts exist → `#event_conflict_modal` opens; proceed to
         STEP 3.
      e. If no conflicts → `update_prf_status(prf_id, newStatus)` runs,
         POSTing to a REST endpoint to persist the status.

3. IF `#event_conflict_modal` opens: resolve the conflict.
   Precondition: `#event_conflict_modal.modal.in:visible`.
   Click the resolution button — typically
   `#btn_event_conflict_approve` inside the modal
   (delegates.js.html.twig:9919).
   MUST scope by `#event_conflict_modal` — "Approve" text overlaps with
   the top-level `.calendar-approve-event`.
   After click:
      - Modal closes (`#event_conflict_modal:not(.in)`)
      - `.calendar-approve-event[disabled=false]` (reset per
        delegates.js.html.twig:9919-9921)
      - Status update proceeds
   Verify: modal closed AND `.toast-success`.

4. Verify status advanced.
   Signals:
      - `.toast-success` (or `.toast-info` for cases like PRF-Live
        transitions)
      - Event card re-renders — approve links may disappear (if new
        status not eligible for further approval by this user), or
        a different label appears
      - `caldata_raw[prf_id].status_code_id` in memory is updated
        to `newStatus`
   For automated assertion: check the rendered status label OR call the
   REST endpoint the app uses to fetch this PRF and confirm the new
   `status_code_id`.
   Re-render is asynchronous — wait for `.toast-success` AND at least
   one calendar re-draw before asserting.

STATUS TRANSITIONS (event_approval.js.html.twig:57-84 default branch):

| Role granting approval  | Prior status → new status |
|-------------------------|---------------------------|
| ROLE_SALES_MANAGER      | (any) → 37                |
| ROLE_PROMOTIONS_DIRECTOR| default → 41, or 39 if station.requires_other_approval, or 40 if station.requires_gm_approval |
| ROLE_OTHER              | prior 62 → 41; else 40 if station.requires_gm_approval; else 41 |
| ROLE_GM                 | → 41 (LIVE)               |

For stations with `custom_approval_process` (event_approval.js.html.twig:32-56),
the chain follows `custom_approval_number` — advance one step to the next
role's status code.

For PRFs currently at status 90 with `cat_app_process_id` set
(event_approval.js.html.twig:25-30), advance to next
`cat_app_process_step`; if next is 'LIVE', jump to status 41.

FAILURE MODES:
- Strict-mode collision on "Yes" text → scope by `data-prf-id`.
- Conflict modal's Approve button colliding with the calendar Approve
  link → scope by `#event_conflict_modal`.
- Asserting new status too fast → wait for `.toast-success` AND a
  calendar redraw.
- Hardcoding an expected status number → status computation depends on
  the station's `custom_approval_process`, `requires_other_approval`,
  `requires_gm_approval`, and the PRF's `cat_app_process_id`. Assert
  via the status label lookup or REST endpoint, not a hardcoded int.
