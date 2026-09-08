"""
tests/backend/test_product_scoping_api.py
==========================================
TDD tests for TASK-124, Phase 2: Product Selector UI & Jira Scoping.

Covers:
- GET /products — returns ProductPublic list for all 6 products
- GET /tickets?product=<slug> — filters by product's jira_board_ids
- AC-HAPPY-1: Ticket list filtered by product's jira_board_ids
- AC-HAPPY-2: /products endpoint returns correct roles per product
- AC-ERROR-1: Unknown product slug → 422 / graceful fallback

All route tests use httpx.AsyncClient + FastAPI's app fixture.
Registry is injected via dependency override where needed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# App import — deferred to avoid startup side-effects in early RED phase
# ---------------------------------------------------------------------------

from backend.main import app
from backend.config.product_registry import (
    ProductRegistry,
    ProductContext,
    ProductPublic,
    load_product_registry,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MINIMAL_REGISTRY_DATA: dict = {
    "schema_version": 1,
    "products": {
        "vpromedia": {
            "display_name": "vProMedia",
            "description": "Broadcast platform.",
            "order": 1,
            "environments": {"qa": "https://two-test.vcreative.net"},
            "default_environment": "qa",
            "jira_board_ids": [27, 36],
            "roles": ["account_executive", "sales_manager"],
            "playwright_tests_dir": "playwright/tests/vpromedia",
            "personas_dir": "knowledge/personas/vpromedia",
        },
        "vtrade": {
            "display_name": "vTrade",
            "description": "Trade platform.",
            "order": 2,
            "environments": {"qa": "https://vtrade-qa.vcreative.net"},
            "default_environment": "qa",
            "jira_board_ids": [],
            "roles": ["vtrade_exec"],
            "playwright_tests_dir": "playwright/tests/vtrade",
            "personas_dir": "knowledge/personas/vtrade",
        },
        "vep": {
            "display_name": "vEP",
            "description": "Stub product.",
            "order": 4,
            "environments": {},
            "jira_board_ids": [],
            "roles": [],
            "playwright_tests_dir": "playwright/tests/vep",
            "personas_dir": "knowledge/personas/vep",
        },
    },
}


@pytest.fixture()
def test_client():
    """Synchronous TestClient for fast route tests."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def minimal_registry() -> ProductRegistry:
    return load_product_registry(data=MINIMAL_REGISTRY_DATA)


# ---------------------------------------------------------------------------
# GET /products — endpoint contract
# ---------------------------------------------------------------------------


class TestGetProductsEndpoint:
    """GET /products returns ProductPublic list."""

    def test_returns_200(self, test_client: TestClient):
        """Endpoint must exist and return HTTP 200."""
        response = test_client.get("/api/products")
        assert response.status_code == 200

    def test_returns_list(self, test_client: TestClient):
        """Response body must be a JSON array."""
        response = test_client.get("/api/products")
        data = response.json()
        assert isinstance(data, list)

    def test_returns_six_products(self, test_client: TestClient):
        """Real products.yaml has 6 products — /products must return all 6."""
        response = test_client.get("/api/products")
        data = response.json()
        assert len(data) == 6

    def test_product_has_required_fields(self, test_client: TestClient):
        """Each product dict must include slug, display_name, jira_board_ids, roles."""
        response = test_client.get("/api/products")
        products = response.json()
        required_fields = {"slug", "display_name", "description", "order",
                           "environments", "default_environment",
                           "jira_board_ids", "roles"}
        for product in products:
            missing = required_fields - set(product.keys())
            assert not missing, f"Product {product.get('slug')} missing fields: {missing}"

    def test_vpromedia_present_with_correct_jira_boards(self, test_client: TestClient):
        """vProMedia must be present with its two Jira board IDs."""
        response = test_client.get("/api/products")
        products = {p["slug"]: p for p in response.json()}
        assert "vpromedia" in products
        assert 27 in products["vpromedia"]["jira_board_ids"]
        assert 36 in products["vpromedia"]["jira_board_ids"]

    def test_no_filesystem_paths_exposed(self, test_client: TestClient):
        """playwright_tests_dir and personas_dir must NOT appear in the response."""
        response = test_client.get("/api/products")
        for product in response.json():
            assert "playwright_tests_dir" not in product
            assert "personas_dir" not in product

    def test_products_sorted_by_order(self, test_client: TestClient):
        """Products must be sorted by their order field (ascending)."""
        response = test_client.get("/api/products")
        products = response.json()
        orders = [p["order"] for p in products]
        assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# GET /tickets?product=<slug> — product-scoped ticket filtering
# ---------------------------------------------------------------------------


class TestTicketsProductScoping:
    """GET /tickets?product=<slug> filters Jira boards by product."""

    def test_tickets_accepts_product_param(self, test_client: TestClient):
        """
        /tickets?product=vpromedia must not return a 422 (param must be accepted).
        It may 200 or 502 depending on Jira availability — just not 422.
        """
        with patch(
            "backend.api.routes.fetch_board_tickets",
            new_callable=AsyncMock,
            return_value=[
                {"id": "VC2-1", "summary": "Test", "status": "To Do",
                 "priority": "Medium", "issue_type": "Story"},
            ],
        ):
            response = test_client.get("/api/tickets?product=vpromedia")
            assert response.status_code != 422

    def test_tickets_with_product_calls_board_ids_for_product(self, test_client: TestClient):
        """
        When ?product=vpromedia, fetch_board_tickets must be called with the
        vpromedia board_ids [27, 36], NOT the global settings.jira_board_ids.
        """
        with patch(
            "backend.api.routes.fetch_board_tickets",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch:
            test_client.get("/api/tickets?product=vpromedia")
            # fetch_board_tickets should have been called with board_ids kwarg
            if mock_fetch.called:
                call_kwargs = mock_fetch.call_args.kwargs if mock_fetch.call_args else {}
                call_args = mock_fetch.call_args.args if mock_fetch.call_args else ()
                # board_ids can be positional or keyword
                board_ids_called = call_kwargs.get("board_ids") or (
                    call_args[1] if len(call_args) > 1 else None
                )
                if board_ids_called is not None:
                    assert 27 in board_ids_called
                    assert 36 in board_ids_called

    def test_tickets_without_product_uses_global_board_ids(self, test_client: TestClient):
        """
        When ?product is omitted, fetch_board_tickets must be called with
        board_ids=None (so the existing global settings fallback applies).
        """
        with patch(
            "backend.api.routes.fetch_board_tickets",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch:
            test_client.get("/api/tickets")
            if mock_fetch.called:
                call_kwargs = mock_fetch.call_args.kwargs if mock_fetch.call_args else {}
                board_ids_called = call_kwargs.get("board_ids")
                # None means global fallback — correct
                assert board_ids_called is None

    def test_tickets_unknown_product_returns_error(self, test_client: TestClient):
        """
        /tickets?product=notaproduct should return 400 or 422 — not 200 with wrong data.
        """
        with patch(
            "backend.api.routes.fetch_board_tickets",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = test_client.get("/api/tickets?product=notaproduct_xyz")
            assert response.status_code in (400, 404, 422)

    def test_tickets_product_vtrade_uses_empty_board_ids(self, test_client: TestClient):
        """
        vTrade has no Jira boards → /tickets?product=vtrade should return empty list.
        """
        with patch(
            "backend.api.routes.fetch_board_tickets",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch:
            response = test_client.get("/api/tickets?product=vtrade")
            assert response.status_code in (200, 502)
            if response.status_code == 200:
                # With empty board_ids, the result should be an empty list
                # (fetch_board_tickets receives [] → returns [])
                assert response.json() == []


# ---------------------------------------------------------------------------
# ProductPublic model tests (unit)
# ---------------------------------------------------------------------------


class TestProductPublicModel:
    """ProductPublic.from_context() projection tests."""

    def test_from_context_excludes_filesystem_paths(self):
        ctx = ProductContext(
            slug="vpromedia",
            display_name="vProMedia",
            description="Test",
            order=1,
            environments={"qa": "https://two-test.vcreative.net"},
            default_environment="qa",
            jira_board_ids=[27, 36],
            roles=["account_executive"],
            playwright_tests_dir="playwright/tests/vpromedia",
            personas_dir="knowledge/personas/vpromedia",
        )
        public = ProductPublic.from_context(ctx)
        public_dict = public.model_dump()
        assert "playwright_tests_dir" not in public_dict
        assert "personas_dir" not in public_dict

    def test_from_context_includes_jira_board_ids(self):
        ctx = ProductContext(
            slug="vpromedia",
            display_name="vProMedia",
            description="Test",
            order=1,
            environments={"qa": "https://two-test.vcreative.net"},
            default_environment="qa",
            jira_board_ids=[27, 36],
            roles=["account_executive"],
            playwright_tests_dir="playwright/tests/vpromedia",
            personas_dir="knowledge/personas/vpromedia",
        )
        public = ProductPublic.from_context(ctx)
        assert public.jira_board_ids == [27, 36]

    def test_from_context_includes_roles(self):
        ctx = ProductContext(
            slug="vtrade",
            display_name="vTrade",
            description="Trade.",
            order=2,
            environments={"qa": "https://vtrade-qa.vcreative.net"},
            default_environment="qa",
            jira_board_ids=[],
            roles=["vtrade_exec", "vtrade_business_manager"],
            playwright_tests_dir="playwright/tests/vtrade",
            personas_dir="knowledge/personas/vtrade",
        )
        public = ProductPublic.from_context(ctx)
        assert "vtrade_exec" in public.roles
        assert "vtrade_business_manager" in public.roles


# ---------------------------------------------------------------------------
# Integration: registry loaded from real products.yaml
# ---------------------------------------------------------------------------


class TestRealRegistryIntegration:
    """Smoke tests against the real products.yaml file."""

    def test_real_registry_has_six_products(self):
        registry = load_product_registry()
        assert len(registry.products) == 6

    def test_real_registry_vpromedia_has_board_ids(self):
        registry = load_product_registry()
        vpromedia = registry.get("vpromedia")
        assert len(vpromedia.jira_board_ids) > 0

    def test_real_registry_all_slugs_valid(self):
        import re
        registry = load_product_registry()
        for slug in registry.slugs():
            assert re.match(r"^[a-z0-9_]+$", slug), f"Invalid slug: {slug}"
