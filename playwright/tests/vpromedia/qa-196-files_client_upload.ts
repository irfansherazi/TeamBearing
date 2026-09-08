import { test, expect, BASE_URL } from '../../utils/setup';
import * as path from 'path';
import { filePreWashUtility, openClientSettings } from './filePreWashUtility';

const TEST_ENV = process.env.TEST_ENV || 'test';
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);
const isDebugMode = process.env.PWDEBUG === '1';

export async function runClientUpload(browser: any) {
    const clientName = process.env.CLIENT_NAME || "Bob's Burgers";
    const baseUrl = BASE_URL;

    console.log(`[Client Upload] Running with user: DemoProdDirector (ENV: ${TEST_ENV})`);

    const context = await browser.newContext({ storageState: storageStatePath });
    const page = await context.newPage();

    // 1. Run Pre-Wash to clean state (Handles navigation, search, and delete)
    console.log('[Check] Starting Pre-Wash...');
    await filePreWashUtility(page);
    console.log('[Check] Pre-Wash completed. Note: Page might be on drawer or reloaded.');

    // Ensure we are strictly on the client settings page for upload (in case PreWash left us elsewhere)
    // and re-open the edit modal
    if (await page.getByText(/Edit .*Bob['']s Burgers/i).isVisible()) {
        console.log('[Check] Already on Edit Modal, skipping re-open.');
    } else {
        console.log('[Check] Re-opening Client Settings...');
        await openClientSettings(page, clientName);
        console.log('[Check] Client Settings opened.');
    }

    // 2a. Open Files tab and scroll to file upload section
    console.log('[Check] Locating File Section...');
    const slideout = page.locator('.p-sidebar, .p-drawer, .p-dialog, .p-dynamic-dialog').last();
    let fileSection = slideout.locator('label, h1, h2, h3, h4, h5, h6, strong, b, div').filter({ hasText: /^Files?$/i }).first();

    if (await fileSection.count() === 0) {
        console.log('[Check] File label not found in slideout, searching globally...');
        fileSection = page.getByText(/^Files?$/i).first();
    }

    // Robust wait and scroll
    try {
        console.log('[Check] Scrolling to File section...');
        await fileSection.waitFor({ state: 'attached', timeout: 5000 });
        await fileSection.scrollIntoViewIfNeeded();
        if ((await fileSection.getAttribute('class'))?.includes('accordion')) {
            await fileSection.click({ timeout: 1000 });
        }
        console.log('[Check] File section visible.');
    } catch (e) {
        console.warn("[Check] Could not scroll to File section header, looking for upload components directly.");
    }

    // 3a. Method 1: Upload via URL
    console.log('Method 1: Uploading file via URL...');
    const urlFileName = 'Image via URL';

    // FIX: Wait for URL upload link to be visible before clicking.
    // The previous `if (await link.isVisible())` silently skipped the click when
    // the drawer was still loading, leaving the URL form unopened.
    const link = page.locator('#urlFileLink, a.url-upload-link').first();
    await link.waitFor({ state: 'visible', timeout: 30000 });
    console.log('[Check] Clicking URL Upload Link...');
    await link.click();

    // Wait for the URL fields to appear
    console.log('[Check] Waiting for File Name input...');
    const fileNameInput = page.locator('input[name="fileName"]');
    await expect(fileNameInput).toBeVisible({ timeout: 15000 });

    await fileNameInput.click();
    await fileNameInput.fill(urlFileName);
    // Explicitly focus/click URL field
    await page.locator('input[name="fileUrl"]').click();
    await page
        .locator('input[name="fileUrl"]')
        .fill('https://vc-qs-images.s3.amazonaws.com/Logos/vCreative+logo/vCreative_Logo_RGB.png');

    // Select File Type (Required)
    // FIX: Use role-based option selector compatible with PrimeNG 19.
    // The previous `li[aria-label="Prod File"]` selector relied on an aria-label attribute
    // that PrimeNG 19 no longer guarantees on list option elements.
    console.log('[Check] Selecting File Type for URL Upload...');
    const typeDropdown = page.locator('p-select[name="selectedFileType"]').first();
    await expect(typeDropdown).toBeVisible({ timeout: 10000 });
    await typeDropdown.click();
    await page.locator('.p-select-panel, .p-dropdown-panel, [role="listbox"]').first()
        .waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});

    const prodFileOption = page.getByRole('option', { name: 'Prod File', exact: true }).first()
        .or(page.locator('li.p-select-option').filter({ hasText: 'Prod File' }).first());
    await expect(prodFileOption).toBeVisible({ timeout: 5000 });
    await prodFileOption.click();

    // Verify selection stuck
    await expect(typeDropdown).toContainText('Prod File');

    // Try filling Notes if visible, then submit
    // FIX: Guard focus()/press() inside the visibility check — calling focus() on a
    // hidden element throws. Fall back to submit-button click if notes field absent.
    console.log('[Check] Submitting URL upload form...');
    const notesInput = page.locator('input[name="fileNotes"], input[name="notes"]').first();
    if (await notesInput.isVisible()) {
        await notesInput.fill('Test Notes');
        await page.waitForTimeout(500);
        await notesInput.focus();
        await page.keyboard.press('Enter');
    } else {
        // Submit via the dialog's SAVE button when notes field is absent
        const uploadBtn = page.locator('.p-dialog, .p-dynamic-dialog')
            .locator('button').filter({ hasText: /Save|Upload/i }).last();
        await uploadBtn.waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
        if (await uploadBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
            await uploadBtn.click();
        } else {
            // Last resort: DOM-level click on the submit button (same pattern as QA-279)
            await page.evaluate(() => {
                setTimeout(() => {
                    const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
                    for (const btn of buttons) {
                        if (btn.textContent && btn.textContent.trim().toUpperCase() === 'SAVE') {
                            (btn as HTMLElement).click();
                        }
                    }
                }, 0);
            });
        }
    }

    // Wait for dialog to close
    await expect(page.locator('.p-dialog, .p-dynamic-dialog')).not.toBeVisible({ timeout: 10000 })
        .catch(() => console.warn('[Check] URL upload dialog still visible — proceeding anyway.'));

    // 3b. Method 2 & 3: Standard & Drag-Drop Uploads (Simulated)
    console.log('Method 2 & 3: Uploading files via Standard Browse & Drag-Drop...');
    const fileBrowsePath = path.resolve(__dirname, '../../storage/test_files/Client Logo.jpg');
    const fileDndPath = path.resolve(__dirname, '../../storage/test_files/Background Music.mp3');

    const dropzoneInput = page.locator('p-fileupload input[type="file"]').first();
    await expect(dropzoneInput).toBeAttached({ timeout: 5000 });

    // Upload both files
    console.log('[Check] Setting input files (Drag-Drop simulation)...');
    await dropzoneInput.setInputFiles([fileBrowsePath, fileDndPath]);

    // Robust wait: Ensure the files actually appear in the grid
    console.log('Waiting for uploaded files to populate in the grid...');
    const logoRow = page.locator('[class*="upload-file-name"], span.upload-file-name, .file-name').filter({ hasText: 'Client Logo.jpg' });
    const musicRow = page.locator('[class*="upload-file-name"], span.upload-file-name, .file-name').filter({ hasText: 'Background Music.mp3' });

    await expect(logoRow).toBeVisible({ timeout: 30000 });
    await expect(musicRow).toBeVisible({ timeout: 30000 });
    console.log('[Check] Files populated in grid.');

    // 4. Select File Types using Row-Scoped Locators
    console.log('Selecting file types using filename-scoped locators...');

    const selectTypeForFile = async (fileName: string, typeOption: string) => {
        console.log(`Selecting type "${typeOption}" for file "${fileName}"...`);
        const row = page.locator('div.grid').filter({ has: page.locator('span.upload-file-name', { hasText: fileName }) }).first();

        if (await row.count() === 0) {
            console.log(`Standard grid row for ${fileName} not found, trying broad search...`);
        }

        const dropdown = row.locator('p-select').first();

        await expect(row).toBeVisible({ timeout: 5000 });
        await row.scrollIntoViewIfNeeded();

        if (await dropdown.isVisible()) {
            console.log(`Clicking dropdown for ${fileName}...`);
            await dropdown.click();

            const option = page.getByRole('option', { name: typeOption, exact: true })
                .or(page.locator(`li.p-select-option`).filter({ hasText: typeOption }));

            await expect(option.first()).toBeVisible({ timeout: 5000 });
            await option.first().click();

            await page.waitForTimeout(500);
        } else {
            console.log(`Dropdown for ${fileName} not found or already satisfied.`);
        }
    };

    await selectTypeForFile('Client Logo.jpg', 'Client Logo');
    await selectTypeForFile('Background Music.mp3', 'Background Music');

    if (isDebugMode) await page.waitForTimeout(3000);

    // 4. Save all uploaded files
    console.log('[Check] Clicking Save...');
    const saveButton = page.locator('button.v-btn.primary.solid, .p-drawer-footer button').filter({ hasText: 'Save' }).first();
    await expect(saveButton).toBeVisible({ timeout: 10000 });
    await saveButton.click();
    
    await expect(slideout).not.toBeVisible({ timeout: 20000 });
    console.log('✅ All files uploaded and saved.');

    // Add stabilization wait before context teardown to ensure network/file writes complete
    await page.waitForTimeout(3000);

    await context.close();
}
