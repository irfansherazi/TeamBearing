import { render, screen, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CopilotSidebar from '../CopilotSidebar';

// Mock authenticatedFetch
vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn()
}));

describe('CopilotSidebar', () => {
  const defaultProps = {
    runId: 'test-run-123',
    ticketId: 'QA-123',
    ws: null,
  };

  it('renders initial state correctly', () => {
    render(<CopilotSidebar {...defaultProps} />);
    expect(screen.getByText(/Copilot/i)).toBeInTheDocument();
    expect(screen.getByText(/Waiting for AC steps/i)).toBeInTheDocument();
  });

  it('updates steps when ac_progress message is received', async () => {
    const mockWs = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    render(<CopilotSidebar {...defaultProps} ws={mockWs as any} />);

    // Get the handler from addEventListener
    const messageCall = mockWs.addEventListener.mock.calls.find(c => c[0] === 'message');
    const handler = messageCall ? messageCall[1] : null;
    if (!handler) throw new Error('Message handler not registered');

    // Trigger it
    const event = {
      data: JSON.stringify({
        type: 'ac_progress',
        steps: [
          { index: 0, text: 'Step 1', status: 'passed', error: '', human_selector: '' }
        ]
      })
    };
    
    await act(async () => {
      handler(event);
    });

    await waitFor(() => {
      expect(screen.getByText(/Step 1/i)).toBeInTheDocument();
    });
  });

  it('shows awaiting human state when copilot_ready message is received', async () => {
    const mockWs = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    render(<CopilotSidebar {...defaultProps} ws={mockWs as any} />);

    const messageCall = mockWs.addEventListener.mock.calls.find(c => c[0] === 'message');
    const handler = messageCall ? messageCall[1] : null;
    if (!handler) throw new Error('Message handler not registered');

    const event = {
      data: JSON.stringify({
        type: 'copilot_ready',
        ac_step_index: 0,
        ac_step_text: 'Current Step',
        error_message: 'Selector failed',
        instructions: 'Please click the button'
      })
    };
    
    await act(async () => {
      handler(event);
    });

    await waitFor(() => {
      expect(screen.getByText(/Selector failed/i)).toBeInTheDocument();
      expect(screen.getByText(/Please click the button/i)).toBeInTheDocument();
    });
  });
});
