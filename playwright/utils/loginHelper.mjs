import { expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

/** QA rejects doc+test_admin — use the known ghost-capable admin instead. */
const QA_ADMIN_EMAIL = 'Suzan.Goritz@pattisonmedia.com';

/**
 * Resolve a username/role shorthand to a login email.
 *
 * @param identifier - Username, role, or email
 * @param env - TEST_ENV value (qa, test, smoke, local)
 * @returns Email for login
 */
export function resolveLoginEmail(identifier, env = process.env.TEST_ENV || 'test') {
    if (!identifier) {
        return identifier;
    }
    if (identifier.includes('@')) {
        if (
            env === 'qa' &&
            identifier.toLowerCase() === 'doc+test_admin@vcreativeinc.com'
        ) {
            return QA_ADMIN_EMAIL;
        }
        return identifier;
    }
    if (env === 'qa' && (identifier === 'Admin' || identifier === 'admin')) {
        return QA_ADMIN_EMAIL;
    }
    try {
        const usersJsonPath = path.resolve('./playwright/fixtures/users/users.json');
        if (fs.existsSync(usersJsonPath)) {
            const userList = JSON.parse(fs.readFileSync(usersJsonPath, 'utf-8'));
            const found = userList.find((u) => u.username === identifier || u.role === identifier);
            if (found?.email) {
                if (
                    env === 'qa' &&
                    String(found.email).toLowerCase() === 'doc+test_admin@vcreativeinc.com'
                ) {
                    return QA_ADMIN_EMAIL;
                }
                return found.email;
            }
        }
    } catch {
        return identifier;
    }
    return identifier;
}

/**
 * Manual Login with Session Detection
 */
export async function login(page, username, password, baseURL) {
    let loginEmail = resolveLoginEmail(username);
    if (loginEmail !== username) {
        console.log(`🔑 Resolved ${username} -> ${loginEmail}`);
    }

    console.log(`👤 Attempting login for: ${loginEmail} (role: ${username})`);

    // 1. Navigate to baseURL and determine state
    // If we are already on the dashboard or deep link, we might not need to goto baseURL
    const currentUrl = page.url();
    if (currentUrl.includes('#/vpro/') || currentUrl.includes('#/home')) {
        console.log('🔍 Already on an authenticated page. Checking identity...');
    } else {
        await page.goto(baseURL, { timeout: 30000, waitUntil: 'domcontentloaded' });
    }

    // Wait for either the login form OR the authenticated header
    const loginFormIndicator = page.locator('input[name="username"]');
    // Expanded indicators for better detection of modern Angular 19 dashboard and vPPO legacy navbar/sidebar
    const authenticatedIndicator = page.locator(
        '#top-navbar, .user-text, .vppo-icon, .layout-topbar, app-topbar, ' +
        '.layout-topbar-start, .layout-topbar-menu, app-layout, ' +
        '[class*="topbar"], .p-menubar, app-menu, #left-nav, #sidebar, .sidebar, ' +
        'a[href*="logout"], a:has-text("Logout"), a:has-text("My Account")'
    ).first();
    const productChooserIndicator = page.locator('#vpro-media-product-selector-btn button');

    console.log('🔍 Detecting session state...');

    // Check if we are obviously on the product selection page first
    if (page.url().includes('select-product')) {
        await productChooserIndicator.waitFor({ state: 'visible', timeout: 10000 }).catch(() => { });
    }

    const state = await Promise.race([
        loginFormIndicator.waitFor({ state: 'visible', timeout: 8000 }).then(() => 'logged-out'),
        authenticatedIndicator.waitFor({ state: 'visible', timeout: 8000 }).then(() => 'logged-in'),
        // Only wait for product selection if the URL suggests it or if we aren't seeing the other two
        page.url().includes('select-product') || !(await loginFormIndicator.isVisible() || await authenticatedIndicator.isVisible())
            ? productChooserIndicator.waitFor({ state: 'visible', timeout: 5000 }).then(() => 'product-selection')
            : Promise.resolve('no-selection')
    ]).catch(() => 'unknown');

    console.log(`🔍 Current session state: ${state}`);

    if (state === 'logged-in' || state === 'product-selection') {
        console.log(`🔍 Session detected (${state}) at ${page.url()}. Verifying user identity...`);

        if (state === 'product-selection') {
            console.log('🔍 Selecting vProMedia from chooser...');
            await productChooserIndicator.click();
            // Wait for dashboard or redirection - handle potential long loads
            await page.waitForURL(/.*#(?!.*(login|select-product)).*/, { timeout: 30000 }).catch(() => console.log('Wait for dashboard URL timed out or skipped.'));
            await authenticatedIndicator.waitFor({ state: 'visible', timeout: 30000 });
        }

        // Wait for loader to disappear
        const loader = page.locator('app-v-loader #loader-wrapper, #loader-wrapper').first();
        try {
            console.log('⏳ Ensuring loader/overlay is hidden (up to 45s)...');
            await loader.waitFor({ state: 'hidden', timeout: 45000 });
            console.log('✅ Loader/Overlay hidden.');
        } catch (e) {
            console.log('⚠️ Loader/Overlay sync delay detected; attempting to proceed.');
        }

        try {
            // Open profile menu to see email
            // Based on discovery: .user-profile-info is the reliable clickable container
            const profileTrigger = page.locator('.user-profile-info, .p-avatar, .user-text:not(.user-email)').first();
            await profileTrigger.waitFor({ state: 'visible', timeout: 15000 });

            // Ensure menu is open by checking for email visibility, click if not present
            const emailLocator = page.locator('span.user-email, .user-dropdown-details span, .user-email').filter({ hasText: '@' }).first();
            if (!(await emailLocator.isVisible())) {
                await profileTrigger.click({ force: true });
                await page.waitForTimeout(1500); // Wait for menu open animation
            }

            try {
                await emailLocator.waitFor({ state: 'visible', timeout: 8000 });
            } catch {
                console.log('⚠️ Email locator not visible. Retrying profile trigger click...');
                await profileTrigger.click({ force: true });
                await page.waitForTimeout(1500);
                await emailLocator.waitFor({ state: 'visible', timeout: 8000 });
            }

            const activeEmail = (await emailLocator.textContent())?.trim().toLowerCase();

            console.log(`👤 Active session email: ${activeEmail}`);

            if (activeEmail === username.toLowerCase()) {
                console.log('✅ Correct user already logged in. Skipping login process.');
                // Close dropdown if it's still open (optional, but good practice)
                await page.mouse.click(10, 10);
                return;
            } else {
                console.log(`⚠️ Session active for DIFFERENT user (${activeEmail}). Logging out...`);
                await logout(page);
                // After logout, we should be on the login page or redirected to it
                await page.waitForTimeout(2000);
                await page.goto(baseURL, { timeout: 30000, waitUntil: 'domcontentloaded' });
            }
        } catch (error) {
            console.log(`⚠️ Session identity check failed: ${error.message || error}. Checking overall authenticated state...`);
            if (await authenticatedIndicator.isVisible()) {
                console.log('✅ Authenticated indicator is visible. Proceeding with active session.');
                return;
            } else {
                console.log('⚠️ Not authenticated. Clearing cookies and forcing a fresh login.');
                await page.context().clearCookies().catch(() => {});
                await page.evaluate(() => window.localStorage.clear()).catch(() => {});
                await page.evaluate(() => window.sessionStorage.clear()).catch(() => {});
                await page.goto(baseURL, { timeout: 30000, waitUntil: 'domcontentloaded' });
            }
        }
    }

    // Proceed with standard login flow
    //Debug Pause
    if (process.env.PWDEBUG === '1') await page.pause();

    const usernameField = page.locator('#username');
    if (!(await usernameField.isVisible({ timeout: 5000 }).catch(() => false))) {
        const loginUrl = `${String(baseURL || '').replace(/\/$/, '')}/#/login`;
        console.log(`🔑 Opening login page: ${loginUrl}`);
        await page.goto(loginUrl, { timeout: 30000, waitUntil: 'domcontentloaded' });
    }
    const loginLoaderEarly = page.locator('#loader, #loader-wrapper, app-v-loader').first();
    await loginLoaderEarly.waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});
    await usernameField.waitFor({ state: 'visible', timeout: 30000 });
    await usernameField.fill(loginEmail);
    await page.locator('#password').fill(password);

    // Wait for any loading overlay to clear before clicking submit — div#loader intercepts clicks.
    // waitFor('hidden') resolves immediately if the element doesn't exist or is already hidden.
    const loginLoader = page.locator('#loader, #loader-wrapper, app-v-loader').first();
    await loginLoader.waitFor({ state: 'hidden', timeout: 20000 }).catch(() => {});

    // Guard: only submit if the login form is still present. If the page navigated
    // away (e.g., storage-state session auto-logged in), skip to avoid a 30s timeout.
    const formStillPresent = await page.locator('button[type="submit"]').first().isVisible({ timeout: 5000 }).catch(() => false);
    if (!formStillPresent) {
        console.log('⚠️ Submit button not visible — form may have navigated away or session auto-resumed. Skipping submit.');
    } else {
        // force:true bypasses the "is element covered?" check — needed because the loader overlay
        // may still be fading out (CSS transition) even after loginLoader.waitFor resolves.
        await page.locator('button[type="submit"]').first().click({ force: true, timeout: 10000 }).catch(async () => {
            console.log('⚠️ Submit button click failed; trying DOM-level click...');
            const submitBtn = page.locator('button[type="submit"]').first();
            if (await submitBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
                await submitBtn.evaluate(el => el.click());
            }
        });
    }

    // Wait for either the dashboard OR the product chooser
    await Promise.race([
        authenticatedIndicator.waitFor({ state: 'visible', timeout: 20000 }),
        productChooserIndicator.waitFor({ state: 'visible', timeout: 20000 })
    ]).catch(() => console.log('Wait for post-login indicators finished or timed out.'));

    // Handle Product Chooser if it appears
    if (await productChooserIndicator.isVisible()) {
        console.log('🔍 Product chooser detected. Selecting vProMedia...');
        await productChooserIndicator.click();
        await authenticatedIndicator.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    }

    const isOffLogin = !page.url().toLowerCase().includes('/login') && page.url() !== 'about:blank';
    if (!isOffLogin) {
        await expect(authenticatedIndicator).toBeVisible();
    }
    console.log(`✅ Successfully logged in as: ${username}`);
}

/**
 * Manual Logout
 */
export async function logout(page) {
    console.log('🚪 Logging out...');
    const profileTrigger = page.locator('.user-profile-info, .p-avatar, .user-text:not(.user-email)').first();
    const logoutBtn = page.locator('#user-log-out, a:has-text("Logout"), .logout-link').first();

    if (await logoutBtn.isVisible()) {
        console.log('🚪 Logout button is already visible. Clicking...');
        await logoutBtn.click({ force: true }).catch(async () => {
            console.log('⚠️ Logout button click failed; trying DOM-level click...');
            await logoutBtn.evaluate(el => el.click());
        });
        await page.waitForLoadState('domcontentloaded').catch(() => {});
        return;
    }

    if (await profileTrigger.isVisible()) {
        console.log('🚪 Profile trigger visible. Clicking once to expand...');
        await profileTrigger.click().catch(async () => {
            console.log('⚠️ Profile trigger click failed; trying DOM-level click...');
            await profileTrigger.evaluate(el => el.click());
        });
        await page.waitForTimeout(1000); // Wait for transition

        await logoutBtn.waitFor({ state: 'visible', timeout: 5000 });
        await logoutBtn.click().catch(async () => {
            console.log('⚠️ Logout button click failed; trying DOM-level click...');
            await logoutBtn.evaluate(el => el.click());
        });
        await page.waitForLoadState('domcontentloaded').catch(() => {});
    }
}

/**
 * Assumes a user session based on the provided identifier (email or shorthand)
 */
export async function assumeUser(page, identifier, password, baseURL) {
    if (!identifier) identifier = process.env.DEFAULT_USER || 'DemoProdDirector';

    if (identifier.includes('@')) {
        console.log(`🚀 Email detected (${identifier}). Performing manual login...`);
        await login(page, identifier, password, baseURL);
    } else {
        console.log(`🚀 Testing user detected (${identifier}). Ensuring session via storage state...`);
        // In the new setup.ts, shorthand users have their storageState injected at the context level.
        // We just navigate to the correct product URL and verify.

        // Look up productUrl from users.json for product-specific routing
        // (e.g. vPPO users land on a separate PHP domain, not the Angular baseURL)
        let navigationUrl = baseURL;
        let userProduct = null;
        try {
            const fs = await import('fs');
            const path = await import('path');
            const usersJsonPath = path.resolve('./playwright/fixtures/users/users.json');
            if (fs.existsSync(usersJsonPath)) {
                const userList = JSON.parse(fs.readFileSync(usersJsonPath, 'utf-8'));
                const found = userList.find(u => u.username === identifier || u.role === identifier);
                if (found) {
                    userProduct = found.product;
                    if (found.productUrl) {
                        navigationUrl = found.productUrl;
                        console.log(`📍 User '${identifier}' is a ${found.product} user. Navigating to product URL: ${navigationUrl}`);
                    }
                }
            }
        } catch (e) { /* ignore — fall back to baseURL */ }

        await page.goto(navigationUrl, { timeout: 30000, waitUntil: 'domcontentloaded' });

        // For vPPO (PHP app): auth is determined by whether we are NOT on a login page.
        // The PHP app has no Angular topbar, so CSS selectors don't apply.
        const isVppo = userProduct === 'vppo' ||
            navigationUrl.includes('hotfixes.sandbox.internal.vcreative.net') ||
            navigationUrl.includes('mytlc');

        if (isVppo) {
            // For the vPPO PHP app, just confirm we're on the dashboard URL (not login/select-product)
            const currentUrl = page.url();
            const onDashboard = currentUrl.includes('mytlc_logged') || currentUrl.includes('mytlc');
            const onLogin = currentUrl.includes('login') || currentUrl.includes('select-product');

            if (onDashboard) {
                console.log(`✅ vPPO session confirmed via URL: ${currentUrl}`);
            } else if (onLogin || !onDashboard) {
                console.log(`⚠️ vPPO: Not on dashboard (at ${currentUrl}). Falling back to live login...`);
                // Resolve email for live login
                let resolvedEmail = resolveLoginEmail(identifier);
                if (resolvedEmail !== identifier) {
                    console.log(`🔑 Resolved ${identifier} -> ${resolvedEmail}`);
                }
                await login(page, resolvedEmail, password, baseURL);
            }
            return;
        }

        // For non-vPPO products (Angular app) — check for Angular topbar/sidebar indicators
        const authenticatedIndicator = page.locator(
            '#top-navbar, .user-text, .vppo-icon, .layout-topbar, app-topbar, ' +
            '.layout-topbar-start, .layout-topbar-menu, app-layout, ' +
            '[class*="topbar"], .p-menubar, app-menu'
        ).first();
        const productChooserIndicator = page.locator('#vpro-media-product-selector-btn button');

        const isProductSelection = page.url().includes('select-product');
        if (isProductSelection) {
            console.log('🔍 Product selection page detected. Waiting for chooser...');
            await productChooserIndicator.waitFor({ state: 'visible', timeout: 15000 }).catch(() => { });
            await productChooserIndicator.click().catch(() => { });
        }

        console.log('🔍 Verifying dashboard access for session stability...');
        try {
            await expect(authenticatedIndicator).toBeVisible({ timeout: 20000 });
        } catch {
            console.log('⚠️ Dashboard not detected. Reloading to rehydrate session...');
            await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});

            const isLogin = page.url().includes('login');
            if (isLogin || !(await authenticatedIndicator.isVisible())) {
                console.log(`⚠️ Session expired or not logged in. Falling back to manual login for ${identifier}...`);
                let resolvedEmail = resolveLoginEmail(identifier);
                if (resolvedEmail !== identifier) {
                    console.log(`🔑 Resolved ${identifier} -> ${resolvedEmail}`);
                }
                await login(page, resolvedEmail, password, baseURL);
            } else {
                await expect(authenticatedIndicator).toBeVisible({ timeout: 20000 });
            }
        }
    }
}

/**
 * DEPRECATED: Use Playwright's native storageState in context creation via setup.ts
 * Manual Login Using Stored Session (for specialized contexts)
 */
export async function loginWithStoredSession(page, storageStatePath) {
    console.warn('⚠️ loginWithStoredSession is semi-deprecated. Prefer context-level storageState.');
    if (!storageStatePath) {
        throw new Error('Storage state path is required for stored session login.');
    }
    // Note: This cannot easily "switch" an existing page's context.
    // It is primarily used for deep investigative scripts.
    await page.goto('https://qa.vcreative.net/#/home', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#top-navbar, .vppo-icon, .layout-topbar, [class*="topbar"], app-topbar').first()).toBeVisible({ timeout: 10000 });
}

