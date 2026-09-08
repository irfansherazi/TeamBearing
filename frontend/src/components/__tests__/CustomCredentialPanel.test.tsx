/**
 * CustomCredentialPanel Tests — (custom-creds-prompt-when-required)
 *
 * Mirrors GhostCredentialPanel.test.tsx for the Custom-credentials sibling.
 * Covers:
 * - AC-HAPPY-1: Panel renders email + password inputs on mount (no auto-submit)
 * - AC-HAPPY-2: Save fires onSave with trimmed email + password
 * - AC-DISMISS: Dismiss fires onDismiss without calling onSave
 * - AC-VALIDATION: Submit is blocked when fields are empty
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CustomCredentialPanel from '../CustomCredentialPanel';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CustomCredentialPanel — render on mount', () => {
  it('renders email and password inputs immediately without auto-saving', () => {
    const onSave = vi.fn();

    render(<CustomCredentialPanel onSave={onSave} />);

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save.*credentials/i })).toBeInTheDocument();

    expect(onSave).not.toHaveBeenCalled();
  });
});

describe('CustomCredentialPanel — save path', () => {
  it('calls onSave with trimmed email and password when the form is submitted', () => {
    const onSave = vi.fn();

    render(<CustomCredentialPanel onSave={onSave} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: '  user@example.com  ' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'hunter2' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save.*credentials/i }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith('user@example.com', 'hunter2');
  });
});

describe('CustomCredentialPanel — dismiss path', () => {
  it('fires onDismiss and does not call onSave when the close button is clicked', () => {
    const onSave = vi.fn();
    const onDismiss = vi.fn();

    render(<CustomCredentialPanel onSave={onSave} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole('button', { name: /dismiss.*credential/i }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe('CustomCredentialPanel — validation', () => {
  it('disables the save button when email is empty', () => {
    render(<CustomCredentialPanel onSave={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'hunter2' },
    });

    expect(screen.getByRole('button', { name: /save.*credentials/i })).toBeDisabled();
  });

  it('disables the save button when password is empty', () => {
    render(<CustomCredentialPanel onSave={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'user@example.com' },
    });

    expect(screen.getByRole('button', { name: /save.*credentials/i })).toBeDisabled();
  });
});
