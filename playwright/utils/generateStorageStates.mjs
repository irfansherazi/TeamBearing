import { chromium } from 'playwright';
import { login } from './loginHelper.mjs';
import fs from 'fs';
import path from 'path';
import 'dotenv/config';

const ENV_MAP = {
  prod: 'https://vcreative.net',
  test: 'https://two-test.vcreative.net',
  smoke: 'https://smoketest.vcreative.net',
  qa: 'https://qa.vcreative.net'
};

const PWDEBUG = "0";
const TEST_ENV = process.env.TEST_ENV || 'test'; // Default to smoke
const BASE_URL = ENV_MAP[TEST_ENV];

let users = [];
let userEntries = [];
const usersJsonPath = path.resolve('./playwright/fixtures/users/users.json');
if (fs.existsSync(usersJsonPath)) {
  try {
    userEntries = JSON.parse(fs.readFileSync(usersJsonPath, 'utf-8'));
    users = Array.from(new Set(userEntries.map(u => u.email).filter(Boolean)));
  } catch (e) {
    console.warn('Failed to parse users.json, using static fallback:', e);
  }
}

if (!users.length) {
  users = [
    'imail-test+DemoTopBiller@vcreativeinc.com',
    'imail-test+DemoProdDirector@vcreativeinc.com',
    'imail-test+DemoTrafficDirector@vcreativeinc.com',
    'imail-test+DemoSalesExec@vcreativeinc.com',
    'imail-test+DemoProdMan@vcreativeinc.com',
    'imail-test+DemoProdWoman@vcreativeinc.com',
    'imail-test+DemoDigitalDir@vcreativeinc.com',
    'imail-test+DemoDigitalProd@vcreativeinc.com',
    'imail-test+DemoVoicer@vcreativeinc.com',
    'imail-test+DemoGM@vcreativeinc.com',
    'imail-test+DemoGraphicArtist@vcreativeinc.com',
    'imail-test+writer@vcreativeinc.com',
    'imail-test+DemoTrafficAssnt@vcreativeinc.com',
    'imail-test+SalesExec@vcreativeinc.com',
    'imail-test+DigitalDir@vcreativeinc.com',
    'imail-test+PMJock@vcreativeinc.com',
    'imail-test+GenMan@vcreativeinc.com',
    'imail-test+OtherProd@vcreativeinc.com',
    'imail-test+ProductionDir@vcreativeinc.com',
    'imail-test+SalesAssistant@vcreativeinc.com',
    'imail-test+SalesManager@vcreativeinc.com',
    'imail-test+TrafficDir@vcreativeinc.com',
    'imail-test+Voicing@vcreativeinc.com',
    'imail-test+CopyWriter@vcreativeinc.com',
  ];
}

const password = process.env.SHARED_TEST_PASSWORD || process.env.ROLE_DEFAULT_PASSWORD || 'Ep!cVCteam2026$';
const adminPassword = process.env.ADMIN_TEST_PASSWORD || 'Ep!cVCteam2026$';
// ══════════════════════════════════════════════════════════════════════════════
// PRODUCTION FIREWALL — these credentials use a shared test password and MUST
// NEVER authenticate against vcreative.net (production).
//
// Enforcement layers:
//   1. 'prod' is not in ENVIRONMENTS — it cannot be added without this block.
//   2. Runtime URL check below throws immediately if prod URL is somehow reached.
//   3. playwright.generated.config.ts independently rejects TEST_ENV=prod.
// ══════════════════════════════════════════════════════════════════════════════
const PROD_URL = 'https://vcreative.net';
const ALLOWED_ENVIRONMENTS = ['test', 'smoke', 'qa']; // 'prod' is intentionally absent and must stay absent.

for (const env of ALLOWED_ENVIRONMENTS) {
  const url = ENV_MAP[env];
  if (!url || url === PROD_URL || url.includes('vcreative.net') && !url.includes('-') && !url.includes('smoketest') && !url.includes('qa.')) {
    throw new Error(
      `[SECURITY] Environment '${env}' resolved to production URL '${url}'.\n` +
      'Shared test credentials must NEVER be used against production. Aborting.'
    );
  }
}



(async () => {
  const browser = await chromium.launch({ headless: true });

  // If TEST_ENV is set and valid, only generate for that env (one invocation per env).
  // Fall back to all allowed environments when called directly without TEST_ENV.
  const envsToProcess = (TEST_ENV && ALLOWED_ENVIRONMENTS.includes(TEST_ENV))
    ? [TEST_ENV]
    : ALLOWED_ENVIRONMENTS;

  // Per-env accounting so we don't silently drop failures inside the parallel Promise.all.
  // Prior behavior: caught errors were console.error'd and immediately buried under the
  // other 16 parallel logins; the final "All storage states generated" message ran
  // regardless of whether any user actually landed. That's how Admin has been silently
  // missing from every env for months. Track outcomes and print a summary.
  const results = {};

  for (const env of envsToProcess) {

    const BASE_URL = ENV_MAP[env];
    console.log(`Running for environment: ${env}`);
    results[env] = { succeeded: [], failed: [] };

    // Serialize users within an env instead of Promise.all — the parallel path
    // launches 16 concurrent Chromium contexts against the same origin from one
    // container, which starves CPU (each page's DOM parse slows to a crawl) and
    // trips server-side rate limits on qa/prod-grade infra. Symptom in the
    // parallel path was `page.goto: Timeout 30000ms exceeded ... waiting until
    // "domcontentloaded"` — even the earliest lifecycle event couldn't fire in
    // 30s under contention. Serial execution is ~16× wall-clock slower per env
    // but robust on any container size. If wall-clock becomes an issue, batch
    // 2-3 at a time behind a small semaphore rather than reverting to full
    // parallel.
    for (const email of users) {
      const isAdmin = email.includes('admin');
      const currentPassword = isAdmin ? adminPassword : password;

      let userPart;
      if (isAdmin) {
        userPart = 'Admin';
      } else if (email.includes('+')) {
        userPart = email.split('+')[1].split('@')[0];
      } else {
        userPart = email.split('@')[0].replace(/\./g, '_');
      }

      try {
        const context = await browser.newContext();
        const page = await context.newPage();

        console.log(`Grabbing ${email} on ${BASE_URL}...`);
        await login(page, email, currentPassword, BASE_URL);

        // For products on a separate domain (e.g. vPPO's PHP app), navigate there
        // so the context captures cookies for that domain too before saving.
        const vppoEntry = userEntries.find(u => u.email === email && u.productUrl);
        if (vppoEntry && vppoEntry.productUrl) {
          const productDomain = vppoEntry.productUrl;
          console.log(`🌐 Navigating to product URL ${productDomain} to capture PHP-domain cookies...`);
          await page.goto(productDomain, { timeout: 30000, waitUntil: 'domcontentloaded' }).catch(
            () => console.warn(`⚠️  Could not navigate to productUrl ${productDomain} — PHP cookies may be missing.`)
          );
          // Brief pause so session cookies are flushed to the context
          await page.waitForTimeout(1000);
        }

        const storageDir = path.resolve(`./playwright/storage/${env}`);
        if (!fs.existsSync(storageDir)) fs.mkdirSync(storageDir, { recursive: true });

        const storageStatePath = path.join(storageDir, `storageState_${userPart}.json`);
        await context.storageState({ path: storageStatePath });

        // Save under exact username(s) if defined in users.json (e.g. vppo_account_executive)
        const matchingUsers = userEntries.filter(u => u.email === email);
        for (const uObj of matchingUsers) {
          if (uObj.username && uObj.username !== userPart) {
            const altPath = path.join(storageDir, `storageState_${uObj.username}.json`);
            await context.storageState({ path: altPath });
          }
        }

        console.log(`Saving ${email} (${userPart})`);

        await context.close();
        results[env].succeeded.push(userPart);
      } catch (error) {
        console.error(`❌ Error processing ${email} in ${env}:`, error);
        results[env].failed.push({ userPart, email, reason: (error && error.message) || String(error) });
      }
    }
  }

  await browser.close();

  // Loud, structured summary. Historically the final "all generated" line ran
  // even when Admin (and possibly others) failed — see the Family C investigation
  // in task heal-13-playwright-failures-on-two-test for context.
  let anyFailure = false;
  console.log('\n══════════════════════════════════════════════════════════════════');
  console.log('  Storage state generation summary');
  console.log('══════════════════════════════════════════════════════════════════');
  for (const env of envsToProcess) {
    const r = results[env];
    console.log(`\n  [${env}]  ${r.succeeded.length} succeeded, ${r.failed.length} failed`);
    if (r.succeeded.length) {
      console.log(`    ✅ succeeded: ${r.succeeded.join(', ')}`);
    }
    if (r.failed.length) {
      anyFailure = true;
      for (const f of r.failed) {
        console.log(`    ❌ FAILED — ${f.userPart} (${f.email})`);
        console.log(`         reason: ${f.reason}`);
      }
    }
  }
  console.log('══════════════════════════════════════════════════════════════════\n');

  if (anyFailure) {
    console.error(
      '⚠️  One or more storage states did not land. ' +
      'Tests that opt into a missing user (e.g. `test.use({ user: \'Admin\' })`) ' +
      'will fall through to a live-login retry in assumeUser, then time out on the topbar assertion.'
    );
    process.exitCode = 1;
  } else {
    console.log('✅ All storage states generated for all environments. Sessions closed.');
  }
})();