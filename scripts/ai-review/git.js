const { execSync } = require('child_process');

/**
 * Normalizes a file path to forward slashes so it matches git's own output on any OS
 * @param filePath: string - path to normalize
 * @returns string - path with backslashes converted to forward slashes
 */
function normalizeRepoPath(filePath) {
    return String(filePath).replace(/\\/g, '/');
}

/**
 * Builds a read-only git helper bound to a repo root
 * @param rootDir: string - repo root to run git commands in
 * @returns object - git runner with diff/scope/commit helper methods
 */
function createGitRunner(rootDir) {
    /**
     * Runs a git command and returns trimmed stdout
     * @param args: string - git subcommand and arguments (without the leading "git ")
     * @param options: object - { required } - when required is false, failures return null instead of throwing
     * @returns string - trimmed stdout, or null on failure when not required
     */
    function runGit(args, { required = true } = {}) {
        try {
            return execSync(`git ${args}`, {
                cwd: rootDir,
                encoding: 'utf8',
                stdio: ['ignore', 'pipe', 'pipe']
            }).trim();
        } catch (err) {
            if (!required) {
                return null;
            }
            const stderr = err.stderr ? err.stderr.toString().trim() : err.message;
            throw new Error(`Git command failed (git ${args}): ${stderr}`);
        }
    }

    /**
     * Splits raw git output into normalized, non-empty lines
     * @param output: string - raw git command output
     * @returns array - normalized, non-empty lines
     */
    function splitGitLines(output) {
        if (!output) {
            return [];
        }
        return output.split(/\r?\n/).filter(Boolean).map(normalizeRepoPath);
    }

    /**
     * De-duplicates and normalizes a list of file paths
     * @param files: array - file paths, possibly with duplicates or mixed separators
     * @returns array - unique, normalized file paths
     */
    function uniqueFiles(files) {
        return [...new Set(files.map(normalizeRepoPath))];
    }

    /**
     * Checks whether a git ref (branch, sha, etc.) exists locally
     * @param ref: string - git ref to check
     * @returns boolean - true when the ref resolves
     */
    function gitRefExists(ref) {
        return runGit(`rev-parse --verify ${ref}`, { required: false }) !== null;
    }

    /**
     * Lists all locally changed files: staged, unstaged, and untracked
     * @returns array - unique, normalized file paths
     */
    function getLocalChangedFiles() {
        const staged = splitGitLines(runGit('diff --cached --name-only', { required: false }));
        const unstaged = splitGitLines(runGit('diff --name-only', { required: false }));
        const untracked = splitGitLines(runGit('ls-files --others --exclude-standard', { required: false }));
        return uniqueFiles([...staged, ...unstaged, ...untracked]);
    }

    /**
     * Splits a "base...branch" diff range into its two ref parts
     * @param diffRange: string - diff range, expected as "base...branch"
     * @returns object - { base, branch }, or null when the range is not well-formed
     */
    function parseTripleDotRange(diffRange) {
        const parts = String(diffRange).split('...');
        if (parts.length !== 2 || !parts[0] || !parts[1]) {
            return null;
        }
        return { base: parts[0], branch: parts[1] };
    }

    /**
     * Lists files changed in a branch diff range, validating both refs exist first
     * @param diffRange: string - diff range, e.g. "Develop...Syed/TD-260"
     * @returns object - { files, status, warning }
     */
    function listBranchChangedFiles(diffRange) {
        const range = parseTripleDotRange(diffRange);

        if (range) {
            const missingRefs = [range.base, range.branch].filter((ref) => !gitRefExists(ref));
            if (missingRefs.length > 0) {
                return {
                    files: [],
                    status: 'missing-ref',
                    warning: `Missing local ref(s): ${missingRefs.join(', ')}. Try: git fetch`
                };
            }
        }

        const output = runGit(`diff --name-only ${diffRange}`, { required: false });
        if (output === null) {
            return { files: [], status: 'failed', warning: 'Git diff failed.' };
        }

        const files = splitGitLines(output);
        return files.length > 0
            ? { files, status: 'ok', warning: null }
            : { files: [], status: 'empty', warning: null };
    }

    /**
     * Gets the unified diff for a set of files, either across a range or from local changes
     * @param diffRange: string - diff range, or falsy to diff local staged+unstaged changes
     * @param files: array - file paths to scope the diff to
     * @returns string - unified diff text
     */
    function getDiffForRange(diffRange, files) {
        if (!files.length) {
            return '';
        }
        const fileArgs = files.map((f) => `"${f}"`).join(' ');
        if (diffRange) {
            return runGit(`diff ${diffRange} -- ${fileArgs}`, { required: false }) || '';
        }
        const staged = runGit(`diff --cached -- ${fileArgs}`, { required: false }) || '';
        const unstaged = runGit(`diff -- ${fileArgs}`, { required: false }) || '';
        return [staged, unstaged].filter(Boolean).join('\n');
    }

    /**
     * Gets the current checked-out branch name
     * @returns string - current branch name
     */
    function getCurrentBranch() {
        return runGit('rev-parse --abbrev-ref HEAD');
    }

    /**
     * Resolves and validates a list of refs into full commit SHAs
     * @param refs: array - commit refs (full or short SHAs)
     * @returns array - resolved full commit SHAs
     */
    function resolveCommitShas(refs) {
        const resolved = [];
        for (const ref of refs) {
            const sha = runGit(`rev-parse --verify ${ref}`, { required: false });
            if (!sha) {
                throw new Error(`Invalid commit ref: ${ref}. Use a full or short SHA that exists locally (try git fetch).`);
            }
            const objectType = runGit(`cat-file -t ${sha}`, { required: false });
            if (objectType !== 'commit') {
                throw new Error(`Ref ${ref} is not a commit (found ${objectType || 'unknown'}).`);
            }
            resolved.push(sha);
        }
        return resolved;
    }

    /**
     * Checks whether a commit is an ancestor of (reachable from) a branch ref
     * @param commitSha: string - commit SHA to check
     * @param branchRef: string - branch ref that should contain the commit
     * @returns boolean - true when commitSha is reachable from branchRef
     */
    function isReachableFrom(commitSha, branchRef) {
        if (!gitRefExists(branchRef) || !gitRefExists(commitSha)) {
            return false;
        }
        try {
            execSync(`git merge-base --is-ancestor ${commitSha} ${branchRef}`, {
                cwd: rootDir,
                stdio: 'ignore'
            });
            return true;
        } catch {
            return false;
        }
    }

    /**
     * Lists the union of files touched across a set of commits
     * @param commitShas: array - commit SHAs to inspect
     * @returns array - unique, normalized file paths
     */
    function listFilesForCommits(commitShas) {
        const all = [];
        for (const sha of commitShas) {
            const output = runGit(`diff-tree --no-commit-id --name-only -r ${sha}`, { required: false });
            if (output) {
                all.push(...splitGitLines(output));
            }
        }
        return uniqueFiles(all);
    }

    /**
     * Gets the full patch for a single commit, with fallbacks for root commits
     * @param sha: string - commit SHA
     * @param baseBranchForFallback: string - base branch to diff against if the commit has no parent
     * @returns string - unified patch text
     */
    function getCommitPatch(sha, baseBranchForFallback) {
        let patch = runGit(`show ${sha} --format= --patch --no-color`, { required: false });
        if (patch) {
            return patch;
        }

        patch = runGit(`diff ${sha}^..${sha} --no-color`, { required: false });
        if (patch) {
            return patch;
        }

        if (baseBranchForFallback && gitRefExists(baseBranchForFallback)) {
            patch = runGit(`diff ${baseBranchForFallback}...${sha} --no-color`, { required: false });
            if (patch) {
                return patch;
            }
        }

        return runGit(`show ${sha} --format= --patch --no-color`, { required: false }) || '';
    }

    /**
     * Gets the patch for a single file within a single commit, with root-commit fallbacks
     * @param sha: string - commit SHA
     * @param file: string - file path to scope the patch to
     * @param baseBranchForFallback: string - base branch to diff against if the commit has no parent
     * @returns string - unified patch text for that file, or '' when none
     */
    function getDiffForCommitFile(sha, file, baseBranchForFallback) {
        let patch = runGit(`show ${sha} --format= --patch --no-color -- "${file}"`, { required: false });
        if (patch) {
            return patch;
        }

        patch = runGit(`diff ${sha}^..${sha} --no-color -- "${file}"`, { required: false });
        if (patch) {
            return patch;
        }

        if (baseBranchForFallback && gitRefExists(baseBranchForFallback)) {
            patch = runGit(`diff ${baseBranchForFallback}...${sha} --no-color -- "${file}"`, { required: false });
            if (patch) {
                return patch;
            }
        }

        return '';
    }

    /**
     * Builds the combined unified diff across a list of commits, each labeled by short SHA
     * @param commitShas: array - commit SHAs to include
     * @param baseBranchForFallback: string - base branch to diff against for root commits
     * @returns string - combined unified diff text
     */
    function getDiffForCommits(commitShas, baseBranchForFallback) {
        if (!commitShas.length) {
            return '';
        }

        return commitShas
            .map((sha) => {
                const patch = getCommitPatch(sha, baseBranchForFallback);
                if (!patch) {
                    return '';
                }
                return `# Commit ${sha.slice(0, 7)}\n${patch}`;
            })
            .filter(Boolean)
            .join('\n\n');
    }

    return {
        runGit,
        normalizeRepoPath,
        getLocalChangedFiles,
        listBranchChangedFiles,
        getDiffForRange,
        getCurrentBranch,
        gitRefExists,
        resolveCommitShas,
        isReachableFrom,
        listFilesForCommits,
        getCommitPatch,
        getDiffForCommitFile,
        getDiffForCommits
    };
}

module.exports = { createGitRunner, normalizeRepoPath };
