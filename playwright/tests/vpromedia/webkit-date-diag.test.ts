/**
 * Diagnostic: WebKit date input investigation
 * 
 * Creates a basic order (which populates the form including date fields),
 * then inspects and tests different date input methods on WebKit.
 */
import { test, expect } from '../../utils/setup';
import { openQuickOrderForm, createBasicOrder } from '../../utils/OrderHelper';

test.use({ user: 'DemoProdDirector' });
test.setTimeout(180_000);

test('webkit date input diagnostic', async ({ page }) => {
    // Navigate to inbox
    await page.goto('/#/vpro/production-orders/folder/inbox');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(5000);

    // Open QO form and fill basic fields (this creates date inputs)
    await openQuickOrderForm(page);
    await createBasicOrder(page, { client: "Bob's Burgers", selectStation: true });
    await page.waitForTimeout(2000);

    // ═══════════════════════════════════════════════════════════════
    // STEP 1: Catalog ALL date-related inputs in the DOM
    // ═══════════════════════════════════════════════════════════════
    const allDateInputs = await page.evaluate(() => {
        const results: any[] = [];
        document.querySelectorAll('input').forEach((inp, idx) => {
            const input = inp as HTMLInputElement;
            if (input.id.includes('date') || 
                input.placeholder?.includes('MM') ||
                input.placeholder?.includes('Date') ||
                input.name?.includes('date') ||
                input.getAttribute('aria-label')?.includes('Date')) {
                results.push({
                    index: idx,
                    id: input.id,
                    name: input.name,
                    type: input.type,
                    placeholder: input.placeholder,
                    ariaLabel: input.getAttribute('aria-label'),
                    className: input.className?.substring(0, 80),
                    value: input.value,
                    visible: input.offsetParent !== null,
                    readonly: input.readOnly,
                    disabled: input.disabled,
                    parentHTML: input.parentElement?.outerHTML?.substring(0, 150),
                });
            }
        });
        return results;
    });

    console.log(`\n═══ ALL DATE INPUTS IN DOM (${allDateInputs.length}) ═══`);
    allDateInputs.forEach(d => {
        console.log(`  [${d.visible ? '✅VIS' : '❌HID'}] id="${d.id}" placeholder="${d.placeholder}" type="${d.type}" readonly=${d.readonly} disabled=${d.disabled} value="${d.value}"`);
        console.log(`    class="${d.className}"`);
        console.log(`    parent: ${d.parentHTML}`);
    });

    // ═══════════════════════════════════════════════════════════════
    // STEP 2: Check what getByRole resolves to
    // ═══════════════════════════════════════════════════════════════
    for (const label of ['Due Date', 'Start Date', 'End Date']) {
        const loc = page.getByRole('textbox', { name: new RegExp(label, 'i') }).first();
        const visible = await loc.isVisible({ timeout: 2000 }).catch(() => false);
        if (visible) {
            const info = await loc.evaluate(el => ({
                id: el.id,
                tagName: el.tagName,
                type: (el as HTMLInputElement).type,
                placeholder: (el as HTMLInputElement).placeholder,
                readonly: (el as HTMLInputElement).readOnly,
                disabled: (el as HTMLInputElement).disabled,
                value: (el as HTMLInputElement).value,
            }));
            console.log(`\n🎯 getByRole("${label}"): id="${info.id}" tag=${info.tagName} type=${info.type} placeholder="${info.placeholder}" value="${info.value}" readonly=${info.readonly} disabled=${info.disabled}`);
        } else {
            console.log(`\n❌ getByRole("${label}"): NOT VISIBLE`);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // STEP 3: Target the first visible date input and test methods
    // ═══════════════════════════════════════════════════════════════
    const visibleDate = allDateInputs.find(d => d.visible && d.id.includes('date'));
    if (!visibleDate) {
        console.log('❌ No visible date input found after form creation!');
        return;
    }

    const targetInput = page.locator(`input[id="${visibleDate.id}"]`);
    console.log(`\n═══ TESTING INPUT: #${visibleDate.id} ═══`);

    // Test A: fill()
    console.log('\n--- Test A: fill("03-31-2026") ---');
    await targetInput.fill('03-31-2026');
    let val = await targetInput.inputValue();
    console.log(`  After fill(): value="${val}"`);

    // Small wait, then re-read
    await page.waitForTimeout(500);
    val = await targetInput.inputValue();
    console.log(`  After 500ms: value="${val}"`);

    // Test B: clear + click + keyboard.type with delay  
    await targetInput.fill('');
    await page.waitForTimeout(300);
    console.log('\n--- Test B: click + type("03-31-2026", delay:80) ---');
    await targetInput.click();
    await page.waitForTimeout(200);
    await page.keyboard.type('03-31-2026', { delay: 80 });
    val = await targetInput.inputValue();
    console.log(`  After type(): value="${val}"`);
    await page.waitForTimeout(500);
    val = await targetInput.inputValue();
    console.log(`  After 500ms: value="${val}"`);

    // Test C: clear + pressSequentially (digits only, let mask handle separators)
    await targetInput.fill('');
    await page.waitForTimeout(300);
    console.log('\n--- Test C: click + pressSequentially("03312026", delay:100) ---');
    await targetInput.click();
    await targetInput.pressSequentially('03312026', { delay: 100 });
    val = await targetInput.inputValue();
    console.log(`  After pressSequentially(): value="${val}"`);
    await page.waitForTimeout(500);
    val = await targetInput.inputValue();
    console.log(`  After 500ms: value="${val}"`);

    // Test D: clear + click + type slash format
    await targetInput.fill('');
    await page.waitForTimeout(300);
    console.log('\n--- Test D: click + type("03/31/2026", delay:80) ---');
    await targetInput.click();
    await page.keyboard.type('03/31/2026', { delay: 80 });
    val = await targetInput.inputValue();
    console.log(`  After type(slash): value="${val}"`);
    await page.waitForTimeout(500);
    val = await targetInput.inputValue();
    console.log(`  After 500ms: value="${val}"`);

    // Test E: clear + triple-click to select all + type
    await targetInput.fill('');
    await page.waitForTimeout(300);
    console.log('\n--- Test E: triple-click + type("03312026", delay:50) ---');
    await targetInput.click({ clickCount: 3 });
    await page.keyboard.type('03312026', { delay: 50 });
    val = await targetInput.inputValue();
    console.log(`  After triple-click+type: value="${val}"`);

    console.log('\n═══ DIAGNOSTIC COMPLETE ═══');
});
