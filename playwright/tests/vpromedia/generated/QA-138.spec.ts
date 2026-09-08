import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Admin Account Checks', () => {
  test('should verify admin functionality and HDash access', async ({ page }) => {
    await page.goto('/');
    
    await expect(page).toHaveURL(/.*vcreative\.net/);
    
    await page.goto('/hdash');
    
    await expect(getLocator(page, 'page-spinner')).not.toBeVisible({ timeout: 10000 });
    
    await expect(page.locator('text=Failed Logins')).toBeVisible();
    await expect(page.locator('text=Dashboard')).toBeVisible();
    
    const ghostingLink = page.getByRole('link', { name: /ghost/i });
    if (await ghostingLink.isVisible()) {
      await ghostingLink.click();
      await expect(page).toHaveURL(/.*ghost/);
      await page.goBack();
    }
    
    const userEditLink = page.getByRole('link', { name: /user/i }).first();
    if (await userEditLink.isVisible()) {
      await userEditLink.click();
      await expect(page.locator('input[type="text"]').first()).toBeVisible();
      await page.goBack();
    }
    
    const firmEditLink = page.getByRole('link', { name: /firm/i }).first();
    if (await firmEditLink.isVisible()) {
      await firmEditLink.click();
      await expect(page.locator('input[type="text"]').first()).toBeVisible();
      await page.goBack();
    }
    
    const stationEditLink = page.getByRole('link', { name: /station/i }).first();
    if (await stationEditLink.isVisible()) {
      await stationEditLink.click();
      await expect(page.locator('input[type="text"]').first()).toBeVisible();
      await page.goBack();
    }
    
    await expect(page.locator('text=Dashboard')).toBeVisible();
  });
});