/**
 * FormbuilderHelper.ts — Primitives for the vCreative formbuilder widgets
 * rendered inside the PRF drawer (`#prf_form_rightview`).
 *
 * Field-widget map (from create-prf-happy-path.STEP-6.patch.md):
 *   text                 — plain <input type="text">                             → .fill()
 *   textarea             — span.tasp[contenteditable] + hidden backing <input>   → contenteditable_tasp
 *   select2              — single-select select2 v3                              → Select2v3Helper.pickSelect2Single
 *   select2tags          — multi-select select2 v3                               → Select2v3Helper.pickSelect2Multi
 *   select2typeahead     — ajax-backed select2 v3                                → Select2v3Helper.pickSelect2Ajax
 *   date                 — input.datetimepicker w/ "99-99-9999" inputmask        → hasdatepicker, format MM-DD-YYYY
 *   datetime             — input.datetimepicker w/ time                          → hasdatepicker, format "MM-DD-YYYY hh:mm A"
 *   file                 — anchor.upload_inital_prf_files (opens Dropzone modal) → see UploadPrfFilesHelper.ts
 *
 * Field naming convention (formbuilder.js.html.twig:303, :325):
 *   All rendered controls carry `name` prefixed with `_` (e.g. `_title`, `_stations`).
 *   The wrapper for a select2 field is `#s2id_<form-id>_<field>` where <form-id>
 *   is `prf_<recordId>_form` for existing PRFs or `prf__form` for new. Use
 *   suffix-matching to remain agnostic to the record id.
 *
 * Required-field detection:
 *   - `.input_required` class on the control OR on the wrapping span.tasp.
 *   - `.required` attribute may also be set (formbuilder.js.html.twig:311-315).
 */

import { expect, Page, Locator } from '@playwright/test';

/**
 * Resolve the PRF form id from the drawer. The form id embeds the record id:
 *   - New PRF:      `prf__form`  (empty record id)
 *   - Existing PRF: `prf_<id>_form`
 */
export async function getPrfFormId(page: Page): Promise<string> {
    const form = page.locator('#prf_form_rightview form[id$="_form"]').first();
    await expect(form).toBeVisible({ timeout: 8000 });
    const id = await form.getAttribute('id');
    if (!id) throw new Error('getPrfFormId: form has no id attribute');
    return id;
}

/**
 * Build the `#s2id_<form-id>_<field>` container id for a formbuilder select2 field.
 * Passing `_title` or `title` both work — the leading underscore is optional.
 */
export async function s2idFor(page: Page, field: string): Promise<string> {
    const formId = await getPrfFormId(page);
    const cleaned = field.replace(/^_+/, '');
    return `s2id_${formId}_${cleaned}`;
}

/**
 * Fill a plain text input inside the PRF drawer (widget type `text`).
 * Anchors on `.field-<name>` (formbuilder.js.html.twig:328) which is stable
 * across new/existing records, unlike the id which embeds the record id.
 */
export async function fillPrfTextField(
    page: Page,
    fieldName: string,
    value: string
): Promise<void> {
    const cleaned = fieldName.replace(/^_+/, '');
    const input = page.locator(
        `#prf_form_rightview input.field-${cleaned}:visible, ` +
        `#prf_form_rightview input[name="_${cleaned}"]:visible, ` +
        `#prf_form_rightview input[id$="_${cleaned}"]:visible`
    ).first();
    await expect(input).toBeVisible({ timeout: 5000 });
    await input.fill(value);
    // Blur to fire formbuilder change tracking.
    await input.press('Tab').catch(() => {});
}

/**
 * Fill a `textarea`-type field: the visible editor is a contenteditable
 * `span.tasp` with a sibling hidden `<input>` that receives the serialized
 * html at submit time (formbuilder.js.html.twig:299-317, :1868).
 *
 * IMPORTANT (from the STEP-6 patch — this widget was previously misidentified
 * as wysihtml):
 *   - Do NOT `.fill()` the visible span — throws "Element is not an <input>".
 *   - Do NOT `.fill()` the hidden input — formbuilder overwrites it on serialize.
 *   - DO click to place caret, then `page.keyboard.type()`.
 */
export async function fillPrfTaspField(
    page: Page,
    fieldName: string,
    content: string,
    options: { replace?: boolean } = {}
): Promise<void> {
    const { replace = true } = options;
    const cleaned = fieldName.replace(/^_+/, '');

    const tasp = page.locator(
        `#prf_form_rightview span.tasp[id$="_${cleaned}_tasp"]:visible, ` +
        `#prf_form_rightview span.tasp[name="_${cleaned}"]:visible`
    ).first();
    await expect(tasp).toBeVisible({ timeout: 5000 });

    await tasp.click();

    if (replace) {
        // contenteditable — select-all + delete before typing new content.
        await page.keyboard.press('Control+A').catch(() => {});
        await page.keyboard.press('Meta+A').catch(() => {}); // WebKit fallback
        await page.keyboard.press('Delete').catch(() => {});
    }

    await page.keyboard.type(content);

    // Blur to trigger formbuilder's change detection.
    await page.keyboard.press('Tab').catch(() => {});
    console.log(`✅ tasp field "${cleaned}" filled (${content.length} chars)`);
}

/**
 * Format a Date as "MM-DD-YYYY" (formbuilder default `date_format: 'mm-dd-yy'`
 * where 'yy' is jQuery UI's 4-digit convention).
 */
export function formatDateForPicker(date: Date): string {
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${mm}-${dd}-${date.getFullYear()}`;
}

/**
 * Format a Date as "MM-DD-YYYY hh:mm A" (formbuilder default
 * `time_format: 'hh:mm tt'`). Uses 12-hour clock.
 */
export function formatDateTimeForPicker(date: Date): string {
    const dateStr = formatDateForPicker(date);
    const h24 = date.getHours();
    const h12 = h24 % 12 || 12;
    const mins = String(date.getMinutes()).padStart(2, '0');
    const ampm = h24 >= 12 ? 'PM' : 'AM';
    return `${dateStr} ${String(h12).padStart(2, '0')}:${mins} ${ampm}`;
}

/**
 * Fill a `date` or `datetime` hasdatepicker field.
 *
 * Input mask (`99-99-9999`) enforces the shape while typing; blurring the
 * input fires `vCreative.vDates.parseDateTime()` which validates and toasts
 * "Invalid Date" on failure (formbuilder.js.html.twig:120-125).
 *
 * Cross-field constraint (prf.js.html.twig:33-46):
 *   - Setting Start updates End's minDate; if End < new Start it is cleared.
 *   - Setting End updates Start's maxDate; if Start > new End it is cleared.
 *   → Always set Start FIRST, then End.
 *
 * @param fieldName - e.g. `event_startdatetime`, `event_enddatetime` (leading `_` optional)
 * @param value     - either `Date` or a string in the expected picker format
 * @param withTime  - true → "MM-DD-YYYY hh:mm A"; false → "MM-DD-YYYY"
 */
export async function fillPrfDatePicker(
    page: Page,
    fieldName: string,
    value: Date | string,
    options: { withTime?: boolean } = {}
): Promise<void> {
    const { withTime = false } = options;
    const cleaned = fieldName.replace(/^_+/, '');
    const formatted = typeof value === 'string'
        ? value
        : (withTime ? formatDateTimeForPicker(value) : formatDateForPicker(value));

    const input = page.locator(
        `#prf_form_rightview input.datetimepicker[id$="_${cleaned}"]:visible, ` +
        `#prf_form_rightview input.datetimepicker[name="_${cleaned}"]:visible`
    ).first();
    await expect(input).toBeVisible({ timeout: 5000 });

    // Focus first — inputmask needs an active input to accept keystrokes cleanly.
    await input.click();
    // Select-all + delete to clear the mask template ("MM-DD-YYYY" or "MM-DD-YYYY hh:mm A").
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Meta+A').catch(() => {});
    await page.keyboard.press('Delete').catch(() => {});
    // Type through the mask (digits + AM/PM only — mask handles separators).
    await page.keyboard.type(formatted, { delay: 20 });
    // Blur to fire parseDateTime — check for a toastr.error immediately after.
    await input.press('Tab').catch(() => {});
    await page.waitForTimeout(300);

    const errorToast = page.locator('.toast-error, .toast-message.toast-error').last();
    if (await errorToast.isVisible({ timeout: 200 }).catch(() => false)) {
        const msg = ((await errorToast.textContent().catch(() => '')) || '').trim();
        if (/invalid\s+date/i.test(msg)) {
            throw new Error(`fillPrfDatePicker: "${formatted}" rejected as Invalid Date on field "_${cleaned}"`);
        }
    }

    const actual = await input.inputValue().catch(() => '');
    console.log(`✅ hasdatepicker "_${cleaned}" set to "${actual}" (wanted "${formatted}")`);
}

/**
 * Return happy-path safe defaults for the Start/End datetime pair
 * (per STEP-6 patch: today + 7 days at 09:00 AM, today + 8 days at 09:00 AM).
 */
export function safeStartEndDefaults(): { start: string; end: string } {
    const s = new Date();
    s.setDate(s.getDate() + 7);
    s.setHours(9, 0, 0, 0);
    const e = new Date(s);
    e.setDate(e.getDate() + 1);
    return {
        start: formatDateTimeForPicker(s),
        end: formatDateTimeForPicker(e),
    };
}

/**
 * Enumerate every rendered formbuilder-owned form control in the drawer.
 * The field set is NOT static — it is driven by the record passed to
 * `create_form_builder` (functions.js.html.twig:13453). Fields differ by
 * category, sub-PRF status, campaign vs standalone, and user role.
 *
 * Returns an array describing each control by its formbuilder name and
 * whether it is required (has `.input_required`).
 */
export async function enumeratePrfFields(page: Page): Promise<Array<{
    name: string;
    tag: string;
    type: string | null;
    required: boolean;
    fieldClass: string | null;
}>> {
    // Selector: any element with name starting with `_` that is a form control
    // (matches textareas, selects, inputs, hidden inputs backing tasp spans).
    return await page.evaluate(() => {
        const drawer = document.querySelector('#prf_form_rightview form');
        if (!drawer) return [];
        const controls = Array.from(drawer.querySelectorAll('[name^="_"]')) as HTMLElement[];
        const seen = new Set<string>();
        const out: Array<{ name: string; tag: string; type: string | null; required: boolean; fieldClass: string | null }> = [];
        for (const el of controls) {
            const name = el.getAttribute('name') || '';
            if (!name || seen.has(name)) continue;
            seen.add(name);
            const fieldClass = Array.from(el.classList).find(c => c.startsWith('field-')) || null;
            out.push({
                name,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type'),
                required: el.classList.contains('input_required') || el.hasAttribute('required'),
                fieldClass,
            });
        }
        return out;
    });
}

/**
 * Wait for the Save button to become enabled. Formbuilder disables it at
 * render (formbuilder.js.html.twig:1187) and clears the flag only when the
 * form internally validates.
 */
export async function waitForSaveEnabled(page: Page, timeout = 10000): Promise<Locator> {
    const submit = page.locator(
        '#prf_form_rightview .form-buttons button[type=submit].prf_submit:not(:disabled):visible'
    ).first();
    await expect(submit).toBeVisible({ timeout });
    return submit;
}

/**
 * Detect whether the current PRF drawer is in DRAFT state (status_code_id 33).
 * In draft state, `.prf_submit` is `.hidden` and `.btn-is-draft` is the primary
 * save entrypoint (functions.js.html.twig:13460-13464).
 *
 * Uses `hasClass('hidden')` — NOT `:visible` — because prf.js.html.twig:256-259
 * toggles visibility via `.addClass('hidden')` / `.removeClass('hidden')`, and
 * Playwright's `:visible` may still consider `.hidden` items visible depending
 * on the CSS resolution.
 */
export async function isPrfDrawerInDraftMode(page: Page): Promise<boolean> {
    return await page.evaluate(() => {
        const submit = document.querySelector('#prf_form_rightview .prf_submit');
        return !!(submit && submit.classList.contains('hidden'));
    });
}
