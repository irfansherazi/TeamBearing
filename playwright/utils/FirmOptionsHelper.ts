/**
 * FirmOptionsHelper.ts - Firm Settings Navigation and Verification
 * 
 * Provides robust utilities for navigating HDash Firm settings and verifying/updating options.
 * Part of the Phase 1 "Lego Brick" helpers for the 2026 automation plan.
 */

import { expect, Page } from '@playwright/test';
import { BASE_URL, STORAGE_DIR } from './setup';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Navigate to HDash > Firms for a specific firm.
 * Uses breadcrumbs and search for reliability.
 */
export async function navigateToFirmSettings(
    page: Page,
    firmName: string = 'Demo Broadcasting'
): Promise<void> {
    console.log(`🚀 Navigating to Firm Settings for: ${firmName}`);

    // Debug Pause
    if (process.env.PWDEBUG === '1') { await page.pause(); }

    // Step 1: Navigate to Firms list
    // Use the deep-link URL provided by the user for reliability on QA
    const firmsUrl = `${BASE_URL}/#/hdash/hdash-firms?user=629640`;

    // Settling delay: Ensure the dashboard is fully ready before deep-linking
    console.log('⏳ Letting session settle before navigation...');
    await page.waitForTimeout(2000);

    console.log(`🚀 Navigating directly to Firms page: ${firmsUrl}`);

    await page.goto(firmsUrl, { waitUntil: 'load' });
    // Final verification of header and URL
    console.log('🔍 Verifying Firms page load content...');
    const firmsHeading = page.locator('h1, h5, .page-header, .p-panel-header').filter({ hasText: /Firms/i }).first();
    await expect(firmsHeading).toBeVisible({ timeout: 15000 });
    await expect(page).toHaveURL(/firms/, { timeout: 15000 });
    await page.waitForLoadState('load');

    // Step 2: Search for the firm with a deliberate pace to allow filter to settle
    console.log(`🔍 Searching for firm: ${firmName}`);

    const searchInput = page.locator('.sidebarView input[placeholder="Search"], input[placeholder="Search"]').first();
    await searchInput.click();
    await searchInput.clear();
    await searchInput.fill(firmName);
    await page.waitForTimeout(1500);

    // Debug Pause
    if (process.env.PWDEBUG === '1') { await page.pause(); }

    // Step 3: Click the matching result in the sidebar/search list if visible
    const sidebarResult = page.locator('.search-list li, .search-item, .sidebarView .p-listbox-item').filter({ hasText: firmName }).first();
    if (await sidebarResult.isVisible()) {
        console.log(`✨ Selecting "${firmName}" from search results...`);
        await sidebarResult.click();
        await page.waitForTimeout(1000);
    }

    // Step 4: Click the Edit pencil icon in the table row
    const tableRow = page.locator('tr.p-datatable-row, tr').filter({ hasText: firmName }).first();
    // Target the button specifically, or the icon within it (SVG on QA, pi-pencil elsewhere)
    const editIcon = tableRow.locator('button .pi-pencil, .pi-pencil, img[src*="edit-icon"], [alt*="Edit"], [icon*="pencil"]').first();

    console.log(`✨ Clicking Edit for "${firmName}"...`);
    await editIcon.waitFor({ state: 'visible', timeout: 5000 });
    await editIcon.click({ force: true });

    // Step 5: Verify arrival at details (brief pause for transition)
    await page.waitForTimeout(1000);
    console.log(`✅ Navigation to ${firmName} details initiated.`);
}

/**
     * Access a specific tab in the Firm Options sidebar.
     * 
     * @param page - Playwright Page object
     * @param tabName - The exact or partial name of the tab (e.g., "vProMedia Firm Fields 2")
     */
export async function goToFirmOptionsTab(
    page: Page,
    tabName: string
): Promise<void> {
    console.log(`📂 Selecting Firm Options tab: ${tabName}`);

    // The tabs are in a vertical sidebar list (Modern PrimeNG 19 uses p-tab)
    const tab = page.locator('p-tab, .side-nav-item, li').filter({ hasText: new RegExp(`^${tabName}$`, 'i') }).first();

    // Fallback search if exact match fails
    const fallbackTab = page.locator('p-tab, .side-nav-item, li').filter({ hasText: tabName }).first();

    if (await tab.isVisible()) {
        await tab.scrollIntoViewIfNeeded();
        await tab.click();
    } else {
        await fallbackTab.scrollIntoViewIfNeeded();
        await fallbackTab.click();
    }

}

/**
 * Check if the "Require client approval for AE's" setting is enabled in "vProMedia Firm Fields 2".
 * 
 * @param page - Playwright Page object
 * @returns boolean indicating if the requirement is enabled
 */
export async function isClientApprovalRequired(
    page: Page
): Promise<boolean> {
    console.log('🔍 Checking Client Approval requirement status...');

    // Solid locator using the stable ID discovered via browser inspection
    // Fallback-heavy locator for PrimeNG 19 compatibility
    const multiselect = page.locator('p-multiselect').filter({
        has: page.locator('input#_ppo_firm_fields2-ppo_restricted_options, input[id*="restricted_options"]')
    }).or(
        page.locator('div.input-wrap').filter({ has: page.locator('label').filter({ hasText: /Restricted Options/i }) }).locator('p-multiselect')
    ).or(
        page.locator('p-multiselect').filter({ has: page.locator('label').filter({ hasText: /Restricted Options/i }) })
    ).first();

    await expect(multiselect).toBeVisible({ timeout: 45000 });

    const label = multiselect.locator('.p-multiselect-label');
    const labelText = await label.innerText();

    return labelText.includes("Require client approval for AE's");
}

/**
 * Enable or disable the client approval requirement.
 * 
 * @param page - Playwright Page object
 * @param enable - true to enable, false to disable
 * @param saveAfter - whether to click SAVE after making the change (default: true)
 */
export async function setClientApprovalRequired(
    page: Page,
    enable: boolean,
    saveAfter: boolean = true
): Promise<void> {
    const currentState = await isClientApprovalRequired(page);

    if (currentState === enable) {
        console.log(`ℹ️ Client approval setting already ${enable ? 'enabled' : 'disabled'}`);
        return;
    }

    // ID-based locator for stability
    // Fallback-heavy locator for PrimeNG 19 compatibility
    const multiselect = page.locator('p-multiselect').filter({
        has: page.locator('input#_ppo_firm_fields2-ppo_restricted_options, input[id*="restricted_options"]')
    }).or(
        page.locator('div.input-wrap').filter({ has: page.locator('label').filter({ hasText: /Restricted Options/i }) }).locator('p-multiselect')
    ).or(
        page.locator('p-multiselect').filter({ has: page.locator('label').filter({ hasText: /Restricted Options/i }) })
    ).first();

    console.log('Opening Restricted Options multiselect...');
    await multiselect.click({ force: true });
    await page.waitForTimeout(2000);

    const option = page.locator('li[role="option"]').filter({ hasText: "Require client approval for AE's" }).first();
    await expect(option).toBeVisible({ timeout: 15000 });

    // Check if the option has a checkbox
    const checkbox = option.locator('.p-checkbox-box, input[type="checkbox"]').first();
    const classAttribute = await checkbox.getAttribute('class') || '';
    const isChecked = await checkbox.getAttribute('aria-checked') === 'true' || classAttribute.includes('p-highlight');

    if (isChecked !== enable) {
        console.log(`${enable ? 'Selecting' : 'Deselecting'} client approval option...`);
        await option.click({ force: true });
        await page.waitForTimeout(1000);
    }

    // Close dropdown
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1000);

    if (saveAfter) {
        const saveBtn = page.getByRole('button', { name: /SAVE/i }).first();
        await saveBtn.scrollIntoViewIfNeeded();
        console.log('Saving firm settings changes...');
        await saveBtn.click();

        // Wait for save completion
        const loader = page.locator('.loader-wrapper').first();
        await page.waitForTimeout(2000);
        if (await loader.isVisible()) {
            await loader.waitFor({ state: 'hidden', timeout: 60000 });
        }
        await page.waitForTimeout(2000);
    }
}

/**
 * Check if a firm setting is already cached as having the expected value.
 * Skip if the cache entry is less than 7 days old.
 */
export function checkFirmSettingCached(
    firmName: string,
    settingKeySuffix: string,
    expectedValue: any
): boolean {
    const cachePath = path.join(STORAGE_DIR, 'firm_settings_cache.json');
    const settingKey = `${firmName}_${settingKeySuffix}`;
    const sevenDaysInMs = 7 * 24 * 60 * 60 * 1000;

    if (!fs.existsSync(cachePath)) {
        // A missing cache file is a common source of confusion — it looks like the
        // caller's Admin pre-condition just "decided to run" when in fact the whole
        // skip-optimization couldn't even try. Surface loudly so future debugging
        // doesn't repeat the Family C investigation.
        console.warn(
            `⚠️ Firm settings cache missing at ${cachePath} — Admin pre-condition will not be skipped. ` +
            `If this env needs the same skip qa gets, create the file with the same shape as ` +
            `playwright/storage/qa/firm_settings_cache.json (sentinel timestamp 1800000000000 = year-2027 never-expire).`
        );
        return false;
    }

    try {
        const cache = JSON.parse(fs.readFileSync(cachePath, 'utf-8'));
        const entry = cache[settingKey];

        if (entry && entry.value === expectedValue) {
            const age = Date.now() - entry.timestamp;
            if (age < sevenDaysInMs) {
                console.log(`⚡ Optimization: Firm setting "${settingKey}" was verified ${Math.round(age / (1000 * 60 * 60))}h ago.`);
                return true;
            }
        }
    } catch (e) {
        console.warn('⚠️ Failed to read firm settings cache:', e);
    }
    return false;
}

/**
 * High-level wrapper to ensure the client approval setting is correctly set.
 * Includes caching to skip UI verification if validated within the last 7 days.
 */
export async function ensureClientApprovalSetting(
    page: Page,
    enable: boolean,
    firmName: string = 'Demo Broadcasting'
): Promise<void> {
    const settingKeySuffix = 'clientApprovalRequired';
    const cachePath = path.join(STORAGE_DIR, 'firm_settings_cache.json');
    const settingKey = `${firmName}_${settingKeySuffix}`;

    // Check cache first using the standalone utility
    if (checkFirmSettingCached(firmName, settingKeySuffix, enable)) {
        console.log(`⚡ Skipping UI verification for "${settingKey}".`);
        return;
    }

    // Perform UI verification
    await navigateToFirmSettings(page, firmName);
    await goToFirmOptionsTab(page, "vProMedia Firm Fields 2");
    await setClientApprovalRequired(page, enable, true);

    // Update cache
    try {
        let cache: any = {};
        if (fs.existsSync(cachePath)) {
            cache = JSON.parse(fs.readFileSync(cachePath, 'utf-8'));
        }
        cache[settingKey] = {
            value: enable,
            timestamp: Date.now(),
            date: new Date().toISOString()
        };
        fs.writeFileSync(cachePath, JSON.stringify(cache, null, 2));
        console.log(`💾 Updated firm settings cache for "${settingKey}"`);
    } catch (e) {
        console.warn('⚠️ Failed to update firm settings cache:', e);
    }
}
