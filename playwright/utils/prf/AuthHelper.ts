/**
 * AuthHelper.ts — Authenticate through the vCreative SSO/promo login chain
 * and wait until the Home tab is fully rendered.
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/auth-and-sso.md
 *
 * The full "ready" state requires SIX distinct milestones:
 *   1. Reach /promo (or /app_test.php/promo in test env) after any SSO hops
 *   2. If /promo_login rendered, submit credentials
 *   3. After /login_check → /promo, wait for the shell (body.page-header-fixed + jQuery/App globals)
 *   4. Wait for the deferred #pg-content swap (1000ms setTimeout after DOM ready)
 *   5. Wait for FullCalendar's `.fc.fc-ltr` + `.fc-toolbar` to paint
 *   6. Give render_tasks (+3000ms) time to churn the DOM before asserting stability
 *
 * The whole cold-cache path can take 5–8 seconds. Do NOT snapshot before this.
 */

import { expect, Page, BrowserContext } from '@playwright/test';

/**
 * Register the "accept any dialog" handler BEFORE any navigation.
 * Early-load code paths and the "Discard unsaved modifications?" confirm
 * (functions.js.html.twig:13440) can fire browser confirms.
 *
 * IMPORTANT: register at the CONTEXT level so it survives navigations —
 * a page-level `page.on('dialog')` is scoped to the current Page instance.
 */
export function registerDialogAccept(target: Page | BrowserContext): void {
    target.on('dialog', d => {
        console.log(`⚠️ dialog auto-accepted: type=${d.type()} message="${d.message()}"`);
        d.accept().catch(() => {});
    });
}

/**
 * Detect whether this session is against the test environment.
 * The test discriminator is either `app_test.php` in the URL or
 * `currentEnv == 'test'` in JS (formbuilder.js.html.twig:660).
 */
export async function isTestEnvironment(page: Page): Promise<boolean> {
    if (page.url().includes('app_test.php')) return true;
    return await page.evaluate(() => {
        try {
            // @ts-expect-error — currentEnv is a global set in the app
            return typeof currentEnv !== 'undefined' && currentEnv === 'test';
        } catch { return false; }
    }).catch(() => false);
}

/**
 * Compute the /promo path for the given base URL, honoring the test-env
 * front-controller convention.
 */
export function promoUrl(baseUrl: string, useAppTest = false): string {
    const trimmed = baseUrl.replace(/\/+$/, '');
    return useAppTest ? `${trimmed}/app_test.php/promo` : `${trimmed}/promo`;
}

/**
 * STEP 1: Navigate to /promo. Waits for network idle to survive up to 3
 * redirect hops (rc → SSO gateway → back).
 *
 * Terminal states: /promo, /promo_login, or an SSO landing (vcreative.net).
 * The caller must inspect page.url() to decide what to do next.
 */
export async function landOnPromo(page: Page, baseUrl: string, useAppTest = false): Promise<void> {
    const url = promoUrl(baseUrl, useAppTest);
    console.log(`🔐 landOnPromo: navigating to ${url}`);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    // Follow any redirects to steady state.
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
    console.log(`🔐 landOnPromo: settled at ${page.url()}`);
}

/**
 * STEP 2-3: If /promo_login is showing, fill & submit credentials.
 * Returns true if login was performed, false if already authenticated.
 *
 * Runbook note: input#username has autofocus; a click-then-type races the
 * autofocus and drops the first char. Use .fill() (native input, not select2).
 */
export async function loginIfNeeded(
    page: Page,
    username: string,
    password: string
): Promise<boolean> {
    if (!page.url().includes('/promo_login')) return false;

    console.log('🔐 loginIfNeeded: /promo_login detected — submitting credentials');

    const userInput = page.locator('input#username');
    const passInput = page.locator('input#password');
    const submitBtn = page.locator('button#_submit');

    await expect(userInput).toBeVisible({ timeout: 8000 });
    await expect(passInput).toBeVisible({ timeout: 4000 });
    await expect(submitBtn).toBeVisible({ timeout: 4000 });

    await userInput.fill(username);
    await passInput.fill(password);

    // Submit fires POST /login_check → 302 /promo. Wait for the URL to settle.
    await Promise.all([
        page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}),
        submitBtn.click(),
    ]);

    // Bad credentials un-hide #loginerror (login.html.twig:174).
    const loginError = page.locator('div#loginerror');
    const hasClassHidden = await loginError.evaluate(el => el.classList.contains('hidden')).catch(() => true);
    if (!hasClassHidden) {
        const msg = ((await loginError.textContent().catch(() => '')) || '').trim();
        throw new Error(`loginIfNeeded: credentials rejected. #loginerror: "${msg}"`);
    }

    // After login the URL should end with /promo (or /app_test.php/promo).
    if (!/\/(app_test\.php\/)?promo(\/|$|\?)/.test(page.url())) {
        console.warn(`🔐 loginIfNeeded: post-login URL unexpected: ${page.url()}`);
    }
    return true;
}

/**
 * STEP 4: Wait for the initial shell to render.
 *   - body.page-header-fixed
 *   - .header.navbar
 *   - #pg-content
 *   - jQuery.noConflict + App global available (index.html.twig:64, base.footerjs.twig:33)
 */
export async function waitForHomeShell(page: Page, timeout = 20000): Promise<void> {
    await expect(page.locator('body.page-header-fixed')).toBeVisible({ timeout });
    await expect(page.locator('.header.navbar')).toBeVisible({ timeout });
    await expect(page.locator('#pg-content')).toBeAttached({ timeout });

    await page.waitForFunction(
        () => {
            try {
                // @ts-expect-error — App is defined by app.js
                return typeof jQuery !== 'undefined'
                    // @ts-expect-error
                    && typeof jQuery.noConflict === 'function'
                    // @ts-expect-error
                    && typeof App === 'object';
            } catch { return false; }
        },
        { timeout }
    );
    console.log('🔐 waitForHomeShell: shell + globals ready');
}

/**
 * STEP 5: Wait for the deferred #pg-content swap (fires on 1000ms setTimeout
 * after DOM ready — index.html.twig:113-115).
 *   - `#pg-content` now contains `.promo_tab_div`
 *   - `#promo-all.tab-pane.active` exists
 *   - `#promo-calendar` exists (calendar renders inside #promo-all)
 *
 * Cold cache: 5–8 seconds. Wait up to 15s.
 */
export async function waitForDeferredHome(page: Page, timeout = 15000): Promise<void> {
    await expect(page.locator('#pg-content .promo_tab_div')).toBeAttached({ timeout });
    await expect(page.locator('#promoTabs > ul.nav-pills > li.active.promo_home_tab')).toBeAttached({ timeout });
    await expect(page.locator('#promo-all.tab-pane.active')).toBeAttached({ timeout });
    await expect(page.locator('#promo-calendar')).toHaveCount(1, { timeout });
    console.log('🔐 waitForDeferredHome: home content swapped in');
}

/**
 * STEP 6: Wait for FullCalendar to render and for the New PRF button to
 * attach (for creation-capable roles).
 *
 * @param options.expectNewPrfButton
 *   - true (default): fail if the button does not appear within timeout.
 *   - false: this user's role is one of ROLE_ON_AIR / ROLE_FRONT_DESK /
 *            ROLE_PROMO_ASSISTANT / NOBODY (fullcal.js.html.twig:979) and the
 *            button legitimately never appears. Just wait for the toolbar.
 */
export async function waitForFullCalendar(
    page: Page,
    options: { expectNewPrfButton?: boolean; timeout?: number } = {}
): Promise<void> {
    const { expectNewPrfButton = true, timeout = 15000 } = options;

    await expect(page.locator('#promo-calendar div.fc.fc-ltr div.fc-toolbar')).toBeVisible({ timeout });

    if (expectNewPrfButton) {
        await expect(page.locator('#promo-calendar .fc-toolbar .fc-left button#create_new_prf')).toBeVisible({ timeout });
    }

    // render_tasks runs at +3000ms (fullcal.js.html.twig:1036) and can churn DOM.
    // Do not assume stability until then.
    await page.waitForTimeout(3200);
    console.log(`🔐 waitForFullCalendar: calendar stable${expectNewPrfButton ? ' + #create_new_prf visible' : ''}`);
}

/**
 * Orchestrator: full auth flow → Home ready.
 *
 * @param options.credentials  - required if the /promo_login step is expected
 * @param options.useAppTest   - hits `/app_test.php/promo` instead of `/promo`
 * @param options.expectNewPrfButton - see waitForFullCalendar
 */
export async function loginAndWaitForHomeReady(
    page: Page,
    baseUrl: string,
    options: {
        credentials?: { username: string; password: string };
        useAppTest?: boolean;
        expectNewPrfButton?: boolean;
    } = {}
): Promise<void> {
    // Register the confirm/alert handler before we navigate.
    registerDialogAccept(page);

    await landOnPromo(page, baseUrl, options.useAppTest);

    // SSO handoff to two-test.vcreative.net / vcreative.net is out of scope
    // per runbook (PRECONDITION_MISSING). Fail explicitly.
    if (/\/\/(two-test\.)?vcreative\.net\/?#/.test(page.url())) {
        throw new Error(
            `loginAndWaitForHomeReady: landed on external SSO landing (${page.url()}). ` +
            `Complete SSO out-of-band, then re-invoke.`
        );
    }

    if (page.url().includes('/promo_login')) {
        if (!options.credentials) {
            throw new Error('loginAndWaitForHomeReady: /promo_login rendered but no credentials supplied.');
        }
        await loginIfNeeded(page, options.credentials.username, options.credentials.password);
    }

    // The post-login redirect chain may push the user to /select-product if
    // their SSO record no longer grants promo access (DefaultController.php:50-63).
    if (!/\/(app_test\.php\/)?promo(\/|$|\?)/.test(page.url())) {
        throw new Error(
            `loginAndWaitForHomeReady: post-login URL is not /promo (got ${page.url()}). ` +
            `User may lack promo access.`
        );
    }

    await waitForHomeShell(page);
    await waitForDeferredHome(page);
    await waitForFullCalendar(page, { expectNewPrfButton: options.expectNewPrfButton });

    console.log('✅ Home tab fully rendered and ready.');
}

/**
 * Ready-state predicate matching the runbook's final check block.
 * Non-throwing — returns true/false. Handy for polling from tests.
 */
export async function isHomeReady(page: Page): Promise<boolean> {
    return await page.evaluate(() => {
        const active = document.querySelector('#promo-all.tab-pane.active');
        const calToolbar = document.querySelector('#promo-calendar .fc.fc-ltr .fc-toolbar');
        if (!active || !calToolbar) return false;
        const newBtn = document.querySelector('#create_new_prf') as HTMLElement | null;
        const btnVisible = !!newBtn && newBtn.offsetParent !== null;
        // Non-create roles legitimately have no button — accept toolbar-only.
        // Callers can invoke waitForFullCalendar with expectNewPrfButton=false to enforce.
        return btnVisible || !newBtn;
    }).catch(() => false);
}
