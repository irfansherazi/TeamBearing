const fs = require('fs');
const path = require('path');
const {
    DEFAULT_CONFIG,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_BASE_BRANCH,
    VALID_MODES,
    DEFAULT_BRANCH_NAME_RULES,
    DEFAULT_AUTOMATED_CHECKS,
    DEFAULT_ADVISORY_AUTOMATED_IDS,
    DEFAULT_SOURCE_OF_TRUTH_DOCS
} = require('./constants');

/**
 * Resolves a path relative to the repo root
 * @param rootDir: string - repo root
 * @param relativePath: string - path relative to rootDir
 * @returns string - absolute path
 */
function resolveFromRoot(rootDir, relativePath) {
    return path.resolve(rootDir, relativePath);
}

/**
 * Normalizes an --app value to a known review target
 * @param raw: string - raw app name from CLI/env/config
 * @returns string - 'platform' or 'vcapi'
 */
function normalizeApp(raw) {
    const value = String(raw || '')
        .trim()
        .toLowerCase();
    if (!value || value === 'platform' || value === 'vsuite' || value === 'vsuiteplatform') {
        return 'platform';
    }
    if (value === 'vcapi') {
        return 'vcapi';
    }
    return '';
}

/**
 * Returns true when dir is a git checkout
 * @param dir: string - absolute path to test
 * @returns True when .git exists
 */
function looksLikeGitRoot(dir) {
    return fs.existsSync(path.join(dir, '.git'));
}

/**
 * Returns true when dir looks like the vcapi repo root
 * @param dir: string - absolute path to test
 * @returns True when package.json and AGENTS.md exist
 */
function looksLikeVcapiRoot(dir) {
    return (
        fs.existsSync(path.join(dir, 'package.json')) &&
        fs.existsSync(path.join(dir, 'AGENTS.md'))
    );
}

/**
 * Returns true when dir looks like the vsuitePlatform repo root
 * @param dir: string - absolute path to test
 * @returns True when angular.json exists
 */
function looksLikePlatformRoot(dir) {
    return fs.existsSync(path.join(dir, 'angular.json'));
}

/**
 * Returns the vReview standards folder for an app
 * @param toolRootDir: string - vReview root (where npm run ai:review is invoked)
 * @param app: string - 'platform' or 'vcapi'
 * @returns string - absolute standards directory
 */
function resolveStandardsDir(toolRootDir, app) {
    return path.join(toolRootDir, 'standards', app);
}

/**
 * Resolves which git/repo root the review should run against
 * @param toolRootDir: string - vReview root
 * @param app: string - 'platform' or 'vcapi'
 * @param exitWithError: function - called (and never returns) on failure
 * @returns string - absolute review root (sibling checkout)
 */
function resolveReviewRoot(toolRootDir, app, exitWithError) {
    const parent = path.resolve(toolRootDir, '..');
    if (app === 'platform') {
        const sibling = path.join(parent, 'vsuitePlatform');
        if (looksLikePlatformRoot(sibling) || looksLikeGitRoot(sibling)) {
            return sibling;
        }
        exitWithError(
            `Could not find vsuitePlatform at ${sibling}. Keep it as a sibling of vReview.`
        );
    }

    const sibling = path.join(parent, 'vcapi');
    if (looksLikeVcapiRoot(sibling) || looksLikeGitRoot(sibling)) {
        return sibling;
    }
    exitWithError(`Could not find vcapi at ${sibling}. Keep it as a sibling of vReview.`);
}

/**
 * Parses process.argv into a partial config object
 * @param argv: array - process.argv
 * @returns object - cli overrides (mode, baseBranch, branch, commits, configPath, aiReviewCommand, etc.)
 */
function parseCliArgs(argv) {
    const cli = {};

    for (const arg of argv.slice(2)) {
        if (arg === '--help' || arg === '-h') {
            cli.help = true;
            continue;
        }
        if (arg === '--scope-only') {
            cli.scopeOnly = true;
            continue;
        }
        if (arg === '--run-tests') {
            cli.runTests = true;
            continue;
        }
        // PowerShell npm.ps1 sometimes strips "--app=" and leaves a bare token ("vcapi").
        if (arg === 'vcapi' || arg === 'platform' || arg === 'vsuite' || arg === 'vsuitePlatform') {
            cli.app = arg;
            continue;
        }

        const match = arg.match(/^--([^=]+)=(.*)$/);
        if (!match) {
            continue;
        }

        const [, key, value] = match;
        if (key === 'mode') {
            cli.mode = value;
        } else if (key === 'base' || key === 'baseBranch') {
            cli.baseBranch = value;
            cli.baseBranchExplicit = true;
        } else if (key === 'branch') {
            cli.branch = value;
        } else if (key === 'commits') {
            cli.commits = value
                .split(',')
                .map((part) => part.trim())
                .filter(Boolean);
        } else if (key === 'config') {
            cli.configPath = value;
        } else if (key === 'ai-command') {
            cli.aiReviewCommand = value;
        } else if (key === 'app') {
            cli.app = value;
        }
    }

    return cli;
}

/**
 * Parses AI_REVIEW_* / npm_config_* environment variables into a partial config object
 * @returns object - env overrides (baseBranch, branch, commits, aiReviewCommand, app)
 */
function parseEnvOverrides() {
    const overrides = {};
    const {
        AI_REVIEW_BASE,
        AI_REVIEW_BRANCH,
        AI_REVIEW_COMMITS,
        AI_REVIEW_COMMAND,
        AI_REVIEW_APP,
        npm_config_base,
        npm_config_branch,
        npm_config_commits,
        npm_config_app
    } = process.env;

    if (AI_REVIEW_BASE) {
        overrides.baseBranch = AI_REVIEW_BASE;
        overrides.baseBranchExplicit = true;
    }
    if (npm_config_base) {
        overrides.baseBranch = npm_config_base;
        overrides.baseBranchExplicit = true;
    }
    if (AI_REVIEW_BRANCH) {
        overrides.branch = AI_REVIEW_BRANCH;
    }
    if (npm_config_branch) {
        overrides.branch = npm_config_branch;
    }
    if (AI_REVIEW_COMMITS) {
        overrides.commits = AI_REVIEW_COMMITS.split(',')
            .map((part) => part.trim())
            .filter(Boolean);
    }
    if (npm_config_commits) {
        overrides.commits = npm_config_commits.split(',')
            .map((part) => part.trim())
            .filter(Boolean);
    }
    if (AI_REVIEW_COMMAND) {
        overrides.aiReviewCommand = AI_REVIEW_COMMAND;
    }
    if (AI_REVIEW_APP) {
        overrides.app = AI_REVIEW_APP;
    }
    if (npm_config_app) {
        overrides.app = npm_config_app;
    }

    return overrides;
}

/**
 * Resolves which config file to load, preferring --config over the app default
 * @param toolRootDir: string - directory where the AI review tool was invoked
 * @param reviewRootDir: string - repo being reviewed
 * @param argv: array - process.argv
 * @param cli: object - parsed cli args from parseCliArgs
 * @returns string - absolute path to the config file to read
 */
function resolveConfigPath(toolRootDir, reviewRootDir, argv, cli, app) {
    if (cli.configPath) {
        return resolveFromRoot(toolRootDir, cli.configPath);
    }
    const configArg = argv.find((arg) => arg.startsWith('--config='));
    if (configArg) {
        return resolveFromRoot(toolRootDir, configArg.slice('--config='.length));
    }
    const standardsConfig = path.join(resolveStandardsDir(toolRootDir, app), DEFAULT_CONFIG);
    if (fs.existsSync(standardsConfig)) {
        return standardsConfig;
    }
    return resolveFromRoot(toolRootDir, DEFAULT_CONFIG);
}

/**
 * Reads and parses the JSON config file, if present
 * @param configPath: string - absolute path to the config file
 * @param exitWithError: function - called (and never returns) on invalid JSON
 * @returns object - parsed config, or {} when the file does not exist
 */
function readConfigFile(configPath, exitWithError) {
    if (!fs.existsSync(configPath)) {
        return {};
    }

    try {
        return JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (err) {
        exitWithError(`Invalid JSON in config: ${err.message}`);
    }
}

/**
 * Merges defaults, file config, env overrides, and cli overrides (in increasing precedence) and validates the result
 * @param fileConfig: object - parsed ai-code-review.config.json
 * @param envConfig: object - overrides from parseEnvOverrides
 * @param cliConfig: object - overrides from parseCliArgs
 * @param exitWithError: function - called (and never returns) when validation fails
 * @returns object - final merged config
 */
function mergeConfig(fileConfig, envConfig, cliConfig, exitWithError) {
    const config = {
        mode: 'branch',
        branch: '',
        commits: [],
        baseBranch: DEFAULT_BASE_BRANCH,
        branchNameRules: DEFAULT_BRANCH_NAME_RULES,
        instructionsFile: DEFAULT_INSTRUCTIONS,
        automatedChecks: DEFAULT_AUTOMATED_CHECKS,
        advisoryAutomatedIds: DEFAULT_ADVISORY_AUTOMATED_IDS,
        sourceOfTruthDocs: DEFAULT_SOURCE_OF_TRUTH_DOCS,
        aiReviewCommand: '',
        aiReviewTimeoutMs: 900000,
        maxDiffLines: 8000,
        outputDir: '.ai-review',
        scopeOnly: false,
        runTests: false,
        ...fileConfig,
        ...envConfig,
        ...cliConfig
    };

    if (!VALID_MODES.includes(config.mode)) {
        exitWithError(`"mode" must be one of: ${VALID_MODES.join(', ')}`);
    }

    if (config.commits?.length && config.mode === 'files') {
        exitWithError('"--commits" cannot be used with --mode=files. Use npm run ai:review instead of ai:review:changed.');
    }

    return config;
}

/**
 * Loads and merges the full ai-review configuration for this run
 * @param toolRootDir: string - directory where npm run ai:review was invoked
 * @param argv: array - process.argv
 * @param exitWithError: function - called (and never returns) on invalid config
 * @returns object - { cli, config, rootDir } — config/rootDir null when --help was passed
 */
function loadConfig(toolRootDir, argv, exitWithError) {
    const cli = parseCliArgs(argv);
    if (cli.help) {
        return { cli, config: null, rootDir: null };
    }

    const envConfig = parseEnvOverrides();
    const rawApp = cli.app || envConfig.app || 'platform';
    const app = normalizeApp(rawApp);
    if (!app) {
        exitWithError(`Unknown --app=${rawApp}. Use platform (default) or vcapi.`);
    }

    const rootDir = resolveReviewRoot(toolRootDir, app, exitWithError);
    const standardsDir = resolveStandardsDir(toolRootDir, app);
    const config = mergeConfig(
        readConfigFile(resolveConfigPath(toolRootDir, rootDir, argv, cli, app), exitWithError),
        envConfig,
        { ...cli, app },
        exitWithError
    );

    config.app = app;
    config.toolRootDir = toolRootDir;
    config.standardsDir = standardsDir;

    const checklistPath = path.join(standardsDir, config.instructionsFile || DEFAULT_INSTRUCTIONS);
    if (!fs.existsSync(checklistPath)) {
        exitWithError(`Checklist not found at ${checklistPath}`);
    }

    return { cli, config, rootDir };
}

module.exports = {
    loadConfig,
    parseCliArgs,
    resolveFromRoot,
    normalizeApp,
    resolveReviewRoot,
    resolveStandardsDir,
    looksLikeVcapiRoot,
    looksLikePlatformRoot
};
