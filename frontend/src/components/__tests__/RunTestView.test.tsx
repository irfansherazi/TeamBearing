/**
 * RunTestView Tests — cu-loop-default-remove-toggle
 *
 * Covers requirements for:
 * - State machine transitions: SELECT -> REVIEW -> RUNNING -> COMPLETE.
 * - Integration with useExecution and useWebSocket hooks.
 * - CU-always invariant: the legacy toggle checkbox must not render and
 *   startComputerUseExecution must be the only run-initiation path.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RunTestView } from '../RunTestView';
import { authenticatedFetch } from '../../api_client';

// Mock api_client
vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn(),
}));

// Mock hooks
const mockStartComputerUseExecution = vi.fn();
const mockCheckHealth = vi.fn();
const mockResetRun = vi.fn();

vi.mock('../../hooks/useExecution', () => ({
  useExecution: () => ({
    isLoading: false,
    error: null,
    executeResponse: { run_id: 'run-123' },
    startComputerUseExecution: mockStartComputerUseExecution,
    checkHealth: mockCheckHealth,
    checkTicketCredentials: vi.fn(),
    pauseExecution: vi.fn(),
    resumeExecution: vi.fn(),
    resetRun: mockResetRun,
  }),
}));

const mockConnect = vi.fn();
const mockResetState = vi.fn();

vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: () => ({
    acProgress: [],
    terminalMessage: null,
    latestScreenshot: null,
    isThinking: false,
    thinkingText: '',
    thinkingAcStep: 0,
    thinkingAcTotal: 0,
    triageMessage: null,
    humanTakeoverMessage: null,
    personaCredentialsMessage: null,
    ghostCredentialsMessage: null,
    wsSocket: null,
    connect: mockConnect,
    resetState: mockResetState,
  }),
}));

// Mock SelectView to simplify transitions.
// The onTicketSelected config includes customEmail so the CU path can find
// admin credentials (required since the toggle was removed and CU is always on).
vi.mock('../SelectView', () => ({
  SelectView: ({ onTicketSelected, onStaticTestSelected }: any) => (
    <div data-testid="select-view">
      <button onClick={() => onTicketSelected(
        { id: 'VC-1', summary: 'Test' },
        {
          role: 'admin',
          targetUrl: 'https://test.com',
          preParseGuidance: '',
          useCustomCreds: true,
          customEmail: 'admin@example.com',
          customPassword: 'secret',
        }
      )}>
        Select Ticket
      </button>
      <button onClick={() => onStaticTestSelected(
        { id: 'VC-1', summary: 'Test' },
        { id: 'qa-170-test', step_names: ['Step 1'] },
        { role: 'account_executive', targetUrl: 'https://two-test.vcreative.net', preParseGuidance: '' }
      )}>
        Select Static Ticket
      </button>
    </div>
  )
}));

describe('RunTestView — State Machine', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ steps: ['Step 1'], parse_quality: 'good' }),
    } as Response);
  });

  it('starts in SELECT mode', () => {
    render(<RunTestView />);
    expect(screen.getByTestId('select-view')).toBeInTheDocument();
  });

  it('transitions to REVIEW mode when a ticket is selected', async () => {
    render(<RunTestView />);
    fireEvent.click(screen.getByText(/Select Ticket/i));

    // The title should be the ticket summary
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Test');
    });
  });

  it('transitions to RUNNING mode via Computer-Use path when test starts', async () => {
    mockStartComputerUseExecution.mockResolvedValue({ run_id: 'run-123' });
    render(<RunTestView />);

    // Select ticket
    fireEvent.click(screen.getByText(/Select Ticket/i));

    // Wait for preview to finish (button becomes enabled)
    await waitFor(() => {
      const startBtn = screen.getAllByRole('button', { name: /Start Test/i })[0];
      expect(startBtn).not.toBeDisabled();
    });

    // Start test
    const startBtn = screen.getAllByRole('button', { name: /Start Test/i })[0];
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(mockStartComputerUseExecution).toHaveBeenCalled();
      expect(screen.getByText(/EXECUTING/i)).toBeInTheDocument();
      expect(mockConnect).toHaveBeenCalledWith('run-123');
    });
  });

  it('transitions directly to RUNNING mode when a static test is selected', async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ run_id: 'run-static-123' }),
    } as Response);

    render(<RunTestView />);
    fireEvent.click(screen.getByText(/Select Static Ticket/i));

    await waitFor(() => {
      expect(authenticatedFetch).toHaveBeenCalledWith(
        expect.stringContaining('/playwright/run'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            test_id: 'qa-170-test',
            env: 'test',
            user: 'DemoSalesExec',
            browser: 'chromium'
          })
        })
      );
      expect(screen.getByText(/EXECUTING/i)).toBeInTheDocument();
      expect(mockConnect).toHaveBeenCalledWith('run-static-123');
    });
  });
});

// ── CU-always regression assertions ────────────────────────────────────────
// These tests fail if the toggle checkbox is re-introduced or if the legacy
// startExecution path is wired back into the component. They are structural
// guards: they do not test behavior — they test *absence* of removed code.

describe('RunTestView — CU-always invariant (regression guards)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(authenticatedFetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ steps: ['Step 1'], parse_quality: 'good' }),
    } as Response);
  });

  it('does not render the Computer-Use loop toggle checkbox', () => {
    render(<RunTestView />);
    // The checkbox had id="cu-loop-toggle"; it must not exist.
    expect(document.getElementById('cu-loop-toggle')).toBeNull();
  });

  it('does not render a label referencing the legacy /execute endpoint', () => {
    render(<RunTestView />);
    // The toggle label mentioned "POST /execute (legacy LangGraph pipeline)".
    // If this text appears, the toggle was re-added.
    expect(screen.queryByText(/legacy LangGraph pipeline/i)).toBeNull();
  });
});
