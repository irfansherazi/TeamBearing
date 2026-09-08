# primeng_rules.md
# vsuitePlatform Frontend UI Rules — AI Agent Knowledge Base
# Location: backend/kb/profiles/primeng_rules.md

**Source:** Live audit of vsuitePlatform Angular 19 / PrimeNG 19 source code (full `src/app/` scan)  
**Audited Paths (Phase 1 — productionorders module):**
- `src/app/user/vppo/modules/productionorders/productionorders.html`
- `src/app/user/vppo/modules/productionorders/spot-row/spot-row.component.html`
- `src/app/user/vppo/modules/productionorders/spot-compact/spot-compact.component.html`
- `src/app/user/vppo/modules/productionorders/cart-col/cart-col.component.html`
- `src/app/user/vppo/modules/productionorders/status-col/status-col.component.html`
- `src/app/user/vppo/modules/productionorders/client-col/client-col.component.html`
- `src/app/user/vppo/modules/productionorders/poc-col/poc-col.component.html`
- `src/app/user/vppo/modules/productionorders/startend-col/startend-col.component.html`
- `src/app/user/vppo/modules/productionorders/spotbulk/spotbulk.component.html`
- `src/app/user/vppo/modules/productionorders/productionorders.scss`
- `src/app/user/common/quickorders/quickorders.html`

**Audited Paths (Phase 2 — full app scan):**
- `src/app/app.component.html` — global `p-toast`
- `src/app/user-wrapper/user-wrapper.component.html` — all `p-confirmDialog` variants, `p-dialog`
- `src/app/user/shared/+vFields/vFields.html` — `p-fileupload`, `p-dialog`, `p-datepicker`
- `src/app/user/shared/v-import/v-import.component.html` — `p-fileupload`
- `src/app/user/shared/+vSpotFilters/simple-search/simple-search.component.html` — `p-datepicker`
- `src/app/user/shared/+vSpotFilters/power-search.html` — `p-datepicker`
- `src/app/user/admin/modules/users/users.component.html` — `p-dialog`
- `src/app/user/vagency/modules/agency/agency.html` — `p-fileupload`, `p-dialog`
- `src/app/user/vtrade/modules/trade/trade.component.html` — `p-datepicker`, `p-dialog`, `p-fileupload`

**Version:** Angular 19 + PrimeNG 19 (`p-table`, `p-select`, `p-autocomplete`, `p-popover`, `p-datepicker`, `p-dialog`, `p-confirmdialog`, `p-fileupload`, `p-toast`)  
**Last Updated:** 2026-04-20 (Phase 2 full-app expansion)

---

> **CRITICAL GLOBAL RULE:** This application uses **Angular 19 with PrimeNG 19**. PrimeNG 19 renders most overlay panels (dropdowns, popovers, menus) **appended to `document.body`** via `appendTo="body"`. These panels are NOT children of their trigger element. NEVER attempt to locate overlay content relative to the trigger. Always query `document.body` or use the panel's own CSS class directly. Do NOT use `page.get_by_text()` for PrimeNG list items — these are `<li>` or `<span>` elements whose text content may be altered by Angular's `language_pipe`. Always prefer `locator()` with stable CSS selectors.

---

> ⭐ **MANDATORY TOOL OVERRIDE — HIGHEST PRIORITY RULE IN THIS FILE:**
>
> **YOU MUST USE THE `primeng_dropdown` ACTION** for every interaction with:
> - Any **standard** PrimeNG `p-select` or `p-autocomplete` dropdown (e.g., Quick Filter, Status)
> - The `#sort-btn` (Compact View Sort By button) → portal `.sort-panel`
>
> **⛔ EXCEPTION — CUSTOM COMBOBOX COLUMN HEADERS (Due/Days, Start/End):**
> - Do **NOT** use `primeng_dropdown` for the "Due / Days" or "Start / End" column headers.
> - These are **CUSTOM comboboxes** using `.po-sorting-dropdown-panel` — the `primeng_dropdown` macro
>   will fail because these elements do not behave like standard PrimeNG `p-select` portals.
> - Instead, use a **TWO-STEP click approach**:
>   1. Click the column header (e.g., `th.po-col-duedaysCol p-select`) to open `.po-sorting-dropdown-panel`.
>   2. Click the target option text inside that panel.
> - Use `coordinate_action` or a standard `click` with `strategy='css_selector'`.
>
> **Correct format for standard dropdowns:**
> ```json
> {"action": "primeng_dropdown",
>  "trigger_selector": "#sort-btn",
>  "target_text": "Due Date",
>  "portal_class": ".sort-panel"}
> ```
>
> **Correct format for Due/Days column (TWO-STEP, NOT primeng_dropdown):**
> ```json
> Step 1: {"action": "click", "strategy": "css_selector", "name": "th.po-col-duedaysCol p-select"}
> Step 2: {"action": "click", "strategy": "get_by_text", "name": "Due Date A-Z",
>          "container_selector": ".po-sorting-dropdown-panel"}
> ```
>
> **NEVER use this (will cause infinite toggle loop):**
> ```json
> {"action": "click", "strategy": "css_selector", "name": "#sort-btn"}
> ```

---

## 1. Data Tables & Pagination — List View (`po-table-wrapper`)

**UI Component:** Production Orders List View — `p-table` (PrimeNG DataTable)

**How it appears in the DOM:**
The main production orders List View is rendered inside a `<div class="po-table-wrapper [viewClassName]">` wrapper element. The view class is one of: `.modern`, `.classic`, `.minimal`, `.normal`. Inside, PrimeNG renders a `<p-table>` with `styleClass="sticky-pagination"`, which produces a standard HTML `<table>` with `<thead>`, `<tbody>`, and a PrimeNG paginator. The paginator button selectors:
- **Next page:** `.p-paginator-next` button (contains `.p-paginator-next-icon`)
- **Previous page:** `.p-paginator-prev` button
- **First page:** `.p-paginator-first` button
- **Last page:** `.p-paginator-last` button
- **Rows-per-page dropdown:** `p-select` within `.p-paginator`

The Compact View is a completely separate component (`app-spot-compact`) and does NOT use `p-table` or `.p-paginator`.

Column headers are `<th>` elements with class `table-th` and a column-specific class like `.po-col-clientCol`, derived from `'po-col-' + col.id`.

**Strict Action Rule:**
- **IF** clicking "Next Page" in the List View, **THEN** use `page.locator('.p-paginator-next').click()`. **DO NOT** use `get_by_text('Next')` or `get_by_role('button', name='Next')` — the paginator button contains only an icon, no visible text.
- **IF** changing rows per page, **THEN** locate the `p-select` inside `.p-paginator`, click to open the portal on `document.body` with class `.p-select-overlay`, then click the desired `<li>` option.
- **DO NOT** assume Compact View has a paginator — it uses infinite scroll on `#compact-card-list`.

**Verification Goal:**
- Pagination succeeded: `.p-paginator-page.p-highlight` contains the expected page number.
- Table has data: `tbody tr` count inside `.po-table-wrapper` is greater than 0.
- Table is loading: Presence of `app-v-loader.po-table-loader` OR `.p-datatable-loading-overlay`.

---

## 2. Data Tables — Column Header Identification

**UI Component:** Production Orders table column headers (`<th class="table-th po-col-[colId]">`)

**How it appears in the DOM:**
Each `<th>` in the table header gets two deterministic classes:
1. `table-th` — always present on all column headers
2. `po-col-[col.id]` — where `col.id` is the Angular-side identifier:
   - `po-col-checkboxOnlyCol` — row selection checkbox column
   - `po-col-clientCol` — Client column
   - `po-col-pocCol` — Points of Contact column
   - `po-col-duedaysCol` — Due / Days column
   - `po-col-startendCol` — Start/End Date column
   - `po-col-contractCol` — Contract column
   - `po-col-lengthCol` — Length column
   - `po-col-rotationCol` — Rotation column
   - `po-col-statusCol` — Status/Tasks column
   - `po-col-cartCol` — Cart ID column (Traffic)
   - `po-col-filesCol` — Files column

**Strict Action Rule:**
- **IF** clicking a specific column header, **THEN** use `page.locator('th.po-col-[colId]').click()`. For example: `page.locator('th.po-col-clientCol').click()`.
- **DO NOT** use `page.get_by_text('Client')` for column header clicks — the same text may appear multiple times in the DOM.
- **IF** the column uses `col.reorderOptions` (e.g., Due/Days), do NOT click the `<th>` for sorting — use the `p-select` inside. See Section 4 (Sorting).

**Verification Goal:**
- Column header exists: `document.querySelector('th.po-col-duedaysCol')` is not null.
- Table is in the correct view mode: `document.querySelector('.po-table-wrapper.modern')` for Modern view.

---

## 3. Data Tables — Global Search & Filters

**UI Component:** Quick Filter Dropdown (`p-select#user-filter-header-drop-down`) and Search panel

**How it appears in the DOM:**
The header bar contains a `<p-select>` with `inputId="user-filter-header-drop-down"` and `panelStyleClass="quick-filter-panel"`. When clicked, it appends a `.quick-filter-panel` overlay portal to `document.body`. Search is triggered via a button with `id="top-open-search-panel"` (top) or `id="footer-open-search-panel"` (footer), which opens a `p-menu` portal on `document.body`.

There is NO persistent global text search input in the main list view.

> ⭐ **MANDATORY:** Use `primeng_dropdown` for the Quick Filter `p-select`. Do NOT use `action="click"` on the trigger.

**Strict Action Rule:**
- **IF** applying a Quick Filter (e.g., "My Orders"), **THEN**:
  ```json
  {"action": "primeng_dropdown",
   "trigger_selector": "p-select#user-filter-header-drop-down",
   "target_text": "My Orders",
   "portal_class": ".quick-filter-panel"}
  ```
  **CRITICAL:** You MUST use the `primeng_dropdown` action here.
  DO NOT use `action="click"` on the `p-select` trigger — it causes a toggle loop on the second attempt.
  DO NOT use `.p-dropdown-panel` — removed in PrimeNG 19. The correct portal class is `.quick-filter-panel`.
- **IF** opening search, **THEN** use `action="click"` on `#top-open-search-panel` (this is a regular
  button, NOT a PrimeNG dropdown portal, so standard click is safe here).

**Verification Goal:**
- Quick filter applied: the `p-select[inputid="user-filter-header-drop-down"]` trigger label text changes to the selected filter name.
- Search panel open: `page.locator('.p-menu').is_visible()` returns true.

---

## 4. Sorting — List View (Sortable Column Headers)

**UI Component:** PrimeNG `[pSortableColumn]` directive + `p-sortIcon` + custom combobox headers

**How it appears in the DOM:**
For standard sortable columns (Client, Status, Length, Rotation, Contract, Files), the `<th>` element has the `[pSortableColumn]` Angular directive. When sorting is active, PrimeNG adds `aria-sort="ascending"` or `aria-sort="descending"` to the `<th>` element.

**Columns sortable via direct `<th>` click (standard click IS safe here — no portal overlay):**
- clientCol, statusCol, contractCol, lengthCol, rotationCol, cartCol, filesCol
- These are plain `<th>` elements with no PrimeNG portal. `action="click"` is correct.

**Columns NOT sortable via header click — MUST use TWO-STEP CLICK (NOT primeng_dropdown):**
- `duedaysCol` — has `[pSortableColumnDisabled]="true"`. The `<th>` click is DISABLED. It uses
  `p-select#header-sort-drop-down-duedaysCol` with `panelStyleClass="po-sorting-dropdown-panel"`.
- `startendCol` — same pattern: `[pSortableColumnDisabled]="true"`, uses
  `p-select#header-sort-drop-down-startendCol`.

> ⛔ **CRITICAL: DO NOT USE `primeng_dropdown` FOR Due/Days OR Start/End COLUMNS.**
> These are CUSTOM comboboxes. The executor will BLOCK `primeng_dropdown` for these elements.
> You MUST use a TWO-STEP click approach:
>   Step 1: Click the column header trigger to open `.po-sorting-dropdown-panel`.
>   Step 2: Click the target option inside that panel.

**Strict Action Rule:**
- **IF** sorting by a standard sortable column (e.g., Client A→Z), **THEN**:
  1. `{"action": "click", "strategy": "css_selector", "name": "th.po-col-clientCol"}`
  2. Wait for `aria-sort="ascending"` on that `<th>`.
  3. For descending: click the same `<th>` again.
  4. **DO NOT** click the `.pi-sort-up` or `.pi-sort-down` icons — they are non-interactive `<i>` elements.

- **IF** sorting by Due/Days (`duedaysCol`), **THEN** use TWO-STEP CLICK:
  Step 1: Click the trigger:
  ```json
  {"action": "click", "strategy": "css_selector", "name": "th.po-col-duedaysCol p-select"}
  ```
  Step 2: Click the option inside the panel:
  ```json
  {"action": "click", "strategy": "get_by_text", "name": "Due Date A-Z",
   "container_selector": ".po-sorting-dropdown-panel"}
  ```
  > ⚠️ **Do NOT use `p-select#header-sort-drop-down-duedaysCol`** — that ID is on the inner
  > `<input>` element, NOT the host `<p-select>`. Use the `th.po-col-duedaysCol p-select` form.

  Available `target_text` values for Due/Days:
  - `"Due Date A-Z"` → oldest due date first
  - `"Due Date Z-A"` → newest due date first
  - `"Days A-Z"` → fewest days first
  - `"Days Z-A"` → most days first
  - `"Submitted On A-Z"` → oldest submitted first
  - `"Submitted On Z-A"` → most recently submitted first

- **IF** sorting by Start/End (`startendCol`), **THEN** use TWO-STEP CLICK:
  Step 1:
  ```json
  {"action": "click", "strategy": "css_selector", "name": "th.po-col-startendCol p-select"}
  ```
  Step 2:
  ```json
  {"action": "click", "strategy": "get_by_text", "name": "Start Date A-Z",
   "container_selector": ".po-sorting-dropdown-panel"}
  ```

- **FORBIDDEN:** `{"action": "primeng_dropdown", ... "trigger_selector": "th.po-col-duedaysCol p-select"}` ← WILL BE BLOCKED BY EXECUTOR
- **FORBIDDEN:** `{"action": "click", ... "name": "th.po-col-duedaysCol"}` ← th click is DISABLED in HTML
- **FORBIDDEN:** `{"trigger_selector": "p-select#header-sort-drop-down-duedaysCol"}` ← WRONG SELECTOR — use `th.po-col-duedaysCol p-select`

**Verification Goal:**
- Standard column sorted ascending: `page.locator('th.po-col-clientCol').get_attribute('aria-sort') == 'ascending'`
- Standard column sorted descending: `page.locator('th.po-col-clientCol').get_attribute('aria-sort') == 'descending'`

---

## 5. Sorting — Compact View (`compact-view-wrapper`)

**UI Component:** Compact View Sort Button + `p-popover` sort panel

**How it appears in the DOM:**
In Compact View, `p-table` and `[pSortableColumn]` do NOT exist. Sorting uses the `<button id="sort-btn" class="sort-btn">` in the header bar. Clicking it opens a `<p-popover>` with `[styleClass]="'sort-panel'"`, appended to `document.body` as `.sort-panel`. Inside is a `<ul>` with `<li>` items for each sort field.

Sort direction indicator: `<i class="sort-arrow ml-1">` inside `#sort-btn`. Class `.up` = ascending, no `.up` = descending.

> ⭐ **MANDATORY TOOL RULE — Compact View Sort:**
> CRITICAL: You MUST use the `primeng_dropdown` action for ALL Compact View sorting.
> DO NOT use the standard `click` action on `#sort-btn`.
> Set `trigger_selector` to `"#sort-btn"`, set `target_text` to the desired field label,
> and set `portal_class` to `".sort-panel"`.
> Using `action="click"` on `#sort-btn` WILL cause an infinite toggle loop on the second
> planning step because the second click closes the `.sort-panel` instead of selecting an option.

**Strict Action Rule:**
- **IF** sorting in Compact View, **THEN** use `primeng_dropdown`:
  ```json
  {"action": "primeng_dropdown",
   "trigger_selector": "#sort-btn",
   "target_text": "Due Date",
   "portal_class": ".sort-panel"}
  ```
  Available `target_text` values (exact visible text from the `.sort-panel` `<li>` items):
  - `"Client"` — sort by Client name
  - `"Title"` — sort by Spot Title
  - `"Status"` — sort by Status
  - `"Due Date"` — sort by Due Date
  - `"Submit Date"` — sort by Submit Date

- **IF** flipping sort direction (same field, toggle), **THEN** emit a second `primeng_dropdown`
  with the same `target_text`. The server toggles `sort_check` on repeat selection.
- **DO NOT** look for `aria-sort` attributes in Compact View — they do not exist.
- **DO NOT** click `.sort-arrow` directly — it is decorative only.
- **FORBIDDEN:** `{"action": "click", "strategy": "css_selector", "name": "#sort-btn"}` ← WILL TOGGLE-LOOP

> ⚡ **CRITICAL RULE — Atomic Dropdown Interactions (applies to ALL dropdowns and sort panels):**
> Before clicking any dropdown trigger (e.g., `#sort-btn`, a `.p-select-label`), you **MUST** first check
> whether the overlay portal is **ALREADY VISIBLE** on the page.
>
> **Decision tree:**
> - If `page.locator('.sort-panel').is_visible()` returns **true** → the panel is open.
>   **DO NOT** click `#sort-btn` again. Clicking the trigger a second time will **close** the menu.
>   **Immediately** execute the option click scoped to the portal using `container_selector`:
>   ```json
>   {"action": "click", "strategy": "get_by_text", "name": "Client Name", "container_selector": ".sort-panel"}
>   ```
> - If the panel is **not** visible → click the trigger to open it, then wait for the panel, then click the option.
>
> **NEVER** use a generic `page.get_by_text("Client Name")` without `container_selector`. PrimeNG renders the
> same text in BOTH the closed trigger label AND the open portal, causing Strict Mode Violations.
> Always scope via `container_selector` set to the portal class (e.g., `.sort-panel`, `.p-select-overlay`,
> `.po-sorting-dropdown-panel`).

> ⛔ **FORBIDDEN SELECTOR SYNTAX — css_selector + :has-text() on PrimeNG lists:**
> Do **NOT** use `css_selector` with `:has-text()` or `:has()` pseudo-classes for dropdown options.
> PrimeNG wraps option text in nested `<span>` elements, causing `:has-text()` to match the outer `<li>`
> but land the click on the wrong element, or fail with a Strict Mode Violation.
>
> | ❌ WRONG (will break) | ✅ CORRECT |
> |---|---|
> | `{"strategy": "css_selector", "name": ".sort-panel li:has-text('Client Name')"}` | `{"strategy": "get_by_text", "name": "Client Name", "container_selector": ".sort-panel"}` |
> | `{"strategy": "css_selector", "name": ".p-select-overlay .p-select-option:has-text('Due Date')"}` | `{"strategy": "get_by_text", "name": "Due Date", "container_selector": ".p-select-overlay"}` |
> | `{"strategy": "css_selector", "name": ".po-sorting-dropdown-panel .po-sorting-dropdown-items:has-text('Due Date A-Z')"}` | `{"strategy": "get_by_text", "name": "Due Date A-Z", "container_selector": ".po-sorting-dropdown-panel"}` |

**Verification Goal:**
- Sort panel opened: `page.locator('.sort-panel').is_visible()` returns true.
- Sort field applied: `page.locator('#sort-btn').text_content()` contains the expected field name.
- Sort direction ascending: `page.locator('#sort-btn i.sort-arrow').has_class('up')` returns true.

---

## 6. Dropdowns & Overlays — `p-select` (PrimeNG 19 Dropdown)

**UI Component:** PrimeNG 19 `p-select` (formerly `p-dropdown`)

**How it appears in the DOM:**
`p-select` renders as `<div class="p-select p-component p-inputwrapper">`. When opened, the panel appends to `document.body` (or `appendTo` target). Panel CSS classes:
- **Base panel class:** `.p-select-overlay` (PrimeNG 19 standard)
- **Custom panel class:** value of `panelStyleClass` binding (e.g., `quick-filter-panel`, `po-sorting-dropdown-panel`)

**Key instances:**

| inputId | trigger_selector | portal_class |
|---|---|---|
| `user-filter-header-drop-down` | `p-select#user-filter-header-drop-down` | `.quick-filter-panel` |
| `header-sort-drop-down-duedaysCol` | `th.po-col-duedaysCol p-select` | `.po-sorting-dropdown-panel` |
| `header-sort-drop-down-startendCol` | `th.po-col-startendCol p-select` | `.po-sorting-dropdown-panel` |
| Status row dropdown | `p-select[inputid^="status-"]` | `.p-select-overlay` |

> ⚠️ **IMPORTANT — `inputId` maps to the INNER `<input>`, NOT the host `<p-select>`:**
> PrimeNG 19 applies `inputId` to the hidden `<input>` element rendered inside `<p-select>`.
> This means `p-select#header-sort-drop-down-duedaysCol` is **INVALID CSS** that will always
> time out with a Timeout 10000ms error.
>
> Use the column-scoped selector instead:
> - ✅ `th.po-col-duedaysCol p-select` → correct
> - ❌ `p-select#header-sort-drop-down-duedaysCol` → broken (id is on inner `<input>`)

> ⭐ **MANDATORY TOOL RULE — Standard `p-select` interactions (NOT Due/Days or Start/End):**
> CRITICAL: You MUST use the `primeng_dropdown` action for standard `p-select` interactions
> (Quick Filter, Status dropdowns, etc.).
> DO NOT use the standard `click` action on a `p-select` trigger, `.p-select-label`, or
> any `p-select` wrapper element for standard dropdowns. Doing so causes a toggle loop.
>
> **⛔ EXCEPTION:** The Due/Days and Start/End column header `p-select` elements are
> CUSTOM comboboxes — use the TWO-STEP click approach described in Section 4.
> The executor will BLOCK `primeng_dropdown` for these elements.

**Strict Action Rule:**
- **IF** interacting with ANY `p-select`, **THEN** use `primeng_dropdown`:
  ```json
  {"action": "primeng_dropdown",
   "trigger_selector": "<CSS selector for the p-select element>",
   "target_text": "<exact visible text of the option>",
   "portal_class": "<panelStyleClass or .p-select-overlay>"}
  ```
  **DO NOT** use `.p-dropdown-panel` — **does not exist in PrimeNG 19**.
  **DO NOT** use `page.get_by_role('option')` — PrimeNG options are `<li>` elements, not ARIA `option` roles.
  **DO NOT** emit `action="click"` targeting any `p-select`, `.p-select-label`, or `.p-select-trigger`.

- **IF** the portal is ALREADY VISIBLE and you need to click an option without re-triggering,
  use `action="click"` scoped with `container_selector` (this is the only safe use of click here):
  ```json
  {"action": "click", "strategy": "get_by_text", "name": "My Option",
   "container_selector": ".p-select-overlay"}
  ```
  But prefer `primeng_dropdown` — it handles the portal-already-open case gracefully.

- **FORBIDDEN:** `{"action": "click", ... "name": ".p-select-label"}` ← TOGGLE-LOOP
- **FORBIDDEN:** `{"action": "click", ... "name": "p-select#..."}` ← TOGGLE-LOOP
- **FORBIDDEN:** `{"action": "select_option", ...}` on `p-select` — not a native `<select>` element

**Verification Goal:**
- Dropdown open: `page.locator('.p-select-overlay').is_visible()` returns true.
- Option selected: Trigger `.p-select-label` text matches expected value.
- Overlay closed: `page.locator('.p-select-overlay').is_visible()` returns false.

---

## 7. Dropdowns & Overlays — `p-autocomplete` (Status Dropdown)

**UI Component:** Status column `p-autocomplete` (Modern View & Compact View)

**How it appears in the DOM:**
The Status column uses `<p-autocomplete>` with `[dropdown]="true"` — NOT `p-select`. Input IDs:
- Modern view: `inputId="status-dropdown-[spot.id]"`
- Compact view: `inputId="compact-status-dropdown-[spot.id]"`

Panel class when open: `.p-autocomplete-panel` (appended to `document.body`). Options are `<li class="p-autocomplete-item">` with child `<div style="font-size: 11px">` containing status text.

The autocomplete is **only rendered when `spot._showSpotStatusList === true` AND `spot._canEdit === true`**.

**Strict Action Rule:**
- **IF** changing spot status (Modern View), **THEN**:
  1. Locate: `page.locator(f'#status-dropdown-{spot_id}')`.
  2. Click the dropdown arrow button: `.p-autocomplete-dropdown` button inside the `p-autocomplete` wrapper.
  3. Wait for `.p-autocomplete-panel` on `document.body`.
  4. Click: `page.locator('.p-autocomplete-panel .p-autocomplete-item').filter(has_text='In Production').click()`.
  5. **DO NOT** use `.p-select-overlay` — status uses `p-autocomplete`, not `p-select`.
  6. **DO NOT** type if the spot is read-only (no autocomplete rendered, only plain `<div id="dropdownListOff">` text).

**Verification Goal:**
- Panel open: `page.locator('.p-autocomplete-panel').is_visible()` returns true.
- Status updated: `page.locator(f'#status-dropdown-{spot_id}').input_value()` equals the new status.

---

## 8. Dropdowns & Overlays — `p-popover` (General Overlay Panels)

**UI Component:** PrimeNG 19 `p-popover` (formerly `p-overlayPanel`)

**How it appears in the DOM:**
`p-popover` renders as `<div class="p-popover p-component">` appended to `document.body`. Custom `[styleClass]` values are appended to that element.

**Key `p-popover` instances:**

| Context | styleClass | Trigger |
|---|---|---|
| POC assignment (Modern View) | `modern-overlay modern-ui poc-overlay` | Click `.poc-job-container` |
| POC assignment (Compact View) | `modern-overlay modern-ui poc-overlay compact-overlay-poc-picker` | `id="compact-overlay-poc-picker"` |
| Client info detail | `spot-list-view-overlay-panel` | Click `i.fa.fa-info-circle.client-info-edit-icon` |
| Sorting panel (Compact) | `sort-panel` | `id="sort-btn"` |
| Approvals count | `approval-overlay` | Click approvals icon in Compact View |

**Strict Action Rule:**
- **IF** waiting for a `p-popover`, **THEN** use `page.locator('.p-popover').wait_for(state='visible')`. For specific instance: `page.locator('.poc-overlay').wait_for(state='visible')`.
- **IF** closing a dismissable `p-popover`, **THEN** press `Escape` or click outside. For panels with a close icon use `.overlay-close` click.
- **DO NOT** use `.p-overlay-panel` — **does not exist in PrimeNG 19**.

**Verification Goal:**
- Panel open: `page.locator('.p-popover').is_visible()` returns true.
- Panel closed: `page.locator('.p-popover').is_visible()` returns false.

---

## 9. Dropdowns & Overlays — `p-menu` (Popup Menus)

**UI Component:** PrimeNG `p-menu` with `[popup]="true"`

**How it appears in the DOM:**
`p-menu` popup renders `<div class="p-menu p-component">` on `document.body`. Menu items are `<li class="p-menu-item"><a class="p-menu-item-link"><span class="p-menu-item-label">`.

Key instances:
- Settings/View Options: `id="settings-btn"` trigger → model `poViewOptions`.
- Search options: `id="top-open-search-panel"` trigger.
- QO Settings: `p-menu#menu` inside quickorders sidebar.

**Strict Action Rule:**
- **IF** opening Settings menu, **THEN** click `page.locator('#settings-btn').click()` and wait for `.p-menu` to be visible.
- **IF** clicking a menu item, **THEN** `page.locator('.p-menu .p-menu-item-label').filter(has_text='Classic').click()`.
- **DO NOT** use `.p-dropdown-item` or `.p-menuitem` — PrimeNG 19 uses `.p-menu-item` and `.p-menu-item-label`.

**Verification Goal:**
- Menu open: `page.locator('.p-menu').is_visible()` returns true.
- Menu closed after selection: `page.locator('.p-menu').is_visible()` returns false.

---

## 10. Action Menus — POC Column Delegation Panel

**UI Component:** POC Column (`app-vppo-poc-col`) — Job Delegation Panel

**How it appears in the DOM:**

**Modern/List View:** Each job is `<div class="poc-job-container [_isEditableClass]">`. Click opens a `p-popover` with `styleClass="modern-overlay modern-ui poc-overlay"` (defined in `productionorders.html`).

**Compact View:** Each job has `<i id="overlayButton" class="fa fa-angle-down">` inside `.poc-users-data`. Opens `p-popover` with `id="compact-overlay-poc-picker"` and `styleClass="modern-overlay modern-ui poc-overlay compact-overlay-poc-picker"` (defined in `poc-col.component.html`).

Inside the panel:
```html
<div class="accordion">
  <div class="accordion-header">Users</div>
  <div class="accordion-content">
    <input class="search-field" placeholder="Search..." />
    <li class="p-select-option"> [User Name] </li>
  </div>
</div>
```

**Strict Action Rule:**
- **IF** assigning a POC (e.g., Writer), **THEN**:
  1. Click: `page.locator('.poc-job-container').filter(has_text='Writer').click()`.
  2. Wait: `page.locator('.poc-overlay').wait_for(state='visible')`.
  3. Optionally filter: `page.locator('.poc-overlay .search-field').fill('John')`.
  4. Click user: `page.locator('.poc-overlay .p-select-option').filter(has_text='John Doe').click()`.
  5. **DO NOT** click the `.fa.fa-caret-down.fake-dropdown-caret` icon — click the parent `.poc-job-container`.
  6. **DO NOT** use `page.get_by_role('option')` — these are `<li>` elements.
- **IF** unassigning, **THEN** click the `<i class="overlay-close">` within `<span class="b-close">` next to the user's name in the overlay.

**Verification Goal:**
- Overlay open: `page.locator('.poc-overlay').is_visible()` returns true.
- POC assigned: `.poc-job-container` for that job shows the user's name in `.poc-user-name`.

---

## 11. Action Menus — Cart Column / Job Checkboxes

**UI Component:** Cart Column (`app-vppo-cart-col`) — Cart ID inputs and Job Completion Checkboxes

**How it appears in the DOM:**
1. Cart ID input: `<input id="cart-id-input-[spot.id]" class="po-text-cart-id">` (Modern/direct view).
2. Job completion `p-checkbox` controls with dynamically-generated `inputId`:
   - Modern/Normal: `id="checkbox-shown-[spotId]-[jobName]"`
   - Compact (inline): `id="compact-job-[spotId]-[jobName]"`
   - Compact (expanded): `id="complete-job-[spotId]-[jobName]"`

**Strict Action Rule:**
- **IF** completing a job checkbox (e.g., "Dubbed"), **THEN**:
  1. Modern view: `page.locator(f'#checkbox-shown-{spot_id}-Dubbed').click()`.
  2. Compact view inline: `page.locator(f'#compact-job-{spot_id}-Dubbed').click()`.
  3. **DO NOT** use `page.get_by_label('Dubbed')` — label text varies by firm config.
- **IF** entering a Cart ID (Modern direct view), **THEN** `page.locator(f'#cart-id-input-{spot_id}').fill(value)`.
- **IF** entering a Cart ID via `p-inplace` (Normal subview), **THEN** double-click the `.po-text-cart-id` display div to activate, then fill `input.p-inputtext` inside the inplace content.

**Verification Goal:**
- Job checkbox checked: `page.locator(f'#checkbox-shown-{spot_id}-Dubbed').is_checked()` returns true.
- Cart ID saved: `page.locator(f'#cart-id-input-{spot_id}').input_value()` equals the entered value.

---

## 12. Inline Editing — Client Column (`p-inplace`)

**UI Component:** PrimeNG `p-inplace` (Spot Title, ISCI Code in client-col)

**How it appears in the DOM:**
Inline editable fields use `<p-inplace>` with `[preventClick]="true"`:
- **Single-click**: calls handler but does NOT activate editor.
- **Double-click**: activates the inplace editor (sets BehaviorSubject `titleBeingEdited$`).

Spot Title `p-inplace` has `id="{{ spot.id }}-spot-title-edit"`. When active, `pInplaceContent` shows `<input class="p-inputtext">`. Save is `<div class="inline-btn review-pass">`, cancel is `<div class="inline-btn review-fail">`.

**Strict Action Rule:**
- **IF** editing Spot Title inline, **THEN**:
  1. Double-click: `page.locator(f'#{spot_id}-spot-title-edit').dblclick()`.
  2. Wait for input: `page.locator(f'#{spot_id}-spot-title-edit input.p-inputtext').wait_for(state='visible')`.
  3. Fill: `page.locator(f'#{spot_id}-spot-title-edit input.p-inputtext').fill('New Title')`.
  4. Save: `page.locator(f'#{spot_id}-spot-title-edit .inline-btn.review-pass').click()`.
  5. **DO NOT** single-click and type — the editor does not activate on single-click.

**Verification Goal:**
- Edit mode active: `page.locator(f'#{spot_id}-spot-title-edit input.p-inputtext').is_visible()` returns true.
- Edit saved: `pInplaceDisplay` span contains the new title text.

---

## 13. Opening an Existing Quick Order (QO Form / Sidebar)

**UI Component:** Quick Order (`app-quickorders`) — Custom `app-v-sidebar`

**How it appears in the DOM:**
Clicking `<a class="title">` in the Client column triggers `parentComponent.loadProductionOrder($event)`. This opens `<app-quickorders>` → `<app-v-sidebar>` with `id="quickorders-sidebar"` (or `id="quickorders-sidebar-standard"`).

Footer action buttons (non-CRE mode only):
- `id="discard-all-drafts"` — "Discard All Drafts"
- `id="cancel-drafts"` — "Cancel"
- `id="submit-all-drafts"` — "Submit All"

**Strict Action Rule:**
- **IF** opening an existing Quick Order, **THEN**:
  1. Click: `page.locator('app-vppo-client-col a.title').nth(rowIndex).click()`.
  2. Wait: `page.locator('#quickorders-sidebar, #quickorders-sidebar-standard').wait_for(state='visible')`.
  3. **DO NOT** click `<span class="title">` — only `<a class="title">` triggers `loadProductionOrder()`.
  4. **IF** spot is read-only, the client column shows `<span class="title">` with NO `<a>` anchor — the sidebar will NOT open.
- **IF** submitting the Quick Order, **THEN** `page.locator('#submit-all-drafts').click()` and wait for sidebar to close.

**Verification Goal:**
- QO sidebar open: `page.locator('#quickorders-sidebar').is_visible()` OR `page.locator('#quickorders-sidebar-standard').is_visible()`.
- Spot form loaded: `page.locator('app-v-forms').is_visible()` inside the sidebar.
- QO submitted: sidebar not visible AND spot appears in production orders list, or success toast.

---

## 14. Context Menu (Right-Click Row Actions)

**UI Component:** PrimeNG `p-contextmenu` with `styleClass="contextMenu"`

**How it appears in the DOM:**
Right-clicking a table row with `[pContextMenuRow]` directive shows `<p-contextmenu #cm styleClass="contextMenu" appendTo="body">`, rendered as `<div class="p-contextmenu contextMenu p-component">` on `document.body`. Menu items: `<li class="p-menuitem"><a class="p-menuitem-link"><span class="p-menuitem-label">`.

Common items: Open, Add Voice, Blog, History, Copy, Extend, Revise, Reject (vary by spot state/permissions).

**Strict Action Rule:**
- **IF** accessing row-level context menu actions, **THEN**:
  1. Right-click: `page.locator('app-vppo-spot-row tr').nth(rowIndex).click(button='right')`.
  2. Wait: `page.locator('.p-contextmenu').wait_for(state='visible')`.
  3. Click action: `page.locator('.p-contextmenu .p-menuitem-label').filter(has_text='Add Voice').click()`.
  4. **DO NOT** use `page.get_by_role('menuitem')`.

**Verification Goal:**
- Context menu visible: `page.locator('.p-contextmenu').is_visible()` returns true.
- Action triggered: `.p-contextmenu` no longer visible AND expected sidebar/overlay opens.

---

## 15. View Mode Switching (List View vs. Compact View)

**UI Component:** Settings menu → View Options

**How it appears in the DOM:**
- **List View:** `<div class="po-table-wrapper [viewClass]">` containing `<p-table>`.
- **Compact View:** `<app-spot-compact>` with wrapper `<div class="compact-view-wrapper">` and `<div id="compact-card-list">`.

View changed via `id="settings-btn"` → `p-menu` popup → view option calling `setTableView()`.

**Strict Action Rule:**
- **IF** ensuring List View, **THEN**:
  1. Check: `page.locator('.po-table-wrapper').is_visible()`.
  2. If not, open: `page.locator('#settings-btn').click()`, wait for `.p-menu`, click desired view option.
  3. Wait for `.po-table-wrapper` visible.
- **IF** ensuring Compact View, **THEN**:
  1. Check: `page.locator('.compact-view-wrapper').is_visible()`.
  2. If not, open Settings and select Compact.
  3. Wait for `.compact-view-wrapper` visible.

**Verification Goal:**
- List View: `page.locator('.po-table-wrapper').is_visible()` true.
- Compact View: `page.locator('.compact-view-wrapper').is_visible()` AND `page.locator('#compact-card-list').is_visible()` both true.

---

## 16. Application Loading & Overlay Guards

**UI Component:** Loading indicators and locked states

**How it appears in the DOM:**
- **List View loader:** `<app-v-loader class="po-table-loader">` (visible when `vppoService.spotsLoading$ | async` is truthy).
- **Compact View loader:** `<app-v-loader class="po-table-loader-compact">`.
- **Spot locked indicator (List):** `<div class="locked-container">` on the row.
- **Spot locked indicator (Compact):** `<div class="locked-spot-overlay">`.
- **QO progress bar:** `<p-progressbar>` inside `#quickorders-sidebar`.

**Strict Action Rule:**
- **BEFORE** interacting with any table row or QO form content, **THEN** wait for all loaders to disappear:
  1. `page.locator('app-v-loader.po-table-loader').wait_for(state='hidden')` (List View)
  2. `page.locator('app-v-loader.po-table-loader-compact').wait_for(state='hidden')` (Compact View)
  3. `page.locator('.p-progressbar').wait_for(state='hidden')` (QO sidebar)
- **IF** `.locked-spot-overlay` or `.locked-container` is visible on a target spot, **THEN STOP** — log "Spot is locked by another user." Do NOT attempt to force-click or bypass the lock.

**Verification Goal:**
- Page fully loaded: `page.locator('app-v-loader.po-table-loader').is_visible()` returns false AND `page.locator('.po-table-wrapper').is_visible()` returns true.
- No locked spots: `page.locator('.locked-spot-overlay').count()` returns 0.

---

## ANTI-PATTERN REFERENCE — What NOT To Do

The following patterns are **guaranteed to fail** in vsuitePlatform and must NEVER be used:

| Anti-Pattern | Why It Fails | Correct Alternative |
|---|---|---|
| `action="click"` on `#sort-btn` | Causes toggle loop — second click closes portal | `action="primeng_dropdown"` with `trigger_selector="#sort-btn"` |
| `action="primeng_dropdown"` on `th.po-col-duedaysCol p-select` | Custom combobox — executor BLOCKS this | TWO-STEP: click trigger, then click option in `.po-sorting-dropdown-panel` |
| `action="primeng_dropdown"` on `th.po-col-startendCol p-select` | Custom combobox — executor BLOCKS this | TWO-STEP: click trigger, then click option in `.po-sorting-dropdown-panel` |
| `action="click"` on `p-select#header-sort-drop-down-duedaysCol` | Causes toggle loop on second step | TWO-STEP click using `th.po-col-duedaysCol p-select` then option |
| `action="click"` on any `.p-select-label` | Causes toggle loop — portal opens then closes | `action="primeng_dropdown"` with the parent `p-select` as `trigger_selector` |
| `action="select_option"` on `p-select` | PrimeNG v19 `p-select` is not a native `<select>` | `action="primeng_dropdown"` |
| `page.locator('.p-dropdown-panel')` | Class removed in PrimeNG 19 | `.p-select-overlay` |
| `page.locator('.p-overlay-panel')` | Class removed in PrimeNG 19 | `.p-popover` |
| `page.locator('p-dropdown')` | Component renamed in PrimeNG 19 | `p-select` |
| `page.get_by_role('option')` | PrimeNG options are `<li>`, not ARIA options | `.p-select-option` or `.p-autocomplete-item` |
| `page.get_by_role('button', name='Next')` | Paginator buttons contain only icons, no text | `.p-paginator-next` |
| `page.get_by_text('Client').click()` for column sort | Text appears many times in the DOM | `th.po-col-clientCol` |
| Clicking `.pi-sort-up` or `.pi-sort-down` | Non-interactive `<i>` elements | Click the parent `<th>` |
| Detecting sort state in Compact View via `aria-sort` | No `p-table` in Compact View | `#sort-btn` text content + `i.sort-arrow.up` |
| `page.get_by_label('Submit All')` | Better to use stable IDs | `#submit-all-drafts` |
| Clicking `<span class="title">` to open QO | Only `<a class="title">` triggers `loadProductionOrder()` | `app-vppo-client-col a.title` |
| Interacting before `ngIf` resolves | Angular conditionally renders DOM | Always check `is_visible()` before click |
| Interacting while loader is visible | Data is still loading | `wait_for(state='hidden')` on loaders first |
| Using `page.get_by_label('Dubbed')` for checkboxes | Label text varies by firm config | `#checkbox-shown-{spot_id}-Dubbed` |
| Using `.p-menuitem` class | PrimeNG 19 uses `.p-menu-item` | `.p-menu-item` and `.p-menu-item-label` |

---

## 17. Date Pickers — `p-datepicker` (PrimeNG 19 Calendar)

**UI Component:** PrimeNG 19 `p-datepicker` (formerly `p-calendar`)

**How it appears in the DOM:**
PrimeNG 19 renamed `p-calendar` to `p-datepicker`. Across the app, all date/calendar inputs use this component. All instances in the vsuitePlatform use `appendTo="body"`, meaning the calendar panel portal always appears on `document.body`.

**Key instances by `inputId`:**
| inputId | Location | Purpose |
|---|---|---|
| `calendar-start-date-modern-view` | `startend-col.component.html` | Start date picker (List/Modern View) |
| `calendar-end-date-modern-view` | `startend-col.component.html` | End date picker (List/Modern View) |
| `bulk-due-date-calendar` | `spotbulk.component.html` | Bulk Due Date |
| `bulk-start-date-calendar` | `spotbulk.component.html` | Bulk Start Date |
| `bulk-end-date-calendar` | `spotbulk.component.html` | Bulk End Date |
| (dynamic, in power-search/simple-search) | `power-search.html`, `simple-search.component.html` | Search date range filters |

**DOM Structure when opened:**
The calendar panel appended to `document.body` renders as:
```html
<div class="p-datepicker-panel p-component">
  <div class="p-datepicker-header"> ... </div>
  <div class="p-datepicker-calendar-container">
    <table class="p-datepicker-calendar">
      <thead> ... </thead>
      <tbody>
        <tr> <td data-p-today="true"> ... </td> </tr>
      </tbody>
    </table>
  </div>
</div>
```
Day cells: `<td>` with `data-p-today="true"` for today, `aria-label="[Month] [Day], [Year]"` on each selectable day. The `[showIcon]="false"` binding (used on most instances) means there is NO calendar icon button — clicking the `<input>` element directly opens the picker.

**Strict Action Rule:**
- **IF** opening a date picker, **THEN**:
  1. Click the `<input>` inside the `p-datepicker`: `page.locator('#calendar-start-date-modern-view').click()`.
  2. Wait for the panel: `page.locator('.p-datepicker-panel').wait_for(state='visible')`.
  3. Navigate months via `<button class="p-datepicker-prev-button">` and `<button class="p-datepicker-next-button">`.
  4. Click the target day by its `aria-label`: `page.locator('.p-datepicker-panel td[aria-label="April 25, 2026"]').click()`.
  5. **DO NOT** use `page.locator('p-calendar')` — the component is now `p-datepicker` in PrimeNG 19.
  6. **DO NOT** look for a `.p-calendar-panel` class — removed in PrimeNG 19. Use `.p-datepicker-panel`.
  7. **DO NOT** look for a calendar icon button when `[showIcon]="false"` is set — click the `<input>` directly.
  8. **IF** the instance has `[numberOfMonths]="2"` (e.g., bulk date pickers), **THEN** the panel renders two month calendars side by side — use `aria-label` to target the correct day regardless of which month panel it appears in.
- **IF** clearing a date picker input, **THEN** triple-click the input to select all, then press `Delete` or `Backspace`.
- **IF** setting a date programmatically for speed, **THEN** fill the `<input>` directly (format must match the component's `dateFormat` binding, e.g., `mm/dd/yy` or `dd/mm/yy` — check the `firmDatePickerFormat` variable in the component). After fill, press `Tab` or `Enter` to commit.

**Verification Goal:**
- Date picker open: `page.locator('.p-datepicker-panel').is_visible()` returns true.
- Date selected: `page.locator('#calendar-start-date-modern-view').input_value()` equals the formatted date string.
- Date picker closed: `page.locator('.p-datepicker-panel').is_visible()` returns false after selection.

---

## 18. Modals & Dialogs — `p-dialog` and `p-confirmDialog`

**UI Component:** PrimeNG `p-dialog` (custom dialogs) and `p-confirmDialog` (system-wide confirmation dialogs)

**How it appears in the DOM:**
All dialogs use `appendTo="body"` and render as `<div class="p-dialog p-component">` on `document.body`. There are **two distinct component types** used across the app:

### Type A: `p-dialog` (Custom Content Dialogs)
Renders as `<div class="p-dialog [styleClass]">` with a `<div class="p-dialog-header">` and `<div class="p-dialog-content">`.

**Key `p-dialog` instances:**
| styleClass | id | Purpose | Close selector |
|---|---|---|---|
| `changeFileTypeDialog` | *(none)* | Change File Type (global, `user-wrapper.component.html`) | `button.p-dialog-close-button` |
| *(inline style only)* | *(none)* | Update Product Status (`users.component.html`) | `button.p-dialog-close-button` |
| *(none)* | `poc-migration-dialog` | Migrate Spots From POC | `#poc-migration-dialog .p-dialog-close-button` |
| *(none)* | `migration-warning-dialog` | Migration Warning | `.p-dialog-close-button` |
| *(none)* | `migration-results` | Migration Results | `.p-dialog-close-button` |

The close (X) button is always `<button class="p-dialog-close-button">` inside the dialog header. The **OK/Submit/Confirm** button is inside the `<ng-template #footer>` of the dialog — it renders as `<div class="p-dialog-footer"><button ...>`.

### Type B: `p-confirmDialog` (System-Wide Confirmation Dialogs)
Registered globally in `user-wrapper.component.html`. All append to `document.body`. Rendered as `<div class="p-confirmdialog p-dialog [styleClass]">`. Interactions are driven by calling `confirmationService.confirm(...)` from TypeScript — the agent does NOT open these dialogs directly; they open in response to destructive actions.

**Known confirmation dialog keys and their `styleClass`:**
| key | styleClass | Purpose | Accept button |
|---|---|---|---|
| `delete` | `v-dialog delete-dialog` | Delete confirmation | `page.locator('.delete-dialog button.p-button:has-text("YES, DELETE")')` |
| `warningSidebar` | `v-dialog warning-dialog` | Warning before closing sidebar | `page.locator('.warning-dialog button.p-button:has-text("YES, CONFIRM")')` |
| `confirm` | `v-confirm-dialog` | Generic confirmation | `page.locator('.v-confirm-dialog .p-confirmdialog-accept-button')` |
| `confirm-no-icon` | `v-dialog warning-dialog-confirm` | Under Review confirmation | `page.locator('#confirm-button-dialog-with-no-icon')` ← **has stable ID** |
| `warning` | `v-dialog warning-dialog` | Generic warning | accept via `page.locator('.warning-dialog .p-confirmdialog-accept-button')` |
| `warning-with-no` | `v-dialog warning-dialog` | Yes/No warning | Yes: `button:has-text("Yes")`, No: `button:has-text("No")` |
| `edit-with-no` | `v-dialog edit-dialog` | Edit confirmation | Yes: `#edit-dialog-yes-btn`, No: `#edit-dialog-no-btn` ← **stable IDs** |
| `warning-with-ok` | `v-dialog warning-dialog` | Informational OK | `page.locator('.warning-dialog button:has-text("Ok")')` |
| `warning-continue` | `v-dialog warning-dialog` | Continue/Cancel | Continue: `button:has-text("Continue")`, Cancel: `button:has-text("Cancel")` |

**Strict Action Rule:**
- **IF** a `p-dialog` opens and the agent needs to confirm/save inside it, **THEN**:
  1. Wait for dialog: `page.locator('.p-dialog').wait_for(state='visible')`.
  2. Interact with form content inside `.p-dialog-content`.
  3. Click the footer accept button: `page.locator('.p-dialog-footer .p-button').last().click()` OR use a stable `id` (e.g., `#edit-dialog-yes-btn`).
  4. Wait for dialog to close: `page.locator('.p-dialog').wait_for(state='hidden')`.
- **IF** a `p-confirmDialog` appears (triggered by a destructive action), **THEN**:
  1. Wait for it: `page.locator('.p-confirmdialog').wait_for(state='visible')`.
  2. Accept via the custom footer button using its label or stable ID (see table above).
  3. Reject/Cancel: click `page.locator('.p-confirmdialog .p-confirmdialog-reject-button')` OR the "No" / "Cancel" labelled button.
- **DO NOT** use `page.get_by_role('dialog')` for targeting — PrimeNG dialogs use `<div>`, not a native `<dialog>` element.
- **DO NOT** try to open a `p-confirmDialog` directly — it only appears in response to `confirmationService.confirm()` calls triggered by prior user actions.
- **DO NOT** use `.p-dialog-mask` as an identification selector — it is the backdrop overlay, not the dialog itself.

**Verification Goal:**
- Dialog open: `page.locator('.p-dialog').is_visible()` returns true.
- Dialog closed: `page.locator('.p-dialog').is_visible()` returns false.
- ConfirmDialog resolved: `page.locator('.p-confirmdialog').is_visible()` returns false.
- Specific dialog open by styleClass: `page.locator('.delete-dialog').is_visible()` returns true.

---

## 19. File Uploaders — `p-fileupload` (PrimeNG File Upload)

**UI Component:** PrimeNG `p-fileupload` with `customUpload="true"` and `#content` / `#file` templates

**How it appears in the DOM:**
All file upload components in vsuitePlatform use the **advanced templated mode** with `customUpload="true"`. This means:
1. There is NO "Upload" button that submits files to the server automatically — the `(uploadHandler)` callback handles the actual upload.
2. The component's drop zone area renders as `<div class="p-fileupload p-component [styleClass]">` containing an inner `<div class="p-fileupload-content">` with the drag-and-drop zone.
3. The actual file `<input type="file">` is a hidden `<input>` rendered inside the component — it must be targeted with Playwright's `set_input_files()` method, NOT by clicking the drag zone.

**Key instances:**
| id | Location | `name` attr | accept | Purpose |
|---|---|---|---|---|
| `#spotFileUpload` (template ref) | `productionorders.html` | `spotFileUploader` | `mimeTypes` | Spot file upload (sidebar) |
| dynamic: `file-upload-{{field.id}}` | `vFields.html` | `myfile[]` | varies | Quick Order form file fields |
| *(no id)* | `v-import.component.html` | varies | varies | Import files |

After files are selected, they appear as queued file entries using the `#file` template slot. Each queued file shows:
- `<span class="p-fileupload-template-filename">` — displays file name (truncated)
- `<i class="overlay-close">` — removes the file from queue when clicked
- `<p-select>` — selects the file type (appended to body, standard `.p-select-overlay`)
- `<input pInputText>` — file notes field

The "drag and drop" placeholder text is: `<span class="p-fileupload-template-placeholder">Drag and drop here</span>`.

**Strict Action Rule:**
- **IF** uploading a file, **THEN**:
  1. Use Playwright's `set_input_files()` on the hidden file input — **NEVER** try to drag-and-drop a file via simulated mouse events:
     ```python
     # For the spot file uploader in productionorders:
     await page.locator('p-fileupload[name="spotFileUploader"] input[type="file"]').set_input_files('/path/to/file.mp3')
     # For a Quick Order form field:
     await page.locator(f'#file-upload-{field_id} input[type="file"]').set_input_files('/path/to/file.pdf')
     ```
  2. Wait for the file to appear in the queue: `page.locator('.p-fileupload-template-filename').is_visible()` returns true.
  3. If file type selection is required: click the `p-select` inside the queued file row and select the type from `.p-select-overlay`.
  4. Click the submit/upload button to trigger `(uploadHandler)`: look for the button with `uploadLabel` text (e.g., "Submit") inside the `p-fileupload` footer: `page.locator('p-fileupload[name="spotFileUploader"] .p-fileupload-buttonbar button:has-text("Submit")').click()`.
- **DO NOT** use `page.locator('.p-fileupload-choose').click()` and then handle a native OS file dialog — the Playwright `set_input_files()` approach bypasses the file dialog entirely and is the only reliable method.
- **DO NOT** attempt to drag a local file path string onto the `.p-fileupload-content` area — simulated drag events do not transfer local file handles.
- **IF** removing a file from the queue, **THEN** click the `<i class="overlay-close">` inside the specific queued file row.

**Verification Goal:**
- File queued: `page.locator('.p-fileupload-template-filename').is_visible()` returns true AND the file name appears.
- Upload initiated: The `(uploadHandler)` fires — verify via a success toast (`page.locator('.p-toast-message')`) or the file appearing in the spot's file list (`page.locator('.files-list')`).
- File removed from queue: `page.locator('.p-fileupload-template-filename')` count decreases by 1.

---

## 20. Toasts & Notifications — `p-toast` (PrimeNG 19 Toast)

**UI Component:** PrimeNG 19 `p-toast` (global, single instance in `app.component.html`)

**How it appears in the DOM:**
There is exactly **one** `<p-toast>` in the entire app, declared in `app.component.html` with `[style]="{ marginTop: '80px' }"`. Toast messages are triggered via `messageService.add({ ... })` calls from any component. The rendered toast container is `<div class="p-toast p-component">` (typically positioned fixed at top-right). Individual messages render as:
```html
<div class="p-toast-message-content">
  <span class="p-toast-message-icon">...</span>
  <div class="p-toast-message-text">
    <span class="p-toast-summary"><!-- title --></span>
    <div class="p-toast-detail"><!-- body text --></div>
  </div>
  <button class="p-toast-close-button"><!-- × --></button>
</div>
```

**Toast severity CSS classes** (applied on the wrapping `<div class="p-toast-message [severity]">`):
- `.p-toast-message-success` — green, success state
- `.p-toast-message-error` — red, error/failure state
- `.p-toast-message-warn` — yellow/orange, warning state
- `.p-toast-message-info` — blue, informational state

Toast messages auto-dismiss after a configurable delay (typically 3–5 seconds). They can also be manually dismissed by clicking the `×` (`p-toast-close-button`).

**Strict Action Rule:**
- **IF** verifying that an action succeeded via toast, **THEN**:
  1. Wait for a success toast: `page.locator('.p-toast-message-success').wait_for(state='visible', timeout=10000)`.
  2. Read the toast text: `page.locator('.p-toast-message-success .p-toast-summary').text_content()`.
  3. **DO NOT** use `page.get_by_role('alert')` — PrimeNG toast uses `<div>`, not ARIA `alert` role on this element.
  4. **DO NOT** block test progress waiting for toast auto-dismiss — once visible and verified, proceed to the next step.
- **IF** verifying that an action FAILED via toast, **THEN**:
  1. Wait for an error toast: `page.locator('.p-toast-message-error').wait_for(state='visible', timeout=5000)`.
  2. Read the detail: `page.locator('.p-toast-message-error .p-toast-detail').text_content()`.
- **IF** a toast is blocking a click target, **THEN** dismiss it by clicking `page.locator('.p-toast-close-button').click()` before interacting.
- **DO NOT** use `page.locator('.p-toast')` to wait — this always exists in the DOM (it is declared globally). Use the `.p-toast-message` children which only exist when a message is active.

**Verification Goal:**
- Success toast visible: `page.locator('.p-toast-message-success').is_visible()` returns true.
- Error toast visible: `page.locator('.p-toast-message-error').is_visible()` returns true.
- Toast dismissed: `page.locator('.p-toast-message').count()` returns 0.
- Toast content matches: `page.locator('.p-toast-summary').text_content()` contains expected string.

---

## ANTI-PATTERN REFERENCE — What NOT To Do

The following patterns are **guaranteed to fail** in vsuitePlatform and must NEVER be used:

| Anti-Pattern | Why It Fails | Correct Alternative |
|---|---|---|
| `action="click"` on `#sort-btn` | Causes toggle loop — second click closes portal | `action="primeng_dropdown"` with `trigger_selector="#sort-btn"` |
| `action="click"` on `p-select#header-sort-drop-down-duedaysCol` | Causes toggle loop | `action="primeng_dropdown"` with that trigger_selector |
| `action="click"` on any `.p-select-label` | Causes toggle loop | `action="primeng_dropdown"` with the parent `p-select` |
| `action="click"` on any PrimeNG combobox | Two-step pattern is not atomic | `action="primeng_dropdown"` is atomic |
| `action="select_option"` on `p-select` | Not a native HTML `<select>` element | `action="primeng_dropdown"` |
| `page.locator('.p-dropdown-panel')` | Class removed in PrimeNG 19 | `.p-select-overlay` |
| `page.locator('.p-overlay-panel')` | Class removed in PrimeNG 19 | `.p-popover` |
| `page.locator('p-dropdown')` | Component renamed in PrimeNG 19 | `p-select` |
| `page.locator('p-calendar')` | Component renamed in PrimeNG 19 | `p-datepicker` |
| `page.locator('.p-calendar-panel')` | Class removed in PrimeNG 19 | `.p-datepicker-panel` |
| `page.get_by_role('option')` | PrimeNG options are `<li>`, not ARIA options | `.p-select-option` or `.p-autocomplete-item` |
| `page.get_by_role('button', name='Next')` | Paginator buttons contain only icons, no text | `.p-paginator-next` |
| `page.get_by_role('dialog')` | PrimeNG dialogs use `<div>`, not `<dialog>` | `.p-dialog` or `.p-confirmdialog` |
| `page.get_by_role('alert')` for toasts | PrimeNG toast uses `<div>`, not ARIA alert | `.p-toast-message-success` / `.p-toast-message-error` |
| `page.get_by_text('Client').click()` for column sort | Text appears many times in the DOM | `th.po-col-clientCol` |
| Clicking `.pi-sort-up` or `.pi-sort-down` | Non-interactive `<i>` elements | Click the parent `<th>` |
| Detecting sort state in Compact View via `aria-sort` | No `p-table` in Compact View | `#sort-btn` text content + `i.sort-arrow.up` |
| `page.get_by_label('Submit All')` | Better to use stable IDs | `#submit-all-drafts` |
| Clicking `<span class="title">` to open QO | Only `<a class="title">` triggers `loadProductionOrder()` | `app-vppo-client-col a.title` |
| Interacting before `ngIf` resolves | Angular conditionally renders DOM | Always check `is_visible()` before click |
| Interacting while loader is visible | Data is still loading | `wait_for(state='hidden')` on loaders first |
| Using `page.get_by_label('Dubbed')` for checkboxes | Label text varies by firm config | `#checkbox-shown-{spot_id}-Dubbed` |
| Using `.p-menuitem` class | PrimeNG 19 uses `.p-menu-item` | `.p-menu-item` and `.p-menu-item-label` |
| Clicking file drop zone for upload | Simulated drag events don't transfer file handles | `set_input_files()` on hidden `input[type="file"]` |
| `page.locator('.p-toast')` to detect active toast | `.p-toast` always exists globally in the DOM | `.p-toast-message` children |
| Clicking `confirmationService.confirm()` directly | Not a DOM action — server-side trigger only | Wait for `.p-confirmdialog` to appear after triggering the upstream action |

---

*End of primeng_rules.md — Source: vsuitePlatform Angular 19 full-app audit, 2026-04-20*
