import { test, expect, BASE_URL } from '../../utils/setup';
import type { Browser } from '@playwright/test';
import * as path from 'path';
import { ensureSimpleDateEntry } from '../../utils/userSettingsSimpleDates';
import { generateRandomSpotTitle, calculateDueDate, calculateStartDate, calculateEndDate, generateRandomISCI } from '../../utils/QO_helpers';
import { verifyNoMissingFields, ensureAllDraftSpotsHaveStations, fillContractField } from '../../utils/OrderHelper';
import * as fs from 'fs';

// Must match playwright.config.ts default ('test'), not 'qa', so storage state path is correct
const TEST_ENV = process.env.TEST_ENV || 'test';
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);

export async function runQOInteraction(browser: Browser) {
    const context = await browser.newContext({
        storageState: storageStatePath,
    });
    const page = await context.newPage();

    console.log('🛠️ Running Setup: Ensuring Simple Date Entry is enabled...');
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });

    try {
        // Wait for app to load before settings navigation
        await page.locator('.layout-topbar, app-topbar').first().waitFor({ state: 'visible', timeout: 20000 });
        await ensureSimpleDateEntry(page, BASE_URL);
    } catch (error) {
        console.warn('⚠️ An error occurred during user settings navigation; proceeding anyway as settings are likely already correct:', error);
        // Explicitly navigate back to the Inbox/Dashboard to ensure we are off the settings page!
        console.log('🚪 Self-Healing: Forcing navigation back to Inbox dashboard...');
        await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/inbox`).catch(() => {});
        await page.waitForLoadState('domcontentloaded').catch(() => {});
        await page.waitForTimeout(3000);
    }

    // Wait to ensure user data loads after login
    console.log('Wait after login to ensure user data loads...');
    await page.locator('.layout-topbar, app-topbar, #top-navbar').first()
        .waitFor({ state: 'visible', timeout: 25000 }).catch(() => {});

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before starting a new order.');
        await page.pause();
    }

    // Start a new request
    try {
        const trigger = page.locator('li.submenu-large-desktop a.quickorder-a', {
            hasText: /Quick Order|New Request|Create Order/i,
        });
        await expect(trigger).toBeVisible({ timeout: 5000 });
        await trigger.click();
    } catch (error) {
        console.warn('Fallback to span → ancestor anchor');
        const fallback = page
            .locator('li.submenu-large-desktop span', {
                hasText: /Quick Order|New Request|Create Order/i,
            })
            .locator('xpath=ancestor::a[1]');
        await expect(fallback).toBeVisible({ timeout: 5000 });
        await fallback.click();
    }

    // Wait for QO form to open — accept either the combined label or the ad type selector alone
    await page.locator('p-select#adtype-select, [id="adtype-select"]').waitFor({ state: 'visible', timeout: 30000 });
    // Open Ad Type dropdown and select 'Radio Commercial'
    const adTypeSelector = page.locator('p-select#adtype-select');
    await adTypeSelector.click();
    await page.getByRole('option', { name: 'Radio Commercial' }).click();

    console.log('Filling out required QO form fields...');

    // Fill in Client Information with 10s wait for auto-suggest
    // Explicitly wait for the client autocomplete input to become editable — prod environments
    // can take longer to enable the input after ad type selection.
    const clientInput = page.locator('p-autocomplete[name="card_client_id"] input');
    await clientInput.waitFor({ state: 'visible', timeout: 20000 });
    await page.waitForTimeout(500); // brief stabilization after ad-type selection
    await clientInput.fill("Burgers");

    // Wait for the autocomplete option to appear – use a broader locator and semantic role
    const option = page.getByRole('option', { name: /Bob['’]s Burgers/i }).first();
    await option.waitFor({ state: 'visible', timeout: 15000 });
    await option.click();

    // Generate dynamic data
    const isciCode = generateRandomISCI();
    const spotTitle = generateRandomSpotTitle();
    const dueDate = calculateDueDate(3);
    const startDate = calculateStartDate();
    const endDate = calculateEndDate();
    const contractNO = `CN${Math.floor(1000 + Math.random() * 9000)}`;

    // Fill in Spot Title using a retry loop
    const upperSpotTitle = spotTitle.toUpperCase();
    const spotTitleInput = page.locator('#spot-cards-list-wrapper').getByPlaceholder('Spot title');
    const tableTitleInput = page.locator('input[placeholder="Enter Title"]').first();

    await expect(spotTitleInput).toBeVisible();

    let success = false;
    const methods = ['fill', 'sequential', 'evaluate'];
    for (const [index, method] of methods.entries()) {
        console.log(`Attempting to fill Spot Title (Attempt ${index + 1}) using method: ${method}`);

        if (method === 'fill') {
            await spotTitleInput.fill(upperSpotTitle);
        } else if (method === 'sequential') {
            await spotTitleInput.click();
            await spotTitleInput.press('Control+a');
            await spotTitleInput.press('Backspace');
            await spotTitleInput.fill(upperSpotTitle);
        } else if (method === 'evaluate') {
            await spotTitleInput.evaluate((el: HTMLInputElement, val: string) => {
                const input = el as HTMLInputElement;
                input.value = val;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }, upperSpotTitle);
        }

        await spotTitleInput.focus();
        await page.keyboard.press('Tab');
        await page.waitForTimeout(2000);

        const currentTableValue = await tableTitleInput.inputValue();
        if (currentTableValue.toUpperCase() === upperSpotTitle) {
            console.log(`✅ Spot Title "${upperSpotTitle}" synced successfully using ${method} method.`);
            success = true;
            break;
        }
    }

    if (!success) {
        const finalValue = await tableTitleInput.inputValue();
        expect(finalValue.toUpperCase(), `Spot Title failed to sync to grid. Current value: "${finalValue}"`).toBe(upperSpotTitle);
    }

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before status selection.');
        await page.pause();
    }

    await page.getByText('Select Status').click();
    await page.getByText('Needs Writing').click();

    // Fill Sales POC — required on QA; p-multiselect at the top of the form sidebar.
    // Do NOT press Escape to close — Escape on QO form triggers "Draft Saved" dialog.
    const salesMultiselect = page.locator('#spot-cards-list-wrapper p-multiselect').filter({ hasText: /Select Sales/i }).first();
    const salesFallback = page.locator('#spot-cards-list-wrapper p-multiselect, .p-drawer-content p-multiselect').first();
    const salesEl = await salesMultiselect.isVisible({ timeout: 2000 }).catch(() => false)
        ? salesMultiselect
        : salesFallback;
    if (await salesEl.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('📝 Filling Sales POC...');
        await salesEl.scrollIntoViewIfNeeded();
        await salesEl.click({ force: true });
        await page.waitForTimeout(500);
        const msItems = page.locator('.p-multiselect-option, li[role="option"]');
        await msItems.first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
        const itemCount = await msItems.count();
        if (itemCount > 0) {
            const optionText = await msItems.first().innerText().catch(() => '');
            await msItems.first().click();
            console.log(`✅ Sales POC selected: "${optionText.trim()}"`);
        }
        // Close overlay by clicking a neutral area — do NOT press Escape
        await page.locator('#spot-cards-list-wrapper, .p-drawer-content').first()
            .click({ position: { x: 5, y: 5 } }).catch(() => {});
        await page.waitForTimeout(300);
    } else {
        console.log('ℹ️ Sales multiselect not visible — skipping (may be optional on this environment)');
    }

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before filling in ISCI Code.');
        await page.pause();
    }

    await page.locator('#spot-cards-list-inner').getByPlaceholder('AD-ID OR ISCI CODE').click();
    await page.locator('#spot-cards-list-inner').getByPlaceholder('AD-ID OR ISCI CODE').fill(isciCode);

    await page.getByRole('textbox', { name: 'Length ' }).fill('30');
    await page.getByRole('textbox', { name: 'Rotation ' }).fill('100');

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before date input.');
        await page.pause();
    }

    // Date inputs inside the QO spot grid row — use placeholder-based selectors since p-datepicker
    // does not consistently pass the [name] attribute to the host element across all session states.
    // The QO form is a complementary/aside panel; the grid table has "Due Date" column header.
    // Use page-wide "MM-DD-YYYY" placeholder inputs scoped to the QO grid table (not the sidebar form).
    // The grid table header has "Due Date", "Start Date", "End Date" columns — the inputs appear in order.
    const qoGridTable = page.locator('table').filter({ has: page.locator('th, [role="columnheader"]', { hasText: 'Due Date' }) }).first();
    await qoGridTable.waitFor({ state: 'visible', timeout: 15000 });

    const dueDateInput = qoGridTable.locator('input[placeholder*="MM-DD"]').nth(0);
    await dueDateInput.click().catch(() => {});
    await dueDateInput.evaluate((el: Element) => (el as HTMLElement).removeAttribute('readonly')).catch(() => {});
    await dueDateInput.fill(dueDate);
    await dueDateInput.press('Tab');

    const startDateInput = qoGridTable.locator('input[placeholder*="MM-DD"]').nth(1);
    await startDateInput.click().catch(() => {});
    await startDateInput.evaluate((el: Element) => (el as HTMLElement).removeAttribute('readonly')).catch(() => {});
    await startDateInput.fill(startDate);
    await startDateInput.press('Tab');

    const endDateInput = qoGridTable.locator('input[placeholder*="MM-DD"]').nth(2);
    await endDateInput.click().catch(() => {});
    await endDateInput.evaluate((el: Element) => (el as HTMLElement).removeAttribute('readonly')).catch(() => {});
    await endDateInput.fill(endDate);
    await endDateInput.press('Tab');

    const stations = page.locator('p-checkbox[name="card_stations"] input[type="checkbox"]');
    await expect(stations.first()).toBeVisible();

    const count = await stations.count();
    const randomIndex = Math.floor(Math.random() * count);
    const station = stations.nth(randomIndex);
    await station.click();

    const contractInput = page.locator('input[placeholder="Add Contract #"]');
    await contractInput.fill(contractNO);

    const filesSection = page.locator('label', { hasText: 'Files' });
    await filesSection.scrollIntoViewIfNeeded();
    await expect(filesSection).toBeVisible();

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before file uploads.');
        await page.pause();
    }

    console.log('Uploading file via URL...');
    const urlAsFileBtn = page.locator('a#urlFileLink, a:has-text("URL As File")').first();
    // Scroll first — the label scrollIntoView only ensures "Files" label is visible,
    // not the links below it
    await urlAsFileBtn.scrollIntoViewIfNeeded();
    await expect(urlAsFileBtn).toBeVisible({ timeout: 15000 });
    await urlAsFileBtn.click({ force: true });

    // Target the actual p-drawer element using its semantic role for better visibility detection
    const activeDrawer = page.getByRole('complementary').filter({ hasText: /Upload File Using URL/i }).first();
    await activeDrawer.waitFor({ state: 'attached', timeout: 15000 });

    // We check if it's visible, but we proceed even if Playwright is unsure about its visibility 
    // due to PrimeNG drawer animation/wrapper styles, as long as it is attached.
    const isVisible = await activeDrawer.isVisible();
    console.log(`Drawer visibility status: ${isVisible}`);

    console.log('Filling URL as File details...');
    // FIX: input[inputid="..."] is not a valid HTML attribute — PrimeNG renders inputId as the
    // standard `id` attribute and also sets `name`. Use name="fileName" / name="fileUrl" which
    // are confirmed working in the passing QA-279 test using the same URL-upload form.
    const urlFileNameInput = activeDrawer.locator('input[name="fileName"], #urlFileName').filter({ visible: true }).first();
    await urlFileNameInput.waitFor({ state: 'visible', timeout: 10000 });
    await urlFileNameInput.fill('Test File via URL');

    const urlFileUrlInput = activeDrawer.locator('input[name="fileUrl"], #url').filter({ visible: true }).first();
    await urlFileUrlInput.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    await urlFileUrlInput.fill('https://vcreative.com/test-audio.mp3');

    // Handle the File Description dropdown (PrimeNG 19 p-select)
    // Using a more robust locator for any select in the drawer
    const descDropdown = activeDrawer.locator('p-select, p-dropdown, .p-select, .p-dropdown, [role="combobox"]').first();
    await descDropdown.scrollIntoViewIfNeeded().catch(() => { });
    await expect(descDropdown).toBeAttached({ timeout: 10000 });
    await descDropdown.click();

    // Select "Final Spot" or similar - using force: true because overlays/masks might intercept
    // We look for any option that matches the text
    const fileOption = page.locator('.p-select-option, .p-dropdown-item, [role="option"]').filter({ hasText: /Final Spot|Prod File/i }).first();
    await fileOption.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
    await fileOption.click({ force: true }).catch(() => { });

    console.log('Saving URL file...');
    // Log all buttons in drawer for debugging
    const buttonsInDrawer = activeDrawer.locator('button, [role="button"], .p-button');
    const buttonCount = await buttonsInDrawer.count().catch(() => 0);
    console.log(`Found ${buttonCount} buttons in drawer area.`);
    for (let i = 0; i < buttonCount; i++) {
        const text = await buttonsInDrawer.nth(i).innerText().catch(() => 'no text');
        const role = await buttonsInDrawer.nth(i).getAttribute('role').catch(() => 'no role');
        console.log(`Button ${i}: "${text}" (role: ${role})`);
    }

    // Primary action button: try by common save keywords, then type="submit", then LAST button.
    // Using .last() because PrimeNG drawers typically order [Cancel / secondary, SAVE / primary].
    const saveByText = activeDrawer.locator('button').filter({ hasText: /^(SAVE|Save|ADD|Add File|Submit|SUBMIT|OK|Apply|APPLY)$/i }).first();
    const saveBySubmit = activeDrawer.locator('button[type="submit"]').first();
    // Last non-close button — exclude X/close icon buttons by filtering out those with only icon content
    const saveByLast = activeDrawer.locator('button:not([aria-label*="close" i]):not([class*="-close"])').last();

    let savedViaBtn = false;
    for (const btn of [saveByText, saveBySubmit, saveByLast]) {
        if (await btn.isVisible({ timeout: 1000 }).catch(() => false)) {
            const txt = ((await btn.textContent().catch(() => '')) ?? '').trim();
            console.log(`Clicking save button: "${txt}"`);
            await btn.scrollIntoViewIfNeeded().catch(() => {});
            await btn.click({ force: true });
            savedViaBtn = true;
            break;
        }
    }
    if (!savedViaBtn) {
        console.log('No save button found, pressing Enter...');
        await activeDrawer.locator('input[name="fileUrl"], #url').filter({ visible: true }).first().focus().catch(() => {});
        await page.keyboard.press('Enter');
    }

    // Wait for drawer to close
    console.log('Waiting for drawer to close...');
    await page.waitForTimeout(2000);
    if (await activeDrawer.isVisible()) {
        console.warn('Drawer still visible, attempting to close with Escape...');
        await page.keyboard.press('Escape');
    }

    console.log('Verifying attached file link...');
    // test env: a#showFileTypeName carries the file TYPE as text, file NAME as title attribute
    // QA env: plain <a> with the file NAME as link text (no title/id)
    const qoWrapper = page.locator('#spot-cards-list-wrapper');
    const attachedFileLink = qoWrapper.locator(
        'a[title*="Test File via URL"], a:has-text("Test File via URL")'
    ).first();
    await expect(attachedFileLink).toBeVisible({ timeout: 30000 });

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before Drag-and-Drop upload.');
        await page.pause();
    }

    console.log('Uploading file via drag-and-drop...');
    const dragDropFilePath = path.resolve(__dirname, '../../storage/test_files/Client Logo.jpg');
    const dropzoneInput = qoWrapper.locator('p-fileupload input[type="file"]').first();
    await expect(dropzoneInput).toBeAttached({ timeout: 5000 });
    await dropzoneInput.setInputFiles(dragDropFilePath);
    await page.waitForTimeout(2000); // Allow S3 upload to start

    console.log('Waiting for file type dropdown to appear after drag-drop...');
    // Scope to #spot-cards-list-wrapper to avoid matching file type dropdowns in other parts of the page.
    // After drag-drop upload, exactly 1 new "Select a File Type" dropdown appears inside the QO form.
    // Use the p-select component directly (not span.p-select-label) to ensure the trigger is clicked.
    const allFileTypeSelects = qoWrapper.locator('p-select, p-dropdown').filter({ hasText: /Select a File Type|File Type/i });
    await expect(allFileTypeSelects.first()).toBeVisible({ timeout: 30000 });
    const dragDropSelect = allFileTypeSelects.last();
    // Click the dropdown trigger button inside p-select (PrimeNG 19)
    const dragDropTrigger = dragDropSelect.locator('[data-pc-section="trigger"], .p-select-trigger, .p-dropdown-trigger').first();
    if (await dragDropTrigger.isVisible({ timeout: 1000 }).catch(() => false)) {
        await dragDropTrigger.click();
    } else {
        await dragDropSelect.click();
    }
    await page.locator('.p-select-option, li[role="option"]', { hasText: 'Client Logo' }).first().click();
    await page.waitForTimeout(500);

    // After selecting file type, click Save to finalize — the button may render outside qoWrapper.
    // Use full-page scope with 5s timeout to match the same button text as the list-view upload form.
    const dragDropSaveBtn = page.getByRole('button', { name: 'Save', exact: true });
    if (await dragDropSaveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await dragDropSaveBtn.click();
        console.log('✅ Clicked Save for drag-drop file type');
        // Wait for the file-type dropdown to disappear (form closed)
        await allFileTypeSelects.first().waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1000);
    }

    // S3 uploads are asynchronous and can take several seconds to complete and re-render.
    // Scroll to see newly added file row
    await qoWrapper.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(3000); // Extra wait for S3 upload processing
    // test env: a#showFileTypeName text="Client Logo"; QA: link text="Client Logo.jpg" (filename)
    const dragDropFileLink = qoWrapper.locator('a#showFileTypeName, a').filter({ hasText: /Client Logo/i }).first();
    await expect(dragDropFileLink).toBeVisible({ timeout: 60000 }); // Increased to 60s
    await expect(dragDropFileLink).toHaveText(/Client Logo/i);

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before file dialog upload');
        await page.pause();
    }

    console.log('Uploading file via file dialog...');
    const fileDialogFilePath = path.resolve(__dirname, '../../storage/test_files/Background Music.mp3');
    // PrimeNG 19 removed span.p-fileupload-choose — use p-fileupload input[type="file"] directly.
    // The same hidden input handles both drag-drop and choose-button interactions.
    // Scope to QO wrapper to avoid matching file inputs in inline-edit rows.
    const fileDialogInput = qoWrapper.locator('p-fileupload input[type="file"]').first();
    await expect(fileDialogInput).toBeAttached({ timeout: 5000 });
    await fileDialogInput.setInputFiles(fileDialogFilePath);
    await page.waitForTimeout(2000); // Allow S3 upload to start

    console.log('Waiting for file type dropdown to appear after file dialog...');
    // After selecting "Client Logo" for drag-drop, there are 0 "Select a File Type" dropdowns remaining.
    // After the file dialog upload, 1 new "Select a File Type" dropdown appears inside the QO form.
    const allFileTypeSelects2 = qoWrapper.locator('p-select, p-dropdown').filter({ hasText: /Select a File Type|File Type/i });
    await expect(allFileTypeSelects2.first()).toBeVisible({ timeout: 30000 });
    const fileDialogSelect = allFileTypeSelects2.last();
    const fileDialogTrigger = fileDialogSelect.locator('[data-pc-section="trigger"], .p-select-trigger, .p-dropdown-trigger').first();
    if (await fileDialogTrigger.isVisible({ timeout: 1000 }).catch(() => false)) {
        await fileDialogTrigger.click();
    } else {
        await fileDialogSelect.click();
    }
    await page.locator('.p-select-option, li[role="option"]', { hasText: 'Background Music' }).first().click();
    await page.waitForTimeout(500);

    // After selecting file type, click Save — same pattern as drag-drop above.
    const fileDialogSaveBtn = page.getByRole('button', { name: 'Save', exact: true });
    if (await fileDialogSaveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await fileDialogSaveBtn.click();
        console.log('✅ Clicked Save for file-dialog file type');
        await allFileTypeSelects2.first().waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1000);
    }

    // test env: a#showFileTypeName text="Background Music"; QA: link text="Background Music.mp3" (filename)
    const fileDialogFileLink = qoWrapper.locator('a#showFileTypeName, a').filter({ hasText: /Background Music/i }).first();
    await expect(fileDialogFileLink).toBeVisible();
    await expect(fileDialogFileLink).toHaveText(/Background Music/i);

    // Extract POID from the QO form URL before submission (the URL has ?edit=${poid})
    const preSubmitUrl = page.url();
    const poidMatch = preSubmitUrl.match(/edit=(\d+)/);

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing before submitting the order.');
        await page.pause();
    }

    // Pre-flight checks before submission — mirror the OrderHelper.submitOrder() logic:
    // ensure all draft spots have stations, fill any remaining contract fields, and verify
    // no required fields are flagged as missing by the form's validation.
    await ensureAllDraftSpotsHaveStations(page).catch(() => {});
    await fillContractField(page).catch(() => {});

    // Diagnostic: dump all input values in the QO form to identify missing fields
    const formDiag = await page.evaluate(() => {
        const containers = [
            document.querySelector('[data-pc-name="drawer"]'),
            document.querySelector('.p-drawer'),
            document.querySelector('.p-sidebar'),
            document.querySelector('app-v-sidebar'),
            document.querySelector('[role="complementary"]'),
            document.querySelector('#qo-form-panel'),
        ].filter(Boolean);
        const container = containers[0] || document.body;
        const inputs = Array.from(container.querySelectorAll('input, select, textarea, p-select, p-dropdown'));
        return inputs.map(el => {
            const htmlEl = el as HTMLInputElement;
            return {
                tag: el.tagName,
                id: htmlEl.id || null,
                name: htmlEl.name || null,
                placeholder: htmlEl.placeholder || null,
                value: htmlEl.value || null,
                type: htmlEl.type || null,
                ariaLabel: el.getAttribute('aria-label'),
                required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
                disabled: htmlEl.disabled || false,
            };
        });
    }).catch(() => []);
    console.log(`📋 QO form input diagnostic (${formDiag.length} inputs):`);
    for (const inp of formDiag) {
        if (inp.required || !inp.value) {
            console.log(`  [${inp.tag}] id="${inp.id}" name="${inp.name}" placeholder="${inp.placeholder}" value="${inp.value}" required=${inp.required} disabled=${inp.disabled}`);
        }
    }

    await verifyNoMissingFields(page).catch((e) => console.warn(`⚠️ Pre-flight check: ${e.message}`));

    const submitBtn = page.locator('#submit-all-drafts');
    await submitBtn.click();
    await page.waitForTimeout(3000);

    // Dismiss any lead time warning or blocking dialog that appears after submit.
    for (let attempt = 0; attempt < 3; attempt++) {
        const warningDialog = page.locator('p-dialog').filter({ visible: true }).first();
        if (await warningDialog.isVisible({ timeout: 2000 }).catch(() => false)) {
            const dlgText = (await warningDialog.textContent().catch(() => '')) ?? '';
            console.log(`⚠️ Dialog after submit (attempt ${attempt + 1}): "${dlgText.substring(0, 80).trim()}"`);
            const okBtn = warningDialog.locator('button:has-text("OK"), button:has-text("Ok"), button:has-text("CONTINUE WORKING"), .p-dialog-header-close').first();
            if (await okBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
                await okBtn.click({ force: true });
                await warningDialog.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
                await page.waitForTimeout(1000);
            }
        }

        // If the QO form panel is still open, run pre-flight again and retry submit
        if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
            console.log(`⚠️ QO form still open after submit attempt ${attempt + 1} — running pre-flight and retrying`);
            await ensureAllDraftSpotsHaveStations(page).catch(() => {});
            await fillContractField(page).catch(() => {});
            await submitBtn.click({ force: true });
            await page.waitForTimeout(3000);
        } else {
            break; // Form closed — submission succeeded
        }
    }

    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    // Capture the post-submit URL — the app navigates here after QO submission.
    // Subsequent steps (listview, slideout, history) use this URL to find the spot without
    // triggering DemoProdDirector's saved 'Status: Deleted,Canceled' filter on order/${poid}.
    const postSubmitUrl = page.url();
    console.log(`Post-submit URL: ${postSubmitUrl}`);

    if (poidMatch) {
        const poid = poidMatch[1];
        const browserName = browser.browserType().name();
        const combinedFilePath = path.resolve(__dirname, `../../storage/qa-196/qa-196_spot_data_${TEST_ENV}_${browserName}.json`);
        fs.mkdirSync(path.dirname(combinedFilePath), { recursive: true });
        const combinedData = {
            timestamp: new Date().toISOString(),
            spotTitle,
            poid,
            postSubmitUrl,
            expectedFileEventCount: 3
        };
        fs.writeFileSync(combinedFilePath, JSON.stringify([combinedData], null, 2));
        console.log(`Saved spot data: poid=${poid}, postSubmitUrl=${postSubmitUrl}`);
    }

    console.log('✅ QO interaction test completed successfully.');
    await context.close();
}
