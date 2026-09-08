## WORKFLOW: Angular Change Detection Timing Contracts
KEYWORDS: wait, timeout, debounce, loading, spinner, angular, animation, delay, timing, slow, freeze, stuck
---
Source: vsuitePlatform/playwright/utils/OrderHelper.ts, NavHelper.ts, QO_helpers.ts

CRITICAL: Angular SPAs have asynchronous change detection (zone.js). Many failures
are NOT selector problems — they are TIMING problems. The element exists but Angular
hasn't rendered it yet.

══════════════════════════════════════════════════════════════
1. CLIENT / ADVERTISER AUTOCOMPLETE (Quick Order form)
══════════════════════════════════════════════════════════════
- After typing in the Client/Advertiser field: WAIT 500ms minimum
- The dropdown renders asynchronously via an API debounce request
- Click the dropdown option using get_by_text(clientName) NOT get_by_role('link')
- If dropdown doesn't appear after 500ms: try clicking the field again first

══════════════════════════════════════════════════════════════
2. PRIMENG CALENDAR (Date Picker — due date, start/end date)
══════════════════════════════════════════════════════════════
- Opening: click button.p-datepicker-dropdown
- After opening: wait for div.p-datepicker-panel visibility (timeout up to 5000ms)
- Day selector format: span.p-datepicker-day[data-date="YYYY-M-D"]:not(.p-disabled)
  - YEAR = 4-digit year (e.g. 2026)
  - MONTH = 0-indexed, no padding (Jan=0, Feb=1, Mar=2, Apr=3, etc.)
  - DAY = no zero-padding (8 not 08)
  - Example April 8 2026: data-date="2026-3-8"
- After selecting day: WAIT 500ms for Angular to process value
- Month navigation: use button.p-datepicker-next-button or button.p-datepicker-prev-button
- After navigating month: WAIT 300ms for re-render

══════════════════════════════════════════════════════════════
3. ANGULAR ROUTER NAVIGATION (Sidebar / Menu links)
══════════════════════════════════════════════════════════════
- Angular 19 router links DO NOT have href= attributes in the DOM
- NEVER use a[href="..."] selectors — they will always fail (count=0)
- Use get_by_text("Folder Name") or get_by_role("link", name="Folder Name")
- After clicking a sidebar/nav link: WAIT for tbody tr to be visible
- NOT networkidle — Angular routes are client-side and don't fire load events
- If click intercepted by overlay: use force=true (dispatchEvent equivalent)

══════════════════════════════════════════════════════════════
4. QUICK ORDER FORM — SUBMIT ALL BUTTON STATE
══════════════════════════════════════════════════════════════
- Submit All button is DISABLED until Angular's reactive form validates all required fields
- Required fields: Client, Ad Type, Status, Spot Title, Length, Rotation, Station(s)
- If Submit All appears disabled after filling fields: check if a required field is empty
  - Common miss: length or rotation not set
- After Submit All click: wait for URL change to contain a POID (not a fixed timeout)
- Toast "Order submitted successfully" appears within 2000ms — use transient selectors

══════════════════════════════════════════════════════════════
5. LOGIN — JWT TOKEN AVAILABILITY
══════════════════════════════════════════════════════════════
- After clicking Log In and networkidle fires: JWT may NOT be in localStorage yet
- Angular writes vc2JWT ASYNCHRONOUSLY after the API login response resolves
- Poll localStorage.getItem('vc2JWT') up to 5 seconds (10x 500ms) before declaring failure
- If still no JWT after 5s: login failed (wrong credentials or API error)

══════════════════════════════════════════════════════════════
6. TABLE / LIST RENDERING AFTER NAVIGATION
══════════════════════════════════════════════════════════════
- After navigating to a folder: rows render asynchronously
- Wait for: p-table tbody tr OR .p-datatable-tbody tr to be visible
- If no rows appear within 5s: the folder may genuinely be empty (not an error)
- Row count badges in sidebar may lag behind — do not rely on badge = row count

══════════════════════════════════════════════════════════════
7. STATUS CHANGES AND API CALLS
══════════════════════════════════════════════════════════════
- Status changes via the Quick Order form → POST/PUT API call
- Success indicator: toast notification OR URL change OR status badge update
- Use wait_for_response action to detect silent API calls:
  { "action": "wait_for_response", "value": "/api/quick-orders" }
- Toast timeout: check within 2000ms — if no toast, check URL/DOM state instead

══════════════════════════════════════════════════════════════
8. POSTACTION SETTLE WAITS (Angular zone.js)
══════════════════════════════════════════════════════════════
- After ANY click that triggers Angular state change: wait 300ms minimum
- This covers zone.js change detection cycle completing
- For API-triggered changes (form submit, status change): wait for networkidle OR response
- For pure UI changes (dropdown open, tab switch): 300ms is usually sufficient


══════════════════════════════════════════════════════════════
AUTO-EXTRACTED TIMING PATTERNS (from Playwright tests)
══════════════════════════════════════════════════════════════
- Wait 2000ms (from qa-138_basics.test.ts)
- waitForSelector: .alert.alert-danger (from invalid_login.test.ts)
- Wait 5000ms: wait for download (from qa-257-Exporting spot info.test.ts)
- Wait 2000ms: 2-second delay (from validate_login.test.ts)
- Wait 3000ms (from qa-196-files_client_upload.test.ts)
- Wait 2000ms: Wait a bit for Angular to initialize (from show_password.test.ts)
- Wait 500ms: Small delay to ensure interactivity (from qa-58-poc_counts.test.ts)
- waitForSelector: .ui-toast-message-content, .p-toast-message-content (from invalid_login.test.ts)
- Wait 1000ms (from qa-196-files_client_upload.test.ts)
- waitForSelector: #globalFilterInp (from filePreWashUtility.test.ts)
- Wait 2000ms: Wait a bit for Angular to initialize (from invalid_login.test.ts)
- waitForSelector: .alert-danger, [role= (from qa-138_basics.test.ts)
- Wait 5000ms (from qa-196-files_qo_interaction.test.ts)