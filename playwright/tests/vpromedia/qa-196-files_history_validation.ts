import { test, expect, BASE_URL } from '../../utils/setup';
import type { Browser } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { overrideStatusFilter } from '../../utils/SearchHelper';

const TEST_ENV = process.env.TEST_ENV || 'test';
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);


export async function runHistoryValidation(browser: Browser) {
  const context = await browser.newContext({
    storageState: storageStatePath,
  });
  const page = await context.newPage();

  // Load Spot Data
  const browserName = browser.browserType().name();
  const spotDataPath = path.resolve(__dirname, `../../storage/qa-196/qa-196_spot_data_${TEST_ENV}_${browserName}.json`);

  if (!fs.existsSync(spotDataPath)) {
    throw new Error(`Spot data file not found at ${spotDataPath}. Run previous tests to generate data.`);
  }

  const spotData = JSON.parse(fs.readFileSync(spotDataPath, 'utf-8'))[0];
  const { spotTitle, poid, postSubmitUrl, expectedFileEventCount } = spotData;
  console.log(`Validating History for Spot: "${spotTitle}" (Expected Events: ${expectedFileEventCount})`);

  const orderUrl = `${BASE_URL}/#/vpro/production-orders/order/${poid}`;
  // Use postSubmitUrl if it references this poid — draft orders return blank at /order/${poid}
  // Strip user= param — it belongs to the submitter's session and can logout a different user
  const usePostSubmitUrl = !!postSubmitUrl && postSubmitUrl.includes(String(poid));
  const cleanedPostSubmitUrl = postSubmitUrl
      ? postSubmitUrl
          .replace(/([?&])user=\d+&/, '$1')
          .replace(/[?&]user=\d+$/, '')
      : postSubmitUrl;
  const startingURL = usePostSubmitUrl ? cleanedPostSubmitUrl : orderUrl;

  await page.goto(startingURL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // If spot not visible, DemoProdDirector's saved status filter may be hiding it
  const spotText = page.getByText(`Title: ${spotTitle}`, { exact: false }).filter({ visible: true });
  if (!await spotText.isVisible({ timeout: 5000 }).catch(() => false)) {
    console.log('Spot not visible — attempting status filter override...');
    if (!page.url().includes(`/order/${poid}`)) {
      await page.goto(orderUrl, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(3000);
    }
    await overrideStatusFilter(page);
  }

  // Wait for spot title to be visible to ensure page is loaded
  await expect(page.getByText(`Title: ${spotTitle}`, { exact: false }).filter({ visible: true })).toBeVisible({ timeout: 20000 });

  // Open History panel via the clock icon in the PO column.
  // Scope to the row containing spotTitle to avoid strict-mode violations when
  // multiple rows share the same td.po-col i.history-on selector.
  const spotRow = page.locator('tr').filter({ hasText: spotTitle }).first();
  const historyIcon = spotRow.locator('td.po-col i.history-on').first();
  await expect(historyIcon).toBeVisible({ timeout: 10000 });
  await historyIcon.click();

  // Wait for History Sidebar
  const historyContainer = page.locator('.history__content');
  await expect(historyContainer).toBeVisible({ timeout: 10000 });

  // Wait for history items to load
  await historyContainer.locator('.history__item').first()
      .waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});

  // Count history items
  const historyItems = historyContainer.locator('.history__item');
  const count = await historyItems.count();

  // Validate total count
  expect(count).toBeGreaterThanOrEqual(expectedFileEventCount);
  console.log(`✅ History count ${count} is valid (Expected >= ${expectedFileEventCount})`);

  // Validate the latest entry (most recent)
  const latestEntry = historyItems.first();
  const latestMessage = latestEntry.locator('.history__message');

  // Look for "Reactivated", "file", or "Prod File" related text in the message
  await expect(latestMessage).toContainText(/Reactivated|file|Prod/i);
  // Truncate message for cleaner logs
  const fullMessage = (await latestMessage.innerText()).replace(/\s+/g, ' ').trim();
  const truncatedMessage = fullMessage.length > 120 ? fullMessage.substring(0, 120) + '...' : fullMessage;
  console.log(`✅ Latest history entry validated: "${truncatedMessage}"`);

  await context.close();
}
