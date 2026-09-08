import { test } from '../../../utils/setup';
import { runClientUpload } from '../qa-196-files_client_upload';

test.describe('QA-196 Component: Step 2 - Client Upload', () => {
    test('Add client files (Upload)', async ({ browser }) => {
        await runClientUpload(browser);
    });
});
