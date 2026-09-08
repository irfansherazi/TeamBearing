/**
 * ReviewView Tests — Phase 6 (TASK-065)
 *
 * Covers requirements for:
 * - REVIEW mode: ticket title as H1, step table visible, CTA buttons.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ReviewView } from '../ReviewView';

const mockTicket = { id: 'VC-1', summary: 'Test Ticket Summary' };
const mockConfig = { role: 'account_executive', targetUrl: 'https://test.vcreative.net' };
const mockSteps = [
  { id: '1', text: 'Step 1', source: 'jira' as const },
];

describe('ReviewView — Rendering', () => {
  it('renders ticket summary as H1', () => {
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );
    
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Test Ticket Summary');
  });

  it('renders the StepTable', () => {
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );
    
    expect(screen.getByText('Step 1')).toBeInTheDocument();
  });
});

describe('ReviewView — Actions', () => {
  it('calls onStartTest when "Start Test" button is clicked', () => {
    const onStartTest = vi.fn();
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={onStartTest}
        onBack={vi.fn()}
      />
    );
    
    const startBtn = screen.getAllByRole('button', { name: /Start Test/i })[0];
    fireEvent.click(startBtn);
    
    expect(onStartTest).toHaveBeenCalled();
  });

  it('calls onBack when back button is clicked', () => {
    const onBack = vi.fn();
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={onBack}
      />
    );
    
    const backBtn = screen.getByTitle(/Change Ticket/i);
    fireEvent.click(backBtn);
    
    expect(onBack).toHaveBeenCalled();
  });
});

describe('ReviewView — Pre-Parse Guidance', () => {
  it('renders Additional Context textarea with placeholder and live character counter', () => {
    render(
      <ReviewView
        ticket={mockTicket}
        config={{ ...mockConfig, preParseGuidance: 'Initial guidance' }}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );

    const textarea = screen.getByLabelText(/Additional Context \(Pre-Parse Guidance\)/i) as HTMLTextAreaElement;
    expect(textarea).toBeInTheDocument();
    expect(textarea.value).toBe('Initial guidance');
    expect(screen.getByText('16/2000 characters')).toBeInTheDocument();
  });

  it('updates character count dynamically', () => {
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );

    const textarea = screen.getByLabelText(/Additional Context \(Pre-Parse Guidance\)/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Hello' } });

    expect(textarea.value).toBe('Hello');
    expect(screen.getByText('5/2000 characters')).toBeInTheDocument();
  });

  it('passes the typed guidance text as argument to onStartTest', () => {
    const onStartTest = vi.fn();
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={onStartTest}
        onBack={vi.fn()}
      />
    );

    const textarea = screen.getByLabelText(/Additional Context \(Pre-Parse Guidance\)/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Guidance text to submit' } });

    const startBtn = screen.getAllByRole('button', { name: /Start Test/i })[0];
    fireEvent.click(startBtn);

    expect(onStartTest).toHaveBeenCalledWith('Guidance text to submit');
  });

  it('resets or updates textarea value when switching tickets/config', () => {
    const { rerender } = render(
      <ReviewView
        key={mockTicket.id}
        ticket={mockTicket}
        config={{ ...mockConfig, preParseGuidance: 'Guidance 1' }}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );

    const textarea = screen.getByLabelText(/Additional Context \(Pre-Parse Guidance\)/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Guidance 1');

    rerender(
      <ReviewView
        key="VC-2"
        ticket={{ id: 'VC-2', summary: 'Ticket 2' }}
        config={{ ...mockConfig, preParseGuidance: 'Guidance 2' }}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
      />
    );

    const textareaAfter = screen.getByLabelText(/Additional Context \(Pre-Parse Guidance\)/i) as HTMLTextAreaElement;
    expect(textareaAfter.value).toBe('Guidance 2');
  });

  it('hides the Additional Context textarea in paused execution resume mode', () => {
    render(
      <ReviewView
        ticket={mockTicket}
        config={mockConfig}
        steps={mockSteps}
        isLoading={false}
        onEditStep={vi.fn()}
        onRemoveStep={vi.fn()}
        onReorderSteps={vi.fn()}
        onAddStep={vi.fn()}
        onStartTest={vi.fn()}
        onBack={vi.fn()}
        isPaused={true}
      />
    );

    expect(screen.queryByLabelText(/Additional Context \(Pre-Parse Guidance\)/i)).not.toBeInTheDocument();
  });
});
