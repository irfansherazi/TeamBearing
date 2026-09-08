/**
 * RunningView Tests — Phase 6 (TASK-065)
 *
 * Covers requirements for:
 * - RUNNING mode: live status indicators, StepTable, Agent Reasoning accordion.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RunningView } from '../RunningView';

// Mock ExecutionLog to avoid deep rendering issues
vi.mock('../ExecutionLog', () => ({
  ExecutionLog: () => <div data-testid="execution-log">Mock Log</div>
}));

const mockTicket = { id: 'VC-1', summary: 'Test Ticket In Progress' };
const mockConfig = { role: 'account_executive', targetUrl: 'https://test.vcreative.net' };
const mockSteps = [
  { id: '1', text: 'Step 1', source: 'jira' as const, result: 'passed' as const },
];

describe('RunningView — Rendering', () => {
  it('renders "EXECUTING" status label', () => {
    render(
      <RunningView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        runId="run-123"
        isThinking={false}
        thinkingText=""
        thinkingAcStep={0}
        thinkingAcTotal={0}
        terminalMessage={null}
        onPauseTest={vi.fn()}
        onStopTest={vi.fn()}
      />
    );
    
    expect(screen.getByText(/EXECUTING/i)).toBeInTheDocument();
  });

  it('renders the StepTable with current results', () => {
    render(
      <RunningView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        runId="run-123"
        isThinking={false}
        thinkingText=""
        thinkingAcStep={0}
        thinkingAcTotal={0}
        terminalMessage={null}
        onPauseTest={vi.fn()}
        onStopTest={vi.fn()}
      />
    );
    
    expect(screen.getByText('Step 1')).toBeInTheDocument();
    expect(screen.getByText(/Passed/i)).toBeInTheDocument();
  });

  it('renders Agent Reasoning accordion', () => {
    render(
      <RunningView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        runId="run-123"
        isThinking={true}
        thinkingText="I am thinking..."
        thinkingAcStep={1}
        thinkingAcTotal={5}
        terminalMessage={null}
        onPauseTest={vi.fn()}
        onStopTest={vi.fn()}
      />
    );
    
    expect(screen.getByText(/Agent Reasoning/i)).toBeInTheDocument();
    expect(screen.getByText(/I am thinking.../i)).toBeInTheDocument();
  });
});

describe('RunningView — Actions', () => {
  it('calls onStopTest when Stop button is clicked', () => {
    const onStopTest = vi.fn();
    render(
      <RunningView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        runId="run-123"
        isThinking={false}
        thinkingText=""
        thinkingAcStep={0}
        thinkingAcTotal={0}
        terminalMessage={null}
        onPauseTest={vi.fn()}
        onStopTest={onStopTest}
      />
    );
    
    const stopBtn = screen.getByRole('button', { name: /Stop Test/i });
    fireEvent.click(stopBtn);
    
    expect(onStopTest).toHaveBeenCalled();
  });
});
