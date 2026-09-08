const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const {
    CLAUDE_DISALLOWED_TOOLS,
    buildClaudeArgs,
    buildReviewerPrompt,
    extractIdsFromText,
    formatTable,
    getClaudeBin
} = require('./run-claude-review');

describe('buildClaudeArgs', () => {
    const cases = [
        {
            description: 'passes the prompt after -- so disallowed tools cannot swallow it',
            setup: () => ({ prompt: 'You are a reviewer.\nEvaluate CQ-01.' }),
            expectations: (args, prompt) => {
                assert.deepEqual(args.slice(0, 6), [
                    '-p',
                    '--permission-mode',
                    'plan',
                    '--disallowedTools',
                    'Edit,Write,Bash',
                    '--'
                ]);
                assert.equal(args[args.length - 1], prompt);
            }
        },
        {
            description: 'does not include MultiEdit in disallowed tools',
            setup: () => ({ prompt: 'review' }),
            expectations: (args) => {
                assert.equal(args.includes('MultiEdit'), false);
                assert.equal(CLAUDE_DISALLOWED_TOOLS.includes('MultiEdit'), false);
            }
        }
    ];

    cases.forEach(({ description, setup, expectations }) => {
        test(description, () => {
            const { prompt } = setup();
            expectations(buildClaudeArgs(prompt), prompt);
        });
    });
});

describe('buildReviewerPrompt', () => {
    test('embeds the request path and checklist ids', () => {
        const prompt = buildReviewerPrompt('D:/tmp/review-request.md', ['CQ-01', 'F-01']);
        assert.equal(prompt.includes('D:/tmp/review-request.md'), true);
        assert.equal(prompt.includes('CQ-01, F-01'), true);
        assert.equal(prompt.includes('| ID | Result | Notes |'), true);
    });
});

describe('extractIdsFromText', () => {
    const cases = [
        {
            description: 'finds unique checklist ids',
            setup: () => 'CQ-01 and F-02 then CQ-01 again',
            expectations: (result) => {
                assert.deepEqual(result, ['CQ-01', 'F-02']);
            }
        },
        {
            description: 'returns empty when no ids present',
            setup: () => 'no checklist here',
            expectations: (result) => {
                assert.deepEqual(result, []);
            }
        }
    ];

    cases.forEach(({ description, setup, expectations }) => {
        test(description, () => {
            expectations(extractIdsFromText(setup()));
        });
    });
});

describe('formatTable', () => {
    test('writes a markdown table and escapes pipes in notes', () => {
        const table = formatTable([
            { id: 'CQ-01', status: 'PASS', notes: '' },
            { id: 'CQ-02', status: 'FAIL', notes: 'a | b' }
        ]);
        assert.equal(table.includes('| CQ-01 | PASS |  |'), true);
        assert.equal(table.includes('| CQ-02 | FAIL | a \\| b |'), true);
    });
});

describe('getClaudeBin', () => {
    test('uses the claude executable on PATH', () => {
        assert.equal(getClaudeBin(), 'claude');
    });
});
