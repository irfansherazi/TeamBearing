import { test } from '../../../utils/setup';
import { runListviewActions } from '../qa-196-files_listview_actions';
import * as path from 'path';
import * as fs from 'fs';

const TEST_ENV = process.env.TEST_ENV || 'test';

test.describe('QA-196 Component: Step 5 - List View Actions', () => {
    test('List View file actions', async ({ browser }) => {
        test.setTimeout(180000); // Stay under 360s subprocess limit (playwright_routes.py L1120)
        const browserName = browser.browserType().name();
        const spotDataPath = path.resolve(
            __dirname,
            `../../storage/qa-196/qa-196_spot_data_${TEST_ENV}_${browserName}.json`
        );
        if (!fs.existsSync(spotDataPath)) {
            test.skip(
                true,
                `Spot data file not found at ${spotDataPath}. Run Step 4 (QO Interaction) first.`
            );
            return;
        }
        await runListviewActions(browser);
    });
});
