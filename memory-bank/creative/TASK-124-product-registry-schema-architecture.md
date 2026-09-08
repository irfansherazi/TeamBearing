# Architecture Decision: Product Registry Schema (`backend/config/products.yaml`)

**Task**: TASK-124 — Multi-Product Support (Phase 1 / Q2)
**Feature**: FEAT-115 — Multi-Product Support
**Created**: 2026-07-20
**Status**: DECIDED
**Decision Type**: Architecture — Data Schema & Loader
**Author**: `bmb:creative-architecture-agent` (Opus 4.7)

---

## Context

### System Requirements

The vQA platform must evolve from a hardcoded single-product (vProMedia) testing tool into a first-class multi-product platform that supports six products today (vProMedia, vTrade, vEP, vPPO, vPromotions, PSN) and can grow to N products in the future. All product-specific configuration currently spread across `backend/config.py` (globals) and `backend/engine/roles.py` (implicit role-to-product mapping) must be centralized in a single declarative registry.

The registry is the **single source of truth** for:

1. Which Jira boards belong to which product (`jira_board_ids`)
2. Which role keys belong to which product (`roles`)
3. What target application URL(s) each product uses (`target_url` / `environments`)
4. Where each product's Playwright test tree lives (`playwright_tests_dir`)
5. Where each product's persona knowledge files live (`personas_dir`)

### Technical Constraints

- **C-1 (Zero-code-change growth)**: Adding a 7th product must require ONLY (a) a new entry in `products.yaml` and (b) creating the two per-product filesystem directories. **No Python code edits.** This is the hardest constraint and drives most of the decision.
- **C-2 (No secrets in YAML)**: Credentials MUST NOT appear in `products.yaml`. They continue to live in AWS SSM (`/vQA/roles/*`, `/vQA/jira/*`) and are looked up by role key at runtime.
- **C-3 (Pydantic v2 idiom)**: The existing `backend/config.py` uses `pydantic-settings` v2 with `Field(default=..., description=...)`. The loader must fit this idiom to keep `Settings` cohesive.
- **C-4 (Env-var override respected)**: Existing users may have `JIRA_BOARD_IDS=27,36` or `TARGET_URL=...` set in their shell. Phase 1 must not silently drop these; the registry values should be the **new source of truth** but the migration must be observable (a startup log line, not a silent switch).
- **C-5 (Frontend has no knowledge of products at bundle time)**: The React app must fetch `/products` at boot and dynamically render whatever the registry contains. No hardcoded product enum in TypeScript beyond a discovered union.
- **C-6 (Empty-state hygiene, AC-ERROR-2)**: A product with `jira_board_ids: []`, `roles: []`, and a missing test directory must still load and render — not raise a startup exception.
- **C-7 (Backwards-compatible startup)**: Existing test runs against vProMedia must not break on Day 1 of the migration.

### Non-Functional Requirements

- **NFR-Perf-1**: Registry load happens once at process startup; cost budget is < 50 ms including YAML parse and Pydantic validation.
- **NFR-Perf-2**: `settings.get_product(slug)` accessor is O(1) hash lookup — called on every `/execute`, `/tickets`, `/preview-steps` request.
- **NFR-Security-1**: The `/products` HTTP response is a strict projection — role KEYS only, never credentials, never board API tokens. A Pydantic response model enforces this at the type level.
- **NFR-Observability-1**: Structured log at startup: `product_registry.loaded product_count=6 slugs=[vpromedia,vtrade,...]`. Structured log per resolution: `product_registry.resolved slug=vtrade jira_board_ids=[36]`. Correlate with `traceId` per FR requirements in CLAUDE.md.
- **NFR-Testability-1**: The loader must be injectable — tests must be able to pass in a `dict` or path override without setting env vars or writing temp files (though it must ALSO support that path).
- **NFR-Migratability-1**: An entry currently absent from the registry (e.g. someone forgets to add vEP) must produce a clear error at request time (`404 product 'vep' not registered`), not a silent fallback to `settings.jira_board_ids`.

### Existing Patterns to Respect

- **File location convention**: Static registry-like config lives under `backend/config/` (new) or is referenced by relative path from `Settings.playwright_tests_dir`. YAML "data as code" precedent exists at `knowledge/blueprints/*.yaml` (heavy header comments, snake_case keys, top-of-file rationale block).
- **Loader pattern**: `Settings` is a Pydantic `BaseSettings` singleton exposed as `settings`. New per-product accessors should live as methods on `Settings` so callers continue to import a single object.
- **Role registry pattern**: `backend/engine/roles.py::ROLE_REGISTRY` is a `dict[str, RoleContext]` built at module load. Product registry mirrors this shape: `dict[str, ProductContext]`.

---

## Component Analysis

### Core Components

| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `products.yaml` | Declarative source of truth for all products | Store slug → {jira_board_ids, roles, target_url/environments, playwright_tests_dir, personas_dir, display_name, description} |
| `ProductContext` (Pydantic model) | Typed per-product config | Validate individual product entries; provide `resolve_target_url(env: str \| None)` helper |
| `ProductRegistry` (Pydantic model) | Typed collection wrapper | Validate slug uniqueness, expose `.get(slug)`, `.list()`, `.contains_role(role_key)` |
| `load_product_registry(path)` | Loader function | Read YAML, materialize into `ProductRegistry`, log summary, fail fast on schema errors |
| `Settings.product_registry` | Attribute on the global settings singleton | Lazily loaded; `settings.get_product(slug)` accessor |
| `ProductPublic` (Pydantic response model) | API surface projection | Fields exposed via `/products` endpoint — no credentials, no absolute filesystem paths |
| `/products` FastAPI route | Frontend discovery endpoint | Returns list of `ProductPublic` — feeds the product-selector dropdown |

### Component Interactions

```
┌───────────────────────────────────────────────────────────────────────┐
│                           process startup                             │
└───────────────────────────────────────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┴──────────────────────────────────┐
    ▼                                                                  ▼
Settings.__init__                                          load_product_registry(
  ├─ reads env vars                                          Path("backend/config/products.yaml")
  ├─ builds jira/otel/etc config                           )
  └─ calls load_product_registry(...) ────────────────────► reads YAML file
                                                            ├─ yaml.safe_load(...)
                                                            ├─ ProductRegistry(**data)   ← Pydantic validates
                                                            ├─ log_summary(...)
                                                            └─ returns ProductRegistry
                                    │
                                    ▼
                          settings.product_registry
                                    │
    ┌───────────────────────────────┼──────────────────────────────────────────┐
    ▼                               ▼                                          ▼
GET /products               GET /tickets?product=vtrade              POST /execute {product,role,...}
project ProductPublic       registry.get("vtrade").jira_board_ids    registry.get(product).contains_role(role) → validate
```

---

## Options Explored

### Option A: Flat Map `products: {slug: {…}}`

- **Description**: Single YAML file. Top-level key `products:` is a mapping whose keys are the product slugs. Each value is an inline object with the product's fields.

  ```yaml
  products:
    vpromedia:
      display_name: vProMedia
      jira_board_ids: [27, 36]
      roles: [account_executive, sales_manager, ...]
      target_url: https://two-test.vcreative.net
      playwright_tests_dir: playwright/tests/vpromedia
      personas_dir: knowledge/personas/vpromedia
    vtrade:
      display_name: vTrade
      jira_board_ids: [36]
      roles: [vtrade_exec, vtrade_business_manager, vtrade_sales_manager]
      target_url: https://vtrade-qa.vcreative.net
      playwright_tests_dir: playwright/tests/vtrade
      personas_dir: knowledge/personas/vtrade
  ```

- **Architecture Diagram**:
  ```
  products.yaml (single file)
        │
        ▼
  yaml.safe_load → dict[str, dict]
        │
        ▼
  ProductRegistry(root={slug: ProductContext})   ← Pydantic RootModel
        │
        ▼
  registry.get("vtrade") → ProductContext
  ```

- **Pros**:
  - **Slug uniqueness is enforced by YAML itself** — duplicate top-level keys are a YAML parse error. No manual `set()` check needed.
  - Lookup by slug is native: `data["products"]["vtrade"]` is just a dict access.
  - Diff-friendly: adding/removing a product is a single hunk in one file.
  - Matches the existing `ROLE_REGISTRY: dict[str, RoleContext]` pattern in the codebase (mental parallel).
  - One file → one review, one PR. Reviewer sees the full picture at a glance.

- **Cons**:
  - Six products with 5–10 fields each = ~150 lines in one file. Manageable but not tiny.
  - The slug appears once (as the map key) rather than being redundantly declared in each entry — good for DRY, but slightly less "self-describing" if you excerpt a single entry out of context.
  - Cannot easily template or generate per-product files with codegen.

- **Technical Fit**: **High** — mirrors `ROLE_REGISTRY` idiom already used in the codebase.
- **Complexity**: **Low** — one file, one loader function, one Pydantic model.
- **Scalability**: **Medium** — fine up to ~20 products. Beyond that, split-file (Option C) becomes preferable.

---

### Option B: List of Product Objects

- **Description**: Top-level `products:` is a YAML list; each element is a full product object with `slug` as one of its fields.

  ```yaml
  products:
    - slug: vpromedia
      display_name: vProMedia
      jira_board_ids: [27, 36]
      roles: [account_executive, sales_manager, ...]
      target_url: https://two-test.vcreative.net
      playwright_tests_dir: playwright/tests/vpromedia
      personas_dir: knowledge/personas/vpromedia
    - slug: vtrade
      display_name: vTrade
      ...
  ```

- **Pros**:
  - Each product entry is self-describing (`slug:` appears inside the block).
  - Preserves declaration order deterministically — useful if the UI wants to render products in a defined order (though `int order:` field solves this without a list).
  - Familiar shape for anyone from a Kubernetes/Helm background (`items: [...]`).

- **Cons**:
  - **Duplicate slugs are silently allowed by YAML** — Pydantic must validate uniqueness explicitly. Extra loader code and a fresh failure mode.
  - Lookup is O(n) unless the loader builds an index dict — doable, but that means the raw YAML shape is *not* the shape the code consumes. Two mental models for the same data.
  - Adding a new field to all products requires touching every list element (each is standalone) — no schema-level default sharing without extra scaffolding.

- **Technical Fit**: **Medium** — perfectly valid YAML but foreign to this codebase's dict-registry style.
- **Complexity**: **Low-Medium** — adds an explicit uniqueness validator and a build-index step.
- **Scalability**: **Medium** — same practical ceiling as A.

---

### Option C: Split Files — `products.yaml` (manifest) + `products/<slug>.yaml` (per-product)

- **Description**: Master manifest lists slugs; each slug has its own file.

  ```yaml
  # products.yaml
  products:
    - vpromedia
    - vtrade
    - vep
    - vppo
    - vpromotions
    - psn
  ```
  ```yaml
  # products/vpromedia.yaml
  slug: vpromedia
  display_name: vProMedia
  jira_board_ids: [27, 36]
  roles: [account_executive, ...]
  target_url: https://two-test.vcreative.net
  playwright_tests_dir: playwright/tests/vpromedia
  personas_dir: knowledge/personas/vpromedia
  ```

- **Pros**:
  - Per-product PRs touch a single file → clean git blame, easy `CODEOWNERS` scoping (e.g. `products/vtrade.yaml @vtrade-team`).
  - Scales cleanly to 50+ products without one giant file.
  - Enables per-product schema evolution — one product can adopt a new optional field ahead of others.

- **Cons**:
  - **Violates C-1 subtly**: adding a product now requires editing `products.yaml` AND creating `products/<slug>.yaml`. Two files, not one. (Still zero code, but higher ceremony.)
  - Two-step load: read manifest, then fan out to per-slug files. More error surface (what if manifest lists `vep` but `products/vep.yaml` is missing?).
  - Overkill for a 6-product world today. YAGNI.
  - Harder to see the whole registry at once during code review.

- **Technical Fit**: **Medium** — good pattern, but doesn't match this repo's density (small config surface).
- **Complexity**: **Medium** — two file reads, cross-file validation.
- **Scalability**: **High** — best of the three for 50+ products.

---

### Option D (discovered): Hybrid — Flat map + `!include` per-product **defaults blocks**

- **Description**: Start with Option A's flat map, but allow a top-level `defaults:` block that all product entries inherit unless they override. Example:

  ```yaml
  defaults:
    playwright_tests_dir: "playwright/tests/{slug}"      # {slug} interpolated
    personas_dir: "knowledge/personas/{slug}"
    environments:
      qa: "https://{slug}-qa.vcreative.net"

  products:
    vpromedia:
      display_name: vProMedia
      jira_board_ids: [27, 36]
      roles: [account_executive, ...]
      # inherits playwright_tests_dir → playwright/tests/vpromedia
      # inherits personas_dir → knowledge/personas/vpromedia
      environments:
        qa: https://two-test.vcreative.net    # explicit override
  ```

- **Pros**: DRY. Adding a new product with default conventions is 3 lines.
- **Cons**: Introduces a **DSL** (template interpolation, inheritance rules) — non-standard YAML behavior. Every future developer has to learn the merge algorithm. Violates the "simplest thing that works" principle for a 6-product registry. Debugging "why did my override not apply?" adds real cognitive load.
- **Verdict**: **Rejected** — premature abstraction. If defaults-inheritance ever becomes worth it (say, 20+ products), we revisit. For now, ~5 lines of repetition per product across 6 products is cheaper than a config DSL.

---

## Evaluation Matrix

Scores: **H** = High / good, **M** = Medium, **L** = Low / poor. "Fit" and "Zero-Code-Change" are the load-bearing criteria per C-1.

| Criteria | Option A (flat map) | Option B (list) | Option C (split files) | Option D (defaults DSL) |
|----------|---------------------|-----------------|------------------------|-------------------------|
| Zero-code-change to add product (C-1) | **H** — edit 1 file | **H** — edit 1 file | M — edit 2 files | H |
| Slug uniqueness enforcement | **H** — free from YAML | L — needs explicit validator | M — cross-file check | M |
| Loader complexity | **H** (low) | M | L (higher) | L (much higher) |
| Schema readability at review time | **H** — whole picture | H | M — must open N files | L — indirection |
| Pattern fit with existing codebase | **H** — mirrors ROLE_REGISTRY | M | M | L |
| Testability (dict override) | H | H | M — path fanout | M |
| Scalability to 20+ products | M | M | **H** | H |
| Scalability to 100+ products | L | L | **H** | H |
| Time to implement | **H** (fast) | M | L (slower) | L |
| Empty-state hygiene (AC-ERROR-2) | H (any option handles this) | H | H | M |

**Load-bearing signals**: A wins on fit, uniqueness, complexity, and readability. C wins on scale-to-100. Today we have 6 products with a plausible ceiling of 15–20 over the next 2–3 years. **A is the right choice for our size; C is a migration target if we ever cross 25 products.**

---

## Environment Modeling: Single URL vs. Map

A separate decision inside the schema: is `target_url` a **string** or a **map** of `env → url`?

### E-Option 1: Single string per product

```yaml
target_url: https://two-test.vcreative.net
```

- **Pros**: Matches today's global `settings.target_url` shape 1:1. Zero migration friction. YAGNI-compliant.
- **Cons**: When we inevitably want to run a suite against staging or prod, we scaffold `staging_url`, `prod_url` as siblings and end up with an ad-hoc string bag.

### E-Option 2: Explicit environments map

```yaml
environments:
  qa: https://vtrade-qa.vcreative.net
  staging: https://vtrade-staging.vcreative.net
  prod: https://vtrade.vcreative.net
default_environment: qa
```

- **Pros**: Clean primitive for the near-future multi-env test story. The `/execute` payload can accept `environment: "staging"` and resolve via the registry.
- **Cons**: Complexity that isn't paid for on Day 1. All six products currently ship with QA only. Verbose.

### E-Option 3 (chosen): **Environments map REQUIRED; single-env is the trivial case**

```yaml
environments:
  qa: https://two-test.vcreative.net
default_environment: qa
```

- **Rationale**: Slightly more YAML (2 lines vs. 1), but the loader is uniform — no `if isinstance(target_url, str): treat as {default: target_url}` branching in Python. This is the single sharpest instance of C-1: adding staging later is a one-line YAML edit, not a schema migration.
- **Accessor**: `product.resolve_target_url(env=None)` returns `environments[env or default_environment]`, raising `KeyError` on missing env with a helpful message.
- **Note**: If `default_environment` is omitted, the loader defaults it to the single key when `len(environments) == 1`; otherwise it's required. This keeps the trivial single-env case terse.

---

## Observability Architecture

### Logging

- **Library**: existing structured logger in `backend/utils/logging.py` (Pydantic-friendly, JSON output, includes `traceId`/`spanId`).
- **Startup event**: `INFO product_registry.loaded product_count=6 slugs=[vpromedia,vtrade,vep,vppo,vpromotions,psn] path=backend/config/products.yaml`
- **Startup validation failure**: `ERROR product_registry.load_failed path=... error=... field=... — process exits with non-zero`
- **Per-resolution**: `DEBUG product_registry.resolved slug=vtrade jira_board_ids=[36] target_url=https://vtrade-qa.vcreative.net env=qa`
- **Missing-product error**: `WARN product_registry.miss slug=vunknown available=[vpromedia,...]` — surfaced to `/products/{slug}` as 404.

### Distributed Tracing

- **SDK**: OpenTelemetry (already in use per CLAUDE.md).
- **Span**: `product_registry.load` at startup with attributes `products.count`, `products.slugs`, `products.file_path`.
- **Span**: `product_registry.get` on each accessor call, attribute `product.slug`, linked to the parent HTTP request span via `traceparent` propagation.

### Metrics

- `vqa_product_registry_load_duration_seconds` — histogram, one sample per process boot.
- `vqa_product_registry_lookup_total{slug, result}` — counter labels `result=hit|miss`; watch for high miss rate as a signal of a stale frontend cache.
- `vqa_product_registry_products_count` — gauge set at boot; expected to be constant unless we hot-reload (not planned).

### Configuration Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `VQA_PRODUCTS_CONFIG` | Absolute path to `products.yaml` override | `backend/config/products.yaml` |
| `LOG_LEVEL` | Log verbosity | `info` |
| `OTEL_SERVICE_NAME` | Service id in traces | `vqa-backend` |

No secrets are ever read by the registry loader — credentials remain in SSM per C-2.

---

## Decision

**Chosen: Option A (Flat Map) + Environments Map (E-Option 3)**

### Canonical YAML — `backend/config/products.yaml`

```yaml
# ────────────────────────────────────────────────────────────────────────────
# vQA Product Registry
# ────────────────────────────────────────────────────────────────────────────
#
# Single source of truth for all products under test by the vQA platform.
#
# ADDING A NEW PRODUCT
# --------------------
# 1. Add a new top-level entry under `products:` below.
#    - `slug` is the map key (must be lowercase, alphanumeric + underscore).
#    - Required fields:  display_name, environments, default_environment,
#                        jira_board_ids, roles, playwright_tests_dir,
#                        personas_dir
#    - Optional fields:  description, order
# 2. Create the two filesystem directories referenced by the entry:
#      - playwright/tests/<slug>/
#      - knowledge/personas/<slug>/
#    (Empty directories are OK — vQA renders empty state gracefully.)
# 3. That's it. No Python code changes required.
#
# NEVER PUT SECRETS HERE
# ----------------------
# Login credentials and Jira API tokens live in AWS SSM under `/vQA/roles/*`
# and `/vQA/jira/*` respectively. This file lists ROLE KEYS only — the runtime
# resolves keys → credentials via SSM at request time.
#
# SCHEMA
# ------
# See backend/config/product_registry.py::ProductContext for the authoritative
# Pydantic model.  The loader validates every entry at startup and fails fast.
# ────────────────────────────────────────────────────────────────────────────

schema_version: 1

products:

  # ──────────────────────────────────────────────────────────────────────────
  # vProMedia (production — existing product, all 9 roles)
  # ──────────────────────────────────────────────────────────────────────────
  vpromedia:
    display_name: vProMedia
    description: >
      Radio broadcast production management — sales, traffic, dubbing, and
      digital pipelines. The original vQA target product.
    order: 1
    environments:
      qa: https://two-test.vcreative.net
    default_environment: qa
    jira_board_ids: [27, 36]
    roles:
      - account_executive
      - sales_manager
      - sales_assistant
      - production_manager
      - producer
      - gm_gsm
      - dubber
      - digital_director
      - demo_prod_director
    playwright_tests_dir: playwright/tests/vpromedia
    personas_dir: knowledge/personas/vpromedia

  # ──────────────────────────────────────────────────────────────────────────
  # vTrade (partial bootstrap from TASK-012 — 3 roles, board 36)
  # ──────────────────────────────────────────────────────────────────────────
  vtrade:
    display_name: vTrade
    description: >
      Radio ad-inventory trade / barter marketplace. Financial and contract
      oversight surface layered on top of vProMedia's traffic engine.
    order: 2
    environments:
      qa: https://vtrade-qa.vcreative.net
    default_environment: qa
    jira_board_ids: [36]
    roles:
      - vtrade_exec
      - vtrade_business_manager
      - vtrade_sales_manager
    playwright_tests_dir: playwright/tests/vtrade
    personas_dir: knowledge/personas/vtrade

  # ──────────────────────────────────────────────────────────────────────────
  # vPromotions (single existing role — vpromotions_user)
  # ──────────────────────────────────────────────────────────────────────────
  vpromotions:
    display_name: vPromotions
    description: >
      Promotions and contests management surface for radio stations.
    order: 3
    environments:
      qa: https://vpromotions-qa.vcreative.net
    default_environment: qa
    jira_board_ids: []          # to be populated when boards exist
    roles:
      - vpromotions_user
    playwright_tests_dir: playwright/tests/vpromotions
    personas_dir: knowledge/personas/vpromotions

  # ──────────────────────────────────────────────────────────────────────────
  # vEP  (empty stub — awaiting boards, roles, and tests)
  # ──────────────────────────────────────────────────────────────────────────
  vep:
    display_name: vEP
    description: >
      vEP product surface — placeholder entry. Board IDs, roles, and Playwright
      tests will be populated as the product enters vQA coverage.
    order: 4
    environments:
      qa: https://vep-qa.vcreative.net
    default_environment: qa
    jira_board_ids: []          # AC-ERROR-2: empty must render clean state
    roles: []                   # AC-ERROR-2: empty must render clean state
    playwright_tests_dir: playwright/tests/vep       # dir may not yet exist
    personas_dir: knowledge/personas/vep             # dir may not yet exist

  # ──────────────────────────────────────────────────────────────────────────
  # vPPO  (empty stub)
  # ──────────────────────────────────────────────────────────────────────────
  vppo:
    display_name: vPPO
    description: >
      vPPO product surface — placeholder entry.
    order: 5
    environments:
      qa: https://vppo-qa.vcreative.net
    default_environment: qa
    jira_board_ids: []
    roles: []
    playwright_tests_dir: playwright/tests/vppo
    personas_dir: knowledge/personas/vppo

  # ──────────────────────────────────────────────────────────────────────────
  # PSN  (empty stub)
  # ──────────────────────────────────────────────────────────────────────────
  psn:
    display_name: PSN
    description: >
      Programmatic Sales Network — placeholder entry.
    order: 6
    environments:
      qa: https://psn-qa.vcreative.net
    default_environment: qa
    jira_board_ids: []
    roles: []
    playwright_tests_dir: playwright/tests/psn
    personas_dir: knowledge/personas/psn
```

### Pydantic Models — `backend/config/product_registry.py`

```python
"""
vQA — Product Registry
======================
Module: backend/config/product_registry.py

Loads `backend/config/products.yaml` into strongly-typed Pydantic models and
exposes accessors for per-product configuration. See the file's header comment
for the authoring contract.

Design decision: TASK-124 (memory-bank/creative/TASK-124-product-registry-
schema-architecture.md). Flat map + environments map. Zero-code-change growth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, RootModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# ProductContext — one product entry
# ---------------------------------------------------------------------------

class ProductContext(BaseModel):
    """Typed configuration for a single product in the registry."""

    slug: str = Field(
        ...,
        description="Lowercase alphanumeric+underscore identifier; matches the "
                    "top-level YAML map key. Injected by the loader.",
    )
    display_name: str = Field(..., description="Human-readable product name.")
    description: str | None = Field(
        default=None, description="Short prose description for UI/docs.",
    )
    order: int = Field(
        default=100,
        description="Sort order in the product-selector dropdown. Lower = earlier.",
    )
    environments: dict[str, str] = Field(
        ...,
        description="Map of environment name (qa/staging/prod/...) → base URL. "
                    "Must contain at least one entry.",
    )
    default_environment: str | None = Field(
        default=None,
        description="Which env in `environments` is used when the caller does "
                    "not specify one. Optional if `environments` has exactly one key.",
    )
    jira_board_ids: list[int] = Field(
        default_factory=list,
        description="Jira Software board IDs owned by this product. Empty list "
                    "is valid — the product will render an empty ticket list.",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Role keys (must exist in backend/engine/roles.ROLE_REGISTRY) "
                    "that belong to this product.",
    )
    playwright_tests_dir: str = Field(
        ...,
        description="Path (relative to repo root) to this product's Playwright "
                    "test tree. Directory may be empty or not yet exist.",
    )
    personas_dir: str = Field(
        ...,
        description="Path (relative to repo root) to this product's persona "
                    "knowledge files. Directory may be empty or not yet exist.",
    )

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c == "_" for c in v) or not v.islower():
            raise ValueError(
                f"slug '{v}' must be lowercase alphanumeric+underscore only",
            )
        return v

    @model_validator(mode="after")
    def _resolve_default_env(self) -> "ProductContext":
        if not self.environments:
            raise ValueError(f"{self.slug}: environments must be non-empty")
        if self.default_environment is None:
            if len(self.environments) == 1:
                # Trivial case: single env is the default.
                object.__setattr__(
                    self,
                    "default_environment",
                    next(iter(self.environments)),
                )
            else:
                raise ValueError(
                    f"{self.slug}: default_environment is required when "
                    f"environments has multiple keys ({list(self.environments)})",
                )
        if self.default_environment not in self.environments:
            raise ValueError(
                f"{self.slug}: default_environment '{self.default_environment}' "
                f"not in environments {list(self.environments)}",
            )
        return self

    def resolve_target_url(self, env: str | None = None) -> str:
        """Return the base URL for the given environment (or default)."""
        key = env or self.default_environment
        if key not in self.environments:
            raise KeyError(
                f"product '{self.slug}' has no environment '{key}'. "
                f"Available: {list(self.environments)}",
            )
        return self.environments[key]

    def has_role(self, role_key: str) -> bool:
        """AC-ERROR-3 gate: is `role_key` valid for this product?"""
        return role_key in self.roles


# ---------------------------------------------------------------------------
# ProductRegistry — the collection
# ---------------------------------------------------------------------------

class ProductRegistry(BaseModel):
    """Typed collection wrapper over the flat products map."""

    schema_version: int = Field(default=1, description="Registry schema version.")
    products: dict[str, ProductContext] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _inject_slugs_and_validate(self) -> "ProductRegistry":
        for slug, product in self.products.items():
            # Slug in the map key is authoritative; inject into the model.
            if product.slug and product.slug != slug:
                raise ValueError(
                    f"slug mismatch: map key '{slug}' vs product.slug "
                    f"'{product.slug}'. Remove `slug:` from the entry body.",
                )
            object.__setattr__(product, "slug", slug)
        return self

    def get(self, slug: str) -> ProductContext:
        if slug not in self.products:
            raise KeyError(
                f"product '{slug}' not registered. "
                f"Available: {sorted(self.products)}",
            )
        return self.products[slug]

    def list(self) -> list[ProductContext]:
        """Return products sorted by `order` then slug for deterministic UI."""
        return sorted(self.products.values(), key=lambda p: (p.order, p.slug))

    def slugs(self) -> list[str]:
        return [p.slug for p in self.list()]

    def contains_role(self, role_key: str) -> str | None:
        """Return the slug that owns `role_key`, or None if orphaned."""
        for slug, product in self.products.items():
            if role_key in product.roles:
                return slug
        return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY_PATH = Path("backend/config/products.yaml")


def load_product_registry(
    path: Path | None = None,
    data: dict[str, Any] | None = None,
) -> ProductRegistry:
    """Load and validate the product registry.

    Two modes:
      * File mode: pass `path=` (defaults to `DEFAULT_REGISTRY_PATH`, override
        via `VQA_PRODUCTS_CONFIG` env var — resolved by the caller).
      * Dict mode: pass `data=` for tests. Takes precedence over `path`.
    """
    if data is None:
        target = path or DEFAULT_REGISTRY_PATH
        with target.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    return ProductRegistry.model_validate(data)


# ---------------------------------------------------------------------------
# API projection — safe subset for GET /products
# ---------------------------------------------------------------------------

class ProductPublic(BaseModel):
    """Safe projection returned by GET /products. NO credentials, NO absolute
    filesystem paths."""

    slug: str
    display_name: str
    description: str | None
    order: int
    environments: dict[str, str]        # URLs are non-secret and needed by UI
    default_environment: str
    jira_board_ids: list[int]
    roles: list[str]                    # ROLE KEYS only

    @classmethod
    def from_context(cls, ctx: ProductContext) -> "ProductPublic":
        return cls(
            slug=ctx.slug,
            display_name=ctx.display_name,
            description=ctx.description,
            order=ctx.order,
            environments=ctx.environments,
            default_environment=ctx.default_environment or "",
            jira_board_ids=ctx.jira_board_ids,
            roles=ctx.roles,
        )
```

### Rationale

1. **Fit over cleverness.** Option A mirrors the existing `ROLE_REGISTRY: dict[str, RoleContext]` idiom exactly. A developer opening `products.yaml` for the first time will feel the same shape they already know from `roles.py`. Consistency compounds.
2. **YAML gives us uniqueness for free.** Duplicate top-level keys are a parse-time error — we get the C-1 slug uniqueness guarantee without writing a validator or discovering a bug in prod.
3. **One-file scope matches our size.** Six products, ~15 lines each = ~100 lines of YAML. Fits comfortably in one editor screen. If we ever cross ~25 products, Option C becomes worth the migration; the flat-map shape is compatible with a future split (each split file is essentially a slice of Option A).
4. **Environments map costs one extra line today, saves a schema migration tomorrow.** The moment someone asks for a staging run, they add one YAML line — not a Python code change and a data migration. This is the sharpest version of C-1.
5. **Empty lists everywhere for stubs.** AC-ERROR-2 is honored by making `jira_board_ids: list[int]` and `roles: list[str]` default to `[]` — a stub product is legal and renders as a clean empty state.
6. **Public projection model separates concerns.** `ProductPublic.from_context` guarantees the `/products` endpoint cannot leak credentials or absolute paths — it simply doesn't have fields for them. Type-level enforcement > runtime discipline.
7. **Loader accepts `data=` for tests.** No temp files, no env-var juggling. Tests read like `load_product_registry(data={"products": {"vtrade": {...}}})`.

### Trade-offs Accepted

- **We chose 6 files of duplication over a defaults DSL.** ~30 lines of "the same shape repeated" in exchange for zero config-magic to explain. Cheap.
- **We accept a small migration cost if we ever hit 25+ products.** Splitting the flat map into per-file entries is a mechanical `git mv`-style transformation, not a schema change. Both shapes deserialize into the same `dict[str, ProductContext]`, so a future Option-C loader can co-exist during the migration.
- **We accept coordinated changes with the sibling creative "Role↔Product Enforcement".** Our schema declares `roles:` per product (Option B in the sibling document's framing). If the sibling picks the "product on RoleContext" flavor, we keep the field as a soft-manifest-with-audit — the loader logs any role listed in `products.yaml` whose `RoleContext.product` disagrees. The reconciler is a 20-line function; the schema does not need to change.

---

## Implementation Guidelines

1. **File placement**:
   - `backend/config/products.yaml` — the registry data
   - `backend/config/product_registry.py` — the Pydantic models + loader
   - `backend/config/__init__.py` — new (empty is fine)
2. **Integration with `backend/config.py::Settings`**:
   - Add `product_registry: ProductRegistry` computed field, populated in a `@model_validator(mode="after")` that calls `load_product_registry(Path(self._resolve_registry_path()))`.
   - Add `Settings.get_product(slug: str) -> ProductContext` convenience method (thin passthrough).
   - **Do NOT delete** `settings.jira_board_ids` or `settings.target_url` in Phase 1 — mark them `deprecated=True` in Field metadata and log a `WARN` if any caller still reads them. Phase 6 removes them once no callers remain.
3. **Startup logging** (per Observability section):
   - Log the product count, slugs, and file path at INFO on successful load.
   - Log field-level Pydantic errors and exit non-zero on validation failure.
4. **`/products` endpoint** (a separate small ticket, but the response model belongs here):
   - Route: `GET /products` → `list[ProductPublic]`
   - Use `[ProductPublic.from_context(p) for p in settings.product_registry.list()]`
   - Return 200 with an empty list if the registry has zero products (never crash).
5. **`/products/{slug}` endpoint** (optional but recommended):
   - Route: `GET /products/{slug}` → `ProductPublic` — returns 404 with `product_registry.miss` log line if unknown.
6. **AC-ERROR-3 enforcement point**:
   - In the `/execute` request handler, after resolving `product = settings.get_product(payload.product)`, check `if not product.has_role(payload.role): raise HTTPException(400, ...)`.
7. **Path handling**:
   - `playwright_tests_dir` and `personas_dir` are stored as **relative** strings and resolved against the repo root at consumption time. This keeps the YAML portable across dev/docker/CI and avoids leaking absolute paths through `/products`.
8. **Env override**:
   - Read `VQA_PRODUCTS_CONFIG` in `Settings` to allow tests / staging to point at an alternate registry file. Never allow this in production (guard by NODE_ENV or an explicit deployment env var).

---

## Validation Checklist

- [x] Meets all system requirements — single source of truth for all 5 fields per product
- [x] Respects technical constraints — no secrets in YAML (C-2), Pydantic v2 idiom (C-3), empty-state legal (C-6)
- [x] Addresses NFRs — O(1) accessors, structured logging, testable loader, safe API projection
- [x] Technically feasible — pure YAML + Pydantic, no new dependencies (PyYAML and Pydantic already in the stack)
- [x] Risks identified and acceptable — see Risk Assessment below
- [x] Complies with Guiding Principles in systemPatterns.md — no deviations required
- [x] Respects established patterns in systemPatterns.md — mirrors `ROLE_REGISTRY` shape, uses `pydantic-settings` idiom
- [x] Observability architecture defined — logs, spans, metrics all specified
- [x] Trace context propagation across all service boundaries — `product_registry.get` span linked via `traceparent`
- [x] Logging strategy consistent with observability-requirements.md — structured JSON, no secrets
- [x] Metrics strategy follows naming conventions — `vqa_*` prefix, low-cardinality labels

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Registry file missing at startup | L | H (crash) | Fail fast with clear error naming the expected path and the `VQA_PRODUCTS_CONFIG` override. |
| Slug mismatch between YAML map key and inline `slug:` field | L | M | `ProductRegistry._inject_slugs_and_validate` raises with a pointed message. Contract: authors do NOT put `slug:` inside the entry body (map key is authoritative). |
| Role listed in `products.yaml` but not present in `ROLE_REGISTRY` | M | M | Startup cross-check emits `WARN product_registry.orphan_role` per orphaned role and exits non-zero (config error, not a soft warning). Implemented outside this schema — in a startup hook after both registries load. |
| Frontend caches stale `/products` response after a config change | M | L | Set `Cache-Control: no-cache` on `/products`; UI refetches on every mount. Deployment restart naturally clears state. |
| Someone commits an SSM secret into `products.yaml` | L | H (leak) | Pre-commit hook via `.gitattributes` / `gitleaks` scans YAML for known secret patterns. Enforced by CI in Phase 5. |
| `default_environment` semantics confusion | M | L | Doc-string on the field + validator error message + single-env auto-default keep the trivial case terse and the multi-env case explicit. |
| Product with unreachable `target_url` at test time | H | M (test flake) | Existing pre-flight URL reachability check (see `settings.skip_preflight` in `backend/config.py:963`) handles this — no schema-level change needed. |
| Migration: existing `JIRA_BOARD_IDS=27,36` env var silently overridden | M | M | Emit `WARN` log at startup when both env var and registry values exist and disagree, naming the winner (registry). Remove env vars in Phase 6. |

---

## Next Steps

1. **Implement** `backend/config/product_registry.py` (Pydantic models + loader) — TDD with a `tests/config/test_product_registry.py` covering: happy path, slug validation, missing default_environment, unknown role in entry, duplicate slug (YAML parse error), empty products dict, `resolve_target_url` env resolution.
2. **Populate** `backend/config/products.yaml` with the canonical content above (all 6 products).
3. **Integrate** into `backend/config.py::Settings` via a `@model_validator` that loads the registry and adds `get_product(slug)`, marking `jira_board_ids` and `target_url` as deprecated.
4. **Ship** `GET /products` and `GET /products/{slug}` endpoints in Phase 1 backend work.
5. **Refactor** existing call sites of `settings.jira_board_ids` and `settings.target_url` to route through `settings.get_product(payload.product)` — per-endpoint, in later phases.
6. **Coordinate** with the Role↔Product Enforcement creative decision to finalize the `roles:` field semantics (source-of-truth question). This schema is compatible with either outcome.

---

## Phase 6 Decision: Product-Aware Knowledge Base — DEFERRED (2026-07-21)

**Decision**: Do NOT implement KB/RAG product-scoping in TASK-124.

**Rationale**: No creative exploration (Q3 or otherwise) identified a concrete user scenario where a cross-product persona leak causes a test failure or incorrect test execution. The KB (`backend/engine/kb_client.py`) is already implicitly product-scoped by Phase 3: each test run passes the product-specific `personas_dir` to `load_local_persona_credentials()`, so the retrieval pool is already bounded per product. A global ChromaDB index has no cross-product personas in it today (all 11 persona files are vProMedia-specific). The marginal safety gain from adding a product filter to the RAG layer is zero at current data volume.

**When to revisit**: If vTrade personas are added and an automated test run pulls a vProMedia persona credential by similarity, re-open this decision. The `personas_dir` parameter already exists and is the natural extension point — adding a metadata filter to ChromaDB queries would be a Level 2 task at that point.

**Phase 6 closure**: Mark as DEFERRED (not SKIPPED) so future operators know this was an explicit decision, not an oversight.
