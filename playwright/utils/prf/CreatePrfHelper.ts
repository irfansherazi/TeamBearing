/**
 * CreatePrfHelper.ts — Happy-path PRF creation via the right-side drawer.
 *
 * Runbook source:
 *   knowledge-base/vqa-agent/scenario-runbooks/create-prf-happy-path.md
 *   knowledge-base/vqa-agent/scenario-runbooks/create-prf-happy-path.STEP-6.patch.md
 *
 * The PRF form is a right-side drawer inside the Home tab (NOT a modal). The
 * drawer container is `#prf_form_rightview` and starts as
 * `<div style="display:none;">` (calendar.html.twig:85). Clicking
 * `#create_new_prf` invokes `show_event_form(null, '')` via the delegate at
 * delegates.js.html.twig:9890 which:
 *   - resizes the calendar (`resize_promo_cal('shrink')`)
 *   - builds the form via `create_form_builder('#prf_form_rightview', {...})`
 *   - shows `#prf_form_rightview`
 *   - focuses `.field-title`
 *
 * Applies to authenticated users whose role IS NOT one of:
 *   ROLE_ON_AIR, ROLE_FRONT_DESK, ROLE_PROMO_ASSISTANT, NOBODY
 *   (fullcal.js.html.twig:979 — those roles never get #create_new_prf).
 */

import { expect, Page, Locator } from '@playwright/test';
import { pickSelect2Multi, pickSelect2Single } from './Select2v3Helper';
import {
    getPrfFormId,
    s2idFor,
    fillPrfTextField,
    fillPrfTaspField,
    fillPrfDatePicker,
    safeStartEndDefaults,
    enumeratePrfFields,
    waitForSaveEnabled,
} from './FormbuilderHelper';

/**
 * All the inputs a happy-path create needs, plus escape hatches for
 * per-tenant differences in required fields.
 */
export interface CreatePrfDetails {
    /** Required — the PRF title (plain text). */
    title: string;
    /**
     * Required — category label as displayed in the drop.
     * In multi-firm accounts the label is prefixed: "[Firm Name] Contest".
     */
    category: string;
    /**
     * At least one station is required for most categories. Sub-PRFs are
     * filtered to the parent's stations; unknown values silently do not appear
     * in the drop.
     */
    stations: string[];
    /**
     * Sales assignment — the full label including parens, e.g.
     * "Aaron Stack (Prog - Gotham City)". Parens are literal; do not escape.
     * Optional because stations may drive the list to a single default that
     * auto-selects; but pass it whenever the tenant requires it.
     */
    salesAssignment?: string;
    /**
     * Start datetime — either a Date or a preformatted "MM-DD-YYYY hh:mm A" string.
     * Defaults to today + 7 days @ 09:00 AM (STEP-6 patch safe default).
     */
    startDatetime?: Date | string;
    /**
     * End datetime — defaults to Start + 1 day.
     * MUST be >= Start (cross-field constraint at prf.js.html.twig:33-46).
     */
    endDatetime?: Date | string;
    /**
     * Formbuilder field name for the Start datetime input. Varies by tenant.
     * Defaults to `event_startdatetime` per the runbook.
     */
    startDatetimeField?: string;
    endDatetimeField?: string;
    /**
     * Optional description/copy field content — filled via contenteditable_tasp
     * (per STEP-6 patch, this is NOT wysihtml).
     */
    description?: string;
    /**
     * Formbuilder field name for the description tasp. Defaults to `description`.
     * Pass explicitly when the tenant uses a different field (e.g. `copy`).
     */
    descriptionField?: string;
    /**
     * Extra text-input fields to fill by formbuilder name (leading `_` optional).
     */
    extraTextFields?: Record<string, string>;
}

/**
 * STEP 1: Open the PRF drawer by clicking `#create_new_prf`.
 *
 * Common failure: clicking `#create_new_prf` while a previous PRF form is
 * `.data('modified')` triggers `window.confirm('Discard unsaved modifications?')`
 * (functions.js.html.twig:13440). Playwright auto-dismisses to `false` without
 * a handler → `show_event_form` bails and the drawer does not open. The
 * caller MUST have registered a dialog handler (`registerDialogAccept` in
 * AuthHelper.ts) BEFORE calling this.
 */
export async function openPrfDrawer(page: Page): Promise<void> {
    // pre_wait: #create_new_prf visible AND #promo-all is the active tab.
    await expect(page.locator('#promo-all.tab-pane.active')).toBeAttached({ timeout: 8000 });
    const newBtn = page.locator('#create_new_prf');
    await expect(newBtn).toBeVisible({ timeout: 8000 });

    await newBtn.click();

    const drawer = page.locator('#prf_form_rightview');
    const form = drawer.locator('form[id$="_form"]');
    const titleInput = drawer.locator('input[id$="_title"]');

    await expect(drawer).toBeVisible({ timeout: 8000 });
    await expect(form).toBeVisible({ timeout: 8000 });
    await expect(titleInput).toBeVisible({ timeout: 8000 });
    // formbuilder focuses .field-title on show (functions.js.html.twig:13472).
    // Focus assertion is best-effort — some browsers rehydrate focus asynchronously.
    await expect(titleInput).toBeFocused({ timeout: 2000 }).catch(() => {});
    console.log('📝 openPrfDrawer: drawer + form + title input ready');
}

/**
 * STEP 2: Fill the Title. The title input is a plain <input> — use .fill().
 * Anchor by `.field-title` (event.js.html.twig:70) rather than id (id embeds
 * the record id which is empty for new PRFs).
 */
export async function fillPrfTitle(page: Page, title: string): Promise<void> {
    const input = page.locator('#prf_form_rightview input.field-title').first();
    // Fallback: suffix-match on id in case .field-title is not applied.
    const fallback = page.locator('#prf_form_rightview input[id$="_title"]').first();

    const target = (await input.isVisible({ timeout: 500 }).catch(() => false)) ? input : fallback;
    await expect(target).toBeVisible({ timeout: 5000 });
    await target.fill(title);
    // Blur to fire the `modified` flip on `#prf_form_rightview` (prf.js.html.twig:4).
    await target.press('Tab').catch(() => {});

    // Verify: form data-modified was set true after the change.
    const isModified = await page.evaluate(() => {
        // @ts-expect-error — jQuery global
        return !!(window as any).jQuery && (window as any).jQuery('#prf_form_rightview').data('modified') === true;
    }).catch(() => false);
    if (!isModified) {
        console.log('⚠️ fillPrfTitle: #prf_form_rightview.data("modified") did not flip to true — value may not have committed');
    }
    console.log(`📝 fillPrfTitle: "${title}"`);
}

/**
 * STEP 3: Pick a Category. This is `select2tags` (multi-select) — some
 * categories collide on prefix ("Corporate Contest" vs "Corporate Content"),
 * so the caller must pass the full label.
 *
 * SPECIAL CASE — "Corporate Contest":
 *   cat_change_checker (functions.js.html.twig:13498-13515) enforces
 *   "when choosing Corporate Contest, it must be the only selection" — if
 *   other categories are present, the pick is silently removed 300ms later
 *   and a toastr.error appears. To combine Corporate Contest with others,
 *   the runbook explicitly says: won't work.
 */
export async function pickPrfCategory(
    page: Page,
    category: string | string[]
): Promise<void> {
    const categories = Array.isArray(category) ? category : [category];
    const containerId = await s2idFor(page, 'category');
    await pickSelect2Multi(page, containerId, categories);
    console.log(`📝 pickPrfCategory: picked ${categories.join(', ')}`);
}

/**
 * STEP 4: Pick Station(s). Also `select2tags`. May only be rendered AFTER
 * a category is picked, depending on scenario — the caller should call
 * pickPrfCategory first.
 *
 * Sub-PRF caveat: for `_is_sub` PRFs the list is filtered to the parent's
 * stations. Unknown stations silently do not appear in the search results.
 */
export async function pickPrfStations(
    page: Page,
    stations: string[]
): Promise<void> {
    if (stations.length === 0) return;
    const containerId = await s2idFor(page, 'stations');
    // The stations wrapper may render only after a category is picked.
    await expect(page.locator(`#${containerId}`)).toBeVisible({ timeout: 10000 });
    await pickSelect2Multi(page, containerId, stations);
    // Verify at least one tag rendered.
    const tags = page.locator(`#${containerId} li.select2-search-choice`);
    await expect(tags.first()).toBeVisible({ timeout: 3000 });
    console.log(`📝 pickPrfStations: picked ${stations.join(', ')}`);
}

/**
 * STEP 5: Pick a Sales Assignment. This is a select2 single-select on a
 * native <select>. Options are formatted `Name (Role - Station)` via
 * `getSalesPeopleForStation` (formbuilder.js.html.twig:478). The list
 * DEPENDS on selected stations — call pickPrfStations first or the list is
 * empty.
 *
 * The field name may be `sales_person_id` or `salesperson_id` (verify per
 * tenant). We try the canonical name first, then the alternate.
 */
export async function pickPrfSalesAssignment(
    page: Page,
    label: string,
    fieldName: 'sales_person_id' | 'salesperson_id' = 'sales_person_id'
): Promise<void> {
    let containerId = await s2idFor(page, fieldName);
    let container = page.locator(`#${containerId}`);
    if (!(await container.isVisible({ timeout: 2000 }).catch(() => false))) {
        // Try alternate spelling.
        const alt = fieldName === 'sales_person_id' ? 'salesperson_id' : 'sales_person_id';
        containerId = await s2idFor(page, alt);
        container = page.locator(`#${containerId}`);
        await expect(container).toBeVisible({ timeout: 5000 });
    }
    await pickSelect2Single(page, containerId, label);
    console.log(`📝 pickPrfSalesAssignment: "${label}"`);
}

/**
 * STEP 6: Fill remaining required fields.
 *
 * The field set is dynamic (STEP-6 patch), so we do the deterministic work
 * — Start/End datetimes, optional description — and expose enumeration for
 * per-tenant additions.
 *
 * Order matters: fill Start FIRST, then End (prf.js.html.twig:33-46
 * updates End's minDate from Start, and would clear End < new Start).
 */
export async function fillPrfCoreFields(
    page: Page,
    details: CreatePrfDetails
): Promise<void> {
    const startField = details.startDatetimeField ?? 'event_startdatetime';
    const endField = details.endDatetimeField ?? 'event_enddatetime';

    // Resolve Start/End: user-supplied or safe defaults.
    let startVal: Date | string | undefined = details.startDatetime;
    let endVal: Date | string | undefined = details.endDatetime;
    if (!startVal || !endVal) {
        const defaults = safeStartEndDefaults();
        if (!startVal) startVal = defaults.start;
        if (!endVal) endVal = defaults.end;
    }

    await fillPrfDatePicker(page, startField, startVal, { withTime: true });
    await fillPrfDatePicker(page, endField, endVal, { withTime: true });

    if (details.description !== undefined) {
        const descField = details.descriptionField ?? 'description';
        await fillPrfTaspField(page, descField, details.description);
    }

    if (details.extraTextFields) {
        for (const [name, value] of Object.entries(details.extraTextFields)) {
            await fillPrfTextField(page, name, value);
        }
    }
}

/**
 * STEP 7: Save the PRF.
 *
 * Runbook notes:
 *   1. Strict-mode collision — there are ~8+ "Save" buttons across the
 *      page. ALWAYS scope by drawer + class. NEVER `page.getByText('Save')`.
 *   2. Toastr can render below viewport at some resolutions — check DOM
 *      presence, NOT visibility.
 *   3. On success either the drawer hides OR stays open in edit-mode with
 *      the new id populated in `input[id$="_id"]`.
 *
 * @returns object indicating success/failure with the new record id when available.
 */
export async function savePrf(
    page: Page,
    options: { timeout?: number } = {}
): Promise<{ ok: boolean; recordId: string | null; toast: string }> {
    const { timeout = 10000 } = options;

    const submit = await waitForSaveEnabled(page, 8000);
    await submit.click();

    // Race success toast against error toast. Toastr is checked by presence
    // (attached), NOT visibility, because it can render below viewport.
    const successToast = page.locator('.toast-success, .toast-message.toast-success').first();
    const errorToast = page.locator('.toast-error, .toast-message.toast-error').first();

    const winner = await Promise.race([
        successToast.waitFor({ state: 'attached', timeout }).then(() => 'success' as const).catch(() => null),
        errorToast.waitFor({ state: 'attached', timeout }).then(() => 'error' as const).catch(() => null),
    ]);

    if (winner === 'error') {
        const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
        console.log(`❌ savePrf: save-failed.formbuilder — "${msg}"`);
        return { ok: false, recordId: null, toast: msg };
    }
    if (winner !== 'success') {
        console.warn('⚠️ savePrf: no toast within timeout — treating as failure');
        return { ok: false, recordId: null, toast: '' };
    }

    // Drawer may hide OR stay open with id populated.
    const drawer = page.locator('#prf_form_rightview');
    const idInput = drawer.locator('input[id$="_id"]').first();

    const drawerHidden = await drawer.isHidden().catch(() => false);
    const recordId = drawerHidden
        ? null
        : (await idInput.inputValue().catch(() => '')) || null;

    const successMsg = ((await successToast.textContent().catch(() => '')) || '').trim();
    console.log(`✅ savePrf: drawerHidden=${drawerHidden} recordId=${recordId ?? '—'} toast="${successMsg}"`);
    return { ok: true, recordId, toast: successMsg };
}

/**
 * STEP 8 (optional): Confirm the PRF appears on the calendar.
 *
 * Calendar refresh is asynchronous — allow up to 5s for the new .fc-event
 * to render.
 */
export async function verifyPrfOnCalendar(
    page: Page,
    title: string,
    timeout = 5000
): Promise<void> {
    const event = page
        .locator('#promo-calendar .fc-event')
        .filter({ hasText: title })
        .first();
    await expect(event).toBeVisible({ timeout });
    console.log(`✅ verifyPrfOnCalendar: found .fc-event with title "${title}"`);
}

/**
 * Orchestrator: STEP 1 → STEP 7 (STEP 8 verification is opt-in).
 *
 * The caller MUST have already:
 *   - authenticated + navigated to Home (see AuthHelper.loginAndWaitForHomeReady)
 *   - registered a dialog handler at the context level
 */
export async function createPrfHappyPath(
    page: Page,
    details: CreatePrfDetails,
    options: { verifyOnCalendar?: boolean } = {}
): Promise<{ recordId: string | null; toast: string; formId: string }> {
    await openPrfDrawer(page);
    const formId = await getPrfFormId(page);

    await fillPrfTitle(page, details.title);
    await pickPrfCategory(page, details.category);
    await pickPrfStations(page, details.stations);
    if (details.salesAssignment) {
        await pickPrfSalesAssignment(page, details.salesAssignment);
    }
    await fillPrfCoreFields(page, details);

    const result = await savePrf(page);
    if (!result.ok) {
        // Enumerate the form so callers can see what fields are still required.
        const fields = await enumeratePrfFields(page);
        const stillRequired = fields.filter(f => f.required).map(f => f.name).join(', ');
        throw new Error(
            `createPrfHappyPath: save failed. toast="${result.toast}". ` +
            `Required fields still on form: ${stillRequired || '<none>'}.`
        );
    }

    if (options.verifyOnCalendar) {
        await verifyPrfOnCalendar(page, details.title);
    }

    return { ...result, formId };
}

/**
 * Locate the calendar event(s) matching a title. Handy for follow-up
 * assertions (e.g. after createPrfHappyPath returns).
 */
export function findCalendarEvents(page: Page, title: string): Locator {
    return page.locator('#promo-calendar .fc-event').filter({ hasText: title });
}
