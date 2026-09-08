"""
tests/backend/test_product_registry.py
========================================
TDD tests for TASK-124, Phase 1: Product Registry.

Verifies the Pydantic loader and registry models in
backend/config/product_registry.py.

Test strategy: use load_product_registry(data={...}) for all isolated tests to
avoid file I/O. One test reads the real products.yaml to validate the
canonical 6-product configuration.

ALL TESTS SHOULD FAIL until Phase 1 implementation is complete (TDD RED phase).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Import target (does not exist yet — this import will fail in RED phase)
# ---------------------------------------------------------------------------
from backend.config.product_registry import (
    ProductContext,
    ProductPublic,
    ProductRegistry,
    load_product_registry,
)

# ---------------------------------------------------------------------------
# Minimal fixture dicts used across tests
# ---------------------------------------------------------------------------

VTRADE_ENTRY: dict = {
    "display_name": "vTrade",
    "description": "Trade marketplace.",
    "order": 2,
    "environments": {"qa": "https://vtrade-qa.vcreative.net"},
    "default_environment": "qa",
    "jira_board_ids": [36],
    "roles": ["vtrade_exec", "vtrade_business_manager", "vtrade_sales_manager"],
    "playwright_tests_dir": "playwright/tests/vtrade",
    "personas_dir": "knowledge/personas/vtrade",
}

VPROMEDIA_ENTRY: dict = {
    "display_name": "vProMedia",
    "description": "Broadcast production platform.",
    "order": 1,
    "environments": {"qa": "https://two-test.vcreative.net"},
    "default_environment": "qa",
    "jira_board_ids": [27, 36],
    "roles": [
        "account_executive",
        "sales_manager",
        "sales_assistant",
        "production_manager",
        "producer",
        "gm_gsm",
        "dubber",
        "digital_director",
        "demo_prod_director",
    ],
    "playwright_tests_dir": "playwright/tests/vpromedia",
    "personas_dir": "knowledge/personas/vpromedia",
}


def _two_product_data() -> dict:
    """Minimal valid registry data dict with vpromedia + vtrade."""
    return {
        "schema_version": 1,
        "products": {
            "vpromedia": VPROMEDIA_ENTRY,
            "vtrade": VTRADE_ENTRY,
        },
    }


# ---------------------------------------------------------------------------
# 1. Happy path — load from dict
# ---------------------------------------------------------------------------


class TestLoadValidRegistryFromDict:
    """load_product_registry(data=...) happy path."""

    def test_load_valid_registry_from_dict(self):
        """Registry loads successfully from a valid in-memory dict."""
        registry = load_product_registry(data=_two_product_data())
        assert isinstance(registry, ProductRegistry)
        assert "vpromedia" in registry.products
        assert "vtrade" in registry.products

    def test_slug_is_injected_from_map_key(self):
        """ProductContext.slug is set from the YAML map key, not from an
        inline 'slug:' field in the entry body."""
        registry = load_product_registry(data=_two_product_data())
        vtrade = registry.products["vtrade"]
        assert vtrade.slug == "vtrade"
        vpromedia = registry.products["vpromedia"]
        assert vpromedia.slug == "vpromedia"


# ---------------------------------------------------------------------------
# 2. Validation — required fields
# ---------------------------------------------------------------------------


class TestMissingRequiredField:
    """Missing required fields must raise ValidationError."""

    def test_missing_required_field_raises(self):
        """A product entry missing 'display_name' (required) raises ValidationError."""
        data = {
            "products": {
                "vtrade": {
                    # Missing display_name
                    "environments": {"qa": "https://vtrade-qa.vcreative.net"},
                    "jira_board_ids": [36],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        with pytest.raises(ValidationError):
            load_product_registry(data=data)


# ---------------------------------------------------------------------------
# 3. Slug validation
# ---------------------------------------------------------------------------


class TestSlugValidation:
    """Slug format enforcement — lowercase alphanumeric + underscore only."""

    def test_slug_validation_rejects_uppercase(self):
        """A slug with uppercase letters (e.g. 'VTrade') must be rejected."""
        data = {
            "products": {
                "VTrade": {
                    "display_name": "vTrade",
                    "environments": {"qa": "https://vtrade-qa.vcreative.net"},
                    "jira_board_ids": [],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        with pytest.raises((ValidationError, ValueError)):
            load_product_registry(data=data)

    def test_duplicate_slug_impossible_via_yaml(self):
        """Document that YAML dict uniqueness prevents duplicate slugs at the
        parser level. When loading via dict, the loader must accept a
        correctly-keyed dict and reject an inconsistent slug body.

        This test verifies the loader handles the normal (valid) case — the
        duplicate-prevention is a YAML parser guarantee, not a Pydantic one.
        """
        registry = load_product_registry(data=_two_product_data())
        # Only 2 products — no duplicates possible in a dict
        assert len(registry.products) == 2


# ---------------------------------------------------------------------------
# 4. Empty / stub products
# ---------------------------------------------------------------------------


class TestEmptyProducts:
    """Edge cases: empty products dict, stub products."""

    def test_empty_products_dict_is_valid(self):
        """A registry with zero products is valid (AC-ERROR-2 foundation)."""
        registry = load_product_registry(data={"products": {}})
        assert isinstance(registry, ProductRegistry)
        assert len(registry.products) == 0

    def test_product_with_empty_roles_and_boards_is_valid(self):
        """A stub product with empty jira_board_ids and roles is valid (AC-ERROR-2)."""
        data = {
            "products": {
                "vep": {
                    "display_name": "vEP",
                    "environments": {"qa": "https://vep-qa.vcreative.net"},
                    "jira_board_ids": [],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vep",
                    "personas_dir": "knowledge/personas/vep",
                }
            }
        }
        registry = load_product_registry(data=data)
        vep = registry.get("vep")
        assert vep.jira_board_ids == []
        assert vep.roles == []


# ---------------------------------------------------------------------------
# 5. Default environment auto-promotion
# ---------------------------------------------------------------------------


class TestDefaultEnvironmentAutopromotion:
    """When environments has exactly one key and default_environment is omitted,
    it must be auto-set to that single key."""

    def test_single_env_autopromotion_of_default(self):
        """Single environment auto-promoted to default_environment."""
        data = {
            "products": {
                "vtrade": {
                    "display_name": "vTrade",
                    "environments": {"qa": "https://vtrade-qa.vcreative.net"},
                    # default_environment intentionally omitted
                    "jira_board_ids": [],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        registry = load_product_registry(data=data)
        vtrade = registry.products["vtrade"]
        assert vtrade.default_environment == "qa"

    def test_multiple_envs_without_default_raises(self):
        """When environments has multiple keys and default_environment is omitted,
        validation must raise."""
        data = {
            "products": {
                "vtrade": {
                    "display_name": "vTrade",
                    "environments": {
                        "qa": "https://vtrade-qa.vcreative.net",
                        "staging": "https://vtrade-staging.vcreative.net",
                    },
                    # default_environment intentionally omitted — invalid
                    "jira_board_ids": [],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        with pytest.raises(ValidationError):
            load_product_registry(data=data)


# ---------------------------------------------------------------------------
# 6. ProductContext.resolve_target_url()
# ---------------------------------------------------------------------------


class TestResolveTargetUrl:
    """ProductContext.resolve_target_url() behavior."""

    def _vtrade_context(self) -> ProductContext:
        registry = load_product_registry(data=_two_product_data())
        return registry.get("vtrade")

    def test_resolve_target_url_with_default(self):
        """resolve_target_url() with no argument returns the default env URL."""
        vtrade = self._vtrade_context()
        assert vtrade.resolve_target_url() == "https://vtrade-qa.vcreative.net"

    def test_resolve_target_url_with_explicit_env(self):
        """resolve_target_url('staging') works when staging env is configured."""
        data = {
            "products": {
                "vtrade": {
                    "display_name": "vTrade",
                    "environments": {
                        "qa": "https://vtrade-qa.vcreative.net",
                        "staging": "https://vtrade-staging.vcreative.net",
                    },
                    "default_environment": "qa",
                    "jira_board_ids": [],
                    "roles": [],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        registry = load_product_registry(data=data)
        vtrade = registry.get("vtrade")
        assert vtrade.resolve_target_url("staging") == "https://vtrade-staging.vcreative.net"

    def test_resolve_target_url_unknown_env_raises(self):
        """resolve_target_url('nonexistent') raises KeyError."""
        vtrade = self._vtrade_context()
        with pytest.raises(KeyError):
            vtrade.resolve_target_url("nonexistent")


# ---------------------------------------------------------------------------
# 7. ProductContext.has_role()
# ---------------------------------------------------------------------------


class TestHasRole:
    """ProductContext.has_role(role_key) membership check."""

    def test_has_role_returns_true_for_member(self):
        """has_role() returns True for a role that belongs to the product."""
        registry = load_product_registry(data=_two_product_data())
        vtrade = registry.get("vtrade")
        assert vtrade.has_role("vtrade_exec") is True

    def test_has_role_returns_false_for_non_member(self):
        """has_role() returns False for a role that belongs to a different product."""
        registry = load_product_registry(data=_two_product_data())
        vtrade = registry.get("vtrade")
        # account_executive belongs to vpromedia, not vtrade
        assert vtrade.has_role("account_executive") is False


# ---------------------------------------------------------------------------
# 8. ProductRegistry collection helpers
# ---------------------------------------------------------------------------


class TestRegistryHelpers:
    """ProductRegistry.list(), slugs(), get(), contains_role()."""

    def test_registry_list_sorted_by_order(self):
        """registry.list() returns products sorted by order field (ascending)."""
        registry = load_product_registry(data=_two_product_data())
        listed = registry.list()
        orders = [p.order for p in listed]
        # vpromedia order=1 comes before vtrade order=2
        assert orders == sorted(orders), "list() must be sorted by order"
        # vpromedia appears first
        assert listed[0].slug == "vpromedia"
        assert listed[1].slug == "vtrade"

    def test_contains_role_returns_slug(self):
        """registry.contains_role(role_key) returns the slug that owns the role."""
        registry = load_product_registry(data=_two_product_data())
        result = registry.contains_role("vtrade_exec")
        assert result == "vtrade"

    def test_contains_role_returns_none_for_unknown(self):
        """registry.contains_role() returns None for a role not in any product."""
        registry = load_product_registry(data=_two_product_data())
        result = registry.contains_role("totally_unknown_role")
        assert result is None

    def test_registry_get_raises_key_error_for_unknown_slug(self):
        """registry.get() raises KeyError when the slug is not registered."""
        registry = load_product_registry(data=_two_product_data())
        with pytest.raises(KeyError):
            registry.get("vunknown")


# ---------------------------------------------------------------------------
# 9. Real products.yaml integration test
# ---------------------------------------------------------------------------


class TestLoadRealProductsYaml:
    """Read the canonical backend/config/products.yaml and validate its contents."""

    def _registry_path(self) -> Path:
        """Resolve the path to the real products.yaml relative to repo root."""
        return Path(__file__).parent.parent.parent / "backend" / "config" / "products.yaml"

    def test_load_real_products_yaml(self):
        """products.yaml loads successfully and contains exactly 6 products."""
        yaml_path = self._registry_path()
        registry = load_product_registry(path=yaml_path)
        assert len(registry.products) == 6, (
            f"Expected 6 products, got {len(registry.products)}: "
            f"{sorted(registry.products.keys())}"
        )

    def test_real_yaml_vpromedia_has_board_ids_27_and_36(self):
        """vpromedia entry in products.yaml has jira_board_ids [27, 36]."""
        yaml_path = self._registry_path()
        registry = load_product_registry(path=yaml_path)
        vpromedia = registry.get("vpromedia")
        assert sorted(vpromedia.jira_board_ids) == [27, 36]

    def test_real_yaml_all_expected_slugs_present(self):
        """All six product slugs from the design decision are present."""
        expected_slugs = {"vpromedia", "vtrade", "vpromotions", "vep", "vppo", "psn"}
        yaml_path = self._registry_path()
        registry = load_product_registry(path=yaml_path)
        assert set(registry.products.keys()) == expected_slugs

    def test_real_yaml_vpromedia_resolves_qa_url(self):
        """vpromedia.resolve_target_url() returns the two-test URL from the file."""
        yaml_path = self._registry_path()
        registry = load_product_registry(path=yaml_path)
        vpromedia = registry.get("vpromedia")
        url = vpromedia.resolve_target_url()
        assert url == "https://two-test.vcreative.net"


# ---------------------------------------------------------------------------
# 10. Zero-code-change new-product NFR (parameterized)
# ---------------------------------------------------------------------------


class TestZeroCodeChangeNewProductNfr:
    """Adding a synthetic product to a fixture registry must work without
    touching any Python module — only YAML (or dict) changes. Verifies the
    NFR from the creative decision: 'adding a 7th product must require ONLY
    (a) a new entry in products.yaml and (b) creating two filesystem directories.'
    """

    @pytest.mark.parametrize(
        "slug,display_name,qa_url,board_ids",
        [
            ("vsynthetic", "vSynthetic", "https://vsynthetic-qa.vcreative.net", [99]),
            ("vacme", "vAcme", "https://vacme-qa.vcreative.net", []),
        ],
    )
    def test_zero_code_change_new_product_nfr(self, slug, display_name, qa_url, board_ids):
        """Injecting a new product slug into the data dict produces a valid
        ProductContext accessible via registry.get(slug) — no Python code touched."""
        data = dict(_two_product_data())
        data["products"] = dict(data["products"])  # shallow copy
        data["products"][slug] = {
            "display_name": display_name,
            "environments": {"qa": qa_url},
            "default_environment": "qa",
            "jira_board_ids": board_ids,
            "roles": [],
            "playwright_tests_dir": f"playwright/tests/{slug}",
            "personas_dir": f"knowledge/personas/{slug}",
        }
        registry = load_product_registry(data=data)
        product = registry.get(slug)
        assert product.slug == slug
        assert product.display_name == display_name
        assert product.resolve_target_url() == qa_url
        assert product.jira_board_ids == board_ids


# ---------------------------------------------------------------------------
# 11. ProductPublic — safe API projection
# ---------------------------------------------------------------------------


class TestProductPublic:
    """ProductPublic.from_context() strips filesystem paths and produces the
    API-safe projection."""

    def test_product_public_excludes_filesystem_paths(self):
        """ProductPublic must not expose playwright_tests_dir or personas_dir."""
        registry = load_product_registry(data=_two_product_data())
        vtrade = registry.get("vtrade")
        public = ProductPublic.from_context(vtrade)
        assert not hasattr(public, "playwright_tests_dir"), (
            "playwright_tests_dir must not be on ProductPublic"
        )
        assert not hasattr(public, "personas_dir"), (
            "personas_dir must not be on ProductPublic"
        )

    def test_product_public_includes_role_keys_not_credentials(self):
        """ProductPublic includes role keys as strings, not RoleContext objects."""
        registry = load_product_registry(data=_two_product_data())
        vtrade = registry.get("vtrade")
        public = ProductPublic.from_context(vtrade)
        assert isinstance(public.roles, list)
        assert all(isinstance(r, str) for r in public.roles)
        assert "vtrade_exec" in public.roles
