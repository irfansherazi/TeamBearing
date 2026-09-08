import { test, expect } from '@playwright/test';

test('demo test - login and check title', async ({ page }) => {
  await page.goto('https://www.google.com');
  await expect(page).toHaveTitle(/Google/);
});
