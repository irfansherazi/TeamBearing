// playwright/utils/setup.ts

import { test as baseTest, expect } from '@playwright/test';
import type { Browser, BrowserContext, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { BASE_URL, ENV_MAP, TEST_ENV } from '../../playwright.config';
import { login, loginWithStoredSession, assumeUser, logout } from './loginHelper.mjs';

/**
 * Shared testing password for real user accounts in test environments.
 */
export const SHARED_TEST_PASSWORD = process.env.SHARED_TEST_PASSWORD || 'Ep!cVCteam2026$';

/**
 * Storage directory based on the test environment
 */
const STORAGE_DIR = process.env.STORAGE_DIR || path.resolve(__dirname, '..', 'storage', TEST_ENV);

/**
 * Product-specific base URLs.
 * vPPO lives on a separate PHP domain — tests must navigate here, not to BASE_URL.
 * The ENV_MAP for the PHP app mirrors the Angular gateway env suffix convention.
 */
const VPPO_URL_MAP: Record<string, string> = {
  test:  'http://hotfixes.sandbox.internal.vcreative.net/mytlc/mytlc_logged.php',
  smoke: 'http://smoketest.sandbox.internal.vcreative.net/mytlc/mytlc_logged.php',
  qa:    'http://qa.sandbox.internal.vcreative.net/mytlc/mytlc_logged.php',
  prod:  'http://www.vcreative.net/mytlc/mytlc_logged.php',
};
export const VPPO_BASE_URL = process.env.VPPO_BASE_URL || VPPO_URL_MAP[TEST_ENV] || VPPO_URL_MAP.test;

/**
 * Detect available users based on storage state files
 */
export function getDetectedUsers(userArray?: string[]): string[] {
  if (!fs.existsSync(STORAGE_DIR)) {
    console.warn(`⚠️ STORAGE_DIR does not exist: ${STORAGE_DIR}`);
    return [];
  }
  const allUsers = fs
    .readdirSync(STORAGE_DIR)
    .filter((file) => file.startsWith('storageState_') && file.endsWith('.json'))
    .map((file) => file.replace('storageState_', '').replace('.json', ''));
  return userArray ? allUsers.filter((user) => userArray.includes(user)) : allUsers;
}

const selectedUsers = process.env.USER_ARRAY?.split(',') || undefined;
const availableUsers = getDetectedUsers(selectedUsers);
const allUsers = availableUsers;

// Validate available users (graceful fallback instead of throwing)
if (availableUsers.length === 0) {
  console.warn('⚠️ No available users detected. Proceeding without storage state. You can generate users via storage or set USER_ARRAY/DEFAULT_USER env vars.');
}

// Update default user to be configurable (fallback to DemoProdDirector when none detected)
const defaultUser = process.env.DEFAULT_USER || availableUsers[0] || 'DemoProdDirector';

/**
 * Extend Playwright’s `test` fixture for default user and context setup
 */
export const test = baseTest.extend<{
  user: string;
  anonymous: boolean;
  context: BrowserContext;
  page: Page;
}>({
  // Default anonymous to false
  anonymous: [false, { option: true }],

  // Default user can be overridden via test.use({ user: '...' })
  user: [defaultUser, { option: true }],

  context: async ({ browser, anonymous, user, storageState }, use) => {
    const contextOptions: any = {};

    // Priority:
    // 1. Explicit storageState passed via test.use({ storageState: '...' })
    // 2. Shorthand user (no @) -> Look for storageState_<user>.json
    // 3. Anonymous mode -> Fresh session
    // 4. Fallback -> defaultUser storageState

    if (storageState) {
      console.log(`🔑 Using explicit storageState: ${storageState}`);
      contextOptions.storageState = storageState;
    } else if (anonymous) {
      console.log('👤 Running in anonymous mode. Starting with a fresh session.');
    } else if (user && !user.includes('@')) {
      let storagePath = path.join(STORAGE_DIR, `storageState_${user}.json`);
      if (!fs.existsSync(storagePath)) {
        const usersJsonPath = path.resolve('./playwright/fixtures/users/users.json');
        if (fs.existsSync(usersJsonPath)) {
          try {
            const userList = JSON.parse(fs.readFileSync(usersJsonPath, 'utf-8'));
            const found = userList.find((u: any) => u.username === user || u.role === user);
            if (found && found.email && found.email.includes('+')) {
              const part = found.email.split('+')[1].split('@')[0];
              const altPath = path.join(STORAGE_DIR, `storageState_${part}.json`);
              if (fs.existsSync(altPath)) {
                storagePath = altPath;
              }
            }
          } catch (e) {}
        }
      }
      if (fs.existsSync(storagePath)) {
        console.log(`👤 Assuming session for testing user: ${user} (${path.basename(storagePath)})`);
        contextOptions.storageState = storagePath;
      } else {
        console.warn(`⚠️ Storage state file for user "${user}" not found at: ${storagePath}`);
      }
    } else if (user && user.includes('@')) {
      console.log(`👤 User identified as email (${user}). Manual login required.`);
    } else {
      // Final fallback to defaultUser if nothing else is specified
      const fallbackPath = path.join(STORAGE_DIR, `storageState_${defaultUser}.json`);
      if (fs.existsSync(fallbackPath)) {
        contextOptions.storageState = fallbackPath;
      }
    }

    const context = await browser.newContext(contextOptions);
    await use(context);
  },

  page: async ({ context, user, anonymous }, use) => {
    const page = await context.newPage();

    // Standardized authentication: If a user is specified and we are not in anonymous mode,
    // ensure the session is active before starting the test.
    if (!anonymous && user) {
      await assumeUser(page, user, SHARED_TEST_PASSWORD, BASE_URL);
    }

    await use(page);
  },
});

/**
 * Log test environment and detected users
 */
export function logPlaywrightTestInfo() {
  console.log(`🌎 TEST_ENV: ${TEST_ENV}`);
  console.log(`📂 STORAGE_DIR: ${STORAGE_DIR}`);
  console.log(`👥 Users Detected: ${availableUsers.join(', ') || '<none>'}`);
}

/**
 * Multiplier applied to hard test.setTimeout budgets so remote-hosted environments
 * (slower network + shared server) get proportionally more time without changing
 * the test logic itself.
 *   qa    → 2.5×  (e.g. 220 s → 550 s)
 *   test  → 2×    (two-test.vcreative.net — remote AWS, needs breathing room too)
 *   smoke → 2×
 *   else  → 1×    (reserved for future local/mock envs)
 */
export const ENV_TIMEOUT_MULTIPLIER =
    TEST_ENV === 'qa' ? 2.5 :
    TEST_ENV === 'smoke' ? 2 :
    TEST_ENV === 'test' ? 2 : 1;

export { expect, BASE_URL, VPPO_BASE_URL, TEST_ENV, ENV_MAP, STORAGE_DIR, allUsers, login, loginWithStoredSession, logout, selectedUsers };

/**
 * Optional: Extract context and page setup logic into a helper function
 */
export async function createTestContext(browser: Browser, storageStatePath: string) {
  const options: any = {};
  if (storageStatePath && fs.existsSync(storageStatePath)) {
    options.storageState = storageStatePath;
  }
  const context = await browser.newContext(options);
  const page = await context.newPage();
  return { context, page };
}
