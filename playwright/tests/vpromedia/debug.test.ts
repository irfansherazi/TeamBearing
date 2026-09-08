import { test, expect, BASE_URL } from '../../utils/setup';

test.describe('Debug Compact Card', () => {
    test.use({ user: 'DemoProdDirector' });

    test('Click card with offset and verify drawer opens', async ({ page }) => {
        const inboxUrl = `${BASE_URL.replace(/\/$/, '')}/#/vpro/production-orders/folder/inbox`;
        await page.goto(inboxUrl);
        await page.waitForSelector('#settings-btn', { timeout: 45000 });
        await page.waitForTimeout(2000);

        const settingsBtn = page.locator('#settings-btn');
        await expect(settingsBtn).toBeVisible({ timeout: 15000 });
        await settingsBtn.click();
        await page.waitForTimeout(1000);

        const compactOption = page.locator('#compact_listview, .p-menu-item-link, .p-menuitem-link').filter({ hasText: /^Compact$/i }).first();
        await expect(compactOption).toBeVisible({ timeout: 10000 });
        await compactOption.click();
        await page.waitForTimeout(3000);

        // Ensure compact card is visible
        const firstCard = page.locator('.compact-card').first();
        await firstCard.waitFor({ state: 'visible', timeout: 30000 });

        // Click card background (using top-left offset)
        console.log('Clicking compact card with offset {x:10, y:10}...');
        await firstCard.click({ position: { x: 10, y: 10 } });
        await page.waitForTimeout(4000);

        // Check if drawer is visible
        const editForm = page.locator('app-quickorders, .p-sidebar-active, .p-sidebar, .p-drawer, app-v-sidebar, #quickorders-sidebar').first();
        let isDrawerVisible = await editForm.isVisible();
        console.log(`Is edit form/drawer visible after offset click: ${isDrawerVisible}`);

        if (!isDrawerVisible) {
            console.log('Clicking spotCountNumber...');
            const spotCount = firstCard.locator('.spotCountNumber').first();
            await spotCount.click();
            await page.waitForTimeout(4000);
            isDrawerVisible = await editForm.isVisible();
            console.log(`Is edit form/drawer visible after spotCountNumber click: ${isDrawerVisible}`);
        }

        await expect(editForm).toBeVisible({ timeout: 10000 });
    });
});
