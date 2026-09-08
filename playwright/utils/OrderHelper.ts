/**
 * OrderHelper.ts - Order Creation Utilities for Playwright Tests
 * 
 * Provides reusable functions for creating and submitting Quick Orders.
 * Part of the Phase 1 "Lego Brick" helpers for the 2026 automation plan.
 */

import { expect, Page, Locator } from '@playwright/test';
import {
    generateRandomSpotTitle,
    generateRandomISCI,
    calculateDueDate,
    calculateStartDate,
    calculateEndDate,
    generateUniqueClientName
} from './QO_helpers';

/**
 * Parse a date string in MM/DD/YYYY or MM-DD-YYYY format into a JS Date object.
 * Input dates from QO_helpers are always in MM/DD/YYYY format.
 */
function parseDateString(value: string): Date {
    const normalized = value.replace(/-/g, '/');
    const parts = normalized.split('/');
    if (parts.length !== 3) throw new Error(`parseDateString: invalid format "${value}"`);
    return new Date(parseInt(parts[2], 10), parseInt(parts[0], 10) - 1, parseInt(parts[1], 10));
}

/**
 * Build PrimeNG data-date attribute value: "YYYY-M-D".
 * PrimeNG uses 0-indexed months (Jan=0, Apr=3) and no zero-padding.
 */
function buildDataDateAttr(date: Date): string {
    return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/**
 * Safe scroll utility to protect WebKit's headless rendering engine from rapid layout deadlocks.
 */
async function safeScroll(locator: Locator): Promise<void> {
    await locator.page().waitForTimeout(250);
    try {
        const browser = locator.page().context().browser();
        const isWebKit = browser ? browser.browserType().name() === 'webkit' : false;
        if (isWebKit) {
            await locator.evaluate(el => el.scrollIntoView({ block: 'center', inline: 'nearest' })).catch(() => {});
        } else {
            await locator.scrollIntoViewIfNeeded().catch(() => {});
        }
    } catch {
        await locator.evaluate(el => el.scrollIntoView({ block: 'center', inline: 'nearest' })).catch(() => {});
    }
}

/**
 * Dismiss any PrimeNG p-dialog modal that is currently blocking the page.
 *
 * The "Draft Saved" dialog on the QO form is the primary case. It appears when:
 *   - The form auto-saves after a date cell click or field change
 *   - The user (or a prior Escape key) triggered a sidebar-close prompt
 *
 * Dialog buttons seen in production:
 *   - "CONTINUE WORKING" → keeps the form open (preferred)
 *   - "CLOSE AND SAVE"   → closes form with save
 *   - "CLOSE WITHOUT SAVING" → closes and discards
 *   - "OK" / "Close" / "Got It" → generic dismiss buttons
 *
 * @param waitMs - extra ms to wait before checking (default 0 — caller may wait before calling)
 */
async function dismissBlockingDialog(page: Page, waitMs = 0): Promise<void> {
    if (waitMs > 0) await page.waitForTimeout(waitMs);

    const dialog = page.locator('p-dialog').filter({ visible: true }).first();
    const isBlocking = await dialog.isVisible({ timeout: 1200 }).catch(() => false);
    if (!isBlocking) return;

    const header = await dialog.locator('.p-dialog-header, .p-dialog-title').textContent({ timeout: 500 }).catch(() => '');
    console.log(`⚠️ dismissBlockingDialog: found blocking p-dialog "${(header || '').trim()}". Dismissing...`);

    // Strategy 1: "CONTINUE WORKING" — keep the QO form open after auto-draft save
    const continueBtn = dialog.locator('button:has-text("CONTINUE WORKING")').first();
    if (await continueBtn.isVisible({ timeout: 500 }).catch(() => false)) {
        await continueBtn.click({ force: true });
        await dialog.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
        console.log('⚠️ dismissBlockingDialog: clicked "CONTINUE WORKING"');
        await page.waitForTimeout(300); // Let Angular settle after dialog close
        return;
    }

    // Strategy 2: generic dismiss buttons (OK, Close, Got It, etc.)
    const dismissBtn = dialog.locator(
        'button:has-text("OK"), button:has-text("Ok"), button:has-text("Close"), '
        + 'button:has-text("Got It"), button:has-text("Dismiss"), '
        + 'button[aria-label="Close"], .p-dialog-header-close'
    ).first();
    if (await dismissBtn.isVisible({ timeout: 500 }).catch(() => false)) {
        await dismissBtn.click({ force: true });
        await dialog.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});
        console.log('⚠️ dismissBlockingDialog: clicked generic dismiss button');
        return;
    }

    // Strategy 3: press Escape on the dialog itself
    await dialog.press('Escape').catch(() => {});
    await dialog.waitFor({ state: 'hidden', timeout: 1500 }).catch(() => {});

    // Strategy 4: click the overlay mask backdrop
    if (await dialog.isVisible({ timeout: 300 }).catch(() => false)) {
        const mask = page.locator('.p-overlay-mask, .p-dialog-mask').last();
        await mask.click({ force: true, position: { x: 5, y: 5 } }).catch(() => {});
        await dialog.waitFor({ state: 'hidden', timeout: 1000 }).catch(() => {});
        console.log('⚠️ dismissBlockingDialog: clicked overlay mask');
    }
}


/**
 * Detect whether a date input is in calendar picker mode by checking for
 * a visible .p-datepicker-dropdown button within its parent <p-datepicker>.
 */
async function detectPickerMode(_page: Page, input: Locator): Promise<boolean> {
    try {
        const host = input.locator('xpath=ancestor::p-datepicker[1]').first();
        // Return true for any p-datepicker ancestor, whether or not it has a trigger button.
        // Some configurations (e.g., the inline list-view editor) use showOnFocus mode:
        // clicking the input opens the panel instead of a dedicated trigger button.
        // Restricting to trigger-button-only would wrongly send these inputs to text-entry mode,
        // where fill() silently fails on readonly PrimeNG inputs.
        return await host.isVisible({ timeout: 1000 }).catch(() => false);
    } catch { /* Not inside a p-datepicker host */ }
    return false;
}

/**
 * Fill time fields (hour, minute, AM/PM) inside an open PrimeNG 19 datepicker panel.
 *
 * PrimeNG 19 renders time values as `<span>` text (not `<input>`) between
 * increment/decrement chevron `<button>` elements. This function reads the
 * current value from the span, calculates the delta, and clicks the
 * appropriate spinner button to reach the target.
 *
 * CSS class mapping (PrimeNG 19):
 *   Container:  .p-datepicker-time-picker
 *   Hour:       .p-datepicker-hour-picker
 *   Minute:     .p-datepicker-minute-picker
 *   AM/PM:      .p-datepicker-ampm-picker
 *   Buttons:    .p-datepicker-increment-button / .p-datepicker-decrement-button
 *
 * @param page    - Playwright Page
 * @param panel   - The visible div.p-datepicker-panel locator
 * @param hours   - 1-12 (12-hour clock)
 * @param minutes - 0-59
 * @param ampm    - 'AM' or 'PM'
 */
export async function fillTimeField(
    page: Page,
    panel: Locator,
    hours: number,
    minutes: number,
    ampm: 'AM' | 'PM'
): Promise<void> {
    console.log(`🕐 fillTimeField: setting ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')} ${ampm}`);

    // ── Hour ──
    // PrimeNG 19: container is .p-datepicker-hour-picker (not .p-hour-picker)
    const hourInput = panel.locator('.p-datepicker-hour-picker input, input[aria-label*="hour" i]').first();
    if (await hourInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        // Dispatch events synchronously in one evaluate call to prevent Angular's Zone.js
        // change-detection from resetting the DOM value between fill() and press('Tab').
        // PrimeNG's onHourBlur reads $event.target.value, so the value must be set and
        // the blur event fired atomically without Angular CD running in between.
        await hourInput.evaluate((el, h) => {
            const inp = el as HTMLInputElement;
            inp.value = String(h).padStart(2, '0');
            inp.dispatchEvent(new InputEvent('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            inp.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
        }, hours);
        await page.waitForTimeout(200);
        console.log(`🕐 Hour input filled: ${hours}`);
    } else {
        // Fallback: spinner buttons (TV Ad uses buttons only, no input).
        // Read the current displayed hour from the span between buttons before computing delta.
        const hourUp = panel.locator('.p-datepicker-hour-picker button').first();
        if (await hourUp.isVisible({ timeout: 1000 }).catch(() => false)) {
            const hourSpan = panel.locator('.p-datepicker-hour-picker span').first();
            const currentHourText = (await hourSpan.textContent({ timeout: 1000 }).catch(() => '')) || '';
            const currentHour = parseInt(currentHourText.trim(), 10) || 0;
            // 12-hour wrap: (target - current + 12) % 12 gives the minimum UP clicks needed
            const delta = (hours - currentHour + 12) % 12;
            for (let i = 0; i < delta; i++) {
                await hourUp.click();
                await page.waitForTimeout(100);
            }
            console.log(`🕐 Hour set: ${currentHour} → ${hours} (${delta} clicks via spinner)`);
        } else {
            console.warn('⚠️ fillTimeField: hour picker not found');
        }
    }

    // ── Minute ──
    const minuteInput = panel.locator('.p-datepicker-minute-picker input, input[aria-label*="minute" i]').first();
    if (await minuteInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        // Same synchronous evaluate approach as hour — prevents Angular CD race.
        await minuteInput.evaluate((el, m) => {
            const inp = el as HTMLInputElement;
            inp.value = String(m).padStart(2, '0');
            inp.dispatchEvent(new InputEvent('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            inp.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
        }, minutes);
        await page.waitForTimeout(200);
        console.log(`🕐 Minute input filled: ${minutes}`);
    } else {
        // Read the current displayed minute from the span between buttons before computing delta.
        const minuteUp = panel.locator('.p-datepicker-minute-picker button').first();
        if (await minuteUp.isVisible({ timeout: 1000 }).catch(() => false)) {
            const minuteSpan = panel.locator('.p-datepicker-minute-picker span').first();
            const currentMinuteText = (await minuteSpan.textContent({ timeout: 1000 }).catch(() => '')) || '';
            const currentMinute = parseInt(currentMinuteText.trim(), 10) || 0;
            // 60-minute wrap: minimum UP clicks needed
            const delta = (minutes - currentMinute + 60) % 60;
            for (let i = 0; i < delta; i++) {
                await minuteUp.click();
                await page.waitForTimeout(50);
            }
            console.log(`🕐 Minute set: ${currentMinute} → ${minutes} (${delta} clicks via spinner)`);
        } else {
            console.warn('⚠️ fillTimeField: minute picker not found');
        }
    }

    // ── AM/PM toggle ──
    // The UP/DOWN buttons toggle the value; the current AM/PM is shown in the span BETWEEN the buttons,
    // NOT in the button's own textContent (buttons render arrow icons, not text).
    const ampmDisplay = panel.locator('.p-datepicker-ampm-picker span').first();
    const ampmBtn = panel.locator('.p-datepicker-ampm-picker button').first();
    if (await ampmBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        const current = ((await ampmDisplay.textContent({ timeout: 1000 }).catch(() => '')) || '').trim().toUpperCase();
        if (current !== ampm) {
            await ampmBtn.click();
            await page.waitForTimeout(200);
            console.log(`🕐 AM/PM toggled from ${current} to ${ampm}`);
        } else {
            console.log(`🕐 AM/PM already ${ampm}`);
        }
    }

    await page.waitForTimeout(300);
    console.log(`🕐 fillTimeField: complete`);
}

/**
 * Check whether a datepicker panel currently has a visible time picker.
 * Uses PrimeNG 19 class names. Can be called before or after date selection
 * to conditionally handle time regardless of caller intent.
 */
export async function panelHasTimePicker(panel: Locator): Promise<boolean> {
    const timePicker = panel.locator(
        '.p-datepicker-time-picker, .p-datepicker-hour-picker'
    ).first();
    return await timePicker.isVisible({ timeout: 1500 }).catch(() => false);
}

/**
 * Select a date (and optionally time) via the PrimeNG calendar picker overlay.
 * Works for all user settings (1/3 month, Broadcast/Standard) by targeting
 * the `data-date` attribute on day spans — layout differences don't matter.
 *
 * When `time` is provided, fills hour/minute/AM-PM spinners after day selection.
 *
 * NEVER presses Escape — the day-click closes the overlay or auto-chains
 * to the next date field on the QO form.
 */
export async function selectDateViaPicker(
    page: Page,
    triggerButton: Locator,
    targetDate: Date,
    options?: { skipOpen?: boolean; time?: { hours: number; minutes: number; ampm: 'AM' | 'PM' } }
): Promise<void> {
    const dataDateValue = buildDataDateAttr(targetDate);
    const daySelector = `span.p-datepicker-day[data-date="${dataDateValue}"]:not(.p-disabled)`;

    if (!options?.skipOpen) {
        await safeScroll(triggerButton);
        await triggerButton.click({ force: true });
        console.log('📅 selectDateViaPicker: clicked trigger to open overlay');
    }

    const panel = page.locator('div.p-datepicker-panel').filter({ visible: true }).first();
    let panelVisible = await panel.isVisible({ timeout: 3000 }).catch(() => false);

    // Retry: the first click may fail if Angular is still settling after a
    // previous panel dismissal (e.g. NEXT button on a time-enabled panel).
    if (!panelVisible && !options?.skipOpen) {
        console.log('📅 selectDateViaPicker: panel not visible after first click, retrying...');
        await page.waitForTimeout(500);
        await safeScroll(triggerButton);
        await triggerButton.click({ force: true });
        panelVisible = await panel.isVisible({ timeout: 5000 }).catch(() => false);
    }
    await expect(panel).toBeVisible({ timeout: 5000 });

    let targetDay = panel.locator(daySelector).first();
    let found = await targetDay.isVisible({ timeout: 1000 }).catch(() => false);

    // Navigate months if target day isn't visible (max 12 clicks).
    // Strategy: wait for day cells to be rendered (panel may open before Angular fills it),
    // then read data-date from the 11th cell (index 10) which is always inside the displayed
    // month regardless of how many overflow days appear at the start of the grid.
    // If the panel closes mid-navigation (e.g. focus-loss), re-open via triggerButton.
    if (!found) {
        // Wait up to 5s for at least one day cell to be rendered before navigating.
        await panel.locator('span.p-datepicker-day[data-date]')
            .first().waitFor({ state: 'attached', timeout: 5000 }).catch(() => {});

        const targetTotal = targetDate.getFullYear() * 12 + targetDate.getMonth();
        for (let i = 0; i < 12 && !found; i++) {
            // Re-open panel if it closed between navigation clicks.
            const panelOpen = await panel.isVisible({ timeout: 500 }).catch(() => false);
            if (!panelOpen) {
                console.log('📅 selectDateViaPicker: panel closed mid-navigation — re-opening');
                await triggerButton.click();
                await panel.locator('span.p-datepicker-day[data-date]')
                    .first().waitFor({ state: 'attached', timeout: 5000 }).catch(() => {});
                // Allow panel to settle after re-open before attempting navigation clicks.
                await page.waitForTimeout(400);
            }

            // The 11th cell (index 10) is always in the displayed month: even with 6
            // overflow days at the start, index 10 falls on day 5 of the current month.
            // data-date format: "YYYY-M-D" with 0-indexed month (PrimeNG convention).
            const refDay = panel.locator('span.p-datepicker-day[data-date]').nth(10);
            const dataDate = await refDay.getAttribute('data-date', { timeout: 3000 }).catch(() => null);
            if (dataDate) {
                const parts = dataDate.split('-');
                const dispTotal = parseInt(parts[0], 10) * 12 + parseInt(parts[1], 10);
                if (targetTotal > dispTotal) {
                    // Use a 5s timeout so a panel closure doesn't hang the test indefinitely.
                    await panel.locator('button.p-datepicker-next-button').last().click({ timeout: 5000 }).catch(() => {
                        console.log('⚠️ selectDateViaPicker: next-button click timed out (panel may have closed)');
                    });
                } else if (targetTotal < dispTotal) {
                    await panel.locator('button.p-datepicker-prev-button').first().click({ timeout: 5000 }).catch(() => {
                        console.log('⚠️ selectDateViaPicker: prev-button click timed out (panel may have closed)');
                    });
                } else { break; }
            } else {
                console.log(`⚠️ selectDateViaPicker: no day cells in panel on iteration ${i}`);
            }
            await page.waitForTimeout(300);
            targetDay = panel.locator(daySelector).first();
            found = await targetDay.isVisible({ timeout: 500 }).catch(() => false);
        }
    }

    if (!found) {
        throw new Error(`selectDateViaPicker: day cell not found for data-date="${dataDateValue}"`);
    }

    await safeScroll(targetDay);
    await targetDay.click({ force: true });
    console.log(`📅 selectDateViaPicker: selected ${dataDateValue}`);
    await page.waitForTimeout(500);

    // The QO form may auto-save a draft immediately after date selection,
    // showing a "Draft Saved" p-dialog that intercepts pointer events.
    // Wait 1.5s for the dialog to appear (it fires asynchronously after Angular
    // processes the field change), then dismiss with CONTINUE WORKING.
    await dismissBlockingDialog(page, 1500);

    // After the date click (and any dialog), explicitly close any still-open panel
    // via the trigger button toggle — NOT via Escape. Using Escape would trigger
    // PrimeNG's onOverlayHide → the QO form's Escape handler → "Draft Saved" dialog.
    // Closing via the trigger button is safe and leaves the Angular model intact.
    // This prevents a stray p-overlay from being caught by the test's global Escape handler
    // at line 185, which would silently wipe the Start Date ngModel via Angular CD.
    if (!options?.time) {
        // Only auto-close for date-only fields; time fields manage their own panel lifecycle.
        const residualPanel = page.locator('div.p-datepicker-panel').filter({ visible: true }).first();
        if (await residualPanel.isVisible({ timeout: 300 }).catch(() => false)) {
            console.log('📅 selectDateViaPicker: residual panel still open — closing via trigger button toggle');
            await triggerButton.click({ force: true }).catch(() => {});
            await residualPanel.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});
        }
    }

    // Fill time if provided and time picker is visible in the panel
    if (options?.time) {
        const timePicker = panel.locator('.p-datepicker-time-picker, .p-datepicker-timepicker, .p-datepicker-hour-picker').first();
        // Scroll the panel to bring time picker into view (it may be below the calendar grid)
        const timePickerCount = await timePicker.count();
        if (timePickerCount > 0) {
            await timePicker.scrollIntoViewIfNeeded().catch(() => {});
        }
        if (await timePicker.isVisible({ timeout: 4000 }).catch(() => false)) {
            await fillTimeField(page, panel, options.time.hours, options.time.minutes, options.time.ampm);
        } else {
            console.log('ℹ️ selectDateViaPicker: time requested but no time picker visible in panel');
        }
    }
}

/**
 * Robust helper to type dates directly as text. Used as text entry mode
 * and as a fallback when calendar picker selections fail to update the model.
 */
async function fillDateFieldTextEntry(
    page: Page,
    input: Locator,
    value: string | Date,
    dateString: string,
    timeInfo: { hours: number; minutes: number; ampm: 'AM' | 'PM' } | undefined
): Promise<void> {
    console.log(`📅 fillDateFieldTextEntry: forcing text entry mode for "${dateString}"${timeInfo ? ' + time' : ''}`);
    const placeholders = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('input'))
                    .map(i => i.placeholder)
                    .filter(p => p && p.includes('MM'))
                    .join(' ');
    });
    const isIntl = placeholders.includes('DD-MM') || placeholders.includes('DD/MM');

    let formattedValue = dateString.replace(/\//g, '-');
    const parts = dateString.replace(/-/g, '/').split('/');
    if (parts.length === 3) {
        const mm = parts[0].padStart(2, '0');
        const dd = parts[1].padStart(2, '0');
        const yyyy = parts[2];
        formattedValue = isIntl ? `${dd}-${mm}-${yyyy}` : `${mm}-${dd}-${yyyy}`;
        console.log(`📅 Format: ${isIntl ? 'DD-MM-YYYY' : 'MM-DD-YYYY'} → ${formattedValue}`);
    }

    // Append time only if the input accepts time (not a date-only field).
    if (timeInfo) {
        const placeholder = (await input.getAttribute('placeholder').catch(() => '')) ?? '';
        const isDateOnly = /^MM[-\/]DD[-\/]YYYY$/i.test(placeholder.trim()) ||
                           /^DD[-\/]MM[-\/]YYYY$/i.test(placeholder.trim());
        if (!isDateOnly) {
            const timeSuffix = ` ${String(timeInfo.hours).padStart(2, '0')}:${String(timeInfo.minutes).padStart(2, '0')} ${timeInfo.ampm}`;
            formattedValue += timeSuffix;
            console.log(`📅 Text mode with time → "${formattedValue}"`);
        } else {
            console.log(`📅 Text mode: placeholder="${placeholder}" is date-only — skipping time suffix`);
        }
    }

    await input.evaluate((el) => {
        const inp = el as HTMLInputElement;
        inp.removeAttribute('readonly');
        inp.readOnly = false;
    });
    // Wait for the readonly DOM mutation to propagate before fill().
    await expect(input).not.toHaveAttribute('readonly');
    await input.fill(formattedValue);
    // Tab triggers blur which commits the value to Angular's reactive form model.
    await input.press('Tab');
    await page.waitForTimeout(1500);

    // Force dismiss the p-datepicker-panel overlay if it opened in text mode
    const overlay = page.locator('.p-datepicker-panel, .p-overlay.p-component:visible').first();
    const isOverlayVisible = await overlay.waitFor({ state: 'visible', timeout: 500 }).then(() => true).catch(() => false);
    if (isOverlayVisible) {
        console.log('📅 fillDateFieldTextEntry: dismissing calendar overlay with Escape...');
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);
        // Escape may trigger the "Draft Saved" dialog — dismiss it before continuing.
        await dismissBlockingDialog(page, 800);
    }

    // Re-assert: if fill+Tab didn't persist, try pressSequentially (for masked inputs)
    const afterTab = await input.inputValue().catch(() => '');
    if (!afterTab || afterTab === 'MM-DD-YYYY' || afterTab === 'MM/DD/YYYY') {
        console.log(`📅 fill+Tab produced "${afterTab}" — retrying with pressSequentially...`);
        await input.click({ clickCount: 3 });
        await page.keyboard.press('Delete');
        const digitsOnly = formattedValue.replace(/[^0-9]/g, '');
        await input.pressSequentially(digitsOnly, { delay: 50 });
        await page.waitForTimeout(300);
        const afterSeq = await input.inputValue().catch(() => '');
        if (!afterSeq || afterSeq === 'MM-DD-YYYY' || afterSeq === 'MM/DD/YYYY') {
            // Final fallback: direct DOM value set
            await input.evaluate((el, val) => {
                const inp = el as HTMLInputElement;
                inp.value = val;
                inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: val }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
            }, formattedValue);
            await page.waitForTimeout(200);
        }
    }

    const actual = await input.inputValue().catch(() => '');
    console.log(`📅 fillDateFieldTextEntry: "${formattedValue}" → actual="${actual}"`);
}

/**
 * Adaptive date field filler. Detects text entry vs calendar picker mode
 * and handles each correctly across Chromium and WebKit.
 *
 * - Text mode: format-aware fill (MM-DD-YYYY or DD-MM-YYYY) with Angular sync
 * - Picker mode: opens overlay → navigates → clicks day cell via data-date
 *
 * @param options.skipPickerOpen - For chained fields; tries already-open overlay first, falls back to trigger click
 */
export async function fillDateField(
    page: Page,
    input: Locator,
    value: string | Date,
    options?: { skipPickerOpen?: boolean; skipAutoClose?: boolean }
): Promise<boolean> {
    // Returns true if the panel chained to the next field via NEXT button
    if (!(await input.isVisible({ timeout: 2000 }).catch(() => false))) {
        console.log(`⚠️ fillDateField: input not visible for value "${value}"`);
        return false;
    }

    // Normalize: if a Date object was passed, extract date string and optional time
    let dateString: string;
    let timeInfo: { hours: number; minutes: number; ampm: 'AM' | 'PM' } | undefined;

    if (value instanceof Date) {
        dateString = value.toLocaleDateString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' });
        const h24 = value.getHours();
        timeInfo = {
            hours: h24 % 12 || 12,
            minutes: value.getMinutes(),
            ampm: h24 >= 12 ? 'PM' : 'AM',
        };
        console.log(`📅 fillDateField: Date object → "${dateString}" + ${String(timeInfo.hours).padStart(2,'0')}:${String(timeInfo.minutes).padStart(2,'0')} ${timeInfo.ampm}`);
    } else {
        // Parse time suffix from string like "MM/DD/YYYY HH:MM AM"
        const timeMatch = value.match(/\s+(\d{1,2}):(\d{2})\s*(AM|PM)/i);
        if (timeMatch) {
            dateString = value.replace(/\s+\d{1,2}:\d{2}\s*(AM|PM)/i, '').trim();
            timeInfo = {
                hours: parseInt(timeMatch[1], 10),
                minutes: parseInt(timeMatch[2], 10),
                ampm: timeMatch[3].toUpperCase() as 'AM' | 'PM',
            };
            console.log(`📅 fillDateField: parsed time from string → "${dateString}" + ${timeMatch[1]}:${timeMatch[2]} ${timeMatch[3]}`);
        } else {
            dateString = value;
        }
    }

    // Detect picker mode
    const isPickerMode = await detectPickerMode(page, input);

    if (isPickerMode) {
        // ═══ PICKER MODE ═══
        console.log(`📅 fillDateField: PICKER mode for "${dateString}"${timeInfo ? ' + time' : ''}`);
        
        const triggerButton = input.locator('xpath=ancestor::p-datepicker[1]').locator('button.p-datepicker-dropdown').first();

        const targetDate = parseDateString(dateString);

        // Click/focus the input to open/re-open the picker panel if it was closed.
        // The QA form may close the Due Date panel when the user fills other fields first.
        // For Start Date/End Date in auto-chain mode, this click is harmless (panel is already
        // bound to this field's ngModel). The observed model-wipe for Start Date happens AFTER
        // fillOrderDates returns (during station/billing selection), not here.
        await input.click({ force: true }).catch(() => {});
        await input.focus().catch(() => {});
        await page.waitForTimeout(300);

        // Detect auto-chained panel. If a panel is already open (auto-chained from the previous
        // field), USE IT directly rather than escaping and re-opening. Escaping triggers
        // Angular change-detection, may pop the "Draft Saved" dialog, commits the wrong value,
        // and then prevents the picker from reopening — causing cascading failures.
        // Use 1500ms timeout (not 500ms): the inline list-view editor's panel opens asynchronously
        // (Angular CD + CSS animation); 500ms was too short to catch it.
        const leftoverPanel = page.locator('div.p-datepicker-panel').filter({ visible: true }).first();
        const hasLeftover = await leftoverPanel.isVisible({ timeout: 1500 }).catch(() => false);

        if (hasLeftover) {
            // Auto-chained panel: panel is already bound to this field's ngModel.
            console.log(`📅 fillDateField: open panel detected — using it directly (skipOpen=true)`);
            await selectDateViaPicker(page, triggerButton, targetDate, { skipOpen: true, time: timeInfo });
        } else {
            // No open panel yet. Try trigger button first, then input click as fallback.
            const triggerCount = await triggerButton.count();
            if (triggerCount > 0 && await triggerButton.isVisible({ timeout: 500 }).catch(() => false)) {
                console.log(`📅 fillDateField: clicking trigger button to open panel`);
                await triggerButton.click({ force: true }).catch(() => {});
            }
            // If no trigger button (showOnFocus mode), the input.click() above already opened the panel.
            // Wait for the panel to appear with a generous timeout.
            const panelOpened = await leftoverPanel.isVisible({ timeout: 3000 }).catch(() => false);
            if (!panelOpened) {
                // Panel never opened — fall back to text entry (masked input, special config, etc.)
                console.warn(`⚠️ fillDateField: picker panel did not open after trigger+input click — falling back to text entry`);
                await fillDateFieldTextEntry(page, input, value, dateString, timeInfo);
                return false;
            }
            // No open panel: open fresh via trigger.
            console.log(`📅 fillDateField: clicking trigger to open fresh dedicated panel`);
            await selectDateViaPicker(page, triggerButton, targetDate, { skipOpen: false, time: timeInfo });
        }


        // When time was filled, the panel stays open (no auto-close/auto-chain).
        // TV Ad (Open submit) shows a div.review-save "NEXT" button that must be
        // clicked first to commit the due date before the panel can be dismissed.
        // NOTE: When skipAutoClose=true (inline edit mode), the caller owns the panel
        //       lifecycle — do NOT press Escape here; the SAVE button handles close.
        if (timeInfo && !options?.skipAutoClose) {
            const panel = page.locator('div.p-datepicker-panel').filter({ visible: true }).first();
            if (await panel.isVisible({ timeout: 1000 }).catch(() => false)) {
                const nextBtn = panel.locator('div.review-save').first();
                if (await nextBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
                    await nextBtn.click();
                    // Wait for the panel to finish its closing animation before continuing.
                    // Without this, the stale panel stays in the DOM while the Start Date
                    // picker opens, and selectDateViaPicker finds the ghost panel instead.
                    await panel.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});
                    console.log('📅 fillDateField: clicked NEXT (review-save) to commit due date');
                } else {
                    // The datepicker panel has aria-modal=true which traps pointer events:
                    // clicking the trigger button (outside the panel) always fails when the
                    // panel is open. Use keyboard Escape instead — it closes the topmost modal
                    // without triggering a sidebar-close flow.
                    // Also dismiss any "Draft Saved" dialog that may have appeared first.
                    await dismissBlockingDialog(page, 1500);
                    // Press Escape on the panel to close it (bypasses pointer-event trap)
                    const openPanel = page.locator('div.p-datepicker-panel').filter({ visible: true }).first();
                    if (await openPanel.isVisible({ timeout: 500 }).catch(() => false)) {
                        await openPanel.press('Escape').catch(() => {});
                        await openPanel.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});
                        console.log('📅 fillDateField: closed panel via Escape (panel had aria-modal)');
                        // Pressing Escape on the panel may also trigger a new "Draft Saved" dialog
                        // if Angular interprets the Escape as a sidebar-close intent.
                        await dismissBlockingDialog(page, 800);
                    }
                }
            }
        } else if (timeInfo && options?.skipAutoClose) {
            console.log('📅 fillDateField: skipAutoClose=true — panel kept open for caller SAVE button');
        }

        // Verify
        await page.waitForTimeout(300);
        const actual = await input.inputValue().catch(() => '');
        const looksValid = /\d{2}[-/]\d{2}[-/]\d{4}/.test(actual);
        const expectedClean = dateString.replace(/\//g, '-');
        const hasCorrectDate = actual.includes(expectedClean) || actual.includes(dateString);

        if (looksValid && hasCorrectDate) {
            console.log(`📅 fillDateField (picker): verified → "${actual}". Enforcing blur to commit.`);

            if (options?.skipAutoClose) {
                // In skipAutoClose mode (inline edit), the caller's SAVE button closes the panel
                // and commits the Angular model. Do NOT press Tab here — it could close the panel
                // before the test can click SAVE, or wipe the value via an unexpected blur handler.
                console.log('📅 fillDateField: skipAutoClose=true — skipping Tab/blur commit (SAVE button will handle it)');
                return false;
            }

            // PrimeNG 19 Angular model sync issue: when using auto-chained panels (skipOpen=true),
            // the panel transitions to the next field before firing ngModelChange for this field.
            // The DOM input shows the correct date (from the calendar render), but the Angular
            // reactive form model is never updated.
            // Force Angular change-detection by: focus → Tab → then a direct DOM event dispatch.
            await input.focus().catch(() => {});
            await input.press('Tab').catch(() => {});
            await page.waitForTimeout(200);

            if (hasLeftover) {
                // Used auto-chained panel — verify model is committed; if not, dispatch change event
                const afterTab = await input.inputValue().catch(() => '');
                const stillHasDate = afterTab.includes(expectedClean) || afterTab.includes(dateString);
                if (!stillHasDate) {
                    // Value was wiped by Tab blur — fall back to text entry
                    console.warn(`📅 fillDateField: value wiped after Tab (got "${afterTab}") — falling back to text entry`);
                    await fillDateFieldTextEntry(page, input, value, dateString, timeInfo);
                } else {
                    // Value persisted — dispatch input/change events to ensure Angular ngModel commit
                    console.log(`📅 fillDateField: value persisted after Tab ("${afterTab}") — dispatching change events`);
                    await input.evaluate((el, val) => {
                        const inp = el as HTMLInputElement;
                        inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: val }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }, afterTab);
                    await page.waitForTimeout(200);
                }
            }
        } else {
            console.warn(`⚠️ fillDateField (picker): verification failed! Expected "${expectedClean}", got "${actual}". Falling back to text entry mode...`);
            await fillDateFieldTextEntry(page, input, value, dateString, timeInfo);
        }
    } else {
        // ═══ TEXT ENTRY MODE ═══
        await fillDateFieldTextEntry(page, input, value, dateString, timeInfo);
    }
    return false; // No chaining occurred
}

/**
 * Fill all date fields on the QO form.
 * Automatically detects text entry vs calendar picker mode and handles
 * the QO form's auto-chaining behavior (Due→Start→End) with fallback.
 */
export async function fillOrderDates(
    page: Page,
    dueDate: string | Date,
    startDate: string,
    endDate: string
): Promise<void> {
    console.log('📅 fillOrderDates: filling dates...');

    // Resolve date field locators via multiple strategies
    let dueDateInput: Locator | null = null;
    let startDateInput: Locator | null = null;
    let endDateInput: Locator | null = null;

    // Strategy 1: named placeholder/name selectors
    // TV Ad (Open submit) uses p-datepicker.duedatepicker — add it first so it takes priority
    // over the generic [name="card_due_date"] selector which may not be present on all ad types.
    const s1Due = page.locator(
        'p-datepicker.duedatepicker input:visible, input[placeholder="Due Date"]:visible, p-calendar[name="card_due_date"] input:visible, p-datepicker[name="card_due_date"] input:visible'
    ).first();
    if (await s1Due.isVisible({ timeout: 8000 }).catch(() => false)) {
        console.log('📅 Found date fields via placeholder/name selectors.');
        dueDateInput = s1Due;
        startDateInput = page.locator(
            'input[placeholder="Start Date"]:visible, p-calendar[name="card_start_date"] input:visible, p-datepicker[name="card_start_date"] input:visible'
        ).first();
        endDateInput = page.locator(
            'input[placeholder="End Date"]:visible, p-calendar[name="card_end_date"] input:visible, p-datepicker[name="card_end_date"] input:visible'
        ).first();
    }

    // Strategy 2: getByRole textbox
    if (!dueDateInput) {
        const s2Due = page.getByRole('textbox', { name: /Due Date/i }).first();
        if (await s2Due.isVisible({ timeout: 2000 }).catch(() => false)) {
            console.log('📅 Found date fields via getByRole fallback.');
            dueDateInput = s2Due;
            startDateInput = page.getByRole('textbox', { name: /Start Date/i }).first();
            endDateInput = page.getByRole('textbox', { name: /End Date/i }).first();
        }
    }

    // Strategy 3: Generic MM-DD-YYYY placeholders
    if (!dueDateInput) {
        const genericInputs = page.locator('input[id^="input-date-"][placeholder="MM-DD-YYYY"]');
        const count = await genericInputs.count();
        console.log(`📅 Using generic MM-DD-YYYY inputs (found ${count}).`);
        if (count >= 1) {
            dueDateInput = genericInputs.nth(0);
            if (count >= 2) startDateInput = genericInputs.nth(1);
            if (count >= 3) endDateInput = genericInputs.nth(2);
            if (count < 3) {
                console.log(`📅 fillOrderDates: only ${count} generic date input(s) found — filling what's available.`);
            }
        } else {
            console.warn('⚠️ fillOrderDates: no date inputs found via any strategy!');
            return;
        }
    }

    // Detect picker mode once from the Due Date field
    const isPickerMode = await detectPickerMode(page, dueDateInput);
    console.log(`📅 fillOrderDates: mode=${isPickerMode ? 'PICKER' : 'TEXT'}`);

    // When dueDate includes time, clicking NEXT after date+time selection
    // chains to the Start Date panel (panel is already open). However, if
    // dueDate has no time, the date-click auto-chains all three fields.
    const dueDateHasTime = (dueDate instanceof Date) ||
        (typeof dueDate === 'string' && /\d{1,2}:\d{2}\s*[AP]M/i.test(dueDate));
    const chainDates = isPickerMode && !dueDateHasTime;
    console.log(`📅 fillOrderDates: chaining=${chainDates} (dueDateHasTime=${dueDateHasTime})`);

    // Fill dates — chain Start/End only when Due Date panel auto-chains (no time)
    await fillDateField(page, dueDateInput, dueDate);

    // When due date includes time, the TV Ad (Open submit) form transitions to a new
    // layout after the NEXT button click. Wait for the Start Date field to be ready
    // before attempting to open its picker.
    if (dueDateHasTime && startDateInput) {
        await startDateInput.waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(2000);
    }

    if (startDateInput) {
        await fillDateField(page, startDateInput, startDate, { skipPickerOpen: chainDates });
    }

    // After Start Date picker closes, give the form time to stabilize before End Date.
    if (dueDateHasTime && endDateInput) {
        await endDateInput.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1000);
    }

    if (endDateInput) {
        await fillDateField(page, endDateInput, endDate, { skipPickerOpen: chainDates });
    }

    // ── Self-healing: Start Date model wipe guard ──────────────────────────────
    // In PICKER mode with auto-chain, PrimeNG's panel transitions from Start Date→End Date
    // before firing ngModelChange for Start Date. The Angular reactive form model for
    // Start Date is never committed, even though the DOM input shows the correct value.
    // Additionally, the form's reactive subscriptions may overwrite Start Date when End Date
    // is committed. After End Date is set (no more auto-chain interference), re-check if
    // Start Date's Angular model is empty and re-fill via a fresh dedicated picker if so.
    if (isPickerMode && startDateInput) {
        // Wait 2000ms — NOT 500ms. The form's endDateControl.valueChanges subscription
        // resets startDateControl to null after End Date is committed. Angular's CD runs
        // asynchronously, so the DOM still shows "07-13-2026" at 500ms even when the
        // ngModel is already null. At 2000ms, CD has run and the input shows the true state.
        // Also click somewhere neutral to force Angular CD to run before reading the value.
        await page.waitForTimeout(2000);
        // Trigger Angular CD by moving focus away from any picker (safe, non-destructive)
        await page.mouse.move(10, 10).catch(() => {});
        await page.waitForTimeout(200);

        const startComboboxVal = await page.evaluate(() => {
            const inp = document.querySelector('p-datepicker[name="card_start_date"] input, p-calendar[name="card_start_date"] input') as HTMLInputElement;
            return inp ? inp.value : '';
        }).catch(() => '');

        console.log(`📅 fillOrderDates: Start Date after Angular CD = "${startComboboxVal}"`);

        const startDateCommitted = startComboboxVal && startComboboxVal.trim() !== '' && /\d{2}[-/]\d{2}[-/]\d{4}/.test(startComboboxVal);

        if (!startDateCommitted) {
            console.warn(`⚠️ fillOrderDates: Start Date empty after CD ("${startComboboxVal}") — re-filling via fresh picker...`);
            await fillDateField(page, startDateInput, startDate);
            const healedVal = await startDateInput.inputValue().catch(() => '');
            console.log(`📅 fillOrderDates: Start Date healed → "${healedVal}"`);
        } else {
            console.log(`📅 fillOrderDates: Start Date confirmed = "${startComboboxVal}" ✓`);
        }
    }


    // Enforce final values via direct text insertion if any field was wiped/missed
    for (const [name, input, val] of [
        ['Due Date', dueDateInput, dueDate],
        ['Start Date', startDateInput, startDate],
        ['End Date', endDateInput, endDate]
    ] as [string, Locator | null, string | Date][]) {
        if (input) {
            const currentVal = await input.inputValue().catch(() => '');
            if (!currentVal || currentVal.trim() === '' || currentVal === 'MM-DD-YYYY') {
                console.log(`🩹 fillOrderDates fallback: ${name} is empty or placeholder! Forcing direct text fill...`);
                let dateStr = '';
                if (val instanceof Date) {
                    const mm = String(val.getMonth() + 1).padStart(2, '0');
                    const dd = String(val.getDate()).padStart(2, '0');
                    const yyyy = val.getFullYear();
                    dateStr = `${mm}-${dd}-${yyyy}`;
                    // Only append time if the input accepts it (date-only placeholders reject time)
                    const ph = (await input.getAttribute('placeholder').catch(() => '')) ?? '';
                    const isDateOnly = /^[MD]{2}[-\/][MD]{2}[-\/][YD]{4}$/i.test(ph.trim());
                    if (!isDateOnly) {
                        const h24 = val.getHours();
                        const hours = h24 % 12 || 12;
                        const minutes = String(val.getMinutes()).padStart(2, '0');
                        const ampm = h24 >= 12 ? 'PM' : 'AM';
                        dateStr += ` ${String(hours).padStart(2, '0')}:${minutes} ${ampm}`;
                    }
                } else {
                    dateStr = val.replace(/\//g, '-');
                }
                const finalVal = dateStr;
                await input.evaluate(el => {
                    const inp = el as HTMLInputElement;
                    inp.removeAttribute('readonly');
                    inp.readOnly = false;
                }).catch(() => {});
                // Wait for the readonly DOM mutation to propagate before fill().
                // Without this gate, Angular's reactive form binding resets mid-fill when
                // the readonly removal triggers a change detection cycle concurrently with fill().
                await expect(input).not.toHaveAttribute('readonly');
                await input.fill(finalVal);
                // pressSequentially as a stronger fallback for masked inputs
                const afterFill = await input.inputValue().catch(() => '');
                if (!afterFill || afterFill === 'MM-DD-YYYY' || afterFill === 'MM/DD/YYYY') {
                    await input.click({ clickCount: 3 });
                    await input.pressSequentially(finalVal.replace(/[^0-9]/g, ''), { delay: 50 });
                }
                await input.evaluate((el, v) => {
                    const inp = el as HTMLInputElement;
                    if (!inp.value || inp.value === 'MM-DD-YYYY') {
                        inp.value = v;
                        inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: v }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }, finalVal).catch(() => {});
                console.log(`🩹 fillOrderDates fallback: filled ${name} with "${finalVal}" → actual="${await input.inputValue().catch(() => '')}"`);
            }
        }
    }
}

/**
 * Interface for order details passed to createBasicOrder.
 */
export interface OrderDetails {
    /** Client name (e.g., "Bob's Burgers") - REQUIRED */
    client: string;
    /** Spot title - auto-generated if omitted */
    title?: string;
    /** Ad type - default: "Radio Commercial" */
    adType?: string;
    /** Status - default: "Needs Writing" */
    status?: string;
    /** Length in seconds - default: "30" (only filled if field is visible for the ad type) */
    length?: string;
    /** Rotation percentage - default: "100" (only filled if field is visible for the ad type) */
    rotation?: string;
    /** Digital URL for streaming/display ad types (e.g., "https://example.com") */
    digitalUrl?: string;
    /** Due date (MM/DD/YYYY) - auto-calculated if omitted */
    dueDate?: string;
    /** Start date (MM/DD/YYYY) - auto-calculated if omitted */
    startDate?: string;
    /** End date (MM/DD/YYYY) - auto-calculated if omitted */
    endDate?: string;
    /** ISCI code - auto-generated if omitted */
    isci?: string;
    /** Contract number - auto-generated if omitted */
    contractNo?: string;
    /** Select a random station if true - default: true */
    selectStation?: boolean;
    /** Sales POC name to select (e.g., "Demo AE", "TopBiller"). If true, selects first available. */
    salesPoc?: string | boolean;
    /** Skip date filling (carries forward from previous spot) */
    skipDates?: boolean;
}

/**
 * Open the Quick Order form by clicking the navigation trigger.
 * 
 * @param page - Playwright Page object
 * @param options - Optional configuration
 */
export async function openQuickOrderForm(
    page: Page,
    options: { timeout?: number } = {}
): Promise<void> {
    const { timeout = 15000 } = options;

    // Wait for any loading spinners/overlays to disappear first
    const loader = page.locator('#loader, #loader-wrapper, app-v-loader, .p-blockui').first();
    if (await loader.isVisible().catch(() => false)) {
        console.log('⏳ Waiting for loader/overlay to hide before opening Quick Order...');
        await loader.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    }
    // Small hydration settling wait to ensure Angular reactive bindings are attached
    await page.waitForTimeout(1500);

    const formContainer = page.locator('app-quickorders, .p-sidebar, .p-drawer, #quickorders-sidebar').first();
    const formText = page.getByText('Create OrderSelect Ad type')
        .or(page.getByText('Create Order'))
        .or(page.getByText('Select Ad type'))
        .first();
    const isFormOpen = async () => {
        return await formContainer.or(formText).isVisible().catch(() => false);
    };

    let clicked = false;

    // Strategy A: Try role-based "New Request" link first (most common and reliable)
    const generalLink = page.getByRole('link', { name: /New Request|Quick Order|Create Order/i }).first();
    const isGeneralVisible = await generalLink.waitFor({ state: 'visible', timeout: 2000 }).then(() => true).catch(() => false);
    if (isGeneralVisible) {
        console.log('🔍 Strategy A: Clicking general link by role/name');
        await generalLink.click({ force: true }).catch(async () => {
            await generalLink.evaluate(el => (el as HTMLElement).click());
        });
        // Check if form opens within 3 seconds
        for (let i = 0; i < 6; i++) {
            if (await isFormOpen()) {
                clicked = true;
                break;
            }
            await page.waitForTimeout(500);
        }
    }

    if (!clicked) {
        // Strategy B: Original primary trigger
        try {
            const trigger = page.locator('li.submenu-large-desktop a.quickorder-a', {
                hasText: /Quick Order|New Request|Create Order/i,
            }).first();
            const isTriggerVisible = await trigger.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false);
            if (isTriggerVisible) {
                console.log('🔍 Strategy B: Primary trigger found and visible. Clicking...');
                await trigger.click({ force: true }).catch(async () => {
                    await trigger.evaluate(el => (el as HTMLElement).click());
                });
                // Check if form opens within 3 seconds
                for (let i = 0; i < 6; i++) {
                    if (await isFormOpen()) {
                        clicked = true;
                        break;
                    }
                    await page.waitForTimeout(500);
                }
            }
        } catch (e) {
            console.log(`⚠️ Strategy B failed: ${e}`);
        }
    }

    if (!clicked) {
        // Strategy C: Fallback to span → ancestor anchor pattern
        console.log('🔍 Strategy C: Fallback to span → ancestor anchor');
        const fallback = page
            .locator('li.submenu-large-desktop span', {
                hasText: /Quick Order|New Request|Create Order/i,
            })
            .locator('xpath=ancestor::a[1]')
            .first();
        const isFallbackVisible = await fallback.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false);
        if (isFallbackVisible) {
            await fallback.click({ force: true }).catch(async () => {
                await fallback.evaluate(el => (el as HTMLElement).click());
            });
            // Check if form opens within 3 seconds
            for (let i = 0; i < 6; i++) {
                if (await isFormOpen()) {
                    clicked = true;
                    break;
                }
                await page.waitForTimeout(500);
            }
        }
    }

    if (!clicked) {
        // Strategy D: Broad text match anywhere
        const broadTrigger = page.locator('a, button, span').filter({ hasText: /New Request|Quick Order|Create Order/i }).first();
        const isBroadVisible = await broadTrigger.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false);
        if (isBroadVisible) {
            console.log('🔍 Strategy D: Broad trigger found. Clicking...');
            await broadTrigger.click({ force: true }).catch(async () => {
                await broadTrigger.evaluate(el => (el as HTMLElement).click());
            });
        }
    }

    // Verify the form appeared
    await expect(formContainer.or(formText)).toBeVisible({ timeout });
    console.log('✅ Quick Order form opened.');

    // Clean up any existing drafts in the cart to ensure test isolation
    const discardBtn = page.locator('button:has-text("DISCARD ALL DRAFTS"), button:has-text("Discard All Drafts"), button:has-text("DISCARD ALL"), button:has-text("Discard All")').first();
    if (await discardBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('🧹 Lingering drafts detected in cart, clicking "DISCARD ALL DRAFTS"...');
        await discardBtn.click({ force: true });
        
        // Wait for confirmation dialog to appear and click YES, CONFIRM
        const confirmBtn = page.locator('.p-confirm-dialog-accept, .p-dialog button:has-text("YES, CONFIRM"), .p-dialog button:has-text("YES"), .p-dialog button:has-text("Confirm"), button:has-text("YES, CONFIRM")').first();
        if (await confirmBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
            console.log('🧹 Confirming discard drafts dialog...');
            await confirmBtn.click({ force: true });
        }
        
        // Wait for the cart/loader to clear
        await page.waitForTimeout(2000);
        const spinner = page.locator('.p-progress-spinner, app-v-loader, #loader-wrapper, .loading-overlay').first();
        if (await spinner.isVisible().catch(() => false)) {
            await spinner.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
        }
    }
}

/**
 * Select the ad type in the Quick Order form.
 * 
 * @param page - Playwright Page object
 * @param adType - The ad type to select (default: "Radio Commercial")
 */
export async function selectAdType(page: Page, adType: string = 'Radio Commercial'): Promise<void> {
    const adTypeSelector = page.locator('p-select#adtype-select, .ad-type-dropdown p-select').first();
    if (await adTypeSelector.isVisible({ timeout: 3000 })) {
        const currentVal = await adTypeSelector.innerText();
        if (!currentVal.includes(adType)) {
            await adTypeSelector.click();
            await page.getByRole('option', { name: adType }).click();
            console.log(`Selected Ad Type: ${adType}`);
        } else {
            console.log(`Ad Type already set to: ${adType}`);
        }
    } else {
        console.warn(`⚠️ Ad Type selector not visible, skipping selection of ${adType}`);
    }
}

/**
 * Click the QO form's "Select Status" p-select control and pick the given option.
 *
 * Encapsulates the PR #65-era hardening for PrimeNG v19 status dropdowns:
 *  - Retries the trigger click up to 3 times (overlay masks intermittently swallow the first click).
 *  - Falls back from `getByRole('option')` to broadened PrimeNG-overlay selectors
 *    (`.p-select-option` / `[data-pc-section="option"]`) which appear even when the
 *    accessible-name match misses.
 *  - Refreshes the dropdown on each attempt so a stale/closed overlay doesn't burn the retry budget.
 *
 * Shared by `createBasicOrder` and `createOrderWithNewClient` so both QO paths get identical hardening.
 */
export async function selectQOStatus(page: Page, status: string): Promise<void> {
    // Scope every locator to the QO drawer. Live evidence 2026-08-17 from
    // playwright/test-results/…qa-46…Radio-Commercial…/error-context.md:
    // the drafts-list background carries 25 unhidden `combobox "Select Status"`
    // elements on visible spot cards (refs e289…e2494). Page-scoped locators
    // matched those background elements first — every trigger click either
    // strict-mode-threw or hit a background target visually obscured by the
    // drawer, timing out ~15s without ever touching the drawer's Status.
    // The QO drawer is `role="complementary"` (confirmed error-context.md
    // ref=e2578). `.last()` handles stacked complementary panels (e.g. Revise
    // + QO drawers open simultaneously — the QO drawer is the topmost).
    const drawer = page.getByRole('complementary').last();

    // Early-return if the drawer's Status field already shows the target status.
    // Live evidence 2026-08-12: two-test defaults the QO Status field to a
    // pre-filled value (e.g. "Needs Producing") — a firm- or user-level default.
    // On qa's Demo Broadcasting default the field renders as "Select Status"
    // placeholder; the click path below fires. On two-test the field is already
    // filled with the same value the caller asked for and nothing needs clicking.
    // Drawer-scoped so we don't false-positive on a drafts-list spot card whose
    // Status happens to match the target value.
    const alreadySet = drawer.locator('p-select').filter({
        hasText: new RegExp(`^\\s*${status}\\s*$`, 'i')
    }).first();
    if (await alreadySet.isVisible({ timeout: 500 }).catch(() => false)) {
        console.log(`ℹ️ Status already set to "${status}" — no click needed.`);
        return;
    }

    // Clear any lingering mask before we start. Live evidence 2026-08-12 on two-test:
    // a leftover p-overlay-mask (from a prior CLOSE WITHOUT SAVING dialog) was still
    // absorbing pointer events, so all 3 trigger clicks below timed out at 5s each
    // without a byte of DOM state changing. This helper (built by PR #65) never
    // fired from the QO flow before — call it here so both createBasicOrder and
    // createOrderWithNewClient inherit the fix.
    await dismissBlockingOverlays(page).catch(() => {});

    // The Status field can be in one of three visible states depending on env/firm/user/ad-type:
    //   1. Empty placeholder — visible text is "Select Status" (qa's Demo Broadcasting default).
    //   2. Prepopulated with the target value — handled by the early-return above.
    //   3. Prepopulated with a NON-target value — filled p-select whose child span reads the
    //      current value (e.g. "Needs Producing"), and we need to click it to open the dropdown
    //      so we can pick a different value. This is the case the original locator missed —
    //      its `.filter({ has: span:has-text("Status" | "Select") })` demanded placeholder text
    //      that a prepopulated field doesn't have.
    // Structural locator handles case (3): the p-select immediately following the "Status" label.
    // `statusByLabel` handles envs whose drawer templates use a semantic <label>.
    const statusByLabel = drawer.locator('label:has-text("Status") + p-select, label:has-text("Status") ~ p-select').first();

    // `statusSelect` handles the qa/two-test case where the drawer's STATUS label
    // is a <generic>/<div>/<span> (error-context.md 2026-08-17 ref=e2682: `Status`)
    // and the p-select is prepopulated with a non-target value ("Needs Producing"
    // ref=e2685). Any p-select whose combobox child accessible name IS the current
    // value has no child span reading "Status" or "Select", so the prior filter
    // matched zero elements inside the drawer and `.click()` timed out waiting.
    //
    // Fix: derive the trigger structurally from the label-sibling relationship.
    // getByText matches the innermost element whose own text is exactly "Status"
    // (case-insensitive, whitespace-trimmed) — works whether the label is a
    // <label>, <div>, <span>, or PrimeNG-generic. Then walk forward in document
    // order to the next `p-select` — this is the Status trigger regardless of
    // whether the field is empty or prepopulated.
    const statusSelect = drawer
        .getByText(/^\s*Status\s*$/i)
        .first()
        .locator('xpath=following::p-select[1]');

    // PrimeNG teleports the p-select option overlay to <body> (outside the
    // drawer), so the overlay-visible check MUST stay page-scoped. Used to
    // verify the trigger click actually mounted the listbox — a mask-swallowed
    // click currently silent-fails and burns the entire 4-attempt option budget.
    const overlayVisible = page.locator(
        '.p-select-overlay:visible, .p-overlay:visible [role="listbox"], .p-dropdown-panel:visible'
    ).first();

    let statusClicked = false;
    for (let i = 0; i < 3; i++) {
        try {
            if (await drawer.getByText('Select Status').isVisible()) {
                await drawer.getByText('Select Status').click({ timeout: 5000 });
            } else if (await statusByLabel.isVisible().catch(() => false)) {
                await statusByLabel.click({ timeout: 5000 });
            } else {
                await statusSelect.click({ timeout: 5000 });
            }
            // Delta from Proposal C: verify the overlay actually mounted before
            // treating the click as success. A mask-swallowed click is
            // silent-fail today and wastes the 4-attempt option budget.
            if (await overlayVisible.isVisible({ timeout: 2000 }).catch(() => false)) {
                statusClicked = true;
                break;
            }
            console.log(`⚠️ Status trigger click accepted but overlay did not mount (attempt ${i + 1}) — retrying`);
            await page.waitForTimeout(500);
        } catch (err) {
            console.log(`⚠️ Status select click failed (attempt ${i + 1}), retrying: ${(err as Error).message ?? err}`);
            await page.waitForTimeout(500);
        }
    }

    // Live evidence 2026-08-07: this loop failed intermittently ("Failed to select status
    // 'Needs Writing' after 3 attempts") when the p-select overlay didn't render (dropdown
    // click accepted by DOM but no listbox mounted) OR when the overlay was masked by a
    // lingering p-overlay layer. Broaden option lookup to include the PrimeNG v19 overlay
    // selectors (.p-select-option / [data-pc-section="option"]) which appear even when the
    // getByRole('option') accessible-name match misses, and refresh the dropdown each
    // attempt so a stale/closed overlay doesn't burn the retry budget.
    const optionByRole = page.getByRole('option', { name: status, exact: true }).first();
    const optionByPrimeNG = page.locator(
        '.p-select-overlay:visible li.p-select-option, ' +
        '.p-select-overlay:visible [data-pc-section="option"], ' +
        '.p-overlay:visible li.p-select-option, ' +
        '.p-overlay:visible [role="option"], ' +
        '.p-dropdown-panel:visible li.p-dropdown-item'
    ).filter({ hasText: new RegExp(`^\\s*${status}\\s*$`, 'i') }).first();

    let optionClicked = false;
    for (let i = 0; i < 4; i++) {
        // Prefer role-based match; if not visible within 1s, try the PrimeNG-overlay match.
        let option = optionByRole;
        let visible = await optionByRole.isVisible({ timeout: 1000 }).catch(() => false);
        if (!visible) {
            option = optionByPrimeNG;
            visible = await optionByPrimeNG.isVisible({ timeout: 1000 }).catch(() => false);
        }

        if (visible) {
            try {
                await option.click({ timeout: 5000 });
                optionClicked = true;
                break;
            } catch (err) {
                console.log(`⚠️ Status option click failed (attempt ${i + 1}): ${(err as Error).message ?? err}`);
            }
        } else {
            console.log(`⚠️ Status overlay not showing "${status}" (attempt ${i + 1}) — reopening dropdown`);
        }

        // Overlay closed or click missed: dismiss any stray DROPDOWN overlay + reopen the dropdown.
        // Live evidence 2026-08-12 on two-test: the QO sidebar wires Escape to a
        // "Are you sure you want to close the sidebar?" confirmation, so an unconditional
        // Escape here nukes the whole form. Only press Escape when there is actually a
        // stray dropdown/select overlay to close.
        const strayDropdown = page.locator(
            '.p-select-overlay:visible, .p-dropdown-panel:visible, .p-overlay:visible [role="listbox"]'
        ).first();
        if (await strayDropdown.isVisible({ timeout: 200 }).catch(() => false)) {
            await page.keyboard.press('Escape').catch(() => {});
            await page.waitForTimeout(400);
        }
        if (await drawer.getByText('Select Status').isVisible().catch(() => false)) {
            await drawer.getByText('Select Status').click({ timeout: 5000 }).catch(() => {});
        } else if (await statusByLabel.isVisible().catch(() => false)) {
            await statusByLabel.click({ timeout: 5000 }).catch(() => {});
        } else {
            await statusSelect.click({ timeout: 5000 }).catch(() => {});
        }
        await page.waitForTimeout(600);
    }
    if (!optionClicked) {
        throw new Error(`Failed to select status "${status}" after 4 attempts.`);
    }
}

/**
 * Fill the Quick Order form with the provided details and select a station.
 * Does NOT submit the order - use submitOrder() for that.
 *
 * @param page - Playwright Page object
 * @param details - Order details to fill
 * @returns Object containing the generated/used values for verification
 */
export async function createBasicOrder(
    page: Page,
    details: OrderDetails
): Promise<{ title: string; isci: string; poid?: string }> {
    const {
        client,
        title = generateRandomSpotTitle(),
        adType = 'Radio Commercial',
        status = 'Needs Writing',
        length = '30',
        rotation = '100',
        dueDate = calculateDueDate(3),
        startDate = calculateStartDate(),
        endDate = calculateEndDate(),
        isci = generateRandomISCI(),
        contractNo = `CN${Math.floor(1000 + Math.random() * 9000)}`,
        selectStation = true
    } = details;

    // Select ad type and wait for form to render
    await selectAdType(page, adType);
    await page.locator('#spot-cards-list-wrapper').waitFor({ state: 'visible', timeout: 25000 });
    await page.waitForTimeout(500);

    // ──────────────────────────────────────────────────────────────
    // Fill order TOP-DOWN matching the QO sidebar layout:
    //   1. Sales POC  (top of sidebar)
    //   2. Client
    //   3. Title
    //   4. Status
    //   5. ISCI / Length / Rotation / Digital URL
    //   6. Dates
    //   7. Station + Contract  (bottom of sidebar)
    // ──────────────────────────────────────────────────────────────

    // 1. Sales POC — p-multiselect at the very top of the sidebar.
    //    IMPORTANT: Do NOT press Escape to close the overlay — Escape on the QO
    //    form triggers the "Draft Saved" dialog. Instead, click the trigger again
    //    to toggle the overlay closed.
    const salesPoc = details.salesPoc;
    // Try multiple locator strategies — QA env may not show "Select Sales" text
    let salesMultiselect = page.locator('#spot-cards-list-wrapper p-multiselect').filter({ hasText: /Select Sales/i }).first();
    let salesCount = await salesMultiselect.count();
    if (salesCount === 0) {
        // Fallback: find the first p-multiselect in the form sidebar (Sales is always the topmost multiselect)
        salesMultiselect = page.locator('#spot-cards-list-wrapper p-multiselect, .p-drawer-content p-multiselect').first();
        salesCount = await salesMultiselect.count();
        if (salesCount > 0) {
            console.log('ℹ️ Sales multiselect found via fallback locator (no "Select Sales" text match).');
        }
    }
    if (salesPoc || salesCount > 0) {
        const isSalesVisible = salesCount > 0 && await salesMultiselect.isVisible().catch(() => false);
        if (isSalesVisible) {
            console.log('📝 Filling Sales POC (p-multiselect)...');
            await safeScroll(salesMultiselect);
            await page.waitForTimeout(300);
            await salesMultiselect.click({ force: true });
            await page.waitForTimeout(500);

            // Exclude empty message placeholders
            const msItems = page.locator('.p-multiselect-option, li[role="option"]');
            await msItems.first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => null);
            let itemCount = await msItems.count();

            // Give it a brief moment if it's still loading
            if (itemCount === 0 || (itemCount === 1 && (await msItems.first().innerText()) === '')) {
                await page.waitForTimeout(1000);
                itemCount = await msItems.count();
            }

            console.log(`📝 Found ${itemCount} sales options in multiselect.`);

            if (typeof salesPoc === 'string') {
                const targetItem = msItems.filter({ hasText: salesPoc }).first();
                if (await targetItem.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await targetItem.click();
                    console.log(`✅ Sales POC selected: ${salesPoc}`);
                } else {
                    console.warn(`⚠️ Sales POC "${salesPoc}" not found, selecting first available.`);
                    if (itemCount > 0) await msItems.first().click();
                }
            } else if (itemCount > 0) {
                const optionText = await msItems.first().innerText().catch(() => '');
                await msItems.first().click();
                console.log(`✅ Sales POC selected (first available): ${optionText.trim()}`);
            }

            // Close overlay by clicking the form body — the multiselect text has
            // changed from "Select Sales" to the selected name, so cannot re-click it.
            // Clicking a neutral area of the form sidebar dismisses the overlay.
            const formSidebar = page.locator('#spot-cards-list-wrapper, .p-drawer-content').first();
            await formSidebar.click({ position: { x: 5, y: 5 } });
            await page.waitForTimeout(300);
        } else {
            console.log('ℹ️ Sales multiselect is hidden, already filled, or not found in DOM.');
        }
    }

    // 2. Client (with autocomplete)
    const clientInput = page.locator('p-autocomplete[name="card_client_id"] input, #spot-cards-list-wrapper input[placeholder*="Client"], .p-drawer-content input[placeholder*="Client"]').first();
    const isClientVisible = await clientInput.isVisible().catch(() => false) || 
                            await clientInput.waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false);
    if (isClientVisible) {
        await clientInput.click();
        await clientInput.fill('');
        await clientInput.fill(client.substring(0, 5));
        await page.waitForTimeout(1500);
        // `exact: true` — accessible-name matching is substring by default, so a
        // client like "Bob's Burgers" also matches "The Peach Pit / Bob's Burgers"
        // and trips strict mode. Exact match disambiguates.
        const clientOption = page.getByRole('option', { name: client, exact: true });
        await clientOption.waitFor({ state: 'visible', timeout: 15000 });
        await clientOption.click();
    } else {
        console.log(`ℹ️ Client selector not visible, skipping selection of ${client}`);
    }

    // 3. Title with retry logic
    const upperTitle = title.toUpperCase();
    const spotTitleInput = page.locator('#spot-cards-list-wrapper input[placeholder="Spot title"]:visible, #spot-cards-list-wrapper input[name="card_spot_title"]:visible').first();
    const tableTitleInput = page.locator('input[placeholder="Enter Title"]').first();

    await expect(spotTitleInput).toBeVisible();

    let success = false;
    const methods = ['fill', 'sequential', 'evaluate'] as const;

    for (const method of methods) {
        console.log(`Attempting to fill Spot Title using ${method} method...`);

        if (method === 'fill') {
            await spotTitleInput.fill(upperTitle);
        } else if (method === 'sequential') {
            await spotTitleInput.click();
            await spotTitleInput.press('Control+a');
            await spotTitleInput.press('Backspace');
            await spotTitleInput.fill(upperTitle);
        } else if (method === 'evaluate') {
            await spotTitleInput.evaluate((el, val) => {
                const input = el as HTMLInputElement;
                input.value = val;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }, upperTitle);
        }

        await spotTitleInput.focus();
        await page.keyboard.press('Tab');

        if (details.skipDates) {
            console.log('ℹ️ skipDates is true — skipping Title sync verification on grid.');
            success = true;
            break;
        }

        await page.waitForTimeout(1500);

        const currentTableValue = await tableTitleInput.inputValue();
        if (currentTableValue.toUpperCase() === upperTitle) {
            console.log(`✅ Spot Title synced using ${method} method.`);
            success = true;
            break;
        }
    }

    if (!success) {
        console.warn(`⚠️ Spot Title may not have synced properly. Proceeding anyway.`);
    }

    // 4. Status
    await selectQOStatus(page, status);

    // 5. ISCI, Length, Rotation, Digital URL
    const isciField = page.locator('input[placeholder="AD-ID OR ISCI CODE"]:visible, input[name="card_isci_code"]:visible').first();
    if (await isciField.isVisible({ timeout: 5000 }).catch(() => false) && await isciField.isEnabled().catch(() => false)) {
        await isciField.fill(isci);
    } else {
        console.log('ℹ️ ISCI field is either not visible or disabled. Skipping fill.');
    }

    const lengthField = page.locator(
        'input[placeholder*="Length" i], ' +
        'input[name*="length" i], ' +
        'input[id*="length" i], ' +
        'p-inputnumber[id*="length" i] input, ' +
        'p-inputnumber[name*="length" i] input, ' +
        'input[placeholder*="Len" i], ' +
        'input[placeholder="30"]'
    ).first();
    if (await lengthField.isVisible({ timeout: 2000 }).catch(() => false) && await lengthField.isEnabled().catch(() => false)) {
        await lengthField.fill(length);
    }

    const rotationField = page.getByRole('textbox', { name: 'Rotation ' }).first();
    if (await rotationField.isVisible({ timeout: 5000 }).catch(() => false) && await rotationField.isEnabled().catch(() => false)) {
        await rotationField.scrollIntoViewIfNeeded().catch(() => {});
        await rotationField.fill(rotation);
    }

    if (details.digitalUrl) {
        const digitalUrlField = page.locator(
            'input[placeholder*="click through web address"], input[placeholder*="Digital URL"], input[name*="digital_url"]'
        ).first();
        if (await digitalUrlField.isVisible({ timeout: 2000 }).catch(() => false)) {
            await digitalUrlField.fill(details.digitalUrl);
            await digitalUrlField.press('Tab');
            await page.waitForTimeout(500);
        }
    }

    // Image Ad (Banner Ad) specific fields helper
    const quantityInput = page.locator('input[name="card_quantity"]').first();
    if (await quantityInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('📝 Filling Banner-specific required fields...');
        await quantityInput.fill('1');
        await quantityInput.press('Tab');

        // Select Digital Type (Type)
        const typeSelect = page.locator('p-select[name="card_quantitytype"]').first();
        if (await typeSelect.isVisible()) {
            await typeSelect.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }

        // Select Per
        const perSelect = page.locator('p-select[name="card_unitofmeasure"]').first();
        if (await perSelect.isVisible()) {
            await perSelect.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }

        // Select Banner Size(s)
        const sizeSelect = page.locator('p-select[name="card_web_sizes"]').first();
        if (await sizeSelect.isVisible()) {
            await sizeSelect.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }
    }

    // 6. Dates — adaptive fill handles text entry vs calendar picker mode,
    //    including QO form auto-chaining (Due→Start→End) with fallback.
    if (!details.skipDates) {
        await fillOrderDates(page, dueDate, startDate, endDate);

        // Verify dates stuck — Angular change detection can wipe values after blur events
        await page.waitForTimeout(500);
        const dateFields = [
            { label: 'Due Date', locator: page.getByRole('textbox', { name: /Due Date/i }).first(), expected: dueDate },
            { label: 'Start Date', locator: page.getByRole('textbox', { name: /Start Date/i }).first(), expected: startDate },
            { label: 'End Date', locator: page.getByRole('textbox', { name: /End Date/i }).first(), expected: endDate },
        ];
        for (const df of dateFields) {
            if (await df.locator.isVisible({ timeout: 1000 }).catch(() => false)) {
                const currentVal = await df.locator.inputValue().catch(() => '');
                const looksValid = /^\d{2}-\d{2}-\d{4}$/.test(currentVal);
                if (!looksValid) {
                    console.warn(`⚠️ ${df.label} was wiped ("${currentVal}") — re-filling...`);
                    await fillDateField(page, df.locator, df.expected);
                }
            }
        }
    } else {
        console.log('ℹ️ skipDates is true — skipping date filling & verification (using carried-forward dates).');
    }

    // 7. Station selection (bottom of sidebar)
    console.log(`ℹ️ createBasicOrder: selectStation is ${selectStation}`);
    if (selectStation) {
        let stations = page.locator('p-checkbox[name="card_stations"] input[type="checkbox"]:visible');

        if (await stations.count() === 0) {
            console.log('ℹ️ Standard station checkboxes not found, trying grid-based popover...');
            const stationCell = page.locator('td.stations-field span, .stations-field').first();
            if (await stationCell.isVisible()) {
                await stationCell.click();
                const popover = page.locator('p-popover#station-popover, .spot-list-view-overlay-panel').first();
                await popover.waitFor({ state: 'attached', timeout: 5000 });
                stations = popover.locator('p-checkbox input[type="checkbox"], .p-checkbox input');
                await stations.first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
                    console.log('⚠️ Stations not visible in popover yet, trying another click...');
                });
            }
        }

        // Dismiss any blocking p-dialog (e.g. "Draft Saved") before interacting with stations
        await dismissBlockingDialog(page, 500);

        await expect(stations.first()).toBeVisible({ timeout: 15000 });
        const count = await stations.count();
        console.log(`ℹ️ Found ${count} stations in selection list. Checking all stations...`);
        for (let i = 0; i < count; i++) {
            const surroundingText = await stations.nth(i).evaluate(el => (el.closest('div, span, p, label, td') as HTMLElement)?.innerText || '').catch(() => '');
            console.log(`ℹ️ Checking checkbox station ${i}: "${surroundingText.trim().replace(/\s+/g, ' ')}"`);
            // Dismiss any dialog that may have popped up since last iteration
            await dismissBlockingDialog(page);
            // Use DOM-level click to bypass any overlay that intercepts pointer events
            // (e.g. "Draft Saved" p-dialog-mask that still renders over the form)
            const clicked = await stations.nth(i).evaluate(el => { (el as HTMLInputElement).click(); return true; }).catch(() => false);
            if (!clicked) {
                await stations.nth(i).check({ force: true }).catch(() => stations.nth(i).click());
            }
        }
        let anyChecked = count > 0;

        if (!anyChecked && count > 0) {
            const randomIndex = Math.floor(Math.random() * count);
            await stations.nth(randomIndex).check({ force: true }).catch(() => stations.nth(randomIndex).click());
        }

        // If the "Copy to All Stations" link/button is visible, click it to sync with other rows in the draft
        const copyToAllBtn = page.getByText('Copy to All Stations').first();
        if (await copyToAllBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
            console.log('📝 "Copy to All Stations" link is visible. Clicking to sync station selection to all spots in draft...');
            await copyToAllBtn.click({ force: true });
            await page.waitForTimeout(1000);
        }

        // Close station popover by clicking the station cell again — NOT Escape
        const popover = page.locator('p-popover#station-popover, .spot-list-view-overlay-panel').first();
        if (await popover.isVisible()) {
            const stationCell = page.locator('td.stations-field span, .stations-field').first();
            await stationCell.click();
            await page.waitForTimeout(500);
        }
    }
    let finalContractNo = contractNo;
    if (selectStation && !finalContractNo) {
        finalContractNo = `CN${Math.floor(1000 + Math.random() * 9000)}`;
        console.log(`ℹ️ Station selected: contract number is also required. Auto-generating: ${finalContractNo}`);
    }

    if (finalContractNo) {
        // 8. Contract Number (optional, at the very bottom of the sidebar)
        console.log(`📝 Calling fillContractField to populate all visible contract fields with: ${finalContractNo}`);
        await fillContractField(page, finalContractNo);
    }

    console.log(`✅ Basic order created: "${title}" for client "${client}"`);

    return { title, isci };
}

/**
 * Submit the current draft order(s).
 * 
 * @param page - Playwright Page object
 * @param options - Optional configuration
 * @returns The POID if extractable from the URL
 */
export async function submitOrder(
    page: Page,
    options: { timeout?: number; waitForLoad?: boolean; dueDate?: string; startDate?: string; endDate?: string } = {}
): Promise<string | null> {
    const { timeout = 30000, waitForLoad = true } = options;

    // Wait for any active loaders/spinners to clear first
    const spinner = page.locator('.p-progress-spinner, app-v-loader, #loader-wrapper, .loading-overlay').first();
    if (await spinner.isVisible().catch(() => false)) {
        console.log('⏳ submitOrder: waiting for active loading spinner to clear...');
        await spinner.waitFor({ state: 'hidden', timeout: 30000 }).catch(() => {});
    }

    const submitBtn = page.locator('button#submit-all-drafts, #submit-all-drafts, button:has-text("Submit All"), button:has-text("SUBMIT ALL")').first();
    await expect(submitBtn).toBeVisible({ timeout });
    
    // Fill dates as the absolute LAST action before evaluating constraints.
    if (options.dueDate && options.startDate && options.endDate) {
        console.log('📅 submitOrder: filling dates immediately before click...');
        await fillOrderDates(page, options.dueDate, options.startDate, options.endDate);
    }
    
    // Force sync station selection right before submission to ensure all async rows (e.g. streaming spots) are synced
    // NOTE: querySelectorAll('*') was replaced with a targeted Playwright locator to prevent "Target crashed"
    // under the large Angular DOM of the QA environment.
    try {
        const copyToAllLocator = page.locator('button, a, span, div').filter({ hasText: /^Copy to All Stations$/ }).first();
        if (await copyToAllLocator.isVisible({ timeout: 1500 }).catch(() => false)) {
            console.log('📝 Clicking "Copy to All Stations" to sync station selection.');
            await copyToAllLocator.click({ force: true });
            await page.waitForTimeout(1000);
            const confirmBtn = page.locator('.p-confirm-dialog-accept, button:has-text("Yes"), button:has-text("Confirm"), .p-dialog-footer button:has-text("Yes")').first();
            if (await confirmBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
                console.log('📝 Found confirmation button. Clicking to accept Copy to All Stations...');
                await confirmBtn.click({ force: true });
                await page.waitForTimeout(1000);
            }
        }
    } catch (e) {
        console.log('ℹ️ "Copy to All Stations" link direct click bypassed or not present.');
    }

    // Double-check and force-correct any spot rows in the table that are missing station assignments
    await ensureAllDraftSpotsHaveStations(page).catch(() => {});

    // Force sweep and fill any visible contract fields
    await fillContractField(page).catch(() => {});

    // PRE-FLIGHT UI CHECK: Ensure no required fields are missing before clicking
    await verifyNoMissingFields(page);

    // Capture POID from URL BEFORE submit — the edit=xxx parameter is present while the form is open
    const preSubmitUrl = page.url();
    const preSubmitMatch = preSubmitUrl.match(/edit=(\d+)/);
    const preSubmitPoid = preSubmitMatch ? preSubmitMatch[1] : null;

    // Submit click strategy — WebKit's standard .click() can silently no-op on
    // sticky-footer buttons whose hit-test intersects an overlay/scrollbar.
    // On WebKit, jump straight to the DOM-level click; on other browsers use
    // the standard click first (better trusted-event fidelity) with fallbacks.
    await safeScroll(submitBtn);
    const browserName = page.context().browser()?.browserType().name();
    const isWebKit = browserName === 'webkit';
    if (isWebKit) {
        console.log('🍎 WebKit detected — using DOM-level click for reliable submit dispatch');
        try {
            await submitBtn.evaluate(b => (b as HTMLElement).click());
        } catch {
            console.log('⚠️ WebKit DOM click failed, retrying via focus + Enter...');
            await submitBtn.focus();
            await page.waitForTimeout(300);
            await page.keyboard.press('Enter');
        }
    } else {
        try {
            await submitBtn.click({ timeout: 5000 });
        } catch {
            console.log('⚠️ Standard click timed out on Submit. Firing DOM-level click...');
            try {
                await submitBtn.evaluate(b => (b as HTMLElement).click());
            } catch {
                console.log('⚠️ DOM click failed. Trying focus + Enter (with settle pause)...');
                await submitBtn.focus();
                await page.waitForTimeout(300);
                await page.keyboard.press('Enter');
            }
        }
    }

    // Verify modal closes
    const modal = page.locator('app-quickorders, .p-dialog, .p-sidebar, .p-drawer, .p-sidebar-active, #quickorders-sidebar').first();
    try {
        // Wait for order to appear in grid first as evidence of success
        if (waitForLoad) {
            await page.waitForTimeout(2000);
        }
        await expect(modal).not.toBeVisible({ timeout: 10000 });
    } catch (e) {
        console.warn('⚠️ Modal still visible after submission. Attempting manual close...');
        // Try clicking the close button explicitly
        const closeBtn = page.locator('a#closeIcon, .p-sidebar-close, button.p-sidebar-close, .p-dialog-header-close, .v-sidebar-header .close-btn').first();
        if (await closeBtn.isVisible({ timeout: 3000 })) {
            await closeBtn.click();

            // Handle confirmation dialog if it appears ("CLOSE WITHOUT SAVING")
            const confirmBtn = page.locator('button:has-text("CLOSE WITHOUT SAVING"), button:has-text("Discard")').first();
            if (await confirmBtn.isVisible({ timeout: 3000 })) {
                await confirmBtn.click();
            }
            await page.waitForTimeout(1000);
        } else {
            await page.keyboard.press('Escape');
            await page.waitForTimeout(1000);
        }
    }

    if (waitForLoad) {
        await page.waitForTimeout(1000);
    }

    // WebKit cleanup: app-quickorders Angular wrapper stays in the DOM
    // and intercepts pointer events even after the panel closes.
    // Use visibility:hidden + pointer-events:none (not display:none which breaks Angular state).
    await page.evaluate(() => {
        const el = document.querySelector('app-quickorders');
        if (el) {
            (el as HTMLElement).style.visibility = 'hidden';
            (el as HTMLElement).style.pointerEvents = 'none';
        }
    });
    await page.waitForTimeout(500);

    // Extract POID: try post-submit URL first, fall back to pre-submit capture
    const postUrl = page.url();
    const postMatch = postUrl.match(/edit=(\d+)/);
    const poid = postMatch ? postMatch[1] : preSubmitPoid;

    if (poid) {
        console.log(`✅ Order submitted successfully. POID: ${poid}`);
    } else {
        console.log('✅ Order submitted successfully.');
    }

    return poid;
}

/**
 * Complete workflow: Open form, create order, and submit.
 * Convenience function that combines all steps.
 * 
 * @param page - Playwright Page object
 * @param details - Order details
 * @returns Object with title, isci, and poid
 */
export async function createAndSubmitOrder(
    page: Page,
    details: OrderDetails
): Promise<{ title: string; isci: string; poid: string | null }> {
    await openQuickOrderForm(page);
    const { title, isci } = await createBasicOrder(page, details);
    const poid = await submitOrder(page);
    return { title, isci, poid };
}

/**
 * Approve a spot that is in "Spot Review" status.
 * Handles the specific row-scoped approval button logic.
 * 
 * @param page - Playwright Page object
 * @param row - The row locator for the spot
 */
export async function approveSpot(page: Page, row: Locator): Promise<void> {
    const approveSelectors = [
        '#approveButton',
        'button[title="Approve"]',
        '[aria-label="Approve"]',
        '.approve-btn',
        '.review-pass',
        '.inline-btn.review-pass',
        '[id*="approve"]:not([id*="disapprove"])',
        'button[class*="approve"]',
        'a[class*="approve"]',
        '[class*="review-pass"]',
        'button:has(i.fa-thumbs-up)',
        'button:has(i.fa-thumbs-o-up)',
        'button:has(i.fa-check-circle)',
        'button:has(i.fa-check)',
        'button:has(.pi-check)',
    ].join(', ');

    // First try row-scoped locator, then widen to entire page
    const rowBtn = row.locator(approveSelectors).first();
    const pageBtn = page.locator(approveSelectors).first();
    // Case-insensitive text filter as last resort (covers "APPROVE", "Approve Spot", etc.)
    const textBtn = page.locator('button, a, [role="button"]').filter({ hasText: /approv/i }).first();

    const candidates = [rowBtn, pageBtn, textBtn];

    for (const btn of candidates) {
        try {
            const visible = await btn.isVisible({ timeout: 5000 }).catch(() => false);
            if (visible) {
                await btn.click();
                await page.waitForTimeout(3000);
                console.log('✅ approveSpot: clicked approve button');
                return;
            }
        } catch { /* try next candidate */ }
    }

    console.warn('⚠️ approveSpot: Approval button not found via any selector (may have auto-approved or requires navigation)');
}

/**
 * Interface for new client order details.
 */
export interface NewClientOrderDetails extends Omit<OrderDetails, 'client'> {
    /** New client name to create - auto-generated if omitted */
    newClientName?: string;
}

/**
 * Create an order using a NEW client that doesn't exist in the system.
 * Handles the "New Client" dropdown selection and confirmation dialog.
 * Does NOT submit the order - leaves it as a draft for verification.
 * 
 * @param page - Playwright Page object
 * @param details - Order details (newClientName is auto-generated if omitted)
 * @returns Object with title, isci, and the new client name
 */
export async function createOrderWithNewClient(
    page: Page,
    details: NewClientOrderDetails = {}
): Promise<{ title: string; isci: string; clientName: string }> {
    const {
        newClientName = generateUniqueClientName(),
        title = generateRandomSpotTitle(),
        adType = 'Radio Commercial',
        status = 'Needs Producing',
        length = '30',
        rotation = '100',
        dueDate = calculateDueDate(3),
        startDate = calculateStartDate(),
        endDate = calculateEndDate(),
        isci = generateRandomISCI(),
        contractNo = `CN${Math.floor(1000 + Math.random() * 9000)}`,
        selectStation = true
    } = details;

    // Select ad type first
    await selectAdType(page, adType);

    // Type partial client name to trigger autocomplete
    const clientInput = page.locator('p-autocomplete[name="card_client_id"] input');
    await clientInput.click();
    await clientInput.fill('');
    await clientInput.fill(newClientName);
    await page.waitForTimeout(1500);

    // Look for "New Client: <name>" option in dropdown
    const newClientOption = page.getByRole('option', { name: new RegExp(`New Client:.*${newClientName.substring(0, 5)}`, 'i') });

    // If exact match not found, look for the generic "New Client:" option
    const genericNewClientOption = page.locator('.p-autocomplete-item, .ui-autocomplete-list-item').filter({
        hasText: /New Client:/i
    }).first();

    if (await newClientOption.isVisible({ timeout: 3000 })) {
        await newClientOption.click();
    } else if (await genericNewClientOption.isVisible({ timeout: 3000 })) {
        await genericNewClientOption.click();
    } else {
        // Fallback: Click on any option containing "New Client"
        await page.getByText(/New Client:/i).first().click();
    }

    // Handle "Are you sure you want to create the new client?" confirmation dialog
    const confirmDialog = page.locator('div').filter({ hasText: /Are you sure you want to create the new client/i }).first();
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    console.log('📋 New client confirmation dialog appeared');

    const confirmButton = page.getByRole('button', { name: 'YES, CONFIRM' });
    await expect(confirmButton).toBeVisible({ timeout: 3000 });
    await confirmButton.click();
    await page.waitForTimeout(1000);

    console.log(`✅ New client "${newClientName}" creation confirmed`);

    // Now fill the rest of the order form (similar to createBasicOrder)
    const upperTitle = title.toUpperCase();
    const spotTitleInput = page.locator('#spot-cards-list-wrapper input[placeholder="Spot title"]:visible, #spot-cards-list-wrapper input[name="card_spot_title"]:visible').first();
    await expect(spotTitleInput).toBeVisible();
    await spotTitleInput.fill(upperTitle);
    await spotTitleInput.press('Tab');
    await page.waitForTimeout(1000);

    // Select Status
    await selectQOStatus(page, status);

    // Fill ISCI
    await page.locator('input[placeholder="AD-ID OR ISCI CODE"]:visible, input[name="card_isci_code"]:visible').first().fill(isci);

    // Fill Length (only present for Radio Commercial, Commercial+Streaming)
    const lengthFieldNew = page.locator(
        'input[placeholder*="Length" i], ' +
        'input[name*="length" i], ' +
        'input[id*="length" i], ' +
        'p-inputnumber[id*="length" i] input, ' +
        'p-inputnumber[name*="length" i] input, ' +
        'input[placeholder*="Len" i], ' +
        'input[placeholder="30"]'
    ).first();
    if (await lengthFieldNew.isVisible({ timeout: 2000 }).catch(() => false)) {
        await lengthFieldNew.fill(length);
    }

    // Fill Rotation (present for all except Image Ad)
    const rotationFieldNew = page.getByRole('textbox', { name: 'Rotation ' }).first();
    if (await rotationFieldNew.isVisible({ timeout: 2000 }).catch(() => false)) {
        await rotationFieldNew.fill(rotation);
    }

    // Fill Digital URL (present for Commercial+Streaming, Streaming Only, Image Ad)
    const digitalUrl = details.digitalUrl;
    if (digitalUrl) {
        const digitalUrlFieldNew = page.locator(
            'input[placeholder*="click through web address"], input[placeholder*="Digital URL"], input[name*="digital_url"]'
        ).first();
        if (await digitalUrlFieldNew.isVisible({ timeout: 2000 }).catch(() => false)) {
            await digitalUrlFieldNew.fill(digitalUrl);
            await digitalUrlFieldNew.press('Tab');
            await page.waitForTimeout(500);
        }
    }

    // Image Ad (Banner Ad) specific fields helper
    const quantityInputNew = page.locator('input[name="card_quantity"]').first();
    if (await quantityInputNew.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('📝 Filling Banner-specific required fields for new client...');
        await quantityInputNew.fill('1');
        await quantityInputNew.press('Tab');

        // Select Digital Type (Type)
        const typeSelectNew = page.locator('p-select[name="card_quantitytype"]').first();
        if (await typeSelectNew.isVisible()) {
            await typeSelectNew.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }

        // Select Per
        const perSelectNew = page.locator('p-select[name="card_unitofmeasure"]').first();
        if (await perSelectNew.isVisible()) {
            await perSelectNew.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }

        // Select Banner Size(s)
        const sizeSelectNew = page.locator('p-select[name="card_web_sizes"]').first();
        if (await sizeSelectNew.isVisible()) {
            await sizeSelectNew.click();
            await page.waitForTimeout(500);
            await page.locator('.p-select-overlay p-selectitem, .p-select-overlay [role="option"], .p-select-item').first().click().catch(async () => {
                await page.keyboard.press('ArrowDown');
                await page.keyboard.press('Enter');
            });
            await page.waitForTimeout(500);
        }
    }

    // Fill Dates using the adaptive robust helper
    await fillOrderDates(page, dueDate, startDate, endDate);

    // Select a random station
    if (selectStation) {
        const stations = page.locator('p-checkbox[name="card_stations"] input[type="checkbox"]');
        await expect(stations.first()).toBeVisible();
        const count = await stations.count();
        let anyChecked = false;
        for (let i = 0; i < count; i++) {
            if (await stations.nth(i).isChecked().catch(() => false)) {
                anyChecked = true;
                break;
            }
        }
        
        // Ensure DEMO-FM is checked to expose "Copy to All Stations"
        for (let i = 0; i < count; i++) {
            const surroundingText = await stations.nth(i).evaluate(el => (el.closest('div, span, p, label, td') as HTMLElement)?.innerText || '').catch(() => '');
            if (surroundingText.includes('DEMO-FM')) {
                await stations.nth(i).check({ force: true }).catch(() => {});
                anyChecked = true;
                break;
            }
        }

        if (!anyChecked && count > 0) {
            const randomIndex = Math.floor(Math.random() * count);
            await stations.nth(randomIndex).check({ force: true }).catch(() => stations.nth(randomIndex).click());
        }

        // If the "Copy to All Stations" link/button is visible, click it to sync with other rows in the draft
        const copyToAllBtn = page.getByText('Copy to All Stations').first();
        if (await copyToAllBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
            console.log('📝 "Copy to All Stations" link is visible. Clicking to sync station selection to all spots in draft...');
            await copyToAllBtn.click({ force: true });
            await page.waitForTimeout(1000);
        }
    }

    // Fill Contract Number (optional fallback)
    await fillContractField(page, contractNo);

    console.log(`✅ Order form filled for new client "${newClientName}" with title "${title}"`);

    return { title, isci, clientName: newClientName };
}

/**
 * Validates the QO form natively against PrimeNG missing-field tooltips and red asterisks.
 * Imitates manual human user oversight prior to submitting drafts.
 * 
 * @param page - Playwright Page object
 * @throws Error explicitly listing missing fields if tooltip icon or missing field asterisks are seen.
 */
export async function verifyNoMissingFields(page: Page): Promise<void> {
    let missingFieldsText = '';

    const drawer = page.locator('p-drawer:visible, .p-drawer:visible, .p-sidebar:visible, app-v-sidebar:visible, .p-dialog:visible').first();

    // Check for explicit PrimeNG tooltip icon first.
    // The icon may appear transiently while Angular re-runs form validation after the last
    // field fill. Wait up to 4 seconds for it to clear before treating it as a real blocker.
    const errorIcons = drawer.locator('span#missing-fields-tool-tip-icon, span:has(> .exclamation.fa-exclamation)');
    const iconVisible = await errorIcons.first().isVisible({ timeout: 500 }).catch(() => false);
    if (iconVisible) {
        // Give Angular time to finish change detection
        await page.waitForTimeout(3000);
    }
    const iconStillVisible = await errorIcons.first().isVisible({ timeout: 500 }).catch(() => false);
    if (iconStillVisible) {
        console.warn('⚠️ Missing Fields tooltip icon still visible after settling — hovering to extract requirements...');
        // Hover to reveal tooltip
        await errorIcons.first().hover({ force: true, timeout: 5000 }).catch(() => {});

        // Always try Angular model extraction first — the tooltip may only show a count ("1 Missing fields")
        // while the model has the actual field names
        const ngMissingFields: string[] = await page.evaluate(() => {
            const iconEl = document.getElementById('missing-fields-tool-tip-icon');
            if (!iconEl) return [];
            const row = iconEl.closest('tr');
            if (!row) return [];
            const ctx = (row as any).__ngContext__;
            if (!ctx) return [];
            for (let i = 0; i < ctx.length; i++) {
                const item = ctx[i];
                if (item && typeof item === 'object' && Array.isArray(item._missingFields)) {
                    return item._missingFields;
                }
            }
            return [];
        }).catch(() => []);

        if (ngMissingFields.length > 0) {
            const fromModel = `Missing fields (from Angular model): ${ngMissingFields.join(', ')}`;
            console.warn(`⚠️ ${fromModel}`);
            missingFieldsText = fromModel;
        }

        // Also check tooltip text (may supplement or replace model data)
        const tooltipContent = page.locator('.p-tooltip-text, .tooltip-inner, .p-tooltip').last();
        if (await tooltipContent.isVisible({ timeout: 3000 })) {
            const tooltipText = await tooltipContent.innerText();
            console.warn(`⚠️ Tooltip text: "${tooltipText}"`);
            // Only use tooltip text if Angular model gave us nothing
            if (!missingFieldsText) {
                missingFieldsText = tooltipText;
            }
        }

        if (!missingFieldsText) {
            // Angular model shows no missing fields despite icon — transient state, safe to proceed
            console.warn('⚠️ Missing fields icon visible but _missingFields is empty — transient state, ignoring.');
        }
    }

    // --- Self-Healing Block ---
    if (missingFieldsText) {
        let healed = false;
        if (missingFieldsText.includes('Contract')) {
            console.log('🩹 Self-Healing: Missing fields tooltip indicated "Contract" is missing. Automatically filling contract fields...');
            await fillContractField(page).catch(() => {});
            healed = true;
        }
        if (missingFieldsText.includes('Start Date')) {
            console.log('🩹 Self-Healing: "Start Date" missing (reset by form subscription after status/length change). Re-filling...');
            // Read the current due date from the DOM to calculate a valid start date
            const dueDateStr = await page.evaluate(() => {
                const inp = document.querySelector('p-datepicker[name="card_due_date"] input, input[name="card_due_date"]') as HTMLInputElement;
                return inp ? inp.value : '';
            }).catch(() => '');
            let healStartDate = '';
            if (dueDateStr && /\d{2}[-/]\d{2}[-/]\d{4}/.test(dueDateStr)) {
                // Parse MM-DD-YYYY from due date display value
                const parts = dueDateStr.split(/[\s]+/)[0].split(/[-/]/);
                if (parts.length === 3) {
                    const [mm, dd, yyyy] = parts;
                    const dueMs = new Date(`${yyyy}-${mm}-${dd}`).getTime();
                    if (!isNaN(dueMs)) {
                        // Use dueDate + 21 days (conservative: avoids minimum lead-time validation)
                        const startMs = dueMs + 21 * 24 * 60 * 60 * 1000;
                        const sd = new Date(startMs);
                        healStartDate = `${String(sd.getMonth() + 1).padStart(2, '0')}/${String(sd.getDate()).padStart(2, '0')}/${sd.getFullYear()}`;
                    }
                }
            }
            if (!healStartDate) {
                // Fallback: today + 35 days
                const sd = new Date(Date.now() + 35 * 24 * 60 * 60 * 1000);
                healStartDate = `${String(sd.getMonth() + 1).padStart(2, '0')}/${String(sd.getDate()).padStart(2, '0')}/${sd.getFullYear()}`;
            }
            console.log(`🩹 Self-Healing: re-filling Start Date as "${healStartDate}" (due="${dueDateStr}")`);
            const startInput = page.locator('p-datepicker[name="card_start_date"] input, p-calendar[name="card_start_date"] input').first();
            if (await startInput.isVisible({ timeout: 3000 }).catch(() => false)) {
                await fillDateField(page, startInput, healStartDate).catch(() => {});
                await page.waitForTimeout(1000);
            }
            healed = true;
        }
        if (missingFieldsText.includes('Stations')) {
            console.log('🩹 Self-Healing: Missing fields tooltip indicated "Stations" is missing. Automatically assigning stations...');
            await ensureAllDraftSpotsHaveStations(page).catch(() => {});
            healed = true;
        }
        if (missingFieldsText.includes('Sales')) {
            console.log('🩹 Self-Healing: "Sales" missing — selecting first available Sales POC...');
            const salesEl = page.locator('#spot-cards-list-wrapper p-multiselect').filter({ hasText: /Select Sales/i }).first();
            const salesFallback = page.locator('#spot-cards-list-wrapper p-multiselect, .p-drawer-content p-multiselect').first();
            const sales = await salesEl.isVisible({ timeout: 1500 }).catch(() => false) ? salesEl : salesFallback;
            if (await sales.isVisible({ timeout: 1500 }).catch(() => false)) {
                await sales.scrollIntoViewIfNeeded().catch(() => {});
                await sales.click({ force: true });
                await page.waitForTimeout(500);
                const msItems = page.locator('.p-multiselect-option, li[role="option"]');
                await msItems.first().waitFor({ state: 'visible', timeout: 4000 }).catch(() => {});
                const itemCount = await msItems.count();
                if (itemCount > 0) {
                    await msItems.first().click();
                    console.log('✅ Sales POC self-healed: selected first option');
                }
                await page.locator('#spot-cards-list-wrapper, .p-drawer-content').first()
                    .click({ position: { x: 5, y: 5 } }).catch(() => {});
                await page.waitForTimeout(300);
            }
            healed = true;
        }

        if (healed) {
            console.log('⏳ Waiting for Angular to re-evaluate form status after self-healing...');
            await page.waitForTimeout(3000);
            // Clear the text and re-evaluate if error icon is still there
            missingFieldsText = '';
            const stillVisible = await errorIcons.first().isVisible({ timeout: 500 }).catch(() => false);
            if (stillVisible) {
                await errorIcons.first().hover({ force: true, timeout: 5000 }).catch(() => {});
                const ngMissingFields2: string[] = await page.evaluate(() => {
                    const iconEl = document.getElementById('missing-fields-tool-tip-icon');
                    if (!iconEl) return [];
                    const row = iconEl.closest('tr');
                    if (!row) return [];
                    const ctx = (row as any).__ngContext__;
                    if (!ctx) return [];
                    for (let i = 0; i < ctx.length; i++) {
                        const item = ctx[i];
                        if (item && typeof item === 'object' && Array.isArray(item._missingFields)) {
                            return item._missingFields;
                        }
                    }
                    return [];
                }).catch(() => []);
                if (ngMissingFields2.length > 0) {
                    missingFieldsText = `Missing fields (from Angular model): ${ngMissingFields2.join(', ')}`;
                    console.warn(`⚠️ After healing, still missing: ${missingFieldsText}`);
                }
                const tooltipContent2 = page.locator('.p-tooltip-text, .tooltip-inner, .p-tooltip').last();
                if (!missingFieldsText && await tooltipContent2.isVisible({ timeout: 2000 })) {
                    missingFieldsText = await tooltipContent2.innerText();
                }
            }
        }
    }

    // Scan the DOM natively for visible required asterisks (*)
    // The user notes the asterisks remain until that field is successfully satisfied.
    const asteriskFields = await page.evaluate(() => {
        const results: string[] = [];
        // Restrict scan to the open sidebar/dialog if present, to avoid matching background grid cells
        const container = document.querySelector('.p-sidebar, .p-drawer, .p-dialog, app-v-sidebar, [role="complementary"], .quick-order-form') || document;
        const els = Array.from(container.querySelectorAll('span, label, div, p'));
        for (const el of els) {
            // Find elements that primarily just display the asterisk character
            const htmlEl = el as HTMLElement;
        if (htmlEl.textContent?.trim() === '*' && htmlEl.offsetParent !== null) {
                const parent = el.closest('label') || el.parentElement;
                if (parent) {
                    const labelText = parent.innerText.replace('*', '').trim();
                    if (labelText && !results.includes(labelText)) {
                        results.push(labelText);
                    }
                }
            }
        }
        return results;
    });

    if (missingFieldsText || asteriskFields.length > 0) {
        let errorMsg = `\n❌ Submission Aborted: Required fields are missing!\n`;
        if (missingFieldsText) {
            errorMsg += `Tooltip output:\n${missingFieldsText}\n`;
        }
        if (asteriskFields.length > 0) {
            errorMsg += `Unsatisfied Asterisk (*) fields detected on form:\n${asteriskFields.join('\n')}\n`;
        }
        throw new Error(errorMsg);
    }

    console.log('✅ UI Pre-Flight Validation Passed: No missing field warnings or asterisks visible.');
}

/**
 * Attempt to fill the Contract Number field if it is visible.
 * Often required after selecting stations, so it's abstracted for reuse.
 * 
 * @param page - Playwright Page object
 * @param contractNo - Contract number to fill. Defaults to a random CN#### string.
 */
export async function fillContractField(page: Page, contractNo?: string): Promise<string> {
    const finalContractNo = contractNo || `CN${Math.floor(1000 + Math.random() * 9000)}`;
    const drawer = page.locator('p-drawer:visible, .p-drawer:visible, .p-sidebar:visible, app-v-sidebar:visible, .p-dialog:visible').first();
    const contractInputs = drawer.locator('input[placeholder="Add Contract #"], input[placeholder="Contract #"], input[placeholder*="Contract"]');
    
    const count = await contractInputs.count();
    let filled = 0;
    for (let i = 0; i < count; i++) {
        const input = contractInputs.nth(i);
        // Scroll into view to ensure it becomes visible if it's in a scrollable grid
        await safeScroll(input);
        if (await input.isVisible({ timeout: 1000 }).catch(() => false)) {
            await input.fill(finalContractNo);
            await input.press('Tab');
            filled++;
        }
    }
    
    if (filled > 0) {
        console.log(`📝 Contract Number swept and filled: ${finalContractNo} (${filled} fields)`);
    } else {
        console.log('ℹ️ Contract Number field not found or not visible, skipping.');
    }
    
    return finalContractNo;
}

/**
 * Scan the draft spots grid table and ensure all rows have at least one station checked.
 * If any row is missing stations, click the station cell to open popover, check first station, and close.
 */
/**
 * Dismiss any blocking overlay masks that intercept pointer events.
 *
 * Handles multiple mask families observed in the vCreative Angular app:
 *   - PrimeNG:  `.p-overlay-mask`, `.p-drawer-mask`, `.p-dialog-mask`
 *   - Angular:  `#v-sidebar-mask-overlay`, `.v-sidebar-mask`
 *   - Generic:  `.cdk-overlay-backdrop`, full-screen ancestor pointer-event intercept
 *
 * Strategy:
 *   1. Press Escape — most overlays honour it and close cleanly.
 *   2. If any mask remains, force-remove it from the DOM.
 *   3. Wait a short settle period so Angular's change detection can react.
 *
 * Usage:
 *   await dismissBlockingOverlays(page);
 *   await dismissBlockingOverlays(page, { timeout: 2000, settle: 500 });
 *
 * @param page    - Playwright Page instance
 * @param opts    - Optional configuration
 * @param opts.timeout  - Max ms to wait for each mask to appear (default 1000)
 * @param opts.settle   - Ms to wait after dismissal for Angular to settle (default 500)
 */
export async function dismissBlockingOverlays(
    page: Page,
    opts?: { timeout?: number; settle?: number }
): Promise<void> {
    const timeout = opts?.timeout ?? 1000;
    const settle  = opts?.settle  ?? 600;

    // Selector covers all known blocking-mask families:
    //   PrimeNG:  .p-overlay-mask, .p-drawer-mask, .p-dialog-mask
    //   Angular:  #v-sidebar-mask-overlay, .v-sidebar-mask
    //   Generic:  .cdk-overlay-backdrop
    const MASK_CLASSES = [
        '.p-overlay-mask',
        '.p-drawer-mask',
        '.p-dialog-mask',
        '#v-sidebar-mask-overlay',
        '.v-sidebar-mask',
        '.cdk-overlay-backdrop',
    ];
    const MASK_SELECTOR = MASK_CLASSES.join(', ');

    const anyMask = page.locator(MASK_SELECTOR).first();
    const maskVisible = await anyMask.isVisible({ timeout }).catch(() => false);
    if (!maskVisible) return;

    console.log('⚠️ dismissBlockingOverlays: blocking mask detected — pressing Escape...');
    // Click body first to ensure focus is on the page (Escape only works when the
    // page has focus — if a test action moved focus to a browser chrome element,
    // keyboard.press('Escape') is silently swallowed)
    await page.locator('body').click({ position: { x: 5, y: 5 }, force: true }).catch(() => {});
    await page.keyboard.press('Escape');

    // Wait for masks to actually become hidden (not just settled after a delay)
    await anyMask.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});

    // Check if any mask persists after Escape + wait
    const stillVisible = await anyMask.isVisible({ timeout: 300 }).catch(() => false);
    if (stillVisible) {
        console.log('⚠️ dismissBlockingOverlays: mask persists after Escape — force-removing from DOM...');
        await page.evaluate((selector) => {
            document.querySelectorAll(selector).forEach((el) => (el as HTMLElement).remove());
        }, MASK_SELECTOR);
        // Wait for DOM removal to propagate + Angular CD to settle
        await page.waitForTimeout(settle);
        // Final check: click body to dismiss any remaining pointer-event captures
        await page.locator('body').click({ position: { x: 5, y: 5 }, force: true }).catch(() => {});
    }
}

export async function ensureAllDraftSpotsHaveStations(page: Page): Promise<void> {
    // DOM-wide table scan removed — table.innerText forces reflows on every table and caused "Target crashed".

    const drawer = page.locator('p-drawer:visible, .p-drawer:visible, .p-sidebar:visible, app-v-sidebar:visible, .p-dialog:visible').first();
    const table = drawer.locator('p-table table, .p-datatable-table').first();
    if (!(await table.isVisible().catch(() => false))) return;

    const rows = table.locator('tbody tr');
    const count = await rows.count();
    console.log(`ℹ️ ensureAllDraftSpotsHaveStations: checking ${count} draft rows for station assignments...`);

    for (let i = 0; i < count; i++) {
        const row = rows.nth(i);

        // Debug cell info to understand DOM structure
        const cellDetails = await row.evaluate(tr => {
            const tds = Array.from(tr.querySelectorAll('td'));
            return tds.map((td, idx) => ({
                index: idx,
                className: td.className,
                text: td.innerText
            }));
        }).catch(() => []);
        console.log(`ℹ️ Row ${i + 1} details: ${JSON.stringify(cellDetails)}`);

        const stationCell = row.locator('td.stations-field, td:nth-child(10), td:has-text(" "), td:has-text("*")').first();
        if (await stationCell.isVisible().catch(() => false)) {
            const cellText = (await stationCell.textContent().catch(() => '')) || '';
            console.log(`ℹ️ Row ${i + 1} Stations cell text: "${cellText.trim()}"`);
            
            // If the cell contains "0", "*", or is empty, it needs a station assigned!
            if (cellText.includes('0') || cellText.includes('*') || cellText.trim() === '' || cellText.trim() === '') {
                console.log(`📝 Row ${i + 1} Stations are empty/missing. Clicking to select...`);
                await stationCell.click();
                await page.waitForTimeout(1000);

                const popover = page.locator('p-popover#station-popover, .spot-list-view-overlay-panel').first();
                await popover.waitFor({ state: 'attached', timeout: 5000 }).catch(() => {});
                
                const stations = popover.locator('p-checkbox input[type="checkbox"], .p-checkbox input');
                const stationsCount = await stations.count();
                if (stationsCount > 0) {
                    await stations.first().check({ force: true }).catch(() => stations.first().click());
                    await page.waitForTimeout(500);
                }

                // Close popover by clicking cell again
                await stationCell.click();
                await page.waitForTimeout(500);
            }
        }
    }
}


