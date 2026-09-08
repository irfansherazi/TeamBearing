import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Send Email Function', () => {
  test('should send email with selected file attachments', async ({ page }) => {
    await page.goto('/spots');
    
    await page.waitForLoadState('networkidle');
    
    const spotRow = page.getByRole('row').first();
    await spotRow.click();
    
    await page.waitForLoadState('networkidle');
    
    const notesSection = page.getByText('Notes').or(page.getByRole('tab', { name: 'Notes' }));
    await expect(notesSection).toBeVisible();
    await notesSection.click();
    
    const sendEmailLink = page.getByText('Send Email').or(page.getByRole('link', { name: 'Send Email' }));
    await expect(sendEmailLink).toBeVisible();
    await sendEmailLink.click();
    
    await page.waitForLoadState('networkidle');
    
    const fileCheckbox = page.getByRole('checkbox').first();
    await expect(fileCheckbox).toBeVisible();
    await fileCheckbox.check();
    
    const emailInput = page.getByRole('textbox', { name: /email|recipient/i });
    await expect(emailInput).toBeVisible();
    await emailInput.fill('test@example.com');
    
    const sendButton = page.getByRole('button', { name: 'Send' });
    await expect(sendButton).toBeVisible();
    await sendButton.click();
    
    const successMessage = page.getByText('Email successfully sent.');
    await expect(successMessage).toBeVisible();
  });
});