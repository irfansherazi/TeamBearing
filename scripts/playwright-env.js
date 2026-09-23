/**
 * Playwright browser location for Memory Watch.
 * Cursor's agent sandbox sets PLAYWRIGHT_BROWSERS_PATH to a temp folder
 * that does not contain Chrome. Drop that path so Windows and Mac use the
 * normal Playwright cache, then install Chromium there if it is missing.
 */

const { execFileSync, spawnSync } = require('child_process');

/**
 * True when a browsers path is Cursor's empty sandbox cache.
 *
 * @param browsersPath - PLAYWRIGHT_BROWSERS_PATH value
 * @returns Whether Memory Watch should ignore the path
 */
function isCursorSandboxBrowsersPath(browsersPath) {
    return /cursor-sandbox-cache/i.test(browsersPath || '');
}

/**
 * Copy env and drop a Cursor sandbox browser path.
 *
 * @param source - Process env to copy
 * @returns Env safe to pass to Playwright
 */
function prepareBrowserEnv(source) {
    const env = { ...source };
    if (isCursorSandboxBrowsersPath(env.PLAYWRIGHT_BROWSERS_PATH)) {
        delete env.PLAYWRIGHT_BROWSERS_PATH;
    }
    return env;
}

/**
 * True when Playwright's Chromium binary is already on disk.
 *
 * @param env - Env for the check (sandbox path already removed)
 * @param cwd - vReview root
 * @returns Whether chrome can be launched
 */
function chromiumReady(env, cwd) {
    const script = [
        "const fs = require('fs');",
        "const { chromium } = require('@playwright/test');",
        'const executable = chromium.executablePath();',
        "process.stdout.write(executable && fs.existsSync(executable) ? 'yes' : 'no');"
    ].join('');
    try {
        const output = execFileSync(process.execPath, ['-e', script], {
            cwd,
            env,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'ignore']
        });
        return output.trim() === 'yes';
    } catch {
        return false;
    }
}

/**
 * Download Playwright Chromium into the normal cache.
 *
 * @param env - Env for the install
 * @param cwd - vReview root
 * @returns Exit code from playwright install
 */
function installChromium(env, cwd) {
    const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
    const result = spawnSync(npx, ['playwright', 'install', 'chromium'], {
        cwd,
        env,
        stdio: 'inherit',
        shell: process.platform === 'win32'
    });
    return result.status ?? 1;
}

module.exports = {
    isCursorSandboxBrowsersPath,
    prepareBrowserEnv,
    chromiumReady,
    installChromium
};
