/**
 * StepTable Tests — Phase 5/6 (TASK-065)
 *
 * Covers requirements for:
 * - Rendering steps in REVIEW, RUNNING, and COMPLETE modes.
 * - Interaction in REVIEW mode: Edit, Remove, Add.
 * - Live status updates in RUNNING/COMPLETE modes.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { StepTable } from '../StepTable';
import type { StepRow } from '../StepTable';

const mockSteps: StepRow[] = [
  { id: '1', text: 'Step 1', source: 'jira', result: 'passed' },
  { id: '2', text: 'Step 2', source: 'jira', result: 'running' },
  { id: '3', text: 'Step 3', source: 'user_added', result: 'waiting' },
];

describe('StepTable — Rendering', () => {
  it('renders all steps provided', () => {
    render(<StepTable steps={mockSteps} mode="review" />);
    expect(screen.getByText(/Step 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Step 2/i)).toBeInTheDocument();
    expect(screen.getByText(/Step 3/i)).toBeInTheDocument();
  });

  it('renders "Source" column only in REVIEW mode', () => {
    const { rerender } = render(<StepTable steps={mockSteps} mode="review" />);
    expect(screen.getByText(/Source/i)).toBeInTheDocument();

    rerender(<StepTable steps={mockSteps} mode="running" />);
    expect(screen.queryByText(/Source/i)).not.toBeInTheDocument();
  });

  it('renders "Result" column only in RUNNING/COMPLETE modes', () => {
    const { rerender } = render(<StepTable steps={mockSteps} mode="review" />);
    expect(screen.queryByText(/Result/i)).not.toBeInTheDocument();

    rerender(<StepTable steps={mockSteps} mode="running" />);
    expect(screen.getByText(/Result/i)).toBeInTheDocument();

    rerender(<StepTable steps={mockSteps} mode="complete" />);
    expect(screen.getByText(/Result/i)).toBeInTheDocument();
  });
});

describe('StepTable — REVIEW Mode Actions', () => {
  it('calls onEdit when a step text is changed', () => {
    const onEdit = vi.fn();
    render(<StepTable steps={mockSteps} mode="review" onEdit={onEdit} />);
    
    const input = screen.getAllByRole('textbox')[0]; // StepTable uses textarea in review mode
    fireEvent.change(input, { target: { value: 'Updated Step 1' } });
    
    expect(onEdit).toHaveBeenCalledWith('1', 'Updated Step 1');
  });

  it('calls onRemove when the delete button is clicked', () => {
    const onRemove = vi.fn();
    render(<StepTable steps={mockSteps} mode="review" onRemove={onRemove} />);
    
    const removeBtns = screen.getAllByTitle(/Remove step/i);
    fireEvent.click(removeBtns[0]);
    
    expect(onRemove).toHaveBeenCalledWith('1');
  });

  it('calls onAddStep when the quick-add form is submitted', () => {
    const onAddStep = vi.fn();
    render(<StepTable steps={mockSteps} mode="review" onAddStep={onAddStep} />);
    
    const input = screen.getByPlaceholderText(/Add anything/i);
    const addBtn = screen.getByRole('button', { name: /Add/i });
    
    fireEvent.change(input, { target: { value: 'New User Step' } });
    fireEvent.click(addBtn);
    
    expect(onAddStep).toHaveBeenCalledWith('New User Step');
  });
});

describe('StepTable — RUNNING/COMPLETE Mode Status', () => {
  it('renders correct status badges in running mode', () => {
    render(<StepTable steps={mockSteps} mode="running" />);
    
    expect(screen.getByText(/Passed/i)).toBeInTheDocument();
    expect(screen.getByText(/Running/i)).toBeInTheDocument();
    expect(screen.getByText(/Waiting/i)).toBeInTheDocument();
  });

  it('steps are not editable in complete mode', () => {
    render(<StepTable steps={mockSteps} mode="complete" />);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('calls onFalsePositive when the 🚩 button is clicked', () => {
    const onFalsePositive = vi.fn();
    const stepsWithFailure: StepRow[] = [
      { id: '1', text: 'Step 1', source: 'jira', result: 'failed' }
    ];
    render(<StepTable steps={stepsWithFailure} mode="running" onFalsePositive={onFalsePositive} />);
    
    const fpBtn = screen.getByTitle(/Mark as False Positive/i);
    fireEvent.click(fpBtn);
    
    expect(onFalsePositive).toHaveBeenCalledWith(0);
  });
});
