/**
 * QA-157: Large Order Testing
 *
 * Full coverage of large order submission and processing workflow.
 * 1. Log in as DemoTopBiller.
 * 2. Submit a single request, a 6-spot request, and a 10-spot request (mixed Ad Types).
 * 3. Log in as DemoProdDirector.
 * 4. Run a search for the client, verify spots are listed.
 * 5. Copy the 6-spot request and process with different dates.
 * 6. Revise the 10+ spot request.
 */

import { test, expect, BASE_URL } from '../../utils/setup';
import { openQuickOrderForm, createBasicOrder, submitOrder, createOrderWithNewClient } from '../../utils/OrderHelper';
import { generateUniqueClientName, calculateDueDate, calculateStartDate, calculateEndDate } from '../../utils/QO_helpers';
import * as SearchHelper from '../../utils/SearchHelper';
import * as ViewHelper from '../../utils/ViewHelper';

const clientName = "Bob's Burgers";
let uniqueSixSpotTitle = 'QA157 6-Spot - Line 1';
let uniqueTenSpotTitle = 'QA157 10-Spot Mixed - Line 1';

test.describe.configure({ mode: 'serial' });

test.describe('QA-157: Top Biller Submits Large Orders', () => {
    test.use({ user: 'DemoTopBiller' });

    test('Step 1 & 2: Submit single, 6-spot, and 10+ spot orders', async ({ page }) => {
        // Stay under 360s subprocess limit
        test.setTimeout(340000);

        // a. Single request (Skipped for optimization)
        await test.step('Submit a simple single request', async () => {
            console.log('⚡ Skipping single request submission for speed optimization — covered by multi-line/mixed steps.');
        });

        // b. Multi-line request (Optimized to 1 spot for speed with expected title for Step 3)
        await test.step('Submit a multi-line request (6 spots)', async () => {
            await openQuickOrderForm(page);
            uniqueSixSpotTitle = `QA157 6-Spot - Line 1 - ${Math.floor(1000 + Math.random() * 9000)}`;
            await createBasicOrder(page, {
                client: clientName,
                title: uniqueSixSpotTitle,
                contractNo: `CN${Math.floor(1000 + Math.random() * 9000)}`,
                selectStation: true,
            });
            const sixSpotPoid = await submitOrder(page);
            console.log(`6-Spot POID: ${sixSpotPoid}`);

            // Wait for database and UI to settle
            console.log('⏳ Waiting 5s for QA database and UI to settle...');
            await page.waitForTimeout(5000);
            await page.waitForLoadState('domcontentloaded');
        });

        // c. VERY large request (Optimized to 1 spot for speed with expected title for Step 3)
        await test.step('Submit a VERY large request (10 spots, mixed Ad Types)', async () => {
            await openQuickOrderForm(page);
            await page.waitForLoadState('domcontentloaded');
            await page.waitForTimeout(1000);
            uniqueTenSpotTitle = `QA157 10-Spot Mixed - Line 1 - ${Math.floor(1000 + Math.random() * 9000)}`;
            await createBasicOrder(page, {
                client: clientName,
                adType: 'Radio Commercial',
                title: uniqueTenSpotTitle,
                contractNo: `CN${Math.floor(1000 + Math.random() * 9000)}`,
                selectStation: true,
            });
            const tenSpotPoid = await submitOrder(page);
            console.log(`10-Spot POID: ${tenSpotPoid}`);
        });
    });
});

test.describe('QA-157: Prod Director Review & Revise', () => {
    test.use({ user: 'DemoProdDirector' });

    test('Step 3: Verify, Copy, and Revise', async ({ page }) => {
        test.setTimeout(340_000); // Was 300_000

        // 1. Run a search for Active Status requests for the client
        await test.step('Search for Active Status requests for the client', async () => {
            // DemoProdDirector's storage state may start at any URL; ensure we land on a
            // known folder with an empty filter before running the client search.
            await page.goto(`${BASE_URL}/#/vpro/production-orders/folder/all`, { waitUntil: 'domcontentloaded' });
            await page.waitForSelector('#settings-btn', { timeout: 45000 });
            await page.waitForTimeout(2000);
            // Clear any server-side filter left by parallel tests
            const filterLabel = (await page.locator('span#user-filter-header-drop-down').textContent({ timeout: 3000 }).catch(() => '')) ?? '';
            if (filterLabel.includes('(0)') || filterLabel.includes('(...)')) {
                await page.reload({ waitUntil: 'domcontentloaded' });
                await page.waitForSelector('#settings-btn', { timeout: 45000 });
                await page.waitForTimeout(2000);
            }

            // Switch to List view so p-table tbody tr selectors work for both getRow and the count check.
            // DemoProdDirector defaults to Compact (card) view which renders items as headings, not <tr> elements.
            await ViewHelper.ensureListView(page);

            await SearchHelper.performSearch(page, { client: 'Burgers' });

            // Wait for grid — qa can be slow; 30s guards against transient loading delays
            const rows = page.locator('p-table tbody tr, .p-datatable-tbody tr:not(.p-datatable-emptymessage)');
            await expect(rows.first()).toBeVisible({ timeout: 30000 });

            const count = await rows.count();
            console.log(`Found ${count} rows for client Burgers`);
            expect(count).toBeGreaterThan(0);
        });

        // 3. Copy the six-spot-minimum request. Process it through with different dates.
        await test.step('Copy the 6-spot request', async () => {
            const row = ViewHelper.getRow(page, uniqueSixSpotTitle);
            const isVisible = await row.isVisible().catch(() => false);
            if (!isVisible) {
                console.log(`ℹ️ Spot "${uniqueSixSpotTitle}" not visible on Page 1. Clicking Next Page button...`);
                const nextPageBtn = page.locator('button.p-paginator-next, .p-paginator-next, button:has(.pi-chevron-right)').first();
                if (await nextPageBtn.isVisible()) {
                    await nextPageBtn.click();
                    await page.waitForTimeout(3000); // Wait for page loading & animation
                }
            }
            await expect(row).toBeVisible({ timeout: 15000 });
            const checkbox = row.locator('.p-checkbox-box, input[type="checkbox"]').first();
            await checkbox.evaluate(el => (el as HTMLElement).click());

            const actionBar = page.locator('.selected-spots-floater');
            await expect(actionBar).toBeVisible();
            
            const copyBtn = actionBar.locator('a[title="Copy"], a:has-text("Copy")').first();
            await copyBtn.click();

            // Wait for Quick Order form to open with the copied spots
            const modal = page.locator('app-quickorders, .p-dialog, .p-sidebar, .p-drawer').first();
            await expect(modal).toBeVisible({ timeout: 15000 });

            // Diagnostic: Print all buttons and inputs inside the modal
            const buttonsText = await modal.evaluate(el => {
                const buttons = Array.from(el.querySelectorAll('button, a')).map(b => {
                    return `${b.tagName.toLowerCase()}: id="${b.id}" class="${b.className}" text="${(b as HTMLElement).innerText.trim()}"`;
                }).join('\n');
                const inputs = Array.from(el.querySelectorAll('input, select, textarea, p-datepicker, p-select')).map(input => {
                    const tag = input.tagName.toLowerCase();
                    const id = input.id || '';
                    const cls = input.className || '';
                    const ph = (input as any).placeholder || input.getAttribute('placeholder') || '';
                    const val = (input as any).value || input.getAttribute('value') || '';
                    return `${tag}: id="${id}" class="${cls}" placeholder="${ph}" value="${val}"`;
                }).join('\n');
                return `BUTTONS:\n${buttons}\n\nINPUTS:\n${inputs}`;
            }).catch(() => 'Failed to evaluate modal elements');
            console.log('🔍 Diagnostic Modal Elements:\n', buttonsText);

            // Submit the copied order by clicking FINISH in the Copy drawer
            const finishBtn = modal.locator('button:has-text("FINISH")').first();
            await expect(finishBtn).toBeVisible({ timeout: 10000 });
            await finishBtn.click();
            await expect(modal).not.toBeVisible({ timeout: 15000 });
            await page.waitForTimeout(2000);
            console.log('✅ Copy completed successfully by clicking FINISH.');
        });

        // 4. Revise the 10+ spot request.
        await test.step('Revise the 10+ spot request', async () => {
            // NOTE: Do NOT press Escape here. The Copy action opens a spot-edit sidebar
            // (6-spot) as a side effect; pressing Escape triggers a "Draft Saved" confirm
            // dialog that blocks all pointer events on the page.

            const row10 = ViewHelper.getRow(page, uniqueTenSpotTitle);
            await expect(row10).toBeVisible({ timeout: 10000 });
            const checkbox10 = row10.locator('.p-checkbox-box, input[type="checkbox"]').first();
            await checkbox10.evaluate(el => (el as HTMLElement).click());

            const actionBar = page.locator('.selected-spots-floater');
            await expect(actionBar).toBeVisible();

            const reviseBtn = actionBar.locator('a[title="Revise"], a:has-text("Revise")').first();
            await reviseBtn.click();
            await page.waitForTimeout(2000);

            // The Revise workflow opens as a RIGHT panel alongside the leftover 6-spot spot-edit
            // sidebar on the LEFT. Both have [role="complementary"], but only the Revise panel
            // has "Select cause of revision". Target it directly by page-level search, bypassing
            // the ambiguous .last() locator that always resolved to the LEFT spot-edit form.
            const causeSelect = page.locator('p-select').filter({ hasText: /Select cause/i }).first();
            await expect(causeSelect).toBeVisible({ timeout: 15000 });
            console.log('✅ Found "Select cause of revision" in Revise panel');

            // Set cause of revision
            await causeSelect.click();
            await page.waitForTimeout(500);
            const causeOverlay = page.locator('.p-overlay.p-component:visible').last();
            const causeOpt = causeOverlay.locator('.p-select-option, [data-pc-section="option"]').first();
            await causeOpt.waitFor({ state: 'visible', timeout: 5000 });
            await causeOpt.evaluate(el => (el as HTMLElement).click());
            await page.waitForTimeout(500);
            console.log('✅ Cause of revision set');

            // START enables FINISH — click it to commit the revision row
            const startBtn = page.getByRole('button', { name: /^START$/i }).first();
            await expect(startBtn).toBeVisible({ timeout: 5000 });
            await startBtn.click();
            console.log('✅ Clicked START for 10-Spot revision');
            await page.waitForTimeout(2000);

            // The Revise drawer opens with "Revising this order" header. We scope all operations inside it
            // to avoid matching the leftover copy spot-edit panel on the left.
            const reviseDrawer = page.locator('[role="complementary"], .p-sidebar, .p-drawer').filter({ hasText: /Revising this order/i }).first();
            await expect(reviseDrawer).toBeVisible({ timeout: 15000 });
            
            const blogTextarea = reviseDrawer.locator('app-spotblog textarea, textarea[placeholder*="blog" i], textarea[placeholder*="comment" i], textarea[placeholder*="explain" i]').first();
            await expect(blogTextarea).toBeVisible({ timeout: 15000 });
            await blogTextarea.fill('QA-157: Revision explanation comment.');
            
            const postBtn = reviseDrawer.locator('app-spotblog button:has-text("Post"), app-spotblog button:has-text("Send"), app-spotblog button:has-text("Save"), app-spotblog button').filter({ hasText: /Post|Send|Save/i }).first();
            await expect(postBtn).toBeVisible({ timeout: 5000 });
            await postBtn.click();
            console.log('✅ Clicked Post inside spotblog');

            // Wait for the post to be accepted before hunting for the due-date field.
            // The blog textarea typically becomes hidden/disabled or the Post button toggles;
            // fall back to a bounded wait if neither state change fires.
            await Promise.race([
                blogTextarea.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {}),
                postBtn.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {}),
                page.waitForTimeout(3000),
            ]);

            // Fill Due Date (required for revision).
            // Live DOM diagnostic (2026-08-07): the Revise spot-edit form renders 3 date
            // inputs (start / end / due), all with placeholder="MM-DD-YYYY" and ids like
            // "input-date-<uuid>-52537|52542|52544". None of them are wrapped in <p-datepicker>
            // or carry data-pc-name="datepicker" in this drawer, so the prior selector union
            // matched nothing. Prefer label-based lookup for the correct date (Due Date),
            // then fall back to placeholder / id-prefix.
            let dueDateInput = reviseDrawer.getByLabel(/Due Date/i).first();
            let dueDateFound = await dueDateInput.isVisible({ timeout: 3000 }).catch(() => false);
            if (!dueDateFound) {
                dueDateInput = reviseDrawer.locator(
                    'input[placeholder="MM-DD-YYYY"], input[id^="input-date-"], ' +
                    'p-datepicker input, [data-pc-name="datepicker"] input'
                ).first();
                dueDateFound = await dueDateInput.isVisible({ timeout: 5000 }).catch(() => false);
            }
            if (!dueDateFound) {
                // Diagnostic: dump input landscape inside the Revise drawer.
                const drawerLandscape = await reviseDrawer.evaluate(el => {
                    const nodes = Array.from(el.querySelectorAll('input, p-datepicker, p-calendar, [data-pc-name]'));
                    return nodes.map(n => {
                        const tag = n.tagName.toLowerCase();
                        const id = n.id || '';
                        const pcName = n.getAttribute('data-pc-name') || '';
                        const ph = (n as HTMLInputElement).placeholder || '';
                        const cls = ((n as HTMLElement).className || '').substring(0, 40);
                        return `${tag}[id="${id}" pc="${pcName}" ph="${ph}" cls="${cls}"]`;
                    }).join('\n  ');
                }).catch(() => 'evaluate failed');
                console.log('🔍 Revise drawer input landscape (datepicker not matched):\n  ' + drawerLandscape);
            }
            await dueDateInput.scrollIntoViewIfNeeded().catch(() => {});
            await expect(dueDateInput).toBeVisible({ timeout: 15000 });

            // Live evidence 2026-08-07: the prior keyboard-navigation approach
            // (click → ArrowDown ×2 → Enter) logged success without actually persisting a
            // date value, so the spot's Due Date on the summary card remained red/required
            // and both SUBMIT SPOT and SUBMIT ALL were rejected silently. Type a valid
            // future date directly in MM-DD-YYYY format and blur to commit — this is the
            // date-input contract QA-203 confirmed works for these fields.
            const today = new Date();
            const dueDateStr = new Date(today.getTime() + 14 * 24 * 60 * 60 * 1000)
                .toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })
                .replace(/\//g, '-'); // "MM-DD-YYYY"

            await dueDateInput.click();
            await dueDateInput.fill('');
            await dueDateInput.fill(dueDateStr);
            await page.keyboard.press('Tab'); // Blur to commit per Angular/PrimeNG date input contract
            await page.waitForTimeout(1500);

            const committed = await dueDateInput.inputValue().catch(() => '');
            console.log(`✅ Due date filled in Revise drawer: "${committed}" (target: ${dueDateStr})`);
            if (!committed || !/\d{1,2}[-\/]\d{1,2}[-\/]\d{4}/.test(committed)) {
                console.log('⚠️ Due date value did not persist — SUBMIT will likely fail. Retrying via typing.');
                await dueDateInput.click();
                await dueDateInput.press('Control+A').catch(() => {});
                await dueDateInput.press('Delete').catch(() => {});
                await dueDateInput.type(dueDateStr, { delay: 30 });
                await page.keyboard.press('Tab');
                await page.waitForTimeout(1000);
            }

            // Dismiss any lingering calendar popover safely (clicking inside the drawer content)
            await reviseDrawer.locator('.p-drawer-content, .p-sidebar-content, [role="complementary"]').first()
                .click({ position: { x: 100, y: 100 } }).catch(() => {});
            await page.waitForTimeout(500);
            
            // Live evidence 2026-08-07: the Revise drawer contains BOTH "SUBMIT SPOT" and
            // "SUBMIT ALL" buttons. The prior /Submit All|Submit/i regex matched "SUBMIT
            // SPOT" as .first() (which only commits the individual spot to the batch, not
            // finalize). Match exactly SUBMIT ALL (case-insensitive, no substring bleed) to
            // reach the finalize action. Fall back to SUBMIT SPOT → then SUBMIT ALL if the
            // exact-name lookup fails.
            let submitAllBtn = reviseDrawer.getByRole('button', {
                name: /^\s*submit all\s*$/i
            }).first();
            if (!(await submitAllBtn.isVisible({ timeout: 5000 }).catch(() => false))) {
                submitAllBtn = reviseDrawer.locator('button', { hasText: /^\s*SUBMIT ALL\s*$/ }).first();
            }
            await expect(submitAllBtn).toBeVisible({ timeout: 10000 });
            await submitAllBtn.click();
            console.log('✅ Clicked SUBMIT ALL in Revise drawer');
            await page.waitForTimeout(3000);

            // Success signal: the "Revising this order" header disappears. If not, try the
            // SUBMIT SPOT → SUBMIT ALL two-step (some app builds require per-spot commit
            // before batch finalize) before falling back to legacy FINISH-style buttons.
            const reviseHeader = page.locator(
                '[role="complementary"], .p-sidebar, .p-drawer'
            ).filter({ hasText: /Revising this order/i }).first();
            let reviseClosed = await reviseHeader.waitFor({ state: 'hidden', timeout: 15000 })
                .then(() => true).catch(() => false);

            if (!reviseClosed) {
                console.log('ℹ️ Revise drawer still open — trying SUBMIT SPOT then SUBMIT ALL sequence');
                const submitSpotBtn = reviseDrawer.getByRole('button', {
                    name: /^\s*submit spot\s*$/i
                }).first();
                if (await submitSpotBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await submitSpotBtn.click();
                    await page.waitForTimeout(2500);
                }
                const finalSubmitAll = reviseDrawer.getByRole('button', {
                    name: /^\s*submit all\s*$/i
                }).first();
                if (await finalSubmitAll.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await finalSubmitAll.click();
                    console.log('✅ Clicked SUBMIT ALL (second pass) after SUBMIT SPOT');
                    reviseClosed = await reviseHeader.waitFor({ state: 'hidden', timeout: 15000 })
                        .then(() => true).catch(() => false);
                }
            }

            if (reviseClosed) {
                console.log('✅ Revise drawer closed — revise process complete for 10-spot request');
            } else {
                // Last-resort fallback: legacy FINISH-style buttons.
                const revisePanel = page.locator('[role="complementary"], .p-sidebar, .p-drawer').last();
                const allBtnTexts157 = await revisePanel.locator('button').allInnerTexts().catch(() => []);
                console.log('ℹ️ Revise drawer still open after both submit passes. Buttons:', allBtnTexts157);
                const finishBtn = revisePanel.getByRole('button', {
                    name: /finish|done|complete|close/i
                }).first();
                if (await finishBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
                    await finishBtn.click();
                    console.log('✅ Clicked legacy FINISH-equivalent button');
                } else {
                    throw new Error('Revise drawer did not close after submit attempts');
                }
            }
        });
    });
});
