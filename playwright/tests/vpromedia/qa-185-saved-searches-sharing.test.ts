import { test, expect, BASE_URL } from '../../utils/setup';
import * as SearchHelper from '../../utils/SearchHelper';
import * as NavHelper from '../../utils/NavHelper';
import * as ViewHelper from '../../utils/ViewHelper';

test.describe('QA-185: Saved Search Sharing', () => {
    test.describe.configure({ mode: 'serial' });

    const SHARED_FOLDER_NAME = `QA-185-S-${Date.now().toString().slice(-4)}`;
    const OWNER_USER = 'DemoProdDirector';
    const RECIPIENT_USER = 'DemoSalesExec';
    const RECIPIENT_NAME_IN_DROPDOWN = 'Demo Sales Executive';

    test.describe('Owner Actions - Create & Share', () => {
        test.use({ user: OWNER_USER });

        test('Step 1: Create and Share Folder', async ({ page }) => {
            // Match the recipient test's budget (240s). QA network latency + the multi-step
            // sequence (search → save → reload → scroll → open settings → find row → share modal)
            // routinely burned the prior 120s budget before reaching the share confirmation.
            test.setTimeout(240000);
            // 1. Login and Create Folder
            await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`);
            await expect(page.locator('.layout-menu')).toBeVisible();

            // Force list view before searching so the results container is a predictable
            // .p-datatable-tbody. DemoProdDirector defaults to Compact view, which renders
            // results as .compact-card elements that the prior union selector missed —
            // leaving the toBeVisible() waiting on selectors that never materialized.
            await ViewHelper.ensureListView(page);

            // Perform Search & Save
            await SearchHelper.performSearch(page, { client: 'The' });

            // Wait for search results OR an explicit empty-results indicator. The wait was
            // flaky on QA — sometimes the search panel closes but the datatable takes
            // longer to re-hydrate than 30s allows, and none of the listed selectors match.
            // Two hardening changes:
            // 1. Treat an explicit empty-state row (.p-datatable-emptymessage) as a valid
            //    "search completed" signal so the saveSearchAsFolder path proceeds anyway
            //    (a filter yielding zero rows is still a saveable search).
            // 2. If neither results NOR empty-state appear within 30s, retry the search
            //    once (network flakes on QA occasionally lose the search POST).
            const resultsSelector =
                '.p-datatable-tbody tr:not(.p-datatable-emptymessage):visible, ' +
                '.compact-card:visible, .po-card:visible, p-card:visible, .p-card:visible';
            const emptyStateSelector = '.p-datatable-emptymessage:visible, ' +
                '[data-pc-section="emptymessage"]:visible, ' +
                '.p-datatable tbody tr.p-datatable-emptymessage';
            const resultsContainer = page.locator(resultsSelector).first();
            const emptyState = page.locator(emptyStateSelector).first();

            const raceForCompletion = async (timeout: number) => {
                return Promise.race([
                    resultsContainer.waitFor({ state: 'visible', timeout }).then(() => 'results' as const),
                    emptyState.waitFor({ state: 'visible', timeout }).then(() => 'empty' as const),
                ]).catch(() => null as null);
            };

            let outcome = await raceForCompletion(30000);
            if (outcome === null) {
                console.log('⚠️ Search results/empty-state neither visible after 30s. ' +
                    'Retrying performSearch once — network flake suspected.');
                await SearchHelper.performSearch(page, { client: 'The' });
                outcome = await raceForCompletion(30000);
            }
            if (outcome === null) {
                throw new Error('Search did not produce results or empty-state after two attempts');
            }
            console.log(`✅ Search completed. Outcome: ${outcome}.`);

            // Save Search
            await SearchHelper.saveSearchAsFolder(page, SHARED_FOLDER_NAME);

            // Try to find the newly-created folder without a full reload first — a reload on
            // QA costs ~10-15s. Only fall back to reload if the sidebar hasn't refreshed yet.
            await page.waitForTimeout(2000); // Allow server-side save + sidebar update
            let found = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);
            if (!found) {
                console.log('ℹ️ Folder not visible in sidebar after save — falling back to reload.');
                await page.reload({ waitUntil: 'domcontentloaded' });
                found = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);
            }

            if (!found) {
                console.log('Warning: Folder not found via scroll helper. Checking Settings...');
            } else {
                await expect(page.getByRole('link', { name: new RegExp(SHARED_FOLDER_NAME, 'i') }).first()).toBeVisible();
            }

            // 2. Open Settings and Share
            const settingsModal = await ViewHelper.openSettings(page, 'Settings');

            // Handle Virtualization: Scroll to bottom to ensure new folder is loaded
            const drawerContent = settingsModal.locator('.p-drawer-content, .p-sidebar-content').first();
            if (await drawerContent.isVisible()) {
                await drawerContent.evaluate(el => el.scrollTop = el.scrollHeight);
                await page.waitForTimeout(500); // Virtualization renders quickly; 500ms is sufficient
            }

            // Find Folder Row using robust JS evaluation (from qa-298)
            let folderRowIndex = -1;
            try {
                folderRowIndex = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            } catch (e) {
                console.log(`⚠️ evaluate call failed: ${e}. Retrying after wait...`);
                await page.waitForTimeout(2000);
                folderRowIndex = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            }

            expect(folderRowIndex).not.toBe(-1);

            const row = settingsModal.locator('.cdk-drag, tr, .p-datatable-row, li').nth(folderRowIndex);
            await row.scrollIntoViewIfNeeded();
            await expect(row).toBeVisible();


            // Click Share Icon
            const shareBtn = row.locator('button[id*="share-custom-folder-btn"], i.pi-share-alt, i[title="Share Filter"], .fa-share-square, .vpro-icon-share').first();
            await expect(shareBtn).toBeVisible();
            await shareBtn.click();

            // Debug: Inside Share Modal
            if (process.env.PWDEBUG) await page.pause();

            // 3. Share with Recipient
            const shareModal = page.locator('div[role="dialog"]').filter({ hasText: 'Share Filter' }).last();
            await expect(shareModal).toBeVisible({ timeout: 10000 });

            // Interact with Dropdown
            const userDropdown = shareModal.locator('p-select, p-dropdown, .p-multiselect').first();
            await userDropdown.click();

            // Filter for User (Use fill for Angular trigger)
            const filterInput = page.locator('.p-select-filter, .p-dropdown-filter, .p-multiselect-filter');
            await filterInput.fill(RECIPIENT_NAME_IN_DROPDOWN);
            await page.waitForTimeout(2000); // Allow filter to complete with network latency

            // Select User
            const userOption = page.locator('li[role="option"], li.p-select-option, li.p-dropdown-item, li.p-multiselect-item').filter({ hasText: RECIPIENT_NAME_IN_DROPDOWN }).first();
            await expect(userOption).toBeVisible();
            await userOption.click();

            // Confirm Share
            const confirmShareBtn = shareModal.locator('button').filter({ hasText: /^Share$/ }).first();
            await confirmShareBtn.click();

            // Verify Share Modal closed
            await expect(shareModal).toBeHidden();

            // Close Settings
            await settingsModal.locator('#closeIcon, .p-sidebar-close, button[aria-label="Close"], .p-drawer-close').click();

            // Debug: After sharing complete
            if (process.env.PWDEBUG) await page.pause();
        });
    });

    test.describe('Recipient Actions - Verify & Hide', () => {
        test.use({ user: RECIPIENT_USER });

        test('Step 2: Verify and Hide Folder', async ({ page }) => {
            test.setTimeout(240000); // Was 120000 — needs more time with network latency
            await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`);

            // 1. Verify Folder Exists in Sidebar (Robust Scroll & Retry)
            const found = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);

            if (found) {
                await expect(page.getByRole('link', { name: new RegExp(SHARED_FOLDER_NAME, 'i') }).first()).toBeVisible();
                console.log('Recipient sees the shared folder.');
            } else {
                console.log('Warning: Folder not found after scrolling. Attempting Reload...');
                await page.reload({ waitUntil: 'domcontentloaded' });
                const retryFound = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);
                if (retryFound) {
                    console.log('Recipient sees the shared folder after reload.');
                } else {
                    console.warn('Folder definitely not visible in sidebar. Proceeding to Settings check as final verification.');
                }
            }


            // 2. Hide/Delete the folder (Recipient Action)
            // Open Settings
            const settingsModal = await ViewHelper.openSettings(page, 'Settings');


            // Handle Virtualization
            const drawerContent = settingsModal.locator('.p-drawer-content, .p-sidebar-content').first();
            if (await drawerContent.isVisible()) {
                await drawerContent.evaluate(el => el.scrollTop = el.scrollHeight);
                await page.waitForTimeout(1000);
            }

            // Find Folder Row using robust JS evaluation
            let folderRowIndex2 = -1;
            try {
                folderRowIndex2 = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            } catch (e) {
                console.log(`⚠️ evaluate call failed: ${e}. Retrying after wait...`);
                await page.waitForTimeout(2000);
                folderRowIndex2 = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            }

            expect(folderRowIndex2).not.toBe(-1);

            const row = settingsModal.locator('.cdk-drag, tr, .p-datatable-row, li').nth(folderRowIndex2);
            await row.scrollIntoViewIfNeeded();

            // Recipient clicks "Delete" (Trash icon)
            const deleteBtn = row.locator('i.pi-trash, i[title="delete"], button .pi-trash, .fa-trash').first();
            await deleteBtn.click();

            // Verify row is gone (or marked as hidden)
            // Wait for potential removal or change
            await page.waitForTimeout(1000);

            await settingsModal.locator('#closeIcon, .p-sidebar-close, .p-drawer-close').click();

            // Verify gone from Sidebar
            const folderLink = page.getByRole('link', { name: new RegExp(SHARED_FOLDER_NAME, 'i') });
            await expect(folderLink).toBeHidden();
            console.log('Recipient successfully hid/deleted the shared folder.');
        });
    });

    test.describe('Owner Actions - Cleanup', () => {
        test.use({ user: OWNER_USER });

        test('Step 3: Verify Persistence and Cleanup', async ({ page }) => {
            test.setTimeout(180000); // Increased: reload-with-wait can take 30-40s on QA
            await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`);

            // Wait for the layout menu (sidebar) to fully initialize before searching
            // for the custom folder. domcontentloaded fires before the sidebar's folder list
            // is populated from the server — scrollToFolder was called against an empty sidebar.
            await page.waitForSelector('.layout-menu', { timeout: 45000 });
            await page.waitForTimeout(3000); // Allow sidebar folder list to hydrate from API

            // 1. Verify Folder STILL Exists for Owner - Robust Scroll (with reload fallback)
            let found = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);

            if (!found) {
                // Sidebar may not have fetched the custom folder list yet — force a full reload
                // with longer wait to give the Angular app time to fetch saved searches.
                console.log('⚠️ Folder not found on first attempt — reloading with extended wait...');
                await page.reload({ waitUntil: 'domcontentloaded' });
                await page.waitForSelector('.layout-menu', { timeout: 45000 });
                await page.waitForTimeout(5000); // Give sidebar extra time after reload
                found = await NavHelper.scrollToFolder(page, SHARED_FOLDER_NAME);
            }

            if (found) {
                await expect(page.getByRole('link', { name: new RegExp(SHARED_FOLDER_NAME, 'i') }).first()).toBeVisible();
                console.log('Owner still sees the folder (Independence Verified).');
            } else {
                throw new Error('Owner could not find folder in sidebar. Independence check failed.');
            }


            // 2. Cleanup
            const settingsModal = await ViewHelper.openSettings(page, 'Settings');


            // Handle Virtualization
            const drawerContent = settingsModal.locator('.p-drawer-content, .p-sidebar-content').first();
            if (await drawerContent.isVisible()) {
                await drawerContent.evaluate(el => el.scrollTop = el.scrollHeight);
                await page.waitForTimeout(1000);
            }

            // Find Folder Row using robust JS evaluation
            let folderRowIndex3 = -1;
            try {
                folderRowIndex3 = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            } catch (e) {
                console.log(`⚠️ evaluate call failed: ${e}. Retrying after wait...`);
                await page.waitForTimeout(2000);
                folderRowIndex3 = await settingsModal.evaluate((modalEl, folderName) => {
                    const rows = Array.from(modalEl.querySelectorAll('.cdk-drag, tr, .p-datatable-row, li'));
                    return rows.findIndex(row => {
                        const input = row.querySelector('input');
                        return input && (input as HTMLInputElement).value === folderName;
                    });
                }, SHARED_FOLDER_NAME);
            }

            expect(folderRowIndex3).not.toBe(-1);

            const row = settingsModal.locator('.cdk-drag, tr, .p-datatable-row, li').nth(folderRowIndex3);
            await row.scrollIntoViewIfNeeded();

            // Delete Real Folder
            const deleteBtn = row.locator('i.pi-trash, i[title="delete"], button .pi-trash, .fa-trash').first();
            await deleteBtn.click();

            await settingsModal.locator('#closeIcon, .p-sidebar-close, .p-drawer-close').click();
        });
    });
});
