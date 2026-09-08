# vPromotions — PRF File Upload
# ==============================
# Source: vsuiteHotfix codebase.

## WORKFLOW: Upload a file to a new PRF via the drawer's "Click Here to Add File" link
KEYWORDS: prf upload, upload file, attach file, click here to add file, prf attachment, initial prf files, dropzone, upload prf files modal
---
The upload widget is Dropzone.js — NOT a native `<input type=file>`. This
changes the Playwright interaction pattern entirely. Availability:
edit-mode HIDES `.file_upload_div` (prf.js.html.twig:107-109), so this
workflow ONLY applies to the initial create path.

WIDGET ANATOMY (formbuilder.js.html.twig:378-399):

The `file` field type in formbuilder emits:

   <div id="<form-id>_<field>" class="select2-container select2-container-multi form-control">
     <a class="btn pull-right upload_inital_prf_files" title="Add File">
       <i class="fa fa-plus"></i> Click Here to Add File
     </a>
     <input id="hidden_generic_prf_id" name="hidden_generic_prf_id" value="" class="hidden">
   </div>

The clickable trigger is the `<a>`. On click, delegate at
delegates.js.html.twig:20373-20379 opens `#upload_prf_files_modal` and
sets `data-prf-id` on `#inital_prf_file_save`.

MODAL CONTENTS (upload_prf_files_modal.html.twig):
   - Description input (REQUIRED):
       input#initial_prf_file_descr.input_required.form-control
   - Dropzone container:
       #initial_prf_files_path.prf_files_path_initially.dropzone.x-browser-dropzone
       (upload_prf_files_modal.html.twig:18)
   - Cancel button:
       .modal-footer button.btn.btn-link[data-dismiss='modal']  (text: Cancel)
   - Submit button:
       #inital_prf_file_save.btn.btn-primary.save_initial_prf_files  (text: Submit)

DROPZONE CONFIG (upload_prf_files_modal.html.twig:42-52):
   - URL:                 Symfony route `promo_process_upload`
   - maxFilesize:         100 MB per file
   - maxFiles:            5
   - autoProcessQueue:    false — files queue locally; Submit fires the POST
   - parallelUploads:     5
   - uploadMultiple:      true

STEPS:

1. Open the upload modal.
   Locate: `#prf_form_rightview .upload_inital_prf_files` (scope to drawer
   to avoid strict-mode collisions if a copy renders elsewhere).
   Do NOT locate by text ("Click Here to Add File") — not unique enough.
   Precondition: `#prf_form_rightview .upload_inital_prf_files:visible`.
   Click.
   Wait for `#upload_prf_files_modal.modal.in:visible` AND its `.modal-body`
   rendered. Verify: `#initial_prf_file_descr:visible` AND
   `#initial_prf_files_path:visible`.

2. Enter a description (required).
   Locate: `#initial_prf_file_descr`.
   `.fill('<description>')` — plain text input.
   Do NOT press Enter to commit — Enter is intercepted at
   upload_prf_files_modal.html.twig:154-158. Use blur / Tab.
   Empty description at Submit fires
      toastr.error('Please enter valid file description.')
   (upload_prf_files_modal.html.twig:118-120) and the modal STAYS OPEN.

3. Attach file(s) to the Dropzone.
   Target: Dropzone at `#initial_prf_files_path`.
   Max 5 files, ≤ 100 MB each.
   Playwright approach: Dropzone creates a hidden `<input type="file">`
   inside the `.dropzone` element on init. Target it via:
      page.set_input_files('#initial_prf_files_path input[type=file]', '<path>')
   This triggers Dropzone's `addedfile` event correctly. Alternative: dispatch
   a drag-drop with a `DataTransfer` payload — reliable but more complex.
   Wait for `.dropzone-previews .dz-preview` count equal to files supplied.
   Files > 100 MB or beyond maxFiles=5 are rejected (added to
   `getRejectedFiles()`); Submit will `toastr.error`.

4. Submit the upload.
   Locate: `#inital_prf_file_save` (note the typo — "inital" not "initial").
   Precondition: `#inital_prf_file_save:visible AND :enabled` AND
   `.dropzone-previews .dz-preview` count ≥ 1.
   Click.
   Sequence (upload_prf_files_modal.html.twig:112-142):
      a. loading_spinner.init() overlays the modal
      b. thisDropzone.processQueue() starts the POST to
         promo_process_upload
      c. Dropzone `sendingmultiple` handler builds g_prf_id values and
         appends to formData (:76-109)
      d. On success: `successmultiple` (:70-75) fires
         → toastr.success('File(s) successfully attached to PRF.')
         → $('.modal').modal('hide')
   Verify:
      .toast-success:contains('File(s) successfully attached')
      AND #upload_prf_files_modal:not(.in)

FAILURE MODES:
- `page.set_input_files("input[type=file]")` targeted at page level → NO
  MATCH. The only file input is INSIDE `#initial_prf_files_path` (injected
  by Dropzone on init). Always scope to that container.
- $('.modal').modal('hide') at line 74 hides ALL open modals. If the PRF
  drawer opened its own modal on top of the upload modal before Submit
  fired, that will also be dismissed.
- Network hang → the loading spinner has no hard timeout in the Dropzone
  config. Wait up to ~30s then treat as SCENARIO_FAILED.
- Server-side rejection → Dropzone `error` event. Modal does NOT auto-close.
  Look for `.toast-error`.

## WORKFLOW: Dismiss the upload modal without uploading
KEYWORDS: cancel upload, dismiss upload, close upload modal, abort file upload
---
   Target: #upload_prf_files_modal .modal-footer button.btn-link[data-dismiss='modal']
   Precondition: #upload_prf_files_modal.in:visible
   Click.
   The `hidden` handler at upload_prf_files_modal.html.twig:148-152 fires:
      - thisDropzone.removeAllFiles(true)
      - #initial_prf_file_descr cleared
      - loading_spinner.remove('upload_spinner')
   Verify: #upload_prf_files_modal:not(.in) AND
           #initial_prf_file_descr.val() === '' AND
           #initial_prf_files_path .dz-preview count === 0
   Rapid double-click can race the removeAllFiles cleanup; queued files may
   remain for a subsequent open.

## Skip rule

If the AC does not require attaching a file, SKIP this workflow. There is
NO server-side enforcement of the initial upload as a hard requirement on
a bare PRF create — the anchor is offered but not gated.
