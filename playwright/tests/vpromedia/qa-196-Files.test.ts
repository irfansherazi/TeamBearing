import { test } from '../../utils/setup';
import { runFilePreWash } from './filePreWashUtility';
import { runClientUpload } from './qa-196-files_client_upload';
import { runAudioValidation } from './qa-196-client_audio';
import { runQOInteraction } from './qa-196-files_qo_interaction';
import { runListviewActions } from './qa-196-files_listview_actions';
import { runSlideoutValidation } from './qa-196-files_slideout_panel';
import { runHistoryValidation } from './qa-196-files_history_validation';

test.describe.configure({ mode: 'serial' });

test.describe('QA-196: Files Orchestration - Master Serial Suite', () => {
    test.use({ viewport: { width: 1529, height: 960 } });

    test('Step 1: Remove client files (Pre-Wash)', async ({ browser }) => {
        test.setTimeout(340000);
        await runFilePreWash(browser);
    });

    test('Step 2: Add client files (Upload)', async ({ browser }) => {
        test.setTimeout(340000);
        await runClientUpload(browser);
    });

    test('Step 3: Validate client files (Audio)', async ({ browser }) => {
        test.setTimeout(340000);
        await runAudioValidation(browser);
    });

    test('Step 4: Submit a Production Order with files', async ({ browser }) => {
        test.setTimeout(340000);
        await runQOInteraction(browser);
    });

    test('Step 5: List View file actions', async ({ browser }) => {
        test.setTimeout(340000);
        await runListviewActions(browser);
    });

    test('Step 6: Slideout Panel file actions', async ({ browser }) => {
        test.setTimeout(340000);
        await runSlideoutValidation(browser);
    });

    test('Step 7: Confirm history log validation', async ({ browser }) => {
        test.setTimeout(340000);
        await runHistoryValidation(browser);
    });
});
