const path = require('path');
const { getAiReviewItems } = require('./checklist');

const PR_HYGIENE_IDS = ['PH-01', 'PH-02', 'PH-03', 'PH-04'];

/**
 * Overrides PR-hygiene results to PASS+N/A for local (uncommitted/commits) review modes,
 * since PR title/ticket/screenshots/SQL can only be verified once a PR actually exists
 * @param results: array - merged checklist results
 * @param scope: object - resolved scope, used to check scope.mode
 * @returns array - results with PH-* overridden when scope.mode is 'files' or 'commits'
 */
function applyLocalReviewOverrides(results, scope) {
    if (scope.mode !== 'files' && scope.mode !== 'commits') {
        return results;
    }

    return results.map((r) => {
        if (PR_HYGIENE_IDS.includes(r.id)) {
            return {
                ...r,
                status: 'PASS',
                notes: 'N/A for local uncommitted review — verify when opening PR'
            };
        }
        return r;
    });
}

/**
 * Combines an advisory automated result with the AI verdict for the same id.
 * Advisory IDs run an automated check AND require an AI verdict — neither side
 * is trusted alone: FAIL from either wins, so a narrow-regex PASS can never
 * silently override a real issue the AI found (or vice versa).
 * @param automatedResult: object - { id, status, notes } from the automated check, or undefined
 * @param aiResult: object - { id, status, notes } from the AI reviewer, or undefined
 * @returns object - combined { id, status, notes }
 */
function combineAdvisoryResult(automatedResult, aiResult) {
    const notesParts = [];
    if (automatedResult?.notes) {
        notesParts.push(`Automated hint (${automatedResult.status}): ${automatedResult.notes}`);
    }
    if (aiResult?.notes) {
        notesParts.push(`AI: ${aiResult.notes}`);
    }
    const status =
        automatedResult?.status === 'FAIL' || aiResult?.status === 'FAIL'
            ? 'FAIL'
            : aiResult?.status || automatedResult?.status || 'SKIP';

    return {
        id: automatedResult?.id || aiResult?.id,
        status,
        notes: notesParts.join(' | ') || ''
    };
}

/**
 * Merges automated-check results, AI results, and T-01/PH-* special cases into
 * one final result per checklist item, in checklist order
 * @param checklistItems: array - all parsed checklist items
 * @param automatedResults: array - results from runAutomatedChecks
 * @param aiResults: array - results from runAiReview
 * @param config: object - merged ai-review config
 * @param aiRunMeta: object - metadata about the AI run, e.g. { commandNotFound }
 * @param scope: object - resolved scope, used for local-review overrides
 * @returns array - one { id, status, notes } row per checklist item
 */
function mergeResults(checklistItems, automatedResults, aiResults, config, aiRunMeta = {}, scope = {}) {
    const automatedMap = new Map(automatedResults.map((r) => [r.id, r]));
    const aiMap = new Map(aiResults.map((r) => [r.id, r]));
    const advisoryIds = new Set(config.advisoryAutomatedIds || []);
    const aiItems = getAiReviewItems(checklistItems, config.automatedChecks || {}, config.advisoryAutomatedIds || []);
    const aiItemIds = new Set(aiItems.map((i) => i.id));
    const hasAiCommand = Boolean(config.aiReviewCommand && String(config.aiReviewCommand).trim());
    const commandNotFound = Boolean(aiRunMeta.commandNotFound);

    const skipNote = commandNotFound
        ? 'AI CLI not found — install agent (see instructions below)'
        : hasAiCommand
          ? 'Pending AI review'
          : 'Requires AI review — set AI_REVIEW_COMMAND or use chat: ai:review';

    const merged = [];

    for (const item of checklistItems) {
        const isAdvisory = advisoryIds.has(item.id) && automatedMap.has(item.id);

        if (automatedMap.has(item.id) && !isAdvisory) {
            merged.push(automatedMap.get(item.id));
            continue;
        }

        if (item.id === 'T-01' && config.runTests && automatedMap.has('T-01')) {
            merged.push(automatedMap.get('T-01'));
            continue;
        }

        if (item.id === 'T-01' && !config.runTests) {
            merged.push({
                id: 'T-01',
                status: 'PASS',
                notes: 'Tests not executed in this run — require --run-tests before PR'
            });
            continue;
        }

        if (isAdvisory) {
            if (aiMap.has(item.id)) {
                merged.push(combineAdvisoryResult(automatedMap.get(item.id), aiMap.get(item.id)));
            } else {
                merged.push(
                    combineAdvisoryResult(automatedMap.get(item.id), {
                        status: 'SKIP',
                        notes: skipNote
                    })
                );
            }
            continue;
        }

        if (aiMap.has(item.id)) {
            merged.push(aiMap.get(item.id));
            continue;
        }

        if (aiItemIds.has(item.id)) {
            merged.push({
                id: item.id,
                status: 'SKIP',
                notes: skipNote
            });
            continue;
        }

        merged.push({ id: item.id, status: 'SKIP', notes: 'Not configured for automated check' });
    }

    return applyLocalReviewOverrides(merged, scope);
}

/**
 * Formats the final terminal report: PASS/FAIL table, summary counts, and next-step guidance
 * @param options: object - { scope, files, results, bundlePaths, aiRan, config, commandNotFound, parseWarning, diffTruncated, diffTotalLines }
 * @returns object - { text, pass, fail, skip, incomplete, exitCode }
 */
function formatReport({
    scope,
    files,
    results,
    bundlePaths,
    aiRan,
    config,
    commandNotFound,
    parseWarning,
    diffTruncated,
    diffTotalLines
}) {
    const lines = [];
    const maxDiffLines = config.maxDiffLines || 8000;
    const incomplete = Boolean(diffTruncated);
    const branchLabel =
        scope.mode === 'branch'
            ? `${scope.branch} vs ${scope.baseBranch}`
            : scope.mode === 'commits'
              ? (() => {
                    const shas = (scope.commits || []).map((sha) => sha.slice(0, 7)).join(', ');
                    let label = `commits ${shas}`;
                    if (scope.branchExplicit) {
                        label += ` on ${scope.branch}`;
                    }
                    if (scope.baseBranch) {
                        label += ` (base: ${scope.baseBranch})`;
                    }
                    return label;
                })()
              : `local changes on ${scope.branch}`;

    lines.push(`AI Code Review — ${branchLabel}`);
    lines.push('REVIEW ONLY — suggestions below. Developer fixes code; this tool does not edit files.');
    lines.push(`Files reviewed (${files.length}): ${files.length ? files.join(', ') : '(none)'}`);

    if (incomplete) {
        const notReviewed = Math.max(0, (diffTotalLines || 0) - maxDiffLines);
        lines.push('');
        lines.push(
            `*** DIFF TRUNCATED: only the first ${maxDiffLines} of ${diffTotalLines} diff lines were sent for review ` +
                `(~${notReviewed} lines NOT reviewed). This run is INCOMPLETE — do not treat it as a clean pass. ` +
                'Re-run scoped to fewer files/commits, or raise maxDiffLines in ai-code-review.config.json. ***'
        );
    }

    const droppedIds = results
        .filter((r) => (r.notes || '').includes('Not evaluated by AI command'))
        .map((r) => r.id);
    if (droppedIds.length > 0) {
        lines.push('');
        lines.push(
            `*** COMPLETENESS FAILURE: the AI reviewer response was missing ${droppedIds.length} required checklist row(s): ${droppedIds.join(', ')}. Forced to FAIL below — do not treat this run as a clean pass. ***`
        );
    }

    lines.push('');
    lines.push('Checklist Results:');
    lines.push('| ID | Result | Notes |');
    lines.push('|----|--------|-------|');

    let pass = 0;
    let fail = 0;
    let skip = 0;
    const critical = [];

    for (const r of results) {
        lines.push(`| ${r.id} | ${r.status} | ${(r.notes || '').replace(/\|/g, '\\|')} |`);
        if (r.status === 'PASS') pass++;
        else if (r.status === 'FAIL') {
            fail++;
            critical.push(r.id);
        } else skip++;
    }

    lines.push('');
    lines.push(`Summary: ${pass} PASS, ${fail} FAIL, ${skip} SKIP`);

    const codeFails = results.filter(
        (r) =>
            r.status === 'FAIL' &&
            !PR_HYGIENE_IDS.includes(r.id) &&
            !(scope.mode === 'files' && PR_HYGIENE_IDS.includes(r.id))
    );

    if (codeFails.length > 0) {
        lines.push('');
        lines.push('Fix these first (code / tests):');
        for (const r of codeFails) {
            lines.push(`  ${r.id}: ${r.notes || '(see table above)'}`);
        }
    }

    if (critical.length) {
        lines.push(`Critical IDs: ${critical.join(', ')}`);
    } else if (fail === 0 && skip === 0) {
        lines.push('ALL checklist items PASS');
    }

    if (fail > 0 && incomplete) {
        lines.push('');
        lines.push(
            `Exit code 1 = checklist has ${fail} failure(s), AND the diff was truncated (incomplete review).`
        );
    } else if (fail > 0) {
        lines.push('');
        lines.push(
            `Exit code 1 = checklist has ${fail} failure(s). The review tool ran successfully.`
        );
    } else if (incomplete) {
        lines.push('');
        lines.push('Exit code 1 = diff was truncated. Review incomplete — not a clean pass despite 0 checklist failures.');
    } else {
        lines.push('');
        lines.push('Exit code 0 = no checklist failures.');
    }

    if (scope.mode === 'files' || scope.mode === 'commits') {
        lines.push('PH-* items: PASS with N/A on local review — verify title/ticket/screenshots/SQL when opening the PR.');
    }
    if (!config.runTests) {
        lines.push('T-01 not executed — re-run with --run-tests before PR.');
    }

    if (bundlePaths) {
        lines.push('');
        lines.push(`Review bundle: ${bundlePaths.requestPath}`);
        lines.push(`Context: ${bundlePaths.contextPath}`);
        lines.push(`AI raw response: ${path.join(path.dirname(bundlePaths.requestPath), 'ai-response-raw.txt')}`);
    }

    if (parseWarning) {
        lines.push('');
        lines.push('Warning: Claude returned prose instead of a table. See .ai-review/ai-response-raw.txt');
        lines.push('Re-run after updating run-claude-review.js or use chat: ai:review:changed');
    } else if (commandNotFound) {
        lines.push('');
        lines.push('AI CLI not installed. The "agent" command is separate from the Cursor IDE.');
        lines.push('');
        lines.push('Install Cursor Agent CLI (Windows PowerShell):');
        lines.push("  irm 'https://cursor.com/install?win32=true' | iex");
        lines.push('');
        lines.push('Then restart the terminal, run: agent login');
        lines.push('Verify: agent --version');
        lines.push('');
        lines.push('Your aiReviewCommand in ai-code-review.config.json is correct — it will work once agent is on PATH.');
        lines.push('Until then, use chat: ai:review:changed for full PASS/FAIL.');
    } else if (!aiRan && !config.scopeOnly) {
        const hasAiCommand = Boolean(config.aiReviewCommand && String(config.aiReviewCommand).trim());
        if (!hasAiCommand && skip > 0) {
            lines.push('');
            lines.push('How to complete skipped items:');
            lines.push('  - Chat: say ai:review:changed (Cursor/Copilot evaluates all checklist IDs)');
            lines.push('  - Terminal: set AI_REVIEW_COMMAND to your AI CLI for full PASS/FAIL here');
            lines.push('  - Tests (T-01): re-run with --run-tests');
            lines.push('');
            lines.push(
                'Note: Terminal fully automates CQ-05…CQ-07, CQ-11, CQ-12, CQ-14, CQ-16, CQ-19, CQ-20, T-05, F-04 (+ T-01 with --run-tests).'
            );
            lines.push(
                'CQ-01…CQ-04, CQ-09, CQ-10 get an automated hint but still require AI judgment (regex only covers a narrow slice of those rules).'
            );
            lines.push(
                'CQ-08/13/15/17, F-06…F-08, T-06 need AI judgment with no automated hint. (CQ-18/T-02 folded into CQ-08.)'
            );
        }
    }

    return {
        text: lines.join('\n'),
        pass,
        fail,
        skip,
        incomplete,
        exitCode: fail > 0 || incomplete ? 1 : 0
    };
}

/**
 * Formats the scope-only output shown to chat agents (SCOPE block + automated pre-check hints)
 * @param options: object - { scope, config, bundlePaths, automatedResults }
 * @returns string - formatted scope output
 */
function formatScopeOutput({ scope, config, bundlePaths, automatedResults }) {
    const lines = [
        'SCOPE:',
        scope.scopeText,
        '',
        `Review rules: ${config.instructionsFile}`,
        `Review bundle: ${bundlePaths.requestPath}`,
        `Context: ${bundlePaths.contextPath}`
    ];

    if (automatedResults.length > 0) {
        lines.push('', 'Automated pre-checks:');
        for (const r of automatedResults) {
            lines.push(`  ${r.id}: ${r.status}${r.notes ? ` — ${r.notes}` : ''}`);
        }
    }

    lines.push('', 'Complete semantic review in chat using the checklist IDs above.');

    return lines.join('\n');
}

module.exports = { mergeResults, formatReport, formatScopeOutput };
