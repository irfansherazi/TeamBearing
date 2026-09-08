const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { buildScope } = require('./scope');

function fakeGit(overrides = {}) {
    return {
        getCurrentBranch: () => 'Syed/TD-260',
        getLocalChangedFiles: () => [],
        listBranchChangedFiles: () => ({ files: ['a.ts'], status: 'ok', warning: null }),
        gitRefExists: () => true,
        resolveCommitShas: (refs) => refs.map((r) => `${r}0000000000000000000000000000000000`.slice(0, 40)),
        isReachableFrom: () => true,
        listFilesForCommits: () => ['a.ts'],
        ...overrides
    };
}

describe('buildScope', () => {
    test('branch mode auto-detects master base for a -master suffixed branch', () => {
        const git = fakeGit({ getCurrentBranch: () => 'Syed/VC2-9999-master' });
        const config = { mode: 'branch', branch: '', baseBranch: 'Develop', commits: [] };

        const scope = buildScope(config, git);

        assert.equal(scope.mode, 'branch');
        assert.equal(scope.baseBranch, 'master');
        assert.match(scope.baseSource, /-master/);
    });

    test('branch mode respects an explicit --base over suffix auto-detection', () => {
        const git = fakeGit({ getCurrentBranch: () => 'Syed/VC2-9999-master' });
        const config = { mode: 'branch', branch: '', baseBranch: 'Release-Candidate', baseBranchExplicit: true, commits: [] };

        const scope = buildScope(config, git);

        assert.equal(scope.baseBranch, 'Release-Candidate');
        assert.equal(scope.baseSource, 'from --base');
    });

    test('branch mode falls back to team default when no suffix matches', () => {
        const git = fakeGit({ getCurrentBranch: () => 'Syed/TD-260' });
        const config = { mode: 'branch', branch: '', baseBranch: 'Develop', commits: [] };

        const scope = buildScope(config, git);

        assert.equal(scope.baseBranch, 'Develop');
        assert.equal(scope.baseSource, 'team default');
    });

    test('branch mode falls back to local uncommitted changes when the range has no committed diff', () => {
        const git = fakeGit({
            listBranchChangedFiles: () => ({ files: [], status: 'empty', warning: null }),
            getLocalChangedFiles: () => ['local-only.ts']
        });
        const config = { mode: 'branch', branch: '', baseBranch: 'Develop', commits: [] };

        const scope = buildScope(config, git);

        assert.equal(scope.usedLocalFallback, true);
        assert.deepEqual(scope.files, ['local-only.ts']);
        assert.equal(scope.diffRange, null);
    });

    test('files mode reviews local changed files only', () => {
        const git = fakeGit({ getLocalChangedFiles: () => ['x.ts', 'y.html'] });
        const config = { mode: 'files', commits: [] };

        const scope = buildScope(config, git);

        assert.equal(scope.mode, 'files');
        assert.deepEqual(scope.files, ['x.ts', 'y.html']);
    });

    test('commits mode takes priority over branch/files mode when --commits is set', () => {
        const git = fakeGit();
        const config = { mode: 'branch', commits: ['abc1234'], baseBranch: 'Develop' };

        const scope = buildScope(config, git);

        assert.equal(scope.mode, 'commits');
        assert.equal(scope.commits.length, 1);
    });

    test('commits mode throws when a SHA is not reachable from the target branch', () => {
        const git = fakeGit({ isReachableFrom: () => false });
        const config = { mode: 'branch', commits: ['abc1234'], baseBranch: 'Develop' };

        assert.throws(() => buildScope(config, git), /not on branch/);
    });
});
