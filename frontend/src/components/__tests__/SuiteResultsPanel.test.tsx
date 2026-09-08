import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SuiteResultsPanel } from '../SuiteResultsPanel';
import type { PlaywrightSuiteReportResponse } from '../../types';
import { authenticatedFetch } from '../../api_client';

vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn(),
}));

// Mock API_BASE_URL
vi.mock('../../types', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../types')>();
  return {
    ...actual,
    API_BASE_URL: 'http://localhost:8000',
  };
});

const mockReport: PlaywrightSuiteReportResponse = {
  suite_run_id: "suite-test-123",
  status: "completed",
  started_at: "2026-06-09T12:00:00Z",
  completed_at: "2026-06-09T12:00:15Z",
  total: 3,
  passed: 2,
  failed: 1,
  results: [
    {
      test_id: "qa-100",
      name: "QA-100 Test",
      status: "PASS",
      duration_ms: 5000,
      error_snippet: null,
    },
    {
      test_id: "qa-101",
      name: "QA-101 Test",
      status: "PASS",
      duration_ms: 7000,
      error_snippet: null,
    },
    {
      test_id: "qa-102",
      name: "QA-102 Test",
      status: "FAIL",
      duration_ms: 3000,
      error_snippet: "TimeoutError: Execution exceeded 180 seconds",
    }
  ],
  outcome: "FAIL",
  fail_reason: "Failed tests: qa-102 (TimeoutError: Execution exceeded 180 seconds)"
};

describe('SuiteResultsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    
    // Mock navigator.clipboard
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
      writable: true,
      configurable: true,
    });
  });
  it('renders KPI summary elements with correct numbers', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    expect(screen.getByTestId('kpi-total')).toHaveTextContent('3');
    expect(screen.getByTestId('kpi-passed')).toHaveTextContent('2');
    expect(screen.getByTestId('kpi-failed')).toHaveTextContent('1');
    expect(screen.getByTestId('kpi-duration')).toHaveTextContent('15.0s');
  });

  it('renders table rows for all tests in the report', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    expect(screen.getByText('QA-100 Test')).toBeInTheDocument();
    expect(screen.getByText('QA-101 Test')).toBeInTheDocument();
    expect(screen.getByText('QA-102 Test')).toBeInTheDocument();

    // Verifying badge texts
    const passBadges = screen.getAllByText('PASS');
    expect(passBadges.length).toBe(2);
    expect(screen.getByText('FAIL')).toBeInTheDocument();
  });

  it('toggles expansion of failed row on click to show error details', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    // Error details should not be visible initially
    expect(screen.queryByTestId('error-snippet')).not.toBeInTheDocument();

    // Click failed row
    const failedRow = screen.getByText('QA-102 Test').closest('tr');
    expect(failedRow).toBeInTheDocument();
    if (failedRow) {
      fireEvent.click(failedRow);
    }

    // Now error details should be visible
    expect(screen.getByTestId('error-snippet')).toBeInTheDocument();
    expect(screen.getByTestId('error-snippet')).toHaveTextContent(/TimeoutError: Execution exceeded 180 seconds/);

    // Click failed row again to collapse
    if (failedRow) {
      fireEvent.click(failedRow);
    }
    expect(screen.queryByTestId('error-snippet')).not.toBeInTheDocument();
  });

  it('calls onBack when back button is clicked', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    const backButton = screen.getByRole('button', { name: /return to library/i });
    fireEvent.click(backButton);

    expect(onBackMock).toHaveBeenCalledOnce();
  });

  it('renders overall FAIL outcome banner with fail_reason', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    expect(screen.getByTestId('overall-outcome-banner')).toBeInTheDocument();
    expect(screen.getByText(/SUITE RUN FAILED/)).toBeInTheDocument();
    expect(screen.getByText(/Failed tests: qa-102/)).toBeInTheDocument();
  });

  it('renders overall PASS outcome banner without fail_reason', () => {
    const onBackMock = vi.fn();
    const passReport: PlaywrightSuiteReportResponse = {
      ...mockReport,
      failed: 0,
      passed: 3,
      outcome: "PASS",
      fail_reason: null,
      results: mockReport.results.map(r => ({ ...r, status: "PASS" }))
    };
    render(<SuiteResultsPanel report={passReport} onBack={onBackMock} />);

    expect(screen.getByTestId('overall-outcome-banner')).toBeInTheDocument();
    expect(screen.getByText(/SUITE RUN PASSED/)).toBeInTheDocument();
    expect(screen.queryByText(/Failed tests:/)).not.toBeInTheDocument();
  });

  it('hides the Heal Tests button when failed count is 0', () => {
    const onBackMock = vi.fn();
    const passReport: PlaywrightSuiteReportResponse = {
      ...mockReport,
      failed: 0,
      passed: 3,
      outcome: "PASS",
      fail_reason: null,
      results: mockReport.results.map(r => ({ ...r, status: "PASS" }))
    };
    render(<SuiteResultsPanel report={passReport} onBack={onBackMock} />);
    expect(screen.queryByTestId('heal-tests-btn')).not.toBeInTheDocument();
  });

  it('shows the Heal Tests button when failed count is greater than 0', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);
    expect(screen.getByTestId('heal-tests-btn')).toBeInTheDocument();
  });

  it('triggers heal prompt compilation and displays results in Modal', async () => {
    const onBackMock = vi.fn();
    const mockPromptResponse = { prompt: "compiled healing prompt markdown" };
    
    vi.mocked(authenticatedFetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockPromptResponse,
    } as Response);

    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    const healBtn = screen.getByTestId('heal-tests-btn');
    fireEvent.click(healBtn);

    // Should call API
    expect(authenticatedFetch).toHaveBeenCalledWith(
      'http://localhost:8000/playwright/heal-prompt',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ run_id: mockReport.suite_run_id }),
      })
    );

    // Wait for modal to open
    await waitFor(() => {
      expect(screen.getByTestId('heal-modal')).toBeInTheDocument();
    });

    expect(screen.getByTestId('heal-prompt-textarea')).toHaveValue("compiled healing prompt markdown");

    // Copy to clipboard click
    const copyBtn = screen.getByTestId('copy-prompt-btn');
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("compiled healing prompt markdown");
    
    await waitFor(() => {
      expect(copyBtn).toHaveTextContent(/Copied!/);
    });

    // Close modal
    const closeBtn = screen.getByTestId('modal-close-x');
    fireEvent.click(closeBtn);
    expect(screen.queryByTestId('heal-modal')).not.toBeInTheDocument();
  });

  it('renders the ❌ Failure Summary panel and displays failed tests correctly with dynamic/fallback digest', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    // The failure summary panel should be visible
    expect(screen.getByTestId('failure-summary-panel')).toBeInTheDocument();
    expect(screen.getByTestId('failure-summary-header')).toBeInTheDocument();
    
    // Should list the failed test from mockReport
    expect(screen.getByTestId('failure-summary-list')).toBeInTheDocument();
    expect(screen.getByTestId('failure-item-qa-102')).toBeInTheDocument();
    expect(screen.getByText(/#1 — QA-102 Test \(qa-102\)/)).toBeInTheDocument();
    expect(screen.getByTestId('failure-item-qa-102')).toHaveTextContent(/TimeoutError: Execution exceeded 180 seconds/);
  });

  it('allows collapsing and expanding the failure summary panel', () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    // Starts expanded by default
    expect(screen.getByTestId('failure-summary-list')).toBeInTheDocument();

    // Click header to collapse
    const header = screen.getByTestId('failure-summary-header');
    fireEvent.click(header);

    // List should not be rendered when collapsed
    expect(screen.queryByTestId('failure-summary-list')).not.toBeInTheDocument();

    // Click again to expand
    fireEvent.click(header);
    expect(screen.getByTestId('failure-summary-list')).toBeInTheDocument();
  });

  it('copies formatted plain text to clipboard when copy button is clicked', async () => {
    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    const copyBtn = screen.getByTestId('copy-summary-btn');
    fireEvent.click(copyBtn);

    // Verify correct string is copied: "1. QA-102 Test: TimeoutError: Execution exceeded 180 seconds"
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "1. QA-102 Test: TimeoutError: Execution exceeded 180 seconds"
    );

    // Verify "Copied!" badge is shown temporarily
    await waitFor(() => {
      expect(screen.getByTestId('copied-badge')).toBeInTheDocument();
    });
    expect(screen.getByTestId('copied-badge')).toHaveTextContent('Copied!');
  });

  it('uses off-screen textarea copy fallback when navigator.clipboard is unavailable', () => {
    // Temporarily delete navigator.clipboard to trigger fallback
    const originalClipboard = navigator.clipboard;
    // @ts-expect-error - navigator.clipboard is read-only and needs to be deleted to mock insecure context fallback
    delete navigator.clipboard;

    // Spy on document.execCommand
    const mockExec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      value: mockExec,
      writable: true,
      configurable: true,
    });

    const onBackMock = vi.fn();
    render(<SuiteResultsPanel report={mockReport} onBack={onBackMock} />);

    const copyBtn = screen.getByTestId('copy-summary-btn');
    fireEvent.click(copyBtn);

    // Verify execCommand('copy') is called
    expect(mockExec).toHaveBeenCalledWith('copy');
    expect(screen.getByTestId('copied-badge')).toHaveTextContent('Copied!');

    // Restore clipboard
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      writable: true,
      configurable: true,
    });
  });
});
