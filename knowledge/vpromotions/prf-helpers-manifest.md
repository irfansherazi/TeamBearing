# PRF Playwright Helpers Manifest — vPromotions

> **Purpose:** This manifest declares the TypeScript Playwright helpers in
> `playwright/utils/prf/` and maps AC phrasing → helper invocations. It is
> consumed by:
>   - The AC parser (`backend/engine/ac_parser.py`) — to recognize helper-eligible
>     ACs and emit **one high-level plan step per helper** instead of 15+
>     atomic UI steps.
>   - The codegen (`backend/engine/computer_use/test_codegen.py`) — to emit
>     `await createPrfHappyPath({...})` calls instead of raw click/fill/wait
>     primitives.
>   - The static-test-first gate (proposed in the executor bridge design) —
>     to route PRF-creation ACs to `playwright_executor_node` before falling
>     back to the CU loop.
>
> **This file is complementary to `create-prf-helper.md`.** That file tells
> the CU loop *how to drive the UI when no static path is available*.
> This file tells the planner *which flows have a pre-built Playwright helper
> that runs in ~5-15 seconds vs. the CU loop's 20+ minutes*.
>
> **Import path (from a test in `playwright/tests/vpromotions/`)**:
> ```typescript
> import { createPrfHappyPath } from '../../utils/prf/CreatePrfHelper';
> import { ghostLogin } from '../../utils/prf/GhostLoginHelper';
> import { loginAndWaitForHomeReady } from '../../utils/prf/AuthHelper';
> // ... etc.
> ```

---

## AC → Helper Fast-Match Table

The parser matches AC step text (case-insensitive) against these phrase patterns.
First match wins. `<TICKET>` = ticket id placeholder (e.g. QA-359).

| AC phrase pattern | Helper call | Approx. wall-clock | Replaces (in CU-loop iterations) |
|---|---|---|---|
| "log in as \<user\>", "authenticate", "navigate to promo" | `loginAndWaitForHomeReady(page, baseUrl, {...})` | 5-8s | ~15 CU iters |
| "ghost as \<name\>", "ghost login", "impersonate \<name\>" | `ghostLogin(page, name)` | 3-5s | ~10 CU iters |
| "create a new PRF", "new PRF", "create PRF", "PRF happy path" | `createPrfHappyPath(page, details, {...})` | 8-12s | **~150 CU iters** |
| "open the PRF drawer", "click + New PRF" | `openPrfDrawer(page)` | 1-2s | ~5 CU iters |
| "fill title \<title\>" | `fillPrfTitle(page, title)` | <1s | ~4 CU iters |
| "select category \<cat\>", "pick category \<cat\>" | `pickPrfCategory(page, category)` | 1-2s | ~8 CU iters |
| "select stations \<list\>" | `pickPrfStations(page, [...])` | 1-3s | ~10 CU iters |
| "assign sales \<name\>", "sales assignment \<name\>" | `pickPrfSalesAssignment(page, label)` | 1-2s | ~8 CU iters |
| "set start date …", "set end date …" | `fillPrfDatePicker(page, field, value, {...})` | 1-2s | ~10 CU iters (esp. Done-button loops) |
| "fill description …", "fill play copy …" | `fillPrfTaspField(page, field, value)` | <1s | ~6 CU iters (rich-text tasp fallback) |
| "save as draft", "save the PRF as a draft" | `saveDraftPrfDrawer(page)` | 1-2s | ~5 CU iters |
| "click save", "submit for review" | `savePrf(page)` | 2-3s | ~5 CU iters |
| "approve the pending PRF", "approve PRF \<id\>" | `approvePendingPrf(page, prfId, role)` | 2-3s | ~15 CU iters |
| "revise the approved PRF" | `revisePrf(page, prfId, revisions)` | 5-8s | ~40 CU iters |
| "cancel the PRF", "click cancel" | `cancelPrfDrawer(page)` | 1-2s | ~5 CU iters |
| "upload files to the PRF" | `uploadPrfFiles(page, filePaths, description)` | 3-6s | ~20 CU iters |

**Prefer the orchestrator over primitives when the AC covers a full flow.**
For an AC like *"Create a new PRF with category Contest, stations XXXX-FM,
title 'Test' and save as draft"*, emit ONE step calling `createPrfHappyPath`
with the parsed fields — not 8 separate primitive calls.

---

## Helper Modules

### 1. `AuthHelper.ts` — SSO → Home ready

Handles the full authentication chain: navigate → detect SSO hops → submit
credentials if `/promo_login` renders → wait for FullCalendar to paint.
Cold-cache path is 5-8s; the six-milestone gate prevents snapshotting mid-render.

**Public API:**

| Function | When to invoke |
|---|---|
| `loginAndWaitForHomeReady(page, baseUrl, opts)` | **Orchestrator** — use this by default. Register dialog handler → land on `/promo` → login if needed → wait for shell + deferred content + FullCalendar. Throws on SSO landing or missing promo access. |
| `landOnPromo(page, baseUrl, useAppTest?)` | Just navigate to `/promo` (or `/app_test.php/promo` when `useAppTest=true`). Caller inspects `page.url()` to decide next step. |
| `loginIfNeeded(page, username, password)` | Submit credentials if `/promo_login` is showing; returns `true` if login happened. Non-throwing when already authenticated. |
| `waitForHomeShell(page, timeout?)` | Wait for `body.page-header-fixed` + `.header.navbar` + jQuery + `App` global. |
| `waitForDeferredHome(page, timeout?)` | Wait for the 1000ms `#pg-content` swap → `.promo_tab_div`, `#promo-all.tab-pane.active`, `#promo-calendar`. |
| `waitForFullCalendar(page, opts)` | Wait for `.fc-toolbar` and (default) `#create_new_prf`. Set `expectNewPrfButton:false` for non-create roles (ROLE_ON_AIR, etc.). |
| `registerDialogAccept(page \| context)` | Auto-accept any confirm/alert dialog. Register at **context level** before navigating so it survives page transitions. |
| `isHomeReady(page)` | Non-throwing predicate — true when calendar toolbar + create button (or role-appropriate absence) are stable. |
| `isTestEnvironment(page)` | true if URL contains `app_test.php` or JS global `currentEnv === 'test'`. |
| `promoUrl(baseUrl, useAppTest?)` | Compute the `/promo` URL for a given base + env-marker. |

**Preconditions:** none — this is the entry point.

**Post-conditions:** Home tab is fully rendered; `#create_new_prf` is visible
for creation-capable roles.

---

### 2. `GhostLoginHelper.ts` — Impersonate another user

Uses the admin ghost widget (select2 v3 ajax on `#s2id_ghost_id`) to switch
persona. **Only works** for ROLE_ADMIN / ROLE_FIRM_ADMIN / ROLE_PROMOTIONS_DIRECTOR
/ ROLE_HR (widget isn't bound for other roles — throws PRECONDITION_MISSING).

**Public API:**

| Function | When to invoke |
|---|---|
| `ghostLogin(page, name)` | **Orchestrator** — assert widget available → open drop → pick target (typing ≥3 chars) → wait 2s throttle + XHR → wait for reload → verify `#be_me` in nav. Throws on missing widget or ghost error toast. |
| `isGhostAvailable(page)` | Non-throwing check — is `#s2id_ghost_id` bound? |
| `assertGhostAvailable(page)` | Throws `PRECONDITION_MISSING` if widget absent. |
| `openGhostDropdown(page)` | Click `a.select2-choice` (NOT `.select2-focusser`). |
| `pickGhostTarget(page, name, opts)` | Type name (≥3 chars, single burst), wait `quietMillis+500ms` for XHR, click result. `hasText: name` matches even in multi-firm `<p>Name [Firm Name]</p>` labels. |
| `waitForGhostReload(page, timeout?)` | Race `location.reload()` against a possible `.toast-error` with "ghost" in it. Throws `SCENARIO_FAILED` on error toast or `SILENT_FAILURE` if neither observed at 5s. |
| `verifyGhosted(page)` | Confirm `#be_me` is present in nav (only appears when ghosted). |
| `recoverStuckGhostDrop(page)` | Recovery — Escape any stuck drop and detect if session lost auth (redirect to `/promo_login`). |

**Preconditions:** Home (or any admin-capable page) is already loaded.

**Post-conditions:** Page has reloaded as the impersonated user; may NOT be Home
(landing depends on the target user's default). Re-fingerprint before asserting.

---

### 3. `Select2v3Helper.ts` — Select2 v3 primitives

Not a workflow helper — building blocks used by the PRF helpers. The vPromotions
form uses Select2 v3 (jQuery) with drops mounted **directly under `<body>`**, not
scoped to the widget container. Test authors rarely invoke these directly;
they're re-exported here so `create-prf-helper.md` selectors have a matching
programmatic API.

**Public API:**

| Function | Purpose |
|---|---|
| `pickSelect2Single(page, containerId, labelText, opts?)` | Pick a value in a single-select widget by matching visible label. Use `exact:true` to avoid prefix collisions ("Corporate Contest" vs "Corporate Content"). |
| `pickSelect2Multi(page, containerId, values)` | Pick one or more values in a `select2tags` widget. Waits 400ms after each pick to catch `cat_change_checker`-style silent rejections. |
| `pickSelect2Ajax(page, containerId, query, opts?)` | Pick from an AJAX-backed widget (client typeahead, ghost picker). Handles `minimumInputLength` (default 3) and `quietMillis` (default 2000) throttling. |
| `openSelect2Single(page, containerId)` | Just open the drop (returns the drop Locator). Use when you need to inspect options before picking. |
| `openSelect2Multi(page, containerId)` | Same for multi widgets. |
| `activeSelect2Drop(page, multi?)` | Locate the currently-open body-mounted drop. |
| `closeAnySelect2Drop(page)` | Recovery — press Escape on any stuck drop. |

**Anti-patterns baked into these helpers:**
- `fill()` on the hidden `<select>` — UI never updates (select2 v3 doesn't bind).
- `getByRole('option', ...)` inside select2 drops — role attrs are inconsistent.
- Clicking `a.select2-focusser` to open — it's a transparent proxy; use `.select2-choice`.

---

### 4. `FormbuilderHelper.ts` — PRF formbuilder widget primitives

Handles the widget-specific quirks inside `#prf_form_rightview`: tasp
contenteditable (NOT wysihtml), `hasdatepicker` inputmask, required-field
enumeration, save-button enablement.

**Public API:**

| Function | Purpose |
|---|---|
| `fillPrfTextField(page, fieldName, value)` | Fill a plain `<input type="text">`. Anchors on `.field-<name>` (stable across new/existing records; the id embeds the record id). |
| `fillPrfTaspField(page, fieldName, value, opts?)` | Fill a `span.tasp[contenteditable]` field. **Does not** use `.fill()` — clicks to place caret, Ctrl+A to clear (with `Meta+A` WebKit fallback), then `keyboard.type()`. Applies to description, play copy, prize info, liner copy, liner notes. |
| `fillPrfDatePicker(page, fieldName, value, opts?)` | Fill a `hasdatepicker` datetime field with inputmask `99-99-9999`. Format is `MM-DD-YYYY` (date) or `MM-DD-YYYY hh:mm A` (datetime, 12-hour). **Always set Start BEFORE End** — cross-field constraint clamps End's minDate. Detects `Invalid Date` toast and throws. |
| `getPrfFormId(page)` | Return the form's DOM id (`prf__form` for new, `prf_<recordId>_form` for existing). Used to build `#s2id_<form-id>_<field>` container ids. |
| `s2idFor(page, field)` | Build the select2 container id for a formbuilder field (leading `_` optional). |
| `enumeratePrfFields(page)` | Return every rendered formbuilder control with its name, tag, type, required-flag, and field-class. Use this when you don't know which fields are on-screen (the field set is record-driven, not static). |
| `waitForSaveEnabled(page, timeout?)` | Wait for `.prf_submit` to be visible + `:not(:disabled)`. Returns the button locator. |
| `isPrfDrawerInDraftMode(page)` | true if `.prf_submit.hidden` (draft state 33). In draft mode, `.btn-is-draft` is the only save entrypoint. |
| `safeStartEndDefaults()` | Returns `{start, end}` — today+7d 09:00 AM / today+8d 09:00 AM. |
| `formatDateForPicker(date)` / `formatDateTimeForPicker(date)` | Format helpers for the picker's expected shape. |

**Cross-field constraint:** `fillPrfDatePicker` for start/end MUST be called in
order (Start → End) — setting Start updates End's minDate; setting End updates
Start's maxDate. Out of order → End may silently clear.

---

### 5. `CreatePrfHelper.ts` — End-to-end PRF creation

The primary helper for PRF-creation ACs. Composes the primitives from
Select2v3 + Formbuilder into a full happy-path.

**Public API:**

| Function | Purpose |
|---|---|
| `createPrfHappyPath(page, details, opts?)` | **Orchestrator** — STEP 1 (drawer) → STEP 2 (title) → STEP 3 (category) → STEP 4 (stations) → STEP 5 (sales assignment, if provided) → STEP 6 (dates, description, extras) → STEP 7 (save). Returns `{recordId, toast, formId}`. Throws on save failure with the required-field list. |
| `openPrfDrawer(page)` | Click `#create_new_prf` → wait for drawer + form + title input visible. Caller MUST have registered a dialog handler first (AuthHelper does this). |
| `fillPrfTitle(page, title)` | Fill `input.field-title` and Tab to fire the `modified` flip. Verifies `#prf_form_rightview.data('modified') === true`. |
| `pickPrfCategory(page, category)` | Pick one or more categories in the `select2tags` widget. **"Corporate Contest" cannot be combined** with others — cat_change_checker silently revokes it 300ms after selection with a toast. |
| `pickPrfStations(page, stations)` | Same for stations. Sub-PRFs are filtered to parent's stations — unknown values silently don't appear. |
| `pickPrfSalesAssignment(page, label, fieldName?)` | Pick sales person by full label `Name (Role - Station)`. Tries `sales_person_id` then `salesperson_id`. Options depend on selected stations — pick stations FIRST. |
| `fillPrfCoreFields(page, details)` | Fill Start + End datetimes (Start first!), optional description tasp, any extra text fields via `details.extraTextFields`. Uses safe defaults for missing dates. |
| `savePrf(page, opts?)` | Wait for `.prf_submit` enabled → click → race `.toast-success` against `.toast-error` (attached, NOT visible — toastr can render below viewport). Returns `{ok, recordId, toast}`. |
| `verifyPrfOnCalendar(page, title, timeout?)` | Confirm `.fc-event` with the title appears on the calendar (5s default). |
| `findCalendarEvents(page, title)` | Return the Locator for calendar events matching a title. |

**`CreatePrfDetails` shape:**
```typescript
interface CreatePrfDetails {
    title: string;                          // required
    category: string;                       // required (full label)
    stations: string[];                     // required (may be empty for some tenants)
    salesAssignment?: string;               // "Name (Role - Station)" — literal parens
    startDatetime?: Date | string;          // defaults today+7 @ 09:00 AM
    endDatetime?: Date | string;            // defaults Start + 1 day
    startDatetimeField?: string;            // default 'event_startdatetime'
    endDatetimeField?: string;              // default 'event_enddatetime'
    description?: string;                   // tasp contenteditable
    descriptionField?: string;              // default 'description'
    extraTextFields?: Record<string, string>; // any additional text fields
}
```

---

### 6. `ApprovePrfHelper.ts` — Approve a Pending PRF

Approval is a **single calendar-side click** — no drawer, no form. Only
applies to ROLE_SALES_MANAGER / ROLE_PROMOTIONS_DIRECTOR / ROLE_OTHER / ROLE_GM.

**Public API:**

| Function | Purpose |
|---|---|
| `approvePendingPrf(page, prfId, role)` | **Orchestrator** — verify link exists → click "Yes" → resolve `#event_conflict_modal` if it opens → verify status advanced. Throws PRECONDITION_MISSING if link absent. |
| `isPrfApprovable(page, prfId)` | Non-throwing — is the row-scoped `a.calendar-approve-event[data-prf-id]` visible? |
| `clickApproveYes(page, prfId, opts?)` | Click the row-scoped Yes link. Returns `'conflict-modal'` / `'direct'` / `'unknown'`. |
| `resolveConflictModal(page)` | Handle `#event_conflict_modal` when `get_event_conflicts` returns conflicts. |
| `verifyApprovalAdvanced(page, prfId, role)` | Confirm status transitioned per the role's rule (37 for Sales Mgr, 41 for GM, etc.). |
| `approveLinkFor(page, prfId)` | Row-scoped locator: `a.calendar-approve-event[data-prf-id="<id>"]`. |
| `eventCardFor(page, prfId)` | Row-scoped locator for the `.fc-event`. |

**Strict-mode note:** "Yes" appears at every eligible PRF card — ALWAYS scope
by `data-prf-id`, never `getByText('Yes')`.

---

### 7. `RevisePrfHelper.ts` — Revise an Approved PRF

Right-click the event → Revise → confirm modal → drawer opens in edit mode →
apply revisions → save.

**Public API:**

| Function | Purpose |
|---|---|
| `revisePrf(page, prfId, revisions)` | **Orchestrator** — context menu → Revise → confirm → apply revisions → save. |
| `openPrfContextMenu(page, prfId)` | Right-click the `.fc-event` row. |
| `clickRevise(page, prfId)` | Click "Revise" in the context menu. Returns the drawer Locator. |
| `confirmRevisionModal(page, opts?)` | Handle the confirm modal (creates a revision copy). |
| `applyPrfRevisions(page, revisions)` | Apply text/tasp/date/select changes per the `PrfRevisions` object. |
| `saveRevision(page, opts?)` | Save the revision — same success/error contract as `savePrf`. |
| `reviseLinkFor(page, prfId)` | Locator for the "Revise" context-menu item. |

**`PrfRevisions` shape** (all fields optional):
```typescript
interface PrfRevisions {
    title?: string;
    category?: string | string[];
    stations?: string[];
    salesAssignment?: string;
    startDatetime?: Date | string;
    endDatetime?: Date | string;
    description?: string;
    textFields?: Record<string, string>;
    taspFields?: Record<string, string>;
}
```

---

### 8. `SubmitOrCancelPrfHelper.ts` — Save/draft/cancel actions on an open drawer

Handles the two-save-button ambiguity (`.prf_submit` vs `.btn-is-draft`) plus
Cancel. **Save Draft still validates required fields** — it's not a bypass.

**Public API:**

| Function | Purpose |
|---|---|
| `savePrfDrawer(page, opts?)` | Click `.prf_submit` — submits for review. Wait for `.toast-success` / `.toast-error`. Returns `{ok, recordId, toast}`. |
| `saveDraftPrfDrawer(page, opts?)` | Click `.btn-is-draft` — saves in Draft status (status_code_id=33). Same success contract. **Same validation runs** — required fields must be filled. |
| `cancelPrfDrawer(page)` | Click Cancel; auto-accepts the "Discard unsaved modifications?" confirm. Verifies drawer closes. |
| `assertSaveSucceeded(page)` | Assert `.toast-success` + drawer state; return `{recordId}`. |
| `assertSaveFailed(page)` | Assert `.toast-error`; return `{message}`. |
| `assertCancelSucceeded(page)` | Assert drawer is hidden + no modified data lingers. |

**AC-wording rule:** if the step CONTAINS "draft" (case-insensitive), call
`saveDraftPrfDrawer`; otherwise call `savePrfDrawer`. Wrong button → record
ends up in the wrong `status_code_id` and downstream steps fail.

---

### 9. `UploadPrfFilesHelper.ts` — Dropzone upload modal

**Only available during initial PRF create** — not after submission. It's a
Dropzone modal, not a native `<input type="file">`.

**Public API:**

| Function | Purpose |
|---|---|
| `uploadPrfFiles(page, filePaths, description?)` | **Orchestrator** — verify widget available → open modal → attach files → fill description → submit. |
| `isUploadWidgetAvailable(page)` | Only true during initial create. |
| `openUploadModal(page)` | Click `.upload_inital_prf_files`. |
| `attachFilesToDropzone(page, filePaths)` | Use Playwright's `setInputFiles()` on Dropzone's hidden input — bypasses the OS file picker. |
| `fillUploadDescription(page, description)` | Fill the modal's description field. |
| `submitUploadModal(page, opts?)` | Submit — wait for spinner (Dropzone has NO client-side timeout; treat as network failure past ~30s). |
| `cancelUploadModal(page)` | Cancel/close the modal. |

---

## Composition Example — Full QA-359-style test

```typescript
// playwright/tests/vpromotions/qa-359-create-prf-happy-path.test.ts
import { test } from '../../utils/setup';
import { loginAndWaitForHomeReady } from '../../utils/prf/AuthHelper';
import { ghostLogin } from '../../utils/prf/GhostLoginHelper';
import { createPrfHappyPath } from '../../utils/prf/CreatePrfHelper';

test.use({ user: 'Admin' }); // uses fixture

test('QA-359 — happy-path PRF creation as Sales Assistant', async ({ page, baseURL }) => {
    // STEP 1-6: auth and land on Home ready.
    await loginAndWaitForHomeReady(page, baseURL!, { useAppTest: true });

    // Ghost as the target persona (Sales Assistant).
    await ghostLogin(page, 'Sales Assistant');

    // Re-verify home is ready under the ghosted session.
    await loginAndWaitForHomeReady(page, baseURL!, { useAppTest: true });

    // Happy-path create — one call replaces ~150 CU-loop iterations.
    const result = await createPrfHappyPath(page, {
        title: 'QA-359 Contest Test PRF',
        category: 'Contest',
        stations: ['XXXX-FM', 'ZZZZ-AM'],
        salesAssignment: 'Sales Assistant (Sales - XXXX-FM)',
        description: 'Test description for QA-359',
        // Start/End default to today+7 / today+8 at 09:00 AM.
    }, { verifyOnCalendar: true });

    // Assertion: record was created.
    if (!result.recordId) throw new Error('QA-359 — no recordId returned');
});
```

**Expected wall-clock:** 15-25 seconds (vs. 24 minutes / $7.69 for the CU loop).

---

## Preconditions & failure modes cheat-sheet

Every orchestrator throws with a specific prefix on precondition failure so
the parser / gate can route intelligently:

| Prefix | Meaning | What the parser should do |
|---|---|---|
| `PRECONDITION_MISSING:` | Widget not bound for this role (ghost, approve) | Skip helper, fall back to CU loop |
| `SCENARIO_FAILED:` | Server returned an error the helper detected via toast | Report failure; do NOT retry |
| `SILENT_FAILURE:` | No expected UI change within timeout | Fall back to CU loop with a note |

---

## Version

- Manifest revision: 1
- Helpers source SHA: (populated at generation time)
- Target vPromotions build: legacy jQuery + Select2 v3 + jQueryUI datepicker
  (NOT the Angular/PrimeNG vSuite app)
