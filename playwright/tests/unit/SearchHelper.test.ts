/**
 * playwright/tests/unit/SearchHelper.test.ts
 * =============================================
 * SearchHelper Unit Test Suite
 *
 * Tests the behavioral contract of SearchHelper.ts without requiring a live app.
 * Uses synthetic DOM that faithfully reproduces the PrimeNG/Angular element structure
 * observed in vCreative (DOM analysis: 2026-02-04).
 *
 * Required by GEMINI.md architecture rule:
 *   "Any helper utility promoted to a critical fast-path MUST have a dedicated unit
 *    test suite before it is used in production execution. Minimum contract:
 *    cover the happy path, the already-open guard, the catch/fallback block, and
 *    at least one PrimeNG-specific failure mode."
 *
 * Coverage:
 *   ✅ TC-1  openSearchPanel — already-open guard (no duplicate click)
 *   ✅ TC-2  openSearchPanel — happy path (panel opens, input visible)
 *   ✅ TC-3  performSearch  — client autocomplete happy path
 *   ✅ TC-4  performSearch  — autocomplete catch/fallback (no suggestion → typed value used)
 *   ✅ TC-5  performSearch  — PrimeNG p-multiselect failure mode (status options never render)
 */

import { test, expect, type Page } from '@playwright/test';
import {
    openSearchPanel,
    performSearch,
} from '@utils/SearchHelper';

// ---------------------------------------------------------------------------
// Synthetic DOM
// Reproduces the PrimeNG/Angular DOM structure for search panel interactions.
// ---------------------------------------------------------------------------

/**
 * Generate the base synthetic DOM HTML.
 * @param sidebarVisible  - If true, sidebar starts already open.
 * @param autocompleteEnabled - If true, typing in #client shows the autocomplete list.
 * @param statusOptionsEnabled - If true, clicking p-multiselect renders option elements.
 */
function buildDOM(opts: {
    sidebarVisible?: boolean;
    autocompleteEnabled?: boolean;
    statusOptionsEnabled?: boolean;
} = {}): string {
    const {
        sidebarVisible = false,
        autocompleteEnabled = true,
        statusOptionsEnabled = true,
    } = opts;

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SearchHelper Unit Test Harness</title>
  <style>
    * { box-sizing: border-box; }
  </style>
</head>
<body>

  <!-- ── Search trigger ──────────────────────────────────────── -->
  <button id="top-open-search-panel" aria-label="Open search panel">Open Search</button>

  <!-- ── Sidebar / filter overlay ───────────────────────────── -->
  <div class="p-sidebar" style="${sidebarVisible ? 'display:block' : 'display:none'}">

    <!-- Client autocomplete -->
    <label for="client">Client</label>
    <input id="client" type="text" placeholder="Client Name">
    <ul class="p-autocomplete-list" data-hidden="true" style="display:none">
      <li class="p-autocomplete-option">The Beta Boys</li>
      <li class="p-autocomplete-option">Alpha Media Group</li>
    </ul>

    <!-- Ad Types tab + ng-select (PrimeNG/Angular) -->
    <a id="'search-adtypes-tab'" href="#" role="tab">Ad Types</a>
    <div id="adtypes">
      <ng-select>
        <input role="combobox" type="text" placeholder="Ad type...">
        <div class="ng-option" style="display:none">Radio Commercial</div>
        <div class="ng-option" style="display:none">TV Commercial</div>
      </ng-select>
    </div>

    <!-- Status tab + p-multiselect -->
    <a id="search-spotstatus-tab" href="#" role="tab">Status</a>
    <p-multiselect id="status_dropdown" defaultlabel="Statuses" placeholder="Statuses">
      <div class="p-multiselect-label">Statuses</div>
      <!-- Options rendered only when statusOptionsEnabled -->
    </p-multiselect>

    <!-- Execute -->
    <button id="do-search-btn">Search</button>
    <div class="p-sidebar-close p-sidebar-close-icon" role="button" aria-label="Close"></div>
  </div>

  <!-- ── Overlay mask (visible when sidebar is open) ─────────── -->
  <div class="p-sidebar-mask" style="${sidebarVisible ? '' : 'display:none'}"></div>

  <!-- ── Results area (revealed after search executes) ──────── -->
  <h1 class="search-results-header v-page-header" style="display:none">Search Results</h1>
  <div class="p-datatable-tbody" style="display:none">
    <tr><td>Mock result row</td></tr>
  </div>

  <script>
    /* ── Shared state counters ──────────────────────────────── */
    window.__vqa = {
      searchBtnClicks: 0,
      doSearchClicks: 0,
      autocompleteEnabled: ${autocompleteEnabled},
      statusOptionsEnabled: ${statusOptionsEnabled},
    };

    /* ── Open sidebar on search button click ────────────────── */
    document.getElementById('top-open-search-panel').addEventListener('click', () => {
      const sidebar   = document.querySelector('.p-sidebar');
      const mask      = document.querySelector('.p-sidebar-mask');
      sidebar.style.display = 'block';
      mask.style.display    = 'block';
      window.__vqa.searchBtnClicks++;
    });

    /* ── Autocomplete: show list on typing ──────────────────── */
    document.getElementById('client').addEventListener('input', (e) => {
      if (!window.__vqa.autocompleteEnabled) return;
      const list = document.querySelector('ul.p-autocomplete-list');
      list.style.display = e.target.value.length > 0 ? 'block' : 'none';
    });

    /* ── Autocomplete: option click fills input ─────────────── */
    document.querySelectorAll('.p-autocomplete-option').forEach(li => {
      li.addEventListener('click', () => {
        document.getElementById('client').value = li.textContent.trim();
        document.querySelector('ul.p-autocomplete-list').style.display = 'none';
      });
    });

    /* ── Ad Types tab: expose ng-select combobox ────────────── */
    const adTypesTab = document.getElementById("'search-adtypes-tab'");
    if (adTypesTab) {
      adTypesTab.addEventListener('click', () => {
        const input = document.querySelector('#adtypes ng-select input[role="combobox"]');
        if (input) input.style.display = 'inline-block';
      });
    }

    /* ── ng-select combobox: typing reveals .ng-option ─────── */
    const combobox = document.querySelector('#adtypes ng-select input[role="combobox"]');
    if (combobox) {
      combobox.addEventListener('input', () => {
        document.querySelectorAll('.ng-option').forEach(o => o.style.display = 'block');
      });
    }

    /* ── .ng-option click: select option ───────────────────── */
    document.querySelectorAll('.ng-option').forEach(opt => {
      opt.addEventListener('click', () => {
        document.querySelectorAll('.ng-option').forEach(o => o.style.display = 'none');
      });
    });

    /* ── p-multiselect click: render status options ─────────── */
    const multiselect = document.getElementById('status_dropdown');
    if (multiselect) {
      multiselect.addEventListener('click', () => {
        if (!window.__vqa.statusOptionsEnabled) return;  // PrimeNG failure mode: options never render
        // Simulate options appearing in a portal overlay
        const opt = document.createElement('li');
        opt.setAttribute('role', 'option');
        opt.setAttribute('aria-label', 'Active');
        opt.textContent = 'Active';
        opt.style.display = 'block';
        multiselect.appendChild(opt);
      });
    }

    /* ── Execute search: close sidebar, show results ─────────── */
    document.getElementById('do-search-btn').addEventListener('click', () => {
      document.querySelector('.p-sidebar').style.display          = 'none';
      document.querySelector('.p-sidebar-mask').style.display     = 'none';
      document.querySelector('.search-results-header').style.display = 'block';
      document.querySelector('.p-datatable-tbody').style.display  = 'block';
      window.__vqa.doSearchClicks++;
    });
  </script>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function getClickCounts(page: Page): Promise<{ searchBtn: number; doSearch: number }> {
    return page.evaluate(() => ({
        searchBtn: (window as any).__vqa.searchBtnClicks,
        doSearch: (window as any).__vqa.doSearchClicks,
    }));
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe('SearchHelper — Unit Tests', () => {
    // No real app — block all network requests
    test.use({ storageState: undefined });

    test.beforeEach(async ({ page }) => {
        await page.route('**/*', route => route.abort().catch(() => {}));
    });

    // ── TC-1: Already-open guard ────────────────────────────────────────────
    test('TC-1 — openSearchPanel: already-open guard prevents duplicate click', async ({ page }) => {
        // Sidebar is ALREADY VISIBLE when this test starts
        await page.setContent(buildDOM({ sidebarVisible: true }));

        await openSearchPanel(page, 'TC-1 guard test');

        const clicks = await getClickCounts(page);

        // Contract: if panel is already visible, search button must NOT be clicked
        expect(clicks.searchBtn).toBe(0);

        // Contract: input#client remains accessible (panel is still open)
        await expect(page.locator('input#client')).toBeVisible();
    });

    // ── TC-2: Happy path — panel opens ─────────────────────────────────────
    test('TC-2 — openSearchPanel: happy path opens panel and exposes input', async ({ page }) => {
        // Sidebar starts HIDDEN
        await page.setContent(buildDOM({ sidebarVisible: false }));

        await openSearchPanel(page, 'TC-2 happy path');

        // Contract: search button was clicked at least once
        const clicks = await getClickCounts(page);
        expect(clicks.searchBtn).toBeGreaterThanOrEqual(1);

        // Contract: input#client is now visible (panel opened successfully)
        await expect(page.locator('input#client')).toBeVisible();
    });

    // ── TC-3: Client autocomplete happy path ────────────────────────────────
    test('TC-3 — performSearch: client autocomplete selects matching suggestion', async ({ page }) => {
        await page.setContent(buildDOM({ sidebarVisible: true, autocompleteEnabled: true }));

        // Act: perform search with client name that matches an autocomplete option
        await performSearch(page, { client: 'The Beta Boys' });

        // Contract: search was executed
        const clicks = await getClickCounts(page);
        expect(clicks.doSearch).toBe(1);

        // Contract: results grid is visible
        await expect(page.locator('.p-datatable-tbody')).toBeVisible();

        // Contract: the client input was filled (autocomplete or typed value)
        const clientValue = await page.locator('input#client').inputValue();
        // The value is either set by autocomplete click OR by pressSequentially
        expect(clientValue.toLowerCase()).toContain('beta boys');
    });

    // ── TC-4: Autocomplete catch/fallback ───────────────────────────────────
    test('TC-4 — performSearch: autocomplete catch/fallback uses typed value', async ({ page }) => {
        // autocompleteEnabled: false → autocomplete list never appears → 5s timeout fires → catch block runs
        test.setTimeout(60_000); // Accommodate the 5s autocomplete timeout in SearchHelper
        await page.setContent(buildDOM({ sidebarVisible: true, autocompleteEnabled: false }));

        // Act: client does NOT exist in autocomplete → catch block should fire, function must NOT throw
        let threw = false;
        try {
            await performSearch(page, { client: 'XYZ Corp No Match' });
        } catch {
            threw = true;
        }

        // Contract: function MUST NOT throw even when autocomplete fails
        expect(threw).toBe(false);

        // Contract: typed value is present in input (not reset/cleared by the catch block)
        const clientValue = await page.locator('input#client').inputValue();
        // pressSequentially fills the input; the catch block only skips the autocomplete click
        expect(clientValue).not.toBe('');

        // Contract: search was still executed (search button was clicked after the fallback)
        const clicks = await getClickCounts(page);
        expect(clicks.doSearch).toBe(1);
    });

    // ── TC-5: PrimeNG p-multiselect failure mode ────────────────────────────
    test('TC-5 — performSearch: status p-multiselect unresponsive is handled gracefully', async ({ page }) => {
        // statusOptionsEnabled: false → clicking p-multiselect renders NO option elements
        // SearchHelper.ts: waitFor(statusOption, 5s) → times out → .catch() prevents crash
        test.setTimeout(60_000); // Accommodate the 5s status option timeout in SearchHelper

        await page.setContent(buildDOM({
            sidebarVisible: true,
            autocompleteEnabled: true,
            statusOptionsEnabled: false, // PrimeNG multiselect does NOT render options after click
        }));

        // Act: request a status filter that will fail to find options in the dropdown
        let threw = false;
        try {
            await performSearch(page, {
                client: 'The Beta Boys',
                status: 'Active',
            });
        } catch {
            threw = true;
        }

        // Contract: function MUST NOT throw even when p-multiselect is unresponsive
        // SearchHelper has a .catch(() => console.log('⚠️ Status dropdown wait timeout...'))
        expect(threw).toBe(false);
    });
});
