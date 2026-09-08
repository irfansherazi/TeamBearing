/**
 * PlaywrightLibrary Tests — TASK-124 Phase 5
 *
 * Covers:
 * - Renders loading state initially
 * - After fetch resolves, renders a test entry
 * - Calls /playwright/tests?product=vpromedia when productSlug is vpromedia
 * - Calls /playwright/tests?product=vtrade when productSlug is vtrade
 * - Re-fetches when product changes (dependency on activeSlug)
 *
 * ALL TESTS SHOULD FAIL until Phase 5 implementation is complete (TDD RED phase).
 * Failure reasons:
 *   - PlaywrightLibrary currently calls `/playwright/tests` with no product param
 *   - PlaywrightLibrary does not use useProductContext() yet
 *   - Re-fetch on product change is not implemented
 */

import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PlaywrightLibrary } from '../PlaywrightLibrary';
import { authenticatedFetch } from '../../api_client';

// ---------------------------------------------------------------------------
// Mock dependencies
// ---------------------------------------------------------------------------

vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn(),
}));

// Mock useProductContext — starts as vpromedia by default
const mockUseProductContext = vi.fn();

vi.mock('../../context/ProductContext', () => ({
  useProductContext: () => mockUseProductContext(),
}));

// ---------------------------------------------------------------------------
// Sample test data (post-Phase-5 paths)
// ---------------------------------------------------------------------------

const sampleVpromediaTests = [
  {
    id: 'qa-100-script-library.test',
    file: 'tests/vpromedia/qa-100-script-library.test.ts',
    display_name: 'QA 100 Script Library',
    jira_keys: ['QA-100'],
    description: 'QA-100: Script Library',
    steps_count: 4,
    step_names: ['Phase 1 & 2: Send script to library'],
  },
  {
    id: 'qa-101-client-merging.test',
    file: 'tests/vpromedia/qa-101-client-merging.test.ts',
    display_name: 'QA 101 Client Merging',
    jira_keys: ['QA-101'],
    description: 'QA-101: Client Merging',
    steps_count: 6,
    step_names: ['Ensure'],
  },
];

const sampleVtradeTests = [
  {
    id: 'vt-001-trade-order.test',
    file: 'tests/vtrade/vt-001-trade-order.test.ts',
    display_name: 'VT 001 Trade Order',
    jira_keys: ['VT-1'],
    description: 'VT-001: Trade Order',
    steps_count: 2,
    step_names: ['Login', 'Create Order'],
  },
];

// ---------------------------------------------------------------------------
// Default context values
// ---------------------------------------------------------------------------

function makeProductContext(slug = 'vpromedia') {
  return {
    activeSlug: slug,
    activeProduct: {
      slug,
      display_name: slug === 'vpromedia' ? 'vProMedia' : 'vTrade',
      description: 'Test product.',
      order: 1,
      environments: { qa: 'https://example.vcreative.net' },
      default_environment: 'qa',
      jira_board_ids: [],
      roles: [],
    },
    products: [],
    setProduct: vi.fn(),
    cancelTicketFetch: vi.fn(),
    isLoading: false,
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Default: vpromedia context
  mockUseProductContext.mockReturnValue(makeProductContext('vpromedia'));
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PlaywrightLibrary — TASK-124 Phase 5', () => {
  it('renders loading state initially before fetch resolves', () => {
    // Arrange: fetch never resolves during this test
    vi.mocked(authenticatedFetch).mockReturnValue(new Promise(() => undefined));

    render(
      <PlaywrightLibrary
        onSelect={vi.fn()}
        selectedTestId={null}
      />
    );

    // Assert: loading indicator is shown
    expect(screen.getByText(/Loading Playwright library/i)).toBeInTheDocument();
  });

  it('renders a test card after fetch resolves with vpromedia tests', async () => {
    // Arrange
    vi.mocked(authenticatedFetch).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(sampleVpromediaTests),
    } as Response);

    render(
      <PlaywrightLibrary
        onSelect={vi.fn()}
        selectedTestId={null}
      />
    );

    // Assert: at least one test card is rendered after loading
    await waitFor(() => {
      expect(screen.queryByText(/Loading Playwright library/i)).not.toBeInTheDocument();
    });
    // The test names should appear (formatted via getTestDisplayName)
    // We check for the qa-100 test ID which is always in the card
    expect(screen.getByText('qa-100-script-library.test')).toBeInTheDocument();
  });

  it('calls /playwright/tests?product=vpromedia when productSlug is vpromedia', async () => {
    // Arrange
    mockUseProductContext.mockReturnValue(makeProductContext('vpromedia'));

    const capturedUrls: string[] = [];
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      capturedUrls.push(typeof url === 'string' ? url : String(url));
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(sampleVpromediaTests),
      } as Response);
    });

    render(
      <PlaywrightLibrary
        onSelect={vi.fn()}
        selectedTestId={null}
      />
    );

    // Assert: the fetch URL includes ?product=vpromedia
    await waitFor(() => {
      expect(capturedUrls.length).toBeGreaterThan(0);
    });

    const testsFetchUrl = capturedUrls.find((u) => u.includes('/playwright/tests'));
    expect(testsFetchUrl).toBeDefined();
    expect(testsFetchUrl).toContain('product=vpromedia');
  });

  it('calls /playwright/tests?product=vtrade when productSlug is vtrade', async () => {
    // Arrange
    mockUseProductContext.mockReturnValue(makeProductContext('vtrade'));

    const capturedUrls: string[] = [];
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      capturedUrls.push(typeof url === 'string' ? url : String(url));
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(sampleVtradeTests),
      } as Response);
    });

    render(
      <PlaywrightLibrary
        onSelect={vi.fn()}
        selectedTestId={null}
      />
    );

    // Assert: the fetch URL includes ?product=vtrade
    await waitFor(() => {
      expect(capturedUrls.length).toBeGreaterThan(0);
    });

    const testsFetchUrl = capturedUrls.find((u) => u.includes('/playwright/tests'));
    expect(testsFetchUrl).toBeDefined();
    expect(testsFetchUrl).toContain('product=vtrade');
  });

  it('re-fetches when the active product changes from vpromedia to vtrade', async () => {
    // Arrange: start with vpromedia
    mockUseProductContext.mockReturnValue(makeProductContext('vpromedia'));

    let fetchCallCount = 0;
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : String(url);
      fetchCallCount++;
      if (urlStr.includes('product=vpromedia')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(sampleVpromediaTests),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(sampleVtradeTests),
      } as Response);
    });

    const { rerender } = render(
      <PlaywrightLibrary
        onSelect={vi.fn()}
        selectedTestId={null}
      />
    );

    // Wait for initial fetch to complete
    await waitFor(() => {
      expect(fetchCallCount).toBeGreaterThanOrEqual(1);
    });

    const initialCallCount = fetchCallCount;

    // Act: switch product to vtrade
    mockUseProductContext.mockReturnValue(makeProductContext('vtrade'));

    await act(async () => {
      rerender(
        <PlaywrightLibrary
          onSelect={vi.fn()}
          selectedTestId={null}
        />
      );
    });

    // Assert: a new fetch was triggered after the product change
    await waitFor(() => {
      expect(fetchCallCount).toBeGreaterThan(initialCallCount);
    });

    // Confirm the re-fetch used the vtrade product param
    // (The last fetch URL should contain product=vtrade)
    const allCalls = vi.mocked(authenticatedFetch).mock.calls;
    const lastCallUrl = allCalls[allCalls.length - 1][0] as string;
    expect(lastCallUrl).toContain('product=vtrade');
  });
});
