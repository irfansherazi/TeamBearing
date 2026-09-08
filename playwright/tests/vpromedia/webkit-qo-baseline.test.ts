/**
 * WebKit QO Baseline — Single Quick Order Submission
 *
 * Purpose: A minimal, self-contained test that creates and submits one
 * Radio Commercial Quick Order. Designed as the validation testbed for
 * cross-browser input fixes (VC2-8972).
 *
 * Pattern drawn from QA-46 (Basic Ad Types, Test 1) which is known-passing
 * on Chromium with the same user/client/ad-type combination.
 *
 * Run on Chromium first to establish baseline:
 *   $env:TEST_ENV="test"; npx playwright test webkit-qo-baseline --project=chromium
 *
 * Then validate on WebKit:
 *   $env:TEST_ENV="test"; npx playwright test webkit-qo-baseline --project=webkit
 */

import { test, expect } from '../../utils/setup';
import {
    openQuickOrderForm,
    createBasicOrder,
    submitOrder,
} from '../../utils/OrderHelper';
import { goToFolder } from '../../utils/NavHelper';
import { findRowByScrolling } from '../../utils/ViewHelper';

test.describe('WebKit QO Baseline', () => {
    test.use({ user: 'DemoProdDirector' });
    test.use({ viewport: { width: 1529, height: 960 } });

    // Allow generous time — WebKit is slower with form interactions
    test.setTimeout(180_000);

    const CLIENT = "Bob's Burgers";

    test('Create and submit a single Radio Commercial order', async ({ page }) => {
        let title: string;
        let isci: string;
        let poid: string | null;

        await test.step('Navigate to Inbox', async () => {
            await page.goto('/#/vpro/production-orders/folder/inbox');
            await page.waitForLoadState('domcontentloaded');
            await page.waitForSelector('.layout-topbar, app-topbar, #settings-btn', { timeout: 30000 }).catch(() => {});
            await page.waitForTimeout(3000);
            console.log('📂 Navigated to Inbox');
        });

        await test.step('Open Quick Order form', async () => {
            await openQuickOrderForm(page);
        });

        await test.step('Fill Radio Commercial order', async () => {
            const result = await createBasicOrder(page, {
                client: CLIENT,
                adType: 'Radio Commercial',
                status: 'Needs Writing',
                salesPoc: true,
            });
            title = result.title;
            isci = result.isci;
            console.log(`📋 Order filled — Title: "${title}" | ISCI: ${isci}`);
        });

        await test.step('Submit order and verify POID', async () => {
            poid = await submitOrder(page);
            expect(poid, `Expected a valid POID after submitting "${title}"`).toBeTruthy();
            console.log(`✅ Order submitted — POID: ${poid}`);
        });

        await test.step('Verify order is definitively NOT a Draft', async () => {
            await page.waitForTimeout(2000);
            
            // 1. Verify POID was returned (proof of server acceptance)
            expect(poid, 'POID must exist — order must have been accepted by the server.').toBeTruthy();
            console.log(`✅ Order accepted by server with POID: ${poid}`);
            
            // 2. Verify it is NOT in Drafts folder
            await page.goto('/#/vpro/production-orders/folder/drafts');
            await page.waitForLoadState('domcontentloaded');
            await page.waitForTimeout(3000);

            const partialTitle = title.split(' ').slice(0, 2).join(' ');
            const draftPageText = await page.locator('body').innerText();
            const inDrafts = draftPageText.includes(partialTitle);
            expect(inDrafts, `FATAL: Order "${title}" fell back to Draft status!`).toBe(false);
            console.log(`✅ Verified: Order "${partialTitle}" is NOT in Drafts. Submission confirmed via POID ${poid}.`);
        });
    });
});
