const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
    CLAUDE_DISALLOWED_TOOLS,
    buildClaudeArgs,
    buildReviewArgs,
    writeAgentPromptFile,
    commandLaunch,
    buildReviewerPrompt,
    extractIdsFromText,
    formatTable,
    resolveReviewCommand
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

describe('commandLaunch', () => {
    test('starts Windows agent.cmd through its PowerShell script', () => {
        const launch = commandLaunch(
            'C:\\cursor-agent\\agent.cmd',
            ['-p', 'review'],
            'win32',
            (file) => file.endsWith('.ps1')
        );
        assert.equal(launch.file, 'powershell.exe');
        assert.equal(launch.args.includes('C:\\cursor-agent\\agent.ps1'), true);
        assert.equal(launch.args[launch.args.length - 1], 'review');
    });
});

describe('writeAgentPromptFile', () => {
    test('keeps --run-tests in the file and out of the command line', () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-review-'));
        const cliPrompt = writeAgentPromptFile('require --run-tests before PR', dir);
        const saved = fs.readFileSync(path.join(dir, 'ai-review-prompt.txt'), 'utf8');
        assert.equal(saved.includes('--run-tests'), true);
        assert.equal(cliPrompt.includes('--run-tests'), false);
        assert.equal(cliPrompt.includes('ai-review-prompt.txt'), true);
    });
});

describe('buildReviewArgs', () => {
    test('uses Cursor agent flags when kind is agent', () => {
        const args = buildReviewArgs('agent', 'review this');
        assert.deepEqual(args, ['-p', '--mode', 'ask', '--output-format', 'text', '--trust', '--', 'review this']);
    });
});

describe('resolveReviewCommand', () => {
    const cases = [
        {
            description: 'uses claude when only claude is installed',
            setup: () => ({ env: {}, lookup: (name) => (name === 'claude' ? 'claude' : '') }),
            expectations: (result) => {
                assert.deepEqual(result, { bin: 'claude', kind: 'claude' });
            }
        },
        {
            description: 'uses agent when only Cursor agent is installed',
            setup: () => ({
                env: {},
                lookup: (name) => (name === 'agent' ? '/Users/mac/.local/bin/agent' : '')
            }),
            expectations: (result) => {
                assert.deepEqual(result, { bin: '/Users/mac/.local/bin/agent', kind: 'agent' });
            }
        },
        {
            description: 'keeps claude when both tools are installed',
            setup: () => ({ env: {}, lookup: () => 'found' }),
            expectations: (result) => {
                assert.equal(result.kind, 'claude');
            }
        },
        {
            description: 'honors AI_REVIEW_BIN=agent and uses the installed path',
            setup: () => ({
                env: { AI_REVIEW_BIN: 'agent' },
                lookup: (name) => (name === 'agent' ? 'C:\\cursor-agent\\agent.cmd' : '')
            }),
            expectations: (result) => {
                assert.deepEqual(result, { bin: 'C:\\cursor-agent\\agent.cmd', kind: 'agent' });
            }
        }
    ];

    cases.forEach(({ description, setup, expectations }) => {
        test(description, () => {
            const { env, lookup } = setup();
            expectations(resolveReviewCommand(env, lookup));
        });
    });
});
