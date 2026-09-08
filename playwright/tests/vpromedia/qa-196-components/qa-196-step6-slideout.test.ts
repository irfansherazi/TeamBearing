import { test } from '../../../utils/setup';
import { runSlideoutValidation } from '../qa-196-files_slideout_panel';
import * as path from 'path';
import * as fs from 'fs';

const TEST_ENV = process.env.TEST_ENV || 'test';

test.describe('QA-196 Component: Step 6 - Slideout Panel', () => {
    test('Slideout Panel file actions', async ({ browser }) => {
        test.setTimeout(240000); // Stay under 360s subprocess limit (playwright_routes.py L1120)
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
        await runSlideoutValidation(browser);
    });
});
