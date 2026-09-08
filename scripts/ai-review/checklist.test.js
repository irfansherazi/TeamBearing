const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { parseChecklistFile, getAiReviewItems } = require('./checklist');

describe('parseChecklistFile', () => {
    function writeChecklist(content) {
        const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-checklist-'));
        const fileName = 'checklist.md';
        fs.writeFileSync(path.join(rootDir, fileName), content, 'utf8');
        return { rootDir, fileName };
    }

    test('parses ids, sections, and text from a well-formed checklist', () => {
        const { rootDir, fileName } = writeChecklist(
            [
                '### 1. Code Quality',
                '- **[CQ-01]** Code follows team conventions.',
                '- **[CQ-02]** No commented-out or dead code.',
                '### 2. Functionality',
                '- **[F-01]** No unintended functionality changes.'
            ].join('\n')
        );

        const items = parseChecklistFile(rootDir, fileName);

        assert.deepEqual(items, [
            { id: 'CQ-01', section: 'Code Quality', text: 'Code follows team conventions.' },
            { id: 'CQ-02', section: 'Code Quality', text: 'No commented-out or dead code.' },
            { id: 'F-01', section: 'Functionality', text: 'No unintended functionality changes.' }
        ]);

        fs.rmSync(rootDir, { recursive: true, force: true });
    });

    test('throws when the checklist file does not exist', () => {
        assert.throws(() => parseChecklistFile('/does/not/exist', 'missing.md'), /Checklist file not found/);
    });

    test('throws when no checklist items are found', () => {
        const { rootDir, fileName } = writeChecklist('# Just a heading\nNo bullet items here.');

        assert.throws(() => parseChecklistFile(rootDir, fileName), /No checklist items with IDs found/);

        fs.rmSync(rootDir, { recursive: true, force: true });
    });
});

describe('getAiReviewItems', () => {
    const items = [
        { id: 'CQ-01', section: 'Code Quality', text: 'a' },
        { id: 'CQ-05', section: 'Code Quality', text: 'b' },
        { id: 'F-01', section: 'Functionality', text: 'c' }
    ];

    test('excludes fully-automated ids', () => {
        const result = getAiReviewItems(items, { 'CQ-05': 'noConsoleOrDebugger' }, []);

        assert.deepEqual(result.map((i) => i.id), ['CQ-01', 'F-01']);
    });

    test('keeps advisory ids even though an automated check also runs for them', () => {
        const result = getAiReviewItems(
            items,
            { 'CQ-01': 'conventionGuardrails', 'CQ-05': 'noConsoleOrDebugger' },
            ['CQ-01']
        );

        assert.deepEqual(result.map((i) => i.id), ['CQ-01', 'F-01']);
    });
});
