/**
 * vPPO Authentication Helper
 * ===========================
 * Helper for logging into the vPPO platform using role credentials.
 */

import { Page, expect } from '@playwright/test';

export interface VppoLoginOptions {
  baseUrl?: string;
  email: string;
  password?: string;
}

/**
 * Log in to vPPO and wait for the dashboard to load.
 */
export async function loginToVppo(page: Page, options: VppoLoginOptions): Promise<void> {
  const targetUrl = options.baseUrl || process.env.VPPO_BASE_URL || 'https://two-test.vcreative.net';
  const password = options.password || process.env.ROLE_DEFAULT_PASSWORD_VPPO || process.env.ROLE_DEFAULT_PASSWORD || 'Ep!cVCteam2026$';

  await page.goto(targetUrl);

  // Fill credentials if login form is present
  const emailInput = page.getByRole('textbox', { name: /email/i });
  if (await emailInput.isVisible({ timeout: 5000 }).catch(() => false)) {
    await emailInput.fill(options.email);

    const passInput = page.getByRole('textbox', { name: /password/i });
    await passInput.fill(password);

    await page.getByRole('button', { name: /(login|sign in)/i }).click();
  }

  // Verify post-login auth signal (ssojwt cookie or non-login navigation)
  await page.waitForLoadState('domcontentloaded');
  const cookies = await page.context().cookies();
  const hasAuthCookie = cookies.some((c) => /ssojwt|vc2jwt|vcreative|session/i.test(c.name));
  const isOffLogin = !page.url().toLowerCase().includes('/login');

  expect(hasAuthCookie || isOffLogin).toBeTruthy();
}
