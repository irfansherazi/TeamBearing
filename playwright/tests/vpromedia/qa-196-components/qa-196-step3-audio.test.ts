import { test } from '../../../utils/setup';
import { runAudioValidation } from '../qa-196-client_audio';

test.describe('QA-196 Component: Step 3 - Audio Validation', () => {
    test('Validate client files (Audio)', async ({ browser }) => {
        await runAudioValidation(browser);
    });
});
