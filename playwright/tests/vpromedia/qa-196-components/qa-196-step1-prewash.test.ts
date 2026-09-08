import { test } from '../../../utils/setup';
import { runFilePreWash } from '../filePreWashUtility';

test.describe('QA-196 Component: Step 1 - Pre-Wash', () => {
    test('Remove client files (Pre-Wash)', async ({ browser }) => {
        await runFilePreWash(browser);
    });
});
