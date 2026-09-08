"""
tests/backend/test_persona_scoping.py
========================================
TDD tests for TASK-124, Phase 3: Per-Product Persona Scoping.

Verifies:
1. Persona files have been moved to knowledge/personas/vpromedia/ (filesystem)
2. Per-product persona directories exist for all 6 products
3. load_local_persona_credentials() accepts a product-scoped directory and
   returns credentials for vProMedia roles while gracefully returning an
   empty dict for products that have no persona files.
4. resolve_persona_dir() helper in kb_client resolves the correct filesystem
   path for a given product slug using the registry.

ALL TESTS SHOULD FAIL until Phase 3 implementation is complete (TDD RED phase).

Per-phase test guidance (task file, Phase 3):
  - Extend registry loader tests to cover personas_dir field.
  - Add test that resolves a persona file path for each product and asserts
    the path exists (for vProMedia) or is None / empty (for stub products).
  - Verify load_local_persona_credentials() respects product scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo root — needed for relative filesystem assertions
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# 1. Filesystem structure: vpromedia subdir exists and contains all 11 files
# ---------------------------------------------------------------------------


class TestPersonaDirectoryStructure:
    """Persona .md files must live under knowledge/personas/vpromedia/, not
    at the flat knowledge/personas/ root."""

    def test_vpromedia_subdir_exists(self):
        """knowledge/personas/vpromedia/ directory must exist."""
        vpromedia_dir = _REPO_ROOT / "knowledge" / "personas" / "vpromedia"
        assert vpromedia_dir.is_dir(), (
            f"Expected directory {vpromedia_dir} to exist after Phase 3 migration."
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "account_executive.md",
            "sales_manager.md",
            "sales_assistant.md",
            "production_manager.md",
            "producer.md",
            "gm_gsm.md",
            "dubber.md",
            "digital_director.md",
            "traffic_manager.md",
            "voicer.md",
            "writer.md",
        ],
    )
    def test_vpromedia_persona_file_present(self, filename: str):
        """Each of the 11 vProMedia persona files must be in vpromedia/."""
        persona_path = _REPO_ROOT / "knowledge" / "personas" / "vpromedia" / filename
        assert persona_path.exists(), (
            f"Persona file {filename} not found at {persona_path}. "
            "Files must be moved from knowledge/personas/ to knowledge/personas/vpromedia/."
        )

    def test_flat_personas_dir_has_no_md_files(self):
        """The flat knowledge/personas/ root must no longer contain any .md files
        directly — all persona .md files should be in product subdirectories."""
        flat_dir = _REPO_ROOT / "knowledge" / "personas"
        if not flat_dir.is_dir():
            pytest.skip("knowledge/personas/ does not exist — nothing to check.")
        md_files_at_root = list(flat_dir.glob("*.md"))
        assert md_files_at_root == [], (
            f"Found {len(md_files_at_root)} .md file(s) still at the flat root: "
            f"{[f.name for f in md_files_at_root]}. "
            "All persona files must be moved to product subdirectories."
        )

    @pytest.mark.parametrize("slug", ["vtrade", "vpromotions", "vep", "vppo", "psn"])
    def test_stub_product_subdir_exists(self, slug: str):
        """Each stub product must have an (empty) knowledge/personas/<slug>/ directory."""
        product_dir = _REPO_ROOT / "knowledge" / "personas" / slug
        assert product_dir.is_dir(), (
            f"Expected stub directory knowledge/personas/{slug}/ to exist."
        )


# ---------------------------------------------------------------------------
# 2. ProductContext.personas_dir field is populated for all products
# ---------------------------------------------------------------------------


class TestProductRegistryPersonasDir:
    """ProductContext.personas_dir field must be populated for all 6 products
    and must point to the correct filesystem path convention."""

    def _load_real_registry(self):
        from backend.config.product_registry import load_product_registry
        return load_product_registry(
            path=_REPO_ROOT / "backend" / "config" / "products.yaml"
        )

    def test_vpromedia_personas_dir_points_to_vpromedia_subdir(self):
        """vpromedia.personas_dir == 'knowledge/personas/vpromedia'."""
        registry = self._load_real_registry()
        vpromedia = registry.get("vpromedia")
        assert vpromedia.personas_dir == "knowledge/personas/vpromedia", (
            f"Expected 'knowledge/personas/vpromedia', got '{vpromedia.personas_dir}'"
        )

    @pytest.mark.parametrize("slug", ["vtrade", "vpromotions", "vep", "vppo", "psn"])
    def test_stub_product_personas_dir_populated(self, slug: str):
        """Each stub product must have a non-empty personas_dir field."""
        registry = self._load_real_registry()
        product = registry.get(slug)
        assert product.personas_dir, (
            f"Product '{slug}' has an empty personas_dir field — must be set to "
            f"'knowledge/personas/{slug}'."
        )
        assert product.personas_dir == f"knowledge/personas/{slug}", (
            f"Expected 'knowledge/personas/{slug}', got '{product.personas_dir}'"
        )

    def test_vpromedia_personas_dir_resolves_to_existing_path(self):
        """Resolving vpromedia.personas_dir against the repo root yields a directory
        that exists on disk after the Phase 3 migration."""
        registry = self._load_real_registry()
        vpromedia = registry.get("vpromedia")
        resolved = _REPO_ROOT / vpromedia.personas_dir
        assert resolved.is_dir(), (
            f"Resolved path {resolved} does not exist. "
            "Did you forget to create the vpromedia subdir?"
        )

    def test_stub_product_personas_dir_resolves_to_existing_path(self):
        """Resolving each stub product's personas_dir against the repo root yields a
        directory (even though it is empty)."""
        registry = self._load_real_registry()
        for slug in ("vtrade", "vpromotions", "vep", "vppo", "psn"):
            product = registry.get(slug)
            resolved = _REPO_ROOT / product.personas_dir
            assert resolved.is_dir(), (
                f"Resolved path {resolved} for product '{slug}' does not exist. "
                "Create an empty subdir per the Phase 3 checklist."
            )


# ---------------------------------------------------------------------------
# 3. load_local_persona_credentials with a product-scoped directory
# ---------------------------------------------------------------------------


class TestLoadLocalPersonaCredentialsProductScoped:
    """load_local_persona_credentials() must accept a ``personas_dir`` parameter
    (absolute Path) and return credentials only for files in that directory.

    Signature change expected in Phase 3:
        load_local_persona_credentials(personas_dir: Path | None = None) -> dict
    When ``personas_dir`` is None it falls back to the legacy flat path (backward
    compat) but emits a deprecation log. When supplied it uses the given dir.
    """

    def test_vpromedia_dir_loads_at_least_one_credential(self):
        """Given the vpromedia personas dir, load_local_persona_credentials returns
        at least one role credential (account_executive is always present)."""
        from backend.engine.kb_client import load_local_persona_credentials

        vpromedia_dir = _REPO_ROOT / "knowledge" / "personas" / "vpromedia"
        creds = load_local_persona_credentials(personas_dir=vpromedia_dir)
        assert isinstance(creds, dict), "Expected a dict return."
        assert len(creds) >= 1, (
            f"Expected at least 1 credential from {vpromedia_dir}, got {len(creds)}."
        )
        assert "account_executive" in creds, (
            "account_executive must be present in vpromedia credentials."
        )

    def test_vpromedia_dir_loads_ten_credential_roles(self):
        """vpromedia personas dir has 11 files — 10 of them have Login Email headers
        (sales_manager.md contains only role description, no credential fields) and
        should produce 10 credential entries."""
        from backend.engine.kb_client import load_local_persona_credentials

        vpromedia_dir = _REPO_ROOT / "knowledge" / "personas" / "vpromedia"
        creds = load_local_persona_credentials(personas_dir=vpromedia_dir)
        assert len(creds) == 10, (
            f"Expected 10 vProMedia credentials (10 files have Login Email headers), "
            f"got {len(creds)}: {sorted(creds.keys())}"
        )

    @pytest.mark.parametrize("slug", ["vtrade", "vpromotions", "vep", "vppo", "psn"])
    def test_empty_stub_dir_returns_empty_dict(self, slug: str):
        """Given an empty stub product personas dir, load_local_persona_credentials
        returns an empty dict without raising."""
        from backend.engine.kb_client import load_local_persona_credentials

        stub_dir = _REPO_ROOT / "knowledge" / "personas" / slug
        creds = load_local_persona_credentials(personas_dir=stub_dir)
        assert creds == {}, (
            f"Expected empty creds for stub product '{slug}', got: {creds}"
        )

    def test_nonexistent_dir_returns_empty_dict(self):
        """Passing a directory that does not exist returns {} without raising."""
        from backend.engine.kb_client import load_local_persona_credentials

        nonexistent = _REPO_ROOT / "knowledge" / "personas" / "does_not_exist"
        creds = load_local_persona_credentials(personas_dir=nonexistent)
        assert creds == {}, (
            "Expected empty dict for non-existent dir, no exception."
        )

    def test_no_args_backward_compat_does_not_crash(self):
        """Calling load_local_persona_credentials() with no args must not raise,
        preserving backward compatibility for callers that have not yet been
        updated to pass personas_dir."""
        from backend.engine.kb_client import load_local_persona_credentials

        # After migration, the flat dir has no .md files, so result is {}.
        # We only assert no exception is raised.
        try:
            result = load_local_persona_credentials()
            assert isinstance(result, dict)
        except TypeError as exc:
            pytest.fail(
                f"load_local_persona_credentials() with no args raised TypeError: {exc}. "
                "personas_dir must be a keyword argument with a default of None."
            )


# ---------------------------------------------------------------------------
# 4. resolve_persona_dir helper: product slug → absolute Path
# ---------------------------------------------------------------------------


class TestResolvePersonaDir:
    """kb_client.resolve_persona_dir(slug, registry, repo_root) converts a
    product slug to an absolute filesystem path using the registry's
    personas_dir field and the given repo root.

    Expected signature (new function in Phase 3):
        resolve_persona_dir(
            product_slug: str,
            registry: ProductRegistry | None = None,
            repo_root: Path | None = None,
        ) -> Path | None

    Returns:
      - An absolute Path pointing to knowledge/personas/<slug>/ when the
        product has a personas_dir configured.
      - None when the product is not found or has an empty personas_dir.
    """

    def _registry(self):
        from backend.config.product_registry import load_product_registry
        return load_product_registry(
            path=_REPO_ROOT / "backend" / "config" / "products.yaml"
        )

    def test_vpromedia_resolves_to_absolute_path(self):
        """resolve_persona_dir('vpromedia') returns an absolute path ending in
        knowledge/personas/vpromedia."""
        from backend.engine.kb_client import resolve_persona_dir

        registry = self._registry()
        result = resolve_persona_dir("vpromedia", registry=registry, repo_root=_REPO_ROOT)
        assert result is not None, "resolve_persona_dir returned None for vpromedia."
        assert result.is_absolute(), f"Expected absolute path, got {result}."
        assert result.name == "vpromedia", f"Expected path name 'vpromedia', got '{result.name}'."

    @pytest.mark.parametrize("slug", ["vtrade", "vpromotions", "vep", "vppo", "psn"])
    def test_stub_products_resolve_to_absolute_path(self, slug: str):
        """resolve_persona_dir returns an absolute Path for stub products too."""
        from backend.engine.kb_client import resolve_persona_dir

        registry = self._registry()
        result = resolve_persona_dir(slug, registry=registry, repo_root=_REPO_ROOT)
        assert result is not None, f"resolve_persona_dir returned None for '{slug}'."
        assert result.is_absolute(), f"Expected absolute path for '{slug}', got {result}."
        assert result.name == slug, f"Expected path name '{slug}', got '{result.name}'."

    def test_unknown_slug_returns_none(self):
        """resolve_persona_dir returns None for an unknown product slug."""
        from backend.engine.kb_client import resolve_persona_dir

        registry = self._registry()
        result = resolve_persona_dir("unknown_product", registry=registry, repo_root=_REPO_ROOT)
        assert result is None, (
            f"Expected None for unknown slug, got {result}."
        )


# ---------------------------------------------------------------------------
# 5. Roles.py backward compatibility: vProMedia credentials still load
# ---------------------------------------------------------------------------


class TestRolesBackwardCompatibility:
    """After migrating persona files to knowledge/personas/vpromedia/, the
    roles.py credential resolution path must still be able to load vProMedia
    credentials from local files as a fallback.

    This tests the _resolve_credentials() integration: when Bedrock KB is
    disabled and no env vars are set, the local persona files for vProMedia
    roles must still be found and loaded.
    """

    def test_local_persona_fallback_still_loads_vpromedia_creds(self):
        """With KB disabled and no env vars, load_local_persona_credentials() via
        roles.py still finds at least one vProMedia credential."""
        from backend.engine.kb_client import load_local_persona_credentials

        # Directly test the helper with the vpromedia dir — mimics what
        # _resolve_credentials() should do after Phase 3 update.
        vpromedia_dir = _REPO_ROOT / "knowledge" / "personas" / "vpromedia"
        creds = load_local_persona_credentials(personas_dir=vpromedia_dir)
        assert "account_executive" in creds, (
            "account_executive must be loadable from vpromedia persona files."
        )
        assert creds["account_executive"].get("email"), (
            "account_executive email must be non-empty."
        )
