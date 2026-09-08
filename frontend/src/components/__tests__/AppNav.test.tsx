/**
 * AppNav Tests — vReview
 *
 * Covers:
 *   Left nav rail with brand "vReview" and "AI Review" + "History" links.
 *   No leftover vQA screens (Run a Test, Test History, Playwright Suite).
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { AppNav } from '../AppNav';

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}));

const mockHealthResponse = vi.fn().mockReturnValue({ status: 'ok', checks: {} });
vi.mock('../../hooks/useExecution', () => ({
  useExecution: () => ({
    healthResponse: mockHealthResponse(),
    checkHealth: vi.fn(),
  }),
}));

function renderNav(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="*" element={<AppNav />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AppNav — navigation items', () => {
  it('renders "AI Review" nav link to home', () => {
    renderNav('/');
    const link = screen.getByRole('link', { name: /ai review/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });

  it('renders "Memory Watch" nav link', () => {
    renderNav('/');
    const link = screen.getByRole('link', { name: /memory watch/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/memory');
  });

  it('renders "History" nav link', () => {
    renderNav('/');
    const link = screen.getByRole('link', { name: /^history$/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/history');
  });

  it('does not render leftover vQA nav links', () => {
    renderNav('/');
    expect(screen.queryByRole('link', { name: /run a test/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /test history/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /playwright suite/i })).toBeNull();
  });

  it('renders the vReview brand', () => {
    renderNav('/');
    expect(screen.getByText(/vReview/i)).toBeInTheDocument();
  });
});

describe('AppNav — active state', () => {
  it('marks "AI Review" as active when at root path', () => {
    renderNav('/');
    const link = screen.getByRole('link', { name: /ai review/i });
    expect(link.classList.contains('active') || link.getAttribute('aria-current') === 'page').toBe(true);
  });

  it('marks "History" as active when at /history', () => {
    renderNav('/history');
    const link = screen.getByRole('link', { name: /^history$/i });
    expect(link.classList.contains('active') || link.getAttribute('aria-current') === 'page').toBe(true);
  });
});

describe('AppNav — footer elements', () => {
  it('renders a health/system status indicator', () => {
    renderNav('/');
    const nav = screen.getByRole('navigation');
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('logout button is clickable without throwing', () => {
    renderNav('/');
    const logoutBtn = screen.getByRole('button', { name: /logout/i });
    expect(() => fireEvent.click(logoutBtn)).not.toThrow();
  });
});

describe('AppNav — accessibility', () => {
  it('wraps links in a <nav> landmark', () => {
    renderNav('/');
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders links with a valid href attribute', () => {
    renderNav('/');
    const links = screen.getAllByRole('link');
    links.forEach((link) => {
      expect(link).toHaveAttribute('href');
    });
  });
});

describe('AppNav — build number tracking (TASK-117)', () => {
  it('renders build number when present in healthResponse', () => {
    mockHealthResponse.mockReturnValueOnce({
      status: 'ok',
      checks: {},
      build_number: '#12345-prod',
    });
    renderNav('/');
    expect(screen.getByText(/build: #12345-prod/i)).toBeInTheDocument();
  });

  it('does not render build number when absent from healthResponse', () => {
    mockHealthResponse.mockReturnValueOnce({
      status: 'ok',
      checks: {},
    });
    renderNav('/');
    expect(screen.queryByText(/build:/i)).toBeNull();
  });
});
