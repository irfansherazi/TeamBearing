import { Page, expect } from '@playwright/test';
import type { Browser } from '@playwright/test';
import { BASE_URL } from '../../utils/setup';
import * as path from 'path';

const TEST_ENV = process.env.TEST_ENV || 'test';

/**
 * Robustly searches for a client, handling potential View Filter states (Active vs Waiting Approval).
 * Returns the locator for the client row.
 */
/**
 * Robustly searches for a client, handling potential View Filter states (Active vs Waiting Approval).
 * Returns the locator for the client row.
 */
export async function searchForClient(page: Page, clientName: string) {
    // Wait for table to load at least one row (hydrate) before typing
    await page.locator('p-table tbody tr, .p-datatable-tbody tr').first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});

    const filter = page.locator('#global-filter-input');
    await expect(filter).toBeVisible();

    // Helper to perform search
    const performSearch = async () => {
        await filter.click();
        await filter.fill(clientName);
        await page.keyboard.press('Enter');
        await page.locator('tr.p-datatable-selectable-row, .p-datatable-tbody tr').first()
            .waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    };

    await performSearch();

    // Robust row locator compatible with PrimeNG 19
    // Verified: tr.p-datatable-selectable-row (PrimeNG 19)
    let clientRow = page.locator('tr.p-datatable-selectable-row, .p-datatable-tbody tr, p-table tbody tr').filter({ hasText: new RegExp(clientName, 'i') });

    // Verify client is found
    if (await clientRow.count() === 0) {
        console.warn(`Client "${clientName}" not found immediately. Waiting for potential grid update...`);
        // Retry search once
        await performSearch();
    }

    await expect(clientRow.first()).toBeVisible({ timeout: 5000 });
    return clientRow.first();
}

/**
 * Navigates to Client Settings, matches the client, and opens the Edit method.
 */
export async function openClientSettings(page: Page, clientName: string = "Bob's Burgers") {
    // Direct access to client settings for DemoProdDirector
    // Ensure we handle potential search params correctly if BASE_URL includes them (unlikely)
    await page.goto(`${BASE_URL}/#/settings/clients?user=600920`);

    // Wait for network idle or load
    await page.waitForLoadState('domcontentloaded');

    const clientRow = await searchForClient(page, clientName);

    // Configurable "Edit" button locator
    // Verified: i.fa-pencil (FontAwesome) inside the row
    const editButton = clientRow.locator('i.fa-pencil, i.pencil, i.pi-pencil, button .pi-pencil').first();
    await editButton.click();

    // Wait for the edit drawer to be fully open and loaded
    await page.locator('p-drawer, .p-drawer, .p-dialog').last().waitFor({ state: 'visible', timeout: 15000 });
}

export async function filePreWashUtility(page: Page) {
    const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);

    // Ensure we are in the correct session context if not already
    console.log(`[Pre-Wash] using storage: ${storageStatePath}`);

    // Navigate and Open Client — use exact name to avoid matching other "Burgers" clients
    await openClientSettings(page, "Bob's Burgers");

    // Scroll to Files section and wait for it to load
    const slideout = page.locator('.p-sidebar, .p-drawer, .p-dialog, .p-dynamic-dialog').last();

    // Scroll the drawer to the bottom to ensure the Files section (which may be below the fold) is visible
    await page.evaluate(() => {
        const content = document.querySelector('.p-drawer-content, .p-sidebar-content, .p-dialog-content');
        if (content) content.scrollTop = content.scrollHeight;
    });
    await page.waitForTimeout(500);

    // Check for delete buttons and clean up
    // The DOM shows "delete file" elements as generic/span with aria-label "delete file"
    // Also try FontAwesome / PrimeNG icon selectors as fallbacks
    const deleteLocatorStr = '[aria-label="delete file"], [title="delete file"], i.fa-times, button.p-fileupload-file-remove, i.pi-times';

    // Scope to the slideout; fall back to page-wide if not found
    const slideoutDeleteButtons = slideout.locator(deleteLocatorStr);
    const pageDeleteButtons = page.locator(deleteLocatorStr);
    const deleteButtons = slideoutDeleteButtons.or(pageDeleteButtons);

    // Wait slightly for load
    await page.waitForTimeout(1000);

    let count = await deleteButtons.count();
    console.log(`[Pre-Wash] Found ${count} files to delete.`);

    let attempts = 0;
    while (attempts < 20) {
        // Re-query to get fresh count
        const currentCount = await slideoutDeleteButtons.count() > 0
            ? await slideoutDeleteButtons.count()
            : await pageDeleteButtons.count();

        if (currentCount === 0) break;

        attempts++;
        // Use slideout-scoped buttons if available, else page-wide
        const activeBtns = await slideoutDeleteButtons.count() > 0 ? slideoutDeleteButtons : pageDeleteButtons;
        const btn = activeBtns.first();

        if (await btn.isVisible()) {
            await btn.scrollIntoViewIfNeeded();
            console.log('Clicking delete button...');
            await btn.click();

            // Handle logical "Yes/Delete" confirmation if it appears
            const confirmBtn = page.getByRole('button', { name: /YES, DELETE|YES|DELETE/i });
            try {
                if (await confirmBtn.isVisible({ timeout: 2000 })) {
                    console.log('Clicking confirmation...');
                    await confirmBtn.click();
                }
            } catch (ignored) { }

            await page.waitForTimeout(500); // Wait for list update
        } else {
            console.log('Delete button not visible, breaking loop.');
            break;
        }
    }

    console.log(`[Pre-Wash] Cleanup complete after ${attempts} attempt(s).`);
}

export async function runFilePreWash(browser: Browser) {
    const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);
    const context = await browser.newContext({ storageState: storageStatePath });
    const page = await context.newPage();
    await filePreWashUtility(page);
    await context.close();
}
