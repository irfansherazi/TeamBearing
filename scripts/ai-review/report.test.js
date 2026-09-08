const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { mergeResults, formatReport } = require('./report');

const checklistItems = [
    { id: 'CQ-01', section: 'Code Quality', text: 'naming/formatting/structure' },
    { id: 'CQ-05', section: 'Code Quality', text: 'no console/debugger' },
    { id: 'F-03', section: 'Functionality', text: 'feature works as expected' },
    { id: 'T-01', section: 'Testing', text: 'all existing tests pass' },
    { id: 'PH-01', section: 'PR Hygiene', text: 'PR title and description are clear' }
];

const baseConfig = {
    automatedChecks: { 'CQ-01': 'conventionGuardrails', 'CQ-05': 'noConsoleOrDebugger' },
    advisoryAutomatedIds: ['CQ-01'],
    aiReviewCommand: '',
    runTests: false
};

describe('mergeResults', () => {
    test('advisory id: an automated PASS does not override an AI FAIL for the same id', () => {
        const automatedResults = [
            { id: 'CQ-01', status: 'PASS', notes: 'no id/formatting hits' },
            { id: 'CQ-05', status: 'PASS', notes: '' }
        ];
        const aiResults = [{ id: 'CQ-01', status: 'FAIL', notes: 'missing JSDoc' }];

        const merged = mergeResults(checklistItems, automatedResults, aiResults, baseConfig, {}, { mode: 'branch' });

        const cq01 = merged.find((r) => r.id === 'CQ-01');
        assert.equal(cq01.status, 'FAIL');
        assert.match(cq01.notes, /missing JSDoc/);
        assert.match(cq01.notes, /Automated hint \(PASS\)/);
    });

    test('non-advisory automated result is used as-is, without requiring an AI verdict', () => {
        const automatedResults = [{ id: 'CQ-05', status: 'PASS', notes: '' }];
        const merged = mergeResults(checklistItems, automatedResults, [], baseConfig, {}, { mode: 'branch' });

        assert.deepEqual(merged.find((r) => r.id === 'CQ-05'), { id: 'CQ-05', status: 'PASS', notes: '' });
    });

    test('T-01 is PASS with a not-executed note when --run-tests was not passed', () => {
        const merged = mergeResults(checklistItems, [], [], baseConfig, {}, { mode: 'branch' });

        const t01 = merged.find((r) => r.id === 'T-01');
        assert.equal(t01.status, 'PASS');
        assert.match(t01.notes, /require --run-tests/);
    });

    test('T-01 uses the automated result when --run-tests was passed', () => {
        const config = { ...baseConfig, runTests: true };
        const automatedResults = [{ id: 'T-01', status: 'FAIL', notes: 'serverTest failed' }];

        const merged = mergeResults(checklistItems, automatedResults, [], config, {}, { mode: 'branch' });

        assert.deepEqual(merged.find((r) => r.id === 'T-01'), { id: 'T-01', status: 'FAIL', notes: 'serverTest failed' });
    });

    test('PH-* is overridden to PASS+N/A for local review modes (files/commits), not for branch mode', () => {
        const localMerged = mergeResults(checklistItems, [], [], baseConfig, {}, { mode: 'files' });
        const branchMerged = mergeResults(checklistItems, [], [], baseConfig, {}, { mode: 'branch' });

        assert.equal(localMerged.find((r) => r.id === 'PH-01').status, 'PASS');
        assert.match(localMerged.find((r) => r.id === 'PH-01').notes, /verify when opening PR/);
        assert.notEqual(branchMerged.find((r) => r.id === 'PH-01').notes, localMerged.find((r) => r.id === 'PH-01').notes);
    });

    test('an id needing AI judgment with no AI result is SKIP with a helpful note', () => {
        const merged = mergeResults(checklistItems, [], [], baseConfig, {}, { mode: 'branch' });

        const f03 = merged.find((r) => r.id === 'F-03');
        assert.equal(f03.status, 'SKIP');
        assert.match(f03.notes, /Requires AI review/);
    });

    test('preserves checklist item order in the output', () => {
        const merged = mergeResults(checklistItems, [], [], baseConfig, {}, { mode: 'branch' });

        assert.deepEqual(merged.map((r) => r.id), checklistItems.map((i) => i.id));
    });
});

describe('formatReport — diff truncation', () => {
    const scope = { mode: 'branch', branch: 'feature/x', baseBranch: 'Develop' };
    const allPassResults = [{ id: 'CQ-01', status: 'PASS', notes: '' }];
    const baseOptions = {
        scope,
        files: ['a.ts'],
        results: allPassResults,
        bundlePaths: null,
        aiRan: true,
        config: { maxDiffLines: 8000 },
        commandNotFound: false,
        parseWarning: false
    };

    test('untruncated diff with all-PASS checklist stays exit code 0 and not incomplete', () => {
        const report = formatReport({ ...baseOptions, diffTruncated: false, diffTotalLines: 500 });

        assert.equal(report.incomplete, false);
        assert.equal(report.exitCode, 0);
        assert.doesNotMatch(report.text, /DIFF TRUNCATED/);
    });

    test('truncated diff forces exit code 1 even when every checklist item PASSes', () => {
        const report = formatReport({ ...baseOptions, diffTruncated: true, diffTotalLines: 12000 });

        assert.equal(report.incomplete, true);
        assert.equal(report.exitCode, 1);
        assert.equal(report.fail, 0);
    });

    test('truncation warning states the cap and how many lines were dropped', () => {
        const report = formatReport({ ...baseOptions, diffTruncated: true, diffTotalLines: 12000 });

        assert.match(report.text, /DIFF TRUNCATED/);
        assert.match(report.text, /first 8000 of 12000 diff lines/);
        assert.match(report.text, /~4000 lines NOT reviewed/);
        assert.match(report.text, /INCOMPLETE — do not treat it as a clean pass/);
    });

    test('truncated diff plus a real checklist FAIL still reports exit code 1 with a combined explanation', () => {
        const failResults = [{ id: 'CQ-01', status: 'FAIL', notes: 'bad thing' }];
        const report = formatReport({
            ...baseOptions,
            results: failResults,
            diffTruncated: true,
            diffTotalLines: 9000
        });

        assert.equal(report.exitCode, 1);
        assert.match(report.text, /1 failure\(s\), AND the diff was truncated/);
    });
});
