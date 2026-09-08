import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Revision Process', () => {
  test('should complete revision workflow from spot selection to filtered results', async ({ page }) => {
    await page.goto('/inbox');
    
    const spotCheckbox = page.getByRole('checkbox').first();
    await expect(spotCheckbox).toBeVisible();
    await spotCheckbox.click();
    
    const actionBar = page.locator('.action-bar, [data-testid="action-bar"]');
    await expect(actionBar).toBeVisible();
    
    const reviseButton = page.getByRole('button', { name: /revise/i });
    await expect(reviseButton).toBeVisible();
    await reviseButton.click();
    
    const causeDropdown = page.getByRole('combobox', { name: /cause/i });
    await expect(causeDropdown).toBeVisible();
    await causeDropdown.click();
    
    const internalOption = page.getByRole('option', { name: /internal/i });
    await expect(internalOption).toBeVisible();
    await internalOption.click();
    
    const startButton = page.getByRole('button', { name: /start/i });
    await expect(startButton).toBeVisible();
    await startButton.click();
    
    const blogPostField = page.getByRole('textbox', { name: /blog/i });
    await expect(blogPostField).toBeVisible();
    await blogPostField.fill('Revision requested for quality improvements');
    
    const dueDateField = page.getByRole('textbox', { name: /due date/i });
    await expect(dueDateField).toBeVisible();
    await dueDateField.fill('12/31/2024');
    
    const submitAllButton = page.getByRole('button', { name: /submit all/i });
    await expect(submitAllButton).toBeVisible();
    await submitAllButton.click();
    
    const finishButton = page.getByRole('button', { name: /finish/i });
    await expect(finishButton).toBeVisible();
    await finishButton.click();
    
    await expect(page.getByText(/revised spots \(1\)/i)).toBeVisible();
    
    const revisedSpot = page.locator('.spot-item, [data-testid="spot-item"]').first();
    await expect(revisedSpot).toBeVisible();
    
    await expect(page.getByText('Revision requested for quality improvements')).toBeVisible();
    await expect(page.getByText('12/31/2024')).toBeVisible();
  });
});