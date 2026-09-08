import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Folder Spot Count Verification', () => {
  test('folder count equals visible spot count in Needs Prod folders', async ({ page }) => {
    await page.goto('/spots');
    
    await expect(getLocator(page, 'page-spinner')).not.toBeVisible();
    
    const needsProdFolder = page.getByText('Needs Prod').first();
    await expect(needsProdFolder).toBeVisible();
    
    const folderCountText = await needsProdFolder.textContent();
    const countMatch = folderCountText?.match(/\((\d+)\)/);
    const displayedCount = countMatch ? parseInt(countMatch[1]) : 0;
    
    await needsProdFolder.click();
    await expect(getLocator(page, 'page-spinner')).not.toBeVisible();
    
    const spotRows = page.locator('[data-testid="spot-row"], .spot-item, .spot-list-item').filter({ hasText: /\w/ });
    await expect(spotRows.first()).toBeVisible({ timeout: 10000 });
    
    const actualSpotCount = await spotRows.count();
    
    expect(actualSpotCount).toBe(displayedCount);
    
    const customNeedsProdFolder = page.getByText(/Needs Prod.*Custom/i).first();
    if (await customNeedsProdFolder.isVisible()) {
      const customFolderText = await customNeedsProdFolder.textContent();
      const customCountMatch = customFolderText?.match(/\((\d+)\)/);
      const customDisplayedCount = customCountMatch ? parseInt(customCountMatch[1]) : 0;
      
      await customNeedsProdFolder.click();
      await expect(getLocator(page, 'page-spinner')).not.toBeVisible();
      
      const customSpotRows = page.locator('[data-testid="spot-row"], .spot-item, .spot-list-item').filter({ hasText: /\w/ });
      await expect(customSpotRows.first()).toBeVisible({ timeout: 10000 });
      
      const customActualCount = await customSpotRows.count();
      expect(customActualCount).toBe(customDisplayedCount);
    }
  });
});