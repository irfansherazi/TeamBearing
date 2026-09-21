import fs from 'fs';
import path from 'path';
import type { Page } from '@playwright/test';
import { resolveLoginEmail } from '../../utils/loginHelper.mjs';
import { isAngularGhostAvailable } from './angularGhost';

const AUTH_SELECTOR = [
    '#top-navbar, .user-text, .vppo-icon, .layout-topbar, app-topbar',
    '.layout-topbar-start, .layout-topbar-menu, app-layout',
    '[class*="topbar"], .p-menubar, app-menu, #left-nav, #sidebar, .sidebar',
].join(', ');
const PRODUCT_CHOOSER = '#vpro-media-product-selector-btn button, #vpro-media-product-selector-btn';
const PRODUCT_TITLE = '#select-product-title';
const LOADER = '#loader, #loader-wrapper, app-v-loader';
const LANDING_TIMEOUT_MS = 45000;

export interface EnsureMemoryWatchSessionOptions {
    page: Page;
    baseUrl: string;
    user: string;
    password: string;
    storageDir: string;
    storageUser?: string;
    requireGhostPanel?: boolean;
}

/**
 * Build the hash login URL for a vSuite origin.
 *
 * @param baseUrl - Env origin such as https://qa.vcreative.net
 * @returns Origin with `/#/login`
 */
export function loginHashUrl(baseUrl: string): string {
    const trimmed = (baseUrl ?? '').replace(/\/$/, '');
    return `${trimmed}/#/login`;
}

/**
 * Storage-state path Memory Watch writes after a successful login.
 *
 * @param storageDir - Env folder such as playwright/storage/qa
 * @param user - Role shorthand such as DemoProdDirector
 * @returns JSON file path
 */
export function memoryWatchStorageFile(storageDir: string, user: string): string {
    return path.join(storageDir, `storageState_${user}.json`);
}

/**
 * Whether the browser is on the post-login product chooser.
 *
 * @param url - Current page URL
 * @returns True when the hash route is select-product
 */
export function isSelectProductUrl(url: string): boolean {
    return (url ?? '').toLowerCase().includes('select-product');
}

/**
 * Open `#/login`, sign in if needed, and save cookies for the next run.
 *
 * @param options - Page, origin, role, password, and storage folder
 * @returns void
 */
export async function ensureMemoryWatchSession(
    options: EnsureMemoryWatchSessionOptions
): Promise<void> {
    const { page, baseUrl, user, password, storageDir } = options;
    const email = resolveLoginEmail(user);
    const loginUrl = loginHashUrl(baseUrl);
    const storageUser = options.storageUser ?? user;
    const requireGhostPanel = options.requireGhostPanel ?? false;

    process.stdout.write(`Memory Watch signing in as ${email}\n`);
    await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: LANDING_TIMEOUT_MS });
    await waitForLoaderHidden(page);
    await waitForSessionLanding(page, loginUrl);

    if (await alreadyInApp(page)) {
        await pickProductIfNeeded(page);
        if (!requireGhostPanel || (await isAngularGhostAvailable(page))) {
            await saveStorage(page, storageDir, storageUser);
            return;
        }
        await clearBrowserSession(page);
        await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: LANDING_TIMEOUT_MS });
        await waitForLoaderHidden(page);
        await waitForSessionLanding(page, loginUrl);
        if ((await alreadyInApp(page)) && (!requireGhostPanel || (await isAngularGhostAvailable(page)))) {
            await saveStorage(page, storageDir, storageUser);
            return;
        }
    }

    await submitLoginForm(page, email, password);
    await waitUntilLeftLoginForm(page);
    await enterAppAndSave(page, storageDir, storageUser);
    if (requireGhostPanel && !(await isAngularGhostAvailable(page))) {
        throw new Error(
            `Ghost panel missing after login as ${email}. Need a vCreative admin (firm_id 1).`
        );
    }
}

/**
 * Wait until the full-page loader is gone or missing.
 *
 * @param page - Playwright page
 * @returns void
 */
async function waitForLoaderHidden(page: Page): Promise<void> {
    const loader = page.locator(LOADER).first();
    await loader.waitFor({ state: 'hidden', timeout: LANDING_TIMEOUT_MS }).catch(() => undefined);
}

/**
 * Wait for login, dashboard, or the product chooser.
 *
 * @param page - Playwright page
 * @param loginUrl - URL we navigated to
 * @returns void
 */
async function waitForSessionLanding(page: Page, loginUrl: string): Promise<void> {
    const username = page.locator('#username');
    const auth = page.locator(AUTH_SELECTOR).first();
    const chooser = page.locator(PRODUCT_CHOOSER).first();
    const productTitle = page.locator(PRODUCT_TITLE);
    try {
        await Promise.race([
            username.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            auth.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            chooser.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            productTitle.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
        ]);
    } catch {
        if (isSelectProductUrl(page.url())) {
            return;
        }
        throw new Error(
            `Login form never appeared at ${loginUrl}. Current URL: ${page.url()}`
        );
    }
}

/**
 * Type credentials and submit the email/password form.
 *
 * @param page - Playwright page
 * @param email - Login email
 * @param password - Login password without wrapping quotes
 * @returns void
 */
async function submitLoginForm(page: Page, email: string, password: string): Promise<void> {
    const username = page.locator('#username');
    const loginBtn = page.locator('#login');
    await waitForLoaderHidden(page);
    await username.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS });
    await username.fill(email);
    await page.locator('#password').fill(password);
    await waitForLoaderHidden(page);
    await loginBtn.waitFor({ state: 'visible', timeout: 10000 });
    await page
        .waitForFunction(
            () => {
                const btn = document.getElementById('login');
                return !!btn && !(btn as HTMLButtonElement).disabled;
            },
            { timeout: 10000 }
        )
        .catch(() => undefined);
    await loginBtn.click();
}

/**
 * Wait until the login form is gone, the app shell is up, or a login error shows.
 *
 * @param page - Playwright page after clicking Login
 * @returns void
 */
async function waitUntilLeftLoginForm(page: Page): Promise<void> {
    const loginError = page.locator('.form-signin .alert-danger').first();
    const mfa = page.locator('#mfaCode');
    try {
        await Promise.race([
            page.locator('#username').waitFor({ state: 'hidden', timeout: LANDING_TIMEOUT_MS }),
            page.locator(AUTH_SELECTOR).first().waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            page.locator(PRODUCT_TITLE).waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            page.locator(PRODUCT_CHOOSER).first().waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            loginError.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
            mfa.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS }),
        ]);
    } catch {
        throw new Error(
            `Memory Watch login did not leave the login form. Current URL: ${page.url()}`
        );
    }
    if (await mfa.isVisible().catch(() => false)) {
        throw new Error('Login requires MFA. Memory Watch cannot complete MFA.');
    }
    if (await loginError.isVisible().catch(() => false)) {
        const text = (await loginError.innerText().catch(() => '')).trim();
        throw new Error(`Login failed: ${text || 'unknown error'}`);
    }
}

/**
 * Whether the session is already past the email/password form.
 *
 * @param page - Playwright page
 * @returns True when dashboard or product chooser is showing
 */
async function alreadyInApp(page: Page): Promise<boolean> {
    if (isSelectProductUrl(page.url())) {
        return true;
    }
    if (await isAuthenticated(page)) {
        return true;
    }
    const chooser = page.locator(PRODUCT_CHOOSER).first();
    const productTitle = page.locator(PRODUCT_TITLE);
    return (
        (await chooser.isVisible().catch(() => false)) ||
        (await productTitle.isVisible().catch(() => false))
    );
}

/**
 * Whether the authenticated shell is already on screen.
 *
 * @param page - Playwright page
 * @returns True when a dashboard/nav marker is visible
 */
async function isAuthenticated(page: Page): Promise<boolean> {
    const auth = page.locator(AUTH_SELECTOR).first();
    return auth.isVisible().catch(() => false);
}

/**
 * Pick vProMedia if needed, then confirm the app shell and save cookies.
 *
 * @param page - Playwright page
 * @param storageDir - Env storage folder
 * @param user - Role shorthand
 * @returns void
 */
async function enterAppAndSave(page: Page, storageDir: string, user: string): Promise<void> {
    await pickProductIfNeeded(page);
    if (!(await isAuthenticated(page))) {
        throw new Error(
            `Memory Watch login did not reach the app. Current URL: ${page.url()}`
        );
    }
    await saveStorage(page, storageDir, user);
}

/**
 * Write Playwright storage state for the next Memory Watch run.
 *
 * @param page - Playwright page
 * @param storageDir - Env storage folder
 * @param user - Storage file stem
 * @returns void
 */
async function saveStorage(page: Page, storageDir: string, user: string): Promise<void> {
    if (!fs.existsSync(storageDir)) {
        fs.mkdirSync(storageDir, { recursive: true });
    }
    await page.context().storageState({ path: memoryWatchStorageFile(storageDir, user) });
}

/**
 * Drop cookies and web storage so a different admin can log in.
 *
 * @param page - Playwright page
 * @returns void
 */
async function clearBrowserSession(page: Page): Promise<void> {
    await page.context().clearCookies().catch(() => undefined);
    await page.evaluate(() => {
        window.localStorage.clear();
        window.sessionStorage.clear();
    }).catch(() => undefined);
}

/**
 * Click vProMedia on the product chooser when that screen is showing.
 *
 * @param page - Playwright page
 * @returns void
 */
async function pickProductIfNeeded(page: Page): Promise<void> {
    if (!isSelectProductUrl(page.url())) {
        const chooserVisible = await page.locator(PRODUCT_CHOOSER).first().isVisible().catch(() => false);
        if (!chooserVisible) {
            return;
        }
    }
    const chooser = page.locator(PRODUCT_CHOOSER).first();
    await chooser.waitFor({ state: 'visible', timeout: LANDING_TIMEOUT_MS });
    await chooser.click({ force: true });
    await page.locator(AUTH_SELECTOR).first().waitFor({
        state: 'visible',
        timeout: LANDING_TIMEOUT_MS,
    });
}
