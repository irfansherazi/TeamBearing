/**
 * Manual Production Orders memory ritual: ghost, 1-spot QO, 5-spot QO, snapshots.
 */

import type { CDPSession, Locator, Page } from '@playwright/test';
import { ghostLogin, isGhostAvailable } from '../utils/prf/GhostLoginHelper';
import {
    DEFAULT_GC_PASSES,
    DETAILS_SELECTOR,
    PO_LIST_PATH,
    RITUAL_FIRST_GHOST,
    RITUAL_FIRST_GHOST_FALLBACKS,
    RITUAL_SECOND_GHOST,
} from './constants';
import { closeOverlay, goToProductionOrders } from './flows';
import { bytesToMb, captureMetrics, enableHeapProfiler } from './lib/memorySampler';
import { isLargeOrder, isOneSpotOrder } from './poSpotCount';
import {
    PAGE_SWITCH_ALLOWANCE_MB,
    evaluateRitualVerdict,
    type RitualPersonaGrowth,
} from './lib/verdict';

const SETTLE_MS = 2000;
const MAX_PAGE_TRIES = 8;

export interface RitualHeapPoint {
    label: string;
    usedMb: number;
    pageSwitch: boolean;
}

export interface RitualRunResult {
    points: RitualHeapPoint[];
    flowOk: boolean;
    flowError: string;
    pageSwitchUsed: boolean;
}

/**
 * Clear the browser console before a snapshot.
 *
 * @param page - Playwright page
 * @param client - CDP session for the same page
 * @returns void
 */
async function clearBrowserConsole(page: Page, client: CDPSession): Promise<void> {
    await page.evaluate(() => {
        console.clear();
    });
    try {
        const send = client.send.bind(client) as (name: string) => Promise<unknown>;
        await send('Runtime.discardConsoleEntries');
    } catch {
        return;
    }
}

/**
 * Attach a fresh CDP heap session after navigation or ghost reload.
 *
 * @param page - Playwright page
 * @returns CDP session with HeapProfiler enabled
 */
async function attachHeapSession(page: Page): Promise<CDPSession> {
    const client = await page.context().newCDPSession(page);
    await enableHeapProfiler(client);
    return client;
}

/**
 * Find the first compact card or table row whose PO count matches.
 *
 * @param page - Playwright page
 * @param match - True when this card's count label is the target order
 * @returns Matching locator, or null
 */
async function firstMatchingOrderCard(
    page: Page,
    match: (label: string) => boolean
): Promise<Locator | null> {
    const cards = page
        .locator('.compact-card, tr.p-datatable-selectable-row')
        .filter({ has: page.locator('.spotCountNumber') });
    const count = await cards.count();
    for (let index = 0; index < count; index++) {
        const card = cards.nth(index);
        const label = (await card.locator('.spotCountNumber').first().innerText()) ?? '';
        if (match(label)) {
            return card;
        }
    }
    return null;
}

/**
 * Click the next paginator control when it is enabled.
 *
 * @param page - Playwright page
 * @returns True when a page change happened
 */
async function goToNextListPage(page: Page): Promise<boolean> {
    const next = page.locator('.p-paginator-next:not(.p-disabled)').first();
    if (!(await next.isVisible({ timeout: 1000 }).catch(() => false))) {
        return false;
    }
    await next.click({ force: true });
    await page.waitForTimeout(SETTLE_MS);
    return true;
}

/**
 * Find and open a Quick Order whose spot count matches, paging if needed.
 *
 * @param page - Playwright page
 * @param match - Count-label predicate
 * @param missingMessage - Error when no order is found
 * @returns True when list paging was used
 */
async function openMatchingQuickOrder(
    page: Page,
    match: (label: string) => boolean,
    missingMessage: string
): Promise<boolean> {
    await goToProductionOrders(page);
    let pageSwitch = false;
    for (let attempt = 0; attempt < MAX_PAGE_TRIES; attempt++) {
        const card = await firstMatchingOrderCard(page, match);
        if (card && (await card.isVisible({ timeout: 4000 }).catch(() => false))) {
            await card.click({ force: true });
            const details = page.locator(DETAILS_SELECTOR).first();
            try {
                await details.waitFor({ state: 'visible', timeout: 20000 });
            } catch {
                throw new Error('Quick Order details did not open');
            }
            await page.waitForTimeout(SETTLE_MS);
            return pageSwitch;
        }
        const moved = await goToNextListPage(page);
        if (!moved) {
            break;
        }
        pageSwitch = true;
    }
    throw new Error(missingMessage);
}

/**
 * Close the open order with no edits, then clear console, GC, and snapshot.
 *
 * @param page - Playwright page
 * @param client - CDP session
 * @param label - Sample label
 * @returns Used heap in MB
 */
async function snapshotAfterClose(
    page: Page,
    client: CDPSession,
    label: string
): Promise<number> {
    await closeOverlay(page);
    await clearBrowserConsole(page, client);
    const sample = await captureMetrics(client, label, { gcPasses: DEFAULT_GC_PASSES });
    return bytesToMb(sample.usedHeapSize);
}

/**
 * Ghost as a user, trying fallback display names when the picker has no hit.
 *
 * @param page - Playwright page
 * @param names - Display names to try in order
 * @returns void
 */
async function ghostAsOneOf(page: Page, names: string[]): Promise<void> {
    if (!(await isGhostAvailable(page))) {
        throw new Error(
            'Ghost picker is missing. Log in as Admin first so Demo Prod Dir and Suzan Goritz can be ghosted.'
        );
    }
    let lastError = '';
    for (const name of names) {
        try {
            await ghostLogin(page, name);
            return;
        } catch (err: unknown) {
            lastError = err instanceof Error ? err.message : String(err);
        }
    }
    throw new Error(`Could not ghost as ${names.join(' / ')}: ${lastError}`);
}

/**
 * One persona: 1-spot QO snapshot, then 5-spot QO snapshot.
 *
 * @param page - Playwright page
 * @param client - CDP session
 * @param persona - Label prefix for samples
 * @returns Heap points for this persona
 */
async function runPersonaSnapshots(
    page: Page,
    client: CDPSession,
    persona: string
): Promise<RitualHeapPoint[]> {
    const oneSwitch = await openMatchingQuickOrder(
        page,
        isOneSpotOrder,
        'No 1-spot Quick Order found on the Production Orders list'
    );
    const afterOne = await snapshotAfterClose(page, client, `${persona}-after-1-spot`);
    const fiveSwitch = await openMatchingQuickOrder(
        page,
        (label) => isLargeOrder(label, 5),
        'No 5-spot or larger Quick Order found on the Production Orders list'
    );
    const afterFive = await snapshotAfterClose(page, client, `${persona}-after-5-spot`);
    return [
        { label: `${persona}-after-1-spot`, usedMb: afterOne, pageSwitch: oneSwitch },
        { label: `${persona}-after-5-spot`, usedMb: afterFive, pageSwitch: fiveSwitch },
    ];
}

/**
 * Run the Production Orders Quick Order memory ritual (two ghost users).
 *
 * @param page - Playwright page already logged in as Admin
 * @returns Heap points and flow status
 */
export async function runQoOpenCloseRitual(page: Page): Promise<RitualRunResult> {
    const points: RitualHeapPoint[] = [];
    let client: CDPSession | null = null;
    try {
        await page.goto(PO_LIST_PATH, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(4000);
        await ghostAsOneOf(page, [RITUAL_FIRST_GHOST, ...RITUAL_FIRST_GHOST_FALLBACKS]);
        client = await attachHeapSession(page);
        const first = await runPersonaSnapshots(page, client, 'demo-prod-dir');
        points.push(...first);
        await client.detach().catch(() => undefined);
        client = null;
        await ghostAsOneOf(page, [RITUAL_SECOND_GHOST]);
        client = await attachHeapSession(page);
        const second = await runPersonaSnapshots(page, client, 'suzan-goritz');
        points.push(...second);
        return {
            points,
            flowOk: true,
            flowError: '',
            pageSwitchUsed: points.some((point) => point.pageSwitch),
        };
    } catch (err: unknown) {
        return {
            points,
            flowOk: false,
            flowError: err instanceof Error ? err.message : String(err),
            pageSwitchUsed: points.some((point) => point.pageSwitch),
        };
    } finally {
        if (client) {
            await client.detach().catch(() => undefined);
        }
    }
}

/**
 * Grade ritual snapshots with the 6 MB page-switch allowance.
 *
 * @param points - Heap samples from the ritual
 * @param maxGrowthMb - Cap per persona from first snapshot
 * @returns Pass/fail verdict
 */
export function gradeQoRitual(
    points: RitualHeapPoint[],
    maxGrowthMb: number
): ReturnType<typeof evaluateRitualVerdict> {
    const personas = ['demo-prod-dir', 'suzan-goritz'];
    const growth: RitualPersonaGrowth[] = [];
    for (const persona of personas) {
        const personaPoints = points.filter((point) => point.label.startsWith(persona));
        if (personaPoints.length === 0) {
            continue;
        }
        const baseline = personaPoints[0].usedMb;
        const last = personaPoints[personaPoints.length - 1];
        growth.push({
            name: persona,
            growthMb: last.usedMb - baseline,
            pageSwitch: personaPoints.some((point) => point.pageSwitch),
        });
    }
    return evaluateRitualVerdict(growth, maxGrowthMb, PAGE_SWITCH_ALLOWANCE_MB);
}
