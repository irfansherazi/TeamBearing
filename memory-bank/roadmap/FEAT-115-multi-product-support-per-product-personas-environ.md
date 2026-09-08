---
legacy_id: FEAT-115
version: next
linked_tasks: []
status: planned
---

### FEAT-115: Multi-Product Support — Per-Product Personas, Environments & Playwright Tests
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Extend vQA from a single-product (vProMedia) system to a fully multi-product platform supporting vProMedia, vTrade, vEP, vPPO, vPromotions, and PSN. A product selector becomes the first-class context anchor for the entire application — driving which Jira project is queried, which personas are available, which environment configs are loaded, and which Playwright test suites are shown. All existing vProMedia assets (personas, environments, tests) are preserved and scoped to the vProMedia product context; each additional product gets its own dedicated config files.

  Implementation is phased:
  1. **Product Selector UI & Context Store** — Add a product picker (dropdown/selector) to the vQA UI that sets the active product context. The selected product is stored in application state and persisted across sessions. All subsequent API calls and data loads are product-scoped.
  2. **Jira Project Scoping** — The Jira board/project queried for cards is determined by the active product context. Each product has a configured Jira project key (e.g. vProMedia → VPM, vTrade → VTR, etc.). The product selector directly controls which cards appear in the run panel.
  3. **Per-Product Personas** — Persona config files (credentials, user roles) are organized per product (e.g. `personas/vprimedia/`, `personas/vtrade/`). The persona dropdown in the run UI only shows personas for the active product.
  4. **Per-Product Environments** — Environment config files (base URLs, API endpoints) are organized per product. The environment dropdown only shows environments for the active product.
  5. **Per-Product Playwright Tests** — Playwright test files are organized per product (e.g. `tests/vprimedia/`, `tests/vtrade/`). The test suite browser filters to the active product's tests. Test runs inherit the active product context.
  6. **Product Config Registry** — A central product registry file (`products.yaml` or equivalent) maps each product slug to its Jira project key, personas directory, environments directory, and tests directory.
- **Acceptance Criteria**:
    - AC-1: A product selector is visible in the vQA UI; selecting a product updates the active product context throughout the application without a full page reload.
    - AC-2: The Jira card list only shows cards from the Jira project configured for the active product.
    - AC-3: The persona dropdown only shows personas from the active product's persona directory.
    - AC-4: The environment dropdown only shows environments from the active product's environment config.
    - AC-5: The Playwright test browser only shows tests scoped to the active product.
    - AC-6: Existing vProMedia personas, environments, and tests continue to function correctly when vProMedia is the selected product.
    - AC-7: A central product registry (config file or equivalent) maps each of the 6 products to its Jira key, personas, environments, and tests directory.
    - AC-8: Adding a new product requires only: (a) an entry in the product registry and (b) creating the product's personas/environments/tests directories — no code changes.
- **Key Files**:
    - `frontend/src/context/ProductContext.tsx` (New) — product context provider and selector hook
    - `frontend/src/components/ProductSelector.tsx` (New) — product picker UI component
    - `backend/config/products.yaml` (New) — central product registry
    - `backend/api/jira_routes.py` — scope Jira queries to active product's project key
    - `backend/config/personas/` — reorganize into per-product subdirectories
    - `backend/config/environments/` — reorganize into per-product subdirectories
    - `tests/` — reorganize Playwright tests into per-product subdirectories
- **Linked Tasks**: None
- **Branch**: feature/FEAT-114-multi-product-support
- **Created**: 2026-07-20
