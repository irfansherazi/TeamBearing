import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Saved Searches', () => {
  test('should create and access saved search folder with client filter', async ({ page }) => {
    await page.goto('/');
    
    await getLocator(page, 'search-open-btn').click();
    await expect(getLocator(page, 'search-open-btn')).toBeVisible();
    
    await page.getByRole('textbox', { name: /client/i }).fill('They Beta Boys');
    
    await getLocator(page, 'search-execute-btn').click();
    await page.waitForLoadState('networkidle');
    
    await expect(page.getByText(/search results/i)).toBeVisible();
    
    await getLocator(page, 'search-save-btn').click();
    await expect(getLocator(page, 'search-folder-name-input')).toBeVisible();
    
    await getLocator(page, 'search-folder-name-input').fill('They Beta Boys Search');
    
    await getLocator(page, 'search-save-confirm-btn').click();
    await page.waitForLoadState('networkidle');
    
    await expect(page.getByText('They Beta Boys Search')).toBeVisible();
    
    await page.getByText('They Beta Boys Search').click();
    await page.waitForLoadState('networkidle');
    
    await expect(page.getByRole('textbox').filter({ hasText: 'They Beta Boys' })).toBeVisible();
    
    const cogIcon = page.getByRole('button', { name: /settings/i }).or(page.locator('[data-testid*="cog"]')).or(page.locator('.fa-cog')).first();
    if (await cogIcon.isVisible()) {
      await cogIcon.click();
      await expect(page.getByText(/share/i)).toBeVisible();
    }
  });
});