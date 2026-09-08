const { loadConfig } = require('./config');
const { createGitRunner } = require('./git');
const { buildScope } = require('./scope');
const { collectDiffs } = require('./diffs');
const { parseChecklistFile, getAiReviewItems } = require('./checklist');
const { runAutomatedChecks } = require('./automated-checks');
const { writeReviewBundle } = require('./review-bundle');
const { runAiReview } = require('./ai-runner');
const { mergeResults, formatReport, formatScopeOutput } = require('./report');

/**
 * Prints CLI usage help to stdout
 * @returns void
 */
function printHelp() {
    process.stdout.write(`AI Code Review

Terminal (PASS/FAIL report) — run from vReview/:
  npm run ai:review
  npm run ai:review --base=master
  npm run ai:review -- --branch=Syed/VC2-9204 --commits=abc1234,def5678
  npm run ai:review -- --commits=abc1234,def5678 --base=Develop
  npm run ai:review -- --app=vcapi
  npm run ai:review -- --app=vcapi --branch=Some/VC2-xxxx

Chat (scope + bundle for Cursor/Copilot):
  npm run ai:review:scope
  npm run ai:review:scope --mode=files
  npm run ai:review:scope -- --app=vcapi

Flags:
  --scope-only        Scope + review bundle only (for chat agents)
  --mode=branch|files Review mode (default: branch)
  --app=platform|vcapi  Review target (default: platform = vsuitePlatform)
  --base=<branch>     Override base branch (platform default: Develop; vcapi default: develop)
  --branch=<branch>   Target branch (default: current in the selected app repo)
  --commits=a,b,c     Review only these commit SHAs (comma-separated)
  --config=<path>     Custom config file (relative to vReview unless absolute)
  --ai-command=<cmd>  AI CLI for semantic review (or AI_REVIEW_COMMAND env)
  --run-tests         Run unit tests for T-01 (platform: serverTest; vcapi: npm test)
  --help              Show this help

Base branch resolution:
  1. --base= when provided
  2. Branch suffix (*-master, *-rc / *-develop for vcapi)
  3. Team default (Develop for platform; develop for vcapi)

--app=vcapi reviews the sibling ../vcapi git repo using vReview/standards/vcapi.
Default (no --app) reviews sibling ../vsuitePlatform using vReview/standards/platform.

Set AI_REVIEW_COMMAND for full terminal PASS/FAIL on semantic checklist items.
`);
}

/**
 * Writes an error to stderr and exits the process with code 1
 * @param message: string - error message to print
 * @returns void
 */
function exitWithError(message) {
    process.stderr.write(`${message}\n`);
    process.exit(1);
}

/**
 * Entry point: resolves scope, builds the review bundle, runs automated + AI
 * checks, and prints the report (or scope-only output)
 * @returns void
 */
function main() {
    const toolRootDir = process.cwd();
    const { cli, config, rootDir } = loadConfig(toolRootDir, process.argv, exitWithError);

    if (cli.help) {
        printHelp();
        return;
    }

    const git = createGitRunner(rootDir);
    let scope;

    try {
        scope = buildScope(config, git);
    } catch (err) {
        exitWithError(err.message);
    }

    if (scope.status === 'missing-ref' || scope.status === 'failed') {
        process.stderr.write(`${scope.warning}\n`);
        process.exit(1);
    }

    if (scope.files.length === 0) {
        process.stdout.write(`AI Code Review — no changes to review.\n`);
        if (scope.warning) {
            process.stdout.write(`${scope.warning}\n`);
        }
        process.exit(0);
    }

    let checklistItems;
    try {
        checklistItems = parseChecklistFile(config.standardsDir, config.instructionsFile);
    } catch (err) {
        exitWithError(err.message);
    }

    const diffs = collectDiffs(scope, git, config, rootDir);
    const automatedResults = runAutomatedChecks({
        rootDir,
        files: scope.files,
        config,
        perFileDiffs: diffs.perFile
    });
    const bundlePaths = writeReviewBundle({
        rootDir,
        config,
        scope,
        diffs,
        checklistItems,
        automatedResults
    });

    if (config.scopeOnly) {
        process.stdout.write(
            formatScopeOutput({ scope, config, bundlePaths, automatedResults }) + '\n'
        );
        return;
    }

    const aiItems = getAiReviewItems(checklistItems, config.automatedChecks || {}, config.advisoryAutomatedIds || []);
    const aiItemIds = aiItems.map((i) => i.id);
    const aiRun = runAiReview({
        config,
        requestPath: bundlePaths.requestPath,
        contextPath: bundlePaths.contextPath,
        aiItemIds,
        rootDir
    });

    const results = mergeResults(checklistItems, automatedResults, aiRun.results, config, {
        commandNotFound: aiRun.commandNotFound
    }, scope);
    const report = formatReport({
        scope,
        files: scope.files,
        results,
        bundlePaths,
        aiRan: aiRun.ran,
        config,
        commandNotFound: aiRun.commandNotFound,
        parseWarning: aiRun.parseWarning,
        diffTruncated: diffs.truncated,
        diffTotalLines: diffs.totalLines
    });

    process.stdout.write(report.text + '\n');
    process.exit(report.exitCode);
}

module.exports = { main, exitWithError };
