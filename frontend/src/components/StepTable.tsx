/**
 * vQA — StepTable Component
 * ==========================
 * Module: frontend/src/components/StepTable.tsx
 *
 * A reusable table for displaying and interacting with test steps.
 * Used in REVIEW, RUNNING, and COMPLETE modes.
 *
 * Features:
 * - REVIEW mode: Drag-to-reorder, inline edit, delete, quick-add.
 * - RUNNING mode: Live result badges (✅ Passed, ⏳ Running, etc.).
 * - COMPLETE mode: Final results and summary.
 *
 * Design: TASK-065 UI Overhaul.
 */

import React, { useState } from 'react';

export interface StepRow {
  id: string; // unique ID for keys and drag-drop
  text: string;
  source: 'jira' | 'user_added';
  result?: 'passed' | 'failed' | 'running' | 'skipped' | 'waiting';
  reasoning?: string;
}

interface StepTableProps {
  steps: StepRow[];
  mode: 'review' | 'running' | 'complete';
  onEdit?: (id: string, newText: string) => void;
  onRemove?: (id: string) => void;
  onReorder?: (draggedId: string, overId: string) => void;
  onAddStep?: (text: string) => void;
  onFalsePositive?: (index: number) => void;
}

export function StepTable({
  steps,
  mode,
  onEdit,
  onRemove,
  onReorder,
  onAddStep,
  onFalsePositive
}: StepTableProps) {
  const [quickAddText, setQuickAddText] = useState('');
  const [draggedId, setDraggedId] = useState<string | null>(null);

  const handleDragStart = (id: string) => {
    if (mode !== 'review') return;
    setDraggedId(id);
  };

  const handleDragOver = (e: React.DragEvent, id: string) => {
    if (mode !== 'review' || !draggedId || draggedId === id) return;
    e.preventDefault();
    onReorder?.(draggedId, id);
  };

  const handleDragEnd = () => {
    setDraggedId(null);
  };

  const handleQuickAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (quickAddText.trim()) {
      onAddStep?.(quickAddText.trim());
      setQuickAddText('');
    }
  };

  return (
    <div className={`step-table-container mode-${mode}`}>
      <table className="step-table">
        <thead>
          <tr>
            <th className="col-num">#</th>
            <th className="col-step">Test Step</th>
            {mode === 'review' && <th className="col-source">Source</th>}
            {mode !== 'review' && <th className="col-result">Result</th>}
            {mode === 'review' && <th className="col-actions"></th>}
          </tr>
        </thead>
        <tbody>
          {steps.map((step, idx) => (
            <tr
              key={step.id}
              className={`step-row ${draggedId === step.id ? 'is-dragging' : ''} ${step.result || ''}`}
              draggable={mode === 'review'}
              onDragStart={() => handleDragStart(step.id)}
              onDragOver={(e) => handleDragOver(e, step.id)}
              onDragEnd={handleDragEnd}
            >
              <td className="col-num">
                {mode === 'review' && <span className="drag-handle">⋮⋮</span>}
                {idx + 1}
              </td>
              <td className="col-step">
                {mode === 'review' ? (
                  <textarea
                    className="step-edit-input"
                    value={step.text}
                    rows={1}
                    onChange={(e) => onEdit?.(step.id, e.target.value)}
                    onInput={(e) => {
                      // Auto-expand textarea
                      const target = e.target as HTMLTextAreaElement;
                      target.style.height = 'auto';
                      target.style.height = `${target.scrollHeight}px`;
                    }}
                  />
                ) : (
                  <div className="step-text-display">
                    {step.text}
                    {step.reasoning && (
                      <div className="step-reasoning-inline">{step.reasoning}</div>
                    )}
                  </div>
                )}
              </td>
              {mode === 'review' && (
                <td className="col-source">
                  <span className={`source-badge ${step.source}`}>
                    {step.source === 'jira' ? '⟠ Jira' : '✚ You'}
                  </span>
                </td>
              )}
              {mode !== 'review' && (
                <td className="col-result">
                  <div className="result-group">
                    <StatusBadge status={step.result || 'waiting'} />
                    {(step.result === 'failed' || step.result === 'waiting') && onFalsePositive && (
                      <button
                        className="btn-false-positive"
                        title="Mark as False Positive (Pass this step)"
                        onClick={() => onFalsePositive(idx)}
                      >
                        🚩
                      </button>
                    )}
                  </div>
                </td>
              )}
              {mode === 'review' && (
                <td className="col-actions">
                  <button
                    className="step-remove-btn"
                    onClick={() => onRemove?.(step.id)}
                    title="Remove step"
                  >
                    ✕
                  </button>
                </td>
              )}
            </tr>
          ))}
          {mode === 'review' && (
            <tr className="quick-add-row">
              <td className="col-num">✦</td>
              <td colSpan={3} className="col-step">
                <form onSubmit={handleQuickAdd} className="quick-add-form">
                  <input
                    type="text"
                    className="quick-add-input"
                    placeholder="Add anything — 'also check the error message' or 'what if they try a PDF?'"
                    value={quickAddText}
                    onChange={(e) => setQuickAddText(e.target.value)}
                  />
                  <button type="submit" className="quick-add-btn" disabled={!quickAddText.trim()}>
                    Add
                  </button>
                </form>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const icons: Record<string, string> = {
    passed: '✅',
    failed: '❌',
    running: '⏳',
    skipped: '⏭️',
    waiting: '─',
  };

  const labels: Record<string, string> = {
    passed: 'Passed',
    failed: 'Failed',
    running: 'Running',
    skipped: 'Skipped',
    waiting: 'Waiting',
  };

  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-icon">{icons[status] || '─'}</span>
      <span className="status-label">{labels[status] || 'Waiting'}</span>
    </span>
  );
}
