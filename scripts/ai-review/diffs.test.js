const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { truncateDiff, collectDiffs } = require('./diffs');

describe('truncateDiff', () => {
    test('returns the diff unchanged when under the line cap', () => {
        const diff = 'line1\nline2\nline3';
        const result = truncateDiff(diff, 8000);

        assert.equal(result.diff, diff);
        assert.equal(result.truncated, false);
        assert.equal(result.totalLines, 3);
    });

    test('truncates and appends a marker when over the line cap', () => {
        const diff = Array.from({ length: 10 }, (_, i) => `line${i}`).join('\n');
        const result = truncateDiff(diff, 3);

        assert.equal(result.truncated, true);
        assert.equal(result.totalLines, 10);
        assert.match(result.diff, /diff truncated \(7 more lines\)/);
        assert.equal(result.diff.split('\n').filter((l) => l.startsWith('line')).length, 3);
    });
});

describe('collectDiffs', () => {
    function fakeGit({ diffOutput = '' } = {}) {
        return {
            runGit: () => diffOutput || null,
            getDiffForRange: () => diffOutput
        };
    }

    test('embeds new/untracked file content into the unified diff (regression: previously silently dropped)', () => {
        const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-diffs-'));
        const fileName = 'brand-new-file.js';
        const content = "const x = 1;\nmodule.exports = { x };\n";
        fs.writeFileSync(path.join(rootDir, fileName), content, 'utf8');

        const scope = { mode: 'files', files: [fileName], diffRange: null };
        const git = fakeGit();
        const config = { maxDiffLines: 8000 };

        const result = collectDiffs(scope, git, config, rootDir);

        assert.match(result.unified, /brand-new-file\.js \(new\/untracked file/);
        assert.match(result.unified, /const x = 1;/);
        assert.match(result.perFile[fileName], /^\(new\/untracked file/);

        fs.rmSync(rootDir, { recursive: true, force: true });
    });

    test('does not add untracked-file blocks when git already reports a tracked diff', () => {
        const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-diffs-'));
        const fileName = 'tracked-file.js';
        fs.writeFileSync(path.join(rootDir, fileName), 'const y = 2;\n', 'utf8');

        const scope = { mode: 'files', files: [fileName], diffRange: null };
        const git = {
            runGit: () => '--- a/tracked-file.js\n+++ b/tracked-file.js\n+const y = 2;',
            getDiffForRange: () => '--- a/tracked-file.js\n+++ b/tracked-file.js\n+const y = 2;'
        };
        const config = { maxDiffLines: 8000 };

        const result = collectDiffs(scope, git, config, rootDir);

        assert.doesNotMatch(result.unified, /not shown by `git diff`/);

        fs.rmSync(rootDir, { recursive: true, force: true });
    });

    test('commits mode builds unified diff from git.getDiffForCommits', () => {
        const scope = { mode: 'commits', files: ['a.js'], commits: ['abc123'], baseBranchForFallback: 'Develop' };
        const git = {
            getDiffForCommits: () => '# Commit abc123\n+added line',
            getDiffForCommitFile: () => '+added line'
        };
        const config = { maxDiffLines: 8000 };

        const result = collectDiffs(scope, git, config, '/unused');

        assert.match(result.unified, /Commit abc123/);
        assert.equal(result.perFile['a.js'], '+added line');
    });
});
