import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Date/Time Picker + Past Due', () => {
  test('should handle date/time selection and color coding for due dates', async ({ page }) => {
    await page.goto('/');
    
    await page.getByRole('button', { name: 'Create Order' }).click();
    await expect(getLocator(page, 'search-adtype-input')).toBeVisible();
    await getLocator(page, 'search-adtype-input').click();
    await page.getByText('TV Ad Open Submit').click();
    
    await expect(getLocator(page, 'search-client-input')).toBeVisible();
    await getLocator(page, 'search-client-input').fill('Demo Client');
    await page.getByText('Demo Client').first().click();
    
    await page.getByLabel('Campaign Name').fill('Test Campaign');
    await page.getByLabel('Product').fill('Test Product');
    
    const dueDateField = page.getByLabel('Due Date');
    await expect(dueDateField).toBeVisible();
    await dueDateField.click();
    
    await expect(page.locator('.p-datepicker')).toBeVisible();
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    await page.locator(`[data-date="${tomorrow.getDate()}"]`).first().click();
    
    const timeInput = page.locator('.p-timepicker input').first();
    await expect(timeInput).toBeVisible();
    await timeInput.fill('14:30');
    
    await page.getByRole('button', { name: 'Next' }).click();
    
    await page.getByRole('button', { name: 'Submit Order' }).click();
    
    await expect(page.locator('.order-list')).toBeVisible();
    const orderRow = page.locator('.order-row').first();
    await expect(orderRow.locator('.due-date')).toContainText('14:30');
    
    await orderRow.getByRole('button', { name: 'Edit' }).click();
    
    const editDueDateField = page.getByLabel('Due Date');
    await expect(editDueDateField).toBeVisible();
    await editDueDateField.click();
    
    const now = new Date();
    now.setMinutes(now.getMinutes() + 45);
    const nearFutureTime = now.toTimeString().slice(0, 5);
    
    await page.locator('.p-timepicker input').first().fill(nearFutureTime);
    await page.getByRole('button', { name: 'Save' }).click();
    
    await expect(orderRow.locator('.due-date')).toHaveCSS('color', 'rgb(255, 165, 0)');
  });
});