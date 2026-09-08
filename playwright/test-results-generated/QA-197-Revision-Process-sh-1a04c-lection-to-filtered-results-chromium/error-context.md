# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: QA-197.spec.ts >> Revision Process >> should complete revision workflow from spot selection to filtered results
- Location: playwright/tests/generated/QA-197.spec.ts:7:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('checkbox').first()
Expected: visible
Timeout: 20000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 20000ms
  - waiting for getByRole('checkbox').first()

```

```yaml
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- alertdialog
- text: "77"
- button:
  - img
- text: Demo Prod Director
- img "vProMedia logo"
- text: vProMedia
- list:
  - listitem:
    - link "New Request":
      - /url: "#"
  - listitem:
    - link "Endorsement":
      - /url: "#"
  - listitem:
    - link "vProMedia":
      - /url: "#"
    - list:
      - listitem:
        - link "All (616)":
          - /url: "#/vpro/production-orders/folder/all"
      - listitem:
        - link "MyBox (317)":
          - /url: "#/vpro/production-orders/folder/mybox"
      - listitem:
        - link "Drafts (163)":
          - /url: "#/vpro/production-orders/folder/drafts"
      - listitem:
        - link "Inbox (500)":
          - /url: "#/vpro/production-orders/folder/inbox"
      - listitem:
        - link "New (277)":
          - /url: "#/vpro/production-orders/folder/new"
      - listitem:
        - link "Spec Spots (2)":
          - /url: "#/vpro/production-orders/folder/spec-spots"
      - listitem:
        - link "In Review (2)":
          - /url: "#/vpro/production-orders/folder/in-review"
      - listitem:
        - link "Active TV (27)":
          - /url: "#/vpro/production-orders/folder/active-tv"
      - listitem:
        - link "Delegated (91)":
          - /url: "#/vpro/production-orders/folder/delegated"
      - listitem:
        - link "Archived (137)":
          - /url: "#/vpro/production-orders/folder/archived"
      - listitem:
        - link "Prod Woman Prod (13)":
          - /url: "#/vpro/production-orders/folder/prod-woman-prod"
      - listitem:
        - link "On Air (4)":
          - /url: "#/vpro/production-orders/folder/on-air"
      - listitem:
        - link "Deleted (30)":
          - /url: "#/vpro/production-orders/folder/deleted"
      - listitem:
        - link "Creative Only (4)":
          - /url: "#/vpro/production-orders/folder/creative-only"
      - listitem:
        - link "Extended Dates (26)":
          - /url: "#/vpro/production-orders/folder/extended-dates"
      - listitem:
        - link "Auto Dubs (0)":
          - /url: "#/vpro/production-orders/folder/auto-dubs"
      - listitem:
        - link "Missing QCs (74)":
          - /url: "#/vpro/production-orders/folder/missing-qcs"
      - listitem:
        - link "Auto Dub Failures (31)":
          - /url: "#/vpro/production-orders/folder/auto-dub-failures"
      - listitem:
        - link "Active Radio (495)":
          - /url: "#/vpro/production-orders/folder/active-radio"
      - listitem:
        - link "No-File Archives (31)":
          - /url: "#/vpro/production-orders/folder/no-file-archives"
      - listitem:
        - link "New PSSC":
          - /url: "#/vpro/production-orders/folder/new-pssc"
      - listitem:
        - link "Bluth AM (28)":
          - /url: "#/vpro/production-orders/folder/bluth-am"
      - listitem:
        - link "bluth test (28)":
          - /url: "#/vpro/production-orders/folder/bluth-test"
      - listitem:
        - link "Station (1)":
          - /url: "#/vpro/production-orders/folder/station"
      - listitem:
        - link "ProdMan Dubbing (1)":
          - /url: "#/vpro/production-orders/folder/prodman-dubbing"
      - listitem:
        - link "needs traffic (11)":
          - /url: "#/vpro/production-orders/folder/needs-traffic"
      - listitem:
        - link "Ready to dub (50)":
          - /url: "#/vpro/production-orders/folder/ready-to-dub"
      - listitem:
        - link "CYN TEST SAVED SEARCH (13)":
          - /url: "#/vpro/production-orders/folder/cyn-test-saved-search"
      - listitem:
        - link "RDS Spots (106)":
          - /url: "#/vpro/production-orders/folder/rds-spots"
      - listitem:
        - link "Test 4 Results (4)":
          - /url: "#/vpro/production-orders/folder/test-4-results"
      - listitem:
        - link "TBB (55)":
          - /url: "#/vpro/production-orders/folder/tbb"
      - listitem:
        - link "TBC (26)":
          - /url: "#/vpro/production-orders/folder/tbc"
      - listitem:
        - link "The Peach Pit (19)":
          - /url: "#/vpro/production-orders/folder/the-peach-pit"
      - listitem:
        - link "Need Carts":
          - /url: "#/vpro/production-orders/folder/need-carts"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (...)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Beta Boys Search (71)":
          - /url: "#/vpro/production-orders/folder/beta-boys-search"
      - listitem:
        - link "Script Template Library":
          - /url: "#/vpro/script-template-library"
      - listitem:
        - link "Script Timer":
          - /url: "#"
      - listitem:
        - link "Voice Requests (7)":
          - /url: "#/vpro/spot-voice-requests"
      - listitem:
        - link "Voice Pool Search":
          - /url: "#/vpro/talentpool"
  - listitem:
    - link "Settings":
      - /url: "#"
    - list:
      - listitem:
        - link "Clients":
          - /url: "#/settings/clients"
      - listitem:
        - link "Labels":
          - /url: "#/settings/labels"
      - listitem:
        - link "Media Services":
          - /url: "#/settings/media-services"
      - listitem:
        - link "Pronunciations":
          - /url: "#/settings/pronunciation"
      - listitem:
        - link "Resource and Equipment Manager":
          - /url: "#/settings/resource-and-equipment-manager"
      - listitem:
        - link "Station Groups":
          - /url: "#/settings/station-groups"
      - listitem:
        - link "Submit a Feature":
          - /url: "#"
      - listitem:
        - link "Temporary Abilities":
          - /url: "#/settings/temp_abilities"
  - listitem:
    - link "Analytics":
      - /url: "#/reports/all"
- heading "Support" [level=4]
- text: Live Chat
- link "Help":
  - /url: https://vcreativeinc.com/knowledge/vpro
- link "800-605-9889":
  - /url: tel:800-605-9889
- link "support@vcreativeinc.com":
  - /url: mailTo:support@vcreativeinc.com
- combobox "MyBox (...)"
- button "dropdown trigger"
- button
- button
- button
- button
- button
- button "Month"
- button "Week"
- button "Today"
- text: June 2026
- button "Run Dates"
- button "Due Dates"
- grid:
  - rowgroup:
    - row "Sunday Monday Tuesday Wednesday Thursday Friday Saturday":
      - columnheader "Sunday": Sun
      - columnheader "Monday": Mon
      - columnheader "Tuesday": Tue
      - columnheader "Wednesday": Wed
      - columnheader "Thursday": Thu
      - columnheader "Friday": Fri
      - columnheader "Saturday": Sat
  - rowgroup:
    - row "May 31, 2026 June 1, 2026 June 2, 2026 June 3, 2026 June 4, 2026 June 5, 2026 June 6, 2026":
      - gridcell "May 31, 2026": "31"
      - gridcell "June 1, 2026": "1"
      - gridcell "June 2, 2026": "2 Test Client : TEST11 : 31321 Kathryn's Flowers : TRACY TESTING 9085"
      - gridcell "June 3, 2026": "3"
      - gridcell "June 4, 2026": "4"
      - gridcell "June 5, 2026": "5"
      - gridcell "June 6, 2026": "6"
    - row "June 7, 2026 June 8, 2026 June 9, 2026 June 10, 2026 June 11, 2026 June 12, 2026 June 13, 2026":
      - gridcell "June 7, 2026": "7 Test Client : TEST11 : 31321"
      - gridcell "June 8, 2026": "8"
      - gridcell "June 9, 2026": "9 Apollo Candy Company : GENEROUSLY LIMPING TOOTHBRUSH : MENF-6458 Bath Sheet Crazy : TEST JOHAN : 123456789"
      - gridcell "June 10, 2026": "10"
      - gridcell "June 11, 2026": "11"
      - gridcell "June 12, 2026": "12"
      - gridcell "June 13, 2026": "13"
    - row "June 14, 2026 June 15, 2026 June 16, 2026 June 17, 2026 June 18, 2026 June 19, 2026 June 20, 2026":
      - gridcell "June 14, 2026": "14 Test Client : TEST11 : 31321 Apollo Candy Company : GENEROUSLY LIMPING TOOTHBRUSH : MENF-6458"
      - gridcell "June 15, 2026": "15"
      - gridcell "June 16, 2026": "16"
      - gridcell "June 17, 2026": "17"
      - gridcell "June 18, 2026": "18"
      - gridcell "June 19, 2026": "19"
      - gridcell "June 20, 2026": "20 Grand Panda : PANDA : 123456789123456789123456789123456789"
    - row "June 21, 2026 June 22, 2026 June 23, 2026 June 24, 2026 June 25, 2026 June 26, 2026 June 27, 2026":
      - gridcell "June 21, 2026": "21 Test Client : TEST11 : 31321 Apollo Candy Company : GENEROUSLY LIMPING TOOTHBRUSH : MENF-6458"
      - gridcell "June 22, 2026": "22"
      - gridcell "June 23, 2026": "23"
      - gridcell "June 24, 2026": "24"
      - gridcell "June 25, 2026": "25"
      - gridcell "June 26, 2026": "26"
      - gridcell "June 27, 2026": "27"
    - row "June 28, 2026 June 29, 2026 June 30, 2026 July 1, 2026 July 2, 2026 July 3, 2026 July 4, 2026":
      - gridcell "June 28, 2026": "28 Apollo Candy Company : GENEROUSLY LIMPING TOOTHBRUSH : MENF-6458"
      - gridcell "June 29, 2026": "29"
      - gridcell "June 30, 2026": "30"
      - gridcell "July 1, 2026": "1 The Beta Boys : TEST11 : 31321"
      - gridcell "July 2, 2026": "2"
      - gridcell "July 3, 2026": "3"
      - gridcell "July 4, 2026": "4 I Can't Believe It's Not Brother: DNA Testing : 123456789012345678901234567890"
    - row "July 5, 2026 July 6, 2026 July 7, 2026 July 8, 2026 July 9, 2026 July 10, 2026 July 11, 2026":
      - gridcell "July 5, 2026": "5 Apollo Candy Company : GENEROUSLY LIMPING TOOTHBRUSH : MENF-6458 The Beta Boys : TEST11 : 31321 I Can't Believe It's Not Brother: DNA Testing : 123456789012345678901234567890"
      - gridcell "July 6, 2026": "6"
      - gridcell "July 7, 2026": "7"
      - gridcell "July 8, 2026": "8 Kathryn's Flowers : TRACY TESTING 908522"
      - gridcell "July 9, 2026": "9"
      - gridcell "July 10, 2026": "10 The Beta Boys : TEST_BLOG_9055 : 313"
      - gridcell "July 11, 2026": "11"
- alertdialog
```

# Test source

```ts
  1  | import { test, expect, type Page } from '@playwright/test';
  2  | import { getLocator, type TenantSelectorKey } from '@utils/generated/vpromedia_selectors';
  3  | 
  4  | test.use({ storageState: 'playwright/storage/vpromedia_auth.json' });
  5  | 
  6  | test.describe('Revision Process', () => {
  7  |   test('should complete revision workflow from spot selection to filtered results', async ({ page }) => {
  8  |     await page.goto('/inbox');
  9  |     
  10 |     const spotCheckbox = page.getByRole('checkbox').first();
> 11 |     await expect(spotCheckbox).toBeVisible();
     |                                ^ Error: expect(locator).toBeVisible() failed
  12 |     await spotCheckbox.click();
  13 |     
  14 |     const actionBar = page.locator('.action-bar, [data-testid="action-bar"]');
  15 |     await expect(actionBar).toBeVisible();
  16 |     
  17 |     const reviseButton = page.getByRole('button', { name: /revise/i });
  18 |     await expect(reviseButton).toBeVisible();
  19 |     await reviseButton.click();
  20 |     
  21 |     const causeDropdown = page.getByRole('combobox', { name: /cause/i });
  22 |     await expect(causeDropdown).toBeVisible();
  23 |     await causeDropdown.click();
  24 |     
  25 |     const internalOption = page.getByRole('option', { name: /internal/i });
  26 |     await expect(internalOption).toBeVisible();
  27 |     await internalOption.click();
  28 |     
  29 |     const startButton = page.getByRole('button', { name: /start/i });
  30 |     await expect(startButton).toBeVisible();
  31 |     await startButton.click();
  32 |     
  33 |     const blogPostField = page.getByRole('textbox', { name: /blog/i });
  34 |     await expect(blogPostField).toBeVisible();
  35 |     await blogPostField.fill('Revision requested for quality improvements');
  36 |     
  37 |     const dueDateField = page.getByRole('textbox', { name: /due date/i });
  38 |     await expect(dueDateField).toBeVisible();
  39 |     await dueDateField.fill('12/31/2024');
  40 |     
  41 |     const submitAllButton = page.getByRole('button', { name: /submit all/i });
  42 |     await expect(submitAllButton).toBeVisible();
  43 |     await submitAllButton.click();
  44 |     
  45 |     const finishButton = page.getByRole('button', { name: /finish/i });
  46 |     await expect(finishButton).toBeVisible();
  47 |     await finishButton.click();
  48 |     
  49 |     await expect(page.getByText(/revised spots \(1\)/i)).toBeVisible();
  50 |     
  51 |     const revisedSpot = page.locator('.spot-item, [data-testid="spot-item"]').first();
  52 |     await expect(revisedSpot).toBeVisible();
  53 |     
  54 |     await expect(page.getByText('Revision requested for quality improvements')).toBeVisible();
  55 |     await expect(page.getByText('12/31/2024')).toBeVisible();
  56 |   });
  57 | });
```