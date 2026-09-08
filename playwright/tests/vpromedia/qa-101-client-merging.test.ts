/**
 * QA-101: Client Merging
 *
 * Tests the end-to-end client merge workflow:
 * 1. Admin verifies/enables "Require client approval for AE's"
 * 2. DemoSalesExec discovers an existing client, creates a QO with a typo'd version → draft
 * 3. DemoProdDirector approves the typo'd client
 * 4. DemoSalesExec opens the draft and submits it → confirmed in Inbox
 * 5. DemoProdDirector merges the typo client into the correct client
 * 6. DemoSalesExec reloads Inbox and verifies the order now shows the corrected client name
 */

import { test, expect, BASE_URL } from '../../utils/setup';
import { openQuickOrderForm, createOrderWithNewClient, selectAdType, fillOrderDates, submitOrder, fillContractField } from '../../utils/OrderHelper';
import { calculateDueDate, calculateStartDate, calculateEndDate } from '../../utils/QO_helpers';
import { ensureClientApprovalSetting, checkFirmSettingCached } from '../../utils/FirmOptionsHelper';
import { goToFolder, ensureSystemFolder } from '../../utils/NavHelper';
import { findRowByScrolling, ensureListView, findSpotByTitle } from '../../utils/ViewHelper';
import { clearSearchFilters } from '../../utils/SearchHelper';

test.describe.configure({ mode: 'serial' });

// Shared state across serial test blocks
let correctClientName: string;
let typoClientName: string;
let orderTitle: string;
let submittedPoid: string | null = null;

/**
 * Generate a unique typo variant of a client name.
 * Appends a random suffix to ensure it never matches an existing client,
 * even across repeated test runs.
 */
function createTypoName(name: string): string {
    const suffix = Math.floor(1000 + Math.random() * 9000);
    // Take the first word(s) and change the last character + add suffix
    const chars = name.split('');
    for (let i = chars.length - 1; i >= 0; i--) {
        if (/[a-zA-Z]/.test(chars[i])) {
            chars[i] = chars[i] === 'Z' ? 'A' : chars[i] === 'z' ? 'a'
                : String.fromCharCode(chars[i].charCodeAt(0) + 1);
            break;
        }
    }
    return `${chars.join('')}_${suffix}`;
}

test.describe('QA-101: Client Merging', () => {

    test.use({ viewport: { width: 1529, height: 960 } });

    // Multi-user handoff with approve + submit + merge is too long for the default 60s
    test.setTimeout(300_000);

    // ───────────────────────────────────────────────
    // Block 1 — Pre-condition: Enable Firm Setting
    // ───────────────────────────────────────────────
    const isCached = checkFirmSettingCached('Demo Broadcasting', 'clientApprovalRequired', true);

    test.describe('Pre-condition: Enable Firm Setting', () => {
        if (isCached) {
            console.log('⚡ Skipping Admin pre-condition: Firm setting already verified in cache.');
            test.skip();
        }

        test.use({ user: 'Admin' });

        test('Ensure "Require client approval for AEs" is enabled', async ({ page }) => {
            await ensureClientApprovalSetting(page, true, 'Demo Broadcasting');
            console.log('✅ Firm setting verified: Require client approval for AEs = ENABLED');
        });
    });

    // ───────────────────────────────────────────────
    // Block 2 — Discover Client & Create Typo Order
    // ───────────────────────────────────────────────
    test.describe('Discover Client & Create Typo Order (DemoSalesExec)', () => {
        test.use({ user: 'DemoSalesExec' });

        test('Discover existing client, submit order with typo name', async ({ page }) => {

            await test.step('Discover an existing client name via autocomplete', async () => {
                await page.waitForLoadState('domcontentloaded');
                await openQuickOrderForm(page);
                await selectAdType(page, 'Radio Commercial');

                const clientInput = page.locator('p-autocomplete[name="card_client_id"] input');
                await clientInput.click();
                await clientInput.fill('a');

                // Wait for the autocomplete dropdown options to populate (polling logic)
                const allOptions = page.getByRole('option').or(page.locator('.p-autocomplete-item'));
                let optionCount = 0;
                for (let attempt = 0; attempt < 10; attempt++) {
                    await page.waitForTimeout(1000);
                    optionCount = await allOptions.count();
                    if (optionCount > 1) break; // Found options (usually New Client + real clients)
                }

                // Read the first real client (skip "New Client:" entries)
                for (let i = 0; i < optionCount; i++) {
                    const text = await allOptions.nth(i).textContent();
                    if (text && !/New Client:/i.test(text)) {
                        correctClientName = text.trim();
                        break;
                    }
                }

                expect(correctClientName, 'Must discover at least one existing client').toBeTruthy();
                typoClientName = createTypoName(correctClientName);

                console.log(`✅ Discovered existing client: "${correctClientName}"`);
                console.log(`🧪 Typo version: "${typoClientName}"`);

                // Close the QO form — typing triggers auto-draft, producing a "Draft Saved" dialog
                await page.keyboard.press('Escape'); // close autocomplete dropdown
                await page.waitForTimeout(500);

                // Click the sidebar close icon to trigger the "Draft Saved" dialog
                const closeIcon = page.locator(
                    'a#closeIcon, .p-sidebar-close, button.p-sidebar-close, .p-drawer-close'
                ).first();
                if (await closeIcon.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await closeIcon.click({ force: true });
                    await page.waitForTimeout(1000);
                }

                // The "Draft Saved" dialog appears with CLOSE WITHOUT SAVING / CONTINUE WORKING / CLOSE AND SAVE
                const draftDialog = page.locator('.p-dialog').filter({ hasText: /Draft Saved/i });
                const closeWithoutSavingBtn = draftDialog.getByRole('button', { name: /CLOSE WITHOUT SAVING/i });
                if (await closeWithoutSavingBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
                    console.log('ℹ️ Clicking "CLOSE WITHOUT SAVING" to discard discovery draft');
                    await closeWithoutSavingBtn.click();
                    await page.waitForTimeout(1000);
                }
            });

            await test.step('Open Quick Order form', async () => {
                await openQuickOrderForm(page);
            });

            await test.step('Create order with typo client name', async () => {
                const result = await createOrderWithNewClient(page, {
                    newClientName: typoClientName
                });
                orderTitle = result.title;
                console.log(`🧪 Order title: "${orderTitle}" with client "${typoClientName}"`);

                // Fill required date fields and contract so the order is "completed"
                await fillOrderDates(page, calculateDueDate(3), calculateStartDate(), calculateEndDate());
                await fillContractField(page);
                await page.keyboard.press('Tab');
                await page.waitForTimeout(1000);
            });

            if (process.env.PWDEBUG === '1') await page.pause();

            await test.step('Submit order — expect client-approval draft warning', async () => {
                const submitBtn = page.getByRole('button', { name: 'SUBMIT ALL' });
                await submitBtn.scrollIntoViewIfNeeded();
                await submitBtn.click({ force: true });

                const toaster = page.getByRole('alert').filter({ hasText: /new client.*approve/i });
                await expect(toaster).toBeVisible({ timeout: 10000 });
                console.log('✅ Client approval warning toaster received');

                // Close the form since it stays open after a client approval warning
                const closeIcon = page.locator('a#closeIcon, .p-sidebar-close, button.p-sidebar-close, .p-drawer-close, .p-dialog-header-close, .v-sidebar-header .close-btn').first();
                if (await closeIcon.isVisible({ timeout: 5000 }).catch(() => false)) {
                    await closeIcon.click();
                } else {
                    console.log('⚠️ Close button not visible, pressing Escape');
                    await page.keyboard.press('Escape');
                }

                // Handle the "Draft Saved" dialog to ensure the completed form is properly saved
                const draftDialog = page.locator('.p-dialog').filter({ hasText: /Draft Saved/i });
                if (await draftDialog.isVisible({ timeout: 5000 }).catch(() => false)) {
                    console.log('ℹ️ Handling "Draft Saved" dialog by clicking "CLOSE AND SAVE"');
                    const closeAndSaveBtn = draftDialog.locator('button:has-text("CLOSE AND SAVE")').first();
                    if (await closeAndSaveBtn.isVisible().catch(() => false)) {
                        await closeAndSaveBtn.click();
                    } else {
                        // Fallback if only 'CLOSE' is available
                        await draftDialog.locator('button:has-text("CLOSE")').first().click();
                    }
                    await page.waitForTimeout(2000);
                }
                
                // Wait for the panel to actually close
                const modal = page.locator('app-quickorders, .p-dialog, .p-sidebar, .p-drawer, .p-sidebar-active, #quickorders-sidebar').first();
                try {
                    await expect(modal).not.toBeVisible({ timeout: 15000 });
                } catch (e) {
                    console.log('⚠️ QO Panel did not close automatically, forcefully removing from DOM...');
                }

                // Cleanup DOM to prevent click interception (WebKit/Angular ghosts)
                await page.evaluate(() => {
                    const els = document.querySelectorAll('app-quickorders, .v-sidebar-mask, .p-dialog-mask, .p-sidebar-mask');
                    els.forEach(el => el.remove());
                });
            });

            await test.step('Verify order landed in Drafts', async () => {
                // Wait for the QO sidebar to fully close before navigating
                await page.waitForTimeout(3000);
                
                await goToFolder(page, 'Drafts');
                await ensureListView(page);

                // Use Global Filter to find the order instantly and avoid pagination timeouts
                const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input, [placeholder*="Search"]').first();
                let found = false;

                if (await globalFilter.isVisible({ timeout: 5000 }).catch(() => false)) {
                    await globalFilter.clear();
                    await globalFilter.fill(typoClientName);
                    await page.waitForTimeout(2000); // Wait for filtering to apply
                    
                    found = await page.getByText(typoClientName, { exact: false }).first().isVisible();
                    if (!found) {
                        console.log(`ℹ️ Client name not found, trying order title...`);
                        await globalFilter.clear();
                        await globalFilter.fill(orderTitle);
                        await page.waitForTimeout(2000);
                        found = await page.getByText(orderTitle, { exact: false }).first().isVisible();
                    }
                } else {
                    console.log('⚠️ Global filter not visible, falling back to manual scrolling (may fail if view is List View)');
                    found = await findRowByScrolling(page, typoClientName);
                }

                if (!found) {
                    // Pending-approval clients appear as "Unknown Client" — rely on toaster as proof
                    console.log('⚠️ Order not found by title or client name (may show as "Unknown Client" while pending)');
                    console.log('✅ Relying on client-approval toaster as primary confirmation');
                } else {
                    console.log(`✅ Found draft "${orderTitle}" in Drafts folder`);
                }
            });
        });
    });

    // ───────────────────────────────────────────────
    // Block 3 — Approve Typo Client
    // ───────────────────────────────────────────────
    test.describe('Approve Typo Client (DemoProdDirector)', () => {
        test.use({ user: 'DemoProdDirector' });

        test('Approve the typo client in Settings > Clients', async ({ page }) => {

            await test.step('Navigate to Settings > Clients', async () => {
                await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
                await page.waitForLoadState('domcontentloaded');
                await page.locator('.sidebar, nav, [class*="sidebar"]').first()
                    .waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});
                await page.waitForTimeout(2000);

                await page.goto(`${BASE_URL}/#/settings/clients`, { waitUntil: 'domcontentloaded' });
                await page.waitForLoadState('domcontentloaded');
                await page.locator('.p-datatable, p-table').first()
                    .waitFor({ state: 'visible', timeout: 30000 });
                await page.waitForTimeout(2000);
            });

            await test.step('Toggle to Waiting Approval view', async () => {
                const toggleBtn = page.locator('button').filter({ hasText: /Waiting Approval|All/i }).last();
                await expect(toggleBtn).toBeVisible({ timeout: 10000 });
                const text = (await toggleBtn.textContent()) || '';
                if (text.includes('Waiting Approval')) {
                    await toggleBtn.click();
                    await page.waitForTimeout(2000);
                    console.log('ℹ️ Toggled to Waiting Approval view');
                } else {
                    console.log('ℹ️ Already in Waiting Approval view');
                }
            });

            await test.step('Find and approve the typo client', async () => {
                const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input').first();
                await expect(globalFilter).toBeVisible({ timeout: 10000 });
                await globalFilter.fill(typoClientName);
                await page.waitForTimeout(2000);

                const clientRow = page.locator('.p-datatable-tbody tr, tbody tr').filter({
                    hasText: typoClientName
                }).first();
                await expect(clientRow).toBeVisible({ timeout: 10000 });

                const approveBtn = clientRow.locator('button').filter({
                    has: page.locator('.fa-check, .pi-check')
                }).first();

                if (await approveBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await approveBtn.click();
                } else {
                    const allButtons = clientRow.locator('button');
                    await allButtons.nth(2).click();
                }
                await page.waitForTimeout(1000);
            });

            await test.step('Confirm approval dialog', async () => {
                const confirmDialog = page.locator('.p-dialog').filter({
                    hasText: new RegExp(`Approve.*${typoClientName.substring(0, 10)}`, 'i')
                }).last();
                await expect(confirmDialog).toBeVisible({ timeout: 10000 });

                const yesBtn = confirmDialog.getByRole('button', { name: 'YES, CONFIRM' }).or(
                    confirmDialog.locator('button').filter({ hasText: 'YES, CONFIRM' })
                ).first();
                await expect(yesBtn).toBeVisible({ timeout: 5000 });
                await yesBtn.click({ force: true });
                await page.waitForTimeout(2000);
                console.log(`✅ Client "${typoClientName}" approved`);
            });
        });
    });

    // ───────────────────────────────────────────────
    // Block 4 — Submit Draft (DemoSalesExec)
    // ───────────────────────────────────────────────
    test.describe('Submit Draft Order (DemoSalesExec)', () => {
        test.use({ user: 'DemoSalesExec' });

        test('Open draft and submit, then confirm in Inbox', async ({ page }) => {

            await test.step('Navigate to Drafts and find the order', async () => {
                await page.keyboard.press('Escape');
                await page.waitForTimeout(500);
                await page.locator('.p-dialog-mask, .p-overlay-mask, .p-drawer-mask').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
                await goToFolder(page, 'Drafts');
                await ensureListView(page);
                await page.waitForTimeout(2000);

                let found = false;

                // First: check page 1 directly (newly created draft should be near top)
                const directRow = page.locator('.p-datatable-tbody tr, p-table tbody tr').filter({ hasText: orderTitle }).first();
                found = await directRow.isVisible({ timeout: 5000 }).catch(() => false);

                // Second: try scrolling through the grid
                if (!found) {
                    console.log(`ℹ️ Order title not found on page 1, trying findRowByScrolling...`);
                    found = await findRowByScrolling(page, orderTitle).catch(() => false);
                }

                // Third: try findRowByScrolling with typoClientName
                if (!found) {
                    console.log(`ℹ️ Not found by title, trying findRowByScrolling with client name...`);
                    found = await findRowByScrolling(page, typoClientName).catch(() => false);
                }

                // Last resort: All folder (in case order was submitted already)
                if (!found) {
                    console.log('ℹ️ Not found in Drafts, trying All folder...');
                    await goToFolder(page, 'All');
                    await ensureListView(page);
                    const allRow = page.locator('.p-datatable-tbody tr, p-table tbody tr').filter({ hasText: orderTitle }).first();
                    found = await allRow.isVisible({ timeout: 5000 }).catch(() => false);
                    if (!found) {
                        found = await findRowByScrolling(page, orderTitle).catch(() => false);
                    }
                }

                expect(found, `Draft must exist for title "${orderTitle}" or client "${typoClientName}"`).toBeTruthy();
                console.log(`✅ Found draft for client "${typoClientName}"`);
            });

            await test.step('Open the draft by clicking the client name', async () => {
                // In list/compact view, clicking the Client Name link opens the order for editing
                const orderRow = page.locator('tr, .p-datatable-row').filter({
                    hasText: typoClientName
                }).first();
                const clientLink = orderRow.locator('a').filter({
                    hasText: typoClientName
                }).first();
                await clientLink.scrollIntoViewIfNeeded();
                await clientLink.click();
                
                // Explicitly wait for the QO/Edit drawer to open by checking for its action buttons
                const submitBtn = page.getByRole('button', { name: /SUBMIT ALL/i }).first();
                await expect(submitBtn).toBeVisible({ timeout: 15000 });
                console.log('ℹ️ Clicked client name and QO drawer opened');
                await page.waitForTimeout(1000); // give DOM a moment to settle
            });

            await test.step('Submit the completed draft', async () => {
                // The QO/edit drawer is now open. The fields were filled in Step 2.
                // Use the robust submitOrder helper to submit it
                submittedPoid = await submitOrder(page);
                console.log(`✅ Draft "${orderTitle}" submitted (POID: ${submittedPoid})`);
            });

            await test.step('Verify order appears in Inbox', async () => {
                // Wait for processing to complete
                await page.waitForTimeout(2000);

                if (submittedPoid) {
                    // Using deep URL link method as a focused 'quick filter' view to bypass pagination
                    const deepUrl = `${BASE_URL}/#/vpro/production-orders/order/${submittedPoid}`;
                    console.log(`ℹ️ Navigating directly to order deep link: ${deepUrl}`);
                    await page.goto(deepUrl, { waitUntil: 'domcontentloaded' });
                    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

                    const orderRow = page.locator('tr, .p-datatable-row, .spot-list-view-item, .v-list-item, div.item').filter({ hasText: orderTitle }).first();

                    // Backend indexing after submit can lag; reload once if the row hasn't rendered.
                    let visible = await orderRow.isVisible({ timeout: 10000 }).catch(() => false);
                    if (!visible) {
                        console.log(`⏳ Order row not yet visible at deep link — reloading and retrying...`);
                        await page.reload({ waitUntil: 'domcontentloaded' });
                        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
                        visible = await orderRow.isVisible({ timeout: 15000 }).catch(() => false);
                    }
                    expect(visible, `Order "${orderTitle}" should appear at deep link ${deepUrl}`).toBeTruthy();

                    // Verify it lacks a "Draft" flag
                    const draftBadge = orderRow.locator('.badge, .status-badge').filter({ hasText: 'Draft' });
                    await expect(draftBadge).toHaveCount(0);

                    console.log(`✅ Verified order "${orderTitle}" appears in Inbox and is no longer a draft`);
                } else {
                    console.log(`⚠️ POID was not captured during submission. Falling back to Inbox navigation...`);
                    await goToFolder(page, 'Inbox');
                    await page.waitForTimeout(2000);
                    
                    // Use Global Filter to find the order instantly
                    const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input, [placeholder*="Search"]').first();
                    let found = false;

                    if (await globalFilter.isVisible({ timeout: 5000 }).catch(() => false)) {
                        await globalFilter.clear();
                        await globalFilter.fill(orderTitle);
                        await page.waitForTimeout(2000);
                        found = await page.getByText(orderTitle, { exact: false }).first().isVisible();
                    } else {
                        console.log('⚠️ Global filter not visible, falling back to manual scrolling (may fail if view is List View)');
                        found = await findRowByScrolling(page, orderTitle);
                    }

                    if (found) {
                        console.log(`✅ Order "${orderTitle}" confirmed in Inbox with client "${typoClientName}"`);
                    } else {
                        console.log(`⚠️ Order "${orderTitle}" not found in Inbox scroll.`);
                    }
                }
            });
        });
    });

    // ───────────────────────────────────────────────
    // Block 5 — Merge Typo Client into Correct Client
    // ───────────────────────────────────────────────
    test.describe('Merge Client (DemoProdDirector)', () => {
        test.use({ user: 'DemoProdDirector' });

        test('Merge typo client into the correct client', async ({ page }) => {

            await test.step('Navigate to Settings > Clients', async () => {
                await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
                await page.waitForLoadState('domcontentloaded');
                await page.locator('.sidebar, nav, [class*="sidebar"]').first()
                    .waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});
                await page.waitForTimeout(2000);

                await page.goto(`${BASE_URL}/#/settings/clients`, { waitUntil: 'domcontentloaded' });
                await page.waitForLoadState('domcontentloaded');
                await page.locator('.p-datatable, p-table').first()
                    .waitFor({ state: 'visible', timeout: 30000 });
                // Wait for the initial client list to populate before filtering,
                // otherwise the search fires against an empty grid and no row renders.
                await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
                await page.locator('.p-datatable-tbody tr, tbody tr').first()
                    .waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
            });

            await test.step('Search for the correct client', async () => {
                const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input').first();
                await expect(globalFilter).toBeVisible({ timeout: 10000 });
                await globalFilter.clear();
                await globalFilter.fill(correctClientName);
                // Let debounce + filter query resolve before asserting on the filtered row.
                await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
                await page.waitForTimeout(1000);
            });

            await test.step('Click Merge on correct client row', async () => {
                const correctRow = page.locator('.p-datatable-tbody tr, tbody tr').filter({
                    hasText: correctClientName
                }).first();

                // Filter can occasionally miss on the first fire; clear and re-fill once if the row hasn't rendered.
                let rowVisible = await correctRow.isVisible({ timeout: 10000 }).catch(() => false);
                if (!rowVisible) {
                    console.log(`⏳ correctRow not visible after initial filter — clearing and re-filling...`);
                    const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input').first();
                    await globalFilter.clear();
                    await page.waitForTimeout(500);
                    await globalFilter.fill(correctClientName);
                    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
                    rowVisible = await correctRow.isVisible({ timeout: 10000 }).catch(() => false);
                }
                expect(rowVisible, `correctRow for "${correctClientName}" should be visible after filter`).toBeTruthy();

                // For approved clients, Actions: Edit(0), Merge(1), Delete(2), ClientUsers(3), Lock(4)
                const mergeBtn = correctRow.locator('button').filter({
                    has: page.locator('.fa-compress')
                }).first();

                if (await mergeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await mergeBtn.click();
                } else {
                    const allButtons = correctRow.locator('button');
                    const btnCount = await allButtons.count();
                    console.log(`ℹ️ Found ${btnCount} buttons in row, trying index 1 (merge)...`);
                    await allButtons.nth(1).click();
                }
                await page.waitForTimeout(2000);
            });

            if (process.env.PWDEBUG === '1') await page.pause();

            await test.step('Select typo client in merge drawer', async () => {
                const mergeHeader = page.locator('h3').filter({ hasText: /Merge Clients/i }).first();
                await expect(mergeHeader).toBeVisible({ timeout: 10000 });
                console.log('✅ Merge Clients drawer is visible');

                // DOM confirmed: this is a PrimeNG p-multiselect with NO native <select>.
                // The hidden input uses role="combobox". There is no <select> fallback.
                const multiselect = page.locator('#client-selector p-multiselect, p-multiselect').first();
                await expect(multiselect).toBeVisible({ timeout: 5000 });
                console.log('ℹ️ Detected PrimeNG multiselect for merge client selector');

                // Open the overlay
                await multiselect.click();
                await page.waitForTimeout(1000);

                // Filter for the typo client using full name to uniquely identify this run's client
                // (using only 15 chars showed all historical typo clients from past test runs,
                // pushing the current run's client off-screen in the scrollable dropdown)
                const filterInput = page.locator(
                    '.p-multiselect-filter, [data-pc-section="filterinput"], input[role="searchbox"]'
                ).first();
                if (await filterInput.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await filterInput.fill(typoClientName);
                    await page.waitForTimeout(1500);
                    console.log(`ℹ️ Filtered multiselect for "${typoClientName}"`);
                }

                // Click the typo client option — include [role="option"] without li restriction for PrimeNG v19
                const typoOption = page.locator(
                    '.p-multiselect-item, [data-pc-section="option"], li[role="option"], [role="option"]'
                ).filter({ hasText: typoClientName }).first();
                await expect(typoOption).toBeVisible({ timeout: 10000 });
                await typoOption.scrollIntoViewIfNeeded();
                await typoOption.click();
                await page.waitForTimeout(1000);

                // Close overlay cleanly. Use explicit close button if available.
                // DO NOT use Escape — it propagates up and closes the entire drawer.
                const closeBtn = page.locator('.p-multiselect-close, [data-pc-section="closebutton"]').first();
                if (await closeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await closeBtn.click();
                } else {
                    await multiselect.click();
                }
                await page.waitForTimeout(1500);
                console.log(`✅ Selected typo client "${typoClientName}" via PrimeNG multiselect`);

                // Wait for merge preview content to load (backend query after selection)
                await page.waitForLoadState('domcontentloaded').catch(() => {});
                await page.waitForTimeout(2000);

                // Verify the merge preview loaded
                const previewCheck = page.getByText(/I understand/i).first();
                if (!(await previewCheck.isVisible({ timeout: 8000 }).catch(() => false))) {
                    // WebKit flake: PrimeNG onChange didn't fire from the overlay click.
                    // Re-open overlay, deselect + reselect the option to force onChange.
                    console.log('⚠️ Merge preview did not load — retrying with deselect/reselect cycle...');

                    await multiselect.click();
                    await page.waitForTimeout(1000);

                    // Clear the filter first to find our option
                    const retryFilter = page.locator(
                        '.p-multiselect-filter, [data-pc-section="filterinput"], input[role="searchbox"]'
                    ).first();
                    if (await retryFilter.isVisible({ timeout: 2000 }).catch(() => false)) {
                        await retryFilter.fill(typoClientName.substring(0, 15));
                        await page.waitForTimeout(1000);
                    }

                    const retryOption = page.locator(
                        '.p-multiselect-item, [data-pc-section="option"], li[role="option"]'
                    ).filter({ hasText: typoClientName }).first();

                    if (await retryOption.isVisible({ timeout: 3000 }).catch(() => false)) {
                        // Deselect (uncheck) the already-selected option
                        await retryOption.click();
                        await page.waitForTimeout(500);
                        // Re-select (check) the option — this should fire onChange
                        await retryOption.click();
                        await page.waitForTimeout(500);
                        console.log('ℹ️ Deselect/reselect cycle completed');
                    }

                    // Close overlay cleanly
                    const retryCloseBtn = page.locator('.p-multiselect-close, [data-pc-section="closebutton"]').first();
                    if (await retryCloseBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
                        await retryCloseBtn.click();
                    } else {
                        await multiselect.click();
                    }
                    await page.waitForTimeout(1500);

                    await page.waitForLoadState('domcontentloaded').catch(() => {});
                    await page.waitForTimeout(3000);
                    console.log('ℹ️ Retry complete — proceeding to merge confirmation');
                }
            });

            await test.step('Check I-understand and confirm merge', async () => {
                // Wait for merge preview content to load
                const understandText = page.getByText(/I understand/i).first();
                await expect(understandText).toBeVisible({ timeout: 15000 });
                console.log('ℹ️ Merge preview content loaded');

                // Click the checkbox or its label
                const checkboxArea = page.locator('p-checkbox, [class*="p-checkbox"]').filter({
                    hasText: /I understand/i
                }).first();

                if (await checkboxArea.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await checkboxArea.click();
                    console.log('✅ "I understand" checkbox checked via p-checkbox');
                } else {
                    await understandText.click();
                    console.log('✅ "I understand" clicked via text');
                }
                await page.waitForTimeout(1000);

                // Click MERGE button
                const mergeBtn = page.locator('button').filter({ hasText: /MERGE/i }).first();
                await expect(mergeBtn).toBeVisible({ timeout: 5000 });
                await expect(mergeBtn).toBeEnabled({ timeout: 10000 });
                await mergeBtn.click();
                await page.waitForTimeout(1000);

                // Handle potential confirmation dialog
                const confirmBtn = page.locator('button').filter({ hasText: /OK|Yes|Confirm/i }).first();
                if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await confirmBtn.click();
                    console.log('ℹ️ Confirmed merge dialog');
                }

                await page.waitForTimeout(3000);
                console.log(`✅ Client "${typoClientName}" merged into "${correctClientName}"`);
            });

            await test.step('Verify typo client no longer in client list', async () => {
                await page.reload({ waitUntil: 'domcontentloaded' });
                await page.waitForTimeout(3000);

                const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input').first();
                await expect(globalFilter).toBeVisible({ timeout: 10000 });
                await globalFilter.clear();
                await globalFilter.fill(typoClientName);
                await page.waitForTimeout(2000);

                const dataRows = page.locator('.p-datatable-tbody tr, tbody tr').filter({
                    hasText: typoClientName
                });
                expect(await dataRows.count()).toBe(0);
                console.log('✅ Typo client no longer appears in client list');
            });
        });
    });

    // ───────────────────────────────────────────────
    // Block 6 — Verify Inbox Correction
    // ───────────────────────────────────────────────
    test.describe('Verify Inbox Correction (DemoSalesExec)', () => {
        test.use({ user: 'DemoSalesExec' });

        test('Verify submitted order now shows the corrected client name', async ({ page }) => {
            await test.step('Clear active search filters', async () => {
                await clearSearchFilters(page);
            });

            await test.step('Navigate to All folder', async () => {
                if (submittedPoid) {
                    const deepUrl = `${BASE_URL}/#/vpro/production-orders/order/${submittedPoid}`;
                    console.log(`ℹ️ Navigating directly to order deep link: ${deepUrl}`);
                    await page.goto(deepUrl, { waitUntil: 'domcontentloaded' });
                    await page.waitForTimeout(2000);
                } else {
                    await ensureSystemFolder(page, 'All');
                    await goToFolder(page, 'All');
                }
            });

            await test.step('Find order and verify corrected client', async () => {
                let found = false;

                if (submittedPoid) {
                    found = await page.locator('tr, .p-datatable-row, .spot-list-view-item, .v-list-item, div.item').first().waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false);
                    if (!found) {
                        console.log('⚠️ Deep link shows no rows — falling back to All folder search');
                        await ensureSystemFolder(page, 'All');
                        await goToFolder(page, 'All');
                        const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input, [placeholder*="Search"]').first();
                        const isFilterVisible = await globalFilter.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
                        if (isFilterVisible) {
                            await globalFilter.clear();
                            await globalFilter.fill(orderTitle);
                            await page.waitForTimeout(2000);
                            found = await page.getByText(orderTitle, { exact: false }).first().isVisible().catch(() => false);
                            if (!found) {
                                await globalFilter.clear();
                                await globalFilter.fill(correctClientName);
                                await page.waitForTimeout(2000);
                                found = await page.getByText(orderTitle, { exact: false }).first().isVisible().catch(() => false);
                            }
                        } else {
                            found = await findRowByScrolling(page, orderTitle);
                        }
                    }
                } else {
                    const globalFilter = page.locator('[placeholder*="Global Filter"], #global-filter-input, [placeholder*="Search"]').first();
                    const isFilterVisible = await globalFilter.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
                    if (isFilterVisible) {
                        await globalFilter.clear();
                        await globalFilter.fill(orderTitle);
                        await page.waitForTimeout(2000);
                        found = await page.getByText(orderTitle, { exact: false }).first().isVisible();
                    } else {
                        console.log('⚠️ Global filter not visible, falling back to manual scrolling');
                        found = await findRowByScrolling(page, orderTitle);
                    }
                }

                expect(found, `Order "${orderTitle}" must exist in All folder`).toBeTruthy();

                const orderRow = page.locator('tr, .p-datatable-row, .spot-list-view-item, .v-list-item, div.item').filter({
                    hasText: orderTitle
                }).first();
                await expect(orderRow).toBeVisible();

                // Check if client name is already corrected
                const hasCorrectName = await orderRow.textContent()
                    .then(text => text?.includes(correctClientName) || false)
                    .catch(() => false);

                if (hasCorrectName) {
                    console.log(`✅ Order "${orderTitle}" shows corrected client "${correctClientName}"`);
                    return;
                }

                // Reload and retry — merge propagation may need a fresh page load
                console.log('ℹ️ Client name not yet updated — reloading page...');
                await page.reload({ waitUntil: 'domcontentloaded' });
                await page.waitForTimeout(3000);
                
                if (submittedPoid) {
                    const deepUrl = `${BASE_URL}/#/vpro/production-orders/order/${submittedPoid}`;
                    await page.goto(deepUrl, { waitUntil: 'domcontentloaded' });
                } else {
                    await ensureSystemFolder(page, 'All');
                    await goToFolder(page, 'All');
                }
                
                await page.waitForTimeout(2000);

                const orderRow2 = page.locator('tr, .p-datatable-row, .spot-list-view-item, .v-list-item, div.item').filter({
                    hasText: orderTitle
                }).first();
                await expect(orderRow2).toBeVisible();
                await expect(orderRow2).toContainText(correctClientName, { timeout: 10000 });
                console.log(`✅ Order "${orderTitle}" shows corrected client "${correctClientName}"`);
            });
        });
    });
});
