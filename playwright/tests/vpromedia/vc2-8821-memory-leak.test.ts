/**
 * VC2-8821: Memory Leak Detection Test (Repeat-Action Pattern)
 *
 * Uses Chrome DevTools Protocol (CDP) to detect memory leaks during
 * Quick Order creation by measuring heap growth across repeated cycles.
 *
 * Strategy: Repeat-Action Pattern with 3 cycles
 *   Cycle 1 (Warmup)  — absorbs one-time initialization costs
 *   Cycle 2 (A)        — first "clean" measurement
 *   Cycle 3 (B)        — second "clean" measurement
 *
 * Leak indicator: Delta(B - A) exceeds threshold. This isolates true
 * per-interaction growth from warm-up noise (lazy modules, singleton caches).
 *
 * Two modes:
 *   - Discard: Open QO → Add N spots (minimal) → Discard via UI → GC → Measure
 *   - Submit:  Open QO → Add N spots (full) → Fill form fields → Submit → GC → Measure
 *
 * Chromium-only — CDP HeapProfiler / Memory domains are not available on Firefox/WebKit.
 */

import { test, expect } from '../../utils/setup';
import { Page } from '@playwright/test';
import {
    openQuickOrderForm,
    selectAdType,
    createBasicOrder,
    submitOrder,
} from '../../utils/OrderHelper';
import {
    generateRandomSpotTitle,
    generateRandomISCI,
} from '../../utils/QO_helpers';
import {
    captureMetrics,
    formatBytes,
    type CycleMetrics,
} from '../../memory/lib/memorySampler';

// ─── Configuration ──────────────────────────────────────────────────────────────
const SPOTS_PER_CYCLE = 8;
const CYCLE_COUNT = 3;
const CLIENT_NAME = "Bob's Burgers";

// Threshold gates — a leak must exceed BOTH to trigger a soft failure.
// Starting at 15 MB; goal is to tighten to 5 MB after baseline runs.
const LEAK_THRESHOLD_MB = 15;
const LEAK_THRESHOLD_PERCENT = 1.10; // 10% growth between identical cycles
const DOM_NODE_THRESHOLD = 500;      // max acceptable detached node increase

type TestMode = 'discard' | 'submit';

// ─── Quick Order Interaction Helpers ─────────────────────────────────────────────

/**
 * Add N spots to the currently-open Quick Order form.
 * Fills spot-level fields (title, status, ISCI, length, rotation) on each card.
 */
async function addSpots(page: Page, count: number): Promise<void> {
    for (let i = 0; i < count; i++) {
        const title = generateRandomSpotTitle().toUpperCase();
        const isci = generateRandomISCI();

        console.log(`   🔄 Spot ${i + 1}/${count}: "${title}"`);

        // Fill spot title on the last (newest) card
        const spotTitle = page.locator('#spot-cards-list-wrapper').getByPlaceholder('Spot title').last();
        if (await spotTitle.isVisible({ timeout: 5000 }).catch(() => false)) {
            await spotTitle.fill(title);
            await spotTitle.press('Tab');
            await page.waitForTimeout(500);
        }

        // Select status
        const statusDropdown = page.getByText('Select Status').last();
        if (await statusDropdown.isVisible({ timeout: 2000 }).catch(() => false)) {
            await statusDropdown.click();
            const option = page.getByText('Needs Writing').last();
            if (await option.isVisible({ timeout: 2000 }).catch(() => false)) {
                await option.click();
            }
        }

        // Fill ISCI
        const isciInput = page.locator('#spot-cards-list-inner').getByPlaceholder('AD-ID OR ISCI CODE').last();
        if (await isciInput.isVisible({ timeout: 2000 }).catch(() => false)) {
            await isciInput.fill(isci);
        }

        // Fill Length
        const lengthInput = page.getByRole('textbox', { name: 'Length ' }).last();
        if (await lengthInput.isVisible({ timeout: 2000 }).catch(() => false)) {
            await lengthInput.fill('30');
        }

        // Fill Rotation (required for submission; harmless no-op if hidden)
        const rotationInput = page.getByRole('textbox', { name: 'Rotation ' }).last();
        if (await rotationInput.isVisible({ timeout: 1000 }).catch(() => false)) {
            await rotationInput.fill('100');
        }

        // Tab out to trigger save-on-blur and spawn the next card
        await page.keyboard.press('Tab');
        await page.waitForTimeout(800);
    }
}



/**
 * Discard the current Quick Order via the in-app UI.
 *
 * Flow observed in the live app:
 *   1. Click the sidebar "X" close button
 *   2. A "Draft Saved" p-dialog appears with three options:
 *      - "CLOSE WITHOUT SAVING" (red)   ← we click this
 *      - "CONTINUE WORKING"  (outlined)
 *      - "CLOSE AND SAVE"    (orange)
 *   3. After dismissing the dialog, the QO sidebar closes.
 *
 * This tests whether QuickOrderComponent.ngOnDestroy() properly releases memory,
 * unlike page.goto('/') which replaces the entire JS context.
 */
async function discardQuickOrder(page: Page): Promise<void> {
    // Step 1: Click the sidebar close button (top-right X)
    const closeBtn = page.locator(
        'a#closeIcon, .p-sidebar-close, button.p-sidebar-close, .v-sidebar-header .close-btn'
    ).first();

    if (await closeBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await closeBtn.click();
        console.log('   📌 Clicked sidebar close button');
    } else {
        // Fallback: try "DISCARD ALL DRAFTS" button at the bottom bar
        const discardAll = page.locator('button#discard-all-drafts');
        if (await discardAll.isVisible({ timeout: 3000 }).catch(() => false)) {
            await discardAll.click();
            console.log('   📌 Clicked "DISCARD ALL DRAFTS" button');
        } else {
            console.log('   ⚠️ No close/discard button found, pressing Escape');
            await page.keyboard.press('Escape');
        }
    }

    // Step 2: Handle the "Draft Saved" p-dialog overlay.
    // Scope the button search to the p-dialog to avoid matching the bottom-bar
    // "Discard All Drafts" button that sits behind the modal overlay.
    const draftDialog = page.locator('p-dialog');
    const closeWithoutSaving = draftDialog.locator(
        'button:has-text("CLOSE WITHOUT SAVING")'
    ).first();

    if (await closeWithoutSaving.isVisible({ timeout: 5000 }).catch(() => false)) {
        await closeWithoutSaving.click();
        console.log('   ✅ Dismissed "Draft Saved" dialog via "CLOSE WITHOUT SAVING"');
    } else {
        // Fallback: any visible confirmation dialog button
        const fallbackConfirm = page.locator(
            'button#dialog-button-1, button:has-text("Discard")'
        ).first();
        if (await fallbackConfirm.isVisible({ timeout: 3000 }).catch(() => false)) {
            await fallbackConfirm.click();
            console.log('   ✅ Dismissed via fallback confirm button');
        }
    }

    // Wait for Angular to fully destroy the QO component tree
    await page.waitForTimeout(3000);
}

/**
 * Print the analysis table and run assertions against thresholds.
 * Used by both discard and submit test variants.
 */
function analyzeAndAssert(cycleMetrics: CycleMetrics[], mode: TestMode): void {
    // cycleMetrics: [Baseline, Warmup, Cycle A, Cycle B]
    const cycleA = cycleMetrics[2];
    const cycleB = cycleMetrics[3];

    const heapDelta = cycleB.usedHeapSize - cycleA.usedHeapSize;
    const heapRatio = cycleA.usedHeapSize > 0
        ? cycleB.usedHeapSize / cycleA.usedHeapSize
        : 1;
    const domDelta = cycleB.domNodes - cycleA.domNodes;
    const listenerDelta = cycleB.listeners - cycleA.listeners;

    // ── Report ──
    console.log('\n' + '═'.repeat(65));
    console.log(`  MEMORY LEAK ANALYSIS — VC2-8821 [${mode.toUpperCase()} mode]`);
    console.log('═'.repeat(65));
    console.log(`\n  Config: ${SPOTS_PER_CYCLE} spots × ${CYCLE_COUNT} cycles`);
    console.log(`  Thresholds: ${LEAK_THRESHOLD_MB} MB absolute, ${((LEAK_THRESHOLD_PERCENT - 1) * 100).toFixed(0)}% growth, ${DOM_NODE_THRESHOLD} DOM nodes\n`);

    console.log('  Phase     │  Heap Used     │  DOM Nodes  │  Listeners  │  Δ Heap (vs prev)');
    console.log('  ──────────┼────────────────┼─────────────┼─────────────┼───────────────────');

    for (let i = 0; i < cycleMetrics.length; i++) {
        const m = cycleMetrics[i];
        const prev = i > 0 ? cycleMetrics[i - 1] : null;
        const delta = prev ? m.usedHeapSize - prev.usedHeapSize : 0;
        const deltaStr = prev ? `${delta >= 0 ? '+' : ''}${formatBytes(delta)}` : '—';
        const label = m.label.padEnd(9);

        console.log(
            `  ${label} │  ${formatBytes(m.usedHeapSize).padEnd(12)}  │  ${m.domNodes.toLocaleString().padEnd(9)}  │  ${m.listeners.toLocaleString().padEnd(9)}  │  ${deltaStr}`
        );
    }

    console.log('\n' + '─'.repeat(65));
    console.log(`  Δ(B-A) Heap:       ${heapDelta >= 0 ? '+' : ''}${formatBytes(heapDelta)}  (${((heapRatio - 1) * 100).toFixed(2)}%)`);
    console.log(`  Δ(B-A) DOM Nodes:  ${domDelta >= 0 ? '+' : ''}${domDelta}`);
    console.log(`  Δ(B-A) Listeners:  ${listenerDelta >= 0 ? '+' : ''}${listenerDelta}`);
    console.log('─'.repeat(65));

    // ── Annotations ──
    const heapLeakDetected = heapDelta > LEAK_THRESHOLD_MB * 1024 * 1024
        && heapRatio > LEAK_THRESHOLD_PERCENT;
    const domLeakDetected = domDelta > DOM_NODE_THRESHOLD;

    if (heapLeakDetected) {
        console.log(`\n  ⚠️  HEAP LEAK: Cycle B exceeds Cycle A by ${formatBytes(heapDelta)} (${((heapRatio - 1) * 100).toFixed(2)}%)`);
        console.log(`       Thresholds: >${LEAK_THRESHOLD_MB} MB AND >${((LEAK_THRESHOLD_PERCENT - 1) * 100).toFixed(0)}%`);
    }

    if (domLeakDetected) {
        console.log(`\n  ⚠️  DOM LEAK: ${domDelta} nodes added between Cycle A → B (threshold: ${DOM_NODE_THRESHOLD})`);
    }

    if (!heapLeakDetected && !domLeakDetected) {
        console.log('\n  ✅ No significant memory leak detected.');
        console.log(`     Heap growth between identical cycles is within tolerance.`);
    }

    console.log('═'.repeat(65) + '\n');

    // ── Assertions ──
    expect.soft(
        heapDelta,
        `Heap leak: Cycle B exceeds Cycle A by ${formatBytes(heapDelta)} (threshold: ${LEAK_THRESHOLD_MB} MB)`
    ).toBeLessThan(LEAK_THRESHOLD_MB * 1024 * 1024);

    expect.soft(
        heapRatio,
        `Heap growth ratio: ${heapRatio.toFixed(4)}x (threshold: ${LEAK_THRESHOLD_PERCENT}x)`
    ).toBeLessThan(LEAK_THRESHOLD_PERCENT);

    expect.soft(
        domDelta,
        `DOM node leak: ${domDelta} nodes added between Cycle A → B (threshold: ${DOM_NODE_THRESHOLD})`
    ).toBeLessThan(DOM_NODE_THRESHOLD);
}

// ─── Test ────────────────────────────────────────────────────────────────────────

test.describe('VC2-8821: Memory Leak Detection', () => {
    test.skip(({ browserName }) => browserName !== 'chromium', 'CDP requires Chromium');
    test.use({ user: 'DemoProdDirector' });

    for (const mode of ['discard', 'submit'] as TestMode[]) {

        test(`detect memory leaks via ${mode} pattern (${CYCLE_COUNT} cycles × ${SPOTS_PER_CYCLE} spots)`, async ({ page }) => {

            // Submit mode has more UI interaction per cycle (dates, station, contract, submit wait)
            test.setTimeout(mode === 'submit' ? 600_000 : 360_000);

            const cycleMetrics: CycleMetrics[] = [];

            // ── Step 1: Navigate and stabilize ──────────────────────────────
            await test.step('Navigate to dashboard and stabilize', async () => {
                await page.goto('/', { waitUntil: 'domcontentloaded' });
                // Let Angular bootstrap — avoid networkidle (SPA has persistent connections)
                await page.waitForTimeout(5000);
            });

            // ── Step 2: Open CDP session ────────────────────────────────────
            const client = await page.context().newCDPSession(page);
            await client.send('HeapProfiler.enable');

            // ── Step 3: Baseline measurement ────────────────────────────────
            const baseline = await test.step('Capture BASELINE metrics', async () => {
                return await captureMetrics(client, 'BASELINE', { gcPasses: 4 });
            });
            cycleMetrics.push(baseline);

            // ── Step 4: Execute cycles ──────────────────────────────────────
            const cycleLabels = ['Warmup', 'Cycle A', 'Cycle B'];

            for (let cycle = 0; cycle < CYCLE_COUNT; cycle++) {
                const label = cycleLabels[cycle];

                await test.step(`${label}: Open QO and add ${SPOTS_PER_CYCLE} spots`, async () => {
                    if (mode === 'submit') {
                        // Submit mode: use createBasicOrder for the first spot, which
                        // handles ALL form-level fields (sales POC, client, dates,
                        // station, contract) through the battle-tested OrderHelper.
                        // Increase viewport height so the PrimeNG datepicker overlay
                        // has room to render inside the QO sidebar.
                        await page.setViewportSize({ width: 1920, height: 1200 });
                        await openQuickOrderForm(page);
                        await createBasicOrder(page, { client: CLIENT_NAME });

                        // Add the remaining spots (spot-level fields only; form-level
                        // fields are already set by createBasicOrder above).
                        if (SPOTS_PER_CYCLE > 1) {
                            await addSpots(page, SPOTS_PER_CYCLE - 1);
                        }
                    } else {
                        // Discard mode: lightweight fill — only per-spot fields needed
                        await openQuickOrderForm(page);
                        await selectAdType(page, 'Radio Commercial');

                        const clientInput = page.locator('p-autocomplete[name="card_client_id"] input');
                        await clientInput.fill(CLIENT_NAME.substring(0, 5));
                        const clientOption = page.getByRole('option', { name: CLIENT_NAME });
                        await clientOption.waitFor({ state: 'visible', timeout: 15000 });
                        await clientOption.click();
                        await page.waitForTimeout(1000);

                        await addSpots(page, SPOTS_PER_CYCLE);
                    }
                });

                await test.step(`${label}: ${mode === 'submit' ? 'Submit' : 'Discard'} and measure`, async () => {
                    if (mode === 'submit') {
                        await submitOrder(page);
                        // Allow Angular to fully destroy the QO component tree after submission
                        await page.waitForTimeout(3000);
                    } else {
                        await discardQuickOrder(page);
                    }

                    const metrics = await captureMetrics(client, label, { gcPasses: 4 });
                    cycleMetrics.push(metrics);
                });
            }

            // ── Step 5: Analysis and assertions ─────────────────────────────
            await test.step('Analyze memory deltas and report results', async () => {
                analyzeAndAssert(cycleMetrics, mode);
            });

            // ── Cleanup CDP session ─────────────────────────────────────────
            await client.send('HeapProfiler.disable');
            await client.detach();
        });
    }
});
