# vPromotions — Revise an Approved PRF
# =====================================
# Source: vsuiteHotfix codebase.

## WORKFLOW: Revise an already-approved PRF
KEYWORDS: revise prf, prf revision, revise promotion, revise approved prf, edit approved prf, is_revise, btn_revise_prf, continue to revise, revise the prf, revise a prf, revise the promotion, revise this prf, revise the approved, modify approved prf, change approved prf, update approved prf, prf revise button, revise flow, revise workflow
---
Applies when the user has visibility of an approved PRF whose event action
menu offers "Revise" (`.btn_revise_prf` — attached at functions.js.html.twig:5791,
:5797). Revising re-opens the PRF drawer with `is_revise=true`, which
changes the status computation on save.

PRECONDITIONS:
- Home tab fully rendered (wf-auth-and-sso).
- Register `page.on('dialog', d => d.accept())` — flow can invoke discard
  confirm if another drawer was open.

STEPS:

1. Open the target PRF's context menu on the calendar.
   Locate: a `.fc-event` for the target PRF (FullCalendar event render).
   Some approved PRFs expose the menu on hover (implementation-specific
   — inspect the DOM near the `.fc-event`).
   Precondition: calendar rendered (`#promo-calendar .fc.fc-ltr`) AND the
   target `.fc-event` visible.
   Wait for a menu appearing with:
       <a class="btn_revise_prf" data-prf-id="<id>">…</a>
   (functions.js.html.twig:5791). If NOT present, the PRF status is not
   eligible OR the user lacks permission — treat as PRECONDITION_MISSING.
   Do not fabricate a Revise button.

2. Click `a.btn_revise_prf[data-prf-id='<id>']`.
   Delegate at delegates.js.html.twig:22078.
   A confirmation modal is DYNAMICALLY BUILT (delegates.js.html.twig:22080-22117):
      - `<div class="modal fade">` inserted with body text
        "By Revising this PRF, the original will be locked until the
         Revision is fully Approved. No Plays, Liners, Equipment, or
         People will be added until the Revision is Complete."
      - Two footer buttons:
          .btn.btn-link labeled "Cancel"
          .btn.btn-primary labeled "Continue To Revise"
      - `.modal('show')` is called
   The modal has NO static id — it is built inline. Do NOT locate by id.
   Wait for `div.modal.in:visible` containing
   `button.btn-primary:has-text('Continue To Revise')`.

3. Click "Continue To Revise".
   Locate: `div.modal.in button.btn-primary:has-text('Continue To Revise')`
   (scoped to just-opened modal).
   Expected result:
      - Confirmation modal closes
      - PRF drawer `#prf_form_rightview` opens populated with the existing
        record via `show_event_form(record, date)` (functions.js.html.twig:13432
        or event.js.html.twig:48)
      - `#prf_form_rightview form[id$='_form']` field values pre-filled
      - `.form-buttons button[type=submit]` receives class `is_revise`
        (prf.js.html.twig:582) — used at save-time to compute the new status
   Verify: `#prf_form_rightview:visible` AND
           `#prf_form_rightview input[id$='_id']` has the existing PRF's
           numeric id AND
           `#prf_form_rightview .form-buttons button[type=submit].is_revise`
           exists.

4. Modify one or more fields.
   Use the same field recipes as create (see wf-create-prf). Any change
   sets `#prf_form_rightview.data('modified') === true` (prf.js.html.twig:4).
   Note: for fields with dependent cascades (category → stations filtering;
   stations → sales_person), changing an upstream field can auto-clear
   downstream ones. Re-fill dependents after upstream changes.

5. Save the revision.
   Locate: `#prf_form_rightview .prf_submit` — same button as create, but
   the click also carries `is_revise` class.
   Sequence at prf.js.html.twig:466-524 computes the new status_code_id
   based on `is_revise=true`, user role, and station's approval config:
      - If station has custom_approval_process → walk to the next role
        in the chain
        (SALES_MANAGER=35 → PROMOTIONS_DIRECTOR=37 → OTHER=39 → GM=40 → LIVE=41)
      - Baseline: ROLE_SALES_PERSON → status 35
                  ROLE_SALES_MANAGER → status 37
      - If prior status was 90 → status 91
   POST fires; on success `saved.formbuilder` (prf.js.html.twig:593) with
   e.new_record=false. `is_revise` class is REMOVED from the submit
   button (prf.js.html.twig:606). `.toast-success` appears.
   Verify: `.toast-success` within 10s AND
           `#prf_form_rightview .form-buttons button[type=submit]:not(.is_revise)`.

DIFFERENCES vs create-prf-happy-path:
- Entry point: `.btn_revise_prf` context-menu action, NOT `#create_new_prf`
  toolbar button.
- Intermediate confirmation modal (dynamically built, no stable id).
- Save-button computation uses `is_revise` path, NOT
  `new_prf_status[role]`.
- `saved.formbuilder` sees `e.new_record === false`; downstream
  side-effects (e.g., "Create PRF" gTag firing at prf.js.html.twig:684)
  are skipped.

FAILURE MODES:
- Partial approval-chain state can make the computed status unexpected.
  If asserting on visible status label (e.g., `.prf_status_code_id_info`
  text), verify against the STATUSES map — not against a hardcoded string.
- Locating the confirmation modal by id → fails; it has no id.
- Assuming Cancel in the confirmation modal aborts the revision AND closes
  the PRF drawer → the drawer never opened yet at that point, so Cancel
  simply dismisses the confirmation.
