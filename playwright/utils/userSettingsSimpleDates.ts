import { type Page, expect } from '@playwright/test';

/**
 * Ensures "Pop up calendar" is disabled for date fields, enabling simple text entry.
 * Navigates to User Profile > vPro tab > Site Options via the UI menu,
 * checks the setting, and navigates back to the Inbox.
 *
 * @param page - An already-authenticated Playwright Page instance
 * @param baseURL - Base URL for the environment
 */
export async function ensureSimpleDateEntry(page: Page, baseURL: string) {

    // ─── Navigate to User Profile via the top-right user menu ───
    // Direct URL navigation (goto / hash) triggers a persistent loading overlay
    // in the Angular SPA. UI-based navigation avoids this entirely.
    console.log('🔍 Navigating to User Profile via top-right menu...');

    const userName = page.locator('.user-text, .username, [class*="user-name"]').first();
    await userName.waitFor({ state: 'visible', timeout: 15000 });
    await userName.click();

    // Click "Edit Profile" from the dropdown
    const editProfile = page.getByText('Edit Profile');
    await editProfile.waitFor({ state: 'visible', timeout: 5000 });
    await editProfile.click();
    await page.waitForTimeout(3000);

    if (process.env.PWDEBUG) {
        await page.pause();
    }

    // 1. Ensure we are on the 'vPro' tab
    console.log('🔍 Navigating to vPro tab...');
    const vProBtn = page.getByRole('tab', { name: 'vPro' });
    await vProBtn.waitFor({ state: 'visible', timeout: 15000 });

    // Wait for potential animations and check if active
    const isSelected = await vProBtn.getAttribute('aria-selected') === 'true';
    if (!isSelected) {
        console.log('📝 Clicking vPro tab...');
        await vProBtn.click({ force: true }).catch(async () => {
            await vProBtn.evaluate(el => (el as HTMLElement).click());
        });
        await page.waitForTimeout(3000);
    }

    // 2. Click the 'Edit' button for 'Site Options'
    console.log('🔍 Looking for Site Options Edit button...');

    // Try multiple locator strategies for Angular 19 / PrimeNG 19 compatibility
    let siteOptionsEditButton = page.locator('section').filter({ hasText: 'Site Options' }).getByRole('button', { name: 'Edit' });

    // Fallback to original locator if section-based doesn't work
    if (await siteOptionsEditButton.count() === 0) {
        const siteOptionsHeader = page.locator('.settings__sub-header').filter({
            has: page.locator('h3', { hasText: 'Site Options' })
        });
        siteOptionsEditButton = siteOptionsHeader.getByRole('button', { name: 'Edit' });
    }

    try {
        await expect(siteOptionsEditButton).toBeVisible({ timeout: 15000 });
        console.log('✅ Found Site Options Edit button.');
        await siteOptionsEditButton.click();
        await page.waitForTimeout(1500);
    } catch (e) {
        console.log('❌ Could not find Site Options Edit button. Taking screenshot...');
        await page.screenshot({ path: 'site_options_fail.png', fullPage: true });
        throw e;
    }

    // 3. Open the 'PO Options' dropdown
    console.log('🔍 Opening PO Options dropdown...');

    let poOptionsContainer = page.locator('p-multiselect[name="card_Po Options"]');
    if (await poOptionsContainer.count() === 0) {
        poOptionsContainer = page.locator('p-multiselect').filter({ hasText: 'items selected' });
    }

    const poOptionsTrigger = poOptionsContainer.locator('.p-multiselect-trigger, .p-multiselect-dropdown, .p-multiselect-label').first();

    await poOptionsTrigger.waitFor({ state: 'visible', timeout: 10000 });
    await poOptionsTrigger.click({ force: true });
    await page.waitForTimeout(1500);

    if (process.env.PWDEBUG) {
        console.log('🔍 Debugging: Pausing after opening PO Options dropdown.');
        await page.pause();
    }

    // 4. Target the 'Pop up calendar' item
    console.log('🔍 Looking for Pop up calendar option...');

    let listItem = page.getByRole('option', { name: 'Pop up calendar' });
    if (await listItem.count() === 0) {
        listItem = page.locator('li[aria-label="Pop up calendar"]');
    }

    await listItem.waitFor({ state: 'visible', timeout: 5000 });

    // 5. Logic to disable ONLY if currently checked
    const isChecked = await listItem.getAttribute('aria-checked') === 'true' ||
        await listItem.getAttribute('aria-selected') === 'true';

    if (isChecked) {
        console.log('Pop up calendar is active. Disabling...');

        await listItem.click({ force: true });
        await page.waitForTimeout(500);

        // Close the dropdown
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);

        // Save
        console.log('🔍 Saving settings...');
        const saveButton = page.getByRole('button', { name: 'Save' });
        await saveButton.scrollIntoViewIfNeeded();
        await saveButton.waitFor({ state: 'visible' });
        await saveButton.click({ force: true });

        await page.waitForTimeout(2000);
        console.log('✅ Settings saved successfully.');
    } else {
        console.log('✅ Pop up calendar is already disabled. No action needed.');
        await page.keyboard.press('Escape');
    }

    // Navigate back to the root URL — this forces a full page reload so Angular reinitializes
    // and picks up the saved user settings. SPA hash-route navigation (clicking Inbox link)
    // does NOT reinitialize Angular services, so the new setting would be silently ignored.
    console.log('🔍 Returning to Inbox via full page reload...');
    await page.goto(baseURL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    console.log('✅ Returned to Inbox.');
}