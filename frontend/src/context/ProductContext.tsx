/**
 * vQA — ProductContext
 * ====================
 * Module: frontend/src/context/ProductContext.tsx
 *
 * Provider + hook for the active product selection. Wraps the /products API
 * response and persists the active product slug to localStorage under the key
 * `vqa_product`.
 *
 * Design decisions (TASK-124, Creative Q1 + Q3):
 * - Default product slug: "vpromedia" (preserves existing behaviour)
 * - localStorage key: "vqa_product"
 * - Corrupt / unknown slug in localStorage → fall back to "vpromedia" after
 *   products are loaded and the slug cannot be matched (AC-ERROR-1)
 * - cancelTicketFetch() exposes an AbortController signal for SelectView to
 *   cancel in-flight /tickets fetches on product switch (AC-ASYNC-1)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { API_BASE_URL } from "../types";
import { authenticatedFetch } from "../api_client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProductPublic {
  slug: string;
  display_name: string;
  description: string;
  order: number;
  environments: Record<string, string>;
  default_environment: string;
  jira_board_ids: number[];
  roles: string[];
}

export interface ProductContextValue {
  /** The slug of the currently active product (e.g. "vpromedia"). */
  activeSlug: string;
  /** The full ProductPublic record for the active product, or null while loading. */
  activeProduct: ProductPublic | null;
  /** All products from the /products endpoint, sorted by order. */
  products: ProductPublic[];
  /** Switch the active product. Writes to localStorage. */
  setProduct: (slug: string) => void;
  /**
   * Cancel any in-flight /tickets fetch for the current product.
   * Call this BEFORE switching products so SelectView can abort stale requests
   * (AC-ASYNC-1).
   */
  cancelTicketFetch: () => void;
  /** True while the /products API call is in progress. */
  isLoading: boolean;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_SLUG = "vpromedia";
const LS_KEY = "vqa_product";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ProductCtx = createContext<ProductContextValue>({
  activeSlug: DEFAULT_SLUG,
  activeProduct: null,
  products: [],
  setProduct: () => undefined,
  cancelTicketFetch: () => undefined,
  isLoading: true,
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ProductProvider({ children }: { children: React.ReactNode }) {
  // Read the initial slug from localStorage. Empty / whitespace-only → default.
  const [activeSlug, setActiveSlug] = useState<string>(() => {
    const stored = localStorage.getItem(LS_KEY)?.trim();
    return stored || DEFAULT_SLUG;
  });

  const [products, setProducts] = useState<ProductPublic[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // AbortController for /tickets requests — ref so setProduct doesn't need to
  // be in a useCallback dependency array.
  const ticketAbortRef = useRef<AbortController | null>(null);

  // ---------------------------------------------------------------------------
  // Load products from /products on mount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function fetchProducts() {
      try {
        console.log('[ProductContext] Fetching /products...');
        const response = await authenticatedFetch(`${API_BASE_URL}/products`);
        if (!response.ok) {
          throw new Error(`/products returned ${response.status}`);
        }
        const data: ProductPublic[] = await response.json();
        console.log(`[ProductContext] Received ${data.length} products`, cancelled ? '(cancelled)' : '');
        if (!cancelled) {
          setProducts(data);
        }
      } catch (err) {
        console.warn('[ProductContext] Fetch failed:', err);
        if (!cancelled) {
          // Non-critical: keep products empty, default slug is still valid
          setProducts([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    fetchProducts();
    return () => {
      cancelled = true;
    };
  }, []);

  // ---------------------------------------------------------------------------
  // AC-ERROR-1: Corrupt-slug fallback — runs after products are loaded
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (isLoading || products.length === 0) return;

    const slugs = products.map((p) => p.slug);
    if (!slugs.includes(activeSlug)) {
      // The persisted slug is not in the registry → fall back and persist
      localStorage.setItem(LS_KEY, DEFAULT_SLUG);
      setActiveSlug(DEFAULT_SLUG);
    }
  }, [isLoading, products, activeSlug]);

  // ---------------------------------------------------------------------------
  // setProduct — public API
  // ---------------------------------------------------------------------------
  const setProduct = useCallback((slug: string) => {
    localStorage.setItem(LS_KEY, slug);
    localStorage.removeItem('vqa_targetUrl'); // Reset on product switch (AC-HAPPY-3)
    setActiveSlug(slug);
  }, []);

  // ---------------------------------------------------------------------------
  // cancelTicketFetch — public API (AC-ASYNC-1)
  // ---------------------------------------------------------------------------
  const cancelTicketFetch = useCallback(() => {
    if (ticketAbortRef.current) {
      ticketAbortRef.current.abort();
      ticketAbortRef.current = null;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Derived: activeProduct
  // ---------------------------------------------------------------------------
  const activeProduct =
    products.find((p) => p.slug === activeSlug) ?? null;

  return (
    <ProductCtx.Provider
      value={{
        activeSlug,
        activeProduct,
        products,
        setProduct,
        cancelTicketFetch,
        isLoading,
      }}
    >
      {children}
    </ProductCtx.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

// eslint-disable-next-line react-refresh/only-export-components
export function useProductContext(): ProductContextValue {
  return useContext(ProductCtx);
}
