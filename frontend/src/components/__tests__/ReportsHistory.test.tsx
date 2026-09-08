import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ReportsHistory } from '../ReportsHistory';
import { authenticatedFetch } from '../../api_client';

vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn()
}));

describe('ReportsHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders successfully with empty array', async () => {
    (authenticatedFetch as any).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([])
    });

    render(<ReportsHistory />);
    
    await waitFor(() => {
      expect(screen.getByText(/No previous reports found/i)).toBeInTheDocument();
    });
  });

  it('handles non-array data gracefully without crashing', async () => {
    // Simulate API returning an error object instead of an array
    (authenticatedFetch as any).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ error: 'Internal Server Error', code: 500 })
    });

    // We expect this NOT to throw an error now because of our safety checks
    render(<ReportsHistory />);

    // It should eventually show "No previous reports found" because filtered list is empty
    await waitFor(() => {
      expect(screen.getByText(/No previous reports found/i)).toBeInTheDocument();
    });
  });

  it('handles null data gracefully without crashing', async () => {
    (authenticatedFetch as any).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(null)
    });

    render(<ReportsHistory />);

    await waitFor(() => {
      expect(screen.getByText(/No previous reports found/i)).toBeInTheDocument();
    });
  });

  it('renders reports when provided', async () => {
    const reports = [
      {
        run_id: 'run-1',
        ticket_id: 'VQA-1',
        role: 'account_executive',
        role_label: 'Account Executive',
        timestamp: '2026-05-27T10:00:00Z',
        timestamp_display: 'May 27, 10:00 AM',
        label: 'VQA-1 · Account Executive',
        report_url: 'http://s3/report1.html',
        video_url: 'http://s3/video1.mp4'
      }
    ];

    (authenticatedFetch as any).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(reports)
    });

    render(<ReportsHistory />);

    await waitFor(() => {
      expect(screen.getByText('VQA-1')).toBeInTheDocument();
      expect(screen.getAllByText('Account Executive').length).toBeGreaterThan(0);
    });
  });
});
