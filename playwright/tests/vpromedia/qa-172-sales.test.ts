/**
 * qa-172-sales.test.ts
 * 
 * Regression test for QA-172: Compact View - Sales Workflow.
 */

import { test, expect, BASE_URL } from '../../utils/setup';
import { createAndSubmitOrder } from '../../utils/OrderHelper';

test.describe('QA-172: Compact View - Sales Workflow', () => {
    test.use({ user: 'DemoSalesExec' });

    test('Verify Quick Order and Bottom Toolbar Actions', async ({ page }) => {
        test.setTimeout(240000);

        console.log('--- Step 1: Ensure Compact View ---');
        await page.goto(BASE_URL);

        const settingsBtn = page.locator('#settings-btn');
        await settingsBtn.waitFor({ state: 'visible' });
        await page.locator('#loader-wrapper').waitFor({ state: 'hidden', timeout: 30000 }).catch(() => {});
        await settingsBtn.click();

        const compactOption = page.locator('#compact_listview, .p-menu-item-link, .p-menuitem-link').filter({ hasText: /^Compact$/i }).first();
        if (await compactOption.isVisible()) {
            await compactOption.click();
            try {
                await page.waitForLoadState('domcontentloaded', { timeout: 10000 });
                await page.waitForTimeout(1000); // Minimal stabilization
            } catch (e) {
                if (String(e).includes('closed') || String(e).includes('crashed')) {
                    console.log('⚠️ Page context lost — likely OOM in headless mode');
                    throw new Error('Page crashed in headless mode — reduce parallel workers or memory usage');
                }
                throw e;
            }
        } else {
            await settingsBtn.click();
        }

        console.log('--- Step 2: Create Quick Order ---');
        const order = await createAndSubmitOrder(page, {
            client: "Bob's Burgers",
            title: 'QA-172-SALES-' + Date.now(),
            adType: 'Radio Commercial'
        });
        expect(order.poid).not.toBeNull();
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Pausing after Quick Order creation.');
            await page.pause();
        }

        console.log('--- Step 3: Verify Bottom Toolbar ---');
        const inboxUrl = `${BASE_URL.replace(/\/$/, '')}/#/vpro/production-orders/folder/inbox`;
        await page.goto(inboxUrl, { waitUntil: 'domcontentloaded' });
        await page.waitForLoadState('domcontentloaded');
        // Wait for compact cards or table rows to appear
        await page.locator('.compact-card, .p-datatable-tbody tr').first().waitFor({ state: 'visible', timeout: 30000 });
        await page.waitForTimeout(2000);

        const rowCheckbox = page.locator('.p-checkbox-input, .p-checkbox-box').first();
        await expect(rowCheckbox).toBeVisible({ timeout: 20000 });
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Pausing before Row Selection.');
            await page.pause();
        }
        await rowCheckbox.scrollIntoViewIfNeeded();
        await rowCheckbox.click();

        await expect(page.locator('a[title="Copy"], a:has-text("Copy")')).toBeVisible({ timeout: 15000 });
        await expect(page.locator('a[title="Revise"], a:has-text("Revise")')).toBeVisible();
        await expect(page.locator('a[title="Extend"], a:has-text("Extend")')).toBeVisible();
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Final verification pause.');
            await page.pause();
        }
    });
});
