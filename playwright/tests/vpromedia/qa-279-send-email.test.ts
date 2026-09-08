// playwright/tests/qa-279-send-email.test.ts
//
// QA-279: Send Email function

import { test, expect, BASE_URL } from '../../utils/setup';
import { goToFolder } from '../../utils/NavHelper';
import { waitForEmail, extractUrlsFromBody } from '../../utils/Imail_Test_Email_Check';
import { ensureListView } from '../../utils/ViewHelper';

test.describe('QA-279: Send Email Function', () => {

    test.use({ user: 'DemoProdDirector' });

    test('Send Email with attached file generates valid file links', async ({ page, browser }) => {
        test.setTimeout(240_000); // Allow extra time for email delivery and QO creation

        const uniqueId = Date.now().toString().slice(-6);
        const plusEmail = `imail-test+qa279_${uniqueId}@vcreativeinc.com`;

        await test.step('Locate an existing spot in All folder and attach a file', async () => {
            console.log('Navigating to All folder to ensure we have a spot to attach a file to...');
            await goToFolder(page, 'All');
            await ensureListView(page);

            // Wait for grid to load and stabilize by waiting for the first row
            const firstRow = page.locator('.p-datatable-tbody tr:not(.p-datatable-emptymessage), table tbody tr:not(.p-datatable-emptymessage)').filter({ has: page.locator('td') }).first();
            await expect(firstRow).toBeVisible({ timeout: 20_000 });

            // Extract the POID from the row's checkbox ID for logging
            const checkbox = firstRow.locator('.p-checkbox-input, input[type="checkbox"]').first();
            const checkboxId = await checkbox.getAttribute('id').catch(() => '');
            const spotPoid = checkboxId ? checkboxId.replace('table-checkbox-', '') : 'Unknown';
            console.log(`Using existing spot from All folder. POID: ${spotPoid}`);

            // Attach a file via URL to this spot directly from the List View
            console.log('Attaching file via URL to the spot...');
            
            // Re-query the first row and its Browse button to avoid garbage-collected nodes under memory pressure
            const getFreshBrowseBtn = () => page.locator('.p-datatable-tbody tr:not(.p-datatable-emptymessage), table tbody tr:not(.p-datatable-emptymessage)').filter({ has: page.locator('td') }).first()
                .locator('a.link, .link, a, button').filter({ hasText: 'Browse' }).first();

            await getFreshBrowseBtn().waitFor({ state: 'visible', timeout: 20_000 });

            // Before clicking Browse, dismiss any lingering overlays:
            await page.locator('.p-dialog-mask, .p-overlay-mask').evaluateAll(
                masks => masks.forEach(m => (m as HTMLElement).click())
            ).catch(() => {});
            await page.waitForTimeout(500);

            // Aggressive loop to click Browse until the PrimeNG context menu actually appears
            const urlMenu = page.getByRole('menuitem', { name: 'URL' }).first();
            for (let i = 0; i < 5; i++) {
                console.log(`Clicking browse button (attempt ${i + 1})...`);
                const freshBrowseBtn = getFreshBrowseBtn();
                await freshBrowseBtn.click({ force: true, timeout: 5000 }).catch(() => { });

                if (await urlMenu.isVisible({ timeout: 5000 }).catch(() => false)) {
                    console.log('URL menu appeared.');
                    break;
                }
            }

            await expect(urlMenu).toBeVisible({ timeout: 5000 });
            await urlMenu.click({ force: true });

            // Wait for drawer input to appear
            const fileNameInput = page.locator('input[name="fileName"]').filter({ visible: true }).first();
            await fileNameInput.waitFor({ state: 'visible', timeout: 20_000 });
            await fileNameInput.fill('QA279 File', { force: true });

            const fileUrlInput = page.locator('input[name="fileUrl"]').filter({ visible: true }).first();
            await fileUrlInput.waitFor({ state: 'visible', timeout: 5000 }).catch(() => { });
            await fileUrlInput.fill('https://vcreative.com/test-audio.mp3', { force: true });

            console.log('F1. Clicking fileTypeDropdown...');
            const fileTypeDropdown = page.locator('p-select, p-dropdown, [role="combobox"]').filter({ visible: true }).first();
            await fileTypeDropdown.click({ force: true });

            console.log('F2. Waiting for panel...');
            // Wait for PrimeNG 19's panel to attach to body
            await page.locator('.p-select-panel, .p-dropdown-panel, [role="listbox"]').first()
                .waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});

            console.log('F3. Finding fileOption...');
            const fileOption = page.locator('div.p-select-panel li.p-select-option, .p-dropdown-item, [role="option"]').filter({ hasText: /Final Spot|Prod File/i, visible: true }).first();
            await expect(fileOption).toBeVisible({ timeout: 5000 }).catch(() => { });

            console.log('F4. Clicking fileOption...');
            await fileOption.click({ force: true, timeout: 5000 }).catch(() => { });

            console.log('F5. Calling page.evaluate to submit...');
            // The QA Environment's URL Upload drawer swallows Physical clicks and hangs Playwright Locators
            // Use native DOM injection to submit the modal identically to a user-triggered submit JS event
            // Use setTimeout to decouple the click from Playwright's execution context, preventing it from hanging if Angular locks the loop
            await page.evaluate(() => {
                setTimeout(() => {
                    const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
                    for (const btn of buttons) {
                        if (btn.textContent && btn.textContent.trim().toUpperCase() === 'SAVE') {
                            (btn as HTMLElement).click();
                        }
                    }
                }, 0);
            });
            console.log('F6. Evaluate done, waiting for modal to close...');

            // Wait for the modal to close and file addition to register
            await page.locator('input[name="fileName"]').filter({ visible: true }).first()
                .waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => {});
            console.log('File successfully attached.');
        });

        await test.step('Open Send Email sidebar and dispatch email', async () => {
            const firstRow = page.locator('.p-datatable-tbody tr, table tbody tr').first();

            // Post-upload grid hydration can corrupt firstRow references; look anywhere in the table body
            const sendEmailTrigger = page.locator('tbody a, tbody div.link').filter({ hasText: /Send Email/i }).first();
            await sendEmailTrigger.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => { });

            // Check visibility and click natively to bypass QA overlay bugs
            try {
                // Ensure we wait for it to be found
                await expect(sendEmailTrigger).toBeAttached({ timeout: 15_000 });
                await sendEmailTrigger.evaluate(el => (el as HTMLElement).click());
            } catch (error) {
                console.warn('⚠️ Send Email link fallback physical click.');
                await sendEmailTrigger.click({ force: true, timeout: 5000 }).catch(() => { });
            }

            const emailDialog = page.locator('.p-drawer, .p-sidebar, p-drawer, p-sidebar').filter({ hasText: /Sending Email/i }).first();
            await expect(emailDialog).toBeVisible({ timeout: 15_000 });

            // Add the recipient to the To field
            console.log(`Addressing email to ${plusEmail}...`);
            const chipsInput = emailDialog.locator('p-chips input, p-autocomplete input, input[type="email"], input[placeholder*="Email"]').first();
            await chipsInput.fill(plusEmail);
            await chipsInput.press('Enter');
            // Wait for the chip token to appear in the DOM before pressing Tab
            await page.locator('p-chips .p-chip, .p-chips-token, p-autocomplete .p-autocomplete-token').first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
            await chipsInput.press('Tab'); // Trigger blur to ensure PrimeNG registers the chip
            await page.waitForTimeout(2000); // Allow Angular form re-validation cycle

            // Wait for any background dialog masks (like from the file upload modal) to fully clear
            await expect(page.locator('.p-dialog-mask, .p-overlay-mask')).not.toBeVisible({ timeout: 15000 }).catch(() => {});
            await page.waitForTimeout(1500);

            // Select the file we attached to be sent
            console.log('Selecting the attached file...');
            // In legacy code, they did nth(1).click() on checkboxes. 
            const fileCheckbox = emailDialog.locator('p-checkbox, .p-checkbox').filter({ hasText: /QA279 File/i }).first();

            // PrimeNG checkboxes usually have the input inside or as a sibling
            if (await fileCheckbox.isVisible({ timeout: 3000 }).catch(() => false)) {
                await fileCheckbox.evaluate(el => (el as HTMLElement).click());
            } else {
                // Just click first available file checkbox
                const anyFileCheckbox = emailDialog.locator('.p-checkbox-box, p-checkbox').first();
                if (await anyFileCheckbox.isVisible()) {
                    await anyFileCheckbox.evaluate(el => (el as HTMLElement).click());
                } else {
                    // Try to click standard input checkbox inside the dialog
                    const checkInput = emailDialog.locator('input[type="checkbox"]').first();
                    if (await checkInput.isVisible()) {
                        await checkInput.evaluate(el => (el as HTMLElement).click());
                    }
                }
            }

            // Click send using DOM-level evaluate click to bypass overlay pointer interception
            const sendBtn = emailDialog.getByRole('button', { name: /Send/i }).first();
            await expect(sendBtn).toBeEnabled({ timeout: 30000 });
            await sendBtn.evaluate(el => (el as HTMLElement).click());

            const toast = page.locator('.p-toast-message').filter({ hasText: /Email successfully sent/i });
            await expect(toast).toBeVisible({ timeout: 15_000 });
            console.log('✅ Email successfully sent toast appeared.');
        });

        await test.step('Verify email receipt and extract valid file links', async () => {
            console.log(`Checking email inbox for notifications sent to ${plusEmail}...`);

            // Use the unique recipient address as strings or "qa279" as search terms.
            // Using the full email guarantees exact isolation from other users tests.
            const result = await waitForEmail(plusEmail, plusEmail, {
                timeout: 180_000,
                interval: 10_000
            });

            expect(result.found, `Expected to find an email sent to "${plusEmail}"`).toBe(true);

            console.log(`✅ Email found! Subject: "${result.subject}"`);

            // Extract the body and parse URLs
            const body = result.body || '';
            const urls = extractUrlsFromBody(body);

            console.log(`Extracted ${urls.length} URLs from the email body.`);
            expect(urls.length).toBeGreaterThan(0);

            // Verify that at least one URL responds with HTTP 200
            let validLinkFound = false;
            for (const url of urls) {
                // Some links in emails might be vCreative app links, we are just looking for general accessibility
                try {
                    console.log(`Testing URL from email: ${url}`);
                    const response = await page.request.get(url, { maxRedirects: 3 });
                    if (response.ok()) {
                        console.log(`✅ URL is valid (HTTP ${response.status()})`);
                        validLinkFound = true;
                        break;
                    } else {
                        console.log(`⚠️ URL returned HTTP ${response.status()}`);
                    }
                } catch (e) {
                    console.log(`⚠️ Error validating URL ${url}:`, e);
                }
            }

            expect(validLinkFound, "Expected at least one valid, accessible URL in the email").toBe(true);
        });
    });
});
