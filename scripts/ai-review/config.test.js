const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
    normalizeApp,
    resolveReviewRoot,
    parseCliArgs,
    loadConfig,
    looksLikeVcapiRoot,
    looksLikePlatformRoot
} = require('./config');

describe('normalizeApp', () => {
    const cases = [
        { description: 'empty becomes platform', input: '', expected: 'platform' },
        { description: 'platform stays platform', input: 'platform', expected: 'platform' },
        { description: 'vsuite aliases to platform', input: 'vsuitePlatform', expected: 'platform' },
        { description: 'vcapi stays vcapi', input: 'vcapi', expected: 'vcapi' },
        { description: 'unknown becomes empty', input: 'other', expected: '' }
    ];

    cases.forEach(({ description, input, expected }) => {
        test(description, () => {
            assert.equal(normalizeApp(input), expected);
        });
    });
});

describe('parseCliArgs --app', () => {
    test('parses --app=vcapi', () => {
        const cli = parseCliArgs(['node', 'ai-review.js', '--app=vcapi', '--scope-only']);
        assert.equal(cli.app, 'vcapi');
        assert.equal(cli.scopeOnly, true);
    });

    test('accepts bare vcapi token (PowerShell npm mangling)', () => {
        const cli = parseCliArgs(['node', 'ai-review.js', '--scope-only', 'vcapi']);
        assert.equal(cli.app, 'vcapi');
    });
});

describe('resolveReviewRoot', () => {
    test('platform returns sibling vsuitePlatform', () => {
        const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-apps-'));
        const toolRoot = path.join(parent, 'vReview');
        const platformRoot = path.join(parent, 'vsuitePlatform');
        fs.mkdirSync(toolRoot);
        fs.mkdirSync(platformRoot);
        fs.writeFileSync(path.join(platformRoot, 'angular.json'), '{}');
        const exit = () => {
            throw new Error('should not exit');
        };
        assert.equal(resolveReviewRoot(toolRoot, 'platform', exit), platformRoot);
        fs.rmSync(parent, { recursive: true, force: true });
    });

    test('vcapi resolves sibling folder with AGENTS.md', () => {
        const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-apps-'));
        const toolRoot = path.join(parent, 'vReview');
        const vcapiRoot = path.join(parent, 'vcapi');
        fs.mkdirSync(toolRoot);
        fs.mkdirSync(vcapiRoot);
        fs.writeFileSync(path.join(vcapiRoot, 'package.json'), '{"name":"vcapi"}');
        fs.writeFileSync(path.join(vcapiRoot, 'AGENTS.md'), '# mandates');

        const exit = (msg) => {
            throw new Error(msg);
        };
        assert.equal(resolveReviewRoot(toolRoot, 'vcapi', exit), vcapiRoot);
        assert.equal(looksLikeVcapiRoot(vcapiRoot), true);

        fs.rmSync(parent, { recursive: true, force: true });
    });

    test('vcapi missing sibling exits with clear error', () => {
        const toolRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-missing-'));
        let message = '';
        const exit = (msg) => {
            message = msg;
            throw new Error(msg);
        };
        assert.throws(() => resolveReviewRoot(toolRoot, 'vcapi', exit));
        assert.match(message, /Could not find vcapi/);
        fs.rmSync(toolRoot, { recursive: true, force: true });
    });
});

describe('loadConfig from vReview against sibling apps', () => {
    test('loads platform and vcapi standards from vReview folders', () => {
        const toolRoot = path.resolve(__dirname, '..', '..');
        const exit = (msg) => {
            throw new Error(msg);
        };

        if (!looksLikePlatformRoot(path.resolve(toolRoot, '..', 'vsuitePlatform'))) {
            return;
        }

        const platform = loadConfig(toolRoot, ['node', 'ai-review.js', '--scope-only'], exit);
        assert.equal(platform.config.app, 'platform');
        assert.equal(platform.rootDir, path.resolve(toolRoot, '..', 'vsuitePlatform'));
        assert.equal(platform.config.baseBranch, 'Develop');
        assert.equal(platform.config.instructionsFile, 'pr-review-checklist.md');
        assert.equal(platform.config.standardsDir, path.join(toolRoot, 'standards', 'platform'));
        assert.equal(platform.config.toolRootDir, toolRoot);

        const vcapiSibling = path.resolve(toolRoot, '..', 'vcapi');
        if (!looksLikeVcapiRoot(vcapiSibling)) {
            return;
        }

        const vcapi = loadConfig(toolRoot, ['node', 'ai-review.js', '--app=vcapi', '--scope-only'], exit);
        assert.equal(vcapi.config.app, 'vcapi');
        assert.equal(vcapi.rootDir, vcapiSibling);
        assert.equal(vcapi.config.baseBranch, 'develop');
        assert.equal(vcapi.config.instructionsFile, 'pr-review-checklist.md');
        assert.deepEqual(vcapi.config.sourceOfTruthDocs, ['AGENTS.md']);
        assert.equal(vcapi.config.standardsDir, path.join(toolRoot, 'standards', 'vcapi'));
        assert.equal(vcapi.config.automatedChecks['CQ-08'], 'lint');
        assert.equal(vcapi.config.automatedChecks['CQ-23'], undefined);
    });
});
