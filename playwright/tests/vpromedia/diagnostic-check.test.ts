import { test, expect, BASE_URL } from '../../utils/setup';
import { openQuickOrderForm, selectAdType } from '../../utils/OrderHelper';

test.describe('Diagnostic Datepicker Panel', () => {
    test.use({ user: 'DemoSalesExec' });

    test('dump datepicker panel html', async ({ page }) => {
        await openQuickOrderForm(page);
        await selectAdType(page, 'TV Ad (Open submit)');
        await page.waitForTimeout(2000);

        // Click the Due Date trigger button to open the datepicker
        const dueDatePicker = page.locator('p-datepicker.duedatepicker, p-datepicker[name="card_due_date"]').first();
        const triggerButton = dueDatePicker.locator('button.p-datepicker-dropdown').first();
        
        console.log('Clicking Due Date picker dropdown trigger...');
        await triggerButton.click({ force: true });
        await page.waitForTimeout(2000);

        // Find the panel
        const panel = page.locator('.p-datepicker-panel, div.p-datepicker, div.p-datepicker-panel').first();
        const isVisible = await panel.isVisible();
        console.log(`Is datepicker panel visible: ${isVisible}`);

        if (isVisible) {
            const html = await panel.innerHTML();
            console.log('=== DATEPICKER PANEL HTML ===');
            console.log(html);
            console.log('==============================');
        } else {
            console.log('Datepicker panel not visible! Let\'s list all elements with class containing "datepicker" or "calendar":');
            const classes = await page.evaluate(() => {
                const els = Array.from(document.querySelectorAll('*'));
                return els
                    .map(el => el.className)
                    .filter(c => typeof c === 'string' && (c.includes('datepicker') || c.includes('calendar') || c.includes('overlay')))
                    .slice(0, 50);
            });
            console.log('Found classes:', classes);
        }
    });
});
