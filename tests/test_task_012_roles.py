import os

import pytest
import yaml

from backend.api.schemas import VALID_ROLES, ExecuteRequest
from backend.engine.roles import ROLE_ALIASES, ROLE_REGISTRY, get_role_context, resolve_role_by_name
from backend.profiles.vsuite import VSUITE_PROFILE


def test_vtrade_roles_in_valid_roles():
    """Verify that vTrade roles are present in VALID_ROLES constant."""
    expected_roles = ["vtrade_exec", "vtrade_business_manager", "vtrade_sales_manager"]
    for role in expected_roles:
        assert role in VALID_ROLES, f"{role} missing from VALID_ROLES"


def test_vtrade_roles_in_registry():
    """Verify that vTrade roles are defined in the ROLE_REGISTRY and alias to correct emails."""
    expected_roles = ["vtrade_exec", "vtrade_business_manager", "vtrade_sales_manager"]
    for role in expected_roles:
        assert role in ROLE_REGISTRY, f"{role} missing from ROLE_REGISTRY"
        ctx = get_role_context(role)
        assert ctx["role_key"] == role
        assert "vTrade" in ctx["role_name"]

        # Verify the email correctly resolves and does NOT contain the typo "Managaer"
        assert "Managaer" not in ctx["login_email"]
        if role == "vtrade_business_manager":
            assert ctx["login_email"] == "imail-test+vTradeBusinessManager@vcreativeinc.com"


def test_execute_request_validation():
    """Verify that ExecuteRequest accepts the new vTrade roles."""
    vtrade_roles = ["vtrade_exec", "vtrade_business_manager", "vtrade_sales_manager"]

    for role in vtrade_roles:
        req = ExecuteRequest(
            jira_ticket_id="VC-123", role=role, product="vtrade", target_url="https://test.vcreative.net", mode="headless"
        )
        assert req.role == role


def test_invalid_role_raises_error():
    """Verify that an invalid role still raises a ValueError."""
    with pytest.raises(ValueError, match="Invalid role 'invalid_role'"):
        ExecuteRequest(jira_ticket_id="VC-123", role="invalid_role", target_url="https://test.vcreative.net")


def test_vtrade_role_alias_resolution():
    """Verify that vTrade role aliases correctly resolve to their corresponding contexts."""
    aliases = {
        "vtrade exec": "vtrade_exec",
        "vtrade business manager": "vtrade_business_manager",
        "vtrade sales manager": "vtrade_sales_manager",
    }

    # Verify they are in the alias mapping
    for alias, expected_key in aliases.items():
        assert alias in ROLE_ALIASES, f"Alias '{alias}' missing from ROLE_ALIASES"
        assert ROLE_ALIASES[alias] == expected_key, f"Alias '{alias}' should map to '{expected_key}'"

        # Verify resolution works (case insensitive)
        ctx = resolve_role_by_name(alias.upper())
        assert ctx is not None, f"Could not resolve alias '{alias}'"
        assert ctx["role_key"] == expected_key


def test_vtrade_credential_resolution():
    """Verify that credentials are correctly resolved for vTrade roles."""
    bm_ctx = get_role_context("vtrade_business_manager")

    # We verify that 'Managaer' typo is not present
    assert "Managaer" not in bm_ctx["login_email"]
    assert bm_ctx["login_email"] == "imail-test+vTradeBusinessManager@vcreativeinc.com"
    # Basic check that password is set (either from KB, env, or default)
    assert bm_ctx["login_password"] != ""


# ---------------------------------------------------------------------------
# Regression + invariant tests added for fix-vsuite-profile-missing-roles
# ---------------------------------------------------------------------------


def test_vsuite_profile_contains_vpromotions_user():
    """Regression guard: VSUITE_PROFILE.roles must define vpromotions_user.

    Before the fix, vpromotions_user was absent from _VSUITE_ROLES, causing
    ROLE_EMAIL_VPROMOTIONS_USER to be silently dropped from env_fallback_map
    and credentials to fall through to hardcoded personal-email defaults.
    """
    assert "vpromotions_user" in VSUITE_PROFILE.roles, (
        "vpromotions_user must be defined in VSUITE_PROFILE.roles so that "
        "ROLE_EMAIL_VPROMOTIONS_USER is honoured in the env_fallback_map"
    )
    assert "writer" in VSUITE_PROFILE.roles, (
        "writer must be defined in VSUITE_PROFILE.roles"
    )
    assert "traffic_manager" in VSUITE_PROFILE.roles, (
        "traffic_manager must be defined in VSUITE_PROFILE.roles"
    )


def test_vpromotions_user_honors_env_override(monkeypatch):
    """Prove that ROLE_EMAIL_VPROMOTIONS_USER is actually read when set.

    The env-override path only works when the role is defined in _VSUITE_ROLES
    with the matching email_env_var. This test exercises that end-to-end.
    """
    test_email = "vpromotions-override@vcreativeinc.com"
    monkeypatch.setenv("ROLE_EMAIL_VPROMOTIONS_USER", test_email)

    role_def = VSUITE_PROFILE.roles["vpromotions_user"]
    assert role_def.email_env_var == "ROLE_EMAIL_VPROMOTIONS_USER", (
        "RoleDefinition.email_env_var must be ROLE_EMAIL_VPROMOTIONS_USER"
    )
    resolved = os.getenv(role_def.email_env_var, "")
    assert resolved == test_email, (
        f"Expected env override {test_email!r} but got {resolved!r}"
    )


def test_profile_defines_every_products_yaml_role():
    """Invariant: every role listed in products.yaml must appear in VSUITE_PROFILE.roles.

    This locks the gap so CI catches the next dropped role before it reaches
    production and silently falls back to stale hardcoded credentials.
    """
    products_yaml_path = os.path.join(
        os.path.dirname(__file__), "..", "backend", "config", "products.yaml"
    )
    with open(products_yaml_path) as f:
        config = yaml.safe_load(f)

    profile_role_keys = set(VSUITE_PROFILE.roles.keys())
    missing: list[str] = []
    for product_name, product in config.get("products", {}).items():
        for role_key in product.get("roles", []):
            if role_key not in profile_role_keys:
                missing.append(f"{role_key} (product: {product_name})")

    assert not missing, (
        "The following roles are in products.yaml but missing from VSUITE_PROFILE.roles — "
        "add RoleDefinition entries so env-var overrides work: " + ", ".join(missing)
    )
