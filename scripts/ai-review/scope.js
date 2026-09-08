const { DEFAULT_BASE_BRANCH, DEFAULT_BRANCH_NAME_RULES } = require('./constants');

/**
 * Gets the branch-suffix -> base-branch auto-detection rules to use
 * @param config: object - merged ai-review config
 * @returns array - valid { suffix, baseBranch } rules
 */
function getBranchNameRules(config) {
    if (!Array.isArray(config.branchNameRules) || config.branchNameRules.length === 0) {
        return DEFAULT_BRANCH_NAME_RULES;
    }
    return config.branchNameRules.filter((rule) => rule?.suffix && rule?.baseBranch);
}

/**
 * Resolves the target branch and its base branch (from --base, suffix rules, or team default)
 * @param config: object - merged ai-review config
 * @param git: object - git runner from git.js
 * @returns object - { baseBranch, branch, baseSource }
 */
function resolveBranchNames(config, git) {
    const branch =
        (config.branch && String(config.branch).trim()) || git.getCurrentBranch();

    if (config.baseBranchExplicit && config.baseBranch) {
        return { baseBranch: config.baseBranch, branch, baseSource: 'from --base' };
    }

    for (const rule of getBranchNameRules(config)) {
        if (branch.endsWith(rule.suffix)) {
            return {
                baseBranch: rule.baseBranch,
                branch,
                baseSource: `auto-detected (*${rule.suffix})`
            };
        }
    }

    return {
        baseBranch: config.baseBranch || DEFAULT_BASE_BRANCH,
        branch,
        baseSource: 'team default'
    };
}

/**
 * Appends a "Changed files (N): ..." block to scope-text lines, or an empty-message fallback
 * @param lines: array - scope-text lines to append to, mutated in place
 * @param files: array - file paths to list
 * @param emptyMessage: string - message to append when files is empty
 * @returns void
 */
function appendFileList(lines, files, emptyMessage) {
    if (files.length > 0) {
        lines.push('', `Changed files (${files.length}):`);
        files.forEach((file) => lines.push(`- ${file}`));
    } else {
        lines.push('', emptyMessage);
    }
}

/**
 * Builds scope for --commits mode: resolves and validates the given commit SHAs
 * and lists the files they touch
 * @param config: object - merged ai-review config
 * @param git: object - git runner from git.js
 * @returns object - resolved scope for commits mode
 */
function buildCommitsScope(config, git) {
    const rawCommits = Array.isArray(config.commits) ? config.commits : [];
    if (rawCommits.length === 0) {
        throw new Error('No commits specified. Use --commits=abc1234,def5678');
    }

    let commitShas;
    try {
        commitShas = git.resolveCommitShas(rawCommits);
    } catch (err) {
        throw err;
    }

    const branchExplicit = Boolean(config.branch && String(config.branch).trim());
    const branch = branchExplicit ? String(config.branch).trim() : git.getCurrentBranch();
    const baseBranch = config.baseBranchExplicit ? config.baseBranch : null;
    const baseSource = config.baseBranchExplicit ? 'from --base' : null;
    const baseBranchForFallback =
        config.baseBranchExplicit && config.baseBranch
            ? config.baseBranch
            : config.baseBranch || DEFAULT_BASE_BRANCH;

    if (!git.gitRefExists(branch)) {
        return {
            mode: 'commits',
            commits: commitShas,
            baseBranch,
            baseSource,
            branch,
            branchExplicit,
            baseBranchForFallback,
            diffRange: null,
            files: [],
            status: 'missing-ref',
            warning: `Missing local ref: ${branch}. Try: git fetch`,
            usedLocalFallback: false,
            inspectCommand: commitShas.map((sha) => `git show ${sha.slice(0, 7)}`).join(' && '),
            scopeText: [
                'Mode: commits',
                `Commits (${commitShas.length}): ${commitShas.map((sha) => sha.slice(0, 7)).join(', ')}`,
                branchExplicit
                    ? `Target branch: ${branch} (from --branch)`
                    : `Target branch: ${branch} (current)`,
                baseBranch ? `Base branch: ${baseBranch} (${baseSource})` : null,
                '',
                `Missing local ref: ${branch}. Try: git fetch`
            ]
                .filter(Boolean)
                .join('\n')
        };
    }

    for (const sha of commitShas) {
        if (!git.isReachableFrom(sha, branch)) {
            throw new Error(
                `Commit ${sha.slice(0, 7)} is not on branch ${branch}. Each --commits SHA must exist in that branch's history. Check the SHA, --branch, or run git fetch.`
            );
        }
    }

    const files = git.listFilesForCommits(commitShas);
    const shortShas = commitShas.map((sha) => sha.slice(0, 7)).join(', ');
    const inspectCommand = commitShas.map((sha) => `git show ${sha.slice(0, 7)}`).join(' && ');

    const lines = [
        'Mode: commits',
        `Commits (${commitShas.length}): ${shortShas}`,
        branchExplicit
            ? `Target branch: ${branch} (from --branch)`
            : `Target branch: ${branch} (current)`,
        'Review ONLY the changes in these commits (not the full branch diff).',
        `Inspect with: ${inspectCommand}`
    ];

    if (baseBranch) {
        lines.splice(3, 0, `Base branch: ${baseBranch} (${baseSource}) — optional context / root-commit fallback`);
    }

    if (files.length > 0) {
        appendFileList(lines, files, 'Changed files: none detected for these commits.');
    } else {
        lines.push('', 'Changed files: none detected for these commits.');
    }

    return {
        mode: 'commits',
        commits: commitShas,
        baseBranch,
        baseSource,
        branch,
        branchExplicit,
        baseBranchForFallback,
        diffRange: null,
        files,
        status: files.length > 0 ? 'ok' : 'empty',
        warning: null,
        usedLocalFallback: false,
        inspectCommand,
        scopeText: lines.join('\n')
    };
}

/**
 * Builds scope for branch mode: diffs base...branch, falling back to local
 * uncommitted changes when the range has no committed diff
 * @param config: object - merged ai-review config
 * @param git: object - git runner from git.js
 * @returns object - resolved scope for branch mode
 */
function buildBranchScope(config, git) {
    const { baseBranch, branch, baseSource } = resolveBranchNames(config, git);
    const diffRange = `${baseBranch}...${branch}`;
    const { files, status, warning } = git.listBranchChangedFiles(diffRange);
    const localFiles = git.getLocalChangedFiles();

    let resolvedFiles = files;
    let usedLocalFallback = false;

    if (files.length === 0 && localFiles.length > 0 && status !== 'missing-ref' && status !== 'failed') {
        resolvedFiles = localFiles;
        usedLocalFallback = true;
    }

    const lines = [
        'Mode: branch',
        `Base branch: ${baseBranch} (${baseSource})`,
        `Target branch: ${branch}`,
        `Diff range: ${diffRange}`,
        'Review ONLY the changes in this diff (not untouched code).',
        `Inspect with: git diff ${diffRange}`
    ];

    if (status === 'missing-ref' || status === 'failed') {
        lines.push('', warning);
    } else if (files.length > 0) {
        appendFileList(lines, files, 'Changed files: none detected for this range.');
    } else if (usedLocalFallback) {
        lines.push(
            '',
            `No committed changes in ${diffRange}.`,
            'Falling back to local uncommitted changes.',
            'Inspect with: git status'
        );
        appendFileList(lines, localFiles, 'Changed files: none detected locally.');
    } else {
        lines.push('', `No committed or local changes detected for ${diffRange}.`);
    }

    return {
        mode: 'branch',
        baseBranch,
        branch,
        baseSource,
        diffRange: usedLocalFallback ? null : diffRange,
        files: resolvedFiles,
        status: resolvedFiles.length > 0 ? 'ok' : status === 'empty' ? 'empty' : status,
        warning: status === 'missing-ref' || status === 'failed' ? warning : null,
        usedLocalFallback,
        inspectCommand: usedLocalFallback ? 'git status' : `git diff ${diffRange}`,
        scopeText: lines.join('\n')
    };
}

/**
 * Builds scope for --mode=files: reviews local staged + unstaged + untracked files
 * @param git: object - git runner from git.js
 * @returns object - resolved scope for files mode
 */
function buildFilesScope(git) {
    const files = git.getLocalChangedFiles();
    const lines = [
        'Mode: files',
        'File source: git local changes (staged + unstaged + untracked)',
        'Review ONLY the following file paths (not untouched code).',
        'Inspect with: git status'
    ];

    appendFileList(lines, files, 'Changed files: none detected for this scope.');

    return {
        mode: 'files',
        baseBranch: null,
        branch: git.getCurrentBranch(),
        baseSource: null,
        diffRange: null,
        files,
        status: files.length > 0 ? 'ok' : 'empty',
        warning: null,
        usedLocalFallback: false,
        inspectCommand: 'git status',
        scopeText: lines.join('\n')
    };
}

/**
 * Resolves the review scope from config: commits mode takes priority, then
 * falls back to files or branch mode
 * @param config: object - merged ai-review config
 * @param git: object - git runner from git.js
 * @returns object - resolved scope for the run
 */
function buildScope(config, git) {
    if (Array.isArray(config.commits) && config.commits.length > 0) {
        return buildCommitsScope(config, git);
    }
    return config.mode === 'files' ? buildFilesScope(git) : buildBranchScope(config, git);
}

module.exports = { buildScope };
