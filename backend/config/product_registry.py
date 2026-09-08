"""
vQA — Product Registry
========================
Module: backend/config/product_registry.py

Single source of truth for all products under test by the vQA platform.

The registry is loaded from ``backend/config/products.yaml`` at startup.
It maps product slugs to ``ProductContext`` objects containing all
per-product metadata: environments, roles, Jira board IDs, filesystem paths.

Usage
-----
    from backend.config.product_registry import load_product_registry, ProductPublic

    registry = load_product_registry()          # loads from default products.yaml
    registry = load_product_registry(data={...}) # loads from in-memory dict (tests)

    product = registry.get("vpromedia")
    url = product.resolve_target_url("qa")
    public = ProductPublic.from_context(product)  # API-safe projection

Security
--------
- ``ProductPublic`` never exposes filesystem paths (playwright_tests_dir,
  personas_dir) or credentials. Only public metadata is returned by the API.
- NEVER put secrets in products.yaml — credentials live in AWS SSM.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default registry path — relative to repo root
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY_PATH = Path("backend/config/products.yaml")

# ---------------------------------------------------------------------------
# Repo root — used by validate_product_kb_roots() for filesystem checks.
# Tests patch this via: patch("backend.config.product_registry._REPO_ROOT", tmp_path)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProductKBMissingError(RuntimeError):
    """
    Raised by ``validate_product_kb_roots()`` when a product's declared
    knowledge directory does not exist on the filesystem at startup.
    """

    def __init__(self, product_slug: str, missing_path: Path) -> None:
        self.product_slug = product_slug
        self.missing_path = missing_path
        super().__init__(
            f"product_registry.load_failed: product={product_slug} "
            f"missing_root={missing_path}"
        )


# ---------------------------------------------------------------------------
# ProductContext — one entry from the YAML products map
# ---------------------------------------------------------------------------


class ProductContext(BaseModel):
    """
    Per-product metadata loaded from ``products.yaml``.

    The ``slug`` field is auto-injected from the YAML map key by
    ``ProductRegistry``'s model validator — it is not expected in the
    YAML body itself.

    Attributes
    ----------
    slug : str
        Lowercase alphanumeric + underscore identifier (e.g. ``"vpromedia"``).
        Auto-set from the YAML map key by ``ProductRegistry``.
    display_name : str
        Human-readable product name (e.g. ``"vProMedia"``).
    description : str
        Short product description for documentation / UI tooltips.
    order : int
        Display sort order (ascending). Products with lower ``order`` appear first.
    environments : dict[str, str]
        Map of environment name → base URL.
        Example: ``{"qa": "https://two-test.vcreative.net"}``
    default_environment : str
        The environment name used by ``resolve_target_url()`` when no explicit
        env is provided. Auto-set when ``environments`` has exactly one key.
    jira_board_ids : list[int]
        Jira Software board IDs to search for tickets. Empty list for products
        without Jira integration.
    roles : list[str]
        Role keys that belong to this product. Must match entries in
        ``backend/engine/roles.py::ROLE_REGISTRY``.
    ticket_title_filter : str
        When non-empty, the ``/tickets`` endpoint filters results to only
        include tickets whose summary contains this string (case-insensitive).
        This lets products share Jira boards while only showing their own
        tickets. Example: ``"vTrade"`` for the vTrade product.
    playwright_tests_dir : str
        Filesystem path (relative to repo root) for this product's Playwright
        tests. Example: ``"playwright/tests/vpromedia"``.
    personas_dir : str
        Filesystem path for this product's persona knowledge files.
        Example: ``"knowledge/personas/vpromedia"``.
    """

    slug: str = Field(default="", description="Auto-injected from YAML map key by ProductRegistry.")
    display_name: str = Field(..., description="Human-readable product name.")
    description: str = Field(default="", description="Short product description.")
    order: int = Field(default=999, description="Sort order (ascending).")
    environments: dict[str, str] = Field(..., description="Map of environment name → base URL.")
    default_environment: str = Field(
        default="",
        description="Environment used by resolve_target_url() when no env is specified.",
    )
    jira_board_ids: list[int] = Field(default_factory=list, description="Jira board IDs for this product.")
    roles: list[str] = Field(default_factory=list, description="Role keys belonging to this product.")
    ticket_title_filter: str = Field(default="", description="Case-insensitive substring filter for ticket summaries.")
    playwright_tests_dir: str = Field(default="", description="Filesystem path for Playwright tests.")
    personas_dir: str = Field(default="", description="Filesystem path for persona knowledge files.")
    knowledge_dir: str = Field(
        default="",
        description=(
            "T3-a: Filesystem path (relative to repo root) for this product's KB workflow files. "
            "Example: 'knowledge/vpromotions'. When empty, defaults to 'knowledge/<slug>' at "
            "validation time."
        ),
    )
    selector_registry_dir: str = Field(
        default="knowledge/selector_registry.json",
        description=(
            "T3-a: Filesystem path (relative to repo root) to the selector registry JSON for "
            "this product. Defaults to the shared global registry."
        ),
    )
    playwright_base_url: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional map of environment name → app URL for cross-domain products. "
            "When a product's app lives on a different domain from the Angular SSO gateway "
            "(e.g. vPPO's PHP app at hotfixes.sandbox.internal.vcreative.net), this field "
            "tells codegen and Playwright setup which URL to navigate to after login. "
            "Distinct from environments which holds the SSO login gateway URLs."
        ),
    )
    ghost_login_environments: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional override map of environment name → login URL used for ghost login authentication. "
            "When set, the ghost login node authenticates at this URL (e.g. the main vcreative site) "
            "instead of the product-specific URL, then navigates to the product URL after impersonation. "
            "Required for products like vPPO and vPromotions that share a login site with vProMedia."
        ),
    )

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Slug must be lowercase alphanumeric + underscore only."""
        if v == "":
            # Empty slug is allowed at definition time (injected later by registry)
            return v
        if not re.match(r"^[a-z0-9_]+$", v):
            raise ValueError(
                f"Invalid slug '{v}': must contain only lowercase letters, digits, and underscores."
            )
        return v

    @model_validator(mode="after")
    def _validate_and_autofill_default_environment(self) -> ProductContext:
        """
        Auto-set ``default_environment`` when ``environments`` has exactly one key.
        Raise if multiple environments exist and ``default_environment`` is not set
        or is not one of the environment keys.
        """
        envs = self.environments
        default = self.default_environment

        if len(envs) == 1 and not default:
            # Auto-promote the single key to be the default
            object.__setattr__(self, "default_environment", next(iter(envs)))
        elif len(envs) > 1 and not default:
            raise ValueError(
                f"Product has multiple environments {list(envs.keys())} but "
                f"'default_environment' is not set. Specify one of: {list(envs.keys())}"
            )
        elif default and default not in envs:
            raise ValueError(
                f"default_environment '{default}' is not a key in environments "
                f"{list(envs.keys())}."
            )

        return self

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def resolve_target_url(self, env: str | None = None) -> str:
        """
        Return the base URL for the given environment (or the default).

        Parameters
        ----------
        env : str | None
            Environment name (e.g. ``"qa"``, ``"staging"``).
            If ``None`` or omitted, ``default_environment`` is used.

        Returns
        -------
        str
            Base URL for the requested environment.

        Raises
        ------
        KeyError
            If ``env`` is provided but is not a key in ``environments``.
        """
        target_env = env or self.default_environment
        if target_env not in self.environments:
            raise KeyError(
                f"Unknown environment '{target_env}' for product '{self.slug}'. "
                f"Available: {list(self.environments.keys())}"
            )
        return self.environments[target_env]

    def resolve_ghost_login_url(self, env: str | None = None) -> str | None:
        """
        Return the authentication URL to use for ghost login, or None if no
        override is configured (meaning use the product's own target URL).

        Products like vPPO and vPromotions require logging in at the main
        vcreative site before navigating to the product, because they share
        the vcreative SSO system but live on separate subdomains.
        """
        if not self.ghost_login_environments:
            return None
        target_env = env or self.default_environment
        return self.ghost_login_environments.get(target_env)

    def has_role(self, role_key: str) -> bool:
        """
        Return ``True`` if ``role_key`` belongs to this product.

        Parameters
        ----------
        role_key : str
            Role key string to check (e.g. ``"account_executive"``).
        """
        return role_key in self.roles


# ---------------------------------------------------------------------------
# ProductRegistry — the collection of all products
# ---------------------------------------------------------------------------


class ProductRegistry(BaseModel):
    """
    Collection of all registered products.

    Attributes
    ----------
    schema_version : int
        YAML schema version (currently 1). Reserved for future migrations.
    products : dict[str, ProductContext]
        Map of slug → ProductContext.
    """

    schema_version: int = Field(default=1)
    products: dict[str, ProductContext] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _inject_slugs(self) -> ProductRegistry:
        """Inject the YAML map key as the ``slug`` field in each ProductContext."""
        for slug, product_ctx in self.products.items():
            # Validate slug format (products.yaml key → slug)
            if not re.match(r"^[a-z0-9_]+$", slug):
                raise ValueError(
                    f"Invalid product slug '{slug}': must be lowercase alphanumeric + underscore only."
                )
            # Inject slug into the context (bypass Pydantic immutability)
            object.__setattr__(product_ctx, "slug", slug)
        return self

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def get(self, slug: str) -> ProductContext:
        """
        Return the ``ProductContext`` for a given slug.

        Raises
        ------
        KeyError
            If ``slug`` is not registered.
        """
        if slug not in self.products:
            raise KeyError(
                f"Unknown product slug '{slug}'. Registered products: {sorted(self.products.keys())}"
            )
        return self.products[slug]

    def list(self) -> list[ProductContext]:
        """
        Return all products sorted by ``order`` (ascending), then by ``slug`` as a
        tie-breaker.
        """
        return sorted(self.products.values(), key=lambda p: (p.order, p.slug))

    def slugs(self) -> list[str]:
        """Return all registered product slugs (unsorted)."""
        return list(self.products.keys())

    def contains_role(self, role_key: str) -> str | None:
        """
        Return the slug of the product that owns ``role_key``, or ``None`` if
        no product claims that role.

        Parameters
        ----------
        role_key : str
            Role key to search for.

        Returns
        -------
        str | None
            Product slug, or ``None`` if not found.
        """
        for slug, product in self.products.items():
            if product.has_role(role_key):
                return slug
        return None


# ---------------------------------------------------------------------------
# ProductPublic — API-safe projection (no secrets, no filesystem paths)
# ---------------------------------------------------------------------------


class ProductPublic(BaseModel):
    """
    API-safe projection of a ``ProductContext``.

    Deliberately excludes:
    - ``playwright_tests_dir`` — internal filesystem path
    - ``personas_dir`` — internal filesystem path

    Only public, non-sensitive metadata is included.
    """

    slug: str
    display_name: str
    description: str
    order: int
    environments: dict[str, str]
    default_environment: str
    jira_board_ids: list[int]
    roles: list[str]
    ticket_title_filter: str = ""

    @classmethod
    def from_context(cls, ctx: ProductContext) -> ProductPublic:
        """
        Build a ``ProductPublic`` from a ``ProductContext``.

        Filesystem paths and any server-internal fields are intentionally
        omitted — this is the safe projection for the ``GET /products`` endpoint.
        """
        return cls(
            slug=ctx.slug,
            display_name=ctx.display_name,
            description=ctx.description,
            order=ctx.order,
            environments=ctx.environments,
            default_environment=ctx.default_environment,
            jira_board_ids=ctx.jira_board_ids,
            roles=ctx.roles,
            ticket_title_filter=ctx.ticket_title_filter,
        )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_product_registry(
    path: Path | None = None,
    data: dict[str, Any] | None = None,
) -> ProductRegistry:
    """
    Load and return a ``ProductRegistry``.

    When both ``path`` and ``data`` are provided, ``data`` takes precedence
    (dict mode). When neither is provided, the default path
    (``DEFAULT_REGISTRY_PATH``) is used.

    Parameters
    ----------
    path : Path | None
        Filesystem path to a ``products.yaml`` file. Ignored when ``data``
        is provided.
    data : dict | None
        In-memory dict representation of the YAML file (for tests — avoids
        file I/O).

    Returns
    -------
    ProductRegistry
        Validated registry with all slugs injected.

    Raises
    ------
    pydantic.ValidationError
        If any product entry is malformed or fails validation.
    FileNotFoundError
        If ``path`` is provided but the file does not exist.
    """
    if data is not None:
        # Dict mode — takes precedence (used by tests)
        return ProductRegistry.model_validate(data)

    # File mode
    registry_path = path if path is not None else DEFAULT_REGISTRY_PATH
    registry_path = Path(registry_path)

    if not registry_path.exists():
        raise FileNotFoundError(f"Product registry file not found: {registry_path}")

    with registry_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raw = {}

    return ProductRegistry.model_validate(raw)


# ---------------------------------------------------------------------------
# T3-a — Startup KB root validation (AC-VERIFY-1 / CQ-A1)
# ---------------------------------------------------------------------------


def validate_product_kb_roots(
    registry: ProductRegistry,
    *,
    repo_root: Path | None = None,
    exit_on_failure: bool = False,
) -> None:
    """
    Validate that every active product's declared KB roots exist on the filesystem.

    Stub products (roles == []) are exempt: they cannot be executed.

    Raises ProductKBMissingError when any active product's knowledge_dir is missing.
    """
    root = repo_root if repo_root is not None else _REPO_ROOT

    for slug, product in registry.products.items():
        if not product.roles:
            logger.debug(
                "product_registry: skipping KB validation for stub product '%s' (roles=[])",
                slug,
            )
            continue

        kb_dir_str = product.knowledge_dir or f"knowledge/{slug}"
        kb_path = root / kb_dir_str

        if not kb_path.exists():
            msg = (
                f"product_registry.load_failed: product={slug} "
                f"missing_root={kb_path}"
            )
            logger.error(msg)
            if exit_on_failure:
                sys.exit(1)
            raise ProductKBMissingError(slug, kb_path)

        if product.personas_dir:
            personas_path = root / product.personas_dir
            if not personas_path.exists():
                logger.warning(
                    "product_registry: personas_dir missing for product '%s': %s (non-fatal)",
                    slug,
                    personas_path,
                )

    logger.info(
        "product_registry: KB root validation passed for %d active product(s)",
        sum(1 for p in registry.products.values() if p.roles),
    )
    return None


def product_kb_available(product_slug: str, registry: "ProductRegistry | None" = None) -> bool:
    """
    T3-a hot-reload guard: return True if the product's knowledge directory
    exists on disk RIGHT NOW (defence-in-depth for POST /execute).
    """
    if registry is not None:
        try:
            product = registry.get(product_slug)
        except KeyError:
            return False
        if not product.roles:
            return True
        kb_dir_str = product.knowledge_dir or f"knowledge/{product_slug}"
    else:
        kb_dir_str = f"knowledge/{product_slug}"

    return (_REPO_ROOT / kb_dir_str).exists()
