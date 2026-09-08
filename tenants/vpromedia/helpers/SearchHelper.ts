/**
 * tenants/vpromedia/helpers/SearchHelper.ts
 * =========================================
 * Tenant-scoped pre-packaged autocomplete and guard routines for vProMedia search.
 */

import { expect, Page, Locator } from '@playwright/test';

export interface SearchCriteria {
  client?: string;
  adType?: string;
  status?: string;
  isCurrentFolder?: boolean;
  includeOlder?: boolean;
}

/**
 * Open the Search Panel robustly, handling animation slide-ins and overlays.
 */
export async function openSearchPanel(page: Page, contextLabel: string = 'Opening search panel', isCurrentFolder: boolean = false): Promise<void> {
  const sidebar = page.locator('.p-sidebar, .filter-overlay').first();
  const searchBtn = page.locator('#top-open-search-panel');
  const clientInput = page.locator('input#client');

  const isVisible = await sidebar.isVisible().catch(() => false);
  if (isVisible) {
    return;
  }

  await searchBtn.waitFor({ state: 'visible', timeout: 5000 });
  await searchBtn.click({ force: true });

  await clientInput.waitFor({ state: 'visible', timeout: 5000 });
  await page.waitForTimeout(500); // Animation stabilization
}

/**
 * Perform a search with the given client, adType, or status criteria.
 */
export async function performSearch(page: Page, criteria: SearchCriteria): Promise<void> {
  await openSearchPanel(page, 'Opening search panel', criteria.isCurrentFolder);

  // 1. Client Autocomplete Filter
  if (criteria.client) {
    const clientInput = page.locator('input#client');
    await clientInput.click();
    await clientInput.clear();
    await clientInput.pressSequentially(criteria.client, { delay: 50 });

    const suggestion = page.locator('ul.p-autocomplete-list li.p-autocomplete-option').filter({ hasText: criteria.client }).first();
    await suggestion.waitFor({ state: 'visible', timeout: 3000 });
    await suggestion.click();
  }

  // 2. Ad Type ng-select Filter
  if (criteria.adType) {
    const adTypesTab = page.locator('[id="\'search-adtypes-tab\'"], a').filter({ hasText: /^Ad Types$/ }).first();
    await adTypesTab.click({ force: true });

    const specificNgSelect = page.locator('#adtypes ng-select, ng-select[formcontrolname="ad_types"]').first();
    const activeInput = specificNgSelect.locator('input[role="combobox"]');

    await activeInput.waitFor({ state: 'visible', timeout: 2000 });
    await activeInput.click({ force: true });
    await activeInput.pressSequentially(criteria.adType, { delay: 20 });

    const option = page.locator('.ng-option').filter({ hasText: criteria.adType }).first();
    await option.waitFor({ state: 'visible', timeout: 2000 });
    await option.click();
  }

  // 3. Status Multiselect Filter
  if (criteria.status) {
    const statusTab = page.locator('#search-spotstatus-tab, [id="\'search-spotstatus-tab\'"], a').filter({ hasText: /^Status$/i }).first();
    await statusTab.click();

    const statusDropdown = page.locator('p-multiselect#status_dropdown, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]').first();
    await statusDropdown.waitFor({ state: 'visible', timeout: 2000 });
    await statusDropdown.click();

    const statusOption = page.getByRole('option', { name: criteria.status }).first();
    await statusOption.waitFor({ state: 'visible', timeout: 2000 });
    await statusOption.click({ force: true });
  }

  // Submit Search
  const doSearchBtn = page.locator('#do-search-btn').filter({ visible: true }).first();
  await doSearchBtn.click({ force: true });

  // Verification of Search Landing
  await expect(page.locator('.p-sidebar-mask')).toBeHidden({ timeout: 5000 });
}
