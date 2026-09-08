/**
 * Select2v3Helper.ts — Primitives for select2 v3 widgets used across PRF runbooks.
 *
 * The vPromotions app renders select2 v3 (jQuery). Every select2 v3 widget wraps
 * its underlying <select> or <input> in a container with id `#s2id_<field>` and
 * the drop overlay is mounted directly under <body> (NOT scoped to the container).
 *
 * Widget flavors (see interactions.json + runbook references):
 *   - select2_single_v3  — wrapper contains `a.select2-choice` (opens drop on click)
 *   - select2_multi_v3   — wrapper contains `ul.select2-choices` (multi-tag input)
 *   - select2_ajax_v3    — same DOM shape, but populates via XHR (ghost picker,
 *                          `select2typeahead` clientname). `minimumInputLength` +
 *                          `quietMillis` throttle apply.
 *
 * Locator rules:
 *   - Container:  `#s2id_<field>` — always exists once the widget is bound.
 *   - Single trigger:  container + `a.select2-choice` — the ONLY element that
 *                      opens the drop. `a.select2-focusser` is a transparent proxy
 *                      and clicking it does NOT open.
 *   - Multi trigger:   container + `ul.select2-choices input.select2-input`.
 *   - Drop overlay:    `body > div.select2-drop.select2-drop-active` when open.
 *                      Multi-select variant: `.select2-drop-multi.select2-drop-active`.
 *   - Selectable items: `li.select2-result-selectable` inside `ul.select2-results`.
 *                       `li.select2-result-unselectable` does NOT fire selection.
 *
 * NEVER rely on `role=option` — select2 v3 applies it inconsistently.
 * NEVER rely on placeholder text — the underlying hidden input keeps a different
 *                                  placeholder than the visible select2 renders.
 */

import { expect, Page, Locator } from '@playwright/test';

/**
 * Get the currently active drop overlay. Multi variant has its own class.
 */
export function activeSelect2Drop(page: Page, multi = false): Locator {
    const cls = multi
        ? 'body > div.select2-drop-multi.select2-drop-active, body > div.select2-drop.select2-drop-active'
        : 'body > div.select2-drop.select2-drop-active';
    return page.locator(cls).first();
}

/**
 * Open a select2 single-select drop by clicking `a.select2-choice`.
 * Waits for the drop overlay to become visible under <body>.
 */
export async function openSelect2Single(page: Page, containerId: string): Promise<Locator> {
    const container = page.locator(`#${containerId}`);
    await expect(container).toBeVisible({ timeout: 8000 });

    const choice = container.locator('a.select2-choice');
    await expect(choice).toBeVisible({ timeout: 5000 });
    await choice.click();

    const drop = activeSelect2Drop(page, false);
    await expect(drop).toBeVisible({ timeout: 5000 });
    return drop;
}

/**
 * Open a select2 multi-select drop by clicking the tag input.
 * `select2tags` (per formbuilder.js.html.twig:359) uses `.select2-container-multi`
 * with a `ul.select2-choices > li.select2-search-field > input.select2-input`.
 */
export async function openSelect2Multi(page: Page, containerId: string): Promise<Locator> {
    const container = page.locator(`#${containerId}.select2-container-multi, #${containerId}`);
    await expect(container.first()).toBeVisible({ timeout: 8000 });

    // Clicking the input (or the whole choices ul) focuses select2 and opens drop.
    const input = container.locator('ul.select2-choices input.select2-input').first();
    if (await input.isVisible({ timeout: 1500 }).catch(() => false)) {
        await input.click();
    } else {
        // Fallback: click the choices UL itself
        await container.locator('ul.select2-choices').first().click();
    }

    const drop = activeSelect2Drop(page, true);
    await expect(drop).toBeVisible({ timeout: 5000 });
    return drop;
}

/**
 * Pick a value in a select2 SINGLE widget by matching visible label text.
 * Sales-assignment style labels ("Name (Role - Station)") work verbatim —
 * parentheses are literal, do not escape.
 */
export async function pickSelect2Single(
    page: Page,
    containerId: string,
    labelText: string,
    options: { openDrop?: boolean; exact?: boolean } = {}
): Promise<void> {
    const { openDrop = true, exact = false } = options;

    let drop: Locator;
    if (openDrop) {
        drop = await openSelect2Single(page, containerId);
    } else {
        drop = activeSelect2Drop(page, false);
        await expect(drop).toBeVisible({ timeout: 3000 });
    }

    // Type into the drop's search input to filter (present on most single-selects).
    const search = drop.locator('input.select2-input').first();
    if (await search.isVisible({ timeout: 800 }).catch(() => false)) {
        await search.fill('');
        // Type at least enough to disambiguate — full label is safest for
        // "Corporate Contest" vs "Corporate Content" prefix collision.
        await search.type(labelText, { delay: 20 });
        // Debounce settle (some inputs have local filter; ajax handled elsewhere).
        await page.waitForTimeout(200);
    }

    const items = drop.locator('li.select2-result-selectable');
    await items.first().waitFor({ state: 'visible', timeout: 5000 });

    const target = exact
        ? items.filter({ has: page.locator(`.select2-result-label:text-is("${labelText}")`) }).first()
        : items.filter({ hasText: labelText }).first();

    await expect(target).toBeVisible({ timeout: 3000 });
    await target.click();

    // Drop should close on selection.
    await drop.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});

    // Verify the container's chosen span reflects the pick.
    const chosen = page.locator(`#${containerId} span.select2-chosen`).first();
    if (await chosen.isVisible({ timeout: 1000 }).catch(() => false)) {
        const text = (await chosen.textContent().catch(() => '')) || '';
        console.log(`✅ select2 single (${containerId}) chosen: "${text.trim()}"`);
    }
}

/**
 * Pick one or more values in a select2 MULTI widget.
 * For `select2tags` fields (category, stations), each pick renders as
 * `li.select2-search-choice` inside `ul.select2-choices` (formbuilder.js.html.twig:359).
 */
export async function pickSelect2Multi(
    page: Page,
    containerId: string,
    values: string[]
): Promise<void> {
    const container = page.locator(`#${containerId}`);
    for (const value of values) {
        await openSelect2Multi(page, containerId);
        const drop = activeSelect2Drop(page, true);

        const search = drop.locator('input.select2-input').first();
        if (await search.isVisible({ timeout: 800 }).catch(() => false)) {
            await search.fill('');
            await search.type(value, { delay: 20 });
            // Wait for local filter — long enough to disambiguate prefix collisions
            // (e.g. "Corporate Contest" vs "Corporate Content").
            await page.waitForTimeout(300);
        }

        const items = drop.locator('li.select2-result-selectable');
        await items.first().waitFor({ state: 'visible', timeout: 5000 });

        // Prefer exact label match to avoid picking a prefix collision.
        let target = items.filter({ has: page.locator(`.select2-result-label:text-is("${value}")`) }).first();
        if (!(await target.isVisible({ timeout: 600 }).catch(() => false))) {
            target = items.filter({ hasText: value }).first();
        }
        await expect(target).toBeVisible({ timeout: 3000 });
        await target.click();

        // Confirm the tag rendered under the container.
        const tag = container.locator('ul.select2-choices li.select2-search-choice')
            .filter({ hasText: value }).first();
        await expect(tag).toBeVisible({ timeout: 3000 });

        // Cat-change-checker (functions.js.html.twig:13499) may revoke the pick 300ms
        // later with a toast. Assert the tag is still there after settle.
        await page.waitForTimeout(400);
        if (!(await tag.isVisible().catch(() => false))) {
            const toast = page.locator('.toast-error, .toast-message').last();
            const msg = await toast.textContent().catch(() => '') || '';
            throw new Error(
                `select2 multi (${containerId}) pick "${value}" was rejected by cat_change_checker. Toast: "${msg.trim()}"`
            );
        }
        console.log(`✅ select2 multi (${containerId}) tagged: "${value}"`);
    }
}

/**
 * Pick a value from an ajax-backed select2 widget (ghost picker, select2typeahead).
 * Handles `minimumInputLength` gating (default 3) and `quietMillis` throttle
 * (ghost is 2000ms per adminjs.html.twig:94). Single .type() burst of ≥ minChars
 * keys, then wait quietMillis + XHR RTT.
 */
export async function pickSelect2Ajax(
    page: Page,
    containerId: string,
    query: string,
    options: { minChars?: number; quietMillis?: number; exact?: boolean } = {}
): Promise<void> {
    const { minChars = 3, quietMillis = 2000, exact = false } = options;

    if (query.length < minChars) {
        throw new Error(`pickSelect2Ajax: query "${query}" shorter than minimumInputLength ${minChars} — XHR will not fire.`);
    }

    const drop = await openSelect2Single(page, containerId);

    const search = drop.locator('input.select2-input').first();
    await expect(search).toBeVisible({ timeout: 3000 });
    await expect(search).toBeFocused({ timeout: 2000 }).catch(() => { /* focus is best-effort */ });

    // Single burst — retyping resets quietMillis.
    await search.fill('');
    await search.type(query, { delay: 20 });

    // Wait for the "Searching…" li to appear then disappear.
    const searching = drop.locator('li.select2-searching');
    await searching.first().waitFor({ state: 'attached', timeout: 3500 }).catch(() => {});
    await page.waitForTimeout(quietMillis + 500);
    await searching.first().waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});

    const items = drop.locator('li.select2-result-selectable');
    const count = await items.count();
    if (count === 0) {
        const noMatches = drop.locator('li.select2-no-results');
        const noMatchesVisible = await noMatches.isVisible({ timeout: 500 }).catch(() => false);
        throw new Error(
            `pickSelect2Ajax: no selectable results for "${query}" in #${containerId}${noMatchesVisible ? ' (No matches found)' : ''}`
        );
    }

    const target = exact
        ? items.filter({ has: page.locator(`.select2-result-label:text-is("${query}")`) }).first()
        : items.filter({ hasText: query }).first();

    await expect(target).toBeVisible({ timeout: 3000 });
    await target.click();

    // Drop should close.
    await drop.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => {});
    console.log(`✅ select2 ajax (${containerId}) picked: "${query}"`);
}

/**
 * Close any open select2 drop by pressing Escape on the search input.
 * Use this for recovery only — normal selection closes the drop automatically.
 */
export async function closeAnySelect2Drop(page: Page): Promise<void> {
    const drop = page.locator('body > div.select2-drop-active').first();
    if (await drop.isVisible({ timeout: 300 }).catch(() => false)) {
        await drop.locator('input.select2-input').first().press('Escape').catch(() => {});
        await drop.waitFor({ state: 'hidden', timeout: 2000 }).catch(() => {});
    }
}
