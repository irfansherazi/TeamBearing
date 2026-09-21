/**
 * tests/core/memoryWatchEnsureSession.spec.ts
 * Unit tests for Memory Watch login URL and storage-state path helpers.
 */

import path from 'path';
import { describe, it, expect } from 'vitest';
import {
    isSelectProductUrl,
    loginHashUrl,
    memoryWatchStorageFile,
} from '../../playwright/memory/lib/ensureSession';

const loginHashUrlCases = [
    {
        description: 'appends /#/login to a QA origin',
        setup: () => ({
            input: 'https://qa.vcreative.net',
            expected: 'https://qa.vcreative.net/#/login',
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'strips a trailing slash before appending the hash route',
        setup: () => ({
            input: 'https://qa.vcreative.net/',
            expected: 'https://qa.vcreative.net/#/login',
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'builds a local login URL',
        setup: () => ({
            input: 'http://localhost:4200',
            expected: 'http://localhost:4200/#/login',
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'treats a missing origin as /#/login',
        setup: () => ({
            input: '',
            expected: '/#/login',
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
];

const storageFileCases = [
    {
        description: 'joins the env folder with the role storage file',
        setup: () => ({
            storageDir: path.join('playwright', 'storage', 'qa'),
            user: 'DemoProdDirector',
            expected: path.join('playwright', 'storage', 'qa', 'storageState_DemoProdDirector.json'),
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'uses Admin for the ritual user file',
        setup: () => ({
            storageDir: path.join('playwright', 'storage', 'qa'),
            user: 'Admin',
            expected: path.join('playwright', 'storage', 'qa', 'storageState_Admin.json'),
        }),
        expectations: (result: string, expected: string) => {
            expect(result).toBe(expected);
        },
    },
];

describe('loginHashUrl', () => {
    loginHashUrlCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { input, expected } = setup();
            expectations(loginHashUrl(input), expected);
        });
    });
});

describe('memoryWatchStorageFile', () => {
    storageFileCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { storageDir, user, expected } = setup();
            expectations(memoryWatchStorageFile(storageDir, user), expected);
        });
    });
});

const selectProductUrlCases = [
    {
        description: 'detects the QA product chooser hash',
        setup: () => ({
            input: 'https://qa.vcreative.net/#/select-product',
            expected: true,
        }),
        expectations: (result: boolean, expected: boolean) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'detects a trailing-slash product chooser hash',
        setup: () => ({
            input: 'https://qa.vcreative.net/#/select-product/',
            expected: true,
        }),
        expectations: (result: boolean, expected: boolean) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'does not treat the login hash as the product chooser',
        setup: () => ({
            input: 'https://qa.vcreative.net/#/login',
            expected: false,
        }),
        expectations: (result: boolean, expected: boolean) => {
            expect(result).toBe(expected);
        },
    },
    {
        description: 'treats a missing URL as not the product chooser',
        setup: () => ({
            input: '',
            expected: false,
        }),
        expectations: (result: boolean, expected: boolean) => {
            expect(result).toBe(expected);
        },
    },
];

describe('isSelectProductUrl', () => {
    selectProductUrlCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { input, expected } = setup();
            expectations(isSelectProductUrl(input), expected);
        });
    });
});
