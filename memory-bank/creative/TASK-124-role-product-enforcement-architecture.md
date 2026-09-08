# Architecture Decision: Role↔Product Enforcement (TASK-124 / FEAT-115)

**Created**: 2026-07-20
**Status**: DECIDED
**Decision Type**: Architecture
**Feature**: FEAT-115 Multi-Product Support
**Coordinates with**: Registry Schema creative (Option A flat map in `backend/config/products.yaml`)

---

## Context

### System Requirements

- 13 role keys currently exist in `backend/engine/roles.py` and are duplicated as a
  literal list in `backend/api/schemas.py` (`VALID_ROLES`). They must become
  **product-aware** so that:
  1. The frontend role dropdown filters to the active product's roles (AC-HAPPY-2).
  2. The backend rejects a `/execute` request whose `role` is not part of the
     given `product` with a 400 error (AC-ERROR-3).
  3. Adding a new product requires **only** editing `products.yaml` and creating
     per-product directories — **zero code changes** (feature NFR).
- Existing sibling creative decision (registry schema): `products.yaml` uses a
  **flat map** keyed by product slug, and each product entry contains a
  `roles: [<role_key>, ...]` list.

### Technical Constraints

- `ROLE_REGISTRY` in `backend/engine/roles.py` is ~600 lines with 13
  `RoleContext(...)` blocks. Modifying every one to add a `product=` kwarg is
  surgical but wide.
- `RoleContext` is a `TypedDict` (`backend/engine/state.py:239`) — adding a new
  field is cheap, but the field then must be populated at every construction
  site.
- `Settings` (`backend/config.py`) is a Pydantic `BaseSettings` singleton loaded
  once at process startup. Cross-validation belongs in a `model_validator` on
  the registry loader, not on `Settings` itself.
- `VALID_ROLES` in `schemas.py` is currently a hardcoded literal — this must be
  replaced with a dynamic lookup that reflects the union of all product roles.
- The `/execute` route handler is in `backend/api/routes.py:1239` and currently
  does not know about `product` at all (product field will be added by the
  parallel schema-extension phase of TASK-124).
- Role credentials live inside `RoleContext` and **must never leak to the
  frontend** — the `/products` response returns role **keys** only, no
  credentials, no email fallbacks.

### Non-Functional Requirements

- **Single source of truth**: adding a role to a product must not require
  editing two files (both `products.yaml` AND `roles.py`).
- **Startup-fast validation**: cross-validation must run **once** at process
  boot, not on every `/execute` request.
- **Fail-fast**: an orphan role key (in `products.yaml` but missing from
  `ROLE_REGISTRY`, or vice-versa) must crash the process at startup with a
  clear error message — never at request time.
- **12-Factor compliant**: role↔product mapping is **config**, not code (per
  systemPatterns.md Guiding Principle).
- **Zero-code new-product**: the new-product path must not touch any `.py`
  file.
- **No credential leakage**: `/products` API returns only role keys (whitelist
  of primitives), never `RoleContext` objects.

---

## Component Analysis

### Core Components

| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `backend/config/products.yaml` | Product registry file | Source of truth for product→roles mapping (schema Option A already decided) |
| `backend/config/products.py` (new) | Product registry loader | Parse YAML, cross-validate against `ROLE_REGISTRY`, expose `PRODUCT_REGISTRY` singleton and `get_product_for_role()` |
| `backend/engine/roles.py` | Role registry (unchanged) | Continues to define `RoleContext` objects; `ROLE_REGISTRY` unchanged in shape |
| `backend/api/schemas.py` — `ExecuteRequest` | Request validator | Validates `role` and `product`, then cross-validates that role ∈ product's roles |
| `backend/api/routes.py` — `/execute` | Route handler | Consumes validated request; does not need extra checks |
| `backend/api/routes.py` — `GET /products` (new) | Product discovery endpoint | Returns `[{slug, display_name, roles: [...], environments: {...}}]` for frontend dropdown wiring |

### Component Interactions

```
                                   ┌──────────────────────────────────────┐
                                   │  products.yaml (source of truth)     │
                                   │  vpromedia: { roles: [ae, sm, ...] } │
                                   └───────────────┬──────────────────────┘
                                                   │ parsed at startup
                                                   ▼
      ┌───────────────────┐         ┌─────────────────────────────────┐
      │  ROLE_REGISTRY    │◄────────┤  ProductRegistry loader         │
      │  (roles.py)       │  cross- │  (backend/config/products.py)   │
      │  UNCHANGED        │  check  │  - loads YAML                   │
      └───────────────────┘         │  - asserts every role in yaml   │
                                    │    exists in ROLE_REGISTRY      │
                                    │  - builds role→product index    │
                                    │  - CRASH on mismatch            │
                                    └──────────────┬──────────────────┘
                                                   │
                              ┌────────────────────┼───────────────────┐
                              ▼                    ▼                   ▼
                 ┌────────────────────┐  ┌──────────────────┐  ┌──────────────┐
                 │ ExecuteRequest     │  │ GET /products    │  │ frontend     │
                 │ Pydantic validator │  │ route            │  │ dropdown     │
                 │ (schemas.py)       │  │ (routes.py)      │  │ (react)      │
                 │ role ∈ product.roles│  │ returns roles: []│  │              │
                 └────────┬───────────┘  └──────────────────┘  └──────────────┘
                          │
                          ▼
                    /execute handler
                    (already-validated request)
```

---

## Options Explored — Role→Product Mapping Storage

### Option A: `product: str` field on `RoleContext`

- **Description**: Add a `product: str` field to `RoleContext` (`state.py:239`)
  and set it on every one of the 13 entries in `roles.py`. The backend derives
  a product's role list by filtering `ROLE_REGISTRY.values()`. The `roles: [...]`
  key in `products.yaml` becomes redundant (or a validation cross-check).
- **Pros**:
  - Role↔product association lives next to the role definition (Python code).
  - No YAML lookup needed at request time — direct dict access.
  - Type-checkable via mypy/pyright.
- **Cons**:
  - Requires touching **every one of 13 `RoleContext(...)` blocks** in
    `roles.py` — surgical but wide edit; every new role also requires an edit.
  - **Contradicts the "zero-code new-product" NFR**: adding roles for a new
    product means editing `roles.py`, not just `products.yaml`.
  - Splits truth between YAML (product metadata) and Python (role→product
    membership) — the two can drift, and the schema Option A already chose to
    put `roles: [...]` in `products.yaml`.
  - Frontend still needs a `/products` endpoint anyway to get `display_name`,
    `environments`, `jira_board_ids` — so we don't save a network hop.
- **Technical Fit**: Medium (fights the schema Option A decision)
- **Complexity**: High (13 edit sites, plus every future role adds one)
- **Scalability**: Medium (linear scan `[r for r in ROLE_REGISTRY.values() if r["product"] == slug]` is fine)

### Option B: `roles: [...]` list in `products.yaml` only

- **Description**: Keep `ROLE_REGISTRY` **untouched**. Declare product
  membership entirely in `products.yaml` (schema already decided this). The
  loader validates that every role key in every product's `roles: [...]`
  exists in `ROLE_REGISTRY`, and that **no role key appears in more than one
  product** (mutual exclusivity assertion). The frontend gets product→roles
  via `/products`. `RoleContext` schema is unchanged.
- **Pros**:
  - **Single source of truth** for the product→role mapping: `products.yaml`.
  - **Zero code changes for a new product**: `products.yaml` + directories only.
  - Aligns exactly with the sibling schema Option A decision (roles already
    in YAML).
  - Config-driven per **Guiding Principle: Config in Environment** and
    **12-Factor App** in `systemPatterns.md`.
  - `roles.py` stays a pure catalog of role definitions — separation of
    concerns preserved.
  - Adding a role to an existing product: **one edit** in `products.yaml`
    (plus the role definition itself in `roles.py`, which is unavoidable
    regardless of option).
- **Cons**:
  - Loader must build (and cache) a reverse index `role_key → product_slug`
    at startup to answer `get_product_for_role()` in O(1) at request time.
  - `RoleContext` doesn't self-describe its product — you must ask the
    registry. (Trivial to expose via a helper.)
  - If a role is genuinely shared across products in the future (unlikely
    for vProMedia/vTrade/vEP given they are separate applications), Option B
    forces a `mutual exclusivity` assertion that would need to be relaxed.
- **Technical Fit**: **High** — matches schema decision + Guiding Principles
- **Complexity**: **Low** — 1 loader file, 0 edits to `roles.py`
- **Scalability**: High (dict lookup)

### Option C: Hybrid — YAML + cross-assertion, no `product:` field

- **Description**: Same as Option B (roles in `products.yaml`, `RoleContext`
  unchanged), plus an explicit `assert` block at startup that verifies:
  1. Every role in `products.yaml` exists in `ROLE_REGISTRY`.
  2. Every role in `ROLE_REGISTRY` appears in exactly one product in
     `products.yaml`.
  3. No role key appears in >1 product.

  The assertion runs once at `ProductRegistry.__init__` (or as a
  `model_validator` on the Pydantic loader).
- **Pros**: Everything Option B has, **plus** a formal contract that
  guarantees the two sources agree at boot. Fails **loudly and immediately**
  on drift — critical for the "13 roles today, unknown tomorrow" reality.
- **Cons**: ~20 lines of assertion code on top of Option B — negligible.
- **Technical Fit**: **Highest**
- **Complexity**: Low (Option B + ~20 lines of validator)
- **Scalability**: Same as B (loader runs once at boot)

### Option D (rejected early): Enum with product prefix (`vpromedia.account_executive`)

- **Description**: Namespace role keys with product prefix.
- **Cons**: Breaking change to every existing role key across
  frontend/backend/tests/personas/creds; violates "no code changes for new
  product"; forces every existing API caller and stored run history to
  migrate. Not pursued further.

---

## Options Explored — Enforcement Point on `/execute`

### Sub-option i: Pydantic `model_validator` on `ExecuteRequest`

- Cross-field validator inside `schemas.py` — validates `role ∈ product.roles`
  at request-parse time. Returns 422 (unprocessable entity) via Pydantic's
  standard error path. Requires the validator to import the loaded
  `PRODUCT_REGISTRY` — no circular imports as long as `products.py` doesn't
  import `schemas.py`.
- **Pros**: Zero business-logic pollution in route handler; consistent with
  existing `@field_validator("role")` pattern at `schemas.py:243`; FastAPI
  auto-documents the constraint in `/docs`; unit-testable with plain Pydantic
  instantiation.
- **Cons**: Returns 422 by default, not 400 — but the AC only asks for a
  "clear message on invalid combination", which 422 satisfies. If AC-ERROR-3
  strictly requires 400, we override in the route handler (see i+iii below).

### Sub-option ii: Middleware intercepting every `/execute` POST

- **Cons**: Runs on every request even when validation is unnecessary; must
  re-parse the JSON body before it reaches the route; middleware doesn't have
  access to already-parsed Pydantic model; hard to unit test in isolation.
  Rejected.

### Sub-option iii: Explicit check in route handler

- Runs after Pydantic parse but before `make_initial_state()`. Raises
  `HTTPException(status_code=400, ...)`.
- **Pros**: Full control over status code and error message body — can return
  exactly 400 per AC-ERROR-3.
- **Cons**: Business logic in route handler; drift risk (`/execute-batch`
  needs the same check duplicated); not visible in OpenAPI docs.

### Sub-option iv: Check inside `playwright_executor.py`

- **Cons**: Too late — the run has already been created, a `run_id`
  allocated, WebSocket subscribers connected. Fails the "fast-fail before
  side effects" principle. Rejected.

### Enforcement Point Trade-off Summary

| Approach | Status Code | OpenAPI Docs | Duplication Risk | Testability |
|----------|-------------|--------------|------------------|-------------|
| i. Pydantic validator | 422 | Auto | None (schema applies to all callers) | Excellent |
| iii. Route handler | 400 | Manual | High (need duplicate in `/execute-batch`) | Good |
| i + iii | 400 | Auto + Manual | None | Best |

---

## Evaluation Matrix

### Storage options (A / B / C)

| Criteria | Option A (RoleContext field) | Option B (YAML only) | Option C (YAML + assertion) |
|----------|------------------------------|----------------------|-----------------------------|
| Scalability | Medium | High | High |
| Maintainability | Low (13 edit sites) | High | High |
| Performance | High (dict) | High (dict) | High (dict) |
| Security | Same | Same | Same |
| Observability | Low (no drift detection) | Medium | **High (loud fail on drift)** |
| Alignment with schema Option A | Low (contradicts) | High | High |
| Zero-code new-product NFR | **Violates** | Satisfies | Satisfies |
| Implementation Cost | High | Low | Low |
| Guiding Principles compliance (Config in Env, 12-Factor) | Weak | Strong | Strong |

### Enforcement options (i / ii / iii / iv)

| Criteria | i (validator) | ii (middleware) | iii (route) | iv (executor) |
|----------|---------------|-----------------|-------------|---------------|
| Fast-fail before side effects | Yes | Yes | Yes | **No** |
| OpenAPI documented | Yes | No | No | No |
| Consistent with existing patterns | **Yes** | No | Partial | No |
| Reusable by `/execute-batch` | Yes | Yes | No | No |
| Custom 400 status possible | No (422) | Yes | Yes | Yes |

---

## Observability Architecture

### Logging
- **Library**: `logging.getLogger(__name__)` — matches every other module in
  `backend/` (no new dependency; project uses stdlib `logging` throughout).
- **Startup log**: `products.py` logs `INFO — loaded N products, K roles
  cross-validated OK` at the end of `ProductRegistry.__init__`. On drift,
  logs `ERROR — product '<slug>' declares role '<key>' which is not in
  ROLE_REGISTRY` and raises.
- **Request-time log**: `schemas.py` validator logs at `DEBUG` level on
  success; Pydantic's own `ValidationError` handler logs the rejection
  reason at `WARN`.
- **Sensitive data**: Never log role credentials or the raw `RoleContext`
  object. Log role key + product slug only. (Aligns with existing NFR:
  "Role credentials must never appear in logs".)

### Distributed Tracing
- **N/A for this feature** — enforcement is a synchronous in-process check.
  Existing OpenTelemetry trace context (attached to the `/execute` span by
  the FastAPI middleware, per `CLAUDE.md` observability standards) covers
  it automatically. Span attributes will include `vqa.product`, `vqa.role`.

### Metrics
- **`vqa_execute_rejected_total{reason="role_not_in_product"}`** — counter
  incremented every time the enforcement path returns a 400. This is the
  primary signal that AC-ERROR-3 is firing in production.
- **`vqa_product_registry_load_seconds`** — histogram of startup load time
  (should be <100ms).
- Both are Prometheus-format via the existing `prometheus_client` if wired
  (out of scope for TASK-124; documented for future).

### Configuration Variables
| Variable | Purpose | Default |
|----------|---------|---------|
| `VQA_PRODUCT_REGISTRY_PATH` | Path to `products.yaml` | `backend/config/products.yaml` |
| `VQA_PRODUCT_REGISTRY_STRICT` | If `true`, crash on drift; if `false`, log-only (dev escape hatch) | `true` |

---

## Decision

**Chosen — Storage**: **Option C** (roles in `products.yaml` + startup cross-assertion, `ROLE_REGISTRY` untouched)

**Chosen — Enforcement Point**: **Sub-option i (Pydantic validator on `ExecuteRequest`) with sub-option iii (explicit `HTTPException(400, ...)` in the route handler) as a thin adapter to convert the 422 into the 400 required by AC-ERROR-3.**

In practice the validator is the single source of enforcement logic — a Pydantic `model_validator(mode="after")` — and the route handler wraps the `ValidationError` (or re-checks) to re-raise as `HTTPException(status_code=400)`. This gives us: OpenAPI documentation, batch-endpoint reuse, and the exact 400 status the AC demands.

### Rationale

- **Aligns with sibling schema decision (Option A flat map)** which already
  puts `roles: [...]` inside each product entry in `products.yaml`. Option B/C
  is the natural continuation.
- **Satisfies the "zero code changes for new product" NFR** — the killer
  constraint that eliminates Option A.
- **Complies with Guiding Principles in `systemPatterns.md`**: *Config in
  Environment* and *12-Factor App* — role→product mapping is configuration,
  not code.
- **`ROLE_REGISTRY` untouched** — avoids a 600-line surgical edit and
  eliminates the drift class where developer forgets to set
  `product="vpromedia"` on a new `RoleContext(...)`.
- **The Option C assertion prevents silent drift**: someone deleting a role
  from `roles.py` without updating `products.yaml` (or vice versa) triggers
  a startup crash with a clear error — not a mysterious 500 at request time.
- **Pydantic validator is idiomatic** for this codebase — `schemas.py`
  already uses `@field_validator("role")` at `schemas.py:243`. A
  `@model_validator(mode="after")` for the cross-field check is the
  natural extension.
- **The thin `HTTPException(400)` adapter** honors AC-ERROR-3's literal
  status-code requirement without splitting enforcement logic across two
  files.

### Trade-offs Accepted

- **Reverse index rebuild cost on every process boot**: negligible (~5ms for
  N=6 products × ~13 total roles); happens once at startup, not per request.
- **Role→product lookup requires a helper call, not a `role.product`
  attribute**: acceptable — the helper `get_product_for_role(role_key)`
  returns O(1) from the pre-built dict. Clean separation.
- **`VALID_ROLES` literal list in `schemas.py:56-70` must be replaced with a
  dynamic import** from the loader. This is a code change but a **one-time
  migration** — after this, adding a role for a new product does not touch
  `schemas.py` again.
- **`products.yaml` becomes the authoritative role-membership file**: docs
  and onboarding must reflect this (out of scope for TASK-124 but flagged).

### Coordination with Registry Schema Decision

The sibling creative phase chose **Option A: flat map** in
`backend/config/products.yaml` with `roles: [...]` per product. **This
decision (Option C) consumes that schema directly** — no schema changes
required. Specifically:
- `products.yaml` already has `roles:` under each product.
- The loader defined here reads that field, validates it, and builds the
  reverse index.
- **We do NOT add `roles:` a second time via `product:` on RoleContext** (that
  would be Option A, rejected).

---

## Implementation Guidelines / Pseudocode Sketch

The full enforcement path — startup validation + runtime check — in ~25 lines:

```python
# ── backend/config/products.py (new file) ─────────────────────────────────
import yaml
from pathlib import Path
from backend.engine.roles import ROLE_REGISTRY

class ProductRegistry:
    def __init__(self, yaml_path: Path):
        raw = yaml.safe_load(yaml_path.read_text())
        self.products: dict[str, dict] = raw["products"]

        # Cross-validate at startup (Option C assertion)
        role_to_product: dict[str, str] = {}
        for slug, product in self.products.items():
            for role_key in product.get("roles", []):
                if role_key not in ROLE_REGISTRY:
                    raise RuntimeError(
                        f"Product '{slug}' declares role '{role_key}' "
                        f"which is not in ROLE_REGISTRY (roles.py)"
                    )
                if role_key in role_to_product:
                    raise RuntimeError(
                        f"Role '{role_key}' appears in both "
                        f"'{role_to_product[role_key]}' and '{slug}' "
                        f"— role keys must belong to exactly one product"
                    )
                role_to_product[role_key] = slug
        self._role_to_product = role_to_product

    def get_product_for_role(self, role_key: str) -> str | None:
        return self._role_to_product.get(role_key)

    def roles_for_product(self, slug: str) -> list[str]:
        return list(self.products.get(slug, {}).get("roles", []))

    def all_valid_roles(self) -> set[str]:
        return set(self._role_to_product.keys())

PRODUCT_REGISTRY = ProductRegistry(Path("backend/config/products.yaml"))

# ── backend/api/schemas.py (modified) ─────────────────────────────────────
from pydantic import BaseModel, Field, model_validator
from backend.config.products import PRODUCT_REGISTRY

class ExecuteRequest(BaseModel):
    jira_ticket_id: str = Field(...)
    role: str = Field(...)
    product: str = Field(...)   # NEW — added by the schema-extension phase
    # ... other existing fields ...

    @model_validator(mode="after")
    def _validate_role_matches_product(self):
        expected = PRODUCT_REGISTRY.get_product_for_role(self.role)
        if expected is None:
            raise ValueError(f"Unknown role '{self.role}'")
        if expected != self.product:
            raise ValueError(
                f"Role '{self.role}' belongs to product '{expected}', "
                f"not '{self.product}'"
            )
        return self

# ── backend/api/routes.py (modified /execute handler) ─────────────────────
from fastapi import HTTPException
from pydantic import ValidationError

# FastAPI already runs the model_validator during request parsing and would
# return 422 by default. To honor AC-ERROR-3's 400 requirement, register a
# custom exception handler on the ExecuteRequest ValidationError path OR
# override in the route:

@router.post("/execute", ...)
async def execute_single(request: ExecuteRequest, http_request: Request):
    # Pydantic has already validated role ∈ product.roles at parse time —
    # if we got here, it passed. But we also do an explicit belt-and-suspenders
    # check to make the intent visible + return 400 (not 422) if a future
    # refactor removes the validator:
    if PRODUCT_REGISTRY.get_product_for_role(request.role) != request.product:
        raise HTTPException(
            status_code=400,
            detail=f"Role '{request.role}' does not belong to product "
                   f"'{request.product}'"
        )
    # ... proceed with make_initial_state(), etc. ...
```

The route-handler check is a **belt-and-suspenders defense** — the actual
enforcement runs at Pydantic parse time. If someone later removes the
validator, the route handler still enforces AC-ERROR-3.

### Extensibility: Adding a New Product

To add a hypothetical `vfoo` product (per the NFR):

1. Edit `backend/config/products.yaml`:
   ```yaml
   vfoo:
     display_name: vFoo
     jira_board_ids: [42]
     roles: [vfoo_admin, vfoo_editor]
     environments: {qa: https://vfoo-qa.vcreative.net}
     default_environment: qa
     playwright_tests_dir: playwright/tests/vfoo
     personas_dir: knowledge/personas/vfoo
   ```
2. Add `vfoo_admin` and `vfoo_editor` `RoleContext(...)` entries to
   `ROLE_REGISTRY` in `roles.py` (unavoidable — this is the role's own
   definition, not the product mapping).
3. Create `knowledge/personas/vfoo/` and `playwright/tests/vfoo/` directories.

**Zero edits** to `schemas.py`, `routes.py`, `config.py`, or `products.py`
loader logic. NFR satisfied.

---

## Validation Checklist

- [x] Meets all system requirements (AC-HAPPY-2, AC-ERROR-3, zero-code new-product)
- [x] Respects technical constraints (`ROLE_REGISTRY` shape untouched)
- [x] Addresses NFRs (single source of truth, startup-fast validation, fail-fast)
- [x] Technically feasible (Pydantic 2 `model_validator` is standard; PyYAML already in the project)
- [x] Risks identified and mitigated (see Risk Assessment)
- [x] **Complies with Guiding Principles**: *Config in Environment*, *12-Factor App* (`products.yaml` is config)
- [x] **Respects established patterns in systemPatterns.md**: matches existing `@field_validator` pattern in `schemas.py:243`
- [x] Observability strategy defined (logging + metrics for enforcement rejections)
- [x] Coordinates with sibling schema Option A decision — reuses `roles:` key already in schema
- [x] Metrics naming follows Prometheus conventions (`vqa_execute_rejected_total`)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Developer edits `roles.py` without updating `products.yaml` (adds an orphan role) | Medium | Medium | Option C startup assertion crashes the process with clear error |
| Developer edits `products.yaml` with a typo (references non-existent role) | Medium | High | Same startup assertion catches it before any request |
| Circular import between `products.py` and `roles.py` | Low | High | `products.py` imports from `roles.py` only, never the reverse — enforced by convention + code review |
| Frontend cached role list becomes stale after `products.yaml` edit | Low | Low | `/products` endpoint is stateless; a deploy invalidates browser cache. Add cache-control header if issue emerges. |
| Same role legitimately needed by two products in the future | Low | Medium | Mutual-exclusivity assertion in Option C can be relaxed to `list[str]` per role → product without breaking storage; documented as a future extension point |
| Pydantic `model_validator` import cycle with `products.py` importing at module top | Low | Medium | Import `PRODUCT_REGISTRY` inside the validator function body, or lazy-init via `functools.lru_cache` on the loader |
| `/execute-batch` doesn't get the same validation | Medium | Medium | `BatchTicketItem` in `schemas.py:330` should get the same `model_validator` — flagged as follow-up in TASK-124 build phase |

---

## Test Strategy — `tests/backend/test_role_product_enforcement.py`

The test file must assert the full contract in ≤5 tests. Each test operates
against the real `PRODUCT_REGISTRY` singleton (no mocks — the whole point is
to detect drift):

```python
# tests/backend/test_role_product_enforcement.py

def test_every_role_in_yaml_exists_in_role_registry():
    """Every role key in products.yaml must be in ROLE_REGISTRY."""
    from backend.config.products import PRODUCT_REGISTRY
    from backend.engine.roles import ROLE_REGISTRY
    for slug, product in PRODUCT_REGISTRY.products.items():
        for role_key in product.get("roles", []):
            assert role_key in ROLE_REGISTRY, (
                f"products.yaml declares '{role_key}' under '{slug}' "
                f"but it is not in ROLE_REGISTRY"
            )

def test_every_role_in_registry_belongs_to_exactly_one_product():
    """Every ROLE_REGISTRY entry must appear in exactly one product."""
    from backend.config.products import PRODUCT_REGISTRY
    from backend.engine.roles import ROLE_REGISTRY
    for role_key in ROLE_REGISTRY:
        assert PRODUCT_REGISTRY.get_product_for_role(role_key) is not None, (
            f"Role '{role_key}' is orphaned — not assigned to any product"
        )

def test_no_role_belongs_to_multiple_products():
    """A role key must not appear in two products' 'roles:' lists."""
    from backend.config.products import PRODUCT_REGISTRY
    seen: dict[str, str] = {}
    for slug, product in PRODUCT_REGISTRY.products.items():
        for role_key in product.get("roles", []):
            assert role_key not in seen, (
                f"Role '{role_key}' is in both '{seen[role_key]}' and '{slug}'"
            )
            seen[role_key] = slug

def test_execute_request_rejects_mismatched_role_product():
    """POST /execute with role=account_executive + product=vtrade must fail."""
    from backend.api.schemas import ExecuteRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="does not belong"):
        ExecuteRequest(
            jira_ticket_id="VC2-1",
            role="account_executive",   # a vpromedia role
            product="vtrade",           # ...paired with wrong product
        )

def test_execute_request_accepts_valid_role_product_pair():
    """POST /execute with role=vtrade_exec + product=vtrade must succeed."""
    from backend.api.schemas import ExecuteRequest
    req = ExecuteRequest(
        jira_ticket_id="VC2-1",
        role="vtrade_exec",
        product="vtrade",
    )
    assert req.role == "vtrade_exec"
    assert req.product == "vtrade"
```

An **integration test** additionally verifies AC-ERROR-3 through the HTTP layer:

```python
def test_execute_endpoint_returns_400_on_role_product_mismatch(client):
    """HTTP /execute must return 400 (not 422) per AC-ERROR-3."""
    resp = client.post("/execute", json={
        "jira_ticket_id": "VC2-1",
        "role": "account_executive",
        "product": "vtrade",
    })
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"]
```

---

## Next Steps

1. **TASK-124 build phase** creates `backend/config/products.py` with the
   `ProductRegistry` class and the startup assertion (Option C).
2. **TASK-124 build phase** replaces `VALID_ROLES` literal in
   `schemas.py:56-70` with `list(PRODUCT_REGISTRY.all_valid_roles())`.
3. **TASK-124 build phase** adds `product: str` field to `ExecuteRequest`
   plus the `@model_validator(mode="after")` cross-check.
4. **TASK-124 build phase** adds `GET /products` route returning
   `{slug, display_name, roles: [...], environments: {...}}` for the frontend.
5. **TASK-124 build phase** adds `HTTPException(400)` belt-and-suspenders
   check inside `/execute` route handler.
6. **TASK-124 build phase** writes `tests/backend/test_role_product_enforcement.py`
   per the test strategy above (5 unit tests + 1 integration test).
7. **TASK-124 build phase** applies same `model_validator` to
   `BatchTicketItem` for `/execute-batch` parity.
8. **Follow-up (out of scope for TASK-124)**: expose the enforcement metrics
   (`vqa_execute_rejected_total`) via the existing Prometheus wiring.
