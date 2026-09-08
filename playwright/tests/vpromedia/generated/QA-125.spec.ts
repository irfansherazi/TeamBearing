import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('New User Experience - QA-125', () => {
  test('User can sign up and complete onboarding with role-based folder access', async ({ page }) => {
    await page.goto('/');
    
    // Navigate to signup from login screen
    await page.getByText('Sign up').click();
    
    // Fill signup form with required fields
    const testEmail = `imail-test+qa125test@vcreativeinc.com`;
    await expect(getLocator(page, 'login-email-input')).toBeVisible();
    await getLocator(page, 'login-email-input').fill(testEmail);
    await getLocator(page, 'login-password-input').fill('SuperVCteam2026!');
    
    // Select vPro as product
    await page.getByText('vPro').click();
    
    // Fill remaining required fields
    await page.getByLabel('First Name').fill('Test');
    await page.getByLabel('Last Name').fill('User');
    await page.getByLabel('Company').fill('Demo Broadcasting');
    
    // Submit signup form
    await getLocator(page, 'login-submit-btn').click();
    
    // Wait for account approval and login
    await expect(page.getByText('Welcome')).toBeVisible({ timeout: 30000 });
    
    // Accept EULA pages
    await page.getByText('Accept').click();
    await page.getByText('Accept').click();
    
    // Complete three-tab user setup wizard
    await page.getByText('Next').click();
    await page.getByText('Next').click();
    await page.getByText('Next').click();
    
    // Access notifications and start working
    await expect(getLocator(page, 'notifications-bell')).toBeVisible();
    await getLocator(page, 'notifications-bell').click();
    await page.getByText('Start Working').click();
    
    // Verify role-based folder visibility
    await expect(page.getByText('Inbox')).toBeVisible();
    await expect(page.getByText('All')).toBeVisible();
    await expect(page.getByText('Draft')).toBeVisible();
  });
});