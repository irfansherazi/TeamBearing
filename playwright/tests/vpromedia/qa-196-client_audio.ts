import { test, expect, BASE_URL } from '../../utils/setup';
import * as path from 'path';
import { openClientSettings } from './filePreWashUtility';

// Use the same default env as filePreWashUtility and qa-196-files_client_upload ('test'),
// so step 3 looks for the Background Music file in the same environment that step 2 uploaded it.
const TEST_ENV = process.env.TEST_ENV || 'test';
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);
// Use exact client name to avoid matching "Big bite beefy burgers" before "Bob's Burgers"
const clientName = process.env.CLIENT_NAME || "Bob's Burgers";
const baseUrl = BASE_URL;


// Helper for consistent logging
function logInfo(msg: string) {
  console.log(msg);
}

// Local robust helpers with logging
async function searchForClientLocal(page: any, clientName: string) {
  logInfo(`[Search] Starting search for "${clientName}"...`);

  // Wait for table to load at least one row (hydrate) before typing
  await page.locator('p-table tbody tr, .p-datatable-tbody tr').first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});

  const filter = page.locator('#global-filter-input');
  await expect(filter).toBeVisible();

  const performSearch = async () => {
    logInfo('[Search] Typing query...');
    await filter.click();
    await filter.fill(clientName);
    await page.keyboard.press('Enter');
    await page.locator('tr.p-datatable-selectable-row, .p-datatable-tbody tr').first()
        .waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
  };

  await performSearch();

  // Verify rows
  logInfo('[Search] Checking results...');
  let clientRow = page.locator('tr.p-datatable-selectable-row, .p-datatable-tbody tr, p-table tbody tr').filter({ hasText: new RegExp(clientName, 'i') });
  let count = await clientRow.count();
  logInfo(`[Search] Found ${count} rows matching "${clientName}".`);

  if (count === 0) {
    logInfo('[Search] Retrying search...');
    await performSearch();
    clientRow = page.locator('tr.p-datatable-selectable-row, .p-datatable-tbody tr, p-table tbody tr').filter({ hasText: new RegExp(clientName, 'i') });
    count = await clientRow.count();
    logInfo(`[Search] Retry found ${count} rows.`);
  }

  if (count === 0) {
    logInfo('[Search] FAILURE. Dump of visible text:');
    logInfo((await page.innerText('body')).substring(0, 500));
  }

  await expect(clientRow.first()).toBeVisible({ timeout: 5000 });
  return clientRow.first();
}

async function openClientSettingsLocal(page: any, clientName: string) {
  logInfo(`[Nav] Navigating to Client Settings...`);
  await page.goto(`${BASE_URL}/#/settings/clients?user=600920`);
  await page.waitForLoadState('domcontentloaded');

  const clientRow = await searchForClientLocal(page, clientName);

  logInfo('[Nav] Client row found. Finding Edit button...');
  const editButton = clientRow.locator('i.fa-pencil, i.pencil, i.pi-pencil, button .pi-pencil').first();
  await expect(editButton).toBeVisible();

  logInfo('[Nav] Clicking Edit...');
  await editButton.click();
}

export async function runAudioValidation(browser: any) {
  const context = await browser.newContext({ storageState: storageStatePath });
  const page = await context.newPage();

  logInfo('Starting Audio Validation Test...');


  // 1. Navigation and Client Selection (Robust)
  await openClientSettingsLocal(page, clientName);

  // Wait for Edit Modal/Drawer to appear
  logInfo('[Check] Waiting for Client Edit Drawer...');
  try {
    await expect(page.getByText(/Edit .*Bob['']s Burgers/i).first()).toBeVisible({ timeout: 15000 });
    logInfo('[Check] Drawer title found.');
  } catch (e) {
    logInfo('[Check] Title not found, checking for generic sidebar...');
    await page.locator('.p-drawer, .p-sidebar, .p-dialog').last().waitFor({ state: 'visible', timeout: 5000 });
    logInfo('[Check] Generic sidebar found.');
  }

  // Wait for drawer content to confirm load
  await page.locator('p-drawer, .p-drawer, .p-dialog').last()
      .waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});

  // Scroll to the Files section header first so lazy-loaded file rows are triggered
  logInfo('[Check] Scrolling to Files section...');
  const filesSectionHeader = page.locator('label, h3, h4, strong, div').filter({ hasText: /^Files?$/i }).first();
  if (await filesSectionHeader.isVisible({ timeout: 3000 }).catch(() => false)) {
    await filesSectionHeader.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
  }

  // Force scroll to bottom of drawer to ensure lazy-loaded files appear
  logInfo('[Check] Scrolling drawer to bottom...');
  await page.evaluate(() => {
    const content = document.querySelector('.p-drawer-content, .p-sidebar-content, .p-dialog-content');
    if (content) content.scrollTop = content.scrollHeight;
  });
  await page.waitForTimeout(500);

  // 2a. Locate and Scroll to Audio Row directly (Robust)
  logInfo('[Check] Locating "Background Music" row...');

  // Broad/Relaxed search for debugging
  if (await page.getByText(/Background Music/i).count() > 0) {
    logInfo('[Debug] Found "Background Music" text on page globally.');
    await page.getByText(/Background Music/i).first().scrollIntoViewIfNeeded();
  } else {
    logInfo('[Debug] "Background Music" text NOT found on page globally.');
  }

  // Scroll the "Background Music" text into view first, so the file row is in the viewport.
  const bgMusicText = page.getByText(/Background Music/i).first();
  await bgMusicText.waitFor({ state: 'visible', timeout: 30000 });
  await bgMusicText.scrollIntoViewIfNeeded();
  logInfo('[Check] "Background Music" text located and scrolled into view.');

  // The expand/player button lives in the same drawer. Scope to the open drawer element
  // to avoid matching unrelated expand buttons elsewhere on the page.
  const drawer = page.locator('.p-drawer, .p-sidebar, .p-dialog').last();
  // Scope the files row to row-like containers. Broaden selector to handle PrimeNG 19
  // changes that replaced table rows with list-item or div-based layouts.
  let bgMusicRow = drawer.locator(
    'tr, .p-datatable-row, .p-selectable-row, div.grid > div, .file-row, li, [role="row"], [role="listitem"], [class*="file-item"], [class*="audio-item"], [class*="attachment"]'
  ).filter({ hasText: /Background Music/i }).first();

  const rowFound = await bgMusicRow.isVisible({ timeout: 5000 }).catch(() => false);
  if (!rowFound) {
    // Fallback: any direct child div or li of the drawer that contains the text
    bgMusicRow = drawer.locator('div, li').filter({ hasText: /Background Music/i }).first();
    logInfo('[Check] Structured row not found — falling back to generic div/li container.');
  }
  await expect(bgMusicRow).toBeVisible({ timeout: 10000 });

  const expandButton = bgMusicRow.locator('i.fa-expand, i.fa-expand-arrows-alt, i.file-expand, button.p-button-icon-only, button[title*="Expand" i], button[aria-label*="expand" i]').first();
  await expect(expandButton).toBeVisible({ timeout: 10000 });
  logInfo('Clicking expand player (Force)...');
  await expandButton.click({ force: true });

  // Relaxed Modal Check
  logInfo('[Check] Waiting for OUT CUE text...');
  const modalText = page.getByText(/OUT CUE|Out cue/i).first();
  await expect(modalText).toBeVisible({ timeout: 15000 });

  // FIX: Removed `.locator('visible=true')` — this is invalid Playwright syntax.
  // It was parsed as the CSS attribute selector `[visible=true]` which never matches
  // any HTML element, causing robustModal to always be empty and the waitFor to time out.
  // The correct approach is to scope with .filter({ hasText }) and use .last().
  const robustModal = page.locator('.p-dialog, .p-dynamic-dialog')
    .filter({ hasText: /OUT CUE/i })
    .last();
  await expect(robustModal).toBeVisible({ timeout: 10000 });
  logInfo('[Check] Modal container identified.');

  if (process.env.PWDEBUG) {
    logInfo('🔍 Debugging: Pausing with OUT CUE modal open.');
    await page.pause();
  }

  // Locate the audio element specifically within the OUT CUE modal
  const audioElement = robustModal.locator('audio');
  await expect(audioElement).toBeVisible({ timeout: 5000 });

  // Validate audio element source
  const audioSrc = await audioElement.evaluate((audioEl: any) => (audioEl as HTMLAudioElement).currentSrc);
  const displaySrc = audioSrc.length > 100 ? audioSrc.substring(0, 100) + '...' : audioSrc;
  logInfo(`🎧 Audio source: ${displaySrc}`);

  // Validate that the audio element is loaded with valid media (allow query params)
  expect(audioSrc).toMatch(/\.(mp3|wav|ogg)(\?.*)?$/i);

  // Close OUT CUE modal using the dialog close button
  const closeButton = robustModal.locator('.p-dialog-header-close, .p-dialog-close-button, button[aria-label="Close"]').first();
  await closeButton.click();
  await expect(robustModal).not.toBeVisible();

  // Close the slideout
  const sidebarCloseBtn = page.locator('#addNewClientSideBar #closeIcon, button[aria-label="Close Sidebar"], .p-drawer-close-button, .p-sidebar-close').first();
  if (await sidebarCloseBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await sidebarCloseBtn.click();
  }

  logInfo('✅ OUT CUE modal and audio player validation completed successfully.');

  await context.close();
}
