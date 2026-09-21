/**
 * tests/core/memoryWatchFailureSummary.spec.ts
 * Unit tests for Memory Watch's runner-side failure phase classifier.
 */

import { describe, it, expect } from 'vitest';
import { classifyMemoryWatchFailure } from '../../playwright/memory/lib/failureSummary';

const cases = [
    {
        description: 'identifies a login failure over an earlier setup warning',
        setup: () =>
            [
                '⚠️ STORAGE_DIR does not exist: /storage/qa',
                '⚠️ No available users detected. Proceeding without storage state.',
                'Error: expect(locator).toBeVisible() failed',
                '    at login (../utils/loginHelper.mjs:182:46)',
            ].join('\n'),
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Login / session');
            expect(result.reason).toBe('⚠️ STORAGE_DIR does not exist: /storage/qa');
        },
    },
    {
        description: 'identifies a Memory Watch login form that never appeared',
        setup: () =>
            'Error: Login form never appeared at https://qa.vcreative.net/#/login. Current URL: https://qa.vcreative.net/',
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Login / session');
        },
    },
    {
        description: 'identifies a missing Angular ghost panel after login',
        setup: () =>
            'Error: Ghost panel missing after login as syed@vcreativeinc.com. Need a vCreative admin (firm_id 1).',
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Ghost login');
        },
    },
    {
        description: 'identifies a ghost login failure',
        setup: () => 'Error: Could not ghost as Suzan Goritz: picker had no match',
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Ghost login');
        },
    },
    {
        description: 'identifies a dead-target timeout while the page fixture was setting up',
        setup: () => 'Test timeout of 90000ms exceeded while setting up "page".',
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Page load / connection');
            expect(result.reason).toBe('Test timeout of 90000ms exceeded while setting up "page".');
        },
    },
    {
        description: 'falls back to Unknown when nothing matches a known phase',
        setup: () => "Error: Cannot find module '@playwright/test'",
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Unknown');
            expect(result.reason).toBe("Error: Cannot find module '@playwright/test'");
        },
    },
    {
        description: 'truncates a very long first line',
        setup: () => `Error: ${'x'.repeat(400)}`,
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.reason.length).toBeLessThanOrEqual(200);
            expect(result.reason.endsWith('...')).toBe(true);
        },
    },
    {
        description: 'handles an empty error',
        setup: () => '',
        expectations: (result: ReturnType<typeof classifyMemoryWatchFailure>) => {
            expect(result.phase).toBe('Unknown');
            expect(result.reason).toBe('Unknown error');
        },
    },
];

describe('classifyMemoryWatchFailure', () => {
    cases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            expectations(classifyMemoryWatchFailure(setup()));
        });
    });
});
