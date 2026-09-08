/**
 * CLI wrapper: npm run memory:test -- --flow=po-open-spot --env=qa --cycles=5
 */

const { spawn } = require('child_process');
const path = require('path');

const FLOW_IDS = [
    'po-open-spot',
    'po-search-panel',
    'ai-intake-open-close',
    'sidebar-open-close',
];
const ENVS = ['qa', 'test', 'smoke'];

/**
 * Parse --flow / --env / --cycles from argv.
 *
 * @param argv - process.argv
 * @returns Normalized CLI flags
 */
function parseArgs(argv) {
    const parsed = {
        flow: 'po-open-spot',
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

const env = {
    ...process.env,
    MEMORY_FLOW: flags.flow,
    MEMORY_CYCLES: flags.cycles,
    TEST_ENV: flags.env,
    VQA_HEADLESS: process.env.VQA_HEADLESS ?? '1',
};
if (flags.maxGrowthMb) {
    env.MEMORY_MAX_GROWTH_MB = flags.maxGrowthMb;
}

const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const child = spawn(
    npx,
    ['playwright', 'test', 'playwright/tests/memory/memory-watch.test.ts', '--project=chromium'],
    {
        cwd: path.resolve(__dirname, '..'),
        env,
        stdio: 'inherit',
        shell: process.platform === 'win32',
    }
);
child.on('exit', (code) => {
    process.exit(code ?? 1);
});
