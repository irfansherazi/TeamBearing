#!/usr/bin/env node
/**
 * Wrapper for Claude CLI — forces structured PASS/FAIL table output for ai-review.js.
 * Reads AI_REVIEW_REQUEST and AI_REVIEW_CONTEXT from env (set by ai-runner.js).
 *
 * Invokes `claude` with an argv array (no shell). `--disallowedTools` is
 * variadic, so the reviewer prompt is passed after `--` and is not treated
 * as extra tool names. Default timeout is 15 minutes.
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { parseAiResultsTable } = require('./ai-runner');

const CLAUDE_DISALLOWED_TOOLS = 'Edit,Write,Bash';

/**
 * Returns the Claude CLI executable name.
 * @returns string - binary on PATH
 */
function getClaudeBin() {
    return 'claude';
}

/**
 * Builds Claude CLI argv. `--` ends option parsing so the prompt cannot be
 * consumed as extra `--disallowedTools` values.
 * @param prompt: string - reviewer prompt
 * @returns string[] - arguments after the executable
 */
function buildClaudeArgs(prompt) {
    return [
        '-p',
        '--permission-mode',
        'plan',
        '--disallowedTools',
        CLAUDE_DISALLOWED_TOOLS,
        '--',
        prompt
    ];
}

/**
 * Fallback extraction of checklist ids from AI output when no context file exists
 * @param text: string - AI CLI output
 * @returns string[] - unique checklist ids found in text
 */
function extractIdsFromText(text) {
    const ids = new Set();
    const re = /\b(CQ|F|D|T|PH|LD)-\d+\b/g;
    for (const match of text.matchAll(re)) {
        ids.add(match[0]);
    }
    return [...ids];
}

/**
 * Formats parsed result rows back into a markdown PASS/FAIL table
 * @param rows: Array<{ id: string, status: string, notes?: string }> - parsed rows
 * @returns string - markdown table text
 */
function formatTable(rows) {
    const lines = [
        '| ID | Result | Notes |',
        '|----|--------|-------|'
    ];
    for (const r of rows) {
        lines.push(`| ${r.id} | ${r.status} | ${(r.notes || '').replace(/\|/g, '\\|')} |`);
    }
    return lines.join('\n');
}

/**
 * Builds the reviewer prompt for the request file and checklist ids
 * @param requestPath: string - absolute path to review-request.md
 * @param aiItemIds: string[] - checklist ids the AI must score
 * @returns string - prompt passed to Claude as one argv value
 */
function buildReviewerPrompt(requestPath, aiItemIds) {
    const idList = aiItemIds.length > 0 ? aiItemIds.join(', ') : 'all checklist IDs in the request file';
    return [
        'You are a code reviewer. Read this file completely:',
        requestPath,
        '',
        'Review ONLY the scoped diffs against the checklist in that file. The file also embeds the FULL text of every',
        'source-of-truth doc (PROMPT_coding_conventions.md, Code-Conventions-Pilot.md, PROMPT_unit_test.md) and the',
        'checklist\'s own worked examples — read all of it, not just the short bullet descriptions.',
        '',
        'Rules:',
        `- Evaluate these IDs: ${idList}`,
        '- Score every ID in the list — do not omit rows. Count your output rows against this ID list before finishing.',
        '- Some IDs show an "Automated pre-check" hint inline in the checklist — that check only covers a narrow slice',
        '  of the rule. Do not copy its verdict; independently judge the full rule text against the diff.',
        '- Lifecycle / timer / async-after-destroy memory leaks: score under CQ-08 only (CQ-18 and T-02 are retired)',
        '- If a rule does not apply: Result PASS with Notes "N/A — not in scope" (do not use SKIP for applicability)',
        '- For PH-01 … PH-04 on local review: PASS with Notes "N/A — verify at PR time"',
        '- For T-01 if tests were not run: PASS with Notes "Tests not executed in this run — require --run-tests before PR"',
        '- Every FAIL must have a clear, specific note (file name + issue)',
        '- Every PASS can use an empty note, brief confirmation, or the N/A note above',
        '- READ ONLY: report findings only — do NOT edit, write, or fix any files',
        '- Suggestions go in the Notes column; the developer fixes code themselves',
        '',
        'Output format — CRITICAL: print ONLY a markdown table, nothing else.',
        'No introduction, no summary paragraph, no bullet list before or after.',
        '',
        '| ID | Result | Notes |',
        '|----|--------|-------|',
        '| CQ-01 | PASS | |',
        '',
        'Use exactly PASS or FAIL in the Result column (prefer PASS+N/A over SKIP). One row per checklist ID.'
    ].join('\n');
}

/**
 * Runs Claude CLI and returns stdout (or combined stdout/stderr on non-zero exit)
 * @param prompt: string - reviewer prompt
 * @returns string - CLI output
 */
function runClaude(prompt) {
    const timeout = Number(process.env.AI_REVIEW_TIMEOUT_MS) || 900000;
    try {
        return execFileSync(getClaudeBin(), buildClaudeArgs(prompt), {
            encoding: 'utf8',
            timeout,
            maxBuffer: 10 * 1024 * 1024,
            windowsHide: true
        });
    } catch (err) {
        const stdout = [err.stdout, err.stderr].filter(Boolean).join('\n');
        if (!stdout.trim()) {
            process.stderr.write(`Claude CLI failed: ${err.message}\n`);
            process.exit(1);
        }
        return stdout;
    }
}

/**
 * Entry: invoke Claude and print a parseable PASS/FAIL table
 * @returns void
 */
function main() {
    const requestPath = process.env.AI_REVIEW_REQUEST;
    const contextPath = process.env.AI_REVIEW_CONTEXT;

    if (!requestPath || !fs.existsSync(requestPath)) {
        process.stderr.write('AI_REVIEW_REQUEST file not found.\n');
        process.exit(1);
    }

    let aiItemIds = [];
    if (contextPath && fs.existsSync(contextPath)) {
        try {
            const ctx = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
            aiItemIds = ctx.aiItemIds ?? [];
        } catch {
            aiItemIds = [];
        }
    }

    const prompt = buildReviewerPrompt(requestPath, aiItemIds);
    const stdout = runClaude(prompt);
    const outputDir = path.dirname(requestPath);
    const rawPath = path.join(outputDir, 'ai-response-raw.txt');
    fs.writeFileSync(rawPath, stdout, 'utf8');

    const parsed = parseAiResultsTable(stdout, aiItemIds.length > 0 ? aiItemIds : extractIdsFromText(stdout));

    if (parsed.length === 0) {
        process.stderr.write(`Could not parse table from Claude output. Raw saved to: ${rawPath}\n`);
        process.stdout.write(stdout);
        process.exit(0);
    }

    process.stdout.write(formatTable(parsed));
}

if (require.main === module) {
    main();
}

module.exports = {
    CLAUDE_DISALLOWED_TOOLS,
    buildClaudeArgs,
    buildReviewerPrompt,
    extractIdsFromText,
    formatTable,
    getClaudeBin
};
