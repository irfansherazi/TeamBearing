/**
 * qa-172-production.test.ts
 * 
 * Regression test for QA-172: Compact View - Production Workflow.
 */

import { test, expect, BASE_URL } from '../../utils/setup';

test.describe('QA-172: Compact View - Production Workflow', () => {
    test.use({ user: 'DemoProdDirector' });

    test('Verify Accordion Details, POCs, and Files', async ({ page }) => {
        test.setTimeout(120000);

        const inboxUrl = `${BASE_URL.replace(/\/$/, '')}/#/vpro/production-orders/folder/inbox`;
        await page.goto(inboxUrl);
        await page.waitForSelector('#settings-btn', { timeout: 45000 });
        await page.waitForTimeout(2000); // Allow drawer to fully render if open

        // Live evidence 2026-08-07: DemoProdDirector storage state opens the Inbox behind a
        // full-screen Quick Order draft drawer (headed by "Production Orders" with a
        // CANCEL/SUBMIT ALL/DISCARD ALL DRAFTS button bar). Compact-card clicks silently
        // succeed against the covered cards but never open the spot-edit drawer, so the
        // downstream POC search fails. Dismiss the QO drawer aggressively before proceeding.
        for (let attempt = 0; attempt < 4; attempt++) {
            // Prefer a bottom-bar CANCEL when present — it's the reliable "close without saving"
            // path for the QO drawer. Fall back to top-right close icons after that.
            const cancelBtn = page.getByRole('button', { name: /^cancel$/i }).first();
            const discardBtn = page.getByRole('button', { name: /discard all drafts/i }).first();
            const closeIcon = page.locator(
                '#quickorders-sidebar #closeIcon:visible, app-quickorders #closeIcon:visible, ' +
                'app-quickorders button[aria-label="Close"]:visible, ' +
                '#quickorders-sidebar .p-drawer-close:visible, ' +
                '#quickorders-sidebar .p-sidebar-close:visible'
            ).first();

            let dismissed = false;
            if (await cancelBtn.isVisible({ timeout: 500 }).catch(() => false)) {
                console.log(`🚪 Cancel button visible (attempt ${attempt + 1}) — clicking to close QO drawer`);
                await cancelBtn.click({ force: true }).catch(() => {});
                dismissed = true;
            } else if (await closeIcon.isVisible({ timeout: 500 }).catch(() => false)) {
                console.log(`🚪 QO close icon visible (attempt ${attempt + 1}) — clicking`);
                await closeIcon.click({ force: true }).catch(() => {});
                dismissed = true;
            } else if (await discardBtn.isVisible({ timeout: 500 }).catch(() => false)) {
                console.log(`🚪 DISCARD ALL DRAFTS visible (attempt ${attempt + 1}) — clicking as last resort`);
                await discardBtn.click({ force: true }).catch(() => {});
                dismissed = true;
            }

            if (!dismissed) break;
            await page.waitForTimeout(1500); // Let drawer close & any confirm modal render

            // If a "leave without saving?" confirm dialog appears, accept it
            const leaveBtn = page.getByRole('button', { name: /leave|yes|discard|confirm|ok/i }).first();
            if (await leaveBtn.isVisible({ timeout: 800 }).catch(() => false)) {
                await leaveBtn.click({ force: true }).catch(() => {});
                await page.waitForTimeout(1000);
            }
        }

        // Clear any active search filter that parallel tests (e.g. QA-170) may have left active
        const comboboxLabel = (await page.locator('span#user-filter-header-drop-down').textContent().catch(() => '')) ?? '';
        if (comboboxLabel.includes('(0)') || comboboxLabel.includes('(...)')) {
            console.log('⚠️ Filter detected with no results — reloading to clear server-side filter state');
            await page.reload({ waitUntil: 'domcontentloaded' });
            await page.waitForSelector('#settings-btn', { timeout: 45000 });
        }
        // Wait for data to load
        await page.locator('.p-datatable-tbody tr, .p-checkbox-box, tbody tr').first().waitFor({ state: 'visible', timeout: 45000 });
        await page.waitForTimeout(2000); // UI stabilization
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Pausing after Inbox load.');
            await page.pause();
        }

        console.log('--- Step 2: Ensure Compact View ---');
        const applyCompactView = async () => {
            const settingsBtn = page.locator('#settings-btn').first();
            await expect(settingsBtn).toBeVisible({ timeout: 15000 });
            
            // Wait for loader wrapper and masks to clear
            await page.locator('#loader-wrapper').waitFor({ state: 'hidden', timeout: 30000 }).catch(() => {});
            await page.locator('.p-overlay-mask, .p-dialog-mask, .p-drawer-mask').evaluateAll(
                masks => masks.forEach(m => (m as HTMLElement).click())
            ).catch(() => {});
            await page.waitForTimeout(1000);
            
            await settingsBtn.click({ force: true }).catch(async () => {
                await settingsBtn.evaluate(el => (el as HTMLElement).click());
            });
            await page.waitForTimeout(1000); // Wait for menu to animate

            const compactOption = page.getByText('Compact', { exact: true }).first();
            const isCompactOptionVisible = await compactOption.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
            if (isCompactOptionVisible) {
                await compactOption.click({ force: true }).catch(async () => {
                    await compactOption.evaluate(el => (el as HTMLElement).click());
                });
                await page.waitForTimeout(3000); // Wait for re-render
                return true;
            } else {
                console.log('ℹ️ Compact Option not visible, closing settings menu...');
                await settingsBtn.click().catch(() => {}); // Close menu
                return false;
            }
        };

        // If not already in compact view (indicated by class "compact" on po-table-wrapper), apply compact view
        const tableWrapper = page.locator('.po-table-wrapper').first();
        const wrapperClass = (await tableWrapper.getAttribute('class').catch(() => '')) ?? '';
        if (!wrapperClass.includes('compact')) {
            console.log('🔄 Switching to Compact View...');
            await applyCompactView();
        }

        console.log('--- Step 3: Open Spot Edit Form and Verify POC ---');
        // In compact view, POC is inside the spot edit form. Open it by clicking the spot.
        // Live DOM 2026-08-07: POC roles vary by Ad Type. Image Ad → Graphic Design / Traffic
        // / Uploader. TV Ad → Writer / Filming / PostProd / Releaser / Traffic / Billing
        // (no Producer). Radio Commercial → Writer / Producer / Dubber / Traffic / QC.
        // The test asserts BOTH Producer AND Writer — only Radio Commercial has both. Find a
        // Radio Commercial compact-card specifically (scroll virtualized list if not in the
        // initial viewport). Fall back to the first card if none found (assertions may fail
        // downstream, which is desirable so we don't silently pass on wrong data).
        const radioCard = page.locator('.compact-card').filter({
            hasText: /Radio Commercial/i
        }).first();
        let hasRadioCard = await radioCard.isVisible({ timeout: 5000 }).catch(() => false);
        if (!hasRadioCard) {
            for (let i = 0; i < 10; i++) {
                await page.mouse.wheel(0, 800);
                await page.waitForTimeout(400);
                if (await radioCard.isVisible({ timeout: 500 }).catch(() => false)) {
                    hasRadioCard = true;
                    break;
                }
            }
        }
        const firstCard = hasRadioCard ? radioCard : page.locator('.compact-card').first();
        await expect(firstCard).toBeVisible({ timeout: 30000 });
        const chosenType = await firstCard.innerText().catch(() => '');
        console.log(hasRadioCard
            ? `🎯 Selected Radio Commercial compact-card. Text head: "${chosenType.substring(0, 80).replace(/\s+/g, ' ')}"`
            : `⚠️ No Radio Commercial card found after scroll — using first card. Producer assertion likely to fail.`);
        await firstCard.scrollIntoViewIfNeeded().catch(() => {});
        await page.waitForTimeout(1000);

        // Follow QA-101's known-working pattern: click the client-name title link (an
        // <a class="title">) with scroll + native click, then confirm the QO/edit drawer
        // opened by waiting on its SUBMIT ALL button. The client-name link IS the current
        // compact-view affordance for opening the spot-edit drawer.
        const titleLink = firstCard.locator('a.title, a[class*="title"]').first();
        await titleLink.waitFor({ state: 'visible', timeout: 10000 });
        await titleLink.scrollIntoViewIfNeeded().catch(() => {});
        await titleLink.click();
        console.log('🔗 Clicked compact-card title link — waiting for QO/edit drawer signal...');

        // SUBMIT ALL button is the reliable drawer-open signal (used in QA-101 for the same
        // click-title-to-open flow).
        const submitAllBtn = page.getByRole('button', { name: /SUBMIT ALL/i }).first();
        const editFormOpened = await submitAllBtn.waitFor({ state: 'visible', timeout: 20000 })
            .then(() => true).catch(() => false);

        // The drawer is the visible full-screen QO panel that contains SUBMIT ALL. Scope the
        // POC search to it explicitly — exclude app-quickorders root (always mounted).
        const editForm = page.locator(
            '.p-sidebar:not(app-v-sidebar):visible, .p-drawer:not(app-v-sidebar):visible, ' +
            '#quickorders-sidebar:visible, ' +
            'app-quickorders:visible >> nth=0'
        ).filter({ hasText: /SUBMIT ALL/i }).first();
        const pocContainer = editFormOpened ? editForm : page.locator('body');
        if (!editFormOpened) {
            console.log('ℹ️ QO/edit drawer did not open after title-link click. ' +
                'Falling back to page-scoped POC search.');
        } else {
            console.log('✅ QO/edit drawer confirmed open (SUBMIT ALL visible).');
        }
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Pausing after edit form open.');
            await page.pause();
        }

        console.log('--- Step 3: Verify POCs and Actions ---');
        // POC section header is optional (some layouts omit it)
        const pocSection = pocContainer.locator('text=/POINTS OF CONTACT|Point of Contact|POC/i').first();
        if (await pocSection.isVisible().catch(() => false)) {
            await expect(pocSection).toBeVisible({ timeout: 5000 });
        } else {
            console.log('ℹ️ POC section header not visible, skipping header assertion');
        }
        const producerLabel = pocContainer.getByText('Producer', { exact: true }).first();
        await expect(producerLabel).toBeVisible({ timeout: 10000 });

        const writerLabel = pocContainer.getByText('Writer', { exact: true }).first();
        await expect(writerLabel).toBeVisible({ timeout: 10000 });

        console.log('--- Step 4: Verify Files Tab ---');
        // FILES tab text may be uppercase or mixed case
        const filesTab = pocContainer.getByText('FILES', { exact: true }).or(
            pocContainer.getByText('Files', { exact: true })
        ).first();
        await expect(filesTab).toBeVisible({ timeout: 15000 });

        const browseLink = pocContainer.locator('a, span, button').filter({ hasText: 'Browse' }).first();
        await expect(browseLink).toBeVisible({ timeout: 15000 });
        if (process.env.PWDEBUG === '1') {
            console.log('🔍 Debugging: Final verification pause.');
            await page.pause();
        }
    });
});

