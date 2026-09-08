"""
tests/backend/test_environment_scoping.py
==========================================
TDD tests for TASK-124, Phase 4: Per-Product Environment Scoping.

Covers:
- ProductContext.resolve_target_url() — default and explicit env variants
- ExecuteRequest auto-resolution of target_url from the product registry
- Backwards compatibility: vpromedia default URL is unchanged
- products.yaml phase 4 update: all 6 products have non-empty environments

ALL TESTS SHOULD FAIL until Phase 4 implementation is complete (TDD RED phase).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.config.product_registry import (
    ProductContext,
    ProductRegistry,
    load_product_registry,
)
from backend.api.schemas import ExecuteRequest

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

VPROMEDIA_ENTRY: dict = {
    "display_name": "vProMedia",
    "description": "Broadcast platform.",
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

VTRADE_ENTRY: dict = {
    "display_name": "vTrade",
    "description": "Trade platform.",
    "order": 2,
    "environments": {"qa": "https://vtrade-qa.vcreative.net"},
    "default_environment": "qa",
    "jira_board_ids": [],
    "roles": ["vtrade_exec", "vtrade_business_manager", "vtrade_sales_manager"],
    "playwright_tests_dir": "playwright/tests/vtrade",
    "personas_dir": "knowledge/personas/vtrade",
}


def _two_product_registry() -> ProductRegistry:
    return load_product_registry(
        data={
            "schema_version": 1,
            "products": {
                "vpromedia": VPROMEDIA_ENTRY,
                "vtrade": VTRADE_ENTRY,
            },
        }
    )


# ---------------------------------------------------------------------------
# 1. ProductContext.resolve_target_url() — unit tests
# ---------------------------------------------------------------------------


class TestResolveTargetUrl:
    """ProductContext.resolve_target_url() with default and named environments."""

    def test_resolve_target_url_returns_default_env_url(self):
        """resolve_target_url() with no argument returns the URL for
        the product's default_environment."""
        registry = _two_product_registry()
        vtrade = registry.get("vtrade")
        assert vtrade.resolve_target_url() == "https://vtrade-qa.vcreative.net"

    def test_resolve_target_url_returns_explicit_env_url(self):
        """resolve_target_url('staging') returns the staging URL when it is
        configured as a named environment for the product."""
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
                    "roles": ["vtrade_exec"],
                    "playwright_tests_dir": "playwright/tests/vtrade",
                    "personas_dir": "knowledge/personas/vtrade",
                }
            }
        }
        registry = load_product_registry(data=data)
        vtrade = registry.get("vtrade")
        assert vtrade.resolve_target_url("staging") == "https://vtrade-staging.vcreative.net"

    def test_resolve_target_url_raises_for_unknown_env(self):
        """resolve_target_url('nonexistent') raises KeyError for an environment
        name that is not registered for the product."""
        registry = _two_product_registry()
        vtrade = registry.get("vtrade")
        with pytest.raises(KeyError):
            vtrade.resolve_target_url("nonexistent")


# ---------------------------------------------------------------------------
# 2. ExecuteRequest auto-resolution of target_url
# ---------------------------------------------------------------------------


class TestExecuteRequestTargetUrlAutoResolution:
    """ExecuteRequest.target_url auto-resolves from the product registry when
    no explicit target_url is provided."""

    def test_execute_request_auto_resolves_target_url_for_vpromedia(self):
        """ExecuteRequest with no target_url and product=vpromedia auto-resolves
        to the vpromedia QA URL from the registry (https://two-test.vcreative.net)."""
        req = ExecuteRequest(
            jira_ticket_id="VC2-1234",
            role="account_executive",
            product="vpromedia",
            # target_url intentionally omitted — should resolve from registry
        )
        assert req.target_url == "https://two-test.vcreative.net"

    def test_execute_request_auto_resolves_target_url_for_vtrade(self):
        """ExecuteRequest with no target_url and product=vtrade (role=vtrade_exec)
        auto-resolves to the vtrade QA URL from the registry."""
        req = ExecuteRequest(
            jira_ticket_id="VT-42",
            role="vtrade_exec",
            product="vtrade",
            # target_url intentionally omitted — should resolve from registry
        )
        assert req.target_url == "https://vtrade-qa.vcreative.net"

    def test_execute_request_explicit_target_url_overrides_registry(self):
        """An explicitly-supplied target_url must take precedence over the
        registry default — the caller should be able to override for ad-hoc runs."""
        custom_url = "https://custom-vpromedia.vcreative.net"
        req = ExecuteRequest(
            jira_ticket_id="VC2-9999",
            role="account_executive",
            product="vpromedia",
            target_url=custom_url,
        )
        assert req.target_url == custom_url

    def test_execute_request_default_product_vpromedia_backwards_compat(self):
        """ExecuteRequest with no product field (defaults to 'vpromedia') and no
        target_url resolves to the vpromedia default URL — existing callers that
        don't send a product field still get the historical URL."""
        req = ExecuteRequest(
            jira_ticket_id="VC2-0001",
            role="account_executive",
            # product omitted — must default to 'vpromedia'
            # target_url omitted — must resolve from registry
        )
        assert req.product == "vpromedia"
        assert req.target_url == "https://two-test.vcreative.net"


# ---------------------------------------------------------------------------
# 3. products.yaml Phase 4 update — all 6 products have non-empty environments
# ---------------------------------------------------------------------------


class TestProductsYamlPhase4:
    """After the Phase 4 products.yaml update, all 6 products must have
    non-empty environments maps with at least one named URL."""

    def _registry_path(self) -> Path:
        return Path(__file__).parent.parent.parent / "backend" / "config" / "products.yaml"

    def test_product_context_environments_are_non_empty_after_phase4(self):
        """All 6 products in products.yaml must have at least one environment
        entry (i.e. environments != {}) after the Phase 4 YAML update."""
        registry = load_product_registry(path=self._registry_path())
        for slug, product in registry.products.items():
            assert len(product.environments) > 0, (
                f"Product '{slug}' has an empty environments map after Phase 4. "
                "Phase 4 requires all stub products (vep, vppo, psn) to have "
                "placeholder QA URLs in products.yaml."
            )

    def test_vpromedia_environment_url_unchanged_after_phase4(self):
        """The vpromedia QA URL must still be https://two-test.vcreative.net
        after the Phase 4 YAML update — this is a backwards-compatibility requirement."""
        registry = load_product_registry(path=self._registry_path())
        vpromedia = registry.get("vpromedia")
        assert vpromedia.resolve_target_url() == "https://two-test.vcreative.net", (
            "Backwards compatibility broken: vpromedia default URL changed in Phase 4."
        )

    def test_vtrade_environment_url_set_after_phase4(self):
        """The vtrade product must have a QA URL configured after Phase 4."""
        registry = load_product_registry(path=self._registry_path())
        vtrade = registry.get("vtrade")
        assert vtrade.resolve_target_url().startswith("https://"), (
            "vtrade has no valid HTTPS URL after Phase 4."
        )

    def test_stub_products_have_placeholder_qa_urls_after_phase4(self):
        """The stub products (vep, vppo, psn) must each have at least one
        environment URL after Phase 4, so the frontend can auto-populate
        targetUrl when they are selected."""
        stub_slugs = ["vep", "vppo", "psn"]
        registry = load_product_registry(path=self._registry_path())
        for slug in stub_slugs:
            product = registry.get(slug)
            assert len(product.environments) > 0, (
                f"Stub product '{slug}' still has no environments after Phase 4."
            )
            # Each URL must be a valid HTTPS URL
            for env_name, url in product.environments.items():
                assert url.startswith("https://"), (
                    f"Product '{slug}' env '{env_name}' URL '{url}' is not HTTPS."
                )
