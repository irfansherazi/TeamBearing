# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Scope & Boundaries

> **CRITICAL:** This agent is restricted to the `playwright/` subtree only.
> **DO NOT** modify `src/`, global CI configurations, or Angular application code unless explicitly requested.

---

## Global Context & Rules
The following files provide the "source of truth" for this environment. Claude should prioritize these over general knowledge:

* **Playwright Standards:** @../.agents/rules/playwright.md
* **Environment Manifest:** @../.agents/config/environment_manifest.md
* **Reasoning Protocol:** @../.agents/rules/reasoning.md

---

## UI Framework (Sprint 130+)

> Confirmed via live DOM inspection 2026-03-19. Applies to ALL environments.

- **Angular v19.2.20** (Signal-based components enabled; Zone.js remains active)
- **PrimeNG v19.x** — breaking component renames:
  - `<p-datepicker>` replaces `<p-calendar>` — do not query `p-calendar`
  - `<p-select>` replaces `<p-dropdown>` — do not query `p-dropdown`
- **CSS prefix**: `p-` is the sole active prefix (e.g., `.p-datepicker`, `.p-select`). The `ui-` prefix is completely absent in all environments.
- **PrimeNG Pass-Through (PT) attributes**: `[data-pc-name]` (e.g., `"select"`, `"datepicker"`) and `[data-pc-section]` (e.g., `"trigger"`, `"input"`) are globally enabled — prefer over `.p-element`/`.p-component` wrappers (deprecated).
- **Bulk Actions**: Moved to a bottom bar that appears only after row selection.
- **Checkboxes/Radios**: Use standard HTML `<input>`.

---

## Environments & Users

Full details: `../.agents/config/environment_manifest.md`

| TEST_ENV | URL |
| :--- | :--- |
| `qa` (default) | `https://qa.vcreative.net` |
| `test` | `https://two-test.vcreative.net` |
| `smoke` | `https://smoketest.vcreative.net` |
| `prod` | `https://vcreative.net` (read-only unless authorized) |

### Demo User Roster

| Shorthand | Role |
| :--- | :--- |
| `DemoProdDirector` | Production Director (default user) |
| `DemoGM` | General Manager |
| `DemoSalesExec` | Sales Executive (creates Production Orders) |
| `DemoDigitalDir` | Digital Director |
| `DemoDigitalProd` | Digital Producer |
| `DemoGraphicArtist` | Graphic Artist |
| `DemoProdMan` / `DemoProdWoman` | Production Staff |
| `DemoTrafficAssnt` | Traffic Assistant |
| `DemoTrafficDirector` | Traffic Director |
| `DemoVoicer` | Talent/Voicer |
| `writer` | Copywriter |
| `Admin` | vCreative Admin (`doc+test_admin@vcreativeinc.com`) |

Email pattern: `imail-test+<Shorthand>@vcreativeinc.com`
Global test password: stored in `.env` as `SHARED_TEST_PASSWORD`
Default Firm: **Demo Broadcasting** (Firm ID: 12345)

### vPPO User Roster

> vPPO is a **Type B (cross-domain)** product. Its app lives on a separate PHP domain from the Angular SSO gateway. See the Multi-Product Architecture section below before writing vPPO tests.

| Shorthand | Role |
| :--- | :--- |
| `vppo_account_executive` | Account Executive |
| `vppo_digital_director` | Digital Director |
| `vppo_dubber` | Dubber |
| `vppo_gm_gsm` | GM / GSM |
| `vppo_producer` | Producer |
| `vppo_production_manager` | Production Manager |
| `vppo_sales_assistant` | Sales Assistant |
| `vppo_sales_manager` | Sales Manager |
| `vppo_traffic_manager` | Traffic Manager |
| `vppo_voicer` | Voicer |
| `vppo_writer` | Writer |

vPPO app URL (test env): `http://hotfixes.sandbox.internal.vcreative.net/mytlc/mytlc_logged.php`
Auth detection: URL-based (the PHP app has no Angular topbar — CSS selectors don't apply)

---

## Playwright Architecture

### Directory Layout

```
playwright/
├── tests/           # *.test.ts = finalized (runs by default)
│   │                # *.spec.ts = WIP/draft (ignored by runner)
│   └── 2025/        # Also ignored by default runner
├── utils/
│   ├── setup.ts           # Core: re-exports test/expect/BASE_URL/STORAGE_DIR, user fixtures
│   ├── NavHelper.ts       # goToFolder, openSpot, scrollToFolder
│   ├── ViewHelper.ts      # getRowCount, selectRow, changeStatus, assignPOC
│   ├── OrderHelper.ts     # openQuickOrderForm, createAndSubmitOrder
│   ├── QO_helpers.ts      # calculateDueDate, generateRandomISCI/CartId, demoScripts
│   ├── globalSetup.ts     # Ensures storage/ dir exists, logs env info
│   └── session_nuke.js    # Nuke session state if auth issues arise
├── storage/
│   └── <TEST_ENV>/storageState_<UserName>.json   # Pre-authenticated sessions
└── storage/test_files/    # Example files for upload tests
```

**Test file naming**: `*.test.ts` = production ready; `*.spec.ts` = draft/WIP (ignored).

**Tests in `2025/`** are also ignored by the default runner — they are actively developed.

### Authentication

Always use the fixture pattern — never hardcode login flows:

```typescript
import { test, expect } from '../utils/setup';

// Shorthand (resolves via environment manifest)
test.use({ user: 'DemoProdDirector' });

// Or explicit storage state path
const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);
test.use({ storageState: storageStatePath });
```

Refresh storage states: `node playwright/utils/generateStorageStates.mjs`

---

## Multi-Product Architecture

vQA tests span two product architectures. Identify which you're on **before** writing a test.

| Type | Products | After login lands at | Test navigation |
| :--- | :--- | :--- | :--- |
| **Type A — Angular SPA** | vProMedia, vTrade, vEP | Same domain (`*.vcreative.net`) | `page.goto('/')` or relative paths work |
| **Type B — Cross-domain** | vPPO, vPromotions | Separate domain (PHP app, RC env) | **Must** use a named `PRODUCT_BASE_URL` constant |

### Why Type B is different

After the user selects vPPO (or vPromotions) from the product chooser at `two-test.vcreative.net`, the browser is redirected to a completely different domain. The Angular session cookies and topbar elements exist only on the SSO domain — the PHP app has neither. This means:

- `page.goto('/')` sends the browser back to the SSO product chooser, **not** the app
- CSS selectors like `#top-navbar` or `.layout-topbar` will never be found
- Auth detection is URL-based (are we on the PHP domain, not on a login page?)
- Storage states must capture cookies for **both** domains

### Type B Test Pattern

```typescript
// ✅ CORRECT — import the named constant, never a raw URL string
import { test, expect, VPPO_BASE_URL } from '../../utils/setup';

test.use({ user: 'vppo_account_executive' });

test('QA-NNN: ...', async ({ page }) => {
  // Always navigate to the product URL at the start of every step that needs it
  await page.goto(VPPO_BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  // ✅ Use getByRole for legacy PHP app — no Angular component classes
  await expect(page.getByRole('link', { name: /Spec Spots/i })).toBeVisible();
});
```

```typescript
// ❌ WRONG — '/' resolves to the SSO product chooser, not the vPPO app
await page.goto('/');
// ❌ WRONG — these selectors don't exist in the PHP app DOM
page.locator('#top-navbar')
page.locator('.layout-topbar')
```

### Available Product URL Constants (from `utils/setup.ts`)

| Product | Constant | Test env URL |
| :--- | :--- | :--- |
| vPPO | `VPPO_BASE_URL` | `http://hotfixes.sandbox.internal.vcreative.net/mytlc/mytlc_logged.php` |

### Adding a New Cross-Domain Product

If a new product is Type B:
1. Add `playwright_base_url` per-env to `backend/config/products.yaml`
2. The backend save-as-test handler auto-reads this and passes it to codegen
3. Export the constant from `playwright/utils/setup.ts` (e.g., `YOUR_PRODUCT_BASE_URL`)
4. Import it in test files — never hardcode the URL

---

## Playwright Test Conventions

### Selector Priority (highest → lowest)

1. `getByRole()`, `getByLabel()`
2. `data-testid` attributes
3. `[data-pc-name]` / `[data-pc-section]` (PrimeNG PT attributes)
4. Scoped locators: `.filter({ hasText })`, `.first()`, `locator('li', { hasText })`
5. **Never**: `.ng-tns-*` auto-generated classes, `.p-element`, `.p-component`, `ui-` prefix, auto-generated XPath/CSS chains

### Key Interaction Patterns

- **Visibility gate**: `await expect(locator).toBeVisible()` before every interaction
- **Blur-to-save**: Inline fields save on `Tab`/`blur`, not `Enter` — wait ~2s after editing
- **Row lock-out**: Editing a row locks others for ~5–10s; use `Escape` to dismiss drawers before moving on
- **Cart IDs**: Must be unique — always use `generateRandomCartId()` from `QO_helpers.ts`
- **Lazy-loaded lists**: `await element.scrollIntoViewIfNeeded()` before interacting
- **Dynamic deletion**: Use `while (count > 0)` loops, not `for` loops with static counts
- **Navigation**: Use `NavHelper.ts` (`goToFolder`, etc.) — do not hardcode deep-link URLs

### Serial (Dependent) Test Orchestration

For tests where Step 2 depends on Step 1 (e.g., upload → delete):

```typescript
test.describe.configure({ mode: 'serial' });
// Extract shared logic into plain .ts modules — never import a .test.ts into another test
```

### Debug Pauses (Always Conditional)

```typescript
if (process.env.PWDEBUG === '1') {
    console.log('🔍 Pausing before next step');
    await page.pause();
}
```

### Strict Mode — Scoping Repeated Elements

```typescript
// Bad: matches row text, link title, etc.
page.getByText('File Name')

// Good: scoped to list item
page.getByRole('listitem').filter({ hasText: 'File Name' }).first()
```

---

## Angular Source Conventions

Applies when touching `src/` (rare for this work scope):

- Template literals for string concatenation (no `+` concat)
- Arrow functions; `} else {` on the same line
- 4-space tabs, 120-character line width
- `$` suffix for Observables
- Unique hyphen-separated IDs on HTML elements with content
- JSDoc on all methods; no `console.log` or commented-out code committed
- Component selectors: `app-kebab-case`; directive selectors: `camelCaseAttribute`
- Path aliases: `@services/*`, `@shared/*`, `@SQLModels/*`, `@vppo/*`, `@vpromo/*`, `@vtrade/*`, `@vagency/*`

---

## Commit Message Format

```
<type>(<scope>): <subject>
```

Types: `build`, `docs`, `feature`, `bugfix`, `perf`, `refactor`, `style`, `test`

- Imperative present tense, no capital first letter, no trailing period
- Max 100 characters per line; footer closes issues: `Closes #123`

---

## Additional Context in `.agents/`

The `.agents/` folder contains established workflows and rules used with prior AI agents — relevant to reference when working on Playwright tests:

| Path | Contents |
| :--- | :--- |
| `../.agents/rules/repository_access.md` | Access boundaries |
| `../.agents/workflows/jira2playwright.md` | Full JIRA → Playwright conversion workflow |
| `../.agents/workflows/quick_test.md` | Manual QA browser testing workflow |
| `../.agents/skills/contextual_healer.md` | Protocol for diagnosing and fixing flaky tests |
| `../.agents/skills/test_review.md` | Test review checklist |
| `../knowledge-base/behaviors/` | vCreative system business logic (check before assuming feature behavior) |
