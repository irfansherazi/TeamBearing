const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { isCursorSandboxBrowsersPath, prepareBrowserEnv } = require('./playwright-env');

describe('prepareBrowserEnv', () => {
    const cases = [
        {
            description: 'drops a Cursor sandbox browser path',
            setup: () => ({
                PLAYWRIGHT_BROWSERS_PATH: '/var/folders/T/cursor-sandbox-cache/abc/playwright',
                TEST_ENV: 'qa'
            }),
            expectations: (env) => {
                assert.equal(env.PLAYWRIGHT_BROWSERS_PATH, undefined);
                assert.equal(env.TEST_ENV, 'qa');
            }
        },
        {
            description: 'keeps a normal browser path on Windows or Mac',
            setup: () => ({
                PLAYWRIGHT_BROWSERS_PATH: 'C:\\Users\\me\\AppData\\Local\\ms-playwright',
                TEST_ENV: 'qa'
            }),
            expectations: (env) => {
                assert.equal(env.PLAYWRIGHT_BROWSERS_PATH, 'C:\\Users\\me\\AppData\\Local\\ms-playwright');
            }
        },
        {
            description: 'leaves env unchanged when no browser path is set',
            setup: () => ({ TEST_ENV: 'local' }),
            expectations: (env) => {
                assert.equal(Object.hasOwn(env, 'PLAYWRIGHT_BROWSERS_PATH'), false);
                assert.equal(env.TEST_ENV, 'local');
            }
        }
    ];

    cases.forEach(({ description, setup, expectations }) => {
        test(description, () => {
            expectations(prepareBrowserEnv(setup()));
        });
    });

    test('recognizes the sandbox folder name', () => {
        assert.equal(isCursorSandboxBrowsersPath('/tmp/cursor-sandbox-cache/x'), true);
        assert.equal(isCursorSandboxBrowsersPath('/Users/me/Library/Caches/ms-playwright'), false);
    });
});
