/**
 * GhostLoginHelper.ts — Impersonate another user via the admin ghost widget.
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/ghost-login.md
 *
 * The ghost widget is a select2 v3 ajax picker mounted on `input#ghost_id`
 * in the top nav. The select2 binding runs from `adminjs.html.twig`, loaded
 * only when the user has ROLE_ADMIN / ROLE_FIRM_ADMIN / ROLE_PROMOTIONS_DIRECTOR
 * / ROLE_HR (or is already ghosted). For other users, `#s2id_ghost_id` never
 * exists — treat as PRECONDITION_MISSING.
 *
 * Ajax config (adminjs.html.twig:91-94):
 *   - Endpoint: POST /ghost_people
 *   - minimumInputLength: 3
 *   - quietMillis: 2000
 *
 * On success (adminjs.html.twig:25-39):
 *   POST /Admin_ghost_in → data.email + data.sso_token → setCookie ssojwt(_test)
 *   → location.reload()
 *
 * The reload lands the user (impersonated) on their default landing — which
 * may NOT be Home. Re-fingerprint the page after ghosting.
 */

import { expect, Page } from '@playwright/test';
import { activeSelect2Drop, closeAnySelect2Drop } from './Select2v3Helper';

/**
 * Runbook STEP 1 verification — is the ghost widget bound for this user?
 * A missing `#s2id_ghost_id` means the current user lacks ghost privileges.
 */
export async function isGhostAvailable(page: Page): Promise<boolean> {
    return await page.evaluate(() => document.querySelectorAll('#s2id_ghost_id').length === 1);
}

/**
 * Assert the ghost widget is available; throws with a PRECONDITION_MISSING
 * shape so callers can detect it explicitly.
 */
export async function assertGhostAvailable(page: Page): Promise<void> {
    if (!(await isGhostAvailable(page))) {
        throw new Error(
            'PRECONDITION_MISSING: ghost widget (#s2id_ghost_id) is not bound. ' +
            'Current user lacks ROLE_ADMIN/ROLE_FIRM_ADMIN/ROLE_PROMOTIONS_DIRECTOR/ROLE_HR.'
        );
    }
}

/**
 * STEP 2: Open the ghost dropdown by clicking `a.select2-choice`.
 * Clicking `a.select2-focusser` or the hidden `input#ghost_id` does NOT open.
 */
export async function openGhostDropdown(page: Page): Promise<void> {
    const choice = page.locator('#s2id_ghost_id a.select2-choice');
    await expect(choice).toBeVisible({ timeout: 5000 });
    await expect(choice).toBeEnabled({ timeout: 3000 });
    await choice.click();

    const drop = activeSelect2Drop(page);
    await expect(drop).toBeVisible({ timeout: 5000 });
    // The drop's search input receives focus.
    const search = drop.locator('input.select2-input');
    await expect(search).toBeVisible({ timeout: 3000 });
    console.log('👻 openGhostDropdown: drop open, search input focused');
}

/**
 * STEP 3-4: Type the query (≥ 3 chars, single burst), wait for XHR to
 * settle, then click the target user's row.
 *
 * The server formats results as `<p>Name [Firm Name]</p>` via ghostFormatResult
 * (adminjs.html.twig:66-72), so `hasText: "Aaron Stack"` matches even in a
 * multi-firm account.
 */
export async function pickGhostTarget(
    page: Page,
    name: string,
    options: { quietMillis?: number } = {}
): Promise<void> {
    const { quietMillis = 2000 } = options;

    if (name.length < 3) {
        throw new Error(`pickGhostTarget: name "${name}" is < 3 chars — minimumInputLength=3, no XHR will fire.`);
    }

    const drop = activeSelect2Drop(page);
    const search = drop.locator('input.select2-input').first();
    // Single burst — retyping resets quietMillis (adminjs.html.twig:94).
    await search.fill('');
    await search.type(name, { delay: 20 });

    // Wait through the throttle + XHR round-trip.
    const searching = drop.locator('li.select2-searching');
    await searching.first().waitFor({ state: 'attached', timeout: 3500 }).catch(() => {});
    await page.waitForTimeout(quietMillis + 500);
    await searching.first().waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});

    const items = drop.locator('li.select2-result-selectable div.select2-result-label');
    const count = await items.count();
    if (count === 0) {
        throw new Error(`pickGhostTarget: no selectable results returned by /ghost_people for query "${name}".`);
    }

    const target = items.filter({ hasText: name }).first();
    await expect(target).toBeVisible({ timeout: 3000 });
    await target.click();

    // The drop closes; adminjs.html.twig:155 immediately calls
    // ghost_in(val) then val('') — DO NOT verify by reading #ghost_id.val().
    await drop.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    console.log(`👻 pickGhostTarget: clicked "${name}"`);
}

/**
 * STEP 5-6: Wait for /Admin_ghost_in → SSO cookie → location.reload() to
 * complete. Total elapsed 1–5s depending on SSO latency.
 *
 * Failure modes handled:
 *   - `toastr.error('Error ghosting. …')` (adminjs.html.twig:27) → SCENARIO_FAILED
 *   - Silent failure: no toast, no reload → SILENT_FAILURE at 5s mark
 */
export async function waitForGhostReload(
    page: Page,
    timeout = 15000
): Promise<void> {
    // Race the reload against a possible error toast.
    const navPromise = page.waitForLoadState('load', { timeout }).catch(() => null);
    const errorPromise = page
        .locator('.toast-error, .toast-message.toast-error')
        .filter({ hasText: /ghost/i })
        .first()
        .waitFor({ state: 'visible', timeout: 5000 })
        .then(() => 'error' as const)
        .catch(() => null);

    const result = await Promise.race([
        navPromise.then(() => 'nav' as const),
        errorPromise,
    ]);

    if (result === 'error') {
        const msg = await page.locator('.toast-error, .toast-message').last().textContent().catch(() => '') || '';
        throw new Error(`SCENARIO_FAILED: ghost error toast: "${msg.trim()}"`);
    }

    // Silent-failure check: no toast, no reload after 5s.
    if (result !== 'nav') {
        const stillOnSamePage = !page.url().includes('promo_login');
        const noToast = !(await page.locator('.toast-error').first().isVisible({ timeout: 200 }).catch(() => false));
        if (stillOnSamePage && noToast) {
            throw new Error('SILENT_FAILURE: no toast + no reload observed 5s after ghost pick. Ghost POST likely failed silently.');
        }
    }

    // Extra beat so the reloaded page's initial JS starts running.
    await page.waitForTimeout(500);
    console.log('👻 waitForGhostReload: reload observed');
}

/**
 * STEP 6 verification: confirm the reloaded page reflects an impersonated
 * session. `#be_me` binds at adminjs.html.twig:162; it exists only for
 * ghosted sessions (`app.session.get('ghosted') == 1`).
 */
export async function verifyGhosted(page: Page): Promise<void> {
    // #be_me should now be in the top nav.
    const beMe = page.locator('#be_me');
    await expect(beMe).toHaveCount(1, { timeout: 10000 });
    // #ghost_id still exists so a ghosted user can re-ghost.
    await expect(page.locator('#ghost_id')).toHaveCount(1);
    console.log('👻 verifyGhosted: #be_me present, ghost session active');
}

/**
 * Orchestrator: full ghost-login flow. Caller is responsible for having
 * the Home tab (or any admin-capable page) already loaded.
 *
 * @param name  the target user's displayed name (≥ 3 chars). Matches the
 *              formatted result label `<p>Name [Firm Name]</p>`.
 */
export async function ghostLogin(page: Page, name: string): Promise<void> {
    await assertGhostAvailable(page);
    try {
        await openGhostDropdown(page);
        await pickGhostTarget(page, name);
        await waitForGhostReload(page);
        await verifyGhosted(page);
    } catch (err) {
        // Recovery: close any stuck drop before propagating.
        await closeAnySelect2Drop(page).catch(() => {});
        throw err;
    }
}

/**
 * Recovery utility: if the drop is stuck open with no results after 10s,
 * press Escape to close it and check whether the session lost auth
 * (redirect to /promo_login).
 */
export async function recoverStuckGhostDrop(page: Page): Promise<void> {
    await closeAnySelect2Drop(page);
    if (page.url().includes('/promo_login')) {
        throw new Error('Ghost recovery: session lost auth — landed on /promo_login.');
    }
}
