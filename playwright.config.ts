/**
 * playwright.config.ts
 * =====================
 * Root Playwright configuration for vQA static test library.
 *
 * Consumed by:
 *   - npx playwright test (direct CLI invocation)
 *   - backend/api/playwright_routes.py (POST /playwright/run subprocess)
 *   - playwright/utils/setup.ts (imports TEST_ENV, ENV_MAP, BASE_URL)
 *
 * FEAT-052 / TASK-060 — AC-CFG-1, AC-CFG-3
 */

import { defineConfig } from '@playwright/test';
import dotenv from 'dotenv';

// Cursor's agent sets this to a temp folder with no Chrome binary.
if ((process.env.PLAYWRIGHT_BROWSERS_PATH || '').includes('cursor-sandbox-cache')) {
  delete process.env.PLAYWRIGHT_BROWSERS_PATH;
}

// Do not override vars already set by the CLI (e.g. memory:test --env=local).
dotenv.config();

// ---------------------------------------------------------------------------
// Environment map — must match backend VALID_ENVS
// ---------------------------------------------------------------------------

const ENV_MAP = {
  prod: 'https://vcreative.net',
  test: 'https://two-test.vcreative.net',
  smoke: 'https://smoketest.vcreative.net',
  qa: 'https://qa.vcreative.net',
  local: 'http://localhost:4200',
} as const;

type Env = keyof typeof ENV_MAP;

// Current environment (set by TEST_ENV in .env or CLI: TEST_ENV=test npx playwright test)
const TEST_ENV = ((process.env.TEST_ENV as Env) || 'test') satisfies Env;

if (!ENV_MAP[TEST_ENV]) {
  throw new Error(
    `Invalid TEST_ENV: "${TEST_ENV}". Must be one of: ${Object.keys(ENV_MAP).join(', ')}`
  );
}

const BASE_URL = ENV_MAP[TEST_ENV];

const isCI = !!process.env.CI;
const isDebugging = !!process.env.PWDEBUG;

console.log(`▶  Playwright config loaded — TEST_ENV=${TEST_ENV}, baseURL=${BASE_URL}`);

// ---------------------------------------------------------------------------
// Tests to skip (temporarily disabled or environment-dependent)
// ---------------------------------------------------------------------------

// Tests matching these patterns are excluded from default runs.
// Add patterns here for tests that require manual coordination or are unstable.
const IGNORED_TESTS: string[] = [
  // Add test file paths to ignore, e.g.:
  // 'tests/experimental/**',
];

// ---------------------------------------------------------------------------
// Browser projects
// ---------------------------------------------------------------------------

const allProjects = [
  {
    name: 'chromium',
    use: {
      browserName: 'chromium' as const,
      // Prevent sandbox issues in Docker/EC2
      launchOptions: {
        args: ['--no-sandbox', '--disable-dev-shm-usage'],
      },
    },
  },
  {
    name: 'firefox',
    use: { browserName: 'firefox' as const },
  },
  {
    name: 'webkit',
    use: { browserName: 'webkit' as const },
  },
];

// In CI or when PLAYWRIGHT_ALL_BROWSERS is not set, only run Chromium
// (webkit requires system-level deps not always present in CI)
const chromiumOnly = isCI && !process.env.PLAYWRIGHT_ALL_BROWSERS;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export default defineConfig({
  // Test files are in playwright/tests/ (*.test.ts — finalized tests only)
  // *.spec.ts files are WIP and excluded by the pattern below
  testDir: './playwright/tests',
  testMatch: '**/*.test.ts',
  testIgnore: IGNORED_TESTS,

  // TypeScript config for the playwright subtree
  tsconfig: './playwright/tsconfig.json',

  // Reporters
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  // Run tests in parallel
  fullyParallel: true,
  retries: 2,
  timeout: 90_000,        // 90s per test (some auth-heavy tests take 60s+)
  expect: { timeout: 20_000 },

  use: {
    baseURL: BASE_URL,
    // If VQA_HEADLESS=1 is set, run headless (e.g. for Parallel Headless Suite Runner).
    // Otherwise, default to headed (headless: false) which is required for vQA's visual capture.
    headless: process.env.VQA_HEADLESS === '1',
    trace: 'retain-on-failure',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
  },

  projects: chromiumOnly
    ? [allProjects[0]]  // Chromium only in CI
    : allProjects,       // All 3 browsers locally

  // Output directory for test artifacts
  outputDir: 'playwright/test-results',
});

// ---------------------------------------------------------------------------
// Named exports consumed by playwright/utils/setup.ts
// (import { BASE_URL, ENV_MAP, TEST_ENV } from '../../playwright.config')
// ---------------------------------------------------------------------------
const BASE_URL_EXPORT = BASE_URL;
export { TEST_ENV, ENV_MAP, BASE_URL_EXPORT as BASE_URL };
