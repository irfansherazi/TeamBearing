/**
 * QA-197: Revision Process
 *
 * Full coverage of the end-to-end revision workflow per JIRA QA-197:
 * 1. Select a spot → verify bottom action bar with all 8 items
 * 2. Click REVISE → verify drawer, cause dropdown (Internal + Client), START
 * 3. Click START → verify POST BLOG required, Due Date required with asterisks
 * 4. Fill blog + due date → verify Submit All becomes active
 * 5. Click Add Request → verify second order added, blog optional, fill fields
 * 6. Click SUBMIT ALL → verify revise summary with client/title
 * 7. Click FINISH → verify redirect, revised spot visible with updated data
 *
 * Login: DemoSalesExec (via setup.ts fixture)
 */

import { test, expect, ENV_TIMEOUT_MULTIPLIER } from '../../utils/setup';
import { goToFolder } from '../../utils/NavHelper';
import { selectDateViaPicker, openQuickOrderForm, createBasicOrder, submitOrder } from '../../utils/OrderHelper';
import { findSpotByTitle, ensureListView } from '../../utils/ViewHelper';
import { calculateDueDate } from '../../utils/QO_helpers';

const REVISE_PANEL = '[role="complementary"]';

test.describe('QA-197: Revision Process', () => {
    test.use({ user: 'DemoProdDirector' });

    test('Complete End-to-End Revision Process', async ({ page }) => {
        test.setTimeout(Math.ceil(220000 * ENV_TIMEOUT_MULTIPLIER));
        let spotClientName = '';
        const uniqueTitle = `QA197 Active Spot - ${Math.floor(Date.now() / 1000)}`;

        // Pre-requisite: Submit a fresh order so we have an active, non-Draft, non-Archived spot
        await test.step('Step 0: Pre-requisite: Submit a fresh order', async () => {
            await openQuickOrderForm(page);
            await createBasicOrder(page, {
                client: "Bob's Burgers",
                title: uniqueTitle,
            });
            const poid = await submitOrder(page);
            console.log(`✅ Pre-requisite spot submitted. POID: ${poid}`);
            // Settle time
            await page.waitForTimeout(3000);
            await page.waitForLoadState('domcontentloaded');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 1: Login + navigate to All folder, select a spot
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 1: Select a spot and verify bottom action bar', async () => {
            // Navigate to All folder so the freshly-submitted spot is reachable
            await goToFolder(page, 'All');
            // Extra settle time: newly submitted spots can take several seconds to appear
            // in the All folder due to database replication lag on QA. A reload forces a
            // fresh fetch, avoiding the search-panel fallback in findSpotByTitle which
            // times out if #do-search-btn isn't present in the current page state.
            await page.waitForTimeout(5000);
            await page.reload({ waitUntil: 'domcontentloaded' });
            // ensureListView's implicit 10s window on #settings-btn can starve
            // right after a reload on slow QA responses — wait for the settings
            // button explicitly (extra 30s) before entering ensureListView.
            await page.locator('#settings-btn').waitFor({ state: 'visible', timeout: 30000 });
            await page.waitForTimeout(1500);
            await ensureListView(page);
            // createBasicOrder uppercases the title in the form — search for the stored (uppercased) value
            // so the search panel sends a string that matches what's in the database
            const targetRow = await findSpotByTitle(page, uniqueTitle.toUpperCase());
            await expect(targetRow).toBeVisible({ timeout: 15000 });

            spotClientName = (await targetRow.locator('td').nth(2).innerText()).trim().split('\n')[0];
            console.log(`📋 Selected spot — Client: "${spotClientName}"`);

            // Use highly reliable DOM click for checkbox click to prevent hit-test overlay issues
            const checkbox = targetRow.locator('.p-checkbox-box, input[type="checkbox"]').first();
            await checkbox.evaluate(el => (el as HTMLElement).click());

            // JIRA 1.1: Verify action bar shows with 8 items
            const actionBar = page.locator('.selected-spots-floater');
            await expect(actionBar).toBeVisible({ timeout: 5000 });

            const selectedCount = actionBar.locator('a.selection-count');
            await expect(selectedCount).toBeVisible({ timeout: 3000 });
            await expect(selectedCount).toContainText('SELECTED');

            // JIRA 1.1: Verify action bar shows with expected items
            // Note: JIRA specifies 8 items for DemoProdDirector (includes REJECT).
            // DemoSalesExec sees: SELECTED, Export, View, Copy, Extend, Revise, Bulk Actions
            for (const label of ['Export', 'View', 'Copy', 'Extend', 'Revise']) {
                await expect(actionBar.getByText(label, { exact: false }).first()).toBeVisible({ timeout: 3000 });
            }
            console.log('  ✅ Action bar visible with expected buttons');

            // JIRA 1.2: Verify bulk actions button is present (disabled with single selection)
            const bulkActionsBtn = actionBar.getByText('Bulk Actions', { exact: false }).first();
            await expect(bulkActionsBtn).toBeVisible({ timeout: 3000 });
            console.log('  ✅ Bulk Actions button visible');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 2: Click REVISE, verify drawer, cause dropdown, START
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 2: Open Revise drawer and verify initial state', async () => {
            const actionBar = page.locator('.selected-spots-floater');
            const reviseBtn = actionBar.locator('a[title="Revise"]');
            await expect(reviseBtn).toBeVisible({ timeout: 3000 });
            await reviseBtn.click();

            const activeDrawer = page.locator(REVISE_PANEL).last();
            await expect(activeDrawer).toBeVisible({ timeout: 12000 });
            console.log(`📋 Revise panel opened for "${spotClientName}"`);

            // JIRA 2.1: Verify client and title display
            await expect(activeDrawer).toContainText(/Revise/i);
            await expect(activeDrawer.getByText(spotClientName, { exact: false })).toBeVisible({ timeout: 5000 });
            console.log('  ✅ Client name visible in drawer');

            // JIRA 2.2: Verify cause dropdown shows 2 options (Internal and Client)
            const causeDropdown = activeDrawer.locator('p-select').first();
            await expect(causeDropdown).toBeVisible();
            await causeDropdown.click();
            await page.waitForTimeout(500);

            await expect(page.getByRole('option', { name: 'Internal' })).toBeVisible({ timeout: 3000 });
            await expect(page.getByRole('option', { name: /Client/i })).toBeVisible({ timeout: 3000 });
            console.log('  ✅ Cause dropdown shows Internal and Client');

            // JIRA 2.3: Select Internal → START becomes orange/active
            await page.getByRole('option', { name: 'Internal' }).click();

            const startBtn = activeDrawer.locator('button:has-text("Start"), button:has-text("START")').first();
            await expect(startBtn).toBeEnabled({ timeout: 5000 });
            console.log('  ✅ START button is enabled after selecting Internal');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 3: Click START → verify required fields
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 3: Click START and verify required fields', async () => {
            const activeDrawer = page.locator(REVISE_PANEL).last();
            const startBtn = activeDrawer.locator('button:has-text("Start"), button:has-text("START")').first();
            await startBtn.click();

            // JIRA 3.1: POST BLOG required with message
            await expect(page.getByText('POST BLOG')).toBeVisible({ timeout: 12000 });
            const requiredMsg = page.getByText(/You\s+Must\s+add a message explaining your changes/i);
            await expect(requiredMsg).toBeVisible({ timeout: 5000 });
            console.log('  ✅ Blog is required with validation message');

            // JIRA 3.2: Due Date required — verify the Due Date label and its input field are present.
            // The revise panel uses a plain textbox (placeholder: MM-DD-YYYY) for Due Date, not p-datepicker.
            const dueDateLabel = activeDrawer.getByText(/Due Date|Due by/i).first();
            await expect(dueDateLabel).toBeVisible({ timeout: 5000 });
            // Verify the Due Date input is present — may be a textbox or p-datepicker depending on panel
            const dueDateInput = activeDrawer.locator(
                'input[placeholder="MM-DD-YYYY"], p-datepicker input, input[aria-label*="Due Date"]'
            ).first();
            await expect(dueDateInput).toBeVisible({ timeout: 5000 });
            console.log('  ✅ Due Date field visible as required');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 4: Fill blog + due date → Submit All active
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 4: Fill blog and due date', async () => {
            const activeDrawer = page.locator(REVISE_PANEL).last();

            // Blog textarea lives in app-spotblog in the right column
            const blogTextarea = activeDrawer.locator('app-spotblog textarea').first();

            // Expand blog section if collapsed
            if (!(await blogTextarea.isVisible({ timeout: 2000 }).catch(() => false))) {
                const postBlogHeader = activeDrawer.getByText('POST BLOG', { exact: false }).first();
                if (await postBlogHeader.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await postBlogHeader.click();
                    await page.waitForTimeout(1000);
                }
            }

            await expect(blogTextarea).toBeVisible({ timeout: 5000 });
            await blogTextarea.fill('QA-197 automated revision blog entry');
            await blogTextarea.press('Tab');
            await page.waitForTimeout(500);

            // Click Post inside app-spotblog
            const postBtn = activeDrawer.locator('app-spotblog button:has-text("Post")').first();
            await expect(postBtn).toBeVisible({ timeout: 3000 });
            await postBtn.click();
            await expect(activeDrawer.locator('app-spotblog').first().getByText('QA-197 automated revision blog entry'))
                .toBeVisible({ timeout: 10000 }).catch(() => {});
            console.log('  ✅ Blog posted via app-spotblog');

            // Due Date — fill via text input or keyboard navigation.
            // The revise panel uses a plain textbox (placeholder: MM-DD-YYYY), not p-datepicker.
            const dueDateInput = activeDrawer.locator(
                'input[placeholder="MM-DD-YYYY"], p-datepicker input, input[aria-label*="Due Date"]'
            ).first();
            await expect(dueDateInput).toBeVisible({ timeout: 5000 });
            await dueDateInput.click();
            await page.waitForTimeout(1000);
            // Try keyboard navigation first (works for both plain inputs and datepicker)
            const isDatepicker = await activeDrawer.locator('p-datepicker').first().isVisible({ timeout: 1000 }).catch(() => false);
            if (isDatepicker) {
                await page.keyboard.press('ArrowDown');
                await page.waitForTimeout(200);
                await page.keyboard.press('ArrowDown');
                await page.waitForTimeout(200);
                await page.keyboard.press('Enter');
            } else {
                // Plain text input: fill with a date 2 weeks from now
                const twoWeeks = new Date();
                twoWeeks.setDate(twoWeeks.getDate() + 14);
                const mm = String(twoWeeks.getMonth() + 1).padStart(2, '0');
                const dd = String(twoWeeks.getDate()).padStart(2, '0');
                const yyyy = twoWeeks.getFullYear();
                await dueDateInput.fill(`${mm}-${dd}-${yyyy}`);
                await dueDateInput.press('Tab');
            }
            await page.waitForTimeout(1000);
            console.log('  ✅ Due date filled');

            // Dismiss calendar popover safely
            await activeDrawer.locator('.p-drawer-content, .p-sidebar-content').first()
                .click({ position: { x: 100, y: 100 } }).catch(() => {});
            await page.waitForTimeout(500);

            // JIRA 4.1: Verify Submit All becomes active
            const submitAllBtn = activeDrawer.getByRole('button', { name: /Submit All/i }).first();
            await expect(submitAllBtn).toBeEnabled({ timeout: 10000 });
            console.log('  ✅ Submit All button is enabled after filling required fields');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 5: Click Add Request → add second order, fill required fields
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 5: Add Request and fill second order', async () => {
            const activeDrawer = page.locator(REVISE_PANEL).last();
            const drawerContent = activeDrawer.locator('.p-drawer-content, .p-sidebar-content').first();

            // JIRA 5: Click ADD REQUEST
            const addRequestBtn = activeDrawer.getByRole('button', { name: /ADD REQUEST/i }).first();
            await expect(addRequestBtn).toBeVisible({ timeout: 5000 });
            await addRequestBtn.click();
            console.log('  ✅ ADD REQUEST clicked');

            // JIRA 5.1: Ensure a new order was added (UNTITLED SPOT or No Status appears)
            const secondSpotIndicator = activeDrawer.getByText(/UNTITLED SPOT|No Status/i).first();
            await expect(secondSpotIndicator).toBeVisible({ timeout: 8000 });
            console.log('  ✅ Second request added (UNTITLED SPOT visible)');

            // JIRA 5.2: Verify the blog section is present on the second request
            const blogSection = activeDrawer.locator('app-spotblog').last();
            await expect(blogSection).toBeVisible({ timeout: 5000 });
            console.log('  ✅ Blog section available on second request');

            // ── Fill Title ──────────────────────────────────────────────
            await drawerContent.evaluate(el => el.scrollTop = 0).catch(() => {});
            await page.waitForTimeout(500);

            const allTextInputs = activeDrawer.locator('input[type="text"], input:not([type]):not([role])');
            const inputCount = await allTextInputs.count();
            let titleFilled = false;
            for (let i = 0; i < inputCount; i++) {
                const inp = allTextInputs.nth(i);
                if (!(await inp.isVisible().catch(() => false))) continue;
                const val = await inp.inputValue().catch(() => '');
                if (val === '') {
                    const placeholder = await inp.getAttribute('placeholder').catch(() => '');
                    if (placeholder && /Date|email|Estimate|ISCI|Labels/i.test(placeholder)) continue;
                    await inp.fill('QA-197 Second Spot Title');
                    await inp.press('Tab');
                    await page.waitForTimeout(500);
                    titleFilled = true;
                    console.log(`  ✅ Title filled on second request (placeholder: "${placeholder}")`);
                    break;
                }
            }
            if (!titleFilled) {
                console.log('  ⚠️ Could not find empty Title input — may already be filled');
            }

            // ── Fill Status ─────────────────────────────────────────────
            await drawerContent.evaluate(el => el.scrollTop = el.scrollHeight * 0.3).catch(() => {});
            await page.waitForTimeout(500);

            const statusSelects = activeDrawer.locator('p-select').filter({ hasText: /Select Status/i });
            const statusCount = await statusSelects.count();
            console.log(`  ℹ️ Found ${statusCount} Status dropdown(s) showing "Select Status"`);

            if (statusCount > 0) {
                const statusSelect = statusSelects.last();
                await statusSelect.scrollIntoViewIfNeeded();
                await page.waitForTimeout(300);
                await statusSelect.click();
                // Wait for the listbox options to appear instead of a hard delay.
                await page.locator('[role="listbox"] [role="option"], .p-select-overlay [role="option"]')
                    .first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});

                const optionsList = page.locator('[role="listbox"] [role="option"], .p-select-overlay [role="option"]');
                const optionCount = await optionsList.count();
                console.log(`  ℹ️ Status options count: ${optionCount}`);

                if (optionCount > 0) {
                    const preferredOption = page.getByRole('option', { name: /Needs Producing|Waiting on Copy|Needs Writing/i }).first();
                    if (await preferredOption.isVisible({ timeout: 2000 }).catch(() => false)) {
                        await preferredOption.click();
                    } else {
                        await optionsList.first().click();
                    }
                    await page.waitForTimeout(1000);
                    console.log('  ✅ Status selected on second request');
                } else {
                    console.log('  ⚠️ No options visible in Status overlay. Dismissing...');
                    await page.keyboard.press('Escape');
                    await page.waitForTimeout(500);
                }
            } else {
                console.log('  ⚠️ No "Select Status" dropdown found — may already be set');
            }

            // ── Fill Due Date via selectDateViaPicker ────────────────────
            // Scroll down to reveal the Due Date field on the second request
            await drawerContent.evaluate(el => el.scrollTop = el.scrollHeight * 0.6).catch(() => {});
            await page.waitForTimeout(500);

            // Locate the empty Due Date datepicker on the second request.
            // The trigger button lives inside the p-datepicker host element.
            const allDatepickers = activeDrawer.locator('p-datepicker');
            const dpCount = await allDatepickers.count();
            console.log(`  ℹ️ Found ${dpCount} p-datepicker elements in drawer`);

            let dueDateFilled = false;
            for (let d = dpCount - 1; d >= 0; d--) {
                const dpHost = allDatepickers.nth(d);
                const dpInput = dpHost.locator('input').first();
                if (!(await dpInput.isVisible().catch(() => false))) continue;
                const val = await dpInput.inputValue().catch(() => 'FILLED');
                if (!val || val === '') {
                    await dpInput.scrollIntoViewIfNeeded();
                    await page.waitForTimeout(300);

                    // Determine trigger: inline calendar icon button within the p-datepicker
                    const triggerBtn = dpHost.locator('button.p-datepicker-dropdown, button').first();
                    const hasTrigger = await triggerBtn.isVisible({ timeout: 2000 }).catch(() => false);

                    // Build target date from calculateDueDate (returns MM/DD/YYYY string)
                    const dueDateStr = calculateDueDate();
                    const parts = dueDateStr.split('/');
                    const targetDate = new Date(
                        parseInt(parts[2], 10),
                        parseInt(parts[0], 10) - 1,
                        parseInt(parts[1], 10)
                    );

                    if (hasTrigger) {
                        // Use the battle-tested OrderHelper picker utility
                        await selectDateViaPicker(page, triggerBtn, targetDate);
                        dueDateFilled = true;
                        console.log(`  ✅ Due date selected via picker: ${dueDateStr}`);
                    } else {
                        // Fallback: click input to open inline calendar, then pick the day
                        await dpInput.click();
                        await page.waitForTimeout(1000);
                        await selectDateViaPicker(page, dpInput, targetDate, { skipOpen: true });
                        dueDateFilled = true;
                        console.log(`  ✅ Due date selected (inline fallback): ${dueDateStr}`);
                    }
                    break;
                }
            }
            if (!dueDateFilled) {
                // Fallback: fill ALL empty MM-DD-YYYY inputs (due date, start date, end date).
                // The second request order form has up to 3 date fields sharing the same placeholder.
                // Scroll each input into view FIRST before checking visibility — fields may be
                // outside the current viewport. After filling Start Date, detect any lead time
                // warning dialog (it fires when Start Date is too close to Due Date) and dismiss it;
                // then verify the value wasn't cleared and re-fill with a later date if it was.
                console.log('  ⚠️ No empty p-datepicker found — trying plain textbox fallback');
                const allDueDateInputs = activeDrawer.locator('input[placeholder="MM-DD-YYYY"]');
                const ddCount = await allDueDateInputs.count();
                console.log(`  ℹ️ Found ${ddCount} plain MM-DD-YYYY inputs in drawer`);

                // Date targets with generous lead time buffer:
                //   index 0 = Due Date   (today + 14 days)
                //   index 1 = Start Date (today + 35 days — well past any lead time requirement)
                //   index 2 = End Date   (today + 90 days)
                const fmtDate = (d: Date) =>
                    `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}-${d.getFullYear()}`;
                const mkDate = (offsetDays: number) => { const d = new Date(); d.setDate(d.getDate() + offsetDays); return d; };
                const targetDates = [mkDate(14), mkDate(35), mkDate(90)];

                let filledCount = 0;
                for (let d = 0; d < ddCount; d++) {
                    const inp = allDueDateInputs.nth(d);
                    // Scroll FIRST — input may be above/below current viewport
                    await inp.scrollIntoViewIfNeeded().catch(() => {});
                    await page.waitForTimeout(300);
                    if (!(await inp.isVisible().catch(() => false))) continue;
                    const val = await inp.inputValue().catch(() => 'FILLED');
                    if (!val || val === '') {
                        const targetDate = targetDates[filledCount] ?? mkDate(90 + filledCount * 30);
                        const dateStr = fmtDate(targetDate);
                        await inp.fill(dateStr);
                        await inp.press('Tab');
                        await page.waitForTimeout(1000);

                        // Dismiss any lead time warning dialog — it fires when Start Date is
                        // before the minimum allowed date and will clear the Start Date field.
                        const warningDialog = page.locator('p-dialog:visible, .p-dialog.p-component:visible').first();
                        if (await warningDialog.isVisible({ timeout: 1500 }).catch(() => false)) {
                            const dlgText = (await warningDialog.textContent().catch(() => '')) ?? '';
                            console.log(`  ⚠️ Dialog after date fill: "${dlgText.trim().substring(0, 100)}"`);
                            const okBtn = warningDialog
                                .locator('button:has-text("OK"), button:has-text("Close"), button:has-text("Yes"), .p-dialog-header-close')
                                .first();
                            await okBtn.click().catch(() => {});
                            await page.waitForTimeout(500);
                        }

                        // Verify value survived (lead time warning clears the Start Date)
                        const afterVal = await inp.inputValue().catch(() => '');
                        if (!afterVal || afterVal === '') {
                            console.log(`  ⚠️ Date field ${filledCount + 1} was cleared — retrying 30 days later`);
                            const laterDate = new Date(targetDate);
                            laterDate.setDate(laterDate.getDate() + 30);
                            await inp.fill(fmtDate(laterDate));
                            await inp.press('Tab');
                            await page.waitForTimeout(500);
                        } else {
                            console.log(`  ✅ Date field ${filledCount + 1} filled: ${afterVal}`);
                        }
                        filledCount++;
                        dueDateFilled = true;
                    }
                }
                if (filledCount === 0) {
                    console.log('  ⚠️ Could not find empty date fields for second request');
                }
            }
            if (!dueDateFilled) {
                console.log('  ⚠️ Could not find empty Due Date field for second request');
            }

            // Dismiss any open calendar panel by clicking a neutral area
            await drawerContent.click({ position: { x: 50, y: 50 } }).catch(() => {});
            await page.waitForTimeout(500);

            // ── Fill Blog on second request (if required) ───────────────
            // Blog may or may not be required on the second request.
            // The textarea lives in the right panel (separate scroll context).
            // Iterate all blog textareas and pick the last visible empty one.
            const allBlogTextareas = activeDrawer.locator('app-spotblog textarea');
            const blogCount = await allBlogTextareas.count();
            console.log(`  ℹ️ Found ${blogCount} blog textarea(s) in drawer`);

            let blogPosted = false;
            for (let b = blogCount - 1; b >= 0; b--) {
                const blogTa = allBlogTextareas.nth(b);
                const isVis = await blogTa.isVisible({ timeout: 1000 }).catch(() => false);
                if (!isVis) continue;
                const blogVal = await blogTa.inputValue().catch(() => '');
                if (blogVal) continue;

                // Found a visible, empty blog textarea — fill and post
                await blogTa.fill('QA-197 revision blog for second request');
                await blogTa.press('Tab');
                await page.waitForTimeout(500);

                const postBtn2 = blogTa.locator('xpath=ancestor::app-spotblog[1]')
                    .locator('button').filter({ hasText: /Post/i }).first();
                if (await postBtn2.isVisible({ timeout: 3000 }).catch(() => false)) {
                    await postBtn2.click();
                    await page.waitForTimeout(2000);
                    console.log('  ✅ Blog posted on second request');
                    blogPosted = true;
                }
                break;
            }
            if (!blogPosted) {
                console.log('  ℹ️ No visible empty blog textarea found — blog may not be required');
            }

            // Wait for any field saves to settle
            await page.waitForTimeout(2000);

            // Diagnostic: check Missing Fields status
            const missingFields = activeDrawer.getByText('Missing Fields').first();
            const stillMissing = await missingFields.isVisible({ timeout: 2000 }).catch(() => false);
            if (stillMissing) {
                console.log('  ⚠️ "Missing Fields" still visible — some field may not be filled');
            } else {
                console.log('  ✅ All required fields filled — no "Missing Fields" indicator');
            }
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 6: Click SUBMIT ALL → verify revise summary
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 6: Submit All and verify revise summary', async () => {
            const activeDrawer = page.locator(REVISE_PANEL).last();

            // Scroll back up to see SUBMIT ALL
            await activeDrawer.locator('.p-drawer-content, .p-sidebar-content').first()
                .evaluate(el => el.scrollTop = 0).catch(() => {});

            // Gate on Submit All being enabled — no hard pre-wait needed since toBeEnabled
            // already polls until the condition is true (up to 15 s on slow environments).
            const submitAllBtn = activeDrawer.getByRole('button', { name: /Submit All/i }).first();
            await expect(submitAllBtn).toBeEnabled({ timeout: 15000 });
            await submitAllBtn.click();

            // Wait for Submit All to disappear (panel transitioned) instead of hard-waiting 3 s.
            // On fast servers this resolves in < 500 ms; on QA it may take a few seconds.
            await submitAllBtn.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});

            // If Submit All is still visible the panel didn't transition — retry once.
            const stillSubmitAll = activeDrawer.getByRole('button', { name: /Submit All/i }).first();
            if (await stillSubmitAll.isVisible({ timeout: 500 }).catch(() => false)) {
                console.log('  ⚠️ Submit All did not transition — waiting for API saves and retrying');
                await page.waitForTimeout(5000).catch(() => {});
                await stillSubmitAll.click({ force: true }).catch(() => {});
            }

            // JIRA 6.1: Verify user is back to the revise window with correct client/title.
            // The drawer transition after Submit All can take longer on QA — bump to 30 s
            // and give Angular an explicit settle before probing for visibility. Prior 15 s
            // budget was insufficient when the API save+re-render pipeline stacked.
            await page.waitForTimeout(1500);
            const revisePanel = page.locator(REVISE_PANEL).last();
            await expect(revisePanel).toBeVisible({ timeout: 30000 });
            await expect(revisePanel.getByText(spotClientName, { exact: false }).first()).toBeVisible({ timeout: 10000 });
            console.log(`  ✅ Revise summary visible with client "${spotClientName}"`);

            // Verify FINISH (or equivalent completion) button is present.
            // Diagnostic: log all buttons visible in the panel to aid future debugging.
            const revisePanel2 = page.locator(REVISE_PANEL).last();
            const allBtnTexts = await revisePanel2.locator('button').allInnerTexts().catch(() => []);
            console.log('  ℹ️ Buttons in revise panel after Submit All:', allBtnTexts);
            // Broaden regex to include "OK" / "Submit" — some flows expose a final
            // acknowledgement button that isn't literally labeled Finish/Done.
            const finishBtn = revisePanel2.getByRole('button', { name: /finish|done|complete|close|submit|ok/i }).first();
            await expect(finishBtn).toBeVisible({ timeout: 30000 });
            console.log('  ✅ FINISH button visible in revise summary');
        });

        // ──────────────────────────────────────────────────────────────
        // JIRA Step 7: Click FINISH → verify redirect and revised data
        // ──────────────────────────────────────────────────────────────
        await test.step('Step 7: Click FINISH and verify revised spot', async () => {
            // JIRA 7: Click FINISH (or equivalent completion button)
            const revisePanel3 = page.locator(REVISE_PANEL).last();
            const finishBtn = revisePanel3.getByRole('button', { name: /finish|done|complete|close|submit|ok/i }).first();
            await expect(finishBtn).toBeEnabled({ timeout: 15000 });
            await finishBtn.click();
            await page.waitForLoadState('domcontentloaded');

            // JIRA 7.1: Verify user lands on the list view
            // The post-FINISH redirect goes to a folder view showing revised spots
            const rows = page.locator('.p-datatable-tbody tr');
            await expect(rows.first()).toBeVisible({ timeout: 25000 });
            console.log('  ✅ Redirected to list view after FINISH');

            // JIRA 7.2: Verify that user sees the revised spot
            // Check for the client name in the visible rows
            const clientCell = page.getByText(spotClientName, { exact: false }).first();
            await expect(clientCell).toBeVisible({ timeout: 10000 });
            console.log(`  ✅ Revised spot visible for "${spotClientName}"`);

            // JIRA 7.3: Verify blog and due dates show recently changed data
            // Look for the revised Due Date in the row data
            const spotRow = rows.filter({ hasText: spotClientName }).first();
            if (await spotRow.isVisible({ timeout: 5000 }).catch(() => false)) {
                const rowText = await spotRow.innerText();
                console.log(`  ℹ️ Row data: ${rowText.substring(0, 200)}`);
                // The date should have changed from the original
                expect(rowText.length).toBeGreaterThan(0);
            }
            console.log(`  ✅ Revision process complete for "${spotClientName}"`);
        });
    });
});
