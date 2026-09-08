const fs = require('fs');
const path = require('path');
const { getAiReviewItems } = require('./checklist');

/**
 * Builds the instructions telling the AI reviewer exactly which table rows to return
 * @param aiItems: array - checklist items requiring an AI verdict
 * @returns string - markdown instructions + empty response table template
 */
function buildResponseTemplate(aiItems) {
    const rows = aiItems.map((item) => `| ${item.id} | PASS or FAIL | notes |`);
    return [
        `Respond with ONLY a markdown table in this exact format — all ${aiItems.length} rows are required, in this exact order:`,
        '',
        '| ID | Result | Notes |',
        '|----|--------|-------|',
        ...rows,
        '',
        `Evaluate every ID listed (${aiItems.length} total). Use PASS or FAIL only. Before answering, count your rows against this list — a dropped row is treated as a failed review run, not a skip.`
    ].join('\n');
}

/**
 * Reads a doc's full text if it exists, without throwing
 * @param rootDir: string - repo root
 * @param relativePath: string - doc path relative to rootDir
 * @returns string - file contents, or null when missing/unreadable
 */
function readDocIfExists(rootDir, relativePath) {
    try {
        const fullPath = path.resolve(rootDir, relativePath);
        if (!fs.existsSync(fullPath)) {
            return null;
        }
        return fs.readFileSync(fullPath, 'utf8');
    } catch (_e) {
        return null;
    }
}

/**
 * Embeds the full text of every source-of-truth doc (not just the checklist's
 * one-line ID descriptions). Generic-sounding IDs like D-01 ("properly
 * commented") are proxies for specific rules — e.g. "Use JSDoc comments for
 * all methods" — that only live in these files. A reviewer working from the
 * short descriptions alone will miss them (see: JSDoc miss on ArrayLineBreakPipe
 * / NewAccountsComponent, VC2-9233).
 * @param rootDir: string - repo root
 * @param sourceOfTruthDocs: array - doc paths named as strict source of truth
 * @returns string - markdown section embedding the full text of each doc, or '' if none found
 */
function buildSourceOfTruthSection(rootDir, sourceOfTruthDocs) {
    const sections = [];

    for (const doc of sourceOfTruthDocs || []) {
        const raw = readDocIfExists(rootDir, doc);
        if (!raw) {
            continue;
        }
        sections.push(`### ${doc}`, '```markdown', raw.trim(), '```');
    }

    if (sections.length === 0) {
        return '';
    }

    return [
        '## Source-of-Truth Conventions (full text — read every file below, not just the checklist bullet summary)',
        '',
        'These are named as strict source of truth by the checklist file itself. Rules here (e.g. JSDoc on every method,',
        'no `async/await` in frontend code, no `hasOwnProperty()`, code reuse) are enforced under the checklist IDs above',
        '(mainly D-01, D-02, CQ-01) even when the short bullet text does not spell them out.',
        '',
        ...sections
    ].join('\n');
}

/**
 * Builds the inline "Automated pre-check" hint appended to an advisory checklist item
 * @param item: object - checklist item { id, section, text }
 * @param automatedResults: array - results from runAutomatedChecks
 * @param advisoryIds: Set - ids that require an automated-hint note
 * @returns string - hint text, or '' when the item is not advisory or has no automated result
 */
function buildAdvisoryNote(item, automatedResults, advisoryIds) {
    if (!advisoryIds.has(item.id)) {
        return '';
    }
    const automated = (automatedResults || []).find((r) => r.id === item.id);
    if (!automated) {
        return '';
    }
    return (
        `\n  _Automated pre-check: **${automated.status}**${automated.notes ? ` — ${automated.notes}` : ''}. ` +
        'This only covers a narrow slice of this rule — you must still independently verify the full rule text ' +
        'above (and in the source-of-truth docs below) against the diff. Do not treat this automated result as the final answer._'
    );
}

/**
 * Assembles the full review-request.md content: scope, checklist, source-of-truth
 * docs, unified diff, and response instructions
 * @param options: object - { scope, diffs, checklistItems, instructionsFile, automatedChecks, advisoryAutomatedIds, automatedResults, sourceOfTruthDocs, rootDir }
 * @returns string - full markdown content for review-request.md
 */
function buildReviewRequestMarkdown({
    scope,
    diffs,
    checklistItems,
    instructionsFile,
    automatedChecks,
    advisoryAutomatedIds,
    automatedResults,
    sourceOfTruthDocs,
    rootDir,
    docsRoot
}) {
    const advisoryIds = new Set(advisoryAutomatedIds || []);
    const aiItems = getAiReviewItems(checklistItems, automatedChecks || {}, advisoryAutomatedIds || []);
    const checklistSection = checklistItems
        .map(
            (item) =>
                `- **[${item.id}]** (${item.section}) ${item.text}${buildAdvisoryNote(item, automatedResults, advisoryIds)}`
        )
        .join('\n');

    const truthRoot = docsRoot || rootDir;
    const sourceOfTruthSection = truthRoot
        ? buildSourceOfTruthSection(truthRoot, sourceOfTruthDocs)
        : '';

    return [
        '# AI Code Review Request',
        '',
        '## Scope',
        scope.scopeText,
        '',
        '## Changed Files',
        scope.files.length ? scope.files.map((f) => `- ${f}`).join('\n') : '(none)',
        '',
        '## Checklist (source of truth)',
        `File: ${instructionsFile}`,
        '',
        checklistSection,
        '',
        sourceOfTruthSection,
        '',
        '## Unified Diff',
        '```diff',
        diffs.unified || '(no diff content)',
        '```',
        '',
        '## Instructions',
        'Review ONLY the changes in scope. Apply each checklist item.',
        '',
        '**Read the full "Source-of-Truth Conventions" section above before scoring** — it contains the complete',
        'text of every doc the checklist names as authoritative, including rules that are not spelled out in the',
        'short bullet descriptions, plus worked examples from those docs when present.',
        '',
        '**IDs marked "Automated pre-check" above still require your own independent judgment** — the automated',
        'regex only catches a narrow slice of that rule; do not copy its verdict without checking the full rule text.',
        '',
        '**Review policy:** Report findings and suggestions only. Do NOT edit or fix source files.',
        'The developer applies fixes in their own way. For FAIL items, describe the issue clearly.',
        '',
        buildResponseTemplate(aiItems)
    ].join('\n');
}

/**
 * Writes the review bundle (review-request.md + review-context.json) to disk
 * @param options: object - { rootDir, config, scope, diffs, checklistItems, automatedResults }
 * @returns object - { requestPath, contextPath, outputDir }
 */
function writeReviewBundle({ rootDir, config, scope, diffs, checklistItems, automatedResults }) {
    const outputBase = config.toolRootDir || rootDir;
    const outputDir = path.resolve(outputBase, config.outputDir || '.ai-review');
    fs.mkdirSync(outputDir, { recursive: true });

    const requestPath = path.join(outputDir, 'review-request.md');
    const contextPath = path.join(outputDir, 'review-context.json');

    const aiItems = getAiReviewItems(
        checklistItems,
        config.automatedChecks || {},
        config.advisoryAutomatedIds || []
    );

    const context = {
        mode: scope.mode,
        baseBranch: scope.baseBranch,
        branch: scope.branch,
        branchExplicit: scope.branchExplicit || false,
        commits: scope.commits || [],
        diffRange: scope.diffRange,
        files: scope.files,
        inspectCommand: scope.inspectCommand,
        instructionsFile: config.instructionsFile,
        checklistItemIds: checklistItems.map((i) => i.id),
        aiItemIds: aiItems.map((i) => i.id),
        advisoryAutomatedIds: config.advisoryAutomatedIds || [],
        automatedResults,
        diffTruncated: diffs.truncated,
        diffTotalLines: diffs.totalLines
    };

    const requestMd = buildReviewRequestMarkdown({
        scope,
        diffs,
        checklistItems,
        instructionsFile: config.instructionsFile,
        automatedChecks: config.automatedChecks,
        advisoryAutomatedIds: config.advisoryAutomatedIds,
        automatedResults,
        sourceOfTruthDocs: config.sourceOfTruthDocs,
        rootDir,
        docsRoot: config.standardsDir || rootDir
    });

    fs.writeFileSync(requestPath, requestMd, 'utf8');
    fs.writeFileSync(contextPath, JSON.stringify(context, null, 2), 'utf8');

    return { requestPath, contextPath, outputDir };
}

module.exports = { writeReviewBundle, buildReviewRequestMarkdown };
