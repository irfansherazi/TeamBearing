# vPromotions — Submit or Cancel PRF Drawer
# ==========================================
# Source: vsuiteHotfix codebase.

## WORKFLOW: Save (submit) a PRF from the drawer
KEYWORDS: save prf, submit prf, prf save, prf submit, save button, submit button, prf_submit, finalize prf, complete prf form
---
The drawer's `.form-buttons` container holds up to three buttons, all
scoped to `#prf_form_rightview`. Save is the primary submit:

   Text:   Save
   Class:  btn btn-primary prf_submit
   Type:   submit
   Source: formbuilder.js.html.twig:1178-1189
           (config.id == 'prf' → prf_class = 'prf_submit')

Visibility depends on record status (functions.js.html.twig:13460-13464):
   - `record.status_code_id == 33` (PRF Draft) → `.prf_submit` is `.hidden`
     via addClass('hidden'). Use `.btn-is-draft` (Save Draft) instead — see
     the Save-Draft workflow below.
   - Otherwise → `.prf_submit` is visible.

STEPS:

1. Locate: `#prf_form_rightview .prf_submit`. NEVER use unscoped
   `get_by_text('Save')` — SURFACE D collision. There are ~8+ "Save" buttons
   across the page (loading_modal, various tab-specific modals).

2. Precondition wait: `#prf_form_rightview .prf_submit:not(:disabled)`
   AND the button is not `.hidden` (checked via
   `!$('#prf_form_rightview .prf_submit').hasClass('hidden')` — Playwright's
   `:visible` may still see a `.hidden`-classed element depending on
   applied CSS).

3. Click the button.

4. Expected sequence:
      a. Transient: `#submit_prf_spinner` may briefly appear (removed at
         prf.js.html.twig:617).
      b. formbuilder fires `field-serialize.formbuilder` per field
         (prf.js.html.twig:466 handles this) — validators can veto here
         and produce a `.toast-error`.
      c. Server round-trip: on success `saved.formbuilder` (prf.js.html.twig:593);
         on rejection `save-failed.formbuilder` (formbuilder.js.html.twig:2016,
         :2034, :2053) followed by `.toast-error`.
      d. UI: `.toast-success` appears within ~10s AND EITHER (a)
         `#prf_form_rightview` becomes hidden OR (b) drawer stays open in
         edit-mode with `#prf_form_rightview input[id$='_id']` now holding
         the numeric record id.

5. Verify (positive):
      `.toast-success:visible`
      AND (`#prf_form_rightview:hidden`
           OR `#prf_form_rightview input[id$='_id']` value is numeric)

FAILURE MODES:
- SURFACE D strict-mode collision → scope with `#prf_form_rightview`.
- Toastr can render below viewport in some resolutions — assert PRESENCE,
  not visibility.
- `save-failed.formbuilder` fires and drawer stays open — do not treat
  drawer-open as failure. Look for `.toast-error` too.

## WORKFLOW: Save PRF as Draft (Save Draft button)
KEYWORDS: save draft, prf draft, draft save, is-draft, keep as draft, save without submitting
---
Save Draft is a separate button that formbuilder does not create — it is
prepended by the PromoBundle prf.js hook (prf.js.html.twig:52-67):

   Text:   Save Draft
   Class:  btn btn-default btn-is-draft
   Type:   button (not submit)

Behavior: click marks the drawer with `data-$save-draft=true`, then
triggers a click on the primary submit button anyway (prf.js.html.twig:62-66).
From that point, the flow is identical to the Save workflow.

STEPS:

1. Only relevant when `record.status_code_id == 33` (Draft). Precondition:
      #prf_form_rightview .btn-is-draft:visible
      AND #prf_form_rightview .prf_submit.hidden

2. Click `#prf_form_rightview .btn-is-draft`. Do NOT locate by text alone.

3. Follow the Save workflow post-conditions from step 4 onward.

## WORKFLOW: Cancel the PRF drawer without saving
KEYWORDS: cancel prf, discard prf, close prf drawer, prf_cancel_button, abandon prf, back out of prf
---
Cancel is a jQuery-appended button (prf.js.html.twig:71-91):

   Text:   Cancel
   Class:  btn btn-link prf_cancel_button
   Type:   button (not submit)

CRITICAL CORRECTION: Cancel does NOT hide the drawer. It calls
`resize_promo_cal('full')` (prf.js.html.twig:89), which expands the
calendar back to full width and visually covers the drawer.
`#prf_form_rightview` DOM node REMAINS and may still be `:visible` by
pixel. vQA checks like `#prf_form_rightview:hidden` after Cancel will
falsely fail.

STEPS:

1. Locate: `#prf_form_rightview .prf_cancel_button`. Scope explicitly —
   "Cancel" text appears in many modals.

2. Precondition: `#prf_form_rightview .prf_cancel_button:visible`.

3. Click.

4. Click handler runs SYNCHRONOUSLY (prf.js.html.twig:76-90) and:
      a. Forces `$('#prf_form_rightview').data('modified', false)` — this
         DEFEATS any downstream discard-confirm.
      b. Re-enables non-`.forceHide` `<option>`s inside
         `select[name='_category']` (removes `disabled`, `.hidden`).
      c. Calls `resize_promo_cal('full')` — calendar expands over the
         drawer.
   A separate document delegate at delegates.js.html.twig:26390 also fires:
      d. Removes `.hidden` on `.prf_detail_copy_edit_div`.
      e. Layout reset: `.prf_detail_left_column` gets `col-md-12`
         (removes `col-md-8`).
      f. Resets `prfClientFirmId`.

5. Verify (in order of preference):
      - `#promo-calendar` bounding-box width equals its parent's inner
        width (calendar reflowed to full), OR
      - `$('#prf_form_rightview').data('modified') === false`
        (readable via page.evaluate)

FAILURE MODES:
- Assuming drawer hides on Cancel — it does not.
- Waiting for a network event or toast — Cancel is client-side only,
  no POST, no toast, no navigation. Any wait for those will time out.
- Rapid double-click is idempotent-safe (no additional effect).

## WORKFLOW: Handle "Discard unsaved modifications?" browser confirm
KEYWORDS: discard changes, unsaved changes, confirm dialog, discard modifications, prf modified warning
---
Trigger: attempting to open a second PRF form while the current drawer
has `#prf_form_rightview.data('modified') === true`. Fires
`window.confirm('Discard unsaved modifications?\n\nNote: click \'Cancel\'
to keep the changes.')` at functions.js.html.twig:13440.

Note the inverted labelling: `Cancel` in the confirm KEEPS changes;
`OK` DISCARDS them.

Preemptive handling (mandatory):
   page.on('dialog', d => d.accept())    # DISCARDS the changes
   OR
   page.on('dialog', d => d.dismiss())   # KEEPS the current form open

Register BEFORE the trigger (any action that could open a new form). If
Playwright auto-dismisses (returns false), `show_event_form` bails and the
second form does NOT open.

Note: Cancel button (see workflow above) sets data-modified=false before
this check would ever fire, so Cancel-then-Reopen never hits this dialog.
