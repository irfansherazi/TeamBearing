/**
 * tests/core/memoryWatchSessionCredentials.spec.ts
 * Unit tests for Memory Watch ritual login identity helpers.
 */

import { describe, it, expect, afterEach } from 'vitest';
import {
    DEFAULT_RITUAL_ADMIN_EMAIL,
    resolveMemoryWatchCredentials,
    storageUserFromEmail,
    unquoteEnvValue,
} from '../../playwright/memory/lib/sessionCredentials';

const originalEmail = process.env.MEMORY_WATCH_EMAIL;
const originalPassword = process.env.MEMORY_WATCH_PASSWORD;
const originalShared = process.env.SHARED_TEST_PASSWORD;

afterEach(() => {
    if (originalEmail === undefined) {
        delete process.env.MEMORY_WATCH_EMAIL;
    } else {
        process.env.MEMORY_WATCH_EMAIL = originalEmail;
    }
    if (originalPassword === undefined) {
        delete process.env.MEMORY_WATCH_PASSWORD;
    } else {
        process.env.MEMORY_WATCH_PASSWORD = originalPassword;
    }
    if (originalShared === undefined) {
        delete process.env.SHARED_TEST_PASSWORD;
    } else {
        process.env.SHARED_TEST_PASSWORD = originalShared;
    }
});

const storageUserCases = [
    {
        description: 'uses the local part of an email as the storage stem',
        setup: () => ({ input: 'syed@vcreativeinc.com', expected: 'syed' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'keeps a role shorthand unchanged',
        setup: () => ({ input: 'DemoProdDirector', expected: 'DemoProdDirector' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'replaces dots in the local part',
        setup: () => ({ input: 'syed.ali@vcreativeinc.com', expected: 'syed_ali' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'falls back to user when the value is empty',
        setup: () => ({ input: '', expected: 'user' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
];

describe('storageUserFromEmail', () => {
    storageUserCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { input, expected } = setup();
            expectations(storageUserFromEmail(input), expected);
        });
    });
});

const unquoteCases = [
    {
        description: 'strips wrapping double quotes from a password',
        setup: () => ({ input: '"!Syed1992"', expected: '!Syed1992' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'leaves an unquoted password unchanged',
        setup: () => ({ input: '!Syed1992', expected: '!Syed1992' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'strips wrapping single quotes',
        setup: () => ({ input: "'secret'", expected: 'secret' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'trims blank input to empty',
        setup: () => ({ input: '   ', expected: '' }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
];

describe('unquoteEnvValue', () => {
    unquoteCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { input, expected } = setup();
            expectations(unquoteEnvValue(input), expected);
        });
    });
});

const credentialCases = [
    {
        description: 'unquotes MEMORY_WATCH_PASSWORD for the ritual',
        setup: () => {
            delete process.env.MEMORY_WATCH_EMAIL;
            process.env.MEMORY_WATCH_PASSWORD = '"!Syed1992"';
            return {
                ritual: true,
                expectedEmail: DEFAULT_RITUAL_ADMIN_EMAIL,
                expectedUser: 'syed',
                expectedPassword: '!Syed1992',
            };
        },
        expectations: (
            result: ReturnType<typeof resolveMemoryWatchCredentials>,
            expected: { expectedEmail: string; expectedUser: string; expectedPassword?: string }
        ) => {
            expect(result.email).toBe(expected.expectedEmail);
            expect(result.storageUser).toBe(expected.expectedUser);
            expect(result.password).toBe(expected.expectedPassword);
        },
    },
    {
        description: 'uses the default ritual admin email when env email is empty',
        setup: () => {
            delete process.env.MEMORY_WATCH_EMAIL;
            process.env.MEMORY_WATCH_PASSWORD = 'ritual-secret';
            return {
                ritual: true,
                expectedEmail: DEFAULT_RITUAL_ADMIN_EMAIL,
                expectedUser: 'syed',
            };
        },
        expectations: (
            result: ReturnType<typeof resolveMemoryWatchCredentials>,
            expected: { expectedEmail: string; expectedUser: string }
        ) => {
            expect(result.email).toBe(expected.expectedEmail);
            expect(result.storageUser).toBe(expected.expectedUser);
            expect(result.password).toBe('ritual-secret');
        },
    },
    {
        description: 'throws when ritual password is missing',
        setup: () => {
            delete process.env.MEMORY_WATCH_PASSWORD;
            return { ritual: true, expectedError: 'MEMORY_WATCH_PASSWORD' };
        },
        expectations: (
            _result: ReturnType<typeof resolveMemoryWatchCredentials> | null,
            expected: { expectedError: string },
            error?: Error
        ) => {
            expect(error?.message).toContain(expected.expectedError);
        },
    },
    {
        description: 'uses DemoProdDirector for non-ritual flows',
        setup: () => {
            delete process.env.MEMORY_WATCH_EMAIL;
            delete process.env.MEMORY_WATCH_PASSWORD;
            process.env.SHARED_TEST_PASSWORD = 'shared-secret';
            return {
                ritual: false,
                expectedEmail: 'DemoProdDirector',
                expectedUser: 'DemoProdDirector',
            };
        },
        expectations: (
            result: ReturnType<typeof resolveMemoryWatchCredentials>,
            expected: { expectedEmail: string; expectedUser: string }
        ) => {
            expect(result.email).toBe(expected.expectedEmail);
            expect(result.storageUser).toBe(expected.expectedUser);
            expect(result.password).toBe('shared-secret');
        },
    },
];

describe('resolveMemoryWatchCredentials', () => {
    credentialCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const data = setup() as {
                ritual: boolean;
                expectedEmail?: string;
                expectedUser?: string;
                expectedError?: string;
                expectedPassword?: string;
            };
            let result: ReturnType<typeof resolveMemoryWatchCredentials> | null = null;
            let error: Error | undefined;
            try {
                result = resolveMemoryWatchCredentials(data.ritual);
            } catch (err: unknown) {
                error = err as Error;
            }
            (expectations as (
                result: ReturnType<typeof resolveMemoryWatchCredentials> | null,
                expected: typeof data,
                error?: Error
            ) => void)(result, data, error);
        });
    });
});
