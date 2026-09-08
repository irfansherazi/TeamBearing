const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { parseAiResultsTable, isCommandNotFoundError } = require('./ai-runner');

describe('parseAiResultsTable', () => {
    test('parses a well-formed markdown table', () => {
        const stdout = [
            '| ID | Result | Notes |',
            '|----|--------|-------|',
            '| CQ-01 | PASS | |',
            '| CQ-02 | FAIL | dead code found |'
        ].join('\n');

        const results = parseAiResultsTable(stdout, ['CQ-01', 'CQ-02']);

        assert.deepEqual(results, [
            { id: 'CQ-01', status: 'PASS', notes: '' },
            { id: 'CQ-02', status: 'FAIL', notes: 'dead code found' }
        ]);
    });

    test('force-fails any expected id missing from the table', () => {
        const stdout = ['| ID | Result | Notes |', '|----|--------|-------|', '| CQ-01 | PASS | |'].join('\n');

        const results = parseAiResultsTable(stdout, ['CQ-01', 'CQ-02']);

        assert.deepEqual(results, [
            { id: 'CQ-01', status: 'PASS', notes: '' },
            { id: 'CQ-02', status: 'FAIL', notes: 'Not evaluated by AI command' }
        ]);
    });

    test('normalizes bold-wrapped ids and preserves row order from expectedIds, not table order', () => {
        const stdout = ['| **CQ-02** | FAIL | out of order |', '| **CQ-01** | PASS | |'].join('\n');

        const results = parseAiResultsTable(stdout, ['CQ-01', 'CQ-02']);

        assert.deepEqual(results.map((r) => r.id), ['CQ-01', 'CQ-02']);
        assert.equal(results[1].notes, 'out of order');
    });

    test('ignores markdown separator rows and header rows', () => {
        const stdout = [
            '| ID | Result | Notes |',
            '|----|--------|-------|',
            '| CQ-01 | PASS | |'
        ].join('\n');

        const results = parseAiResultsTable(stdout, ['CQ-01']);

        assert.equal(results.length, 1);
        assert.equal(results[0].id, 'CQ-01');
    });

    test('returns an empty array when expectedIds is empty', () => {
        assert.deepEqual(parseAiResultsTable('| CQ-01 | PASS | |', []), []);
    });
});

describe('isCommandNotFoundError', () => {
    test('detects Windows "not recognized" errors', () => {
        assert.equal(isCommandNotFoundError({}, "'claude' is not recognized as an internal or external command"), true);
    });

    test('detects POSIX ENOENT errors', () => {
        assert.equal(isCommandNotFoundError({ message: 'spawn claude ENOENT' }, ''), true);
    });

    test('returns false for an unrelated failure', () => {
        assert.equal(isCommandNotFoundError({ message: 'exit code 1' }, 'some lint error'), false);
    });
});
