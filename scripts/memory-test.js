/**
 * CLI wrapper: npm run memory:test -- --flow=po-open-spot --env=qa --cycles=5
 */

const { spawn } = require('child_process');
const path = require('path');
const { prepareBrowserEnv, chromiumReady, installChromium, isCursorSandboxBrowsersPath } = require('./playwright-env');

const FLOW_IDS = [
    'qo-open-close-snapshot',
    'po-open-spot',
    'po-open-spot-warm',
    'po-search-panel',
    'ai-intake-open-close',
    'sidebar-open-close',
];
const ENVS = ['local', 'qa', 'test', 'smoke'];

/**
 * Parse --flow / --env / --cycles from argv.
 *
 * @param argv - process.argv
 * @returns Normalized CLI flags
 */
function parseArgs(argv) {
    const parsed = {
        flow: 'qo-open-close-snapshot',
        env: 'qa',
        cycles: '5',
        maxGrowthMb: '',
    };
    for (const arg of argv.slice(2)) {
        if (arg.startsWith('--flow=')) {
            parsed.flow = arg.slice('--flow='.length).trim();
        } else if (arg.startsWith('--env=')) {
            parsed.env = arg.slice('--env='.length).trim();
        } else if (arg.startsWith('--cycles=')) {
            parsed.cycles = arg.slice('--cycles='.length).trim();
        } else if (arg.startsWith('--max-growth-mb=')) {
            parsed.maxGrowthMb = arg.slice('--max-growth-mb='.length).trim();
        }
    }
    return parsed;
}

const flags = parseArgs(process.argv);
if (!FLOW_IDS.includes(flags.flow)) {
    process.stderr.write(`Unknown --flow=${flags.flow}. Use: ${FLOW_IDS.join(', ')}\n`);
    process.exit(2);
}
if (!ENVS.includes(flags.env)) {
    process.stderr.write(`Unknown --env=${flags.env}. Use: ${ENVS.join(', ')}\n`);
    process.exit(2);
}

const root = path.resolve(__dirname, '..');
const sawSandboxBrowsers = isCursorSandboxBrowsersPath(process.env.PLAYWRIGHT_BROWSERS_PATH);
const env = prepareBrowserEnv({
    ...process.env,
    MEMORY_FLOW: flags.flow,
    MEMORY_CYCLES: flags.cycles,
    TEST_ENV: flags.env,
    VQA_HEADLESS: process.env.VQA_HEADLESS ?? '1',
});
if (flags.maxGrowthMb) {
    env.MEMORY_MAX_GROWTH_MB = flags.maxGrowthMb;
}
if (sawSandboxBrowsers) {
    process.stderr.write('Ignoring Cursor sandbox browser path. Using the normal Playwright Chrome install.\n');
}
if (!chromiumReady(env, root)) {
    process.stderr.write('Playwright Chrome is not installed. Downloading it once...\n');
    const installCode = installChromium(env, root);
    if (installCode !== 0) {
        process.stderr.write('Could not install Playwright Chrome. From the vReview folder run: npx playwright install chromium\n');
        process.exit(installCode);
    }
}

const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const child = spawn(
    npx,
    ['playwright', 'test', 'playwright/tests/memory/memory-watch.test.ts', '--project=chromium'],
    {
        cwd: root,
        env,
        stdio: 'inherit',
        shell: process.platform === 'win32',
    }
);
child.on('exit', (code) => {
    process.exit(code ?? 1);
});
