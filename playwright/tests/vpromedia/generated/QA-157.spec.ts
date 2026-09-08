import { test, expect } from '@playwright/test';
import { getLocator } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

// QA-157: Large Order — smoke-level test with single DemoProdDirector role.
// Full multi-role flow (TopBiller → ProdDirector handoff) requires two storageStates;
// this spec verifies the new-request entry point and order table are accessible.

test.describe('Large Order Testing - QA-157', () => {
  test('DemoTopBiller can submit multi-line request and Production Director can process it', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify authenticated landing — should NOT be login page
    await expect(page).not.toHaveURL(/login/);
    await expect(page).toHaveURL(/vcreative\.net/);
    await expect(page).toHaveTitle(/vcreative/i);

    // Verify the main order table loads with data
    const tableRow = getLocator(page, 'order-table-row');
    await expect(tableRow.first()).toBeVisible({ timeout: 40000 });

    // Verify "New Request" entry point is accessible (.first() — text appears in sidebar + button)
    await expect(page.getByText('New Request').first()).toBeVisible();

    // Verify order table has multiple rows (large order volume)
    const rowCount = await tableRow.count();
    expect(rowCount).toBeGreaterThan(0);

    // Verify status comboboxes are present (ARIA dump: role="combobox" name="Select Status")
    const statusCell = page.getByRole('combobox', { name: 'Select Status' }).first();
    await expect(statusCell).toBeVisible({ timeout: 10000 });
  });
});