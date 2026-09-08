"""
tests/backend/test_role_product_enforcement.py
================================================
TDD tests for TASK-124, Phase 1: Role↔Product Enforcement.

Validates the cross-validation contract between:
  - ROLE_REGISTRY  (backend/engine/roles.py)  — the role catalog
  - products.yaml  (backend/config/products.yaml)  — the product registry

CRITICAL: These tests use the REAL ROLE_REGISTRY and the real products.yaml.
DO NOT mock ROLE_REGISTRY in this file — the entire purpose of these tests is
to detect drift between the two sources of truth.

ALL TESTS SHOULD FAIL until Phase 1 implementation is complete (TDD RED phase).
The tests that use ExecuteRequest will fail because the `product` field does
not yet exist on that model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Imports (some will fail in RED phase — that is expected)
# ---------------------------------------------------------------------------
from backend.engine.roles import ROLE_REGISTRY
from backend.config.product_registry import load_product_registry, ProductRegistry

# ExecuteRequest will fail import or instantiation until Phase 1 adds
# the `product` field and model_validator — that failure IS the RED signal.
from backend.api.schemas import ExecuteRequest, VALID_ROLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGISTRY_PATH = Path(__file__).parent.parent.parent / "backend" / "config" / "products.yaml"


def _load_real_registry() -> ProductRegistry:
    """Load the canonical products.yaml. Cached per test session via fixture."""
    return load_product_registry(path=_REGISTRY_PATH)


@pytest.fixture(scope="module")
def real_registry() -> ProductRegistry:
    """Module-scoped fixture: loads products.yaml once for the entire module."""
    return _load_real_registry()


@pytest.fixture(scope="module")
def all_yaml_roles(real_registry: ProductRegistry) -> set[str]:
    """All role keys declared across all products in products.yaml."""
    roles: set[str] = set()
    for product in real_registry.products.values():
        roles.update(product.roles)
    return roles


# ---------------------------------------------------------------------------
# 1. Cross-validation: every yaml role exists in ROLE_REGISTRY
# ---------------------------------------------------------------------------


class TestEveryYamlRoleExistsInRoleRegistry:
    """Every role key in products.yaml must have a matching entry in ROLE_REGISTRY."""

    def test_every_yaml_role_exists_in_role_registry(
        self, real_registry: ProductRegistry, all_yaml_roles: set[str]
    ):
        """For every product in products.yaml, every role key must be in ROLE_REGISTRY.

        Failure here means products.yaml declares a role that does not have a
        corresponding credential/constraint entry in roles.py — a startup crash
        condition in the implemented system.
        """
        orphaned: list[str] = [r for r in all_yaml_roles if r not in ROLE_REGISTRY]
        assert orphaned == [], (
            f"These role keys are in products.yaml but MISSING from ROLE_REGISTRY:\n"
            f"  {orphaned}\n"
            f"Add them to backend/engine/roles.py or remove them from products.yaml."
        )


# ---------------------------------------------------------------------------
# 2. Cross-validation: every ROLE_REGISTRY role belongs to exactly one product
# ---------------------------------------------------------------------------


class TestEveryRegistryRoleBelongsToExactlyOneProduct:
    """Mutual exclusivity and completeness of role→product assignment."""

    def test_every_registry_role_belongs_to_exactly_one_product(
        self, real_registry: ProductRegistry, all_yaml_roles: set[str]
    ):
        """Every user-facing role in VALID_ROLES must be claimed by exactly one product.

        VALID_ROLES (schemas.py) is the canonical list of API-selectable roles —
        the 13 roles surfaced to the frontend. Backend-internal roles such as
        traffic_manager, writer, and voice_talent live in ROLE_REGISTRY but are
        not user-selectable and do not require product assignment.

        Failure here means a VALID_ROLES key is unassigned in products.yaml —
        the frontend would never surface it in any product's role dropdown.
        """
        valid_role_keys = set(VALID_ROLES)
        unassigned = valid_role_keys - all_yaml_roles
        assert not unassigned, (
            f"These VALID_ROLES keys are NOT assigned to any product in products.yaml:\n"
            f"  {sorted(unassigned)}\n"
            f"Add them to the correct product's 'roles:' list in backend/config/products.yaml."
        )

    def test_no_role_belongs_to_multiple_products(self, real_registry: ProductRegistry):
        """No role key must appear in more than one product's roles list.

        Failure here means a role is double-assigned — a user could submit an
        /execute request with either product and both would claim the role,
        leading to non-deterministic behavior.
        """
        role_to_products: dict[str, list[str]] = {}
        for slug, product in real_registry.products.items():
            for role_key in product.roles:
                role_to_products.setdefault(role_key, []).append(slug)

        double_assigned = {
            role: products
            for role, products in role_to_products.items()
            if len(products) > 1
        }
        assert double_assigned == {}, (
            f"These roles appear in MORE THAN ONE product:\n"
            + "\n".join(
                f"  '{role}' → {products}"
                for role, products in sorted(double_assigned.items())
            )
        )

    def test_all_13_roles_are_assigned(
        self, real_registry: ProductRegistry, all_yaml_roles: set[str]
    ):
        """All 13 existing role keys from ROLE_REGISTRY must be assigned in products.yaml.

        The exact count is 13 per the task spec (TASK-124: 'The existing 13 role
        keys... are partitioned across products'). This is the specific invariant
        the task establishes — any addition or removal is a breaking change.
        """
        assert len(all_yaml_roles) == 13, (
            f"Expected exactly 13 roles assigned across products, "
            f"got {len(all_yaml_roles)}: {sorted(all_yaml_roles)}"
        )


# ---------------------------------------------------------------------------
# 3. Per-product role count assertions
# ---------------------------------------------------------------------------


class TestPerProductRoleCounts:
    """Specific role assignments per product per the TASK-124 spec."""

    def test_vpromedia_has_9_roles(self, real_registry: ProductRegistry):
        """vProMedia has 9 roles: 8 core vProMedia roles + demo_prod_director."""
        vpromedia = real_registry.get("vpromedia")
        expected_roles = {
            "account_executive",
            "sales_manager",
            "sales_assistant",
            "production_manager",
            "producer",
            "gm_gsm",
            "dubber",
            "digital_director",
            "demo_prod_director",
        }
        assert set(vpromedia.roles) == expected_roles, (
            f"vpromedia.roles mismatch.\n"
            f"  Expected: {sorted(expected_roles)}\n"
            f"  Got:      {sorted(vpromedia.roles)}"
        )

    def test_vtrade_has_3_roles(self, real_registry: ProductRegistry):
        """vTrade has exactly 3 roles: vtrade_exec, vtrade_business_manager,
        vtrade_sales_manager (bootstrapped by TASK-012)."""
        vtrade = real_registry.get("vtrade")
        expected_roles = {
            "vtrade_exec",
            "vtrade_business_manager",
            "vtrade_sales_manager",
        }
        assert set(vtrade.roles) == expected_roles, (
            f"vtrade.roles mismatch.\n"
            f"  Expected: {sorted(expected_roles)}\n"
            f"  Got:      {sorted(vtrade.roles)}"
        )

    def test_vpromotions_has_1_role(self, real_registry: ProductRegistry):
        """vPromotions has exactly 1 role: vpromotions_user."""
        vpromotions = real_registry.get("vpromotions")
        assert set(vpromotions.roles) == {"vpromotions_user"}, (
            f"vpromotions.roles mismatch.\n"
            f"  Expected: ['vpromotions_user']\n"
            f"  Got:      {sorted(vpromotions.roles)}"
        )

    def test_vep_vppo_psn_have_no_roles(self, real_registry: ProductRegistry):
        """vEP, vPPO, and PSN are stub products with empty role lists (Phase 1)."""
        for slug in ("vep", "vppo", "psn"):
            product = real_registry.get(slug)
            assert product.roles == [], (
                f"{slug} should have no roles in Phase 1, got: {product.roles}"
            )


# ---------------------------------------------------------------------------
# 4. ExecuteRequest schema validation (Pydantic cross-field validator)
# ---------------------------------------------------------------------------


class TestExecuteRequestRoleProductValidation:
    """ExecuteRequest must enforce role ∈ product.roles at schema validation time.

    These tests verify the behavior of the `product` field (ADDED by Phase 1)
    and the @model_validator that cross-checks role vs. product.

    In the RED phase, all of these will fail because:
    - ExecuteRequest has no `product` field yet
    - There is no model_validator cross-checking role vs. product
    """

    _COMMON_KWARGS = {
        "jira_ticket_id": "VC2-1234",
        "target_url": "https://two-test.vcreative.net",
        "mode": "headless",
    }

    def test_execute_request_rejects_mismatched_role_product(self):
        """ExecuteRequest(role='account_executive', product='vtrade') must raise
        ValidationError because account_executive belongs to vpromedia, not vtrade.

        This is the core AC-ERROR-3 Pydantic-level check.
        """
        with pytest.raises(ValidationError) as exc_info:
            ExecuteRequest(
                role="account_executive",
                product="vtrade",  # mismatch — ae belongs to vpromedia
                **self._COMMON_KWARGS,
            )
        errors = exc_info.value.errors()
        # At least one error should describe the role/product mismatch
        error_messages = " ".join(str(e) for e in errors).lower()
        assert any(
            keyword in error_messages
            for keyword in ("product", "role", "mismatch", "not", "belong")
        ), f"Validation error message does not describe role/product mismatch: {errors}"

    def test_execute_request_accepts_valid_vpromedia_role(self):
        """ExecuteRequest(role='account_executive', product='vpromedia') must succeed."""
        req = ExecuteRequest(
            role="account_executive",
            product="vpromedia",
            **self._COMMON_KWARGS,
        )
        assert req.role == "account_executive"
        assert req.product == "vpromedia"

    def test_execute_request_accepts_valid_vtrade_role(self):
        """ExecuteRequest(role='vtrade_exec', product='vtrade') must succeed."""
        req = ExecuteRequest(
            role="vtrade_exec",
            product="vtrade",
            **self._COMMON_KWARGS,
        )
        assert req.role == "vtrade_exec"
        assert req.product == "vtrade"

    def test_execute_request_rejects_vtrade_role_for_vpromedia(self):
        """ExecuteRequest(role='vtrade_exec', product='vpromedia') must raise.

        AC-ERROR-3: Backend rejects a run request whose role does not belong to
        the requested product.
        """
        with pytest.raises(ValidationError):
            ExecuteRequest(
                role="vtrade_exec",
                product="vpromedia",  # mismatch — vtrade_exec belongs to vtrade
                **self._COMMON_KWARGS,
            )

    def test_execute_request_rejects_unknown_role(self):
        """ExecuteRequest with a completely unknown role key must raise ValidationError."""
        with pytest.raises(ValidationError):
            ExecuteRequest(
                role="totally_fake_role",
                product="vpromedia",
                **self._COMMON_KWARGS,
            )

    def test_execute_request_rejects_unknown_product(self):
        """ExecuteRequest with an unregistered product slug must raise ValidationError."""
        with pytest.raises(ValidationError):
            ExecuteRequest(
                role="account_executive",
                product="vunknown",  # not in registry
                **self._COMMON_KWARGS,
            )


# ---------------------------------------------------------------------------
# 5. HTTP integration test — /execute returns 400 on role/product mismatch
# ---------------------------------------------------------------------------


class TestExecuteEndpointReturns400OnRoleProductMismatch:
    """The /execute HTTP endpoint must return 400 (not 422) when product+role
    are mismatched, as required by AC-ERROR-3.

    Uses FastAPI TestClient to exercise the full HTTP layer.
    """

    @pytest.fixture(scope="class")
    def client(self):
        """TestClient wrapping the FastAPI app with auth disabled."""
        from unittest.mock import patch
        from backend.main import app

        with patch("backend.config.settings") as mock_settings:
            mock_settings.api_auth_enabled = False
            mock_settings.vqa_mode = "headless"
            mock_settings.log_level = "ERROR"
            # Provide product_registry so settings.get_product() works
            mock_settings.product_registry = _load_real_registry()
            yield TestClient(app)

    def test_execute_endpoint_returns_400_on_mismatch(self, client: TestClient):
        """POST /execute with product=vpromedia, role=vtrade_exec must return 400.

        AC-ERROR-3: 'Backend returns 400 on product=vpromedia + role=vtrade_exec
        mismatch.'
        """
        payload = {
            "jira_ticket_id": "VC2-9999",
            "role": "vtrade_exec",         # belongs to vtrade
            "product": "vpromedia",        # mismatch
            "target_url": "https://two-test.vcreative.net",
            "mode": "headless",
        }
        response = client.post("/api/execute", json=payload)
        assert response.status_code == 400, (
            f"Expected 400 for role/product mismatch, got {response.status_code}.\n"
            f"Response body: {response.text}"
        )
        body = response.json()
        # Error message should describe the mismatch
        detail = str(body.get("detail", "")).lower()
        assert any(
            keyword in detail
            for keyword in ("role", "product", "not available", "belong", "mismatch")
        ), f"400 response detail does not describe the role/product mismatch: {body}"

    def test_execute_endpoint_returns_not_400_on_valid_request(self, client: TestClient):
        """POST /execute with a valid vpromedia role should NOT return 400.

        The endpoint may return other errors (e.g. 500 due to missing Jira
        config in test env), but it must not reject on role/product grounds.

        NOTE: We assert status_code != 400. A 422 means our new product field
        is not yet accepted by the schema (RED phase). A 500 means the backend
        tried to process but hit an external dependency (acceptable in this
        integration test).
        """
        payload = {
            "jira_ticket_id": "VC2-9999",
            "role": "account_executive",   # belongs to vpromedia
            "product": "vpromedia",        # correct pairing
            "target_url": "https://two-test.vcreative.net",
            "mode": "headless",
        }
        response = client.post("/api/execute", json=payload)
        # Should NOT be rejected for role/product mismatch
        assert response.status_code != 400, (
            f"A valid vpromedia/account_executive request was rejected with 400.\n"
            f"This indicates the role/product validator is incorrectly configured.\n"
            f"Response body: {response.text}"
        )
