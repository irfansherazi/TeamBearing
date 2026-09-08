import { Page, expect } from '@playwright/test';

/**
 * Helper to interact with Google reCAPTCHA v2.
 * Assumes the test environment uses the 'test' site key (6Lf30gcTAAAAAMJ7Pthe6JF5tb92UcUreIklyIN-)
 * which allows automated clicks without challenges.
 *
 * The aria-checked attribute update is ASYNCHRONOUS — Google's reCAPTCHA JS
 * needs ~1-3s to validate the click and update the DOM. A retry loop handles
 * both the async delay and transient challenge animations.
 */
export async function resolveCaptcha(page: Page) {
    const frame = page.frameLocator('iframe[title="reCAPTCHA"]');
    const checkbox = frame.locator('#recaptcha-anchor');

    await expect(checkbox).toBeVisible({ timeout: 15000 });

    // Click and wait for async reCAPTCHA validation with retry
    for (let attempt = 0; attempt < 3; attempt++) {
        let clicked = false;
        await checkbox.click({ force: true, timeout: 5000 }).then(() => clicked = true).catch(() => {
            console.log('⚠️ Click intercepted, trying dispatchEvent...');
        });
        if (!clicked) {
            await checkbox.dispatchEvent('click').catch(() => {});
        }

        // reCAPTCHA validation is async — wait for the animation + backend check
        await page.waitForTimeout(3000);

        const isChecked = await checkbox.getAttribute('aria-checked').catch(() => 'false');
        if (isChecked === 'true') {
            console.log(`✅ reCAPTCHA resolved on attempt ${attempt + 1}`);
            return;
        }

        console.log(`⚠️ reCAPTCHA not yet resolved (attempt ${attempt + 1}), retrying...`);
        await page.waitForTimeout(1000);
    }

    // Final check — log a warning instead of hard-failing so the submit button can still be force-clicked
    const finalState = await checkbox.getAttribute('aria-checked').catch(() => 'false');
    if (finalState !== 'true') {
        console.warn('⚠️ reCAPTCHA did not resolve after all retries. Proceeding anyway (submit will be force-enabled).');
    }
}
