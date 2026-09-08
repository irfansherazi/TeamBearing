/**
 * NavHelper.ts - Navigation Utilities for Playwright Tests
 * 
 * Provides reusable functions for sidebar navigation and spot access.
 * Part of the Phase 1 "Lego Brick" helpers for the 2026 automation plan.
 */

import { expect, Page, Locator } from '@playwright/test';
import { BASE_URL } from './setup';

/**
 * Navigate to a folder by clicking its sidebar link.
 * Handles both system folders (All, Inbox) and custom/saved search folders.
 * 
 * @param page - Playwright Page object
 * @param folderName - Display name of the folder (e.g., "All", "Inbox", "My Custom Search")
 * @param options - Optional configuration
 * @returns The extracted count from the folder badge, or null if not present
 */
export async function goToFolder(
    page: Page,
    folderName: string,
    options: { timeout?: number; waitForRows?: boolean } = {}
): Promise<number | null> {
    const { timeout = 30000, waitForRows = true } = options;

    // Locate folder link in sidebar - handle both system folders (href pattern) and custom folders (text match)
    let folderSelector: Locator;

    // System folders use predictable href patterns
    const systemFolderMap: Record<string, string> = {
        'all': 'folder/all',
        'inbox': 'folder/inbox',
        'mybox': 'folder/my_box',
        'drafts': 'folder/draft',
        'archived': 'folder/archived',
    };

    const normalizedName = folderName.toLowerCase();
    if (systemFolderMap[normalizedName]) {
        // Unanchored regex: match the folder name anywhere in the link text
        // to handle icons, badges, and nested spans in Angular 19 sidebar.
        folderSelector = page.locator('.layout-menu a').filter({
            hasText: new RegExp(folderName, 'i')
        }).first();
    } else {
        // Custom folders - match by visible text
        folderSelector = page.locator('a').filter({ hasText: folderName }).last();
    }

    // Fallback to searching by part of href if text match fails
    if (await folderSelector.count() === 0 && systemFolderMap[normalizedName]) {
        // Try href-based locator first, then getByRole as final fallback
        const hrefLocator = page.locator(`a[href*="${systemFolderMap[normalizedName]}"]`).first();
        if (await hrefLocator.count() > 0) {
            folderSelector = hrefLocator;
        } else {
            // Angular 19 may use (click) bindings without href — use role-based lookup
            folderSelector = page.getByRole('link', { name: new RegExp(folderName, 'i') }).first();
        }
    }

    await folderSelector.waitFor({ state: 'visible', timeout });
    await expect(folderSelector).toBeVisible({ timeout });

    // Extract badge count if present
    let badgeCount: number | null = null;
    const folderText = await folderSelector.textContent();
    const countMatch = folderText?.match(/\((\d+)\)/);
    if (countMatch) {
        badgeCount = parseInt(countMatch[1], 10);
    }

    // Click the folder — fall back to dispatchEvent if an overlay intercepts
    try {
        await folderSelector.click({ timeout: 5000 });
    } catch {
        console.log(`⚠️ Sidebar click intercepted — dispatching click directly on "${folderName}" link...`);
        await folderSelector.dispatchEvent('click');
    }

    // Wait for content to load
    if (waitForRows) {
        const tableRows = page.locator('p-table tbody tr, .p-datatable-tbody tr');
        await tableRows.first().waitFor({ state: 'visible', timeout }).catch(() => {
            console.log(`ℹ️ No rows visible after navigating to folder "${folderName}"`);
        });
    }

    return badgeCount;
}

/**
 * Open a spot's detail view by navigating directly to its edit URL.
 * 
 * @param page - Playwright Page object
 * @param spotId - The Production Order ID (POID) or spot identifier
 * @param options - Optional configuration
 */
export async function openSpot(
    page: Page,
    spotId: string,
    options: { timeout?: number } = {}
): Promise<void> {
    const { timeout = 30000 } = options;

    // Navigate to the spot using the standard edit URL pattern
    const editUrl = `${BASE_URL}?edit=${spotId}`;
    console.log(`🚀 Opening spot: ${editUrl}`);
    await page.goto(editUrl, { timeout });

    // Wait for the spot panel to be visible
    const spotPanel = page.locator('#qo-form-panel, .spot-detail, .po-detail').first();
    await spotPanel.waitFor({ state: 'visible', timeout }).catch(() => {
        console.warn(`⚠️ Spot panel not immediately visible for ID: ${spotId}`);
    });
}

/**
 * Get the total count from the folder header dropdown.
 * Useful for verifying folder counts match sidebar badges.
 * 
 * @param page - Playwright Page object
 * @returns The count from the header, or null if not extractable
 */
export async function getHeaderCount(page: Page, timeout: number = 15000): Promise<number | null> {
    const dropdownTrigger = page.locator('span#user-filter-header-drop-down');

    try {
        await dropdownTrigger.waitFor({ state: 'visible', timeout });
        let textContent = await dropdownTrigger.textContent();
        
        // WORKAROUND: PrimeNG 19 reactivity bug where label gets stuck at All (...)
        // Clicking the dropdown forces Angular change detection to update the label text
        if (textContent && textContent.includes('(...)')) {
            await dropdownTrigger.click();
            await page.waitForTimeout(500);
            await page.keyboard.press('Escape');
            await page.waitForTimeout(500);
            textContent = await dropdownTrigger.textContent();
        }

        const match = textContent?.match(/\((\d+)\)/);
        return match ? parseInt(match[1], 10) : null;
    } catch {
        return null;
    }
}

/**
 * Wait for the header count to update to match an expected value.
 * Handles stale header states where WebKit is slow to refresh after a folder click.
 *
 * @param page - Playwright Page object
 * @param expectedCount - The count the header should update to
 * @param timeout - Max wait time in ms (default 30000)
 * @returns The final header count, or null if it never matched
 */
export async function waitForHeaderCount(
    page: Page,
    expectedCount: number,
    timeout: number = 30000
): Promise<number | null> {
    let headerCount: number | null = null;
    try {
        await expect(async () => {
            headerCount = await getHeaderCount(page);
            if (headerCount === null) throw new Error('Header count not yet loaded');
            expect(headerCount).toBe(expectedCount);
        }).toPass({ timeout });
    } catch {
        // Return whatever we ended up with
        headerCount = await getHeaderCount(page);
    }
    return headerCount;
}

/**
 * Scroll through the sidebar to find a folder, useful for accounts with many custom folders.
 * 
 * @param page - Playwright Page object
 * @param folderName - Name of the folder to find
 * @param maxScrolls - Maximum number of scroll attempts
 * @returns True if folder was found, false otherwise
 */
export async function scrollToFolder(
    page: Page,
    folderName: string,
    maxScrolls: number = 40 // Increased default
): Promise<boolean> {
    const sidebar = page.locator('.layout-menu');
    // More robust selector matching QA-185/298 patterns
    const folderSelector = page.getByRole('link', { name: new RegExp(folderName, 'i') }).first();
    // Fallback if role lookup fails
    const fallbackSelector = page.locator('a[href*="folder/"]').filter({ hasText: folderName }).first();

    // Try finding it immediately
    if (await folderSelector.isVisible()) return true;

    console.log(`Searching for folder: ${folderName} in sidebar...`);

    for (let i = 0; i < maxScrolls; i++) {
        // Check existence (attached) before visibility
        if (await folderSelector.count() > 0 || await fallbackSelector.count() > 0) {
            const target = (await folderSelector.count() > 0) ? folderSelector : fallbackSelector;

            // Force scroll into view
            await target.evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
            await page.waitForTimeout(500); // Allow render

            if (await target.isVisible()) return true;
        }

        // Scroll the container
        await sidebar.evaluate(el => el.scrollTop += 600);
        await page.waitForTimeout(400);

        const isAtBottom = await sidebar.evaluate(el => (el.scrollTop + el.clientHeight) >= el.scrollHeight - 10);
        if (isAtBottom && i > 5) {
            console.log(' reached bottom of sidebar.');
            break;
        }
    }

    return (await folderSelector.isVisible() || await fallbackSelector.isVisible());
}

/**
 * Ensure a System Folder (e.g. "All") is visible in the sidebar.
 * If not, it opens Settings > Filter Options and enables it.
 * 
 * Based on QA-298 logic.
 */
export async function ensureSystemFolder(page: Page, folderName: string): Promise<void> {
    const folderHrefMap: Record<string, string> = {
        'All': 'folder/all',
        'Inbox': 'folder/inbox',
        'MyBox': 'folder/my_box',
        'New': 'folder/new'
    };

    const href = folderHrefMap[folderName];
    // Check if valid check is possible
    if (!href) return;

    // Quick check
    const folderLink = page.locator(`a[href*="${href}"]`).first();
    try {
        await folderLink.waitFor({ state: 'visible', timeout: 5000 });
        return; // It's there!
    } catch {
        console.log(`⚠️ System folder "${folderName}" not visible. Enabling via Settings...`);
    }

    let reloadNeeded = false;

    // Open Settings
    const settingsBtn = page.locator('button#settings-btn').first();
    await settingsBtn.waitFor({ state: 'visible', timeout: 45000 });
    await settingsBtn.click();

    const settingsMenuOption = page.locator('a[title="View folder settings"], .p-menuitem-link, [role="menuitem"]').filter({ hasText: /^Settings$/ }).first();
    await settingsMenuOption.waitFor({ state: 'visible', timeout: 20000 });
    await settingsMenuOption.click();

    const modal = page.locator('#filterOptions, .p-sidebar, .p-drawer').filter({ hasText: /Filter Options/i }).last();
    await modal.waitFor({ state: 'visible', timeout: 30000 });

    // Enable the folder
    const row = modal.locator('.cdk-drag, tr, .p-datatable-row').filter({ hasText: new RegExp(`^\\s*${folderName}\\s*$`) }).first();
    if (await row.count() > 0) {
        await row.scrollIntoViewIfNeeded();
        // Index 1 = "Show In Nav" in Filter Options
        const navCheckbox = row.locator('input[type="checkbox"]').nth(1);
        
        if (!(await navCheckbox.isChecked())) {
            console.log(`Checking box to enable "${folderName}" for Navigation...`);
            await navCheckbox.check();
            await navCheckbox.blur();
            reloadNeeded = true;
            // PrimeNG/vPro needs a moment to persist the preference
            await page.waitForTimeout(2500);
        }
    }

    // Close Modal — must be fully dismissed before proceeding
    const closeBtn = modal.locator('#closeIcon, .p-drawer-close, button.p-dialog-header-close, .pi-times, [aria-label="Close"]').first();
    if (await closeBtn.isVisible()) {
        await closeBtn.click();
    }
    // Wait for the drawer/modal to be fully hidden
    await modal.waitFor({ state: 'hidden', timeout: 10000 }).catch(async () => {
        // Fallback: press Escape to force-close any lingering overlay
        console.warn('⚠️ Filter Options modal did not close via button. Pressing Escape...');
        await page.keyboard.press('Escape');
        await modal.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => { });
    });
    // Brief pause for any close animation to complete
    await page.waitForTimeout(500);

    await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`, { waitUntil: 'domcontentloaded' }); // Safely rehydrate sidebar without breaking SW cache
    await folderLink.waitFor({ state: 'attached', timeout: 60000 }).catch(() => {
        console.warn(`⚠️ The "${folderName}" link did not attach within 60s after settings reload.`);
    });
}

