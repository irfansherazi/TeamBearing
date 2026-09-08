import { test, expect, BASE_URL, login } from '../../utils/setup';

test.describe('Verification: loginHelper Session Detection', () => {
    test.use({ anonymous: true });

    test('Verify session detection and skip logic', async ({ page }) => {
        test.setTimeout(240_000); // Two full login flows + user switch need more time in headless
        const username = 'doug.loepp@pattisonmedia.com';
        const password = process.env.SHARED_TEST_PASSWORD || 'Ep!cVCteam2026$'; // Use correct password

        console.log('--- Phase 1: Initial Login ---');
        await login(page, username, password, BASE_URL);

        console.log('--- Phase 2: Second Login (Should Skip) ---');
        // Call login again with the same user. It should detect the session and skip.
        // We can pass a dummy password to verify it's not trying to fill the form.
        await login(page, username, 'WRONG_PASSWORD', BASE_URL);

        console.log('--- Phase 3: Verify Authenticated State ---');
        await expect(page.locator('.vppo-icon, #top-navbar, .user-text').first()).toBeVisible({ timeout: 30000 });

        console.log('--- Phase 4: Session Mismatch (Different User) ---');
        // Now try to login as a different user. It should logout and re-login.
        const differentUser = 'sambelding@bahakelcomm.com';
        await login(page, differentUser, password, BASE_URL);

        console.log('--- Phase 5: Verify New Identity ---');
        const profileTrigger = page.locator('.user-text, .user-profile-info, .p-avatar').first();
        await expect(profileTrigger).toBeVisible({ timeout: 15000 });
        await profileTrigger.click();
        const newEmailLocator = page.locator('span.user-email, .user-dropdown-details span, .user-email').filter({ hasText: '@' }).first();
        await expect(newEmailLocator).toContainText(differentUser);
    });
});
