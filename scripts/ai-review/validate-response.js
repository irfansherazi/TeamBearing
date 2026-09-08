#!/usr/bin/env node
/**
 * Chat-mode completeness check: the terminal flow (ai-runner.js) already
 * force-fails any checklist ID the AI CLI dropped from its table. Chat mode
 * (ai:review:scope) has no equivalent — the agent posts its table straight
 * into chat and nothing re-checks it against review-context.json. This gives
 * a mechanical way to catch a dropped row before trusting the review:
 *
 *   1. Save the AI's full reply (the markdown table) into a file, e.g.
 *      .ai-review/chat-response.md
 *   2. Run: npm run ai:review:validate -- --response=.ai-review/chat-response.md
 *      For vcapi: npm run ai:review:validate -- --app=vcapi --response=.ai-review/chat-response.md
 *
 * Exits non-zero if any required ID is missing or FAIL.
 */

const fs = require('fs');
const path = require('path');
const { parseAiResultsTable } = require('./ai-runner');
const { loadConfig } = require('./config');

/**
 * Parses --key=value CLI flags into a plain options object
 * @param argv: array - process.argv
 * @returns object - map of flag name -> value
 */
function parseArgs(argv) {
    const args = {};
    for (const arg of argv.slice(2)) {
        const match = arg.match(/^--([^=]+)=(.*)$/);
        if (match) {
            args[match[1]] = match[2];
        }
    }
    return args;
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
 * Entry point: validates a saved chat-reviewer response against the required
 * checklist ids from review-context.json and prints/exits accordingly
 * @returns void
 */
function main() {
    const toolRootDir = process.cwd();
    const args = parseArgs(process.argv);

    let rootDir = toolRootDir;
    if (args.app || process.env.AI_REVIEW_APP || process.env.npm_config_app) {
        const loaded = loadConfig(toolRootDir, process.argv, exitWithError);
        if (loaded.rootDir) {
            rootDir = loaded.rootDir;
        }
    }

    const outputDir = path.resolve(rootDir, args.outputDir || '.ai-review');
    const contextPath = path.resolve(rootDir, args.context || path.join(outputDir, 'review-context.json'));
    let responsePath;
    if (!args.response) {
        responsePath = path.join(outputDir, 'chat-response.md');
    } else if (path.isAbsolute(args.response)) {
        responsePath = args.response;
    } else {
        responsePath = path.resolve(toolRootDir, args.response);
    }

    if (!fs.existsSync(contextPath)) {
        process.stderr.write(
            `Context file not found: ${contextPath}\nRun npm run ai:review:scope (or ai:review:scope:changed) first.\n` +
                'For vcapi: npm run ai:review:scope -- --app=vcapi\n'
        );
        process.exit(1);
    }

    if (!fs.existsSync(responsePath)) {
        process.stderr.write(
            `Response file not found: ${responsePath}\n` +
                'Paste the AI reviewer\'s full markdown table reply into this file, then re-run:\n' +
                '  npm run ai:review:validate -- --response=<path>\n' +
                '  npm run ai:review:validate -- --app=vcapi --response=<path>\n'
        );
        process.exit(1);
    }

    let context;
    try {
        context = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
    } catch (err) {
        process.stderr.write(`Invalid JSON in ${contextPath}: ${err.message}\n`);
        process.exit(1);
    }

    const expectedIds = context.aiItemIds || [];
    if (expectedIds.length === 0) {
        process.stderr.write(`No aiItemIds found in ${contextPath}.\n`);
        process.exit(1);
    }

    const responseText = fs.readFileSync(responsePath, 'utf8');
    const results = parseAiResultsTable(responseText, expectedIds);

    const missing = results.filter((r) => r.notes === 'Not evaluated by AI command');
    const failing = results.filter((r) => r.status === 'FAIL' && r.notes !== 'Not evaluated by AI command');

    process.stdout.write(`Checked ${expectedIds.length} required checklist IDs against ${responsePath}\n\n`);

    if (missing.length > 0) {
        process.stdout.write(
            `*** COMPLETENESS FAILURE: ${missing.length} required row(s) missing from the response: ${missing
                .map((r) => r.id)
                .join(', ')} ***\n`
        );
    } else {
        process.stdout.write('Completeness OK — every required ID has a row.\n');
    }

    if (failing.length > 0) {
        process.stdout.write(`\nFAIL rows (${failing.length}):\n`);
        for (const r of failing) {
            process.stdout.write(`  ${r.id}: ${r.notes}\n`);
        }
    }

    process.exit(missing.length > 0 || failing.length > 0 ? 1 : 0);
}

main();
