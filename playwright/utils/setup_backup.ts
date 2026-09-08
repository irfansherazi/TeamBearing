import { test as baseTest } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Ensure STORAGE_DIR is aligned with generateStorageStates.mjs
const TEST_ENV = process.env.TEST_ENV || 'smoke';
export const STORAGE_DIR = path.resolve(__dirname, '..', 'storage', TEST_ENV);

// Function to get available user storage states
export function getDetectedUsers(): string[] {
    if (!fs.existsSync(STORAGE_DIR)) return [];
    try {
        return fs
            .readdirSync(STORAGE_DIR)
            .filter(file => file.startsWith('storageState_') && file.endsWith('.json'))
            .map(file => file.replace('storageState_', '').replace('.json', ''));
    } catch (error) {
        console.error(`❌ Error reading storage directory: ${STORAGE_DIR}`, error);
        return [];
    }
}

// Function to retrieve a specific user's storage state path
export function getUserStorageState(user: string) {
    return path.join(STORAGE_DIR, `storageState_${user}.json`);
}

// Select a user dynamically (first available or fallback)
const availableUsers = getDetectedUsers();
const selectedUser = availableUsers.length > 0 ? availableUsers[0] : null;

// ✅ Playwright test fixture with dynamic storage state
export const test = baseTest.extend<{ user: string }>({
    user: async ({}, use) => {
        await use(selectedUser || 'NoUserFound');
    },
    context: async ({ browser }, use) => {
        const storageStatePath = selectedUser ? getUserStorageState(selectedUser) : undefined;
        const context = await browser.newContext(
            storageStatePath ? { storageState: storageStatePath } : {}
        );
        await use(context);
    },
    page: async ({ context }, use) => {
        const page = await context.newPage();
        await use(page);
    }
});

export function logTestInfo() {
    const users = getDetectedUsers();
    console.log(`🌎 TEST_ENV: ${TEST_ENV}`);
    console.log(`📂 STORAGE_DIR: ${STORAGE_DIR}`);
    console.log(`👥 Detected Users: ${users.length > 0 ? 'Yes' : 'No'}`);
}