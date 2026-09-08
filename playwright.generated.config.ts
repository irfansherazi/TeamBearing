/**
 * playwright.generated.config.ts
 * ================================
 * Playwright configuration for AI-generated test specs.
 *
 * Generated specs live in playwright/tests/generated/*.spec.ts
 * and are produced by the linear pipeline (linear_runner.py).
 *
 * Run: TEST_ENV=test npx playwright test --config playwright.generated.config.ts
 */

import { defineConfig } from '@playwright/test';

const ENV_MAP = {
  prod:  'https://vcreative.net',
  test:  'https://two-test.vcreative.net',
  smoke: 'https://smoketest.vcreative.net',
  qa:    'https://qa.vcreative.net',
} as const;

type Env = keyof typeof ENV_MAP;
const TEST_ENV = ((process.env.TEST_ENV as Env) || 'test') satisfies Env;

// ── Safety guard: AI-generated benchmarks must NEVER run against production ──
if (TEST_ENV === 'prod') {
  throw new Error(
    '[vQA] BENCHMARK SAFETY: TEST_ENV=prod is forbidden for generated spec runs.\n' +
    'Benchmarks may only target: test | smoke | qa\n' +
    'Re-run with: TEST_ENV=test npx playwright test --config playwright.generated.config.ts'
  );
}

const BASE_URL = ENV_MAP[TEST_ENV];

console.log(`▶  Generated-spec runner — TEST_ENV=${TEST_ENV}, baseURL=${BASE_URL}`);

export default defineConfig({
  testDir:   './playwright/tests/generated',
  testMatch: '**/*.spec.ts',

  // Use the isolated tsconfig so pre-existing utils errors don't block runs
  tsconfig: './playwright/tsconfig.generated.json',

  reporter: [
    ['list'],
    ['json',  { outputFile: '.agent-logs/generated-run-results.json' }],
    ['html',  { open: 'never', outputFolder: 'playwright-report-generated' }],
  ],

  fullyParallel: false,   // Sequential for Week 2 — easier to read output
  workers:       1,       // One at a time — prevents server contention on two-test.vcreative.net
  retries:       1,       // One retry for transient browser/network crashes

  timeout:       90_000,
  expect:        { timeout: 20_000 },

  use: {
    baseURL:           BASE_URL,
    headless:          false,
    trace:             'retain-on-failure',
    actionTimeout:     30_000,
    navigationTimeout: 60_000,
    screenshot:        'only-on-failure',
    video:             'retain-on-failure',
    viewport:          { width: 1440, height: 900 },
  },

  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        launchOptions: {
          args: ['--no-sandbox', '--disable-dev-shm-usage'],
        },
      },
    },
  ],

  outputDir: 'playwright/test-results-generated',
});
