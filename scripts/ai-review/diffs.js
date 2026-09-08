const fs = require('fs');
const path = require('path');

/**
 * Caps a diff string at maxLines so oversized diffs don't blow the AI request budget
 * @param diff: string - full unified diff text
 * @param maxLines: number - maximum number of lines to keep
 * @returns object - { diff, truncated, totalLines }
 */
function truncateDiff(diff, maxLines) {
    const lines = diff.split(/\r?\n/);
    if (lines.length <= maxLines) {
        return { diff, truncated: false, totalLines: lines.length };
    }
    const kept = lines.slice(0, maxLines);
    kept.push(`\n... diff truncated (${lines.length - maxLines} more lines) ...`);
    return { diff: kept.join('\n'), truncated: true, totalLines: lines.length };
}

/**
 * Builds the unified diff and per-file diff map for the resolved review scope
 * @param scope: object - resolved scope (mode, files, diffRange/commits, etc.) from scope.js
 * @param git: object - git runner from git.js
 * @param config: object - merged ai-review config
 * @param rootDir: string - repo root, used to read new/untracked file content
 * @returns object - { unified, perFile, truncated, totalLines }
 */
function collectDiffs(scope, git, config, rootDir) {
    const { files } = scope;

    if (scope.mode === 'commits') {
        const unified = git.getDiffForCommits(scope.commits, scope.baseBranchForFallback);
        const { diff, truncated, totalLines } = truncateDiff(unified, config.maxDiffLines || 8000);

        const perFile = {};
        for (const file of files) {
            const parts = [];
            for (const sha of scope.commits) {
                const fileDiff = git.getDiffForCommitFile(sha, file, scope.baseBranchForFallback);
                if (fileDiff) {
                    parts.push(fileDiff);
                }
            }
            perFile[file] = parts.join('\n');
        }

        return { unified: diff, perFile, truncated, totalLines };
    }

    const { diffRange } = scope;
    const unified = git.getDiffForRange(diffRange, files);

    // `git diff` never reports untracked files, so a brand-new/untracked file
    // in scope would otherwise be listed under "Changed Files" but have no
    // content anywhere in the bundle. Collect its full content here and fold
    // it into the same unified diff that gets embedded in review-request.md.
    const perFile = {};
    const untrackedBlocks = [];
    for (const file of files) {
        let fileDiff = '';
        if (diffRange) {
            fileDiff = git.runGit(`diff ${diffRange} -- "${file}"`, { required: false }) || '';
        } else {
            const staged = git.runGit(`diff --cached -- "${file}"`, { required: false }) || '';
            const unstaged = git.runGit(`diff -- "${file}"`, { required: false }) || '';
            fileDiff = [staged, unstaged].filter(Boolean).join('\n');
            if (!fileDiff && fs.existsSync(path.join(rootDir, file))) {
                const content = fs.readFileSync(path.join(rootDir, file), 'utf8');
                fileDiff = `(new/untracked file, ${content.split(/\r?\n/).length} lines)\n${content}`;
                untrackedBlocks.push(`--- ${file} (new/untracked file — not shown by \`git diff\`) ---\n${content}`);
            }
        }
        perFile[file] = fileDiff;
    }

    const combinedUnified = untrackedBlocks.length
        ? [unified, ...untrackedBlocks].filter(Boolean).join('\n\n')
        : unified;

    const { diff, truncated, totalLines } = truncateDiff(combinedUnified, config.maxDiffLines || 8000);

    return { unified: diff, perFile, truncated, totalLines };
}

module.exports = { collectDiffs, truncateDiff };
