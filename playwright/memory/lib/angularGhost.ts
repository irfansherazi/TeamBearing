import type { Page } from '@playwright/test';

export const ANGULAR_GHOST_INPUT = '#ghost-panel-input';
export const ANGULAR_GHOST_SUGGESTION = '.suggestions a';

/**
 * Whether the Angular "Ghost In As" field is on screen.
 *
 * @param page - Playwright page
 * @returns True when `#ghost-panel-input` is visible
 */
export async function isAngularGhostAvailable(page: Page): Promise<boolean> {
    try {
        await page.locator(ANGULAR_GHOST_INPUT).first().waitFor({
            state: 'visible',
            timeout: 8000,
        });
        return true;
    } catch {
        return false;
    }
}

/**
 * Ghost through the Angular top-bar panel (`app-sa-ghost-panel`).
 *
 * @param page - Playwright page
 * @param name - Display name to search, e.g. Demo Prod Dir
 * @returns void
 */
export async function ghostViaAngularPanel(page: Page, name: string): Promise<void> {
    const input = page.locator(ANGULAR_GHOST_INPUT).first();
    await input.waitFor({ state: 'visible', timeout: 15000 });
    await input.fill('');
    await input.fill(name);
    const suggestion = page.locator(ANGULAR_GHOST_SUGGESTION).filter({ hasText: name }).first();
    await suggestion.waitFor({ state: 'visible', timeout: 20000 });
    const navigation = page.waitForNavigation({
        waitUntil: 'domcontentloaded',
        timeout: 45000,
    }).catch(() => undefined);
    await suggestion.click();
    await navigation;
    await page.waitForTimeout(3000);
}
