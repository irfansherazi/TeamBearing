import { Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const downloadsPath = path.resolve(__dirname, '../../downloads');

/**
 * Hook to spy on window.print calls.
 */
export async function hookPrintSpy(page: Page) {
  await page.addInitScript(() => {
    window.__printCalled = false;
    const originalPrint = window.print;
    window.print = () => {
      window.__printCalled = true;
      originalPrint.call(window);
    };
  });
}

/**
 * Validate that a file was downloaded.
 */
export function validateFileDownload() {
  const downloadedFiles = fs.readdirSync(downloadsPath);
  if (downloadedFiles.length === 0) {
    throw new Error('No files were downloaded.');
  }
  console.log('📁 Downloaded files:', downloadedFiles);
}

/**
 * Validate that window.print was called.
 */
export async function validatePrintCalled(page: Page) {
  const wasPrintCalled = await page.evaluate(() => window.__printCalled);
  if (!wasPrintCalled) {
    throw new Error('window.print() was not called.');
  }
  console.log('✅ window.print() was called.');
}

// Extend the Window interface to include __printCalled
interface Window {
  __printCalled?: boolean;
}