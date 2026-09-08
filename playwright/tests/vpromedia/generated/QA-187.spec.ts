import { test, expect } from '@playwright/test';
import { getLocator } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

// QA-187: New Features Functionality Testing.
// Verifies the test/QA environment is accessible and core app sections load correctly.
// The env-specific URL assertion (qa.vcreative.net) is replaced with a generic check
// since the spec must run against any vCreative environment.

test.describe('QA-187: New Features Functionality Testing', () => {
  test('should access QA environment and verify new features are ready for testing', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify authenticated user lands in the app — NOT on login page
    await expect(page).not.toHaveURL(/login/);
    await expect(page).toHaveURL(/vcreative\.net/);
    await expect(page).toHaveTitle(/vcreative/i);

    // Verify main navigation sidebar is rendered using ARIA link roles.
    // ARIA dump: sidebar nav items are link "All (621)", link "MyBox (322)", etc.
    // getByText('All').first() resolves to a HIDDEN element — use role-based locators.
    await expect(page.getByRole('link', { name: /All \(\d+\)/ }).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('link', { name: 'MyBox' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'New Request' }).first()).toBeVisible();

    // Verify the order table has loaded with feature cards/orders
    const tableRow = getLocator(page, 'order-table-row');
    await expect(tableRow.first()).toBeVisible({ timeout: 40000 });

    // Verify the search and settings controls are accessible (new features entry points)
    const searchBtn = getLocator(page, 'search-open-btn');
    await expect(searchBtn).toBeVisible({ timeout: 10000 });

    // Verify status comboboxes are present (ARIA: role=combobox name="Select Status")
    // .pi-bell class does NOT exist in this app — ARIA dump confirms no such class.
    const statusCombo = page.getByRole('combobox', { name: 'Select Status' }).first();
    await expect(statusCombo).toBeVisible({ timeout: 10000 });

  });
});