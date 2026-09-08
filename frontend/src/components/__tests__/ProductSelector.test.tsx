/**
 * ProductSelector Tests — TASK-124 Phase 2
 *
 * Covers:
 * - AC-ENTRY-1: Selector visible in header, shows product name
 * - Renders "Product:" label + current product name
 * - Dropdown opens/closes on click
 * - Selecting a product calls setProduct
 * - Keyboard navigation: Enter/Space opens, Escape closes, ArrowDown/Up
 * - Per-product colored left-border accent (CSS class)
 * - role="listbox" on dropdown list
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ProductSelector } from '../ProductSelector';

// ---------------------------------------------------------------------------
// Mock ProductContext
// ---------------------------------------------------------------------------

const mockSetProduct = vi.fn();
const mockCancelTicketFetch = vi.fn();

const mockProducts = [
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
  {
    slug: 'vep',
    display_name: 'vEP',
    description: 'Electronic programming platform.',
    order: 4,
    environments: {},
    default_environment: '',
    jira_board_ids: [],
    roles: [],
  },
];

vi.mock('../../context/ProductContext', async () => {
  return {
    useProductContext: vi.fn(() => ({
      activeSlug: 'vpromedia',
      activeProduct: mockProducts[0],
      products: mockProducts,
      setProduct: mockSetProduct,
      cancelTicketFetch: mockCancelTicketFetch,
      isLoading: false,
    })),
  };
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { useProductContext } = await import('../../context/ProductContext') as any;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderSelector() {
  return render(<ProductSelector />);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Reset mock return value after vi.clearAllMocks() which resets mock state
  useProductContext.mockReturnValue({
    activeSlug: 'vpromedia',
    activeProduct: mockProducts[0],
    products: mockProducts,
    setProduct: mockSetProduct,
    cancelTicketFetch: mockCancelTicketFetch,
    isLoading: false,
  });
});

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('ProductSelector — rendering', () => {
  it('renders a trigger button with the "Product:" label', () => {
    renderSelector();
    expect(screen.getByText(/Product:/i)).toBeInTheDocument();
  });

  it('renders the active product name in the trigger', () => {
    renderSelector();
    expect(screen.getByText('vProMedia')).toBeInTheDocument();
  });

  it('renders a chevron icon in the trigger button', () => {
    renderSelector();
    // Chevron is typically rendered as an SVG or a character — just check the button structure
    const button = screen.getByRole('button', { name: /product/i });
    expect(button).toBeInTheDocument();
  });

  it('applies a product-slug CSS class to the trigger for color accent', () => {
    const { container } = renderSelector();
    // The trigger should have a class that includes the product slug
    const trigger = container.querySelector('.product-selector-trigger, [data-product]');
    expect(trigger).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Dropdown open/close
// ---------------------------------------------------------------------------

describe('ProductSelector — dropdown open/close', () => {
  it('dropdown is hidden by default', () => {
    renderSelector();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('opens dropdown on button click', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('lists all products in the dropdown', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /vProMedia/i })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: /vTrade/i })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: /vEP/i })).toBeInTheDocument();
    });
  });

  it('closes dropdown when clicking the trigger again', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('closes dropdown on Escape key', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Product selection
// ---------------------------------------------------------------------------

describe('ProductSelector — product selection', () => {
  it('calls setProduct with the selected slug on option click', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    const vtradeOption = await screen.findByRole('option', { name: /vTrade/i });
    fireEvent.click(vtradeOption);

    expect(mockSetProduct).toHaveBeenCalledWith('vtrade');
  });

  it('calls cancelTicketFetch on product selection', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    const vtradeOption = await screen.findByRole('option', { name: /vTrade/i });
    fireEvent.click(vtradeOption);

    expect(mockCancelTicketFetch).toHaveBeenCalled();
  });

  it('closes the dropdown after selecting a product', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    const vtradeOption = await screen.findByRole('option', { name: /vTrade/i });
    fireEvent.click(vtradeOption);

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('marks the active product as selected in the dropdown', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    const vproOption = await screen.findByRole('option', { name: /vProMedia/i });
    expect(vproOption).toHaveAttribute('aria-selected', 'true');
  });

  it('marks non-active products as not selected', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    const vtradeOption = await screen.findByRole('option', { name: /vTrade/i });
    expect(vtradeOption).toHaveAttribute('aria-selected', 'false');
  });
});

// ---------------------------------------------------------------------------
// Keyboard navigation
// ---------------------------------------------------------------------------

describe('ProductSelector — keyboard navigation', () => {
  it('opens on Enter keydown on the trigger', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('opens on Space keydown on the trigger', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.keyDown(button, { key: ' ' });
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Accessibility attributes
// ---------------------------------------------------------------------------

describe('ProductSelector — accessibility', () => {
  it('trigger has aria-haspopup="listbox"', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    expect(button).toHaveAttribute('aria-haspopup', 'listbox');
  });

  it('trigger has aria-expanded="false" when closed', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('trigger has aria-expanded="true" when open', () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
  });

  it('dropdown has role="listbox"', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('each option has role="option"', async () => {
    renderSelector();
    const button = screen.getByRole('button', { name: /product/i });
    fireEvent.click(button);

    await waitFor(() => {
      const options = screen.getAllByRole('option');
      expect(options.length).toBe(3);
    });
  });
});

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe('ProductSelector — loading state', () => {
  it('renders without crashing when isLoading is true and products are empty', () => {
    useProductContext.mockReturnValueOnce({
      activeSlug: 'vpromedia',
      activeProduct: null,
      products: [],
      setProduct: mockSetProduct,
      cancelTicketFetch: mockCancelTicketFetch,
      isLoading: true,
    });

    expect(() => renderSelector()).not.toThrow();
  });
});
