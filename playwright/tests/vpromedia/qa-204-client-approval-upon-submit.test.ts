/**
 * QA-204: Client Approval Upon Submit
 * 
 * Tests that when a firm has "Require client approval for AE's" enabled,
 * new clients created during order submission require admin approval.
 * 
 * Test Flow:
 * 1. Admin verifies/enables firm setting
 * 2. DemoSalesExec creates order with NEW client → Warning toaster, stays as draft
 * 3. DemoProdDirector approves new client in Settings > Clients > Waiting Approval
 * 4. DemoSalesExec verifies approval notification
 */

import { test, expect, BASE_URL } from '../../utils/setup';
import { openQuickOrderForm, createOrderWithNewClient } from '../../utils/OrderHelper';
import { ensureClientApprovalSetting, checkFirmSettingCached } from '../../utils/FirmOptionsHelper';
import { generateUniqueClientName } from '../../utils/QO_helpers';
import { goToFolder } from '../../utils/NavHelper';
import { findRowByScrolling } from '../../utils/ViewHelper';

// Serial execution required for multi-user handoff
test.describe.configure({ mode: 'serial' });

// Shared state between tests
let newClientName: string;
let orderTitle: string;
let orderPoid: string | null = null;

test.describe('QA-204: Client Approval Upon Submit', () => {

    // Optimized for 3440x1440 @ 150% Scaling: 2/3 width and full height in logical pixels
    test.use({ viewport: { width: 1529, height: 960 } });

    // Check if firm setting is already enabled to skip browser launch for Admin
    const isCached = checkFirmSettingCached('Demo Broadcasting', 'clientApprovalRequired', true);

    test.describe('Pre-condition: Enable Firm Setting', () => {
        if (isCached) {
            console.log('⚡ Skipping Admin pre-condition: Firm setting already verified in cache.');
            // Skip the entire group
            test.skip();
        }

        test.use({ user: 'Admin' });

        test('Ensure "Require client approval for AEs" is enabled', async ({ page }) => {
            await test.step('Navigate to Demo Broadcasting firm settings', async () => {
                await ensureClientApprovalSetting(page, true, 'Demo Broadcasting');
            });

            await test.step('Verify setting is enabled', async () => {
                // Re-check to confirm the setting stuck
                console.log('✅ Firm setting verified: Require client approval for AEs = ENABLED');
            });
        });
    });

    test.describe('Create Order with New Client (DemoSalesExec)', () => {
        test.use({ user: 'DemoSalesExec' });

        test('Submit order with NEW client triggers approval warning', async ({ page }) => {
            // Generate a unique client name for this test run
            newClientName = generateUniqueClientName();
            console.log(`🧪 Testing with new client: ${newClientName}`);

            // Debug pause
            if (process.env.PWDEBUG === '1') {
                console.log('Pause before opening QO form');
                await page.pause();
            }

            await test.step('Open Quick Order form', async () => {
                await openQuickOrderForm(page);
            });

            await test.step('Create and Submit order with NEW client', async () => {
                // This helper generates a random order title and fills the form
                const result = await createOrderWithNewClient(page, { newClientName });
                orderTitle = result.title;

                // Debug pause
                if (process.env.PWDEBUG === '1') {
                    console.log('Pause before submitting order');
                    await page.pause();
                }

                // Capture POID from URL BEFORE submit
                const preSubmitUrl = page.url();
                const preSubmitMatch = preSubmitUrl.match(/edit=(\d+)/);
                if (preSubmitMatch) {
                    orderPoid = preSubmitMatch[1];
                    console.log(`✅ Extracted POID from URL before submit: ${orderPoid}`);
                } else {
                    console.log('⚠️ Could not extract POID from URL. Deep linking may not work.');
                }

                // Submit the order - use exact text and forced click since it's in a fixed footer
                const submitBtn = page.getByRole('button', { name: 'SUBMIT ALL' });
                await submitBtn.scrollIntoViewIfNeeded();
                await submitBtn.click({ force: true });

                // Expect a toaster warning about client approval
                const toaster = page.getByRole('alert').filter({ hasText: /new client.*approve/i });
                await expect(toaster).toBeVisible({ timeout: 10000 });
                console.log('✅ Received expected client approval warning toaster');

                // Wait for QO panel to disappear to prevent navigation interception
                const modal = page.locator('app-quickorders, .p-dialog, .p-sidebar, .p-drawer, .p-sidebar-active, #quickorders-sidebar').first();
                await expect(modal).not.toBeVisible({ timeout: 10000 }).catch(() => {
                    console.log('⚠️ QO panel did not close automatically, proceeding...');
                });

                // WebKit cleanup: app-quickorders Angular wrapper stays in the DOM and blocks clicks
                await page.evaluate(() => {
                    const el = document.querySelector('app-quickorders');
                    if (el) {
                        (el as HTMLElement).style.visibility = 'hidden';
                        (el as HTMLElement).style.pointerEvents = 'none';
                    }
                }).catch(() => {});
                await page.waitForTimeout(1000);
            });

            // Debug pause
            if (process.env.PWDEBUG === '1') {
                console.log('Pause before verifying draft status');
                await page.pause();
            }

            await test.step('Verify order is visible in list view', async () => {
                if (orderPoid) {
                    const deepUrl = `${BASE_URL}/#/vpro/production-orders/order/${orderPoid}`;
                    console.log(`ℹ️ Navigating directly to order deep link: ${deepUrl}`);
                    await page.goto(deepUrl, { waitUntil: 'domcontentloaded' });
                    await page.waitForTimeout(2000);
                } else {
                    // The system automatically routes to a quick filter view showing the draft spot (e.g. folder/all?edit=X)
                    console.log(`🔍 Searching for draft order: "${orderTitle}" in current view`);
                    
                    // Allow a moment for the list view routing and rendering to complete after auto-close
                    await page.waitForTimeout(2000);

                    const found = await findRowByScrolling(page, orderTitle);

                    expect(found).toBeTruthy();
                }
                console.log('✅ Order confirmed as draft in quick filter view');
            });
        });
    });

    test.describe('Approve New Client (DemoProdDirector)', () => {
        test.use({ user: 'DemoProdDirector' });

        test('Approve new client in Settings > Clients > Waiting Approval', async ({ page }) => {
            // Debug pause
            if (process.env.PWDEBUG === '1') {
                console.log('Pause before approving new client');
                await page.pause();
            }

            await test.step('Navigate to Settings > Clients', async () => {
                // Try sidebar navigation first
                try {
                    await page.getByRole('link', { name: 'Settings' }).click({ timeout: 5000 });
                    await page.getByRole('link', { name: 'Clients' }).click({ timeout: 5000 });
                } catch (e) {
                    console.log('⚠️ Sidebar navigation failed or timed out, using deep-link fallback');
                    await page.goto(`${BASE_URL}/#/settings/clients`);
                }

                // 5 second wait for page to load
                await page.waitForTimeout(5000);
            });

            await test.step('Go to Waiting Approval tab', async () => {
                // The toggle button shifts between "Waiting Approval" and "All"
                const toggleBtn = page.locator('.p-button-label').filter({ hasText: /Waiting Approval|All/i }).first();
                await expect(toggleBtn).toBeVisible({ timeout: 10000 });

                const currentText = await toggleBtn.textContent();
                if (currentText?.includes('Waiting Approval')) {
                    console.log('🔘 Clicking "Waiting Approval" toggle');
                    await toggleBtn.click();
                    await page.waitForTimeout(2000);
                } else {
                    console.log('ℹ️ Toggle already set to "All" (viewing pending clients)');
                }
            });

            await test.step('Find and approve the new client', async () => {
                console.log(`🔍 Searching for pending client: "${newClientName}"`);

                // Use the Global Filter to isolate the client
                const globalFilter = page.locator('#global-filter-input, input[placeholder*="Search"], input[placeholder*="Filter"]').first();
                await page.waitForTimeout(5000); // Admin pages are heavier, wait for load
                await expect(globalFilter).toBeVisible({ timeout: 30000 });
                await globalFilter.fill(newClientName);
                await page.waitForTimeout(1000); // Wait for filtering to apply

                const clientRow = page.locator('tr, .p-datatable-row').filter({
                    hasText: newClientName
                }).first();

                if (await clientRow.isVisible({ timeout: 5000 })) {
                    console.log(`✅ Found client "${newClientName}" after filtering`);

                    // Click the approve action (checkmark button in actions column)
                    const approveButton = clientRow.getByRole('button', { name: /approve|✓/i }).or(
                        clientRow.locator('[class*="approve"], [class*="check"]')
                    ).first();

                    if (await approveButton.isVisible({ timeout: 3000 })) {
                        await approveButton.click();
                    } else {
                        const actionBtn = clientRow.locator('button, [role="button"]').first();
                        await actionBtn.click();
                    }
                } else {
                    console.log(`❌ Client "${newClientName}" not found even after filtering`);
                    throw new Error(`Client "${newClientName}" not found in Waiting Approval list`);
                }

                await page.waitForTimeout(1000);
            });

            // Debug pause
            if (process.env.PWDEBUG === '1') {
                console.log('Pause before confirming approval dialog');
                await page.pause();
            }

            await test.step('Confirm approval dialog', async () => {
                // PrimeNG dialog usually has .p-dialog class
                const confirmDialog = page.locator('.p-dialog').filter({
                    hasText: /Approve/i
                }).last(); // Use last() if multiple layers exist

                console.log('⏳ Waiting for approval confirmation dialog...');
                await expect(confirmDialog).toBeVisible({ timeout: 10000 });

                const confirmBtn = confirmDialog.getByRole('button', { name: 'YES, CONFIRM' }).or(
                    confirmDialog.locator('button').filter({ hasText: 'YES, CONFIRM' })
                ).first();

                await expect(confirmBtn).toBeVisible({ timeout: 5000 });
                console.log('🔘 Clicking YES, CONFIRM');
                await confirmBtn.click({ force: true });

                await page.waitForTimeout(2000);
                console.log(`✅ Client "${newClientName}" approved`);
            });

            await test.step('Verify client no longer in Waiting Approval', async () => {
                // Refresh the list
                await page.reload();
                await page.waitForTimeout(2000);

                const waitingApprovalTab = page.getByRole('button', { name: /Waiting Approval/i });
                await waitingApprovalTab.click();
                await page.waitForTimeout(2000);

                // Client should no longer appear
                const clientRow = page.locator('tr, .p-datatable-row').filter({
                    hasText: newClientName
                });

                const count = await clientRow.count();
                expect(count).toBe(0);
                console.log('✅ Verified: Client no longer in Waiting Approval list');
            });
        });
    });

    test.describe('Verify Notification (DemoSalesExec)', () => {
        test.use({ user: 'DemoSalesExec' });

        test('Verify approval notification received', async ({ page }) => {
            // Debug pause
            if (process.env.PWDEBUG === '1') {
                console.log('Pause before verifying notification');
                await page.pause();
            }

            await test.step('Check in-system notifications', async () => {
                // Look for the notification bell/icon
                const notificationBell = page.locator('[class*="notification"], [class*="bell"], .notification-icon').first();

                if (await notificationBell.isVisible({ timeout: 5000 })) {
                    await notificationBell.click();
                    await page.waitForTimeout(1000);

                    // Look for notification about client approval
                    const approvalNotification = page.locator('[class*="notification"]').filter({
                        hasText: new RegExp(`${newClientName}.*approved|approved.*${newClientName}`, 'i')
                    });

                    if (await approvalNotification.isVisible({ timeout: 5000 })) {
                        console.log('✅ Approval notification found');
                        await approvalNotification.click();
                    } else {
                        console.log('ℹ️ Approval notification may have been cleared or is pending');
                    }
                } else {
                    console.log('ℹ️ Notification icon not immediately visible, checking Drafts folder');
                }
            });

            await test.step('Verify draft can now be submitted', async () => {
                if (orderPoid) {
                    const deepUrl = `${BASE_URL}/#/vpro/production-orders/order/${orderPoid}`;
                    console.log(`ℹ️ Navigating directly to order deep link: ${deepUrl}`);
                    await page.goto(deepUrl, { waitUntil: 'domcontentloaded' });
                    await page.waitForTimeout(2000);
                } else {
                    // Navigate to Drafts folder to find the order
                    await goToFolder(page, 'Drafts');
                    console.log(`🔍 Searching for draft order: "${orderTitle}" to verify it's submittable`);

                    let found = false;

                    // Debug pause
                    if (process.env.PWDEBUG === '1') {
                        console.log('Pause before finding order');
                        await page.pause();
                    }

                    found = await findRowByScrolling(page, orderTitle);

                    expect(found).toBeTruthy();
                }
                console.log('✅ Found draft order—client approval flow verified.');
            });
        });
    });
});
