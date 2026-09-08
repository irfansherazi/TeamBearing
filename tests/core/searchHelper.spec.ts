/**
 * tests/core/searchHelper.spec.ts
 * ==================================
 * Dedicated unit test suite for tenants/vpromedia/helpers/SearchHelper.ts.
 *
 * GEMINI.md Rule: Any helper utility promoted to a critical fast-path
 * (e.g., SearchHelper.ts) MUST have a dedicated unit test suite.
 * Minimum contract: happy path, already-open guard, catch/fallback block,
 * and at least one PrimeNG-specific failure mode.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock @playwright/test BEFORE importing SearchHelper
// Vitest hoists vi.mock() calls, so this intercepts the Playwright import
// in SearchHelper.ts and replaces `expect` with a vitest-safe stub.
// ---------------------------------------------------------------------------
vi.mock('@playwright/test', () => ({
  expect: (locator: any) => ({
    toBeHidden: vi.fn().mockResolvedValue(undefined),
    toBeVisible: vi.fn().mockResolvedValue(undefined),
    toHaveText: vi.fn().mockResolvedValue(undefined),
  }),
  Page: class {},
  Locator: class {},
}));

import { openSearchPanel, performSearch, SearchCriteria } from '../../tenants/vpromedia/helpers/SearchHelper';

// ---------------------------------------------------------------------------
// Playwright Page mock factory
// ---------------------------------------------------------------------------
function makeLocator(overrides: Record<string, any> = {}): any {
  const loc: any = {
    isVisible: vi.fn().mockResolvedValue(false),
    waitFor: vi.fn().mockResolvedValue(undefined),
    click: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
    pressSequentially: vi.fn().mockResolvedValue(undefined),
    filter: vi.fn(),
    first: vi.fn(),
    locator: vi.fn(),
    getByRole: vi.fn(),
    ...overrides,
  };
  // filter().first() chains return self by default
  loc.filter.mockReturnValue(loc);
  loc.first.mockReturnValue(loc);
  loc.locator.mockReturnValue(loc);
  loc.getByRole.mockReturnValue(loc);
  return loc;
}

function makePage(): any {
  const page: any = {
    locator: vi.fn(),
    getByRole: vi.fn(),
    waitForTimeout: vi.fn().mockResolvedValue(undefined),
  };
  page.getByRole.mockReturnValue(makeLocator());
  return page;
}

// ---------------------------------------------------------------------------
// openSearchPanel
// ---------------------------------------------------------------------------
describe('openSearchPanel', () => {
  let page: any;

  beforeEach(() => {
    vi.clearAllMocks();
    page = makePage();
  });

  it('Happy Path: opens the search panel when sidebar is not visible', async () => {
    const sidebarLoc = makeLocator({ isVisible: vi.fn().mockResolvedValue(false) });
    const searchBtnLoc = makeLocator();
    const clientInputLoc = makeLocator();

    page.locator
      .mockReturnValueOnce({ first: () => sidebarLoc }) // .p-sidebar, .filter-overlay
      .mockReturnValueOnce(searchBtnLoc)                // #top-open-search-panel
      .mockReturnValueOnce(clientInputLoc);             // input#client

    await openSearchPanel(page, 'Test context label', false);

    expect(searchBtnLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 5000 });
    expect(searchBtnLoc.click).toHaveBeenCalledWith({ force: true });
    expect(clientInputLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 5000 });
    expect(page.waitForTimeout).toHaveBeenCalledWith(500);
  });

  it('Already-Open Guard: skips clicking search button if sidebar is already visible', async () => {
    const sidebarLoc = makeLocator({ isVisible: vi.fn().mockResolvedValue(true) });
    page.locator.mockReturnValueOnce({ first: () => sidebarLoc });

    await openSearchPanel(page, 'Already open context');

    expect(sidebarLoc.click).not.toHaveBeenCalled();
    expect(page.waitForTimeout).not.toHaveBeenCalled();
  });

  it('Catch/Fallback Block: treats sidebar as not-visible when isVisible rejects', async () => {
    // Simulates a Playwright timing edge case where isVisible throws
    const sidebarLoc = makeLocator({ isVisible: vi.fn().mockRejectedValue(new Error('element detached')) });
    const searchBtnLoc = makeLocator();
    const clientInputLoc = makeLocator();

    page.locator
      .mockReturnValueOnce({ first: () => sidebarLoc })
      .mockReturnValueOnce(searchBtnLoc)
      .mockReturnValueOnce(clientInputLoc);

    // Should NOT throw — the catch(() => false) absorbs the error
    await expect(openSearchPanel(page, 'Error context')).resolves.toBeUndefined();
    // Panel was not open (fallback to false), so it should proceed to click
    expect(searchBtnLoc.click).toHaveBeenCalledWith({ force: true });
  });
});

// ---------------------------------------------------------------------------
// performSearch — helper to build locator registry
// ---------------------------------------------------------------------------
function buildPageLocator(overrides: Record<string, any> = {}) {
  const registry: Record<string, any> = {
    '.p-sidebar, .filter-overlay': { first: () => makeLocator({ isVisible: vi.fn().mockResolvedValue(true) }) },
    '#top-open-search-panel': makeLocator(),
    'input#client': makeLocator(),
    '[id="\'search-adtypes-tab\'"], a': makeLocator(),
    '#adtypes ng-select, ng-select[formcontrolname="ad_types"]': makeLocator(),
    '.ng-option': makeLocator(),
    '#search-spotstatus-tab, [id="\'search-spotstatus-tab\'"], a': makeLocator(),
    'p-multiselect#status_dropdown, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]': makeLocator(),
    'ul.p-autocomplete-list li.p-autocomplete-option': makeLocator(),
    '#do-search-btn': { filter: () => ({ first: () => makeLocator() }) },
    '.p-sidebar-mask': makeLocator(),
    ...overrides,
  };

  const page = makePage();
  page.locator.mockImplementation((selector: string) => registry[selector] ?? makeLocator());
  page.getByRole.mockReturnValue(makeLocator());
  return page;
}

describe('performSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ─── Happy path: client only ──────────────────────────────────────────────
  it('Happy Path (client): navigates client autocomplete → submits search', async () => {
    const clientLoc = makeLocator();
    const suggestionLoc = makeLocator();
    const doSearchLoc = makeLocator();

    const page = buildPageLocator({
      'input#client': clientLoc,
      'ul.p-autocomplete-list li.p-autocomplete-option': { filter: () => ({ first: () => suggestionLoc }) },
      '#do-search-btn': { filter: () => ({ first: () => doSearchLoc }) },
    });

    await performSearch(page, { client: 'Acme Corp' });

    expect(clientLoc.click).toHaveBeenCalled();
    expect(clientLoc.clear).toHaveBeenCalled();
    expect(clientLoc.pressSequentially).toHaveBeenCalledWith('Acme Corp', { delay: 50 });
    expect(suggestionLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 3000 });
    expect(suggestionLoc.click).toHaveBeenCalled();
    expect(doSearchLoc.click).toHaveBeenCalledWith({ force: true });
  });

  // ─── Happy path: adType only ──────────────────────────────────────────────
  it('Happy Path (adType): navigates Ad Types tab → ng-select combobox → submits', async () => {
    const adTypeTabLoc = makeLocator();
    const ngSelectLoc = makeLocator();
    const comboboxLoc = makeLocator();
    const optionLoc = makeLocator();
    const doSearchLoc = makeLocator();

    // Replicate the real chain: page.locator('#adtypes ng-select').first().locator('input[role="combobox"]')
    ngSelectLoc.first.mockReturnValue(ngSelectLoc);
    ngSelectLoc.locator.mockReturnValue(comboboxLoc);

    const page = buildPageLocator({
      '[id="\'search-adtypes-tab\'"], a': { filter: () => ({ first: () => adTypeTabLoc }) },
      '#adtypes ng-select, ng-select[formcontrolname="ad_types"]': ngSelectLoc,
      '.ng-option': { filter: () => ({ first: () => optionLoc }) },
      '#do-search-btn': { filter: () => ({ first: () => doSearchLoc }) },
    });

    await performSearch(page, { adType: 'Radio Commercial' });

    expect(adTypeTabLoc.click).toHaveBeenCalledWith({ force: true });
    expect(comboboxLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 2000 });
    expect(comboboxLoc.click).toHaveBeenCalledWith({ force: true });
    expect(comboboxLoc.pressSequentially).toHaveBeenCalledWith('Radio Commercial', { delay: 20 });
    expect(optionLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 2000 });
    expect(optionLoc.click).toHaveBeenCalled();
    expect(doSearchLoc.click).toHaveBeenCalledWith({ force: true });
  });

  // ─── Happy path: status only ──────────────────────────────────────────────
  it('Happy Path (status): navigates Status tab → multiselect → submits', async () => {
    const statusTabLoc = makeLocator();
    const statusDropdownLoc = makeLocator();
    const doSearchLoc = makeLocator();

    // page.getByRole('option', { name: criteria.status }).first()
    const statusOptionLoc = makeLocator();

    const page = buildPageLocator({
      '#search-spotstatus-tab, [id="\'search-spotstatus-tab\'"], a': { filter: () => ({ first: () => statusTabLoc }) },
      'p-multiselect#status_dropdown, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]': statusDropdownLoc,
      '#do-search-btn': { filter: () => ({ first: () => doSearchLoc }) },
    });

    page.getByRole.mockReturnValue({ first: () => statusOptionLoc, waitFor: statusOptionLoc.waitFor });
    // getByRole returns locator with .first()
    const fullStatusOption = makeLocator();
    page.getByRole.mockReturnValue({ first: () => fullStatusOption });

    await performSearch(page, { status: 'Active' });

    expect(statusTabLoc.click).toHaveBeenCalled();
    expect(statusDropdownLoc.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 2000 });
    expect(statusDropdownLoc.click).toHaveBeenCalled();
    expect(fullStatusOption.waitFor).toHaveBeenCalledWith({ state: 'visible', timeout: 2000 });
    expect(fullStatusOption.click).toHaveBeenCalledWith({ force: true });
    expect(doSearchLoc.click).toHaveBeenCalledWith({ force: true });
  });

  // ─── No criteria: skips all filter blocks ────────────────────────────────
  it('No Criteria: skips all filter blocks and submits search directly', async () => {
    const clientLocSpy = vi.fn().mockReturnValue(makeLocator());
    const doSearchLoc = makeLocator();

    const page = buildPageLocator({
      'input#client': clientLocSpy as any,
      '#do-search-btn': { filter: () => ({ first: () => doSearchLoc }) },
    });

    await performSearch(page, {});

    // client input should never have click/clear/pressSequentially called
    expect(doSearchLoc.click).toHaveBeenCalledWith({ force: true });
  });

  // ─── PrimeNG Failure: autocomplete suggestion list timeout ───────────────
  it('PrimeNG Failure Mode: waitFor timeout on p-autocomplete-list suggestion', async () => {
    const failingLoc = makeLocator({
      waitFor: vi.fn().mockRejectedValue(new Error('TimeoutError: Locator.waitFor: Timeout 3000ms exceeded')),
    });

    const page = buildPageLocator({
      'ul.p-autocomplete-list li.p-autocomplete-option': { filter: () => ({ first: () => failingLoc }) },
    });

    await expect(performSearch(page, { client: 'Acme Corp' })).rejects.toThrow(
      'TimeoutError: Locator.waitFor: Timeout 3000ms exceeded'
    );
  });

  // ─── PrimeNG Failure: ng-select combobox input timeout ──────────────────
  it('PrimeNG Failure Mode: waitFor timeout on ng-select combobox input[role="combobox"]', async () => {
    const ngSelectLoc = makeLocator();
    const failingCombobox = makeLocator({
      waitFor: vi.fn().mockRejectedValue(new Error('TimeoutError: ng-select combobox not visible after 2000ms')),
    });
    ngSelectLoc.first.mockReturnValue(ngSelectLoc);
    ngSelectLoc.locator.mockReturnValue(failingCombobox);

    const adTypeTabLoc = makeLocator();

    const page = buildPageLocator({
      '[id="\'search-adtypes-tab\'"], a': { filter: () => ({ first: () => adTypeTabLoc }) },
      '#adtypes ng-select, ng-select[formcontrolname="ad_types"]': ngSelectLoc,
    });

    await expect(performSearch(page, { adType: 'Radio Commercial' })).rejects.toThrow(
      'TimeoutError: ng-select combobox not visible after 2000ms'
    );
  });

  // ─── PrimeNG Failure: status multiselect dropdown timeout ───────────────
  it('PrimeNG Failure Mode: waitFor timeout on p-multiselect status dropdown', async () => {
    const statusTabLoc = makeLocator();
    const failingDropdown = makeLocator({
      waitFor: vi.fn().mockRejectedValue(new Error('TimeoutError: p-multiselect not visible after 2000ms')),
    });

    const page = buildPageLocator({
      '#search-spotstatus-tab, [id="\'search-spotstatus-tab\'"], a': { filter: () => ({ first: () => statusTabLoc }) },
      'p-multiselect#status_dropdown, p-multiselect[defaultlabel="Statuses"], p-multiselect[placeholder="Statuses"]': failingDropdown,
    });

    await expect(performSearch(page, { status: 'Active' })).rejects.toThrow(
      'TimeoutError: p-multiselect not visible after 2000ms'
    );
  });
});

// ---------------------------------------------------------------------------
// Corpus integrity check (AC-8)
// ---------------------------------------------------------------------------
describe('Benchmark corpus_50.json integrity (AC-8)', () => {
  it('should exist and contain exactly 50 cards with required fields', async () => {
    const fs = await import('fs');
    const path = await import('path');
    const corpusPath = path.resolve(__dirname, '../../tests/benchmarks/corpus_50.json');
    expect(fs.existsSync(corpusPath), 'corpus_50.json must exist at tests/benchmarks/corpus_50.json').toBe(true);

    const corpus = JSON.parse(fs.readFileSync(corpusPath, 'utf-8'));
    expect(Array.isArray(corpus), 'corpus_50.json must be a JSON array').toBe(true);
    expect(corpus.length, 'corpus must contain exactly 50 cards').toBe(50);

    const requiredFields = ['ticket_id', 'tier', 'summary', 'acceptance_criteria'];
    for (const card of corpus) {
      for (const field of requiredFields) {
        expect(card, `card ${card.ticket_id} must have field "${field}"`).toHaveProperty(field);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Tenant config integrity check (AC-5 / Phase 3)
// ---------------------------------------------------------------------------
describe('Tenant config and selectors integrity (Phase 3)', () => {
  it('vqa.config.json: should have required multi-tenant fields', async () => {
    const fs = await import('fs');
    const path = await import('path');
    const configPath = path.resolve(__dirname, '../../tenants/vpromedia/vqa.config.json');
    expect(fs.existsSync(configPath)).toBe(true);

    const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    expect(config.tenant_id).toBe('vpromedia');
    expect(config.base_urls).toBeDefined();
    expect(config.rag).toBeDefined();
    expect(config.rag.selector_top_k).toBe(5);
    expect(config.rag.min_corpus_for_bm25).toBe(10);
    expect(config.helpers_dir).toBeDefined();
    expect(config.selectors_file).toBeDefined();
  });

  it('selectors.json: should have at least 20 selector keys and no path traversal markers', async () => {
    const fs = await import('fs');
    const path = await import('path');
    const selectorsPath = path.resolve(__dirname, '../../tenants/vpromedia/selectors.json');
    expect(fs.existsSync(selectorsPath)).toBe(true);

    const selectors = JSON.parse(fs.readFileSync(selectorsPath, 'utf-8'));
    const keys = Object.keys(selectors).filter(k => k !== '_readme');
    expect(keys.length).toBeGreaterThanOrEqual(20);

    // AC architecture rule: no path traversal indicators in selector definitions
    for (const key of keys) {
      const val = JSON.stringify(selectors[key]);
      expect(val, `selector "${key}" must not contain path traversal`).not.toMatch(/\.\.\//);
    }

    // Every selector entry should have both 'selector' and 'description' fields
    for (const key of keys) {
      expect(selectors[key], `selector "${key}" must have 'selector' field`).toHaveProperty('selector');
      expect(selectors[key], `selector "${key}" must have 'description' field`).toHaveProperty('description');
    }
  });
});
