/**
 * vQA — ProductSelector
 * =====================
 * Module: frontend/src/components/ProductSelector.tsx
 *
 * Option 4: Labeled Inline Pill with per-product colored left-border accent.
 * (Creative decision TASK-124, Q1 — UX design)
 *
 * Design:
 * - "Product:" label + active product name + chevron icon
 * - 3px colored left-border accent per product (CSS custom property)
 * - Dropdown rendered via React portal (document.body) with position:fixed
 *   to escape .app-nav overflow:hidden clipping
 * - Full keyboard navigation: Enter/Space opens, Escape closes, click selects
 * - Accessible: aria-haspopup="listbox", aria-expanded, aria-selected
 * - On selection: calls cancelTicketFetch() then setProduct() (AC-ASYNC-1)
 *
 * Per-product CSS colors (HSL):
 *   vpromedia   → hsl(262, 80%, 65%)
 *   vtrade      → hsl(198, 80%, 55%)
 *   vpromotions → hsl(340, 75%, 60%)
 *   vep         → hsl(152, 60%, 45%)
 *   vppo        → hsl(28, 90%, 55%)
 *   psn         → hsl(215, 70%, 58%)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useProductContext } from "../context/ProductContext";

// ---------------------------------------------------------------------------
// Per-product accent colors (Creative Q1 decision)
// ---------------------------------------------------------------------------

const PRODUCT_COLORS: Record<string, string> = {
  vpromedia: "hsl(262, 80%, 65%)",
  vtrade: "hsl(198, 80%, 55%)",
  vpromotions: "hsl(340, 75%, 60%)",
  vep: "hsl(152, 60%, 45%)",
  vppo: "hsl(28, 90%, 55%)",
  psn: "hsl(215, 70%, 58%)",
};

const DEFAULT_COLOR = "hsl(174, 72%, 48%)";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProductSelector() {
  const { activeSlug, activeProduct, products, setProduct, cancelTicketFetch } =
    useProductContext();

  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLUListElement>(null);

  // Fixed position for the portal dropdown
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });

  const accentColor = PRODUCT_COLORS[activeSlug] ?? DEFAULT_COLOR;

  // ---------------------------------------------------------------------------
  // Calculate dropdown position when opening
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (isOpen && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropdownPos({
        top: rect.top,
        left: rect.right + 6,
      });
    }
  }, [isOpen]);

  // ---------------------------------------------------------------------------
  // Close on outside click (check both container and portal dropdown)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      const clickedInContainer =
        containerRef.current && containerRef.current.contains(target);
      const clickedInDropdown =
        dropdownRef.current && dropdownRef.current.contains(target);
      if (!clickedInContainer && !clickedInDropdown) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ---------------------------------------------------------------------------
  // Close on Escape
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // ---------------------------------------------------------------------------
  // Trigger handlers
  // ---------------------------------------------------------------------------
  const handleTriggerClick = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  const handleTriggerKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Option selection
  // ---------------------------------------------------------------------------
  const handleSelect = useCallback(
    (slug: string) => {
      if (slug !== activeSlug) {
        cancelTicketFetch(); // AC-ASYNC-1: cancel in-flight /tickets fetch
        setProduct(slug);
      }
      setIsOpen(false);
    },
    [activeSlug, cancelTicketFetch, setProduct],
  );

  const handleOptionKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLLIElement>, slug: string) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleSelect(slug);
      }
    },
    [handleSelect],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div
      className="product-selector"
      ref={containerRef}
      data-product={activeSlug}
    >
      {/* ── Trigger ─────────────────────────────────────────────── */}
      <button
        type="button"
        ref={triggerRef}
        className="product-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={`Product: ${activeProduct?.display_name ?? activeSlug}`}
        onClick={handleTriggerClick}
        onKeyDown={handleTriggerKeyDown}
        style={
          {
            "--product-accent": accentColor,
          } as React.CSSProperties
        }
      >
        <span className="product-selector-label">Product:</span>
        <span className="product-selector-name">
          {activeProduct?.display_name ?? activeSlug}
        </span>
        <span className="product-selector-chevron" aria-hidden="true">
          {isOpen ? "▲" : "▼"}
        </span>
      </button>

      {/* ── Dropdown (portal to body to escape overflow:hidden) ── */}
      {isOpen &&
        createPortal(
          <ul
            ref={dropdownRef}
            className="product-selector-dropdown"
            role="listbox"
            aria-label="Select product"
            style={{
              position: "fixed",
              top: dropdownPos.top,
              left: dropdownPos.left,
            }}
          >
            {products.map((product) => {
              const itemAccent =
                PRODUCT_COLORS[product.slug] ?? DEFAULT_COLOR;
              const isSelected = product.slug === activeSlug;
              return (
                <li
                  key={product.slug}
                  role="option"
                  aria-selected={isSelected}
                  tabIndex={0}
                  className={`product-selector-option ${isSelected ? "product-selector-option--active" : ""}`}
                  onClick={() => handleSelect(product.slug)}
                  onKeyDown={(e) => handleOptionKeyDown(e, product.slug)}
                  style={
                    {
                      "--product-accent": itemAccent,
                    } as React.CSSProperties
                  }
                >
                  <span className="product-option-name">
                    {product.display_name}
                  </span>
                  {product.roles.length === 0 && (
                    <span className="product-option-badge">Not configured</span>
                  )}
                </li>
              );
            })}
          </ul>,
          document.body,
        )}
    </div>
  );
}

