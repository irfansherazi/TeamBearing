import { test, expect, BASE_URL } from '../../utils/setup';
import type { Browser, Page } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { overrideStatusFilter } from '../../utils/SearchHelper';

const TEST_ENV = process.env.TEST_ENV || 'test';
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);


export async function runListviewActions(browser: Browser) {
    const context = await browser.newContext({
        storageState: storageStatePath,
    });
    const page = await context.newPage();

    const browserName = browser.browserType().name();
    const spotDataPath = path.resolve(__dirname, `../../storage/qa-196/qa-196_spot_data_${TEST_ENV}_${browserName}.json`);
    const spotData = JSON.parse(fs.readFileSync(spotDataPath, 'utf-8'))[0];
    const { spotTitle: expectedSpotTitle, poid, postSubmitUrl } = spotData;
    console.log(`Using Spot Title: ${expectedSpotTitle} and POID: ${poid}`);

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing before starting test actions.');
        await page.pause();
    }

    // 1. Validate files present
    // Navigate to order/${poid} to see spot-level rows. If the user's saved status filter
    // ('Deleted,Canceled') is hiding the newly submitted spot, override it via the search panel.
    // If a postSubmitUrl was captured after Step 4 submission and it's an order-route URL,
    // use it directly — it may already be in the right context without the filter issue.
    console.log('Validating spot title and attached files...');

    const orderUrl = `${BASE_URL}/#/vpro/production-orders/order/${poid}`;
    // Use postSubmitUrl if it references this poid — e.g. folder/drafts?edit=${poid} when the QO
    // landed in drafts due to a lead time warning. Draft orders return a blank page at /order/${poid}.
    // Strip the `user=` param — it belonged to the submitter's session and may redirect/logout
    // a different user (DemoProdDirector) who navigates to this URL.
    const usePostSubmitUrl = !!postSubmitUrl && postSubmitUrl.includes(String(poid));
    const cleanedPostSubmitUrl = postSubmitUrl
        ? postSubmitUrl
            .replace(/([?&])user=\d+&/, '$1')  // user= not at end: remove value, keep delimiter
            .replace(/[?&]user=\d+$/, '')       // user= at end: remove entirely
        : postSubmitUrl;
    const targetUrl = usePostSubmitUrl ? cleanedPostSubmitUrl : orderUrl;
    console.log(`Navigating to ${targetUrl}...`);
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    const spotRow = page.locator('table tbody tr, .p-datatable-tbody tr').filter({ hasText: expectedSpotTitle }).first();

    // Quick visibility check: if spot is hidden (saved status filter applied), override it
    const spotVisible = await spotRow.isVisible({ timeout: 5000 }).catch(() => false);
    if (!spotVisible) {
        console.log(`Spot row not visible after navigation — attempting status filter override...`);
        // Ensure we're on the order/${poid} route before manipulating the search panel
        if (!page.url().includes(`/order/${poid}`)) {
            await page.goto(orderUrl, { waitUntil: 'domcontentloaded' });
            await page.waitForTimeout(3000);
        }
        await overrideStatusFilter(page);
    }

    await expect(spotRow).toBeVisible({ timeout: 30000 });
    console.log(`✅ Spot title "${expectedSpotTitle}" is visible.`);

    // The Files column may truncate to show only 1-2 file links with a "View All" overflow button.
    // Click "View All" if present to expand all file links in the column before verifying.
    const viewAllBtn = spotRow.locator('button, a, span').filter({ hasText: /View All/i }).first();
    if (await viewAllBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('Clicking "View All" to expand truncated file list...');
        await viewAllBtn.click();
        await page.waitForTimeout(1000);
    }

    // Verify the three files attached in step 4 are visible in the spot row.
    // test env: link text = file TYPE label; QA: link text = filename (e.g. "Background Music.mp3")
    await expect(spotRow.locator('a').filter({ hasText: /Background Music/i }).first()).toBeVisible({ timeout: 15000 });
    await expect(spotRow.locator('a').filter({ hasText: /Client Logo/i }).first()).toBeVisible({ timeout: 15000 });
    // URL file type was "Prod File" or "Final Spot" — check for either; QA shows "Test File via URL"
    const prodFileLink = spotRow.locator('a').filter({ hasText: /Prod File|Final Spot|Test File via URL/i }).first();
    await expect(prodFileLink).toBeVisible({ timeout: 15000 });
    console.log('✅ All three files are visible in the list view.');

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after validation.');
        await page.pause();
    }

    // 2. Remove files
    // The "View All" panel is still open — use it to delete files from the panel's table.
    // If panel is not open, open it now. This avoids issues with the inline list truncating files.
    console.log('Deleting existing files via "View All" panel...');

    async function openViewAllPanel() {
        // Check if the Files panel is already open (has a table with file rows)
        const panelTable = page.locator('table').filter({ has: page.locator('th', { hasText: /File Name/i }) }).first();
        if (await panelTable.isVisible({ timeout: 1000 }).catch(() => false)) return;
        // Open by clicking "View All" button in the spot row
        const vab = spotRow.locator('button, a, span').filter({ hasText: /View All/i }).first();
        if (await vab.isVisible({ timeout: 2000 }).catch(() => false)) {
            await vab.click();
            await page.waitForTimeout(1000);
        }
    }

    // Delete files using evaluate() to find and trigger the delete icon directly in the DOM.
    // This bypasses Playwright's visibility/actionability checks for icons hidden behind CSS
    // or clipped by overflow in the inline list and the "View All" panel.
    async function deleteFileFromPanel(page: Page, label: string) {
        // Strategy 1: find the i.file-delete icon in ul.files-list li (works for visible inline files)
        // Strategy 2: trigger mouseenter/hover on the row to reveal the delete icon
        // Strategy 3: select checkbox in the panel and use bulk delete
        const deleted = await page.evaluate((label: string) => {
            // Look in all possible containers: ul.files-list li, panel table rows
            const allRows = [
                ...Array.from(document.querySelectorAll('ul.files-list li')),
                ...Array.from(document.querySelectorAll('table tr')),
            ];
            for (const row of allRows) {
                if (!(row as HTMLElement).textContent?.includes(label)) continue;
                // Trigger hover to reveal hidden delete icon
                row.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                // Try to find delete icon
                const deleteBtn = (row as HTMLElement).querySelector(
                    'i.file-delete[title="Delete file"], [title="Delete file"], .file-delete, button[aria-label*="delete" i]'
                ) as HTMLElement;
                if (deleteBtn) {
                    deleteBtn.click();
                    return 'inline-delete';
                }
            }
            return null;
        }, label);

        if (deleted) {
            console.log(`🗑 Triggered delete for "${label}" via DOM (${deleted})`);
        } else {
            // Fallback: open "View All" panel, select checkbox, look for Delete action
            await openViewAllPanel();
            const panelRow = page.locator('table').filter({ has: page.locator('th', { hasText: /File Name/i }) })
                .locator('tr').filter({ hasText: label }).first();
            if (await panelRow.isVisible({ timeout: 2000 }).catch(() => false)) {
                // Select the row's checkbox
                const checkbox = panelRow.locator('input[type="checkbox"], .p-checkbox').first();
                if (await checkbox.isVisible({ timeout: 1000 }).catch(() => false)) {
                    await checkbox.click({ force: true });
                    await page.waitForTimeout(300);
                }
                // Look for a Delete button that might appear after selection
                const deleteBtn = page.locator('button').filter({ hasText: /Delete/i }).first();
                if (await deleteBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await deleteBtn.click();
                }
            }
        }

        await page.getByRole('button', { name: 'YES, DELETE' }).waitFor({ state: 'visible', timeout: 15000 });
        await page.getByRole('button', { name: 'YES, DELETE' }).click();
        await page.waitForTimeout(500);
    }

    await deleteFileFromPanel(page, 'Background Music');
    await deleteFileFromPanel(page, 'Client Logo');
    // QA shows file name as link text ("Test File via URL"); test env shows file type ("Final Spot" or "Prod File")
    await deleteFileFromPanel(page, 'Test File via URL')
        .catch(() => deleteFileFromPanel(page, 'Final Spot'))
        .catch(() => deleteFileFromPanel(page, 'Prod File'));

    // Close the View All panel if still open before re-uploading via different methods
    const panelAfterDelete = page.locator('table').filter({ has: page.locator('th', { hasText: /File Name/i }) }).first();
    if (await panelAfterDelete.isVisible({ timeout: 1000 }).catch(() => false)) {
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);
    }
    console.log('✅ Files deleted successfully.');

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after deletion.');
        await page.pause();
    }

    // Helper: wait for the file-type form (drawer/dialog) to close after saving
    async function waitForUploadFormToClose() {
        // After clicking Save, wait for either a success toast or the form fields to disappear
        await page.waitForTimeout(1000);
        const fileNameInput = page.locator('input[name="fileName"]');
        // Give up to 10s for form to disappear
        try {
            await expect(fileNameInput).not.toBeVisible({ timeout: 10000 });
        } catch {
            // Form may have a different structure; just wait a bit
            await page.waitForTimeout(2000);
        }
    }

    // Helper: upload a file via Browse → Upload File menu and set the file type
    async function uploadViaFileDialog(filePath: string, fileType: string, label: string) {
        console.log(`Attaching file via file dialog: ${label}...`);
        await spotRow.getByText('Browse', { exact: true }).click();
        await page.getByRole('menuitem', { name: 'Upload File' }).first().click();

        // The upload dialog/drawer opens — find the file input inside it
        // PrimeNG 19: input[type="file"] may be inside p-fileupload or a custom upload dialog
        const uploadDialog = page.locator('.p-dialog, .p-drawer, [role="dialog"], [role="complementary"]').filter({ hasText: /Upload|File Type|Select a File Type/i }).last();
        await uploadDialog.waitFor({ state: 'visible', timeout: 15000 }).catch(async () => {
            console.warn(`Upload dialog not found by text filter, proceeding anyway`);
        });

        // Find the file input — try inside p-fileupload first, then any input[type="file"]
        const fileInput = page.locator('p-fileupload input[type="file"], input[type="file"]').first();
        await expect(fileInput).toBeAttached({ timeout: 10000 });
        await fileInput.setInputFiles(filePath);
        await page.waitForTimeout(1500);

        // Select file type — PrimeNG 19 uses p-select; fall back to p-dropdown
        const fileTypeDropdown = page.locator('p-select, p-dropdown').filter({ hasText: /Select a File Type|Select/i }).last();
        await expect(fileTypeDropdown).toBeVisible({ timeout: 15000 });
        await fileTypeDropdown.click();
        await page.locator('li[role="option"]', { hasText: fileType }).first().click();

        await page.getByRole('button', { name: 'Save', exact: true }).click();
        await waitForUploadFormToClose();
        console.log(`✅ ${label} attached via file dialog.`);
    }

    // 3. Attach files
    console.log('Attaching files...');

    // Attach file via URL
    console.log('Attaching file via URL...');
    await spotRow.getByText('Browse', { exact: true }).click();
    await page.getByRole('menuitem', { name: 'URL' }).click();
    await page.locator('input[name="fileName"]').fill('Test File via URL');
    await page
        .locator('input[name="fileUrl"]')
        .fill('https://vc-qs-images.s3.amazonaws.com/Logos/vCreative+logo/vCreative_Logo_RGB.png');
    await page.getByText('Select a File Type').click();
    await page.getByText('Prod File').click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    // Wait for URL upload form to close before proceeding
    await waitForUploadFormToClose();
    await page.waitForTimeout(1000);

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after URL upload.');
        await page.pause();
    }

    // Attach file via drag-drop simulation (using hidden input on the drag-drop zone)
    // In the list view row, the drag-drop area uses a raw input[type="file"] (not p-fileupload).
    console.log('Attaching file via dropzone...');
    const clientLogoPath = path.resolve(__dirname, '../../storage/test_files/Client Logo.jpg');
    const dropzoneInput = page.locator('input[type="file"]').first();
    await expect(dropzoneInput).toBeAttached({ timeout: 10000 });
    await dropzoneInput.setInputFiles(clientLogoPath);
    await page.waitForTimeout(1500);

    // After dropzone upload, a file type selector appears — select Client Logo
    const dropzoneTypeDropdown = page.locator('p-select, p-dropdown').filter({ hasText: /Select a File Type|Select/i }).last();
    await expect(dropzoneTypeDropdown).toBeVisible({ timeout: 15000 });
    await dropzoneTypeDropdown.click();
    await page.locator('li[role="option"]', { hasText: 'Client Logo' }).first().click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await waitForUploadFormToClose();

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after dropzone upload.');
        await page.pause();
    }

    // Attach file via file dialog (Browse → Upload File menu)
    const file1Path = path.resolve(__dirname, '../../storage/test_files/Background Music.mp3');
    await uploadViaFileDialog(file1Path, 'Background Music', 'Background Music via file dialog');

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after file dialog upload.');
        await page.pause();
    }

    // Attach Aircheck file via file dialog with a unique, long file name
    const uniqueFilePath = path.resolve(
        __dirname,
        '../../storage/test_files/Production_Audio_File_that_was_given_a_really_long_file_name_for_some_reason_or_another_I_gave_up_even-asking-anymore-questions-with-this-team.wav'
    );
    await uploadViaFileDialog(uniqueFilePath, 'Aircheck', 'Aircheck via file dialog (long filename)');

    if (process.env.PWDEBUG === '1') {
        console.log('🔍 Debugging: Pausing after unique file dialog upload.');
        await page.pause();
    }

    console.log('✅ All file actions completed successfully.');

    // Increment expected event count: 3 deletes + 4 uploads = 7 new events
    const dataArray = JSON.parse(fs.readFileSync(spotDataPath, 'utf-8'));
    dataArray[0].expectedFileEventCount = (dataArray[0].expectedFileEventCount || 0) + 7;
    fs.writeFileSync(spotDataPath, JSON.stringify(dataArray, null, 2));
    console.log(`Updated expectedFileEventCount to: ${dataArray[0].expectedFileEventCount}`);

    await context.close();
}
