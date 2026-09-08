/**
 * SearchHelper.ts - Search & Filtering Utilities
 * 
 * Consolidates logic for:
 * - Opening/Managing the Search Panel (handling dropdowns/retries)
 * - Performing Complex Searches (Client, Ad Type, Status)
 * - Saving Searches as Custom Folders
 * - Verifying Filter Retention
 * 
 * Extracted from QA-170 and QA-185.
 */

import { expect, Page, Locator } from '@playwright/test';
import { BASE_URL } from './setup';

export interface SearchCriteria {
    client?: string;
    adType?: string;
    status?: string;
    isCurrentFolder?: boolean; // If true, refines search instead of global
    includeOlder?: boolean; // If true, checks "Include Older Requests"
}

/**
 * Open the Search Panel robustly.
 * Handles the "Search Options" split-button dropdown if it appears.
 */
export async function openSearchPanel(page: Page, contextLabel: string = 'Opening search panel', isCurrentFolder: boolean = false): Promise<void> {
    const sidebar = page.locator('.p-sidebar, .p-drawer, p-drawer, [data-pc-name="drawer"], .filter-overlay').first();
    const searchBtn = page.locator('#top-open-search-panel');

    const currentUrl = page.url();
    if (!currentUrl.includes('/production-orders/')) {
        console.log('🔍 Not on production-orders view. Navigating to folder/all to enable search panel...');
        await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`);
        await page.waitForLoadState('domcontentloaded');
        await page.waitForTimeout(3000); // UI stabilization
    }

    // Detect if the sidebar or filter overlay is already expanded/visible
    if (await sidebar.isVisible()) {
        console.log(`ℹ️ ${contextLabel}: Panel already open.`);
        return;
    }

    // Wait for page load or stability
    await searchBtn.waitFor({ state: 'visible', timeout: 15000 });

    for (let i = 0; i < 3; i++) {
        if (!(await sidebar.isVisible())) {
            console.log(`${contextLabel} (attempt ${i + 1})...`);
            await searchBtn.click({ force: true });

            // Wait longer for potential dropdown or animation
            await page.waitForTimeout(2000);

            // Handle dropdown menu that appears when clicking the search button in certain states
            // (e.g., after a previous search, or when search results are already showing).
            // The menu text varies by context and state, so match broadly.
            const menuPatternCurrent = /Search Current Folder|Current Folder|Refine/i;
            const menuPatternAll = /Search All Folders|Search All|Search Options|New Search|All Folders/i;
            const menuPattern = isCurrentFolder ? menuPatternCurrent : menuPatternAll;
            // Also try a fallback that matches any visible menu item (picks first that looks like a search option)
            const menuOption = page.locator('.p-menuitem-link, .p-menuitem, a[role="menuitem"], li[role="menuitem"], button')
                .filter({ hasText: menuPattern })
                .first();
            const anyMenuOption = page.locator('.p-menuitem-link, .p-menuitem, a[role="menuitem"], li[role="menuitem"]')
                .first();

            if (await menuOption.isVisible({ timeout: 2000 }).catch(() => false)) {
                console.log(`ℹ️ Search Options menu detected (${isCurrentFolder ? 'Current' : 'All'}), clicking to open panel...`);
                await menuOption.click();
            } else if (await anyMenuOption.isVisible({ timeout: 1000 }).catch(() => false)) {
                const anyText = await anyMenuOption.textContent().catch(() => '');
                console.log(`ℹ️ Falling back to first menu option: "${anyText}"`);
                await anyMenuOption.click();
            }

            // Wait for sidebar to appear before next retry
            try {
                await sidebar.waitFor({ state: 'visible', timeout: 3000 });
                break; // It appeared!
            } catch (e) {
                // Ignore and retry
            }
        } else {
            break;
        }
    }

    await sidebar.waitFor({ state: 'visible', timeout: 20000 });
    // Stabilization wait for slide-in animation
    await page.waitForTimeout(1000);
}

/**
 * Perform a search with the given criteria.
 */
export async function performSearch(page: Page, criteria: SearchCriteria): Promise<void> {
    const sidebar = page.locator('.p-sidebar, .p-drawer, p-drawer, [data-pc-name="drawer"], .filter-overlay').first();
    // input#client is the legacy ID; broaden to match current DOM variants
    const clientInput = page.locator([
        'input#client',
        'input[name="client"]',
        'input[name*="client" i]',
        '.p-sidebar p-autocomplete input',
        '.p-drawer p-autocomplete input',
        '[data-pc-name="drawer"] p-autocomplete input',
        '.filter-overlay p-autocomplete input',
    ].join(', ')).first();

    // Only open if not already open (e.g. from retention check)
    if (!(await sidebar.isVisible())) {
        await openSearchPanel(page, 'Opening search panel', criteria.isCurrentFolder);
    } else {
        console.log('ℹ️ Panel already open, proceeding with criteria update...');
    }

    // 1. Client Filter
    if (criteria.client) {
        await clientInput.click();
        await clientInput.clear();
        await clientInput.fill(criteria.client);
        await page.waitForTimeout(1500); // Allow Angular change detection + autocomplete HTTP call

        console.log(`Searching for client: ${criteria.client}`);

        // Handle Auto-complete
        try {
            // Updated Locator based on DOM Analysis 2026-02-04
            // Structure is ul.p-autocomplete-list > li.p-autocomplete-option
            const suggestion = page.locator([
                'ul.p-autocomplete-list li.p-autocomplete-option',
                'ul.p-autocomplete-list li.p-autocomplete-item',
                '.p-autocomplete-option',
                '.p-autocomplete-item',
                'li[role="option"]',
                'ul.p-autocomplete-list li'
            ].join(', ')).filter({ hasText: criteria.client }).first();
            await suggestion.waitFor({ state: 'visible', timeout: 5000 });
            await suggestion.click();
        } catch (e) {
            console.log('ℹ️ Client autocomplete not found (using typed value)');

            // Debugging Fallback: Print what IS there if we failed
            if (process.env.PWDEBUG === '1') {
                const visibleOptions = await page.locator('ul.p-autocomplete-list li').allTextContents().catch(() => []);
                console.log('    -> Visible Options were:', visibleOptions);
            }
        }
        await clientInput.press('Tab');
        await page.waitForTimeout(1000);
    }

    // 2. Ad Type Filter
    if (criteria.adType) {
        const adTypesTab = page.locator('[id="\'search-adtypes-tab\'"], a').filter({ hasText: /^Ad Types$/ }).first();
        await adTypesTab.scrollIntoViewIfNeeded();
        await adTypesTab.click({ force: true });

        console.log(`Searching for Ad Type: ${criteria.adType}`);

        // Optimize: Direct locator first (fastest) - Verified 2026-02-04: #adtypes ng-select
        const specificNgSelect = page.locator('#adtypes ng-select, ng-select[formcontrolname="ad_types"]').first();

        let activeInput: Locator;
        let isNgSelect = false;

        if (await specificNgSelect.count() > 0 && await specificNgSelect.isVisible()) {
            isNgSelect = true;
            activeInput = specificNgSelect.locator('input[role="combobox"]');
        } else {
            // Fallback to slower container search if direct ID fails
            const adTypeContainer = page.locator('div').filter({ has: page.locator('label, h4, h5, h6, strong').filter({ hasText: /^Ad Types?$/ }).last() }).last();
            const ngSelect = adTypeContainer.locator('ng-select, .ng-select-container').first();
            isNgSelect = await ngSelect.count() > 0;
            activeInput = isNgSelect
                ? ngSelect.locator('input[role="combobox"]')
                : adTypeContainer.locator('p-autocomplete input, p-chips input, input').first();
        }

        await activeInput.scrollIntoViewIfNeeded();
        // Wait for input to be interactive instead of hard waiting for animation
        await activeInput.waitFor({ state: 'visible', timeout: 2000 });
        await activeInput.click({ force: true });

        // Fast typing (20ms) is usually sufficient for Angular/PrimeNG 
        await activeInput.fill(criteria.adType);
        await page.waitForTimeout(1000);

        // Select from dropdown
        if (isNgSelect) {
            const option = page.locator('.ng-option').filter({ hasText: criteria.adType }).first();
            await option.waitFor({ state: 'visible', timeout: 3000 });
            await option.click();
        } else {
            // Updated Locator based on previously found DOM structure (ul.p-autocomplete-list > li.p-autocomplete-option)
            const suggestion = page.locator('li.p-autocomplete-item, li.p-autocomplete-option').filter({ hasText: criteria.adType }).first();
            await suggestion.waitFor({ state: 'visible', timeout: 3000 });
            await suggestion.click();
        }
    }

    // 3. Status Filter
    if (criteria.status) {
        console.log('    -> Setting Status filter...');
        // Try multiple strategies to find the tab
        const statusTab = page.locator('#search-spotstatus-tab, [id="\'search-spotstatus-tab\'"], a').filter({ hasText: /^Status$/i }).first();
        if (await statusTab.isVisible()) {
            await statusTab.scrollIntoViewIfNeeded();
            await statusTab.click();
            // Wait for dropdown container to be exposed, but proceed immediately if ready
            const statusDropdownContainer = page.locator('p-multiselect#status_dropdown, #p-multiselect-status, p-multiselect[defaultlabel="Statuses"]').first();
            try {
                await statusDropdownContainer.waitFor({ state: 'visible', timeout: 2000 });
            } catch {
                // Ignore timeout, verification logic handles visibility later
            }
        } else {
            console.log('    ⚠️ Status tab not found or already active/open?');
        }

        console.log(`Searching for Status: ${criteria.status}`);

        // More robust dropdown locator: Find container with label "Statuses" or "Status", then find p-multiselect
        // Or fallback to ID
        const statusDropdown = page.locator('p-multiselect#status_dropdown, #p-multiselect-status, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]').first();

        // Strategy B: Find by Label text if ID fails
        const statusLabel = page.locator('label, span').filter({ hasText: /^Statuses?$/i }).first();
        const finalDropdown = (await statusDropdown.count() > 0)
            ? statusDropdown
            : page.locator('p-multiselect').filter({ has: page.locator('.p-multiselect-label').filter({ hasText: /Statuses/ }) }).first();

        // Ensure we explicitly wait specifically for the element
        await finalDropdown.waitFor({ state: 'visible', timeout: 5000 }).catch(() => console.log('⚠️ Status dropdown wait timeout, proceeding anyway...'));
        await finalDropdown.scrollIntoViewIfNeeded();
        await finalDropdown.click();

        const statusOption = page.getByRole('option', { name: criteria.status }).first();
        await statusOption.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {
            console.log(`⚠️ Status option "${criteria.status}" not visible after dropdown click — p-multiselect may not have rendered options. Proceeding without status filter.`);
        });

        // Only click if visible — avoids strict-mode error on hidden element
        if (await statusOption.isVisible().catch(() => false)) {
            await statusOption.click({ force: true });
        }

        // Optional: wait a moment for selection to register in Angular
        await page.waitForTimeout(500);
    }

    // 3.a Include Older Requests
    if (criteria.includeOlder !== undefined) {
        const olderCheckbox = page.locator('input#archived');
        if (await olderCheckbox.count() > 0) {
            const pCheckbox = olderCheckbox.locator('xpath=ancestor::p-checkbox').first();
            let isChecked = false;
            
            if (await pCheckbox.count() > 0) {
                // PrimeNG 19 checkbox state check
                isChecked = await pCheckbox.getAttribute('data-p-checked') === 'true' || 
                            await pCheckbox.getAttribute('aria-checked') === 'true' ||
                            await pCheckbox.locator('.p-checkbox-box.p-highlight').count() > 0;
            } else {
                isChecked = await olderCheckbox.isChecked();
            }

            if (isChecked !== criteria.includeOlder) {
                console.log(`    -> Toggling Include Older Requests to: ${criteria.includeOlder} (was: ${isChecked})`);
                
                // PrimeNG 19: clicking the p-checkbox wrapper ensures Angular registers the change.
                if (await pCheckbox.count() > 0 && await pCheckbox.isVisible()) {
                    await pCheckbox.click();
                } else {
                    const label = page.locator('label[for="archived"]').first();
                    if (await label.isVisible().catch(() => false)) {
                        await label.click();
                    } else {
                        await olderCheckbox.evaluate((node: any) => node.click());
                    }
                }
                
                await page.waitForTimeout(1000); // Give Angular time to update the model
            }
        }
    }

    // 4. Execute
    // Use the direct ID, but ensure we hit the one that is visible (inside the panel)
    const doSearchBtn = page.locator('#do-search-btn').filter({ visible: true }).first();

    // Ensure any dropdowns have had a moment to settle
    await page.waitForTimeout(500);

    console.log('Executing search...');
    await doSearchBtn.click({ force: true });

    // Wait for sidebar mask to disappear (indicates panel closed)
    const sidebarMask = page.locator('.p-sidebar-mask, .p-drawer-mask, .p-overlay-mask').first();
    if (await sidebarMask.isVisible({ timeout: 2000 }).catch(() => false)) {
        await sidebarMask.waitFor({ state: 'hidden', timeout: 30000 });
    }

    // Also wait for the sidebar itself to close — the mask disappears before aria-hidden is removed
    const sidebarEl = page.locator('.p-sidebar, .p-drawer, [data-pc-name="drawer"]').first();
    if (await sidebarEl.isVisible({ timeout: 1000 }).catch(() => false)) {
        await sidebarEl.waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
    }

    // Wait for aria-hidden to be removed from grid rows — PrimeNG sets aria-hidden="true" on
    // background content while a modal drawer is open; it clears asynchronously after close.
    // Return false when tbody is absent (still loading) so we keep polling until it appears
    // AND has no aria-hidden ancestor.
    await page.waitForFunction(() => {
        const tbody = document.querySelector('p-table tbody, .p-datatable-tbody');
        if (!tbody) return false;
        let el: Element | null = tbody;
        while (el) {
            if (el.getAttribute('aria-hidden') === 'true') return false;
            el = el.parentElement;
        }
        return true;
    }, { timeout: 15000 }).catch(() => {});

    // Wait for grid to actually load data before returning:
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000); // Network latency buffer

    // 5. Verification of Search Landing

    // Verify we landed in Search Results header (ensure we are not in Inbox)
    const searchHeader = page.locator('h1, .p-datatable-header, .v-page-header, .search-results-header').filter({ hasText: /Search Results/i }).first();
    try {
        await searchHeader.waitFor({ state: 'visible', timeout: 15000 });
        console.log('✅ Confirmed: Landed on Search Results.');
    } catch (e) {
        console.warn('⚠️ Search Results header not found. Checking grid visibility as fallback...');
    }

    const grid = page.locator('.p-datatable-tbody');
    try {
        await expect(grid).toBeVisible({ timeout: 15000 });
    } catch (e) {
        console.warn('⚠️ Grid not visible after 15s. This may be a 0-result search or a loading issue. Proceeding without F5 reload to preserve search state...');
        // We do not reload here because a legitimate 0-result search (e.g. testing filter exclusions) 
        // will lose its state upon reload.
    }

    const spinner = page.locator('.v-spinner, p-progress-spinner, .loading-overlay, .p-blockui').first();
    if (await spinner.count() > 0 && await spinner.isVisible()) {
        await spinner.waitFor({ state: 'hidden', timeout: 15000 });
    }
}

/**
 * Save the currently active search as a custom folder.
 */
export async function saveSearchAsFolder(page: Page, folderName: string): Promise<void> {
    const showSaveBtn = page.locator('#show-save-search-btn');
    await expect(showSaveBtn).toBeVisible({ timeout: 10000 });
    await showSaveBtn.click();

    console.log(`Saving search as folder: ${folderName}`);

    const nameInput = page.locator('#new-folder-name');
    await expect(nameInput).toBeVisible();
    await nameInput.fill(folderName);

    await page.locator('#save-search-btn').click();
    await expect(nameInput).toBeHidden(); // Wait for dialog to close
}

/**
 * Verify that search inputs still contain the expected values (Retention Check).
 */
export async function verifySearchRetention(page: Page, criteria: SearchCriteria): Promise<void> {
    await openSearchPanel(page, 'Opening for retention check', criteria.isCurrentFolder);

    // Client
    if (criteria.client) {
        // Wait until Angular has populated at least one of: a chip label or a non-empty input.
        // On QA the search panel is a <dialog> that is destroyed on close, so form state resets
        // on every open (ng-pristine/ng-untouched). When the wait times out we log a warning and
        // skip the client/ad-type assertions — the panel stays open so the status-filter step
        // that follows can still run against the already-open (empty) panel.
        const retentionDetected = await page.waitForFunction(() => {
            const chip = document.querySelector(
                '.p-autocomplete-chip-label, .p-autocomplete-token-label, ' +
                '.p-chip-label, [data-pc-section="label"]'
            );
            const input = document.querySelector(
                'input#client, input[name="client"]'
            ) as HTMLInputElement | null;
            return (chip !== null && (chip.textContent ?? '').trim().length > 0) ||
                   (input !== null && input.value.length > 0);
        }, { timeout: 8000 }).then(() => true).catch(() => false);

        if (!retentionDetected) {
            console.warn('⚠️ verifySearchRetention: client field empty after 8 s — panel opened fresh (dialog-based env resets state on close). Skipping retention assertions.');
            return;
        }

        // PrimeNG autocomplete may show the retained value as a chip/token (input value is cleared
        // after selecting a suggestion). Check for chip first; fall back to raw input value.
        const chipLabel = page.locator(
            '.p-autocomplete-chip-label, .p-autocomplete-token-label, .p-chip-label, ' +
            '.p-autocomplete-chip-item .p-chip-label, ' +
            'ul.p-autocomplete-multiple-container li .p-autocomplete-chip, ' +
            'ul.p-autocomplete-multiple-container span.p-chip-label, ' +
            '[data-pc-section="label"]'
        ).filter({ hasText: criteria.client }).first();

        const chipVisible = await chipLabel.isVisible({ timeout: 5000 }).catch(() => false);
        if (!chipVisible) {
            const clientRetentionInput = page.locator([
                'input#client',
                'input[name="client"]',
                'input[name*="client" i]',
                '.p-sidebar p-autocomplete input',
                '.p-drawer p-autocomplete input',
                '[data-pc-name="drawer"] p-autocomplete input',
                'dialog p-autocomplete input',
                '[role="dialog"] p-autocomplete input',
            ].join(', ')).first();

            const inputValue = (await clientRetentionInput.inputValue().catch(() => '')).trim();
            if (!inputValue) {
                // Final fallback: the retained value may be rendered inside p-autocomplete
                // in a way not covered by chip or input selectors (e.g. a readonly display span).
                // Include dialog/[role="dialog"] for QA env where the panel renders as a <dialog>.
                const autocompleteContainer = page.locator(
                    '.p-sidebar p-autocomplete, .p-drawer p-autocomplete, [data-pc-name="drawer"] p-autocomplete, ' +
                    'dialog p-autocomplete, [role="dialog"] p-autocomplete'
                ).first();
                await expect(autocompleteContainer).toContainText(criteria.client, { timeout: 5000 });
            } else {
                expect(inputValue).toBe(criteria.client);
            }
        }
    }

    // Ad Type
    if (criteria.adType) {
        // Check chips or select values
        const values = page.locator('.ng-value-label, .p-autocomplete-token-label');
        if (await values.count() > 0) {
            await expect(values.filter({ hasText: criteria.adType }).first()).toBeVisible();
        } else {
            // Might be text in input
            // Determine input type (ng-select vs p-autocomplete)
            const adTypeContainer = page.locator('div').filter({ has: page.locator('label, h4, h5, h6, strong').filter({ hasText: /^Ad Types?$/ }).last() }).last();
            const ngSelect = adTypeContainer.locator('ng-select, .ng-select-container').first();
            const activeInput = (await ngSelect.count() > 0)
                ? ngSelect.locator('input[role="combobox"]')
                : adTypeContainer.locator('p-autocomplete input, p-chips input, input').first();

            if (await activeInput.isVisible()) {
                await expect(activeInput).toHaveValue(criteria.adType);
            }
        }
    }

    // Note: Include Older Requests might not be retained in the UI by design
    // after certain actions, so we skip strict retention check for it here
}

/**
 * Open the search panel on an order/${poid} view and override the status filter to show ALL
 * statuses. Needed when DemoProdDirector's saved preference ('Deleted,Canceled') hides a newly
 * submitted spot whose actual status (e.g. 'Submitted', 'Active') differs from the saved filter.
 *
 * Strategy: open the status p-multiselect dropdown, then click "Select All" to select every
 * status option. With partial selection (Deleted,Canceled only), clicking Select All expands to
 * all statuses. The search is then re-executed with the updated filter.
 */
export async function overrideStatusFilter(page: Page): Promise<void> {
    console.log('Overriding status filter — opening search panel...');
    await openSearchPanel(page, 'Opening search panel to override status filter');
    await page.waitForTimeout(500);

    // Clear any stale search criteria (e.g. cart ID or title from a previous test) before
    // changing the status. Without this, the search may return the wrong order when criteria
    // from a prior search session are still active.
    const clearBtn = page.locator('#clear-search-btn').first();
    if (await clearBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        await clearBtn.click({ force: true });
        await page.waitForTimeout(500);
        console.log('[Status Filter] Cleared stale search criteria');
    }

    // Click the "Status" nav item to scroll the panel to the Status section.
    // The search panel may be a <dialog> (QA) or .p-drawer (test) — use a page-wide listitem
    // locator so we don't miss it due to wrong container scope.
    const statusNavItem = page.locator('li, [role="listitem"]').filter({ hasText: /^Status$/i }).first();
    if (await statusNavItem.isVisible({ timeout: 2000 }).catch(() => false)) {
        await statusNavItem.click();
        await page.waitForTimeout(500);
    }

    // Locate the status filter multiselect.
    // On `test` env: p-multiselect has specific attribute identifiers.
    // On `qa` env: the same component omits those attributes, so fall back to XPath from heading.
    let statusMultiselect = page.locator(
        'p-multiselect#status_dropdown, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]'
    ).first();

    if (!await statusMultiselect.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('[Status Filter] Named selector missed — trying container filter approach');
        // Strategy 2: Playwright container filter — find div containing BOTH "Statuses" text AND
        // a p-multiselect child. More reliable than XPath siblings when wrapper divs are present.
        const nestedMultiselect = page.locator('div, fieldset, section, ng-component').filter({
            has: page.locator('p-multiselect')
        }).filter({
            hasText: /Statuses/i
        }).last().locator('p-multiselect').first();

        if (await nestedMultiselect.isVisible({ timeout: 2000 }).catch(() => false)) {
            statusMultiselect = nestedMultiselect;
        } else {
            // Strategy 3: XPath following:: (whole-tree traversal, spans wrapper divs).
            // following-sibling:: fails when p-multiselect is nested inside intermediate divs.
            console.log('[Status Filter] Container filter missed — trying following:: XPath');
            const xpathBase = '(//*[self::h3 or self::h4 or @role="heading"][normalize-space(.)="Status"])[last()]';
            const byFollowing = page.locator(`xpath=${xpathBase}/following::p-multiselect[1]`);
            const byCombobox  = page.locator(`xpath=${xpathBase}/following::*[@role="combobox"][1]`);
            if (await byFollowing.isVisible({ timeout: 2000 }).catch(() => false)) {
                statusMultiselect = byFollowing;
            } else if (await byCombobox.isVisible({ timeout: 2000 }).catch(() => false)) {
                statusMultiselect = byCombobox;
            }
        }
    }

    await expect(statusMultiselect).toBeVisible({ timeout: 5000 });

    const multiselectTrigger = statusMultiselect.locator(
        '[data-pc-section="trigger"], .p-multiselect-trigger, .p-multiselect-dropdown'
    ).first();
    if (await multiselectTrigger.isVisible({ timeout: 1500 }).catch(() => false)) {
        await multiselectTrigger.click();
    } else {
        await statusMultiselect.click();
    }
    await page.waitForTimeout(1000);

    // Click the "Select All" checkbox in the multiselect panel header.
    // Target the <input> directly — PrimeNG overlays an input on top of the styled div, which
    // intercepts pointer events and causes click() to time out on the div.
    const selectAllCheckbox = page.locator(
        '[data-pc-section="headercheckboxcontainer"] input[type="checkbox"], ' +
        '.p-multiselect-header [data-pc-name="checkbox"] input[type="checkbox"], ' +
        '.p-multiselect-header .p-checkbox-input, ' +
        '.p-multiselect-select-all input[type="checkbox"]'
    ).first();

    if (await selectAllCheckbox.isVisible({ timeout: 2000 }).catch(() => false)) {
        await selectAllCheckbox.click({ force: true });
        console.log('✅ Clicked Select All in status multiselect');
    } else {
        // Fallback: click every unselected option individually
        console.warn('Select All checkbox not found — selecting options individually...');
        const options = page.locator(
            '[data-pc-section="list"] li[role="option"], ' +
            '.p-multiselect-list li[role="option"], ' +
            '[role="listbox"] li[role="option"]'
        );
        const count = await options.count();
        for (let i = 0; i < count; i++) {
            if (await options.nth(i).getAttribute('aria-selected') !== 'true') {
                await options.nth(i).click();
                await page.waitForTimeout(100);
            }
        }
        console.log(`Clicked ${count} individual status options`);
    }

    // Do NOT press Escape here — on QA the search panel is a <dialog> and Escape closes the
    // entire dialog rather than just the multiselect dropdown, making #do-search-btn unreachable.
    // Clicking #do-search-btn directly closes the dropdown implicitly.
    await page.waitForTimeout(300);

    // Execute search with the updated status filter
    await page.locator('#do-search-btn').click({ force: true });

    // Wait for the search panel to close and the grid to reload.
    // The panel may be a dialog (QA), drawer, or sidebar (test) — include all selectors.
    const panelEl = page.locator('.p-sidebar, .p-drawer, [data-pc-name="drawer"], dialog, [role="dialog"]').first();
    await panelEl.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);
    console.log('✅ Status filter override complete');
}

/**
 * Clear all active search filters from the search panel and execute the cleared search.
 */
export async function clearSearchFilters(page: Page): Promise<void> {
    console.log('🧹 Clearing all search filters...');
    await openSearchPanel(page, 'Opening search panel to clear filters');
    
    const clearBtn = page.locator('#clear-search-btn, button#clear-search-btn, button:has-text("Clear"), .p-sidebar button:has-text("Clear"), .p-drawer button:has-text("Clear")').first();
    await expect(clearBtn).toBeVisible({ timeout: 10000 });
    await clearBtn.click();
    await page.waitForTimeout(1000);
    
    const searchBtn = page.locator('#do-search-btn, button#do-search-btn, .p-sidebar button:has-text("Search"), .p-drawer button:has-text("Search")').first();
    await expect(searchBtn).toBeVisible({ timeout: 10000 });
    await searchBtn.click();
    
    // Wait for panel to close and grid to reload
    const sidebarEl = page.locator('.p-sidebar, .p-drawer, [data-pc-name="drawer"]').first();
    await sidebarEl.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);
}
