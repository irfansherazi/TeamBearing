import { test, expect, type Page } from '@playwright/test';
import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';

test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });

test.describe('Search Functionality', () => {
  test('should search for The Beta Boys radio commercials and filter by active status', async ({ page }) => {
    await page.goto('/');
    
    await expect(getLocator(page, 'search-open-btn')).toBeVisible();
    await getLocator(page, 'search-open-btn').click();
    
    await expect(getLocator(page, 'search-client-input')).toBeVisible();
    await getLocator(page, 'search-client-input').fill('The Beta Boys');
    
    await expect(getLocator(page, 'search-adtypes-tab')).toBeVisible();
    await getLocator(page, 'search-adtypes-tab').click();
    await page.getByRole('option', { name: 'radio commercial' }).click();
    
    await expect(getLocator(page, 'search-execute-btn')).toBeVisible();
    await getLocator(page, 'search-execute-btn').click();
    
    await expect(getLocator(page, 'search-results-header')).toBeVisible();
    await expect(getLocator(page, 'search-results-grid')).toBeVisible();
    
    const resultsGrid = getLocator(page, 'search-results-grid');
    await expect(resultsGrid).toContainText('The Beta Boys');
    await expect(resultsGrid).toContainText('radio commercial');
    
    await expect(getLocator(page, 'search-open-btn')).toBeVisible();
    await getLocator(page, 'search-open-btn').click();
    
    await expect(getLocator(page, 'search-client-input')).toHaveValue('The Beta Boys');
    
    await page.getByRole('option', { name: 'Active' }).click();
    
    await expect(getLocator(page, 'search-execute-btn')).toBeVisible();
    await getLocator(page, 'search-execute-btn').click();
    
    await expect(getLocator(page, 'search-results-grid')).toBeVisible();
    const updatedResults = getLocator(page, 'search-results-grid');
    await expect(updatedResults).toContainText('The Beta Boys');
    await expect(updatedResults).not.toContainText('archived');
  });
});