/**
 * core/selectors/vqaEngine.ts
 * =============================
 * Pure stateless custom selector engine for vQA.
 * Replaces dynamic DOM tagging and caching to prevent microtask races.
 */

export function _isStandardSelector(selector: string): boolean {
  if (!selector) return false;
  if (/^[#\.\[]|[\s\>\+\~]|^text=/.test(selector)) return true;
  if (/^(div|button|input|span|a|p|h[1-6]|li|ul|ol|table|tr|td|th|select|option|label|form|section|header|footer|textarea|iframe|svg|canvas)$/i.test(selector)) return true;
  if (/[:\(\)]/.test(selector)) return true;
  return false;
}

function _logFallback(selector: string): void {
  console.warn(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: "WARN",
    node: "Executor",
    message: "VQA_SELECTOR_FALLBACK",
    tenant_id: "global",
    technical_debt_metrics: { selector, type: "legacy_css" }
  }));
}

export const vqaEngine = {
  query(root: Document | Element, selector: string): Element | null {
    if (_isStandardSelector(selector)) {
      _logFallback(selector);
      return (root as Element).querySelector?.(selector) || document.querySelector(selector);
    }

    const overlay = document.querySelector('.p-sidebar:not(.p-sidebar-hidden), .p-dialog:not(.p-dialog-hidden), [role="dialog"]');
    const searchRoot = overlay || root;

    return searchRoot.querySelector(`[data-vqa-id="${selector}"]`) ||
           searchRoot.querySelector(`[aria-label="${selector}"]`) ||
           searchRoot.querySelector(`input[placeholder="${selector}"]`) ||
           null;
  },

  queryAll(root: Document | Element, selector: string): Element[] {
    if (_isStandardSelector(selector)) {
      _logFallback(selector);
      return Array.from((root as Element).querySelectorAll?.(selector) || document.querySelectorAll(selector));
    }

    const overlay = document.querySelector('.p-sidebar:not(.p-sidebar-hidden), .p-dialog:not(.p-dialog-hidden), [role="dialog"]');
    const searchRoot = overlay || root;

    const byId = Array.from(searchRoot.querySelectorAll(`[data-vqa-id="${selector}"]`));
    if (byId.length > 0) return byId;

    const byAria = Array.from(searchRoot.querySelectorAll(`[aria-label="${selector}"]`));
    if (byAria.length > 0) return byAria;

    return Array.from(searchRoot.querySelectorAll(`input[placeholder="${selector}"]`));
  }
};
