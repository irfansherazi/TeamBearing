/**
 * RevisePrfHelper.ts — Revise an already-approved PRF.
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/revise-approved-prf.md
 *
 * Entry point: `.btn_revise_prf` context-menu action on a calendar event card
 * (attached at functions.js.html.twig:5791, :5797). Only appended when the
 * current role + PRF status combination is eligible. If absent, treat as
 * PRECONDITION_MISSING.
 *
 * Confirmation modal (delegates.js.html.twig:22080-22117) is built dynamically
 * — no static id. Body reads "By Revising this PRF, the original will be
 * locked until the Revision is fully Approved...". Footer has two buttons:
 *   - `.btn.btn-link`     → "Cancel"
 *   - `.btn.btn-primary`  → "Continue To Revise"
 *
 * After confirmation, `show_event_form(record, date)` opens the drawer
 * pre-populated with the record and appends `.is_revise` to the submit
 * button (prf.js.html.twig:582). The save-time serialization at
 * prf.js.html.twig:466-524 computes the new status from role + station
 * approval config + `is_revise=true` (NOT from `new_prf_status`).
 */

import { expect, Page, Locator } from '@playwright/test';
import { eventCardFor } from './ApprovePrfHelper';
import { fillPrfTextField, fillPrfTaspField, fillPrfDatePicker, waitForSaveEnabled } from './FormbuilderHelper';
import { pickSelect2Single, pickSelect2Multi } from './Select2v3Helper';

/**
 * The context-menu link for revising a PRF. `data-prf-id` scopes it.
 */
export function reviseLinkFor(page: Page, prfId: string | number): Locator {
    return page.locator(`a.btn_revise_prf[data-prf-id="${prfId}"]`).first();
}

/**
 * STEP 1: Reveal the event's context menu on the calendar. The menu is
 * implementation-specific — some cards use hover, some use click. We try
 * hover first; if the revise link doesn't materialize, we fall back to a
 * click.
 *
 * Common failure: for status/role pairs where Revise isn't offered, the
 * link never appears — treat as PRECONDITION_MISSING.
 */
export async function openPrfContextMenu(
    page: Page,
    prfId: string | number,
    options: { timeout?: number } = {}
): Promise<void> {
    const { timeout = 8000 } = options;
    const card = eventCardFor(page, prfId);
    await expect(card).toBeVisible({ timeout });

    const link = reviseLinkFor(page, prfId);
    if (await link.isVisible({ timeout: 500 }).catch(() => false)) return;

    // Hover to reveal action list.
    await card.hover();
    if (await link.isVisible({ timeout: 1500 }).catch(() => false)) return;

    // Fallback: click the card.
    await card.click();
    if (await link.isVisible({ timeout: 2000 }).catch(() => false)) return;

    throw new Error(
        `PRECONDITION_MISSING: no a.btn_revise_prf[data-prf-id="${prfId}"] appeared. ` +
        `The current role/status pair is not eligible for revision (functions.js.html.twig ~line 5750+).`
    );
}

/**
 * STEP 2: Click Revise. The delegate at delegates.js.html.twig:22078 inserts
 * a `<div class="modal fade">` into the DOM and calls `.modal('show')`.
 * The modal has no stable id — target by class + text content.
 */
export async function clickRevise(page: Page, prfId: string | number): Promise<Locator> {
    const link = reviseLinkFor(page, prfId);
    await expect(link).toBeVisible({ timeout: 5000 });
    await link.click();

    // The just-opened modal is the topmost `.modal.in`, containing our copy.
    const modal = page
        .locator('div.modal.in')
        .filter({ hasText: /By Revising this PRF/i })
        .first();
    await expect(modal).toBeVisible({ timeout: 5000 });
    return modal;
}

/**
 * STEP 3: Click "Continue To Revise" in the confirmation modal. Scoping to
 * the modal is critical — the button text alone would match generic
 * primary buttons elsewhere on the page.
 *
 * After the click:
 *   - Confirmation modal closes.
 *   - `#prf_form_rightview` opens populated with the record.
 *   - Submit button gets `.is_revise` class.
 *   - `input[id$="_id"]` has the existing numeric id.
 */
export async function confirmRevisionModal(
    page: Page,
    modal?: Locator
): Promise<void> {
    const target = modal ?? page.locator('div.modal.in').filter({ hasText: /By Revising this PRF/i }).first();
    await expect(target).toBeVisible({ timeout: 3000 });

    const continueBtn = target.locator('button.btn-primary').filter({ hasText: /Continue To Revise/i }).first();
    await expect(continueBtn).toBeVisible({ timeout: 3000 });
    await continueBtn.click();

    // Modal should close (bootstrap 3 transition: loses `.in`).
    await target.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});

    const drawer = page.locator('#prf_form_rightview');
    await expect(drawer).toBeVisible({ timeout: 8000 });

    const idInput = drawer.locator('input[id$="_id"]').first();
    const idVal = (await idInput.inputValue().catch(() => '')) || '';
    if (!/^\d+$/.test(idVal)) {
        throw new Error(`confirmRevisionModal: drawer opened but input[id$="_id"] is not numeric (got "${idVal}").`);
    }

    // `.is_revise` class flags the save flow at prf.js.html.twig:582.
    const isReviseBtn = drawer.locator('.form-buttons button[type=submit].is_revise');
    await expect(isReviseBtn).toHaveCount(1, { timeout: 3000 });
    console.log(`📝 confirmRevisionModal: drawer opened for PRF ${idVal} with .is_revise flag`);
}

/**
 * Field-level revisions. Keys refer to formbuilder-name (leading `_` optional).
 * Categories/stations use select2 v3; text/tasp/datetime use their respective
 * primitives.
 *
 * Cross-field caveat: category changes may filter the stations list and
 * clear later dependent fields. Callers should specify upstream fields first
 * (category → stations → salesAssignment) and re-verify downstream.
 */
export interface PrfRevisions {
    title?: string;
    category?: string | string[];
    stations?: string[];
    salesAssignment?: string;
    startDatetime?: Date | string;
    endDatetime?: Date | string;
    description?: string;
    /** Extra plain text fields keyed by formbuilder name. */
    extraTextFields?: Record<string, string>;
}

/**
 * STEP 4: Apply the requested changes. For fields that trigger dependent
 * updates (category → stations filter; stations → sales list), we re-apply
 * dependent fields AFTER upstream changes.
 */
export async function applyPrfRevisions(page: Page, revisions: PrfRevisions): Promise<void> {
    if (revisions.title !== undefined) {
        await fillPrfTextField(page, 'title', revisions.title);
    }

    if (revisions.category !== undefined) {
        const cats = Array.isArray(revisions.category) ? revisions.category : [revisions.category];
        // Category wrapper id follows `s2id_<form-id>_category`.
        const formId = await page.locator('#prf_form_rightview form[id$="_form"]').first().getAttribute('id');
        if (!formId) throw new Error('applyPrfRevisions: could not resolve form id');
        await pickSelect2Multi(page, `s2id_${formId}_category`, cats);
    }

    if (revisions.stations !== undefined) {
        const formId = await page.locator('#prf_form_rightview form[id$="_form"]').first().getAttribute('id');
        if (!formId) throw new Error('applyPrfRevisions: could not resolve form id');
        await pickSelect2Multi(page, `s2id_${formId}_stations`, revisions.stations);
    }

    if (revisions.salesAssignment !== undefined) {
        const formId = await page.locator('#prf_form_rightview form[id$="_form"]').first().getAttribute('id');
        if (!formId) throw new Error('applyPrfRevisions: could not resolve form id');
        // Try canonical `sales_person_id` first, fall back to `salesperson_id`.
        const primary = `s2id_${formId}_sales_person_id`;
        const alternate = `s2id_${formId}_salesperson_id`;
        const primaryVisible = await page.locator(`#${primary}`).isVisible({ timeout: 1500 }).catch(() => false);
        await pickSelect2Single(page, primaryVisible ? primary : alternate, revisions.salesAssignment);
    }

    if (revisions.startDatetime !== undefined) {
        await fillPrfDatePicker(page, 'event_startdatetime', revisions.startDatetime, { withTime: true });
    }
    if (revisions.endDatetime !== undefined) {
        await fillPrfDatePicker(page, 'event_enddatetime', revisions.endDatetime, { withTime: true });
    }

    if (revisions.description !== undefined) {
        await fillPrfTaspField(page, 'description', revisions.description);
    }

    if (revisions.extraTextFields) {
        for (const [name, value] of Object.entries(revisions.extraTextFields)) {
            await fillPrfTextField(page, name, value);
        }
    }

    // Verify `data-modified` flipped after our changes.
    const modified = await page.evaluate(() => {
        return !!(window as any).jQuery
            && (window as any).jQuery('#prf_form_rightview').data('modified') === true;
    }).catch(() => false);
    if (!modified) {
        console.warn('⚠️ applyPrfRevisions: #prf_form_rightview.data("modified") is not true — changes may not have committed');
    }
}

/**
 * STEP 5: Save the revision. Same button as Create (`.prf_submit`), but the
 * click carries `is_revise` — server computes the new status per the role +
 * station approval config.
 *
 * After save:
 *   - `saved.formbuilder` fires with `e.new_record=false` (prf.js.html.twig:593)
 *   - The submit button has `.is_revise` removed (prf.js.html.twig:606)
 *   - toastr.success within ~10s
 */
export async function saveRevision(
    page: Page,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; toast: string }> {
    const { timeout = 10000 } = options;
    const submit = await waitForSaveEnabled(page, 8000);
    await submit.click();

    const successToast = page.locator('.toast-success, .toast-message.toast-success').first();
    const errorToast = page.locator('.toast-error, .toast-message.toast-error').first();
    const winner = await Promise.race([
        successToast.waitFor({ state: 'attached', timeout }).then(() => 'success' as const).catch(() => null),
        errorToast.waitFor({ state: 'attached', timeout }).then(() => 'error' as const).catch(() => null),
    ]);

    if (winner === 'error') {
        const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
        console.log(`❌ saveRevision: error toast "${msg}"`);
        return { ok: false, toast: msg };
    }
    if (winner !== 'success') {
        return { ok: false, toast: '' };
    }

    // Post-save, the submit no longer carries .is_revise.
    await expect(
        page.locator('#prf_form_rightview .form-buttons button[type=submit]:not(.is_revise)')
    ).toHaveCount(1, { timeout: 3000 }).catch(() => {
        console.log('ℹ️ saveRevision: submit still carries .is_revise (drawer may not have refreshed yet)');
    });

    const msg = ((await successToast.textContent().catch(() => '')) || '').trim();
    console.log(`✅ saveRevision: success toast "${msg}"`);
    return { ok: true, toast: msg };
}

/**
 * Orchestrator: open menu → confirm → apply revisions → save.
 *
 * The caller must have registered a dialog handler at the context level
 * (see AuthHelper.registerDialogAccept) — opening a second form while
 * `data-modified` is true fires `window.confirm('Discard unsaved modifications?')`.
 */
export async function revisePrf(
    page: Page,
    prfId: string | number,
    revisions: PrfRevisions,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; toast: string }> {
    await openPrfContextMenu(page, prfId, { timeout: options.timeout });
    const modal = await clickRevise(page, prfId);
    await confirmRevisionModal(page, modal);
    await applyPrfRevisions(page, revisions);
    return saveRevision(page, options);
}
