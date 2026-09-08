"""
tests/backend/test_t3a_product_kb_validation.py
================================================
TDD tests for Phase 1 (T3-a) — First-Class Product Isolation.

Covers:
  - AC-VERIFY-1: products.yaml startup validation fails when any product's
    declared KB root does not exist on disk.
  - AC-ERROR-1: POST /execute with an unregistered product (or missing KB root)
    returns 4xx with stable code 'product_kb_missing' before any browser launch.
  - AC-VERIFY-2: product-scoped KBLoader.query_workflows(product="vpromotions")
    returns ZERO entries originating from vpromedia files.
  - CQ-A2: ac_negotiator_complaint structured log tag and ComplaintCounter.
  - Startup exemption: stub products with roles=[] are exempt from KB completeness
    (they cannot run; only warn rather than hard-fail).

RED phase: all tests should fail until T3-a implementation is present.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper — minimal products.yaml data dict builder
# ---------------------------------------------------------------------------

def _make_registry_data(
    *,
    include_kb_dir: bool = True,
    kb_dir_exists: bool = True,
    product: str = "vpromotions",
) -> dict:
    """Return a minimal valid products dict for use with load_product_registry(data=...)."""
    entry: dict = {
        "display_name": "vPromotions",
        "description": "Promo platform.",
        "order": 3,
        "environments": {"rc": "https://vpromotions-rc.vcreative.net/app_test.php/promo"},
        "default_environment": "rc",
        "jira_board_ids": [39, 67],
        "roles": ["vpromotions_user"],
        "playwright_tests_dir": f"playwright/tests/{product}",
        "personas_dir": f"knowledge/personas/{product}",
    }
    if include_kb_dir:
        entry["knowledge_dir"] = f"knowledge/{product}"
        entry["selector_registry_dir"] = f"knowledge/selector_registry.json"
    return {
        "schema_version": 1,
        "products": {product: entry},
    }


# ---------------------------------------------------------------------------
# AC-VERIFY-1: Startup validation — validate_product_kb_roots()
# ---------------------------------------------------------------------------


class TestStartupValidation:
    """validate_product_kb_roots() must exit non-zero when any product's
    declared knowledge_dir root does not exist on disk (AC-VERIFY-1)."""

    def test_validate_product_kb_roots_passes_when_dir_exists(self, tmp_path):
        """When the knowledge_dir for all active products exists, validation passes."""
        from backend.config.product_registry import validate_product_kb_roots, load_product_registry

        # Create the expected directory
        kb_dir = tmp_path / "knowledge" / "vpromotions"
        kb_dir.mkdir(parents=True)
        personas_dir = tmp_path / "knowledge" / "personas" / "vpromotions"
        personas_dir.mkdir(parents=True)

        registry = load_product_registry(data=_make_registry_data())

        # Should not raise — all dirs exist (we patch the base path)
        with patch("backend.config.product_registry._REPO_ROOT", tmp_path):
            result = validate_product_kb_roots(registry)
        # Returns True or None when valid
        assert result is None or result is True

    def test_validate_product_kb_roots_raises_when_kb_dir_missing(self, tmp_path):
        """When knowledge_dir is missing, validate_product_kb_roots() raises
        ProductKBMissingError (or SystemExit with non-zero) — AC-VERIFY-1."""
        from backend.config.product_registry import (
            validate_product_kb_roots,
            ProductKBMissingError,
            load_product_registry,
        )

        registry = load_product_registry(data=_make_registry_data())

        # No directories created → missing root
        with patch("backend.config.product_registry._REPO_ROOT", tmp_path):
            with pytest.raises((ProductKBMissingError, SystemExit)):
                validate_product_kb_roots(registry)

    def test_validate_product_kb_roots_error_names_missing_path(self, tmp_path):
        """The error message must name the missing path (AC-VERIFY-1 structured error)."""
        from backend.config.product_registry import (
            validate_product_kb_roots,
            ProductKBMissingError,
            load_product_registry,
        )

        registry = load_product_registry(data=_make_registry_data())

        with patch("backend.config.product_registry._REPO_ROOT", tmp_path):
            with pytest.raises((ProductKBMissingError, SystemExit)) as exc_info:
                validate_product_kb_roots(registry)

        err_str = str(exc_info.value)
        # The error must name the product slug or the missing path
        assert "vpromotions" in err_str or "knowledge" in err_str

    def test_stub_product_with_empty_roles_is_exempt(self, tmp_path):
        """Products with roles=[] are exempt from KB completeness validation
        (they cannot run; startup still succeeds — design decision CQ-A1)."""
        from backend.config.product_registry import validate_product_kb_roots, load_product_registry

        stub_data = {
            "schema_version": 1,
            "products": {
                "vep": {
                    "display_name": "vEP",
                    "environments": {"qa": "https://vep-qa.vcreative.net"},
                    "default_environment": "qa",
                    "jira_board_ids": [],
                    "roles": [],  # stub — exempt
                    "playwright_tests_dir": "playwright/tests/vep",
                    "personas_dir": "knowledge/personas/vep",
                    "knowledge_dir": "knowledge/vep",
                    "selector_registry_dir": "knowledge/selector_registry.json",
                }
            },
        }
        registry = load_product_registry(data=stub_data)

        # No directories created — but stub product should be exempt
        with patch("backend.config.product_registry._REPO_ROOT", tmp_path):
            # Should NOT raise for stub products
            try:
                result = validate_product_kb_roots(registry)
                # exempt → passes silently
            except Exception as exc:
                pytest.fail(
                    f"validate_product_kb_roots() raised {type(exc).__name__} for stub product "
                    f"with roles=[]: {exc}"
                )


# ---------------------------------------------------------------------------
# AC-ERROR-1: POST /execute rejects unknown / missing-KB product with 4xx
# ---------------------------------------------------------------------------


class TestProductKBMissingApiRejection:
    """validate_role_product_match() in schemas.py must surface product_kb_missing
    for a product whose KB root is absent — returned BEFORE browser launch (AC-ERROR-1)."""

    def test_product_kb_missing_raises_value_error_in_schema(self, tmp_path):
        """When the product's knowledge_dir does not exist on disk,
        ExecuteRequest validation raises ValueError containing 'product_kb_missing'."""
        from backend.api.schemas import ExecuteRequest

        # Patch the registry + KB root so vpromotions KB appears missing
        with (
            patch("backend.api.schemas._load_product_registry_cached") as mock_reg,
            patch("backend.config.product_registry._REPO_ROOT", tmp_path),
        ):
            mock_product = MagicMock()
            mock_product.has_role.return_value = True
            mock_product.resolve_target_url.return_value = "https://vpromotions-rc.vcreative.net"
            mock_product.slug = "vpromotions"
            mock_product.roles = ["vpromotions_user"]
            mock_product.knowledge_dir = "knowledge/vpromotions"  # does NOT exist in tmp_path

            mock_registry = MagicMock()
            mock_registry.slugs.return_value = ["vpromotions"]
            mock_registry.get.return_value = mock_product
            mock_reg.return_value = mock_registry

            with pytest.raises(ValueError) as exc_info:
                ExecuteRequest(
                    jira_ticket_id="QA-358",
                    role="vpromotions_user",
                    product="vpromotions",
                    target_url="",
                )
            assert "product_kb_missing" in str(exc_info.value)

    def test_product_kb_present_does_not_raise(self, tmp_path):
        """When the product's knowledge_dir exists, ExecuteRequest validates fine."""
        from backend.api.schemas import ExecuteRequest

        # Create the KB dir so it passes the check
        kb_dir = tmp_path / "knowledge" / "vpromotions"
        kb_dir.mkdir(parents=True)

        with (
            patch("backend.api.schemas._load_product_registry_cached") as mock_reg,
            patch("backend.config.product_registry._REPO_ROOT", tmp_path),
        ):
            mock_product = MagicMock()
            mock_product.has_role.return_value = True
            mock_product.resolve_target_url.return_value = "https://vpromotions-rc.vcreative.net"
            mock_product.slug = "vpromotions"
            mock_product.roles = ["vpromotions_user"]
            mock_product.knowledge_dir = "knowledge/vpromotions"

            mock_registry = MagicMock()
            mock_registry.slugs.return_value = ["vpromotions"]
            mock_registry.get.return_value = mock_product
            mock_reg.return_value = mock_registry

            # Should not raise
            req = ExecuteRequest(
                jira_ticket_id="QA-358",
                role="vpromotions_user",
                product="vpromotions",
                target_url="https://vpromotions-rc.vcreative.net",
            )
            assert req.jira_ticket_id == "QA-358"


# ---------------------------------------------------------------------------
# AC-VERIFY-2: Product-scoped KB loader returns ZERO cross-product entries
# ---------------------------------------------------------------------------


class TestProductScopedKBLoader:
    """LocalKnowledgeBase.query_workflows(product="vpromotions") must return
    ZERO entries whose source file belongs to another product (AC-VERIFY-2)."""

    def test_query_workflows_returns_only_product_scoped_entries(self, tmp_path):
        """When product="vpromotions", no vpromedia workflow entries are returned."""
        from backend.kb.loader import LocalKnowledgeBase

        # Create a minimal KB dir with vpromotions and vpromedia workflows
        kb_dir = tmp_path / "knowledge"
        kb_dir.mkdir()

        vpromedia_dir = kb_dir / "vpromedia"
        vpromedia_dir.mkdir()
        vpromotions_dir = kb_dir / "vpromotions"
        vpromotions_dir.mkdir()

        # Write a vpromedia workflow
        (vpromedia_dir / "workflows.md").write_text(
            "## WORKFLOW: Quick Order\nKEYWORDS: quick order, qo\n---\nClick New Request.\n",
            encoding="utf-8",
        )
        # Write a vpromotions workflow
        (vpromotions_dir / "workflows.md").write_text(
            "## WORKFLOW: New PRF\nKEYWORDS: new prf, category\n---\nClick New PRF button.\n",
            encoding="utf-8",
        )

        with patch("backend.kb.loader._KB_DIR", kb_dir):
            kb = LocalKnowledgeBase()
            results = kb.query_workflows(product="vpromotions", text="Select Category dropdown")

        # No vpromedia workflow should appear
        assert "Quick Order" not in results, (
            "AC-VERIFY-2 VIOLATED: vpromedia 'Quick Order' workflow leaked into vpromotions query"
        )

    def test_query_workflows_zero_cross_product_entries(self, tmp_path):
        """Strict form of AC-VERIFY-2: ALL returned entries must have
        product provenance == 'vpromotions'."""
        from backend.kb.loader import LocalKnowledgeBase

        kb_dir = tmp_path / "knowledge"
        kb_dir.mkdir()

        vpromedia_dir = kb_dir / "vpromedia"
        vpromedia_dir.mkdir()
        vpromotions_dir = kb_dir / "vpromotions"
        vpromotions_dir.mkdir()

        # Write cross-product content that would historically bleed
        (vpromedia_dir / "vpromedia_workflows.md").write_text(
            "## WORKFLOW: Production Order\nKEYWORDS: production, order\n---\nCreate production order.\n",
            encoding="utf-8",
        )
        (vpromotions_dir / "vpromotions_workflows.md").write_text(
            "## WORKFLOW: PRF Submission\nKEYWORDS: prf, submit\n---\nSubmit the PRF form.\n",
            encoding="utf-8",
        )

        with patch("backend.kb.loader._KB_DIR", kb_dir):
            kb = LocalKnowledgeBase()
            # Query with text that could match both products
            results = kb.query_workflows(product="vpromotions", text="submit form")

        # AC-VERIFY-2: vpromedia content must not appear
        assert "Production Order" not in results, (
            "AC-VERIFY-2 VIOLATED: vpromedia 'Production Order' leaked into vpromotions=True query"
        )

    def test_query_workflows_without_product_returns_global(self, tmp_path):
        """Without a product filter, query_workflows() returns global results
        (backward-compatible — callers that don't pass product still work)."""
        from backend.kb.loader import LocalKnowledgeBase

        kb_dir = tmp_path / "knowledge"
        kb_dir.mkdir()

        # Single flat workflow file (global, no product dir)
        (kb_dir / "generic.md").write_text(
            "## WORKFLOW: Generic Task\nKEYWORDS: generic, task\n---\nDo something generic.\n",
            encoding="utf-8",
        )

        with patch("backend.kb.loader._KB_DIR", kb_dir):
            kb = LocalKnowledgeBase()
            results = kb.query_workflows(text="generic task")

        # Global query should still work
        assert isinstance(results, str)


# ---------------------------------------------------------------------------
# CQ-A2: ac_negotiator_complaint structured log tag + ComplaintCounter
# ---------------------------------------------------------------------------


class TestComplaintCounter:
    """ac_enricher.py must emit 'ac_negotiator_complaint' structured log events
    and track per-product complaint counts in state (CQ-A2)."""

    def test_complaint_counter_records_product_scoped_event(self):
        """ComplaintCounter.record() increments state['complaints_by_product'][product]."""
        from backend.engine.ac_enricher import ComplaintCounter

        counter = ComplaintCounter()
        counter.record(product="vpromotions", phrase="Unknown step")
        counter.record(product="vpromotions", phrase="Ambiguous AC")
        counter.record(product="vpromedia", phrase="Some other complaint")

        totals = counter.get_totals()
        assert totals.get("vpromotions", 0) == 2
        assert totals.get("vpromedia", 0) == 1

    def test_complaint_counter_emits_structured_log_event(self, caplog):
        """ComplaintCounter.record() emits a log event with
        event_type='ac_negotiator_complaint' in the extra dict."""
        from backend.engine.ac_enricher import ComplaintCounter

        counter = ComplaintCounter()

        with caplog.at_level(logging.WARNING, logger="backend.engine.ac_enricher"):
            counter.record(product="vpromotions", phrase="Missing step target")

        # Find the log record with the structured event_type
        complaint_records = [
            r for r in caplog.records
            if getattr(r, "event_type", None) == "ac_negotiator_complaint"
            or "ac_negotiator_complaint" in str(getattr(r, "__dict__", {}))
        ]
        assert len(complaint_records) >= 1, (
            "Expected at least one log record with event_type='ac_negotiator_complaint'; "
            f"found: {[r.message for r in caplog.records]}"
        )

    def test_complaint_counter_state_field_compatible_with_vqa_state(self):
        """ComplaintCounter.to_state_dict() returns a dict compatible with
        VQAState['complaints_by_product'] merge pattern."""
        from backend.engine.ac_enricher import ComplaintCounter

        counter = ComplaintCounter()
        counter.record(product="vpromotions", phrase="test")
        state_field = counter.to_state_dict()

        assert isinstance(state_field, dict)
        assert "vpromotions" in state_field
        assert isinstance(state_field["vpromotions"], int)
        assert state_field["vpromotions"] == 1
