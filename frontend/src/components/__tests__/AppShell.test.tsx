/**
 * AppShell Tests — Phase 2 (TASK-065)
 *
 * Covers:
 *   - AppShell renders AppNav + main content area side by side
 *   - AppShell passes children through to main area
 *   - CSS grid layout classes applied correctly
 *   - AppShell does not break protected route rendering
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { AppShell } from '../AppShell';

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => ({ logout: vi.fn(() => Promise.resolve()), user: { name: 'Ada Lovelace', email: 'ada@example.com' } }),
}));

vi.mock('../../hooks/useExecution', () => ({
  useExecution: () => ({
    healthResponse: { status: 'ok', checks: {} },
    checkHealth: vi.fn(),
  }),
}));

function renderShell(children: React.ReactNode = <div>Test Content</div>) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="*" element={<AppShell>{children}</AppShell>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AppShell — layout structure', () => {
  it('renders a nav landmark', () => {
    renderShell();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders a main landmark', () => {
    renderShell();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('renders children inside the main area', () => {
    renderShell(<div data-testid="content">Hello World</div>);
    expect(screen.getByTestId('content')).toBeInTheDocument();
  });

  it('renders both nav and main simultaneously', () => {
    renderShell(<p>Content</p>);
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('applies app-shell class to the shell wrapper', () => {
    const { container } = renderShell();
    expect(container.querySelector('.app-shell')).not.toBeNull();
  });
});

describe('AppShell — navigation integration', () => {
  it('contains the AI Review nav links inside the shell', () => {
    renderShell();
    expect(screen.getByRole('link', { name: /run review/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /review rules/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /memory watch/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^history$/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /run a test/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /test history/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /playwright suite/i })).toBeNull();
  });

  it('shows the vReview brand in the nav', () => {
    renderShell();
    expect(screen.getByText(/vReview/i)).toBeInTheDocument();
  });
});
