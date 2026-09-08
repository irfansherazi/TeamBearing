import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Compact View Configuration and Usage', () => {
  test('should enable Compact View at firm level and verify functionality', async ({ page }) => {
    await page.goto('/hdash');
    
    await page.getByText('Firms').click();
    await page.getByRole('button', { name: 'Edit' }).first().click();
    
    await expect(page.getByText('Production Order Views')).toBeVisible();
    await page.getByText('Production Order Views').click();
    
    const compactViewOption = page.getByText('Compact View');
    await expect(compactViewOption).toBeVisible();
    
    const compactViewCheckbox = page.getByRole('checkbox', { name: 'Compact View' });
    if (!(await compactViewCheckbox.isChecked())) {
      await compactViewCheckbox.click();
    }
    
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    
    await page.goto('/spots');
    
    const settingsCog = page.getByRole('button', { name: 'Settings' });
    await expect(settingsCog).toBeVisible();
    await settingsCog.click();
    
    const compactViewToggle = page.getByText('Compact View');
    await expect(compactViewToggle).toBeVisible();
    await compactViewToggle.click();
    
    await expect(page.locator('.compact-view')).toBeVisible();
    
    const firstCard = page.locator('.order-card').first();
    await expect(firstCard).toBeVisible();
    
    await firstCard.getByRole('button', { name: 'Approve' }).click();
    await expect(page.getByText('Approved')).toBeVisible();
    
    await firstCard.getByRole('button', { name: 'Add Comment' }).click();
    await page.getByRole('textbox', { name: 'Comment' }).fill('Passed - Compact View Test');
    await page.getByRole('button', { name: 'Submit' }).click();
    
    await expect(page.getByText('Passed - Compact View Test')).toBeVisible();
  });
});