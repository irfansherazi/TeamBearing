/**
 * CompleteView Tests — Phase 6 (TASK-065)
 *
 * Covers requirements for:
 * - COMPLETE mode: Final results, summary row, action buttons.
 * - Inline triage for failed runs.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { CompleteView } from '../CompleteView';

// Mock TriagePanel
vi.mock('../TriagePanel', () => ({
  TriagePanel: () => <div data-testid="triage-panel">Mock Triage</div>
}));

const mockTicket = { id: 'VC-1', summary: 'Test Ticket Completed' };
const mockConfig = { role: 'account_executive', targetUrl: 'https://test.vcreative.net' };
const mockStepsPassed = [
  { id: '1', text: 'Step 1', source: 'jira' as const, result: 'passed' as const },
];
const mockStepsFailed = [
  { id: '1', text: 'Step 1', source: 'jira' as const, result: 'failed' as const },
];

describe('CompleteView — Rendering', () => {
  it('renders "PASSED" status for successful run', () => {
    render(
      <CompleteView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockStepsPassed}
        runId="run-123"
        onNewRun={vi.fn()}
        onRunAgain={vi.fn()}
        onViewReport={vi.fn()}
        onCopyLink={vi.fn()}
        onTriageRerun={vi.fn()}
        onDismissTriage={vi.fn()}
      />
    );
    
    expect(screen.getAllByText(/PASSED/i).length).toBeGreaterThan(0);
  });

  it('renders "FAILED" status for failed run', () => {
    render(
      <CompleteView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockStepsFailed}
        runId="run-123"
        onNewRun={vi.fn()}
        onRunAgain={vi.fn()}
        onViewReport={vi.fn()}
        onCopyLink={vi.fn()}
        onTriageRerun={vi.fn()}
        onDismissTriage={vi.fn()}
      />
    );
    
    expect(screen.getAllByText(/FAILED/i).length).toBeGreaterThan(0);
  });

  it('renders summary stats (passed/failed counts)', () => {
    render(
      <CompleteView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockStepsPassed}
        runId="run-123"
        onNewRun={vi.fn()}
        onRunAgain={vi.fn()}
        onViewReport={vi.fn()}
        onCopyLink={vi.fn()}
        onTriageRerun={vi.fn()}
        onDismissTriage={vi.fn()}
      />
    );
    
    expect(screen.getByText(/1 passed/i)).toBeInTheDocument();
    expect(screen.getByText(/0 failed/i)).toBeInTheDocument();
  });

  it('renders TriagePanel when triageMessage is provided', () => {
    const mockTriage = { classification: 'product_bug', explanation: 'Bug found' } as any;
    render(
      <CompleteView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockStepsFailed}
        runId="run-123"
        triageMessage={mockTriage}
        onNewRun={vi.fn()}
        onRunAgain={vi.fn()}
        onViewReport={vi.fn()}
        onCopyLink={vi.fn()}
        onTriageRerun={vi.fn()}
        onDismissTriage={vi.fn()}
      />
    );
    
    expect(screen.getByTestId('triage-panel')).toBeInTheDocument();
    expect(screen.getByText(/Failure Analysis/i)).toBeInTheDocument();
  });
});

describe('CompleteView — Actions', () => {
  it('calls onRunAgain when button clicked', () => {
    const onRunAgain = vi.fn();
    render(
      <CompleteView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockStepsPassed}
        runId="run-123"
        onNewRun={vi.fn()}
        onRunAgain={onRunAgain}
        onViewReport={vi.fn()}
        onCopyLink={vi.fn()}
        onTriageRerun={vi.fn()}
        onDismissTriage={vi.fn()}
      />
    );
    
    fireEvent.click(screen.getByRole('button', { name: /Run Again/i }));
    expect(onRunAgain).toHaveBeenCalled();
  });
});
