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
 * True when the binary name is Cursor's agent CLI.
 * @param bin: string - command or absolute path
 * @returns boolean
 */
function isAgentBin(bin) {
    const base = path.basename(bin || '').toLowerCase();
    return base === 'agent' || base.startsWith('agent.') || base.includes('cursor-agent');
}

/**
 * Finds a CLI on PATH, then in ~/.local/bin (Cursor's Mac install location).
 * @param name: string - executable name
 * @returns string - path or name, or empty when missing
 */
function findCli(name) {
    const home = process.env.HOME || process.env.USERPROFILE || '';
    if (home) {
        const localBin = path.join(home, '.local', 'bin', name);
        if (fs.existsSync(localBin)) {
            return localBin;
        }
    }
    try {
        const checker = process.platform === 'win32' ? 'where.exe' : 'which';
        const output = execFileSync(checker, [name], {
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'ignore']
        });
        return output.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || '';
    } catch {
        return '';
    }
}

/**
 * Picks Claude or Cursor agent. Claude wins when both are installed.
 * Set AI_REVIEW_BIN to force one command.
 * @param env: object - process env
 * @param lookup: function - (name) => path or empty
 * @returns {{ bin: string, kind: 'claude' | 'agent' }}
 */
function resolveReviewCommand(env = process.env, lookup = findCli) {
    const forced = String(env.AI_REVIEW_BIN || '').trim();
    if (forced) {
        const resolved = /[\\/]/.test(forced) ? forced : (lookup(forced) || forced);
        return { bin: resolved, kind: isAgentBin(resolved) ? 'agent' : 'claude' };
    }
    const claude = lookup('claude');
    const agent = lookup('agent');
    if (claude) {
        return { bin: claude, kind: 'claude' };
    }
    if (agent) {
        return { bin: agent, kind: 'agent' };
    }
    return { bin: 'claude', kind: 'claude' };
}

/**
 * Returns the review CLI executable.
 * @returns string - binary on PATH or an absolute path
 */
function getClaudeBin() {
    return resolveReviewCommand().bin;
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
 * Builds argv for the selected CLI. Cursor agent does not accept Claude flags.
 * @param kind: string - claude or agent
 * @param prompt: string - reviewer prompt
 * @returns string[] - arguments after the executable
 */
function buildReviewArgs(kind, prompt) {
    if (kind === 'agent') {
        return ['-p', '--mode', 'ask', '--output-format', 'text', '--trust', '--', prompt];
    }
    return buildClaudeArgs(prompt);
}

/**
 * Cursor's Windows launcher re-splits a long prompt, so "--run-tests" inside
 * the instructions becomes a CLI flag. Keep the full text in a file.
 * @param prompt: string - full reviewer prompt
 * @param outputDir: string - review bundle directory
 * @returns string - short prompt safe to pass on the command line
 */
function writeAgentPromptFile(prompt, outputDir) {
    const promptPath = path.join(outputDir, 'ai-review-prompt.txt');
    fs.mkdirSync(outputDir, { recursive: true });
    fs.writeFileSync(promptPath, prompt, 'utf8');
    return `Read every instruction in this file and print only the markdown table: ${promptPath}`;
}

/**
 * Windows installs Cursor as agent.cmd. Node cannot spawn that directly.
 * @param bin: string - resolved executable
 * @param args: string[] - CLI arguments
 * @param platform: string - process.platform
 * @param exists: function - fs.existsSync
 * @returns {{ file: string, args: string[] }}
 */
function commandLaunch(bin, args, platform = process.platform, exists = fs.existsSync) {
    if (platform === 'win32' && /\.cmd$/i.test(bin)) {
        const ps1 = bin.replace(/\.cmd$/i, '.ps1');
        if (exists(ps1)) {
            return {
                file: 'powershell.exe',
                args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1, ...args]
            };
        }
    }
    return { file: bin, args };
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
function runClaude(prompt, outputDir) {
    const timeout = Number(process.env.AI_REVIEW_TIMEOUT_MS) || 900000;
    const command = resolveReviewCommand();
    const cliPrompt = command.kind === 'agent' && outputDir
        ? writeAgentPromptFile(prompt, outputDir)
        : prompt;
    const launch = commandLaunch(command.bin, buildReviewArgs(command.kind, cliPrompt));
    process.stderr.write(`AI review command: ${command.bin} (${command.kind})\n`);
    try {
        return execFileSync(launch.file, launch.args, {
            encoding: 'utf8',
            timeout,
            maxBuffer: 10 * 1024 * 1024,
            windowsHide: true
        });
    } catch (err) {
        const stdout = [err.stdout, err.stderr].filter(Boolean).join('\n');
        if (!stdout.trim()) {
            process.stderr.write(`AI review command failed (${command.bin}): ${err.message}\n`);
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
    const stdout = runClaude(prompt, path.dirname(requestPath));
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
    buildReviewArgs,
    writeAgentPromptFile,
    buildReviewerPrompt,
    extractIdsFromText,
    formatTable,
    getClaudeBin,
    isAgentBin,
    resolveReviewCommand,
    commandLaunch
};
