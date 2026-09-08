/**
 * GhostCredentialPanel Tests — Phase 2 (TASK-125)
 *
 * Covers requirements for:
 * - AC-HAPPY-1: Panel renders credential form immediately on mount (no auto-submit)
 * - AC-HAPPY-2: Submit path POSTs admin credentials to /runs/{run_id}/ghost-credentials
 * - Dismiss path fires onDismiss callback when cancel button is clicked
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import GhostCredentialPanel from '../GhostCredentialPanel';
import type { WSGhostCredentialsMessage } from '../../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockMessage: WSGhostCredentialsMessage = {
  type: 'GHOST_CREDENTIALS_REQUIRED',
  run_id: 'run-abc123',
  message: 'Ghost login required for this test step.',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess() {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  } as Response);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('GhostCredentialPanel — render on mount', () => {
  it('renders the credential form immediately without auto-submitting on mount', () => {
    // No fetch mock installed — if any fetch fires on mount, the test will
    // still pass (fetch would be undefined and throw), but the assertion
    // confirms the form is visible before any user interaction.
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy;

    render(
      <GhostCredentialPanel message={mockMessage} />
    );

    // Form fields must be immediately visible
    expect(screen.getByLabelText(/admin email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /submit admin credentials/i })).toBeInTheDocument();

    // No fetch should have been triggered on mount
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('GhostCredentialPanel — submit path', () => {
  beforeEach(() => {
    mockFetchSuccess();
  });

  it('POSTs admin credentials to the ghost-credentials endpoint on submit', async () => {
    const onSubmitted = vi.fn();

    render(
      <GhostCredentialPanel message={mockMessage} onSubmitted={onSubmitted} />
    );

    fireEvent.change(screen.getByLabelText(/admin email/i), {
      target: { value: 'admin@vpromedia.com' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'secret123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /submit admin credentials/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/runs/run-abc123/ghost-credentials'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ email: 'admin@vpromedia.com', password: 'secret123' }),
        })
      );
      expect(onSubmitted).toHaveBeenCalledTimes(1);
    });
  });
});

describe('GhostCredentialPanel — dismiss path', () => {
  it('fires onDismiss when the close button is clicked', () => {
    const onDismiss = vi.fn();

    render(
      <GhostCredentialPanel message={mockMessage} onDismiss={onDismiss} />
    );

    const closeButton = screen.getByRole('button', { name: /dismiss admin credential panel/i });
    fireEvent.click(closeButton);

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
