/**
 * SelectView Tests — Phase 4 (TASK-065) + Phase 4 Environment Scoping (TASK-124)
 *
 * Covers requirements for:
 * - SELECT mode UI: ticket search, dropdowns, advanced settings.
 * - Auto-triggering preview on ticket selection.
 * - Per-product environment options rendered from activeProduct.environments.
 * - targetUrl auto-syncs to product default when active product changes.
 * - Stored targetUrl preserved when it belongs to the current product's environments.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SelectView } from '../SelectView';
import { authenticatedFetch } from '../../api_client';
import { ProductProvider } from '../../context/ProductContext';

// Mock api_client
vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn(),
}));

const mockTickets = [
  { id: 'VC-1', summary: 'Ticket 1', status: 'To Do', priority: 'Medium', issue_type: 'Story' },
  { id: 'VC-2', summary: 'Ticket 2', status: 'In Progress', priority: 'High', issue_type: 'Bug' },
];

describe('SelectView — Rendering & Loading', () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ matched: false, tests: [] }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTickets),
      } as Response);
    });
  });

  it('renders the "Start a New Test" header', async () => {
    render(<SelectView onTicketSelected={vi.fn()} onStaticTestSelected={vi.fn()} isLoading={false} onCheckCredentials={vi.fn()} />);
    expect(screen.getByText(/Start a New Test/i)).toBeInTheDocument();
  });

  it('loads and displays tickets in the dropdown', async () => {
    render(<SelectView onTicketSelected={vi.fn()} onStaticTestSelected={vi.fn()} isLoading={false} onCheckCredentials={vi.fn()} />);
    
    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    
    await waitFor(() => {
      expect(screen.getByText('Ticket 1')).toBeInTheDocument();
      expect(screen.getByText('Ticket 2')).toBeInTheDocument();
    });
  });
});

describe('SelectView — Ticket Selection', () => {
  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ matched: false, tests: [] }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTickets),
      } as Response);
    });
  });

  it('calls onTicketSelected when a ticket is clicked', async () => {
    const onTicketSelected = vi.fn();
    render(<SelectView onTicketSelected={onTicketSelected} onStaticTestSelected={vi.fn()} isLoading={false} onCheckCredentials={vi.fn()} />);
    
    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    
    await waitFor(() => screen.getByText('Ticket 1'));
    fireEvent.click(screen.getByText('Ticket 1'));
    
    await waitFor(() => {
      expect(onTicketSelected).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'VC-1' }),
        expect.any(Object)
      );
    });
  });
});

describe('SelectView — Playwright Match Banner', () => {
  const mockSingleMatch = {
    matched: true,
    tests: [
      {
        id: 'qa-170-test',
        file: 'playwright/tests/qa-170-search.test.ts',
        jira_keys: ['QA-170'],
        description: 'Single match test desc',
        steps_count: 2,
        step_names: ['Login', 'Search'],
      }
    ]
  };

  beforeEach(() => {
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockSingleMatch),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTickets),
      } as Response);
    });
  });

  it('renders match banner when static test is found', async () => {
    const onTicketSelected = vi.fn();
    const onStaticTestSelected = vi.fn();
    render(
      <SelectView
        onTicketSelected={onTicketSelected}
        onStaticTestSelected={onStaticTestSelected}
        isLoading={false}
        onCheckCredentials={vi.fn()}
      />
    );

    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    
    await waitFor(() => screen.getByText('Ticket 1'));
    fireEvent.click(screen.getByText('Ticket 1'));

    // Verify banner is shown
    const banner = await screen.findByTestId('playwright-match-banner');
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/Static Playwright test found/i)).toBeInTheDocument();
    expect(screen.getByText('QA 170 Search')).toBeInTheDocument();
    expect(screen.getByText('Single match test desc')).toBeInTheDocument();

    // Click Run Static Test
    const runBtn = screen.getByRole('button', { name: /Run Static Test/i });
    fireEvent.click(runBtn);
    expect(onStaticTestSelected).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'VC-1' }),
      expect.objectContaining({ id: 'qa-170-test' }),
      expect.any(Object)
    );

    // Verify onTicketSelected was NOT called yet
    expect(onTicketSelected).not.toHaveBeenCalled();
  });

  it('allows choosing to Use AI Agent Instead', async () => {
    const onTicketSelected = vi.fn();
    render(
      <SelectView
        onTicketSelected={onTicketSelected}
        onStaticTestSelected={vi.fn()}
        isLoading={false}
        onCheckCredentials={vi.fn()}
      />
    );

    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    
    await waitFor(() => screen.getByText('Ticket 1'));
    fireEvent.click(screen.getByText('Ticket 1'));

    await screen.findByTestId('playwright-match-banner');

    const aiLink = screen.getByRole('button', { name: /Use AI Agent Instead/i });
    fireEvent.click(aiLink);

    await waitFor(() => {
      expect(onTicketSelected).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'VC-1' }),
        expect.any(Object)
      );
    });
  });
});

describe('SelectView — Advanced Settings', () => {
  it('toggles Advanced Settings visibility via <details>', () => {
    render(<SelectView onTicketSelected={vi.fn()} onStaticTestSelected={vi.fn()} isLoading={false} onCheckCredentials={vi.fn()} />);

    const summary = screen.getByText(/Advanced Settings/i);
    expect(summary).toBeInTheDocument();

    // In JSDOM, <details> doesn't necessarily hide content without actual CSS,
    // but we can check if it exists in the DOM
    expect(screen.getByLabelText(/Use Custom Credentials/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Failed Login Testing/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// TASK-124 Phase 4: Per-Product Environment Scoping
// ---------------------------------------------------------------------------

/**
 * Helper: build a mock /products response with product-scoped environments.
 * The vtrade product has a single QA URL that differs from vpromedia's.
 */
function makeMultiProductResponse() {
  return [
    {
      slug: 'vpromedia',
      display_name: 'vProMedia',
      description: 'Broadcast platform.',
      order: 1,
      environments: { qa: 'https://two-test.vcreative.net' },
      default_environment: 'qa',
      jira_board_ids: [27, 36],
      roles: ['account_executive', 'sales_manager'],
    },
    {
      slug: 'vtrade',
      display_name: 'vTrade',
      description: 'Trade platform.',
      order: 2,
      environments: { qa: 'https://vtrade-qa.vcreative.net' },
      default_environment: 'qa',
      jira_board_ids: [],
      roles: ['vtrade_exec'],
    },
  ];
}

/**
 * Render SelectView inside a real ProductProvider so useProductContext() works.
 * The products list is populated via the mocked authenticatedFetch.
 */
function renderWithProductProvider(productSlug?: string) {
  if (productSlug) {
    localStorage.setItem('vqa_product', productSlug);
  }
  return render(
    <ProductProvider>
      <SelectView
        onTicketSelected={vi.fn()}
        onStaticTestSelected={vi.fn()}
        isLoading={false}
        onCheckCredentials={vi.fn()}
      />
    </ProductProvider>
  );
}

describe('SelectView — per-product environment options (TASK-124 Phase 4)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : String(url);
      if (urlStr.includes('/products')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeMultiProductResponse()),
        } as Response);
      }
      if (urlStr.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ matched: false, tests: [] }),
        } as Response);
      }
      // /tickets
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders environment options derived from the active product environments map', async () => {
    // Render with vtrade active so we see vtrade's environments
    renderWithProductProvider('vtrade');

    await waitFor(() => {
      // The env select should contain the vtrade QA URL, NOT the hardcoded
      // vpromedia options from the previous implementation
      const envSelect = screen.getByLabelText(/Environment/i);
      expect(envSelect).toBeInTheDocument();
      // vtrade's QA URL should be an option
      expect(envSelect).toHaveTextContent('vtrade-qa.vcreative.net');
    });
  });

  it('does NOT show hardcoded vpromedia URLs as options when vtrade is active', async () => {
    renderWithProductProvider('vtrade');

    await waitFor(() => {
      const envSelect = screen.getByLabelText(/Environment/i);
      // The old hardcoded "Two Test" option (two-test.vcreative.net) must not
      // appear when vtrade is the active product
      expect(envSelect).not.toHaveTextContent('two-test.vcreative.net');
    });
  });

  it('syncs targetUrl to product default when active product changes to vtrade', async () => {
    // Start with vpromedia URL stored from a previous session
    localStorage.setItem('vqa_targetUrl', 'https://two-test.vcreative.net');

    // Render with vtrade active (simulating a product switch)
    renderWithProductProvider('vtrade');

    await waitFor(() => {
      // After the product changes to vtrade, the env select must show vtrade's
      // default URL as the selected value — NOT the old stored vpromedia URL
      const envSelect = screen.getByLabelText(/Environment/i) as HTMLSelectElement;
      expect(envSelect.value).toBe('https://vtrade-qa.vcreative.net');
    });
  });

  it('keeps the stored targetUrl when it belongs to the current product environments', async () => {
    // Store vtrade's URL as if the user previously selected it
    localStorage.setItem('vqa_targetUrl', 'https://vtrade-qa.vcreative.net');
    localStorage.setItem('vqa_product', 'vtrade');

    renderWithProductProvider('vtrade');

    await waitFor(() => {
      // The stored URL is valid for vtrade — it should be preserved, not reset
      const envSelect = screen.getByLabelText(/Environment/i) as HTMLSelectElement;
      expect(envSelect.value).toBe('https://vtrade-qa.vcreative.net');
    });
  });
});

// ---------------------------------------------------------------------------
// TASK-124 Phase 5: Per-Product Playwright Test Organization
// ---------------------------------------------------------------------------

describe('SelectView — product-scoped Playwright match (TASK-124 Phase 5)', () => {
  /**
   * After Phase 5, handleSelectTicket() must append ?product={productSlug} to
   * the /playwright/match/{ticket_id} fetch. These tests verify the URL passed
   * to authenticatedFetch contains the correct product query parameter.
   */

  const mockTicketsPhase5 = [
    { id: 'QA-100', summary: 'Script Library', status: 'To Do', priority: 'Medium', issue_type: 'Story' },
    { id: 'QA-101', summary: 'Client Merging', status: 'To Do', priority: 'High', issue_type: 'Story' },
  ];

  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('includes ?product=vpromedia in the /playwright/match URL when vpromedia is active', async () => {
    // Arrange: vpromedia is the active product
    localStorage.setItem('vqa_product', 'vpromedia');

    const capturedUrls: string[] = [];
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : String(url);
      capturedUrls.push(urlStr);

      if (urlStr.includes('/products')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeMultiProductResponse()),
        } as Response);
      }
      if (urlStr.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ matched: false, tests: [] }),
        } as Response);
      }
      // /tickets
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTicketsPhase5),
      } as Response);
    });

    render(
      <ProductProvider>
        <SelectView
          onTicketSelected={vi.fn()}
          onStaticTestSelected={vi.fn()}
          isLoading={false}
          onCheckCredentials={vi.fn()}
        />
      </ProductProvider>
    );

    // Act: open dropdown and select a ticket
    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    await waitFor(() => screen.getByText('Script Library'));
    fireEvent.click(screen.getByText('Script Library'));

    // Assert: the /playwright/match/ call included ?product=vpromedia
    await waitFor(() => {
      const matchCalls = capturedUrls.filter((u) => u.includes('/playwright/match/'));
      expect(matchCalls.length).toBeGreaterThan(0);
      const matchUrl = matchCalls[matchCalls.length - 1];
      expect(matchUrl).toContain('product=vpromedia');
    });
  });

  it('includes ?product=vtrade in the /playwright/match URL when vtrade is active', async () => {
    // Arrange: vtrade is the active product
    localStorage.setItem('vqa_product', 'vtrade');

    const capturedUrls: string[] = [];
    vi.mocked(authenticatedFetch).mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : String(url);
      capturedUrls.push(urlStr);

      if (urlStr.includes('/products')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeMultiProductResponse()),
        } as Response);
      }
      if (urlStr.includes('/playwright/match/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ matched: false, tests: [] }),
        } as Response);
      }
      // /tickets — return vtrade-style empty list (vtrade has no Jira boards)
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTicketsPhase5),
      } as Response);
    });

    render(
      <ProductProvider>
        <SelectView
          onTicketSelected={vi.fn()}
          onStaticTestSelected={vi.fn()}
          isLoading={false}
          onCheckCredentials={vi.fn()}
        />
      </ProductProvider>
    );

    // Act: open dropdown and select a ticket
    const input = await screen.findByPlaceholderText(/Search by ticket ID or title/i);
    fireEvent.focus(input);
    await waitFor(() => screen.getByText('Script Library'));
    fireEvent.click(screen.getByText('Script Library'));

    // Assert: the /playwright/match/ call included ?product=vtrade
    await waitFor(() => {
      const matchCalls = capturedUrls.filter((u) => u.includes('/playwright/match/'));
      expect(matchCalls.length).toBeGreaterThan(0);
      const matchUrl = matchCalls[matchCalls.length - 1];
      expect(matchUrl).toContain('product=vtrade');
    });
  });
});
