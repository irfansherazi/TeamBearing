import type { Page } from '@playwright/test';
import { ghostLogin, isGhostAvailable } from '../../utils/prf/GhostLoginHelper';
import { PO_LIST_PATH } from '../constants';
import { ghostViaAngularPanel, isAngularGhostAvailable } from './angularGhost';

const SETTLE_MS = 2000;

/**
 * Ghost as a user, trying fallback display names when the picker has no hit.
 *
 * @param page - Playwright page already signed in as a vCreative admin
 * @param names - Display names to try in order
 * @returns void
 */
export async function ghostAsOneOf(page: Page, names: string[]): Promise<void> {
    const angularGhost = await isAngularGhostAvailable(page);
    const phpGhost = angularGhost ? false : await isGhostAvailable(page);
    if (!angularGhost && !phpGhost) {
        throw new Error(
            'Ghost picker is missing. Log in as a vCreative admin (firm_id 1), e.g. syed@vcreativeinc.com.'
        );
    }
    let lastError = '';
    for (const name of names) {
        try {
            if (angularGhost) {
                await ghostViaAngularPanel(page, name);
            } else {
                await ghostLogin(page, name);
            }
            await page.goto(PO_LIST_PATH, { waitUntil: 'domcontentloaded' });
            await page.waitForTimeout(SETTLE_MS);
            return;
        } catch (err: unknown) {
            lastError = err instanceof Error ? err.message : String(err);
        }
    }
    throw new Error(`Could not ghost as ${names.join(' / ')}: ${lastError}`);
}
