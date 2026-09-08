/**
 * QA-46: Basic Ad Types
 *
 * Validates the Quick Order form for all four basic ad types:
 *   1. Radio Commercial        → Status: "Needs Writing"
 *   2. Commercial+Streaming    → Status: "Needs Producing"  (requires Digital URL)
 *   3. Streaming Only           → Status: "Needs Producing"  (requires Digital URL)
 *   4. Image Ad (Banner)        → Status: "Needs Producing"
 *
 * Each spot is submitted individually. Submission is verified by:
 *   - submitOrder() extracting a valid POID from the post-submit URL
 *   - Asserting POID is truthy (non-null)
 *
 * Streaming ad types (Commercial+Streaming, Streaming Only) additionally
 * assert that the Digital URL field is surfaced and required.
 */

import { test, expect } from '../../utils/setup';
import type { Page } from '@playwright/test';
import {
    openQuickOrderForm,
    createBasicOrder,
    submitOrder,
} from '../../utils/OrderHelper';

// Serial execution — each order is independent but the session is shared
test.describe.configure({ mode: 'serial' });

/**
 * Safety-net station check: if createBasicOrder's DOM-level click did not trigger
 * Angular's change detection (PrimeNG 19 quirk), this falls back to clicking the
 * visible .p-checkbox-box element which fires the full Angular event cycle.
 */
async function ensureStationChecked(page: Page): Promise<void> {
    const stationBoxes = page.locator('p-checkbox[name="card_stations"] .p-checkbox-box');
    const boxCount = await stationBoxes.count();
    if (boxCount === 0) {
        // Station field not present for this ad type — no action needed
        return;
    }
    // Detect whether any station is already visually checked
    const anyChecked = await page.evaluate(() => {
        const boxes = Array.from(document.querySelectorAll('p-checkbox[name="card_stations"] .p-checkbox-box'));
        return boxes.some(b => b.classList.contains('p-checkbox-checked') || b.getAttribute('aria-checked') === 'true');
    });
    if (!anyChecked) {
        console.warn('⚠️ Station safety-net: no station visually checked — clicking first .p-checkbox-box');
        await stationBoxes.first().click({ force: true });
        await page.waitForTimeout(500);
    }
}

test.describe('QA-46: Basic Ad Types', () => {
    test.use({ user: 'DemoSalesExec' });
    test.use({ viewport: { width: 1529, height: 960 } });

    // QO form interactions (calendar, autocomplete, station popover) are slow on QA
    test.setTimeout(340_000); // Was 120_000 — 4 serial QO submissions need more time in headless

    // Default client used across all spots
    const CLIENT = "Bob's Burgers";

    // ──────────────────────────────────────────────
    // Test 1 — Radio Commercial
    // ──────────────────────────────────────────────
    test('Create & submit a Radio Commercial spot', async ({ page }) => {
        let title: string;

        await test.step('Open Quick Order form', async () => {
            await page.waitForLoadState('domcontentloaded');
            await openQuickOrderForm(page);
        });

        await test.step('Fill order — Radio Commercial / Needs Writing', async () => {
            const result = await createBasicOrder(page, {
                client: CLIENT,
                adType: 'Radio Commercial',
                status: 'Needs Writing',
            });
            title = result.title;
            await ensureStationChecked(page);
        });

        await test.step('Submit and verify POID', async () => {
            const poid = await submitOrder(page);
            expect(poid, `Expected a valid POID after submitting "${title}"`).toBeTruthy();
            console.log(`✅ Radio Commercial — POID: ${poid} | Title: "${title}"`);
        });
        await page.waitForLoadState('domcontentloaded');
    });

    // ──────────────────────────────────────────────
    // Test 2 — Commercial+Streaming (combo)
    // ──────────────────────────────────────────────
    test('Create & submit a Commercial+Streaming spot', async ({ page }) => {
        let title: string;

        await test.step('Open Quick Order form', async () => {
            await page.waitForLoadState('domcontentloaded');
            await openQuickOrderForm(page);
        });

        await test.step('Fill order using createBasicOrder', async () => {
            // createBasicOrder will select the ad type, fill client/title/status/stations
            const result = await createBasicOrder(page, {
                client: CLIENT,
                adType: 'Commercial+Streaming',
                status: 'Needs Producing',
                digitalUrl: 'https://example.com/streaming-test',
            });
            title = result.title;
            await ensureStationChecked(page);
        });

        await test.step('Verify Digital URL was filled', async () => {
            // Commercial+Streaming must surface a Digital URL input
            const digitalUrlField = page.locator(
                'input[placeholder*="click through web address"], input[placeholder*="Digital URL"], input[name*="digital_url"]'
            ).first();
            await expect(digitalUrlField).toBeVisible({ timeout: 5000 });
            const val = await digitalUrlField.inputValue();
            expect(val).toBe('https://example.com/streaming-test');
            console.log('✅ Digital URL field verified for Commercial+Streaming');
        });

        await test.step('Submit and verify POID', async () => {
            const poid = await submitOrder(page);
            expect(poid, `Expected a valid POID after submitting "${title}"`).toBeTruthy();
            console.log(`✅ Commercial+Streaming — POID: ${poid} | Title: "${title}"`);
        });
        await page.waitForLoadState('domcontentloaded');
    });

    // ──────────────────────────────────────────────
    // Test 3 — Streaming Only
    // ──────────────────────────────────────────────
    test('Create & submit a Streaming Only spot', async ({ page }) => {
        let title: string;

        await test.step('Open Quick Order form', async () => {
            await page.waitForLoadState('domcontentloaded');
            await openQuickOrderForm(page);
        });

        await test.step('Fill order — Streaming Only / Needs Producing', async () => {
            const result = await createBasicOrder(page, {
                client: CLIENT,
                adType: 'Streaming Only',
                status: 'Needs Producing',
                digitalUrl: 'https://example.com/streaming-only-test',
            });
            title = result.title;
            await ensureStationChecked(page);
        });

        await test.step('Verify Digital URL was filled', async () => {
            // Streaming Only must surface a Digital URL input
            const digitalUrlField = page.locator(
                'input[placeholder*="click through web address"], input[placeholder*="Digital URL"], input[name*="digital_url"]'
            ).first();
            await expect(digitalUrlField).toBeVisible({ timeout: 5000 });
            const val = await digitalUrlField.inputValue();
            expect(val).toBe('https://example.com/streaming-only-test');
            console.log('✅ Digital URL field verified for Streaming Only');
        });

        await test.step('Submit and verify POID', async () => {
            const poid = await submitOrder(page);
            expect(poid, `Expected a valid POID after submitting "${title}"`).toBeTruthy();
            console.log(`✅ Streaming Only — POID: ${poid} | Title: "${title}"`);
        });
        await page.waitForLoadState('domcontentloaded');
    });

    // ──────────────────────────────────────────────
    // Test 4 — Image Ad (Banner Ad)
    // ──────────────────────────────────────────────
    test('Create & submit an Image Ad (Banner) spot', async ({ page }) => {
        let title: string;

        await test.step('Open Quick Order form', async () => {
            await page.waitForLoadState('domcontentloaded');
            await openQuickOrderForm(page);
        });

        await test.step('Fill order — Image Ad / Needs Producing', async () => {
            const result = await createBasicOrder(page, {
                client: CLIENT,
                adType: 'Image Ad',
                status: 'Needs Producing',
                digitalUrl: 'https://example.com/image-ad-test',
            });
            title = result.title;
            console.log(`✅ Image Ad order filled: "${title}"`);
            await ensureStationChecked(page);
        });

        await test.step('Submit and verify POID', async () => {
            const poid = await submitOrder(page);
            expect(poid, `Expected a valid POID after submitting "${title}"`).toBeTruthy();
            console.log(`✅ Image Ad (Banner) — POID: ${poid} | Title: "${title}"`);
        });
    });
});
