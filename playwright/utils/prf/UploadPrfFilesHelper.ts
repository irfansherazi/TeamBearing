/**
 * UploadPrfFilesHelper.ts — Attach files to a PRF via the initial-file
 * upload modal (Dropzone.js).
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/prf-file-upload.md
 *
 * Widget shape (formbuilder.js.html.twig:378-399): the anchor
 *   `<a class="btn pull-right upload_inital_prf_files">Click Here to Add File</a>`
 * is NOT a native <input type="file"> — clicking it opens the Bootstrap 3
 * modal `#upload_prf_files_modal` (delegate at delegates.js.html.twig:20373).
 *
 * The modal contains:
 *   - Required text input `#initial_prf_file_descr.input_required.form-control`
 *   - Dropzone container `#initial_prf_files_path.dropzone.x-browser-dropzone`
 *   - Submit `#inital_prf_file_save` (sic — "inital", per upload_prf_files_modal.html.twig)
 *   - Cancel `.modal-footer .btn-link[data-dismiss='modal']`
 *
 * Dropzone config (upload_prf_files_modal.html.twig:42-52):
 *   - URL: promo_process_upload
 *   - maxFilesize: 100 (MB)
 *   - maxFiles: 5
 *   - autoProcessQueue: false — Submit triggers processQueue()
 *   - parallelUploads: 5, uploadMultiple: true
 *
 * Availability rule (prf.js.html.twig:107-109): the upload widget is HIDDEN
 * in edit mode (`.file_upload_div.hidden`). Only offered on the initial
 * create path. Use isUploadWidgetAvailable() to check before invoking.
 */

import { expect, Page } from '@playwright/test';

/**
 * Runbook "Availability rule": widget is only offered during initial create,
 * not in edit mode.
 */
export async function isUploadWidgetAvailable(page: Page): Promise<boolean> {
    const anchor = page.locator('#prf_form_rightview .upload_inital_prf_files').first();
    return await anchor.isVisible({ timeout: 1500 }).catch(() => false);
}

/**
 * STEP 1: Open the upload modal.
 *
 * Scoped to `#prf_form_rightview` to avoid a strict-mode collision if a copy
 * of the anchor renders elsewhere. Do NOT locate by text ("Click Here to Add
 * File") — the text is not unique.
 *
 * Bootstrap 3 does not queue modals cleanly — if another modal is still open,
 * `shown.bs.modal` may not fire. We defensively wait for any existing
 * `.modal.in` to disappear first.
 */
export async function openUploadModal(page: Page): Promise<void> {
    // Guard: dismiss any preceding modal.
    const priorModal = page.locator('.modal.in').first();
    if (await priorModal.isVisible({ timeout: 300 }).catch(() => false)) {
        console.log('📎 openUploadModal: a prior .modal.in is still visible — waiting for it to close');
        await priorModal.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
    }

    const anchor = page.locator('#prf_form_rightview .upload_inital_prf_files').first();
    await expect(anchor).toBeVisible({ timeout: 5000 });
    await anchor.click();

    const modal = page.locator('#upload_prf_files_modal.modal.in');
    await expect(modal).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#initial_prf_file_descr')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('#initial_prf_files_path')).toBeVisible({ timeout: 3000 });
    console.log('📎 openUploadModal: #upload_prf_files_modal opened');
}

/**
 * STEP 2: Fill the description (required). Enter is intercepted
 * (upload_prf_files_modal.html.twig:154-158) — DO NOT press Enter to commit.
 * Use blur or Tab.
 */
export async function fillUploadDescription(page: Page, description: string): Promise<void> {
    if (!description || !description.trim()) {
        throw new Error('fillUploadDescription: empty description will be rejected at Submit — "Please enter valid file description."');
    }
    const input = page.locator('#initial_prf_file_descr');
    await expect(input).toBeVisible({ timeout: 3000 });
    await expect(input).toBeEnabled({ timeout: 3000 });
    await input.fill(description);
    // Commit via blur, NOT Enter.
    await input.press('Tab').catch(() => {});
    console.log(`📎 fillUploadDescription: "${description}"`);
}

/**
 * STEP 3: Attach files to the Dropzone.
 *
 * Runbook approach: Dropzone injects a hidden `<input type="file">` inside
 * `.dropzone` on init. `page.setInputFiles()` on that hidden input triggers
 * Dropzone's `addedfile` event correctly. This is more reliable than dispatching
 * a synthetic drag-drop with a DataTransfer payload.
 *
 * Enforcement (client-side):
 *   - maxFiles: 5 — extras go to getRejectedFiles(), Submit will toastr.error.
 *   - maxFilesize: 100 MB — rejected with a Dropzone `error` event.
 *
 * @param filePaths - absolute paths to files (up to 5, each ≤ 100 MB).
 */
export async function attachFilesToDropzone(
    page: Page,
    filePaths: string[]
): Promise<void> {
    if (filePaths.length === 0) return;
    if (filePaths.length > 5) {
        throw new Error(`attachFilesToDropzone: ${filePaths.length} files exceeds Dropzone maxFiles=5.`);
    }

    // Dropzone injects a hidden input inside .dropzone on init.
    const hiddenInput = page.locator('#initial_prf_files_path input[type="file"]').first();
    // Use `dispatchEvent`-safe injection via setInputFiles.
    await hiddenInput.setInputFiles(filePaths);

    // Each queued file renders a preview node.
    const previews = page.locator('#initial_prf_files_path .dropzone-previews .dz-preview');
    await expect(previews).toHaveCount(filePaths.length, { timeout: 8000 });
    console.log(`📎 attachFilesToDropzone: queued ${filePaths.length} file(s)`);
}

/**
 * STEP 4: Click Submit to process the queue.
 *
 * Sequence (upload_prf_files_modal.html.twig:112-142):
 *   1. loading_spinner.init(#upload_prf_files_modal, 'upload_spinner')
 *   2. thisDropzone.processQueue() → multi-file POST to promo_process_upload
 *   3. `sendingmultiple` (:76-109) — appends g_prf_id per file to formData
 *   4. `successmultiple` (:70-75) → toastr.success → `$('.modal').modal('hide')`
 *
 * IMPORTANT: `$('.modal').modal('hide')` at line 74 hides ALL open modals.
 * If the PRF drawer opened a modal on top before Submit fired, that modal
 * will also close. Caller should sequence upload BEFORE opening any other
 * modal.
 */
export async function submitUploadModal(
    page: Page,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; toast: string }> {
    const { timeout = 60000 } = options;

    const submit = page.locator('#inital_prf_file_save');
    await expect(submit).toBeVisible({ timeout: 3000 });
    await expect(submit).toBeEnabled({ timeout: 3000 });

    // Sanity: at least one preview queued.
    const previews = page.locator('#initial_prf_files_path .dropzone-previews .dz-preview');
    const previewCount = await previews.count();
    if (previewCount === 0) {
        throw new Error('submitUploadModal: no dz-preview elements — Submit will fire "Must attach a file to upload".');
    }

    await submit.click();

    // Race success vs error toast (error toast if server-side validation failed,
    // network hang, or Dropzone error event).
    const successToast = page
        .locator('.toast-success, .toast-message.toast-success')
        .filter({ hasText: /file\(s\) successfully attached/i })
        .first();
    const errorToast = page
        .locator('.toast-error, .toast-message.toast-error')
        .first();

    const winner = await Promise.race([
        successToast.waitFor({ state: 'attached', timeout }).then(() => 'success' as const).catch(() => null),
        errorToast.waitFor({ state: 'attached', timeout }).then(() => 'error' as const).catch(() => null),
    ]);

    if (winner === 'error') {
        const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
        console.log(`❌ submitUploadModal: error toast "${msg}"`);
        return { ok: false, toast: msg };
    }
    if (winner !== 'success') {
        console.warn('⚠️ submitUploadModal: no toast within timeout — spinner may still be spinning on hung network');
        return { ok: false, toast: '' };
    }

    // On success `$('.modal').modal('hide')` fires — modal should be gone.
    await expect(page.locator('#upload_prf_files_modal.in')).toBeHidden({ timeout: 5000 }).catch(() => {});
    const msg = ((await successToast.textContent().catch(() => '')) || '').trim();
    console.log(`✅ submitUploadModal: "${msg}"`);
    return { ok: true, toast: msg };
}

/**
 * STEP 5 (alternate CANCEL path): Dismiss the modal without uploading.
 *
 * The `hidden` event handler (upload_prf_files_modal.html.twig:148-152)
 * cleans up:
 *   - thisDropzone.removeAllFiles(true)
 *   - #initial_prf_file_descr.val('')
 *   - loading_spinner.remove('upload_spinner')
 *
 * Rapid double-click on Cancel can race the removeAllFiles cleanup; queued
 * files may then linger for the next open. Single click is safe.
 */
export async function cancelUploadModal(page: Page): Promise<void> {
    const modal = page.locator('#upload_prf_files_modal.modal.in');
    await expect(modal).toBeVisible({ timeout: 3000 });

    const cancelBtn = modal.locator('.modal-footer button.btn-link[data-dismiss="modal"]').first();
    await expect(cancelBtn).toBeVisible({ timeout: 2000 });
    await cancelBtn.click();

    // Verify the modal is dismissed AND the cleanup ran.
    await expect(modal).toBeHidden({ timeout: 5000 });
    await expect(page.locator('#initial_prf_file_descr')).toHaveValue('', { timeout: 3000 });
    await expect(
        page.locator('#initial_prf_files_path .dropzone-previews .dz-preview')
    ).toHaveCount(0, { timeout: 3000 });
    console.log('📎 cancelUploadModal: modal dismissed, description + previews cleared');
}

/**
 * Orchestrator: open → describe → attach → submit.
 *
 * @param description  a non-empty description (required)
 * @param filePaths    absolute paths (1..5 files, each ≤ 100 MB)
 */
export async function uploadPrfFiles(
    page: Page,
    description: string,
    filePaths: string[],
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; toast: string }> {
    if (!(await isUploadWidgetAvailable(page))) {
        throw new Error(
            'uploadPrfFiles: .upload_inital_prf_files anchor is not visible. ' +
            'Either the drawer is in edit mode (.file_upload_div is hidden) or no `file` field exists on this record.'
        );
    }
    await openUploadModal(page);
    await fillUploadDescription(page, description);
    await attachFilesToDropzone(page, filePaths);
    return submitUploadModal(page, options);
}
