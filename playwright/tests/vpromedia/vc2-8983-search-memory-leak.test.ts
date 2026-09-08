/**
 * VC2-8983: Search Memory Leak Detection Test (Repeat-Action Pattern)
 *
 * Uses Chrome DevTools Protocol (CDP) to detect memory leaks during
 * search interactions by measuring heap growth across repeated cycles.
 *
 * Context (JIRA VC2-8983):
 *   Chase Antunes reported system slowdowns throughout the day, requiring
 *   cache clears. Slowdowns specifically occur when searching contract
 *   numbers and navigating the 'traffic' section of the search bar.
 *
 * Strategy: Repeat-Action Pattern with 3 cycles (mirrors VC2-8821)
 *   Cycle 1 (Warmup)  — absorbs one-time initialization costs
 *   Cycle 2 (A)        — first "clean" measurement
 *   Cycle 3 (B)        — second "clean" measurement
 *
 * Leak indicator: Delta(B - A) exceeds threshold. This isolates true
 * per-interaction growth from warm-up noise (lazy modules, singleton caches).
 *
 * Test 1 — Global Search: Open panel → search client/ad-type → results → navigate away → GC → Measure
 * Test 2 — Contract # Search: Open panel → search contract number → results → navigate away → GC → Measure
 *
 * Chromium-only — CDP HeapProfiler / Memory domains are not available on Firefox/WebKit.
 */

import { test, expect } from '../../utils/setup';
import { Page } from '@playwright/test';
import * as SearchHelper from '../../utils/SearchHelper';
import {
    captureMetrics,
    formatBytes,
    type CycleMetrics,
} from '../../memory/lib/memorySampler';

// ─── Configuration ──────────────────────────────────────────────────────────────

// Cycle count is configurable via SEARCH_CYCLES env var.
// Default: 3 (Warmup + Cycle A + Cycle B). Minimum enforced: 3.
// Usage: SEARCH_CYCLES=10 npx playwright test ...
const CYCLE_COUNT = Math.max(3, parseInt(process.env.SEARCH_CYCLES || '3', 10));
const CLIENT_NAME = "Bob's Burgers";

// Threshold gates — a leak must exceed BOTH to trigger a soft failure.
// Starting at 15 MB; goal is to tighten after baseline runs.
const LEAK_THRESHOLD_MB = 15;
const LEAK_THRESHOLD_PERCENT = 1.10; // 10% growth between identical cycles
const DOM_NODE_THRESHOLD = 500;      // max acceptable detached node increase

/**
 * Generate human-readable labels for N cycles.
 * Cycle 0 is always "Warmup", then "Cycle A", "Cycle B", "Cycle C", etc.
 */
function generateCycleLabels(count: number): string[] {
    const labels = ['Warmup'];
    for (let i = 1; i < count; i++) {
        // A=65 in ASCII, so Cycle A, Cycle B, ..., Cycle Z, Cycle AA, etc.
        const letter = i <= 26 ? String.fromCharCode(64 + i) : `${i}`;
        labels.push(`Cycle ${letter}`);
    }
    return labels;
}

// ─── Search Interaction Helpers ─────────────────────────────────────────────────

/**
 * Execute a full search cycle: open panel → set filters → execute → wait for results.
 * Uses SearchHelper for all panel interactions to stay consistent with qa-170.
 */
async function executeSearchCycle(
    page: Page,
    criteria: SearchHelper.SearchCriteria,
    cycleLabel: string
): Promise<void> {
    console.log(`\n   🔍 ${cycleLabel}: Executing search...`);
    await SearchHelper.performSearch(page, criteria);

    // Wait for search results grid to fully render and stabilize
    const grid = page.locator('.p-datatable-tbody');
    await grid.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {
        console.log(`   ⚠️ ${cycleLabel}: Grid not visible after search, continuing...`);
    });

    // Wait for any loading spinners to clear
    const spinner = page.locator('.v-spinner, p-progress-spinner, .loading-overlay, .p-blockui').first();
    if (await spinner.isVisible().catch(() => false)) {
        await spinner.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
    }

    // Let Angular settle with rendered results
    await page.waitForTimeout(2000);
}

/**
 * Tear down search results by navigating back to the dashboard.
 * This destroys the entire search results component tree, including
 * the heavy p-datatable and all lazy-loaded row components.
 */
async function teardownSearchResults(page: Page): Promise<void> {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // Allow Angular to fully bootstrap and destroy prior components
    await page.waitForTimeout(4000);
}

/**
 * Fill the contract number field in the search panel.
 * The search panel must already be open.
 *
 * The contract field lives under the "Traffic" tab in the search panel,
 * not on the default "General Details" tab. We must click the Traffic tab
 * first to expose the input.
 *
 * Selector confirmed via browser agent investigation: input#contractno
 * Tab trigger: #search-traffic-tab or anchor with text "Traffic"
 */
async function fillContractNumber(page: Page, contractNo: string): Promise<void> {
    // Step 1: Navigate to the Traffic tab within the search panel
    const trafficTab = page.locator('#search-traffic-tab, a').filter({ hasText: /^Traffic$/ }).first();
    if (await trafficTab.isVisible({ timeout: 5000 }).catch(() => false)) {
        await trafficTab.scrollIntoViewIfNeeded();
        await trafficTab.click();
        console.log('   📂 Switched to Traffic tab in search panel');
        await page.waitForTimeout(1000); // Wait for tab content to render
    } else {
        console.log('   ⚠️ Traffic tab not found in search panel');
    }

    // Step 2: Fill the contract number input (confirmed ID: contractno)
    const contractInput = page.locator('input#contractno').first();

    if (await contractInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await contractInput.click();
        await contractInput.clear();
        await contractInput.pressSequentially(contractNo, { delay: 50 });
        console.log(`   📝 Filled contract number: ${contractNo}`);
        // Tab to trigger blur-based save
        await page.keyboard.press('Tab');
        await page.waitForTimeout(500);
    } else {
        console.log('   ⚠️ Contract number input (input#contractno) not found after switching to Traffic tab');
    }
}

// ─── Analysis Helper ────────────────────────────────────────────────────────────

/**
 * Analyze cycle metrics and print a formatted report.
 * Returns whether a leak was detected (for soft assertions).
 */
function analyzeAndReport(
    cycleMetrics: CycleMetrics[],
    testLabel: string
): { heapLeakDetected: boolean; domLeakDetected: boolean; heapDelta: number; heapRatio: number; domDelta: number } {
    // cycleMetrics: [Baseline, Warmup, ..., Cycle N-1, Cycle N]
    // Always compare the last two measurement cycles for leak detection.
    const cycleA = cycleMetrics[cycleMetrics.length - 2];
    const cycleB = cycleMetrics[cycleMetrics.length - 1];

    const heapDelta = cycleB.usedHeapSize - cycleA.usedHeapSize;
    const heapRatio = cycleA.usedHeapSize > 0
        ? cycleB.usedHeapSize / cycleA.usedHeapSize
        : 1;
    const domDelta = cycleB.domNodes - cycleA.domNodes;
    const listenerDelta = cycleB.listeners - cycleA.listeners;

    // ── Report ──
    console.log('\n' + '═'.repeat(65));
    console.log(`  MEMORY LEAK ANALYSIS — ${testLabel}`);
    console.log('═'.repeat(65));
    console.log(`\n  Config: ${CYCLE_COUNT} cycles`);
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

    return { heapLeakDetected, domLeakDetected, heapDelta, heapRatio, domDelta };
}

// ─── Tests ───────────────────────────────────────────────────────────────────────

test.describe('VC2-8983: Search Memory Leak Detection', () => {
    test.skip(({ browserName }) => browserName !== 'chromium', 'CDP requires Chromium');
    test.use({ user: 'DemoProdDirector' });

    // Scale timeout with cycle count: ~60s per cycle + 60s overhead
    test.setTimeout(CYCLE_COUNT * 60_000 + 60_000);

    test(`detect memory leaks via repeat-action pattern — Global Search (${CYCLE_COUNT} cycles)`, async ({ page }) => {

        const cycleMetrics: CycleMetrics[] = [];
        const cycleLabels = generateCycleLabels(CYCLE_COUNT);

        // ── Step 1: Navigate and stabilize ──────────────────────────────
        await test.step('Navigate to dashboard and stabilize', async () => {
            await page.goto('/', { waitUntil: 'domcontentloaded' });
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
        for (let cycle = 0; cycle < CYCLE_COUNT; cycle++) {
            const label = cycleLabels[cycle];

            await test.step(`${label}: Execute global search`, async () => {
                // Client-only search — exercises the full search component lifecycle
                // (panel render → API call → grid render) without ng-select timing issues.
                // This matches Chase's reported workflow (searching client names).
                await executeSearchCycle(page, {
                    client: CLIENT_NAME,
                    includeOlder: true,
                }, label);
            });

            await test.step(`${label}: Teardown and measure`, async () => {
                await teardownSearchResults(page);
                const metrics = await captureMetrics(client, label, { gcPasses: 4 });
                cycleMetrics.push(metrics);
            });
        }

        // ── Step 5: Analysis and assertions ─────────────────────────────
        await test.step('Analyze memory deltas and report results', async () => {
            const { heapDelta, heapRatio, domDelta } = analyzeAndReport(
                cycleMetrics,
                'VC2-8983 — Global Search (Repeat-Action Pattern)'
            );

            // Soft assertions — test always runs to completion for reporting
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
        });

        // ── Cleanup CDP session ─────────────────────────────────────────
        await client.send('HeapProfiler.disable');
        await client.detach();
    });

    test(`detect memory leaks via repeat-action pattern — Contract # Search (${CYCLE_COUNT} cycles)`, async ({ page }) => {

        const cycleMetrics: CycleMetrics[] = [];
        const cycleLabels = generateCycleLabels(CYCLE_COUNT);
        // Generate a unique contract number for each cycle
        const contractNumbers = Array.from({ length: CYCLE_COUNT }, (_, i) => `CN${1001 + i}`);

        // ── Step 1: Navigate and stabilize ──────────────────────────────
        await test.step('Navigate to dashboard and stabilize', async () => {
            await page.goto('/', { waitUntil: 'domcontentloaded' });
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
        for (let cycle = 0; cycle < CYCLE_COUNT; cycle++) {
            const label = cycleLabels[cycle];

            await test.step(`${label}: Execute contract number search`, async () => {
                console.log(`\n   🔍 ${label}: Opening search panel for contract # search...`);

                await SearchHelper.openSearchPanel(page, `${label} — Contract # Search`);

                // Fill the contract number field
                await fillContractNumber(page, contractNumbers[cycle]);

                // Execute the search
                const doSearchBtn = page.locator('#do-search-btn').filter({ visible: true }).first();
                await doSearchBtn.waitFor({ state: 'visible', timeout: 10000 });
                console.log(`   🔍 ${label}: Executing contract # search...`);
                await doSearchBtn.click({ force: true });

                // Wait for panel to close
                await expect(page.locator('.p-sidebar-mask')).toBeHidden({ timeout: 15000 }).catch(() => {
                    console.log(`   ⚠️ ${label}: Sidebar mask still visible, continuing...`);
                });

                // Wait for grid results to render
                const grid = page.locator('.p-datatable-tbody');
                await grid.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {
                    console.log(`   ⚠️ ${label}: Grid not visible after contract # search`);
                });

                // Wait for spinners to clear
                const spinner = page.locator('.v-spinner, p-progress-spinner, .loading-overlay, .p-blockui').first();
                if (await spinner.isVisible().catch(() => false)) {
                    await spinner.waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {});
                }

                await page.waitForTimeout(2000);
            });

            await test.step(`${label}: Teardown and measure`, async () => {
                await teardownSearchResults(page);
                const metrics = await captureMetrics(client, label, { gcPasses: 4 });
                cycleMetrics.push(metrics);
            });
        }

        // ── Step 5: Analysis and assertions ─────────────────────────────
        await test.step('Analyze memory deltas and report results', async () => {
            const { heapDelta, heapRatio, domDelta } = analyzeAndReport(
                cycleMetrics,
                'VC2-8983 — Contract # Search (Repeat-Action Pattern)'
            );

            // Soft assertions — test always runs to completion for reporting
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
        });

        // ── Cleanup CDP session ─────────────────────────────────────────
        await client.send('HeapProfiler.disable');
        await client.detach();
    });
});
