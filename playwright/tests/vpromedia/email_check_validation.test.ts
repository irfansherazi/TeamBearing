// playwright/tests/email_check_validation.test.ts
//
// Validation / debugging test for the email notification checker utility.
// Confirms the Apps Script endpoint is reachable, the retry logic works,
// and the subject parser correctly identifies all notification types.
//
// Parser tests run offline (no EMAIL_CHECKER_URL needed).
// Endpoint tests require: EMAIL_CHECKER_URL env var.
//
// Run:  $env:TEST_ENV="test"; $env:EMAIL_CHECKER_URL="<url>"; npx playwright test tests/email_check_validation.test.ts

import { test, expect } from '../../utils/setup';
import {
    checkEmailReceived,
    waitForEmail,
    parseEmailSubject,
    EMAIL_CHECKER_URL,
    type EmailCheckResult,
    type NotificationType,
} from '../../utils/Imail_Test_Email_Check';

// ---------------------------------------------------------------------------
// Parser unit tests — no network, always runnable
// ---------------------------------------------------------------------------

test.describe('parseEmailSubject', () => {
    const cases: { subject: string; type: NotificationType; client?: string; detail?: string }[] = [
        // New Spot variants
        { subject: 'New Spot: testing', type: 'new_spot', client: 'testing' },
        { subject: 'New Spot: Test Client', type: 'new_spot', client: 'Test Client' },
        { subject: 'New Spot: Hanso Foundation', type: 'new_spot', client: 'Hanso Foundation' },

        // Spot update variants
        { subject: 'Spot: Test Client Traffic change', type: 'spot_update', detail: 'Test Client Traffic change' },
        { subject: 'Spot: Hanso Foundation Revised', type: 'spot_update', detail: 'Hanso Foundation Revised' },

        // Spot Approved
        { subject: 'Spot Approved: Buy and Large Corporation - SPOT 01', type: 'spot_approved', client: 'Buy and Large Corporation', detail: 'SPOT 01' },

        // Blog
        { subject: 'Blog: Hanso Foundation - HANSO TEST', type: 'blog', client: 'Hanso Foundation', detail: 'HANSO TEST' },

        // Voice
        { subject: 'Voice: The Peach Pit - TEST2222 56', type: 'voice', client: 'The Peach Pit', detail: 'TEST2222 56' },

        // Unread Blogs digest
        { subject: 'Unread Blogs: TEST FORMATING and more...', type: 'unread_blogs', detail: 'TEST FORMATING and more...' },

        // Weekly Summary
        { subject: 'Weekly Summary', type: 'weekly_summary' },

        // Unknown / edge cases
        { subject: '', type: 'unknown' },
        { subject: 'Something Else', type: 'unknown', detail: 'Something Else' },
    ];

    for (const { subject, type, client, detail } of cases) {
        test(`parses "${subject || '(empty)'}" → ${type}`, async () => {
            const parsed = parseEmailSubject(subject);

            expect(parsed.notificationType).toBe(type);

            if (client !== undefined) {
                expect(parsed.client).toBe(client);
            }
            if (detail !== undefined) {
                expect(parsed.detail).toBe(detail);
            }
        });
    }
});

// ---------------------------------------------------------------------------
// Endpoint tests — require EMAIL_CHECKER_URL
// ---------------------------------------------------------------------------

const shouldSkip = !EMAIL_CHECKER_URL;

test.describe('Email Checker Endpoint', () => {
    test.describe.configure({ mode: 'serial' });
    test.setTimeout(120_000);

    test.beforeAll(() => {
        if (shouldSkip) {
            console.warn(
                '⏭️  EMAIL_CHECKER_URL is not set — skipping endpoint tests.',
            );
        }
    });

    test('Smoke: endpoint is reachable and returns valid JSON', async () => {
        test.skip(shouldSkip, 'EMAIL_CHECKER_URL is not set');

        const result: EmailCheckResult = await checkEmailReceived(
            'qa-automation@vcreative.net',
            `BOGUS_TITLE_${Date.now()}`,
        );

        expect(result).toBeDefined();
        expect(typeof result.found).toBe('boolean');
        expect(result.found).toBe(false);
        console.log('✅ Smoke test passed. Response:', JSON.stringify(result, null, 2));
    });

    test('Retry: waitForEmail exhausts retries gracefully', async () => {
        test.skip(shouldSkip, 'EMAIL_CHECKER_URL is not set');

        const startTime = Date.now();

        const result: EmailCheckResult = await waitForEmail(
            'qa-automation@vcreative.net',
            `BOGUS_RETRY_${Date.now()}`,
            { timeout: 15_000, interval: 5_000 },
        );

        const elapsed = Date.now() - startTime;

        expect(result.found).toBe(false);
        expect(elapsed).toBeGreaterThan(10_000);
        expect(elapsed).toBeLessThan(25_000);

        console.log(
            `✅ Retry test passed. Elapsed: ${(elapsed / 1000).toFixed(1)}s — Response:`,
            JSON.stringify(result, null, 2),
        );
    });

    test('(Manual) Verify a real email match', async () => {
        test.skip(shouldSkip, 'EMAIL_CHECKER_URL is not set');

        // ---------------------------------------------------------------
        // Before running: set MANUAL_SPOT_TITLE to a real subject term
        // that exists in the testing Gmail inbox within the last hour.
        // ---------------------------------------------------------------
        const MANUAL_RECIPIENT = 'qa-automation@vcreative.net';
        const MANUAL_SPOT_TITLE = 'REPLACE_ME_WITH_REAL_SPOT_TITLE';

        test.skip(
            MANUAL_SPOT_TITLE === 'REPLACE_ME_WITH_REAL_SPOT_TITLE',
            'Set MANUAL_SPOT_TITLE to a real value before running this test.',
        );

        const result = await waitForEmail(MANUAL_RECIPIENT, MANUAL_SPOT_TITLE, {
            timeout: 30_000,
            interval: 10_000,
        });

        expect(result.found).toBe(true);
        expect(result.subject).toBeDefined();
        expect(result.notificationType).toBeDefined();

        console.log('✅ Real email match found:', JSON.stringify(result, null, 2));
        console.log(`   Type: ${result.notificationType}, Client: ${result.client}, Detail: ${result.detail}`);
    });
});
