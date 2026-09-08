# Playwright — Copilot instructions for test authors (playwright/)

This file contains concise, actionable knowledge an AI coding agent should use when working only inside the `playwright/` folder. Do not change files above the `playwright/` folder unless explicitly asked.

## Key Principles
- Stay in the `playwright/` subtree unless a PR explicitly requests changes to the application or global CI.
- Prefer using existing helpers and storage-state files rather than hardcoding login flows. See `playwright/utils/setup.ts` and `playwright/utils/loginHelper.mjs`.

## Where to Start
- **Documentation**:
  - `playwright/Playwright_Knowledge_Sharing.md`: Human-friendly overview (environment map, examples).
  - `playwright/playwright.config.ts`: TEST_ENV mapping, baseURL, timeouts, and reporter configuration.
- **Utilities**:
  - `playwright/utils/setup.ts`: Fixtures, `STORAGE_DIR`, helpers exported to tests (use `test`, `expect`, `BASE_URL`, `STORAGE_DIR`).
  - `playwright/utils/QO_helpers.ts`: Utility functions for Quick Order (QO) form tests, including date calculations, string generation, and predefined field values.
  - `playwright/utils/globalSetup.ts`: Ensures `storage/` directory exists and logs system/test info.
  - `playwright/generateStorageStates.mjs` and `playwright/utils/loginHelper.mjs`: Utilities to generate or reuse storage states.

## Environment Configuration
- **Canonical Environment Variables**:
  - `TEST_ENV`: Environment name (`prod`, `test`, `smoke`, `qa`). Controls which `storage/<env>/` folder and `baseURL` are used.
  - `DEFAULT_USER`: Fallback user used by fixtures (overrides the default in `setup.ts`).
  - `USER_ARRAY`: Comma-separated list of users to limit test runs to specific storage states.
  - `USE_SPECIFIC_USERS`: Boolean flag used in some test helpers to choose a subset for validation.
  - `PLAYWRIGHT_BROWSER`: Optionally used in `globalSetup` logging to indicate the browser family.
- **Storage State Conventions**:
  - Storage state files live under `playwright/storage/<TEST_ENV>/` and follow the name `storageState_<UserName>.json`.
  - Use `generateStorageStates.mjs` (or `loginHelper.mjs`) to create or refresh these files. Tests rely on them via `test.use({ storageState })` or via the extended fixtures in `setup.ts`.
  - If storage states are missing, `setup.ts` currently throws an error. Prefer adding storage states rather than changing the fixture behavior.

## Test Writing Guidelines

- **Playwright Test Best Practices**

- Never use auto-generated class names like `.ng-tns-*`
- Prefer `getByRole()` or `getByLabel()` when possible
- Use `data-testid` attributes for stable selectors
- Do not rely on placeholder text or input order
- Use `await expect(locator).toBeVisible()` to ensure readiness before interaction


- **Fixtures**:
  - Extend `test` from `playwright/utils/setup.ts` to automatically get `user`, `context`, `page` fixtures.
  - Example:
    ```typescript
    const TEST_ENV = process.env.TEST_ENV || 'qa';
    const storageStatePath = path.resolve(__dirname, `../../storage/${TEST_ENV}/storageState_DemoProdDirector.json`);
    test.use({ storageState: storageStatePath });
    ```
- **Selectors**:
  - Prefer Playwright's role/locator selectors (`getByRole`, `getByText`, `locator`) over brittle CSS selectors.
- **Assertions**:
  - Use `expect` for robust validation.
- **Dynamic Data**:
  - Use utilities like `QO_helpers.ts` for generating test data.
- **Common Interactions**:
  - Use `page.once('dialog', handler)` to assert dialogs (e.g., `qa-257.test.ts` validates a print dialog).
  - For date pickers, calculate dates in test code (e.g., `ooo.test.ts`) and assert formatted strings.
- **Commenting**:
  - Add comments to explain non-obvious logic, especially around dynamic data or complex interactions.
  - Do not add comments for trivial code; focus on clarity where the intent may not be immediately clear.
  - Do not prefix comments or functions with 'Improved', 'Refined' or similar adjectives when modifying existing code.

## Serial Test Orchestration ("Playlist" Pattern)
- **Goal**: Run dependent tests in a strict sequence (e.g., file actions where Step 2 depends on Step 1).
- **Structure**:
  - **Modules**: core logic in `playwright/tests/*.ts` (pure async functions, no `test` blocks, e.g., `runClientUpload(browser)`).
  - **Orchestrator**: Master file `playwright/tests/qa-XXX-Files.test.ts` imports modules and uses `test.describe.configure({ mode: 'serial' })` and `test.step()`.
  - **Wrappers**: Individual debug files in `playwright/tests/specs/*.test.ts` (Import module, simple `test` block).
- **Key Rule**: Never import a `.test.ts` file into another test file. Always refactor logic into a `.ts` module.

## Selector & Interaction Refinements (Lessons from QA-196)
- **Strict Mode Handling**:
  - When matching repeated elements (e.g., file rows), scope tight!
  - Bad: `page.getByText('File Name')` (Matches row text, link title, etc.)
  - Good: `page.getByRole('listitem').filter({ hasText: 'File Name' }).first()`
- **Lazy Loading**:
  - Always scroll to the container or header before interacting with lazy-loaded lists.
  - `await page.getByText('Header').scrollIntoViewIfNeeded();`
- **Dynamic Deletion**:
  - Use `while` loops checking count > 0, not `for` loops with a static count, to handle dynamic DOM updates reliably.


## Mandatory Debugging Practices
- Enable debug mode with `PWDEBUG=1`.
- Add conditional waits for debugging:
  ```typescript
  if (process.env.PWDEBUG === '1') await page.waitForTimeout(3000);
  ```
- Make debug pauses conditional to avoid unnecessary interruptions during normal test runs.
- **Mandatory debug pauses**:
  - **Before major test steps**: Insert a debug pause before each significant test action or section. This ensures that debugging can occur at critical points in the test flow.
  - **Between tests**: Always include a debug pause between tests to allow for step-by-step debugging of transitions and setup for subsequent tests.
  ```typescript
  if (process.env.PWDEBUG === '1') {
      console.log('🔍 Debugging: Pausing before the next test.');
      await page.pause();
  }
  ```
  This ensures that `page.pause()` is only triggered when the `PWDEBUG` environment variable is set, allowing for seamless debugging without impacting automated test executions.

## Running Tests
- **Scripts**:
  - Defined in `package.json`:
    - `playwright:qa`: Runs tests in `qa` environment.
    - `playwright:test`: Runs tests in `test` environment.
    - `playwright:smoke`: Runs smoke tests.
  - Example Command:
    ```bash
    cross-env TEST_ENV=qa npx playwright test --reporter=html
    ```

## Artifact Handling and CI Expectations
- Playwright traces are retained on failure (`trace: 'retain-on-failure'`) and HTML reporter output goes to `playwright-report/`.
- Package scripts in the repo upload `playwright-report/` to an S3 bucket after runs — tests should produce the report in the expected location.

## Best Practices
- Reuse storage states and helpers to avoid redundancy.
- Commit new storage states to `playwright/storage/<env>/` if approved.
- Follow patterns in `playwright/tests/qo_form_basic.test.ts` for dynamic data and error handling.

## Test Files Directory
- A directory `playwright/storage/test_files` contains example files for testing file uploads, downloads, and other interactions. Example:
  ```typescript
  await page.setInputFiles('input[type="file"]', 'playwright/storage/test_files/Client Logo.jpg');
  ```

## Updated Environment Handling and Debugging Logic
- **Dynamic Environment Iteration**:
  - The `validate_login.test.ts` file dynamically iterates over all environments when `TEST_ENV` is not set.
  - Environments are defined in the `ENV_MAP` object, and the test dynamically selects environments based on the `TEST_ENV` variable.
- **Debugging Enhancements**:
  - Conditional pauses facilitate debugging during test runs.
  - A 2-second delay (`page.waitForTimeout(2000)`) ensures that JWT validation occurs after navigation.
- **JWT Validation**:
  - JWT tokens are validated by extracting them from `localStorage` and ensuring they are not null.
  - Debugging logs confirm successful validation for each user and environment.

## Example Code
```typescript
const environmentsToTest = TEST_ENV ? [TEST_ENV] : Object.keys(ENV_MAP);

for (const env of environmentsToTest) {
  const storageDir = path.resolve(__dirname, `../../storage/${env}`);
  const storageFiles = fs.readdirSync(storageDir).filter(file => file.startsWith('storageState_') && file.endsWith('.json'));

  for (const user of usersToValidate) {
    test(`Session validation for user (${user}) in ${env}`, async ({ browser }) => {
      const storageStatePath = path.join(storageDir, `storageState_${user}.json`);
      const context = await browser.newContext({ storageState: storageStatePath });
      const page = await context.newPage();

      await page.goto(ENV_MAP[env]);
      await page.waitForTimeout(2000);

      const jwt = await page.evaluate(() => localStorage.getItem('vc2JWT'));
      expect(jwt).not.toBeNull();

      console.log(`✅ JWT validated for user: ${user} in environment: ${env}`);

      await context.close();
    });
  }
}
```

## Helper Functions

### `deleteFile`

- **Purpose**: Deletes a file from the List View by interacting with the delete icon and confirming the deletion.
- **Location**: Used in `qa-196-files_listview_actions.test.ts`.
- **Implementation**:

```typescript
async function deleteFile(page, label: string) {
    const fileRow = page.locator('ul.files-list li', { hasText: label });
    const deleteIcon = fileRow.locator('i.file-delete[title="Delete file"]');

    await expect(deleteIcon).toBeVisible({ timeout: 3000 });
    await deleteIcon.click();
    await page.getByRole('button', { name: 'YES, DELETE' }).click();
}
```

- **Usage**:
  - Call the function with the `page` object and the file label.
  - Example:

```typescript
await deleteFile(page, 'Background Music');
await deleteFile(page, 'Client Logo');
await deleteFile(page, 'Prod File');
```

- **Best Practices**:
  - Ensure the file label matches the text in the List View.
  - Use `expect` to validate visibility before interacting with the delete icon.
