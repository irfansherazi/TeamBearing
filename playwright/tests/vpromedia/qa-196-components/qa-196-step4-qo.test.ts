import { test } from '../../../utils/setup';
import { runQOInteraction } from '../qa-196-files_qo_interaction';

test.describe('QA-196 Component: Step 4 - QO Interaction', () => {
    test('Submit a Production Order with files', async ({ browser }) => {
        test.setTimeout(340000); // Stay under 360s subprocess limit (playwright_routes.py L1120)
        await runQOInteraction(browser);
    });
});
