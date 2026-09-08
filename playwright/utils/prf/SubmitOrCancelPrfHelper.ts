/**
 * SubmitOrCancelPrfHelper.ts — Save / Save Draft / Cancel actions on the
 * PRF drawer (`#prf_form_rightview`).
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/submit-or-cancel-prf.md
 *
 * Button anatomy (all scoped to `#prf_form_rightview .form-buttons`):
 *   - Save         → `.prf_submit` (btn btn-primary, type=submit)
 *                    formbuilder.js.html.twig:1178-1189 sets class when config.id == 'prf'
 *   - Save Draft   → `.btn-is-draft` (btn btn-default, type=button)
 *                    prf.js.html.twig:52-67 prepends via draw.formbuilder hook
 *   - Cancel       → `.prf_cancel_button` (btn btn-link, type=button)
 *                    prf.js.html.twig:71-91
 *
 * Save vs Save Draft visibility (functions.js.html.twig:13460-13464):
 *   status_code_id == 33 (Draft): .prf_submit is .hidden — use .btn-is-draft
 *   Otherwise: .prf_submit visible
 *
 * IMPORTANT — visibility is via `.hidden` class, NOT `display:none`
 * (prf.js.html.twig:256-259). Playwright's `:visible` may still see a
 * `.hidden` element. Use `hasClass('hidden') === false` OR `not(:hidden)`.
 */

import { expect, Page } from '@playwright/test';
import { isPrfDrawerInDraftMode } from './FormbuilderHelper';

/**
 * Race a success toastr against an error toastr. Toastr is checked by
 * ATTACHED, not VISIBLE — some resolutions render it below the viewport.
 */
async function raceToasts(
    page: Page,
    timeout: number
): Promise<{ status: 'success' | 'error' | 'timeout'; message: string }> {
    const successToast = page.locator('.toast-success, .toast-message.toast-success').first();
    const errorToast = page.locator('.toast-error, .toast-message.toast-error').first();

    const winner = await Promise.race([
        successToast.waitFor({ state: 'attached', timeout }).then(() => 'success' as const).catch(() => null),
        errorToast.waitFor({ state: 'attached', timeout }).then(() => 'error' as const).catch(() => null),
    ]);

    if (winner === 'error') {
        const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
        return { status: 'error', message: msg };
    }
    if (winner === 'success') {
        const msg = ((await successToast.textContent().catch(() => '')) || '').trim();
        return { status: 'success', message: msg };
    }
    return { status: 'timeout', message: '' };
}

/**
 * STEP 1 (SAVE path): Click `.prf_submit` inside the drawer.
 *
 * Common failures:
 *   1. Strict-mode collision (SURFACE D) — NEVER `page.getByText('Save')`.
 *      There are ~8+ Save buttons across the page. ALWAYS scope by drawer + class.
 *   2. Save flips via `.hidden` class — prefer `.not(:hidden)` over `:visible`.
 *   3. `save-failed.formbuilder` may fire — drawer stays open. Check for `.toast-error`.
 *
 * @returns
 *   - ok=true and recordId when the save succeeded (drawer either hides OR
 *     stays open in edit mode with a numeric id in input[id$="_id"]).
 *   - ok=false with the error message when the save failed.
 */
export async function savePrfDrawer(
    page: Page,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; recordId: string | null; message: string }> {
    const { timeout = 10000 } = options;

    // Runbook: use hasClass('hidden') === false, NOT :visible.
    const submit = page.locator('#prf_form_rightview .prf_submit').first();
    const isEnabledAndVisible = await page.evaluate(() => {
        const el = document.querySelector('#prf_form_rightview .prf_submit') as HTMLButtonElement | null;
        return !!el && !el.classList.contains('hidden') && !el.disabled;
    });
    if (!isEnabledAndVisible) {
        throw new Error(
            'savePrfDrawer: `.prf_submit` is hidden or disabled. ' +
            'If the record status_code_id == 33 (Draft), use saveDraftPrfDrawer() instead.'
        );
    }
    await submit.click();

    const toast = await raceToasts(page, timeout);
    if (toast.status === 'error') {
        console.log(`❌ savePrfDrawer: save-failed.formbuilder — "${toast.message}"`);
        return { ok: false, recordId: null, message: toast.message };
    }
    if (toast.status === 'timeout') {
        console.warn('⚠️ savePrfDrawer: no toast observed within timeout');
        return { ok: false, recordId: null, message: '' };
    }

    // Success — drawer either hides OR stays open with id populated.
    const drawer = page.locator('#prf_form_rightview');
    const drawerHidden = await drawer.isHidden().catch(() => false);
    const idInput = drawer.locator('input[id$="_id"]').first();
    const recordId = drawerHidden
        ? null
        : ((await idInput.inputValue().catch(() => '')) || null);

    console.log(`✅ savePrfDrawer: drawerHidden=${drawerHidden} recordId=${recordId ?? '—'} toast="${toast.message}"`);
    return { ok: true, recordId, message: toast.message };
}

/**
 * STEP 1 (SAVE-DRAFT variant): Click `.btn-is-draft` when the record is
 * status_code_id == 33.
 *
 * The Save-Draft handler (prf.js.html.twig:62-66) sets
 *   `$('#prf_form_rightview').data('$save-draft', true)`
 * then triggers a click on the primary submit. From that point the flow
 * merges with the SAVE path.
 *
 * DO NOT target `.btn-is-draft` by text alone — scope by drawer + class.
 */
export async function saveDraftPrfDrawer(
    page: Page,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; recordId: string | null; message: string }> {
    const { timeout = 10000 } = options;

    // Runbook precondition:
    //   #prf_form_rightview .btn-is-draft:visible AND #prf_form_rightview .prf_submit.hidden
    if (!(await isPrfDrawerInDraftMode(page))) {
        throw new Error(
            'saveDraftPrfDrawer: `.prf_submit` is NOT hidden — the record is not in Draft (status_code_id != 33). ' +
            'Use savePrfDrawer() instead.'
        );
    }

    const draftBtn = page.locator('#prf_form_rightview .btn-is-draft').first();
    await expect(draftBtn).toBeVisible({ timeout: 3000 });
    await expect(draftBtn).toBeEnabled({ timeout: 3000 });
    await draftBtn.click();

    // From here the flow merges with SAVE — toastr success/error + drawer state.
    const toast = await raceToasts(page, timeout);
    if (toast.status === 'error') {
        return { ok: false, recordId: null, message: toast.message };
    }
    if (toast.status === 'timeout') {
        return { ok: false, recordId: null, message: '' };
    }

    const drawer = page.locator('#prf_form_rightview');
    const drawerHidden = await drawer.isHidden().catch(() => false);
    const idInput = drawer.locator('input[id$="_id"]').first();
    const recordId = drawerHidden
        ? null
        : ((await idInput.inputValue().catch(() => '')) || null);

    console.log(`✅ saveDraftPrfDrawer: drawerHidden=${drawerHidden} recordId=${recordId ?? '—'}`);
    return { ok: true, recordId, message: toast.message };
}

/**
 * STEP 2 (CANCEL path): Click `.prf_cancel_button`.
 *
 * Client-side only — NO POST, NO toast, NO navigation. The handler
 * (prf.js.html.twig:76-90) runs synchronously:
 *   1. `#prf_form_rightview.data('modified', false)` — defeats discard-confirm
 *   2. Re-enables non-.forceHide options in select[name='_category']
 *   3. `resize_promo_cal('full')` — calendar expands back, VISUALLY covering the drawer
 *
 * Global delegate at delegates.js.html.twig:26390 also:
 *   4. Removes .hidden on .prf_detail_copy_edit_div
 *   5. .prf_detail_left_column → col-md-12 (removes col-md-8)
 *   6. Clears prfClientFirmId
 *
 * IMPORTANT: the drawer DOM node is NOT explicitly hidden. `#prf_form_rightview`
 * remains and may still be `:visible` by pixels — the "close" effect is the
 * calendar reclaiming the width. Testing `:hidden` will FALSELY fail.
 *
 * Verify by (in order of preference):
 *   - #promo-calendar bounding-box width equals its parent's inner width
 *   - #prf_form_rightview.data('modified') === false
 *   - .fc-toolbar visible with reset horizontal scrollbar
 */
export async function cancelPrfDrawer(page: Page): Promise<void> {
    const cancelBtn = page.locator('#prf_form_rightview .prf_cancel_button').first();
    await expect(cancelBtn).toBeVisible({ timeout: 3000 });
    await cancelBtn.click();

    // Verify data-modified was reset.
    const modifiedReset = await page.waitForFunction(
        () => {
            try {
                return !!(window as any).jQuery
                    && (window as any).jQuery('#prf_form_rightview').data('modified') === false;
            } catch { return false; }
        },
        { timeout: 3000 }
    ).then(() => true).catch(() => false);

    if (!modifiedReset) {
        console.warn(
            '⚠️ cancelPrfDrawer: #prf_form_rightview.data("modified") did not settle to false. ' +
            'Handler at prf.js.html.twig:76-90 may not have fired.'
        );
    }

    // Verify the calendar has reflowed to full width.
    const reflowed = await page.evaluate(() => {
        const cal = document.querySelector('#promo-calendar') as HTMLElement | null;
        const parent = cal?.parentElement as HTMLElement | null;
        if (!cal || !parent) return null;
        const calRect = cal.getBoundingClientRect();
        const parentRect = parent.getBoundingClientRect();
        return {
            calWidth: calRect.width,
            parentInner: parent.clientWidth,
            diffPx: Math.abs(calRect.width - parent.clientWidth),
            parentWidth: parentRect.width,
        };
    }).catch(() => null);

    if (reflowed && reflowed.diffPx > 8) {
        // 8px slack for scrollbar / border.
        console.warn(
            `⚠️ cancelPrfDrawer: calendar has NOT reflowed to full width ` +
            `(cal=${reflowed.calWidth}px, parentInner=${reflowed.parentInner}px, diff=${reflowed.diffPx}px). ` +
            `resize_promo_cal('full') may not have completed.`
        );
    }
    console.log('✅ cancelPrfDrawer: data-modified=false, calendar reflowed');
}

/**
 * Ready-state predicate — SAVE succeeded.
 * toastr.success present AND (drawer hidden OR record id present).
 */
export async function assertSaveSucceeded(page: Page): Promise<{ recordId: string | null }> {
    const successToast = page.locator('.toast-success, .toast-message.toast-success').first();
    await expect(successToast).toBeAttached({ timeout: 10000 });

    const drawer = page.locator('#prf_form_rightview');
    const drawerHidden = await drawer.isHidden().catch(() => false);
    if (drawerHidden) return { recordId: null };

    const idInput = drawer.locator('input[id$="_id"]').first();
    const idVal = (await idInput.inputValue().catch(() => '')) || '';
    if (!/^\d+$/.test(idVal)) {
        throw new Error(`assertSaveSucceeded: toast present but drawer still open and input[id$="_id"]="${idVal}" is not numeric.`);
    }
    return { recordId: idVal };
}

/**
 * Ready-state predicate — SAVE failed. `.toast-error` present. Read the
 * message to classify (validation vs server error).
 */
export async function assertSaveFailed(page: Page): Promise<{ message: string }> {
    const errorToast = page.locator('.toast-error, .toast-message.toast-error').first();
    await expect(errorToast).toBeAttached({ timeout: 10000 });
    const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
    return { message: msg };
}

/**
 * Ready-state predicate — CANCEL succeeded. `data-modified` is false AND
 * calendar has reflowed to full width.
 */
export async function assertCancelSucceeded(page: Page): Promise<void> {
    const modified = await page.evaluate(() => {
        try {
            return (window as any).jQuery('#prf_form_rightview').data('modified');
        } catch { return null; }
    });
    if (modified !== false) {
        throw new Error(`assertCancelSucceeded: #prf_form_rightview.data('modified') is ${modified}, expected false.`);
    }
    const widthOk = await page.evaluate(() => {
        const cal = document.querySelector('#promo-calendar') as HTMLElement | null;
        const parent = cal?.parentElement as HTMLElement | null;
        if (!cal || !parent) return false;
        return Math.abs(cal.getBoundingClientRect().width - parent.clientWidth) <= 8;
    });
    if (!widthOk) {
        throw new Error('assertCancelSucceeded: calendar has not reflowed to full width — resize_promo_cal("full") did not run.');
    }
}
