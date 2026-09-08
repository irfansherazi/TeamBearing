const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

/**
 * Normalizes one raw output line into a plain markdown table row for matching
 * @param line: string - raw line from AI CLI stdout
 * @returns string - normalized `| a | b | c |` line
 */
function normalizeTableLine(line) {
    return line
        .replace(/\*\*([A-Z]+-\d+)\*\*/g, '$1')
        .replace(/^\|\s*/, '| ')
        .trim();
}

/**
 * Parses a markdown PASS/FAIL table out of AI CLI stdout and force-fails any expected id it dropped
 * @param stdout: string - raw AI CLI output, expected to contain a `| ID | Result | Notes |` table
 * @param expectedIds: array - checklist ids the AI was asked to score
 * @returns array - one { id, status, notes } row per expected id, in expectedIds order
 */
function parseAiResultsTable(stdout, expectedIds) {
    const results = new Map();
    const lines = stdout.split(/\r?\n/);

    for (const rawLine of lines) {
        const line = normalizeTableLine(rawLine);

        if (/^\|\s*[-:| ]+\|\s*$/.test(line)) {
            continue;
        }

        const match = line.match(
            /^\|\s*([A-Z]+-\d+)\s*\|\s*(PASS|FAIL|SKIP|Result|Status)\s*\|\s*(.*?)\s*\|?\s*$/i
        );

        if (!match) {
            const alt = line.match(/^\|\s*([A-Z]+-\d+)\s*\|\s*(PASS|FAIL|SKIP)\s*\|\s*(.*?)\s*\|?\s*$/i);
            if (alt) {
                results.set(alt[1].toUpperCase(), {
                    id: alt[1].toUpperCase(),
                    status: alt[2].toUpperCase(),
                    notes: alt[3].trim()
                });
            }
            continue;
        }

        const id = match[1].toUpperCase();
        let status = match[2].toUpperCase();
        const notes = match[3].trim();

        if (status === 'RESULT' || status === 'STATUS') {
            continue;
        }

        results.set(id, { id, status, notes });
    }

    const merged = [];
    for (const id of expectedIds) {
        if (results.has(id)) {
            merged.push(results.get(id));
        } else {
            merged.push({ id, status: 'FAIL', notes: 'Not evaluated by AI command' });
        }
    }

    return merged;
}

/**
 * Detects whether an execSync failure was caused by a missing AI CLI binary
 * @param err: object - error thrown by execSync
 * @param combined: string - combined stdout+stderr text captured from the failed command
 * @returns boolean - true when the failure looks like "command not found"
 */
function isCommandNotFoundError(err, combined) {
    const text = `${combined || ''} ${err?.message || ''}`;
    return /not recognized|ENOENT|command not found|No such file or directory/i.test(text);
}

/**
 * Reads the current mtime of ai-response-raw.txt, if it exists
 * @param outputDir: string - directory containing ai-response-raw.txt
 * @returns number - mtime in ms, or undefined when the file does not exist
 */
function getRawResponseMtime(outputDir) {
    try {
        return fs.statSync(path.join(outputDir, 'ai-response-raw.txt')).mtimeMs;
    } catch {
        return undefined;
    }
}

/**
 * Persists raw AI CLI output to ai-response-raw.txt, unless aiReviewCommand already wrote
 * its own (truer) copy of that file since beforeMtime was captured
 * @param outputDir: string - directory to write ai-response-raw.txt into
 * @param stdout: string - raw AI CLI output to persist
 * @param beforeMtime: number - mtime captured before the AI command ran, from getRawResponseMtime
 * @returns void
 */
function saveRawAiResponse(outputDir, stdout, beforeMtime) {
    if (!outputDir || !stdout) {
        return;
    }
    const rawPath = path.join(outputDir, 'ai-response-raw.txt');
    if (getRawResponseMtime(outputDir) !== beforeMtime) {
        return;
    }
    try {
        fs.mkdirSync(outputDir, { recursive: true });
        fs.writeFileSync(rawPath, stdout, 'utf8');
    } catch {
        // ignore
    }
}

/**
 * Runs the configured AI review command against the prepared bundle and parses its verdict
 * @param options: object - { config, requestPath, contextPath, aiItemIds, rootDir }
 * @returns object - { ran, results, error, commandNotFound, parseWarning? }
 */
function runAiReview({ config, requestPath, contextPath, aiItemIds, rootDir }) {
    const command = config.aiReviewCommand;
    if (!command || !String(command).trim()) {
        return { ran: false, results: [], error: null, commandNotFound: false };
    }

    const outputDir = path.dirname(requestPath);
    const env = {
        ...process.env,
        AI_REVIEW_REQUEST: requestPath,
        AI_REVIEW_CONTEXT: contextPath,
        AI_REVIEW_TIMEOUT_MS: String(config.aiReviewTimeoutMs || 900000)
    };
    const beforeMtime = getRawResponseMtime(outputDir);

    try {
        // AI CLI wrapper scripts live under the tool root (vsuitePlatform), even when
        // reviewing the sibling vcapi repo. Request/context paths in env are absolute.
        const commandCwd = config.toolRootDir || rootDir;
        const stdout = execSync(command, {
            cwd: commandCwd,
            encoding: 'utf8',
            env,
            timeout: config.aiReviewTimeoutMs || 900000,
            stdio: ['ignore', 'pipe', 'pipe'],
            shell: true,
            maxBuffer: 10 * 1024 * 1024
        });

        saveRawAiResponse(outputDir, stdout, beforeMtime);
        const results = parseAiResultsTable(stdout, aiItemIds);
        const parsedCount = results.filter((r) => r.notes !== 'Not evaluated by AI command').length;

        if (parsedCount === 0 && stdout.trim()) {
            return {
                ran: true,
                results,
                error: 'AI returned output but no parseable table rows. See .ai-review/ai-response-raw.txt',
                stdout,
                commandNotFound: false,
                parseWarning: true
            };
        }

        return { ran: true, results, error: null, stdout, commandNotFound: false };
    } catch (err) {
        const stdout = err.stdout ? err.stdout.toString() : '';
        const stderr = err.stderr ? err.stderr.toString() : '';
        const combined = [stdout, stderr].filter(Boolean).join('\n');
        saveRawAiResponse(outputDir, combined, beforeMtime);

        if (isCommandNotFoundError(err, combined)) {
            return {
                ran: false,
                results: [],
                error: combined.trim() || err.message,
                commandNotFound: true
            };
        }

        const partial = parseAiResultsTable(combined, aiItemIds);

        if (partial.some((r) => r.status !== 'FAIL' || r.notes !== 'Not evaluated by AI command')) {
            return { ran: true, results: partial, error: err.message, stdout: combined, commandNotFound: false };
        }

        return {
            ran: true,
            results: aiItemIds.map((id) => ({
                id,
                status: 'FAIL',
                notes: `AI command failed: ${err.message}`
            })),
            error: err.message,
            stdout: combined,
            commandNotFound: false
        };
    }
}

module.exports = { runAiReview, parseAiResultsTable, isCommandNotFoundError };
