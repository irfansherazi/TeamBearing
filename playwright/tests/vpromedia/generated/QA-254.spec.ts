import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Manual Archives - QA-254', () => {
  test('should manually archive spot status and persist after refresh', async ({ page }) => {
    await page.goto('/spots');
    
    await expect(getLocator(page, 'page-spinner')).not.toBeVisible();
    
    const statusDropdown = page.getByRole('combobox', { name: /status/i }).first();
    await expect(statusDropdown).toBeVisible();
    await statusDropdown.click();
    
    const archivedOption = page.getByRole('option', { name: 'Archived' });
    await expect(archivedOption).toBeVisible();
    await archivedOption.click();
    
    await expect(getLocator(page, 'success-toast')).toBeVisible();
    
    const spotStatusCell = page.getByText('Archived').first();
    await expect(spotStatusCell).toBeVisible();
    
    await page.reload();
    await expect(getLocator(page, 'page-spinner')).not.toBeVisible();
    
    await expect(page.getByText('Archived').first()).toBeVisible();
  });
});