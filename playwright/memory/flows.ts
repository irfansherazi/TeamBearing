/**
 * Memory Watch user-flow cycles against live vSuite.
 */

import type { Page } from '@playwright/test';
import { openQuickOrderForm } from '../utils/OrderHelper';
import { openSearchPanel } from '../utils/SearchHelper';
import {
    AI_INTAKE_PATH,
    DETAILS_SELECTOR,
    FLOW_IDS,
    FLOW_LABELS,
    PO_LIST_PATH,
    SEARCH_PANEL_SELECTOR,
    SIDEBAR_SELECTOR,
    SPOT_ROW_SELECTOR,
    type MemoryFlowId,
} from './constants';

const SETTLE_MS = 2000;

/**
 * Wait, ignoring timeout by returning false.
 *
 * @param locatorWait - Promise from locator.waitFor
 * @returns True when visible in time
 */
async function appeared(locatorWait: Promise<unknown>): Promise<boolean> {
    try {
        await locatorWait;
        return true;
    } catch {
        return false;
    }
}

/**
 * Close a PrimeNG overlay / Quick Order draft dialog if it is open.
 *
 * @param page - Playwright page
 * @returns void
 */
export async function closeOverlay(page: Page): Promise<void> {
    const closeBtn = page
        .locator(
            'a#closeIcon, .p-sidebar-close, button.p-sidebar-close, .p-drawer-close, .v-sidebar-header .close-btn'
        )
        .first();
    if (await closeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await closeBtn.click({ force: true });
    } else {
        await page.keyboard.press('Escape');
    }
    const closeWithoutSaving = page
        .locator('p-dialog')
        .locator('button:has-text("CLOSE WITHOUT SAVING")')
        .first();
    if (await closeWithoutSaving.isVisible({ timeout: 3000 }).catch(() => false)) {
        await closeWithoutSaving.click({ force: true });
    }
    await page.waitForTimeout(SETTLE_MS);
}

/**
 * Open Production Orders list view and wait for the grid.
 *
 * @param page - Playwright page
 * @returns void
 */
export async function goToProductionOrders(page: Page): Promise<void> {
    await page.goto(PO_LIST_PATH, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(SETTLE_MS);
    const grid = page.locator('.p-datatable-tbody, app-production-orders').first();
    await appeared(grid.waitFor({ state: 'visible', timeout: 30000 }));
}

/**
 * Production Orders: open the first spot, then return to the list.
 *
 * @param page - Playwright page
 * @returns void
 */
async function runPoOpenSpot(page: Page): Promise<void> {
    await goToProductionOrders(page);
    const row = page.locator(SPOT_ROW_SELECTOR).first();
    const rowVisible = await appeared(row.waitFor({ state: 'visible', timeout: 30000 }));
    if (!rowVisible) {
        throw new Error('No Production Order row found to open');
    }
    await row.click({ force: true });
    await appeared(
        page.locator(DETAILS_SELECTOR).first().waitFor({ state: 'visible', timeout: 20000 })
    );
    await page.waitForTimeout(SETTLE_MS);
    await goToProductionOrders(page);
}

/**
 * Open the search panel, then close it without running a search.
 *
 * @param page - Playwright page
 * @returns void
 */
async function runPoSearchPanel(page: Page): Promise<void> {
    await goToProductionOrders(page);
    await openSearchPanel(page, 'Memory Watch search panel');
    await appeared(
        page.locator(SEARCH_PANEL_SELECTOR).first().waitFor({ state: 'visible', timeout: 20000 })
    );
    await closeOverlay(page);
    await page
        .locator(SEARCH_PANEL_SELECTOR)
        .first()
        .waitFor({ state: 'hidden', timeout: 15000 })
        .catch(() => undefined);
}

/**
 * Open AI Intake, then leave back to Production Orders.
 *
 * @param page - Playwright page
 * @returns void
 */
async function runAiIntake(page: Page): Promise<void> {
    await page.goto(AI_INTAKE_PATH, { waitUntil: 'domcontentloaded' });
    const opened = await appeared(
        page.locator('app-ai-intake, .ai-intake-page').first().waitFor({
            state: 'visible',
            timeout: 30000,
        })
    );
    if (!opened) {
        throw new Error('AI Intake page did not render');
    }
    await page.waitForTimeout(SETTLE_MS);
    await goToProductionOrders(page);
}

/**
 * Open the Quick Order sidebar, then discard/close it.
 *
 * @param page - Playwright page
 * @returns void
 */
async function runSidebar(page: Page): Promise<void> {
    await goToProductionOrders(page);
    await openQuickOrderForm(page);
    await appeared(
        page.locator(SIDEBAR_SELECTOR).first().waitFor({ state: 'visible', timeout: 20000 })
    );
    await page.waitForTimeout(SETTLE_MS);
    await closeOverlay(page);
}

/**
 * Run one open/use/close cycle for a named Memory Watch flow.
 *
 * @param page - Playwright page
 * @param flowId - Recipe id
 * @returns void
 */
export async function runFlowCycle(page: Page, flowId: MemoryFlowId): Promise<void> {
    switch (flowId) {
        case 'qo-open-close-snapshot':
            throw new Error('qo-open-close-snapshot must run via runQoOpenCloseRitual');
        case 'po-open-spot':
            await runPoOpenSpot(page);
            return;
        case 'po-search-panel':
            await runPoSearchPanel(page);
            return;
        case 'ai-intake-open-close':
            await runAiIntake(page);
            return;
        case 'sidebar-open-close':
            await runSidebar(page);
            return;
        default: {
            const exhaustive: never = flowId;
            throw new Error(`Unsupported memory flow: ${String(exhaustive)}`);
        }
    }
}

/**
 * Return true when id is a known Memory Watch flow.
 *
 * @param value - Raw --flow / MEMORY_FLOW value
 * @returns True when the id is in FLOW_IDS
 */
export function isMemoryFlowId(value: string): value is MemoryFlowId {
    return (FLOW_IDS as readonly string[]).includes(value);
}

/**
 * Display name for a flow id.
 *
 * @param flowId - Recipe id
 * @returns Human label
 */
export function flowLabel(flowId: MemoryFlowId): string {
    return FLOW_LABELS[flowId];
}
