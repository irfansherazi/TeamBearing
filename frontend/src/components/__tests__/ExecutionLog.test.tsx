import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ExecutionLog } from '../ExecutionLog';

// Mock thinking card to simplify
vi.mock('../ThinkingCard', () => ({
  ThinkingCard: () => <div data-testid="thinking-card">Thinking...</div>
}));

// Mock authenticatedFetch
vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn()
}));

describe('ExecutionLog', () => {
  const defaultProps = {
    runId: 'test-run-123',
    runLabel: 'Test Run',
    steps: [],
    terminalMessage: null,
    connectionState: 'connected' as const,
    isThinking: false,
    thinkingText: '',
    thinkingAcStep: 0,
    thinkingAcTotal: 4,
  };

  it('renders empty state when no steps are present', () => {
    render(<ExecutionLog {...defaultProps} />);
    expect(screen.getByText(/Waiting for execution steps/i)).toBeInTheDocument();
  });

  it('renders steps when provided', () => {
    const steps = [
      {
        type: 'step' as const,
        action: 'click',
        selector: 'button',
        success: true,
        llm_reasoning: 'I clicked the button',
        timestamp: new Date().toISOString(),
        ac_step_index: 0,
        screenshot_url: 'http://example.com/shot.png'
      }
    ];
    render(<ExecutionLog {...defaultProps} steps={steps as any} />);
    expect(screen.getByText(/I clicked the button/i)).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for execution steps/i)).not.toBeInTheDocument();
  });

  it('shows thinking card when isThinking is true', () => {
    render(<ExecutionLog {...defaultProps} isThinking={true} />);
    expect(screen.getByTestId('thinking-card')).toBeInTheDocument();
  });

  it('shows terminal card when terminalMessage is provided', () => {
    const terminalMessage = {
      type: 'completed' as const,
      run_id: 'test-run-123',
      ac_steps_passed: 4,
      ac_steps_total: 4,
      bugs_found: 0,
      report_url: 'http://example.com/report.html'
    };
    render(<ExecutionLog {...defaultProps} terminalMessage={terminalMessage as any} />);
    expect(screen.getByText(/All Tests Passed/i)).toBeInTheDocument();
    expect(screen.getByText(/4\/4 AC steps passed/i)).toBeInTheDocument();
  });

  it('shows error terminal card on failure', () => {
    const terminalMessage = {
      type: 'failed' as const,
      run_id: 'test-run-123',
      ac_steps_passed: 2,
      ac_steps_total: 4,
      bugs_found: 1,
      error: 'Something went wrong',
      report_url: 'http://example.com/report.html'
    };
    render(<ExecutionLog {...defaultProps} terminalMessage={terminalMessage as any} />);
    expect(screen.getByText(/Test Run Failed/i)).toBeInTheDocument();
    expect(screen.getByText(/2\/4 AC steps passed · 1 bug found/i)).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
  });
});
