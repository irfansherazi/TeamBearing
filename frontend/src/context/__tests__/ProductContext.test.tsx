/**
 * ProductContext Tests — TASK-124 Phase 2
 *
 * Covers:
 * - AC-ENTRY-1: Selector defaults to vpromedia
 * - AC-ENTRY-2: Persists across reloads (localStorage)
 * - AC-ERROR-1: Corrupt localStorage slug falls back to vpromedia
 * - AC-ASYNC-1: In-flight fetch cancelled on product switch
 * - Hook exposes correct shape
 * - setProduct updates context and localStorage
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { ProductProvider, useProductContext } from '../ProductContext';
import { authenticatedFetch } from '../../api_client';

vi.mock('../../api_client', () => ({
  authenticatedFetch: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeProductsResponse() {
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

function wrapper({ children }: { children: React.ReactNode }) {
  return <ProductProvider>{children}</ProductProvider>;
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(authenticatedFetch).mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(makeProductsResponse()),
  } as Response);
});

afterEach(() => {
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// AC-ENTRY-1: Default product is vpromedia
// ---------------------------------------------------------------------------

describe('ProductContext — default product', () => {
  it('defaults active product to vpromedia when localStorage is empty', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    // Initial slug before products load
    expect(result.current.activeSlug).toBe('vpromedia');
  });

  it('loads products list from /products on mount', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      // Let effects run
      await new Promise(r => setTimeout(r, 0));
    });

    expect(authenticatedFetch).toHaveBeenCalledWith(expect.stringContaining('/products'));
    expect(result.current.products.length).toBeGreaterThan(0);
  });

  it('exposes activeProduct matching the active slug', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    expect(result.current.activeProduct?.slug).toBe('vpromedia');
  });
});

// ---------------------------------------------------------------------------
// AC-ENTRY-2: Persistence across reloads (localStorage)
// ---------------------------------------------------------------------------

describe('ProductContext — localStorage persistence', () => {
  it('reads saved slug from localStorage on mount', async () => {
    localStorage.setItem('vqa_product', 'vtrade');

    const { result } = renderHook(() => useProductContext(), { wrapper });

    expect(result.current.activeSlug).toBe('vtrade');
  });

  it('writes new slug to localStorage on setProduct', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    act(() => {
      result.current.setProduct('vtrade');
    });

    expect(localStorage.getItem('vqa_product')).toBe('vtrade');
    expect(result.current.activeSlug).toBe('vtrade');
  });
});

// ---------------------------------------------------------------------------
// AC-ERROR-1: Corrupt localStorage falls back to vpromedia
// ---------------------------------------------------------------------------

describe('ProductContext — corrupt localStorage fallback', () => {
  it('falls back to vpromedia for an unrecognized slug in localStorage', async () => {
    localStorage.setItem('vqa_product', 'notaproduct_xyz_corrupt');

    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    // After products load, the corrupt slug is not in the list → fall back
    expect(result.current.activeSlug).toBe('vpromedia');
  });

  it('falls back to vpromedia for empty string in localStorage', async () => {
    localStorage.setItem('vqa_product', '');

    const { result } = renderHook(() => useProductContext(), { wrapper });

    expect(result.current.activeSlug).toBe('vpromedia');
  });
});

// ---------------------------------------------------------------------------
// AC-ASYNC-1: AbortController cancellation on product switch
// ---------------------------------------------------------------------------

describe('ProductContext — AbortController cancellation', () => {
  it('exposes abortRef that the caller can use to cancel in-flight fetches', () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    // The context must expose a cancelTicketFetch function or abortSignal
    // for SelectView to call on product switch
    expect(typeof result.current.cancelTicketFetch).toBe('function');
  });

  it('cancelTicketFetch is callable without throwing', () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    expect(() => result.current.cancelTicketFetch()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// setProduct behaviour
// ---------------------------------------------------------------------------

describe('ProductContext — setProduct', () => {
  it('updates activeSlug and activeProduct on setProduct', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    act(() => {
      result.current.setProduct('vtrade');
    });

    expect(result.current.activeSlug).toBe('vtrade');
    expect(result.current.activeProduct?.slug).toBe('vtrade');
  });

  it('does not throw when setProduct called with unknown slug', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    expect(() => {
      act(() => {
        result.current.setProduct('nonexistent');
      });
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// AC-HAPPY-3: setProduct clears vqa_targetUrl on product switch
// ---------------------------------------------------------------------------

describe('ProductContext — setProduct target URL reset (AC-HAPPY-3)', () => {
  it('clears vqa_targetUrl from localStorage on product switch', async () => {
    // Prime localStorage as if vProMedia's URL was previously stored
    localStorage.setItem('vqa_targetUrl', 'https://two-test.vcreative.net');

    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    act(() => {
      result.current.setProduct('vtrade');
    });

    // After switching products, the stored URL must be cleared so SelectView
    // can auto-populate it from the new product's registry entry (AC-HAPPY-3)
    expect(localStorage.getItem('vqa_targetUrl')).toBeNull();
  });

  it('preserves vqa_product in localStorage after switching away from vpromedia', async () => {
    localStorage.setItem('vqa_targetUrl', 'https://two-test.vcreative.net');

    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    act(() => {
      result.current.setProduct('vtrade');
    });

    // vqa_product must be updated to the new slug
    expect(localStorage.getItem('vqa_product')).toBe('vtrade');
  });
});

// ---------------------------------------------------------------------------
// Context shape contract
// ---------------------------------------------------------------------------

describe('ProductContext — shape contract', () => {
  it('exposes expected fields from useProductContext', async () => {
    const { result } = renderHook(() => useProductContext(), { wrapper });

    const ctx = result.current;
    expect(ctx).toHaveProperty('activeSlug');
    expect(ctx).toHaveProperty('activeProduct');
    expect(ctx).toHaveProperty('products');
    expect(ctx).toHaveProperty('setProduct');
    expect(ctx).toHaveProperty('cancelTicketFetch');
    expect(ctx).toHaveProperty('isLoading');
  });
});

// ---------------------------------------------------------------------------
// Error handling — /products fetch failure
// ---------------------------------------------------------------------------

describe('ProductContext — /products fetch failure', () => {
  it('falls back gracefully when /products returns an error', async () => {
    vi.mocked(authenticatedFetch).mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => useProductContext(), { wrapper });

    await act(async () => {
      await new Promise(r => setTimeout(r, 0));
    });

    // Should still default to vpromedia without crashing
    expect(result.current.activeSlug).toBe('vpromedia');
    expect(result.current.products).toEqual([]);
  });
});
