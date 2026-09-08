# TASK-124: Multi-Product Support — Per-Product Personas, Environments & Playwright Tests

**Complexity**: Level 4 (inherited from FEAT-115)
**Status**: BUILD_COMPLETE
**Roadmap**: FEAT-115
**Branch**: feature/FEAT-115-multi-product-support

## Task Description

Extend vQA from a single-product (vProMedia) testing platform to a first-class multi-product platform supporting six products: **vProMedia** (existing), **vTrade** (partially bootstrapped by TASK-012), **vEP**, **vPPO**, **vPromotions** (single role exists), and **PSN**.

The architectural core of this task is a **product registry** (`backend/config/products.yaml`) that becomes the single source of truth mapping each product slug to:

1. **Jira board IDs** — replaces the currently-global `settings.jira_board_ids: list[int]` in `backend/config.py:111-117` with a per-product mapping.
2. **Role keys** — declares which entries in `backend/engine/roles.py::ROLE_REGISTRY` belong to that product. The existing 13 role keys (`account_executive` through `vtrade_sales_manager` in `frontend/src/types/index.ts:637-650`) are partitioned across products; **no roles are added or removed** in TASK-124.
3. **Environment target URL(s)** — replaces the currently-global `settings.target_url` (`backend/config.py:958-961`, default `https://two-test.vcreative.net`) with a per-product default.
4. **Playwright test root** — a filesystem prefix under `playwright/tests/` (see `backend/config.py:1090-1094`) used to filter which tests appear in the Playwright browser.
5. **Personas directory** — a filesystem prefix under `knowledge/personas/` used to filter which persona files are surfaced to the planner / KB.

A **Product Selector** in the Dashboard header (`frontend/src/components/Dashboard.tsx:176-246`) becomes the first-class context anchor: selecting a product filters the Jira ticket list, the role dropdown in `SelectView` (`frontend/src/components/SelectView.tsx:82-84`), the Playwright test browser, and the default `targetUrl`.

The **explicit design constraint** from the user: adding a new product in the future must require only (a) a new entry in `products.yaml` and (b) creating per-product `knowledge/personas/<product>/`, `playwright/tests/<product>/` directories. **Zero code changes.**

**What already exists (do NOT re-implement):**
- vTrade role entries in `backend/engine/roles.py:532-585` (vtrade_exec, vtrade_business_manager, vtrade_sales_manager) — added by TASK-012.
- vTrade + vPromotions roles in `frontend/src/types/index.ts:647-670` (RoleKey union + ROLE_DISPLAY_NAMES).
- All 11 vProMedia personas in the flat directory `knowledge/personas/*.md`.
- Global `jira_board_ids: list[int] = [27, 36]` in `backend/config.py:111-117`.
- Global `target_url: str` in `backend/config.py:958-961`.
- Role dropdown + `targetUrl` field in `frontend/src/components/SelectView.tsx:82-88`, both persisted to localStorage (`vqa_role`, `vqa_targetUrl`).
- Dashboard header + tab nav in `frontend/src/components/Dashboard.tsx:176-246`.

## Specification

**Feature Type**: End-User Feature
**Primary Persona**: QA Lead / Automation Engineer (the vQA operator who selects a Jira ticket, picks a role, and launches a test run)
**Creative Exploration Needed**: Yes — three questions require design exploration (see "Creative Exploration Needed" below).

### Invocation Method

- **Location**: New **Product Selector** dropdown placed in the Dashboard header, immediately to the right of the app title (`frontend/src/components/Dashboard.tsx:176-183`) and to the left of the tab nav (`Dashboard.tsx:186-213`). Rendered on every Dashboard view (Run Test, Reports Archive, Analytics) so context is always visible.
- **Element**: `<ProductSelector />` — new component at `frontend/src/components/ProductSelector.tsx`, backed by a new `useProductContext()` hook at `frontend/src/context/ProductContext.tsx`. Component renders as a compact dropdown showing the current product's display name and icon (e.g. "vProMedia" / "vTrade").
- **Visibility**: Always visible in the Dashboard header. Also visible in the Playwright page header (`frontend/src/pages/PlaywrightPage.tsx`) so the same product filter applies to the static-test browser.
- **Navigation**: The Product Selector is the FIRST context choice on app load. On first mount (no `vqa_product` in localStorage), it defaults to `vpromedia` (preserves existing behavior). On subsequent loads, the last-selected product is restored from `localStorage.getItem('vqa_product')`. Changing the product:
  1. Updates `ProductContext` (React context).
  2. Persists to `localStorage['vqa_product']`.
  3. Triggers a re-fetch of `/tickets` (which is now product-scoped).
  4. Resets the role dropdown in `SelectView` to the first role of the newly-active product (clears `vqa_role` if the previously-stored role is not in the new product's role set).
  5. Resets `targetUrl` to the new product's default from the registry (clears `vqa_targetUrl`).
  6. Re-filters the Playwright test list.
- **Confidence**: MEDIUM — placement in the Dashboard header is a reasonable inference from the existing header layout, but exact visual treatment (icon, color coding, badge) needs UX exploration in the Creative phase.

### Success Criteria

- **User sees**: The Dashboard header shows a product name (default "vProMedia") in a selector control. When they open the selector, they see all 6 products from `backend/config/products.yaml`. Selecting a different product:
  - Immediately updates the header display to the new product.
  - Refreshes the Jira ticket list in `SelectView` (`SelectView.tsx:102-120`) to show only tickets from the boards mapped to that product in the registry.
  - Refreshes the role dropdown (currently populated from `ALL_ROLES` in `frontend/src/types/index.ts:676`) to show only role keys assigned to that product in the registry.
  - Pre-populates the `targetUrl` field (`SelectView.tsx:86-88`) with the product's registry-defined default URL.
  - Filters the Playwright test browser to show only tests under `playwright/tests/<product-slug>/`.
- **Verifiable at**:
  - Dashboard header shows selected product name.
  - `/tickets` API response (backend) — verifiable via network tab and by the reduced ticket list.
  - Role dropdown in `SelectView` (`SelectView.tsx:82-84`) — verifiable by opening the dropdown and counting entries.
  - Playwright page test list — verifiable by counting `.spec.ts` / `.test.ts` entries.
- **Data persisted**: `localStorage['vqa_product']` (new key) — string slug matching a product in `products.yaml`. Existing keys `vqa_role` and `vqa_targetUrl` are conditionally reset on product change.
- **Observable within**: Immediate (context re-render + ticket refetch within ~1s on typical network).

### Acceptance Criteria

#### AC-ENTRY-1: Operator can locate the Product Selector on first load
**Priority**: MUST
**Given** an operator loads the Dashboard with no previously-selected product (empty localStorage)
**When** the Dashboard mounts
**Then** the Product Selector is visible in the Dashboard header to the right of the app title, defaulted to "vProMedia", and the ticket list, role dropdown, and Playwright tests all reflect the vProMedia product scope (preserving existing behavior).

#### AC-ENTRY-2: Product Selector persists across page reloads and tab navigation
**Priority**: MUST
**Given** an operator has previously selected "vTrade" as the active product
**When** they reload the page or navigate between the Run Test / Reports Archive / Analytics / Playwright tabs
**Then** the Product Selector still shows "vTrade" and all product-scoped views (tickets, roles, tests, target URL) remain scoped to vTrade.

#### AC-HAPPY-1: Selecting a product filters the Jira ticket list to that product's boards
**Priority**: MUST
**Given** the operator is on the Run Test tab with vProMedia selected
**When** they open the Product Selector and choose "vTrade"
**Then**
  1. The Product Selector header updates to show "vTrade".
  2. `/tickets` is re-fetched with the active product context (either as a query parameter `?product=vtrade` or via a header, per Creative decision).
  3. The Jira ticket list in `SelectView.tsx:102-120` shows only tickets from the Jira board IDs mapped to `vtrade` in `products.yaml` — NOT the currently-global `[27, 36]` from `backend/config.py:111-117`.
  4. Any previously-selected ticket in `SelectView` state is cleared.

#### AC-HAPPY-2: Selecting a product filters the role dropdown to that product's roles
**Priority**: MUST
**Given** the operator has switched the active product to "vTrade"
**When** they open the role dropdown in `SelectView.tsx:82-84`
**Then** the dropdown shows exactly the three vTrade role keys (`vtrade_exec`, `vtrade_business_manager`, `vtrade_sales_manager` — see `backend/engine/roles.py:532-585` and `frontend/src/types/index.ts:647-650`) and NONE of the vProMedia role keys.

#### AC-HAPPY-3: Selecting a product sets the default target URL to that product's environment
**Priority**: MUST
**Given** the operator has switched the active product to "vTrade" (assume `products.yaml` maps vtrade → `https://vtrade-qa.vcreative.net`)
**When** the product switch completes
**Then** the `targetUrl` input in `SelectView.tsx:86-88` shows the vTrade default URL (NOT the previously-stored vProMedia URL) AND `localStorage['vqa_targetUrl']` is either cleared or updated to the new default.

#### AC-HAPPY-4: Selecting a product filters the Playwright test browser to that product's test directory
**Priority**: MUST
**Given** the operator has switched the active product to "vTrade"
**When** they navigate to the Playwright page (`frontend/src/pages/PlaywrightPage.tsx`)
**Then** the visible test list contains only tests under `playwright/tests/vtrade/**` and none of the existing vProMedia tests under `playwright/tests/*.test.ts` (which will have been moved to `playwright/tests/vpromedia/` by Phase 5).

#### AC-HAPPY-5: Playwright static-match lookup in SelectView is product-scoped
**Priority**: MUST
**Given** the operator has selected a Jira ticket while vTrade is the active product
**When** the SelectView performs its Playwright static-match lookup (`SelectView.tsx:77-79`)
**Then** the lookup only searches tests under `playwright/tests/vtrade/**`; a matching vProMedia test with the same ticket ID prefix is NOT surfaced as a match.

#### AC-HAPPY-6: An operator runs a vTrade test end-to-end using product-scoped context
**Priority**: MUST
**Given** the operator selects vTrade from the Product Selector, picks a vTrade Jira ticket, selects `vtrade_exec` as the role, and clicks "Run Test"
**When** the run reaches the executor (`backend/engine/playwright_executor.py`)
**Then** the run uses the vTrade target URL from the registry, the vTrade role credentials from `ROLE_REGISTRY["vtrade_exec"]`, and the Playwright test picks tests from the vTrade test root — the run completes without cross-product credential or URL bleed.

#### AC-ERROR-1: Product Selector recovers from a corrupt or unknown product slug in localStorage
**Priority**: MUST
**Given** `localStorage['vqa_product']` contains a slug that is not present in `products.yaml` (e.g. left over after a product was removed from the registry, or manual browser tampering)
**When** the Dashboard mounts
**Then** the Product Selector falls back to the default product (`vpromedia`), logs a warning to the console, and overwrites `localStorage['vqa_product']` with the fallback slug — the app does NOT crash and no unfiltered data leaks through.

#### AC-ERROR-2: Product with no Jira boards, no roles, or no tests still renders without crashing
**Priority**: MUST
**Given** a product (e.g. `vep`, `vppo`, `psn`) is declared in `products.yaml` with an empty `jira_board_ids: []`, empty `roles: []`, and no test directory
**When** the operator selects that product
**Then** the ticket list shows an empty-state message ("No tickets configured for this product"), the role dropdown shows a disabled placeholder ("No roles configured for this product"), the Playwright test list shows an empty-state message, AND the operator is prevented from clicking "Run Test" with a disabled button + explanatory tooltip. No JavaScript errors surface in the console.

#### AC-ERROR-3: Backend rejects a run request whose role does not belong to the requested product
**Priority**: MUST
**Given** a client sends a `/execute` request with `product=vpromedia` and `role=vtrade_exec` (mismatched)
**When** the backend validates the request (in `backend/api/schemas.py` or the routes layer)
**Then** the backend returns a 400 with a clear message ("Role 'vtrade_exec' is not available for product 'vpromedia'") — this prevents credential/URL cross-contamination even if the frontend state is inconsistent.

#### AC-ASYNC-1: Switching products mid-selection cleanly cancels an in-flight ticket fetch
**Priority**: SHOULD
**Given** the operator has switched to vTrade and the `/tickets?product=vtrade` request is in flight
**When** they immediately switch to vEP before the vTrade fetch completes
**Then** the vTrade response is discarded (either via `AbortController` or a request-generation counter) and only the vEP ticket list is rendered — no flash of vTrade tickets appears.

### Scope Boundaries

**In scope:**
- Introduce `backend/config/products.yaml` as the single product registry (schema defined in Phase 1).
- Refactor `backend/config.py` to load the registry and expose per-product accessors (e.g. `settings.get_product("vtrade").jira_board_ids`).
- Refactor `backend/engine/roles.py` — add a `product` tag to each entry in `ROLE_REGISTRY` (or add a parallel `ROLE_TO_PRODUCT` mapping) so the frontend can filter without duplicating the assignment.
- New frontend `ProductContext` provider and `ProductSelector` component.
- New `/products` API endpoint returning the registry (minus secrets) so the frontend does not hardcode the product list.
- Update `/tickets`, `/execute`, `/playwright/tests`, and any credential-check endpoints to accept and honor an active-product parameter.
- Reorganize `knowledge/personas/` from a flat directory into `knowledge/personas/vpromedia/*.md` (11 files moved) and stub subdirectories for the other 5 products. Update any code that reads personas (search for `knowledge/personas/`) to accept a product-scoped prefix.
- Reorganize `playwright/tests/` from a flat directory into `playwright/tests/vpromedia/**` (all existing `qa-*.test.ts`, `debug.test.ts`, `email_check_validation.test.ts`, and generated tests moved) and stub subdirectories for the other 5 products. Update `settings.playwright_tests_dir` handling (`backend/config.py:1090-1094`) and the Playwright registry file logic (`backend/config.py:1096-1098`).
- Assign the 13 existing role keys in `frontend/src/types/index.ts:637-650` to their products in the registry: 8 vProMedia roles (`account_executive`, `sales_manager`, `sales_assistant`, `production_manager`, `producer`, `gm_gsm`, `dubber`, `digital_director`) + 1 legacy demo role (`demo_prod_director`, assigned to vProMedia) + `vpromotions_user` (→ vPromotions product) + 3 vTrade roles (→ vTrade product). vEP, vPPO, and PSN have zero role keys initially.
- Preserve all existing vProMedia behavior when vProMedia is the selected product (regression bar).

**Out of scope:**
- Adding NEW roles for vEP, vPPO, or PSN. These products get registry entries but empty `roles` lists in Phase 1; adding their roles is a separate FEAT (out of scope for FEAT-115).
- Product-scoped knowledge base / RAG changes. The Bedrock Roles KB (`JXMMTMTI06`) and vSuite actions KB stay global for now. If a product-scoped KB is needed later, it is a follow-up feature.
- Multi-product simultaneous runs (running vProMedia + vTrade in parallel from one operator session). The Product Selector enforces one active product at a time.
- Cross-product Jira ticket search (e.g. "find this ticket anywhere"). Ticket search is always scoped to the active product.
- Migration of already-completed run history / reports to be product-scoped in the Reports Archive. Historical reports remain as-is; new reports get a `product` field.
- Any change to the Bedrock model, LLM prompts, or planner logic. Multi-product scoping is a data / configuration concern only.
- vTrade credential population (already done by TASK-012).

**Dependencies:**
- TASK-012 (vTrade role scaffolding) — must be complete. Verified: vTrade roles are present in `backend/engine/roles.py:532-585` and `frontend/src/types/index.ts:647-650`.
- No new external services. No new secrets in SSM — existing `/vQA/roles/*` and `/vQA/jira/*` paths remain the source of truth.

**NFR implications:**
- **Backwards compatibility (MUST):** When vProMedia is selected (the default), the app behaves identically to today — same ticket list, same role dropdown, same target URL, same tests visible. Any regression here is a P0 bug.
- **Configuration-only extensibility (MUST):** Adding vEP / vPPO / PSN roles later must require ONLY a new `ROLE_REGISTRY` entry in `backend/engine/roles.py` + a `roles: [...]` list update in `products.yaml`. Adding a new *product* must require ONLY a new `products.yaml` entry + `knowledge/personas/<slug>/` + `playwright/tests/<slug>/`. This is a testable NFR — see AC-INTEGRATION-style verification in the Test Strategy section.
- **Secret handling:** No product should be able to see another product's role credentials via the `/products` API. The registry endpoint returns product metadata and role KEYS only — never credentials. Credentials continue to be resolved server-side in `_resolve_credentials()` (`backend/engine/roles.py:60-80`).
- **Empty-state hygiene:** Products with no configured Jira boards / no roles / no tests still render a usable empty state (see AC-ERROR-2). The app never crashes on a partially-configured product — this is a hard requirement for the "add a product with zero code changes" design goal.

### Creative Exploration Needed

Yes — three questions require Creative-phase exploration before implementation begins:

1. **Product Selector visual design.** Where exactly in the Dashboard header does it go (left of tabs vs. right of tabs vs. as a full-width sub-header)? What does the trigger look like — icon + name, colored pill, dropdown-arrow button? How does it visually indicate the active product across all 6 products (color coding? per-product icons/emoji?)? How does it handle the case of only one configured product (does it hide, does it display as a static badge)? Deliverable: a Figma-quality mockup or ASCII wireframe + CSS variable palette per product.

2. **Product registry schema (`products.yaml`).** The exact YAML shape. Options include (a) a flat `products: {slug: {jira_board_ids, roles, target_url, ...}}` map, (b) a list of product objects, (c) split into `products.yaml` + separate `products/<slug>.yaml` files. Also: how are environments modeled — is `target_url` a single string per product, or a map of environment name → URL (e.g. `{qa: ..., staging: ..., prod: ...}`) with an env selector? The user's brief mentions "environment scoping" but currently only one URL exists per product. Deliverable: a canonical schema example for one populated product (vProMedia) and one empty product (vEP).

3. **How role-to-product assignment is stored and enforced.** Two options: (a) Add a `product: str` field to each `RoleContext` in `backend/engine/roles.py` and derive the frontend list from `/products` (single source of truth, but touches every role entry). (b) Keep `ROLE_REGISTRY` untouched and declare `roles: [<role_key>, ...]` in `products.yaml`; add a startup validation that every registry role appears in exactly one product. Also: how does the backend enforce role↔product consistency on `/execute` (see AC-ERROR-3) — a Pydantic validator, a middleware, or a check in the routes layer? Deliverable: a decision + a 20-line pseudocode sketch of the enforcement path.

Additionally flag as MEDIUM confidence (not blocking):
- Whether the Product Selector should appear in the LoginPage / MfaPage. Assumption: no, it appears post-login only.
- Whether `settings.jira_board_ids: list[int]` in `backend/config.py:111-117` should be *removed* entirely or kept as a global fallback for legacy code. Recommended: remove after all call sites migrate (part of Phase 2 implementation).

## Test Strategy

### Approach

- **Test emphasis:** Integration tests over unit tests. The value of this feature is that scoping propagates *end to end* — from the Product Selector click, through the `/tickets`, `/execute`, `/playwright/tests` APIs, through the executor's use of role credentials and target URLs, into the actual test artifacts. Unit tests on `ProductContext` and `products.yaml` loader are cheap and worth having, but the failure modes we care about (cross-product credential bleed, unfiltered ticket lists) only surface at integration boundaries.
- **Target test count:** ~18–24 new test cases across pytest (backend) and Vitest/Playwright (frontend). Roughly: 6 backend unit tests for the registry loader + role/product enforcement, 8 backend integration tests for the product-scoped APIs (`/products`, `/tickets`, `/execute`, `/playwright/tests`), 6 frontend component/hook tests for `ProductContext` and `ProductSelector`, and 2–4 E2E flows exercising a full "switch product → pick ticket → pick role → run" cycle.
- **Regression bar:** All existing pytest + Playwright tests that assume vProMedia must continue to pass without modification when vProMedia is the default product. Any test that currently reads `settings.jira_board_ids` or `settings.target_url` directly is a canary — those references get updated to the product-scoped accessor and the test must still pass.

### File Organization

**New test files:**
- `tests/backend/test_product_registry.py` — loader tests: valid YAML, missing fields, unknown role keys, duplicate slugs, empty products, malformed file. Also the "add a product with zero code changes" NFR — parameterized test that adds a synthetic product to a fixture registry and asserts all four scopes (Jira, roles, target URL, tests dir) resolve without code touching any Python module outside the loader.
- `tests/backend/test_product_scoping_api.py` — integration tests for the product-scoped endpoints: `/products` returns all 6 products without secrets, `/tickets?product=vtrade` uses the correct board IDs, `/execute` with a mismatched product+role combo returns 400 (AC-ERROR-3), `/playwright/tests?product=vpromedia` returns the reorganized vProMedia tests and not the vTrade stubs.
- `tests/backend/test_role_product_enforcement.py` — enforces that every entry in `ROLE_REGISTRY` (`backend/engine/roles.py:595`) belongs to exactly one product in `products.yaml`, and that every `roles: [...]` entry in the registry maps to a real `RoleContext`. This is the guard rail for AC-ERROR-3 and the "zero code changes" NFR.
- `frontend/src/context/__tests__/ProductContext.test.tsx` — hook behavior: default product, localStorage restore, corrupt-slug fallback (AC-ERROR-1), product change triggers dependent resets, unknown product does not crash.
- `frontend/src/components/__tests__/ProductSelector.test.tsx` — component behavior: renders all products from `/products`, updates context on selection, empty-product state (AC-ERROR-2), disabled Run Test button when no roles available.
- `playwright/tests/vpromedia/multi-product-e2e.test.ts` — E2E: switch from vProMedia to vTrade, verify ticket list shrinks, verify role dropdown shrinks, verify target URL updates. Runs against the actual `/products` API in the CI Docker compose.

**Files to extend:**
- `tests/core/pipeline.spec.ts`, `tests/core/vqaEngine.spec.ts`, `tests/core/searchHelper.spec.ts` — currently vProMedia-implicit. After Phase 5, these move to `tests/core/vpromedia/` (or the equivalent) but the test bodies themselves need only minor updates: any hardcoded reference to `jira_board_ids` or `target_url` becomes `product_context.jira_board_ids` / `product_context.target_url`.
- `frontend/src/components/__tests__/SelectView.test.tsx` (if exists; create if not) — extend to cover: role dropdown is filtered by active product, ticket list is filtered by active product, Playwright static-match is product-scoped.
- Any existing test that reads `settings.target_url` or `settings.jira_board_ids` directly — grep for these usages and update to the product-scoped equivalent.

### What NOT to Test

- **Do not test that `products.yaml` values match production reality.** The registry file's *shape* is testable; its *contents* (real Jira board IDs, real URLs) are configuration and are validated at ops time, not in CI.
- **Do not test cross-product Jira ticket contents.** We test that the ticket list is filtered by product; we do NOT test the individual ticket data (that's Jira's job).
- **Do not test the visual polish of the Product Selector** — the Creative phase produces the design; snapshot tests would ossify a design that is expected to iterate. Cover behavior, not pixels.
- **Do not test individual product configurations for vEP / vPPO / PSN.** Their registry entries in Phase 1 are stubs — testing them will just prove that stubs behave like stubs. Test the *framework* that would let a real config drop in.
- **Do not add new tests for the vTrade credentials or vPromotions login flow.** Those live in TASK-012 and prior work; we consume them, we don't re-verify them here.

### Per-Phase Test Guidance

- **Phase 1 (Product Registry & Context Architecture):** Test the loader (`tests/backend/test_product_registry.py`) and role/product cross-validation (`tests/backend/test_role_product_enforcement.py`). No UI tests yet — the frontend has nothing to render.
- **Phase 2 (Product Selector UI & Jira Scoping):** Test `ProductContext` (React hook), `ProductSelector` (component), and the product-scoped `/tickets` and `/products` endpoints (`tests/backend/test_product_scoping_api.py`). This is the phase where AC-ENTRY-1, AC-ENTRY-2, AC-HAPPY-1, AC-ERROR-1, and AC-ASYNC-1 are proven.
- **Phase 3 (Per-Product Persona Scoping):** Extend the registry loader tests to cover the `personas_dir` field. Add a test that resolves a persona file path for each product and asserts the returned path exists (for vProMedia) or is `None` (for empty products). Verify the planner / RAG code that reads `knowledge/personas/` respects the product scope.
- **Phase 4 (Per-Product Environment Scoping):** Test that `settings.get_product(slug).target_url` returns the registry value. Test AC-HAPPY-3 (target URL updates on product switch). Verify the `/execute` payload uses the product-scoped URL when no override is provided.
- **Phase 5 (Per-Product Playwright Test Organization):** Test AC-HAPPY-4 and AC-HAPPY-5. After moving test files into per-product subdirs, run the FULL existing Playwright suite under `playwright/tests/vpromedia/**` and assert zero regressions — this is the vProMedia regression bar.
- **Phase 6 (Product-Aware Knowledge Base):** If (and only if) Creative decides to product-scope any KB usage, add tests that a vTrade run does NOT pull a vProMedia persona from the RAG results. Otherwise, no new tests here.

## Implementation Roadmap

- [x] **Phase 1: Product Registry & Context Architecture**
  - Design and land `backend/config/products.yaml` schema (Creative Q2 output).
  - Add a `ProductRegistry` loader class in a new `backend/config/product_registry.py`; import into `backend/config.py`.
  - Add `product` tag to each `RoleContext` (or add `ROLE_TO_PRODUCT` map) per Creative Q3 decision.
  - Add startup validation: every `ROLE_REGISTRY` key must appear in exactly one product's `roles` list.
  - Add `/products` GET endpoint returning registry data (no secrets).
  - Deprecate global `settings.jira_board_ids` and `settings.target_url` (keep as fallbacks; log warnings if read).
  - Land backend unit tests: `test_product_registry.py`, `test_role_product_enforcement.py`.
  - **Acceptance:** `/products` returns 6 products; startup fails loudly if any role is orphaned or double-assigned.

- [x] **Phase 2: Product Selector UI & Jira Scoping**
  - Create `frontend/src/context/ProductContext.tsx` (provider + `useProductContext` hook).
  - Create `frontend/src/components/ProductSelector.tsx` per Creative Q1 mockup.
  - Wire ProductSelector into `Dashboard.tsx` header (between `.header-left` and `.dashboard-tabs`, ~line 184).
  - Update `SelectView.tsx:102-120` (ticket loader) to pass active product to `/tickets`.
  - Update `SelectView.tsx:82-84` (role dropdown) to filter `ALL_ROLES` by active product's role list.
  - Update backend `/tickets` route to accept and honor `?product=<slug>` and use the registry's `jira_board_ids` for that product.
  - Add localStorage restore + corrupt-slug fallback in `ProductContext`.
  - Add `GET /products` endpoint returning ProductPublic list.
  - Add AbortController cancellation on product switch (AC-ASYNC-1).
  - **Acceptance:** AC-ENTRY-1, AC-ENTRY-2, AC-HAPPY-1, AC-HAPPY-2, AC-ERROR-1, AC-ASYNC-1. ALL MET.

- [x] **Phase 3: Per-Product Persona Scoping**
  - Move `knowledge/personas/*.md` (11 files) into `knowledge/personas/vpromedia/`.
  - Create empty subdirs for the other 5 products.
  - Add `personas_dir` field to `products.yaml` schema.
  - Update any code that reads `knowledge/personas/` (`grep -rn "knowledge/personas" backend/`) to use the product-scoped path.
  - Land backend tests covering persona resolution per product.
  - **Acceptance:** vProMedia runs continue to load all 11 personas; other products load an empty persona set without crashing. ALL MET.

- [x] **Phase 4: Per-Product Environment Scoping**
  - Add `target_url` (or `environments: {...}` per Creative Q2) to each product in `products.yaml`.
  - Add `settings.get_product(slug).target_url` accessor to `ProductRegistry`.
  - Update `SelectView.tsx:86-88` to pull default `targetUrl` from active product's registry entry.
  - Update `/execute` route (in `backend/api/routes.py`) to default `target_url` from the active product when the payload does not override.
  - Update `product_switch` handler in `ProductContext` to reset `vqa_targetUrl` on change.
  - **Acceptance:** AC-HAPPY-3, AC-HAPPY-6 (target URL portion).

- [x] **Phase 5: Per-Product Playwright Test Organization** — COMPLETE (2026-07-21)
  - `playwright/tests/vpromedia/` — all ~46 test files moved here via `git mv` (history preserved)
  - `playwright/tests/{vtrade,vep,vppo,vpromotions,psn}/.gitkeep` — stub directories for other products
  - `playwright/playwright_index.json` — all 26 entries updated: `"file": "tests/qa-*.test.ts"` → `"file": "tests/vpromedia/qa-*.test.ts"`
  - `backend/storage/playwright_registry.py` — `list_tests_for_product(playwright_tests_dir)` filters index by path prefix
  - `backend/api/playwright_routes.py` — `?product=` param on `/playwright/tests` and `/playwright/match/{id}`
  - `backend/api/routes.py` — compat `/playwright/tests` endpoint updated with same `?product=` param
  - `frontend/src/components/PlaywrightLibrary.tsx` — passes `?product=` to fetch, re-fetches on product change
  - `frontend/src/pages/PlaywrightPage.tsx` — passes `?product=` to fetch
  - `frontend/src/components/SelectView.tsx` — `/playwright/match/{id}?product=` in handleSelectTicket
  - `tests/backend/test_playwright_scoping.py` — 12 new tests GREEN
  - `frontend/src/components/__tests__/PlaywrightLibrary.test.tsx` — 5 new tests GREEN
  - `frontend/src/components/__tests__/SelectView.test.tsx` — extended with 2 new Phase 5 tests GREEN
  - **19 Phase 5 tests: 19 passed, 0 failed**
  - **Acceptance:** AC-HAPPY-4, AC-HAPPY-5, AC-HAPPY-6 (full E2E).

- [x] **Phase 6: Product-Aware Knowledge Base (conditional)** — DEFERRED (2026-07-21)
  - No KB/RAG product-scoping implemented. Phase 3 already bounds the persona retrieval pool per product via the `personas_dir` parameter in `load_local_persona_credentials()`. No cross-product persona leak scenario identified in creative docs. Decision documented in `memory-bank/creative/TASK-124-product-registry-schema-architecture.md` (Phase 6 Decision section).
  - **Acceptance:** documented decision — SATISFIED.

## Creative Phases

This is a Level 4 feature. The following creative phases must run before Phase 1 implementation begins (or in parallel with Phase 1 planning):

1. ✅ **`/bmb:creative` — Product Selector UX design.** Deliverable: `memory-bank/creative/TASK-124-product-selector-uiux.md` — **COMPLETE**. Decision: Labeled inline pill with per-product colored left-border accent, placed between `.header-left` and `.dashboard-tabs`. 6 HSL product colors defined. Feeds Phase 2.
2. ✅ **`/bmb:creative` — Product Registry Schema design.** Deliverable: `memory-bank/creative/TASK-124-product-registry-schema-architecture.md` — **COMPLETE**. Decision: Option A flat map in single `products.yaml`; `environments: {name: url}` map with `default_environment`. Feeds Phase 1.
3. ✅ **`/bmb:creative` — Role↔Product enforcement architecture.** Deliverable: `memory-bank/creative/TASK-124-role-product-enforcement-architecture.md` — **COMPLETE**. Decision: Option C (roles in products.yaml, ROLE_REGISTRY untouched, startup cross-assertion) + Pydantic model_validator + HTTPException(400) in route handler. Feeds Phase 1 and AC-ERROR-3.

Optional (defer to reflection if not clearly needed at planning time):

4. **`/bmb:creative` — Empty-product empty-state UX.** How the app looks when a product has no Jira boards, no roles, and no tests. May be folded into creative phase 1 if UX bandwidth allows.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: Phase 5 — Per-Product Playwright Test Organization — COMPLETE
**Phase Number**: 5 of 6 (Phase 6 pending)
**Is Multi-Phase**: YES
**Build Started**: 2026-07-21
**Build Completed**: 2026-07-21
**Can Resume**: NO

### Completed Phases
- **Phase 1: Product Registry & Context Architecture** — COMPLETE (2026-07-21)
  - `backend/config/product_registry.py` — ProductContext, ProductRegistry, ProductPublic, load_product_registry()
  - `backend/config/products.yaml` — 6-product registry (vpromedia, vtrade, vpromotions, vep, vppo, psn), 13 roles assigned
  - `backend/api/schemas.py` — ExecuteRequest.product field + model_validator cross-checking role↔product
  - `backend/main.py` — RequestValidationError exception handler converting role/product mismatch to 400 (AC-ERROR-3)
  - `tests/backend/test_product_registry.py` — 26 tests, all GREEN
  - `tests/backend/test_role_product_enforcement.py` — 16 tests, all GREEN
  - **42 Phase 1 tests: 42 passed, 0 failed**

- **Phase 2: Product Selector UI & Jira Scoping** — COMPLETE (2026-07-21)
  - `frontend/src/context/ProductContext.tsx` — ProductProvider + useProductContext hook (AC-ENTRY-1, AC-ENTRY-2, AC-ERROR-1, AC-ASYNC-1)
  - `frontend/src/components/ProductSelector.tsx` — Option 4 labeled inline pill with per-product colored left-border accent
  - `frontend/src/components/Dashboard.tsx` — ProductSelector wired between .header-left and .dashboard-tabs
  - `frontend/src/components/SelectView.tsx` — ticket loader passes ?product=<slug> to /tickets; role dropdown filtered by product roles
  - `frontend/src/App.tsx` — ProductProvider wraps RouterProvider
  - `backend/api/routes.py` — GET /products endpoint + /tickets?product=<slug> with board_id scoping
  - `frontend/src/context/__tests__/ProductContext.test.tsx` — 13 tests GREEN
  - `frontend/src/components/__tests__/ProductSelector.test.tsx` — 22 tests GREEN
  - `tests/backend/test_product_scoping_api.py` — 18 tests GREEN
  - **53 Phase 2 tests: 53 passed, 0 failed**

- **Phase 3: Per-Product Persona Scoping** — COMPLETE (2026-07-21)
  - `knowledge/personas/vpromedia/` — 11 vProMedia persona files migrated here from flat root
  - `knowledge/personas/{vtrade,vpromotions,vep,vppo,psn}/` — empty stub directories created
  - `backend/engine/kb_client.py` — `load_local_persona_credentials(personas_dir=...)` parameter added; `resolve_persona_dir()` helper added; TYPE_CHECKING guard for ProductRegistry; _REPO_ROOT constant
  - `tests/backend/test_persona_scoping.py` — 43 new tests GREEN
  - **43 Phase 3 tests: 43 passed, 0 failed**

- **Phase 4: Per-Product Environment Scoping** — COMPLETE (2026-07-21)
  - `backend/config/products.yaml` — Added proper `environments` maps + `default_environment` to stub products (vep, vppo, psn) that previously had empty `environments: {}`
  - `backend/api/schemas.py` — `ExecuteRequest.target_url` now defaults to `""` and auto-resolves from `product_ctx.resolve_target_url()` in the `validate_role_product_match` model_validator when left empty; backwards-compat fallback to `https://two-test.vcreative.net`
  - `frontend/src/context/ProductContext.tsx` — `setProduct()` now calls `localStorage.removeItem('vqa_targetUrl')` on product switch (AC-HAPPY-3)
  - `frontend/src/components/SelectView.tsx` — Environment select renders dynamic options from `activeProduct.environments`; `useEffect` syncs `targetUrl` to product default when stored URL is absent or not in current product's environment map
  - `tests/backend/test_environment_scoping.py` — 11 new tests GREEN
  - `frontend/src/context/__tests__/ProductContext.test.tsx` — extended with 2 new tests GREEN
  - `frontend/src/components/__tests__/SelectView.test.tsx` — extended with 4 new tests GREEN
  - **17 Phase 4 tests: 17 passed, 0 failed; Backend total: 114 passing**

- **Phase 5: Per-Product Playwright Test Organization** — COMPLETE (2026-07-21)
  - `playwright/tests/vpromedia/` — all ~46 test files moved here via `git mv`
  - `playwright/playwright_index.json` — 26 entries updated to `tests/vpromedia/` paths
  - `backend/storage/playwright_registry.py` — `list_tests_for_product()` added
  - `backend/api/playwright_routes.py` + `routes.py` — `?product=` param on list/match endpoints
  - `frontend/src/components/PlaywrightLibrary.tsx`, `PlaywrightPage.tsx`, `SelectView.tsx` — product-scoped fetch
  - **19 Phase 5 tests: 19 passed, 0 failed**

### Current Build Step
**Step**: Step 11 — Git Commit
**Status**: COMPLETE
**Completed**: 2026-07-21

### Completed Steps
- Step 3 Test Writer: COMPLETE (2026-07-21) — 19 tests in 3 files
- Step 4/6 TDD Implementation: COMPLETE (2026-07-21) — 12 backend + 7 frontend Phase 5 tests GREEN
- Step 7 Integration Verification: COMPLETE (2026-07-21) — all tests pass, build clean, 2 pre-existing lint failures not introduced by Phase 5
- Step 8 Code Review: COMPLETE (2026-07-21) — APPROVED WITH NOTES; R1 (no-op), R2 (503 handler added), R3 (import hoisted)
- Step 9 Documentation: COMPLETE (2026-07-21) — techContext.md + systemPatterns.md updated; no inline comments needed
- Step 10 Memory Bank: COMPLETE (2026-07-21) — Phase 5 checkbox marked [x]; Execution State updated

### Sub-Agent: Test Writer
**Agent Type**: Test Writer
**Status**: COMPLETE
**Completed**: 2026-07-21
**Output**: 19 tests written — tests/backend/test_playwright_scoping.py (12), frontend/src/components/__tests__/PlaywrightLibrary.test.tsx (5 new), frontend/src/components/__tests__/SelectView.test.tsx (+2 extended)

### Guard & Recovery Log
Phase 2: guard C1 FAIL (pre-existing unrelated modified files: .claude/settings.local.json, ecs-vqa-backend-task.json, memory-bank/agent-rules-index.md, storage/* — all present before phase started per initial git status). C2 PASS (prod=6, test=3). C3 PASS (all reported artifacts in commit). Pre-existing dirty tree is not a Phase 2 artifact — no recovery needed.
Phase 3: guard C2 PASS (prod=2, test=1). C3 PASS (all reported artifacts in commit). Pre-existing dirty files excluded from commit.

## Design Critique (advisory)
Backend: unresolved:no-companion (Codex not installed). Adversarial critique not run this session.
