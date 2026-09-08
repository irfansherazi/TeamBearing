# Playwright Knowledge Sharing

## Overview

This document provides detailed information about the Playwright setup, configuration, and test examples used in the `vsuitePlatform` project. It is designed for knowledge sharing and ingestion by AI systems for retrieval-augmented generation (RAG) and other purposes.

---

## Playwright Configuration

### Environment Setup

The Playwright configuration is defined in `playwright.config.ts`. It includes environment-specific URLs, global settings, and project definitions for browser families.

#### Environment URLs

```typescript
const ENV_MAP = {
  prod: 'https://vcreative.net',
  test: 'https://two-test.vcreative.net',
  smoke: 'https://smoketest.vcreative.net',
  qa:   'https://qa.vcreative.net'
};
```

#### Current Environment

The `TEST_ENV` variable determines the active environment. It defaults to `smoke` if not explicitly set.

```typescript
const TEST_ENV = (process.env.TEST_ENV as keyof typeof ENV_MAP) || 'smoke';
```

#### Browser Families

Playwright is configured to run tests across three browser families:

- Chromium
- Firefox
- Webkit

```typescript
projects: [
  {
    name: 'chromium',
    use: { browserName: 'chromium' },
  },
  {
    name: 'firefox',
    use: { browserName: 'firefox' },
  },
  {
    name: 'webkit',
    use: { browserName: 'webkit' },
  },
],
```

#### Global Settings

- **Timeouts**: 30 seconds for tests, 10 seconds for expectations.
- **Headless Mode**: Enabled unless debugging (`PWDEBUG=1`).
- **Screenshots**: Captured only on failure.
- **Trace**: Retained on failure.

---

## Utilities

### `globalSetup.ts`

Handles global setup tasks, including:

- Ensuring the storage directory exists.
- Logging detected users.
- Logging system capabilities.

### `setup.ts`

Provides shared utilities for tests, including:

- User detection based on storage state files.
- Extended Playwright fixtures for user and context setup.

### `generateStorageStates.mjs`

Generates storage state files for users in different environments.

### `QO_helpers.ts`

Provides utility functions for Quick Order (QO) form tests, including:

- **Date Calculations**:
  - `calculateDueDate(days: number)`: Calculates a future date by adding a specified number of weekdays to today.
  - `calculateStartDate()`: Calculates the start date, which is two weeks from today, skipping weekends.
  - `calculateEndDate()`: Calculates the end date, which is three months from today.

- **String Generators**:
  - `generateRandomWords(count: number)`: Generates a random sequence of words.
  - `generateRandomISCI()`: Generates a random ISCI code (e.g., ABCD-1234).
  - `generateRandomDigits(length: number)`: Generates a random sequence of digits.
  - `generateRandomSpotTitle()`: Generates a random Spot Title consisting of an adverb, adjective, and noun.

- **Predefined Field Values**:
  - `demoScripts`: Contains predefined demo scripts for 30s and 60s spots.
  - `demoNotes`: Contains predefined notes for production, digital, traffic, blog, creative, and tag copy fields.

---

## Test Files Directory

A dedicated directory `playwright/storage/test_files` has been created to store example files for testing purposes. This directory includes a variety of file types such as images, audio files, documents, and PDFs. These files are intended for use in scenarios like file uploads, downloads, and other file-related interactions.

### Current Contents

- `500x1500.jpg`
- `Background Music.mp3`
- `Client Logo.jpg`
- `Copy points.doc`
- `Final Image Ad.png`
- `Final Script.doc`
- `Final Spot 15.mp3`
- `Final Spot 30.mp3`
- `Final Spot 60 .mp3`
- `Production_Audio_File_that_was_given_a_really_long_file_name_for_some_reason_or_another_I_gave_up_even-asking-anymore-questions-with-this-team.wav`
- `Traffic Information File.pdf`
- `Voice Part 1.mp3`
- `Voice Part 2.mp3`
- `Voice Part 3.mp3`

#### Usage Example

To use these files in a Playwright test, reference their relative path from the `playwright/` directory. For example:

```typescript
await page.setInputFiles('input[type="file"]', 'playwright/storage/test_files/Client Logo.jpg');
```

---

## Serial Test Orchestration (The "Playlist" Pattern)

For scenarios where tests must run in a specific order (e.g., File Upload -> Interactions -> Validation -> Deletion), use the "Playlist" pattern:

1.  **Refactor**: Move logic from `QA-XXX.test.ts` into a pure async function in `QA-XXX.ts` (e.g., `export async function runTest(browser) { ... }`).
2.  **Orchestrate**: Create a master `QA-XXX-Files.test.ts`:
    ```typescript
    test.describe.configure({ mode: 'serial' });
    test('Sequence', async ({ browser }) => {
      await test.step('Step 1', async () => await runStep1(browser));
      await test.step('Step 2', async () => await runStep2(browser));
    });
    ```
3.  **Debug**: Create thin wrappers in `playwright/tests/specs/` to run individual steps during development.

---

## Robust Automation Patterns (Lessons Learned)

### 1. Dynamic Deletion (The `while` Loop)
When deleting items from a list that updates dynamically (and potentially slowly), avoid `for` loops with a cached count. Use a `while` loop:

```typescript
const getButtons = () => page.locator('button.delete');
let count = await getButtons().count();
while (count > 0) {
    await getButtons().first().click();
    await page.waitForTimeout(500); // Wait for list update
    count = await getButtons().count();
}
```

### 2. Strict Mode & Scoping
To avoid "strict mode violation" errors when multiple elements match (e.g., 'Background Music' text in both a row and a link):
- **Scope to Parent**: `page.getByRole('listitem').filter({ hasText: 'Background Music' }).first()`
- **Avoid Generic Selectors**: Prefer specific roles over broad `getByText` or classes that might apply to multiple elements.

### 3. Lazy Loading Lists
If a list (checking for existence) fails to be found even though it exists, it might be lazy-loaded.
- **Scroll First**: `await page.getByText('Files Section').scrollIntoViewIfNeeded();`
- **Wait for Attachment**: `await locator.waitFor({ state: 'attached' });`

---

## Example Test Suite

The `example.test.ts` file demonstrates various Playwright features:

### Basic Navigation and Assertions

```typescript
test('should navigate to a page and verify title', async ({ page }) => {
  await page.goto('https://smoketest.vcreative.net');
  await expect(page).toHaveTitle('vCreative Smoke Test');
});
```

### Form Interactions

```typescript
test('should fill and submit a form', async ({ page }) => {
  await page.goto('https://smoketest.vcreative.net/form');
  await page.fill('input[name="username"]', 'testuser');
  await page.fill('input[name="password"]', 'password123');
  await page.click('button[type="submit"]');
  await expect(page.locator('.success-message')).toBeVisible();
});
```

### API Testing

```typescript
test('should make an API request and validate response', async ({ request }) => {
  const response = await request.get('https://qa.vcreative.net/api/data');
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data).toHaveProperty('key', 'value');
});
```

### Login Validation with Environment Handling

```typescript
test('should validate login using stored sessions', async ({ browser, baseURL }) => {
  const TEST_ENV = process.env.TEST_ENV || 'qa';
  const USE_SPECIFIC_USERS = process.env.USE_SPECIFIC_USERS === 'true';

  const storageDir = path.resolve(__dirname, `../../storage/${TEST_ENV}`);
  const storageFiles = fs.readdirSync(storageDir).filter(file => file.startsWith('storageState_') && file.endsWith('.json'));

  const usersToValidate = USE_SPECIFIC_USERS
    ? ['DemoProdDirector']
    : storageFiles.map(file => file.replace('storageState_', '').replace('.json', ''));

  const browserFamily = browser.browserType().name();
  console.log(`🌐 Running test for browser family: ${browserFamily}`);
  console.log(`👥 Validating users: ${usersToValidate.join(', ')}`);

  for (const user of usersToValidate) {
    const storageStatePath = path.join(storageDir, `storageState_${user}.json`);
    const context = await browser.newContext({ storageState: storageStatePath });
    const page = await context.newPage();

    await page.goto(baseURL!);
    const jwt = await page.evaluate(() => localStorage.getItem('vc2JWT'));
    expect(jwt).not.toBeNull();

    const payload = JSON.parse(Buffer.from(jwt!.split('.')[1], 'base64').toString());
    expect(payload.email).toContain(user);
    console.log(`✅ Login validated successfully for user: ${user} in environment: ${TEST_ENV}`);

    await context.close();
  }
});
```

---

## Helper Functions

### `deleteFile`

This helper function is used to delete files from the List View in the QA-196 test. It ensures that the delete icon is interactable and confirms the deletion action.

```typescript
async function deleteFile(page, label: string) {
    const fileRow = page.locator('ul.files-list li', { hasText: label });
    const deleteIcon = fileRow.locator('i.file-delete[title="Delete file"]');

    await expect(deleteIcon).toBeVisible({ timeout: 3000 });
    await deleteIcon.click();
    await page.getByRole('button', { name: 'YES, DELETE' }).click();
}
```

**Usage Example:**

```typescript
await deleteFile(page, 'Background Music');
await deleteFile(page, 'Client Logo');
await deleteFile(page, 'Prod File');
```

**Notes:**

- The function uses `locator` to find the file row and delete icon.
- It includes a visibility check for the delete icon to ensure it is interactable.
- The confirmation dialog is handled by clicking the 'YES, DELETE' button.

---

## Updated Environment Handling and Debugging Logic

### Dynamic Environment Iteration

- The `validate_login.test.ts` file now dynamically iterates over all environments when `TEST_ENV` is not set.
- Environments are defined in the `ENV_MAP` object, and the test dynamically selects environments based on the `TEST_ENV` variable.

### Debugging Enhancements

- Conditional pauses have been added to facilitate debugging during test runs.
- A 2-second delay (`page.waitForTimeout(2000)`) ensures that JWT validation occurs after navigation.

### JWT Validation

- JWT tokens are validated by extracting them from `localStorage` and ensuring they are not null.
- Debugging logs confirm successful validation for each user and environment.

### Example Code

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

### Debugging Practices

- Use `PWDEBUG=1` to enable debug mode.
- Add conditional waits to observe test flow during debugging:

```typescript
const isDebugMode = process.env.PWDEBUG === '1';
if (isDebugMode) await page.waitForTimeout(3000); // Debugging aid
```

This ensures that debugging pauses do not affect normal test runs.

---

## Angular 19 / PrimeNG 19 Upgrade (Test Environment)

The `test` environment (`two-test.vcreative.net`) has been upgraded to Angular 19 and PrimeNG 19. Tests running in this environment require updated locator patterns.

### Key Changes
- **Class Prefix**: `ui-` classes are now `p-` classes (e.g., `.p-datatable`, `.p-checkbox`).
- **Input Elements**: Checkboxes and Radio buttons now use standard HTML `input` elements.
- **Bulk Actions**: Functions like "Export" have moved to a bottom "Bulk Actions" bar that only appears after a table row is selected.

For a full list of breaking changes and new locator strategies, see the [Playwright Upgrade Reference Guide](file:///C:/Users/docbe/.gemini/antigravity/brain/280af5ae-5bb1-4861-9427-326f247dc678/playwright_upgrade_reference.md).
