import { test, expect, BASE_URL } from '../../utils/setup';
import type { Page } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

// --- Helpers ---

/** Clear all files in the downloads folder, namespaced per-browser. */
function getBrowserDownloadsPath(baseDir: string, browserName: string): string {
  const dir = path.join(baseDir, browserName);
  if (fs.existsSync(dir)) {
    for (const f of fs.readdirSync(dir)) {
      fs.rmSync(path.join(dir, f), { force: true });
    }
  } else {
    fs.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

/**
 * Inject the window.print spy directly into the CURRENT page context.
 * Called via page.evaluate just before the PDF export button is clicked.
 * Do NOT use addInitScript here — Angular's hash router never creates a
 * new document, so addInitScript only fires once at initial load and the
 * spy would be clobbered by Angular's bootstrapping.
 */
async function injectPrintSpy(page: Page) {
  await page.evaluate(() => {
    (window as any).__printCalled = false;
    window.print = () => { (window as any).__printCalled = true; };
  });
}

// --- Test Configuration ---
const TEST_ENV = process.env.TEST_ENV || 'qa';
const downloadsBase = path.resolve(__dirname, '../../downloads');

if (!fs.existsSync(downloadsBase)) {
  fs.mkdirSync(downloadsBase, { recursive: true });
}

test.use({ user: 'DemoProdDirector' });

// Wrap in a describe block so serial mode applies correctly to all browser projects.
// Without this, test.describe.configure has no effect and all 3 browser instances
// run in parallel, corrupting each other's DemoProdDirector session (Inbox shows 0 items).
test.describe('qa-257: Export Spot Info', () => {
  test.describe.configure({ mode: 'serial' });

  test('qa-257: Exporting Spot Info', async ({ page }, testInfo) => {
    const browserName = testInfo.project.name; // 'chromium' | 'firefox' | 'webkit'
    const downloadsPath = getBrowserDownloadsPath(downloadsBase, browserName);

    // Navigate directly to Inbox — always has data, avoids 'MyBox (...)' loading race.
    await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/inbox`);
    await page.waitForURL(/production-orders\/folder\/inbox/, { timeout: 20000 });

    // Confirm logged in
    const jwt = await page.evaluate(() => localStorage.getItem('vc2JWT'));
    expect(jwt, 'JWT token must be present — session not established').not.toBeNull();

    if (process.env.PWDEBUG === '1') await page.pause();

    // --- Ensure List View ---
    // Wait robustly for the table to appear; all browsers need adequate render time.
    console.log('Checking current view state...');
    const listViewSelector = '.po-table-wrapper, .p-datatable, table[class]';

    try {
      await page.locator(listViewSelector).first().waitFor({ state: 'visible', timeout: 20000 });
      console.log('✅ List view detected. Continuing...');
    } catch {
      console.warn('⚠️ List view not detected. Attempting to switch...');
      const settingsBtn = page.locator(
        '#settings-btn, button.action-btn:has(img[src*="setting.svg"]), .settings-trigger'
      ).first();
      if (await settingsBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await settingsBtn.click();
        const listViewOpt = page.locator('li#listview, a#listview, .list-view-option').first();
        await listViewOpt.waitFor({ state: 'visible', timeout: 10000 });
        await listViewOpt.click();
        await page.locator(listViewSelector).first().waitFor({ state: 'visible', timeout: 15000 });
        console.log('✅ Switched to list view.');
      } else {
        expect.soft(false, `[${browserName}] Could not detect or switch to list view.`);
      }
    }

    if (process.env.PWDEBUG === '1') await page.pause();

    // --- Row Selection ---
    // Use a broad selector that covers all three browser rendering approaches.
    // Give extra time (20s) — WebKit/Firefox may render the table slower.
    console.log('Selecting a row for export...');
    const rowCheckbox = page.locator(
      'table tbody tr input[type="checkbox"], p-tablecheckbox input[type="checkbox"]'
    ).first();

    try {
      await rowCheckbox.waitFor({ state: 'visible', timeout: 20000 });
    } catch {
      // Hard fail — a silent return here would be a false green.
      throw new Error(
        `[${browserName}] Timed out waiting for a row checkbox. ` +
        'The table may not have loaded, or the row selector is wrong for this browser.'
      );
    }

    const isChecked = await rowCheckbox.isChecked().catch(() => false);
    if (!isChecked) {
      await rowCheckbox.click();
    }
    console.log('✅ Row selected.');

    // Allow the UI a moment to activate the Export action after row selection.
    await page.waitForTimeout(1000);

    if (process.env.PWDEBUG === '1') await page.pause();

    // --- Open Export Dialog ---
    // In qa env, `getByText('Export').first()` reliably targets the Export action.
    // In test env, the Export button is in the bulk-actions bar with a title attribute.
    console.log('Opening Export panel...');

    const exportTrigger = (TEST_ENV === 'test')
      ? page.locator('a[title="Export"], button[title="Export"], .bulk-actions-bar a[title="Export"]').first()
      : page.getByText('Export').first();

    await exportTrigger.waitFor({ state: 'visible', timeout: 10000 });
    await exportTrigger.click();

    // --- Export Dialog Interactions ---
    console.log('Interacting with Export panel...');

    if (TEST_ENV === 'test') {
      // test env uses a PrimeNG 19 p-sidebar panel
      const exportPanel = page.locator(
        'complementary, .p-sidebar, .export-sidebar, [role="complementary"]'
      ).first();
      await exportPanel.waitFor({ state: 'visible', timeout: 15000 });

      const selectAllBox = exportPanel.locator(
        'p-checkbox[inputid="p-checkbox-select-all"], #p-checkbox-select-all'
      ).first();
      await selectAllBox.waitFor({ state: 'visible', timeout: 10000 });
      await selectAllBox.click();
      console.log('✅ Select All clicked.');

      const excelRadio = exportPanel.locator('p-radiobutton, .p-radiobutton')
        .filter({ hasText: 'Excel' })
        .or(exportPanel.getByLabel('Excel'))
        .first();
      await excelRadio.click();

      // Prime download BEFORE clicking to eliminate the race condition.
      console.log('Waiting for Excel download...');
      const exportBtn = exportPanel.locator('button').filter({ hasText: 'Export' }).first();
      const [xlsDownload] = await Promise.all([
        page.waitForEvent('download', { timeout: 30000 }),
        exportBtn.click(),
      ]);
      const xlsPath = path.join(downloadsPath, xlsDownload.suggestedFilename());
      await xlsDownload.saveAs(xlsPath);
      expect(fs.existsSync(xlsPath), `Excel file not saved: ${xlsPath}`).toBe(true);
      console.log('✅ Downloaded file:', xlsDownload.suggestedFilename());

      // --- PDF export ---
      // Inject print spy immediately before clicking — page.evaluate patches the live context.
      console.log('Exporting as PDF/Print...');
      await injectPrintSpy(page);
      const pdfRadio = exportPanel.locator('p-radiobutton, .p-radiobutton')
        .filter({ hasText: 'Pdf' })
        .or(exportPanel.getByLabel('Pdf'))
        .first();
      await pdfRadio.click();
      await exportBtn.click();

      if (!process.env.PWDEBUG) {
        const wasPrintCalled = await page.evaluate(() => (window as any).__printCalled);
        expect(wasPrintCalled, 'window.print() was not triggered for PDF export').toBe(true);
        console.log('✅ window.print() triggered.');
      }

      const undoButton = exportPanel.locator('button').filter({ hasText: 'Undo' }).first();
      if (await undoButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await undoButton.click();
      }

    } else {
      // qa env: Export Orders dialog uses native <label>/<input> elements.
      // No reliable ARIA role — anchor on "Select All" label (unique to this dialog).
      console.log('Waiting for Export dialog...');
      const selectAllLabel = page.locator('label').filter({ hasText: /^Select All$/i }).first();
      await selectAllLabel.waitFor({ state: 'visible', timeout: 15000 });

      await selectAllLabel.click();
      console.log('✅ Select All clicked.');

      // --- Excel radio ---
      console.log('Exporting as Excel/CSV...');
      const excelLabel = page.locator('label').filter({ hasText: /^Excel$/i }).first();
      if (await excelLabel.isVisible({ timeout: 3000 }).catch(() => false)) {
        await excelLabel.click();
      } else {
        await page.locator('input[type="radio"]').first().click();
      }

      // Locate EXPORT button — orange button at bottom-right of dialog.
      const exportBtn = page.locator('button').filter({ hasText: /^EXPORT$/i }).last();

      // Prime download listener BEFORE the click (race-condition safe).
      console.log('Waiting for Excel download...');
      const [xlsDownload] = await Promise.all([
        page.waitForEvent('download', { timeout: 30000 }),
        exportBtn.click(),
      ]);
      const xlsPath = path.join(downloadsPath, xlsDownload.suggestedFilename());
      await xlsDownload.saveAs(xlsPath);
      expect(fs.existsSync(xlsPath), `Excel file not saved: ${xlsPath}`).toBe(true);
      console.log('✅ Downloaded file:', xlsDownload.suggestedFilename());

      if (process.env.PWDEBUG === '1') await page.pause();

      // --- PDF export ---
      // Inject print spy immediately before the PDF click so it is live in the current context.
      console.log('Exporting as PDF/Print...');
      await injectPrintSpy(page);
      const pdfLabel = page.locator('label').filter({ hasText: /^Pdf$/i }).first();
      if (await pdfLabel.isVisible({ timeout: 3000 }).catch(() => false)) {
        await pdfLabel.click();
      } else {
        await page.locator('input[type="radio"]').nth(1).click();
      }
      await exportBtn.click();

      if (process.env.PWDEBUG === '1') {
        console.warn('⚠️ Skipping print validation in debug mode.');
      } else {
        const wasPrintCalled = await page.evaluate(() => (window as any).__printCalled);
        expect(wasPrintCalled, 'window.print() was not triggered for PDF export').toBe(true);
        console.log('✅ window.print() triggered.');
      }

      if (process.env.PWDEBUG === '1') await page.pause();

      // --- Close dialog ---
      console.log('Closing Export panel...');
      const closeX = page.locator(
        'button[aria-label="Close"], .p-dialog-header-close, a#closeIcon[role="button"]'
      ).first();
      if (await closeX.isVisible({ timeout: 2000 }).catch(() => false)) {
        await closeX.click({ force: true });
        console.log('✅ Closed via X button.');
      } else {
        const undoBtn = page.locator('button').filter({ hasText: /^UNDO$/i }).first();
        if (await undoBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await undoBtn.click({ force: true });
          console.log('✅ Closed via UNDO button.');
        }
      }
    }

    console.log(`✅ [${browserName}] QA-257 Export Spot Info completed successfully.`);
  });
});
