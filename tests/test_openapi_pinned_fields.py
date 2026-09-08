"""
tests/test_openapi_pinned_fields.py
=====================================

Phase 5: OpenAPI schema verification for pinned TestPlan fields.

The ``/vc`` plugin preflights ``/openapi.json`` to detect Lock-B support before
choosing the ``POST /preview-steps`` → ``plan_id`` → ``POST /execute`` path.
This test file verifies that the FastAPI application's generated OpenAPI schema
exposes all three new fields introduced across Phases 1-4 so that preflight
detection works correctly without hitting a live server.

Coverage:
  - OA-1: ``ExecuteRequest.plan_id`` is present in the schema with type
    ``string | null`` (anyOf nullable) or equivalent.
  - OA-2: ``PreviewStepsRequest`` exists as a named schema component in the
    OpenAPI document (its existence signals Lock-B support to the preflight).
  - OA-3: ``PreviewStepsResponse.plan_id`` is present in the schema with
    type ``string | null`` or equivalent.
  - OA-4: The ``POST /preview-steps`` path is present in the OpenAPI paths
    (distinct from the existing ``GET /preview-steps``).
"""

import pytest

# ---------------------------------------------------------------------------
# Fixture: generate the OpenAPI schema once per session from the live app
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi_schema():
    """
    Generate the OpenAPI schema dict from the FastAPI app directly.
    Uses ``app.openapi()`` — no network call required.
    """
    from backend.main import app

    return app.openapi()


# ---------------------------------------------------------------------------
# OA-1: ExecuteRequest.plan_id in schema
# ---------------------------------------------------------------------------


class TestExecuteRequestPlanIdInSchema:
    """OA-1: ExecuteRequest.plan_id is present and nullable in the OpenAPI schema."""

    def test_execute_request_schema_exists(self, openapi_schema):
        """The ExecuteRequest component schema must exist."""
        components = openapi_schema.get("components", {}).get("schemas", {})
        assert "ExecuteRequest" in components, (
            "OA-1: ExecuteRequest must be a named schema component in the OpenAPI document"
        )

    def test_execute_request_has_plan_id_property(self, openapi_schema):
        """ExecuteRequest schema must include a plan_id property."""
        components = openapi_schema.get("components", {}).get("schemas", {})
        execute_schema = components.get("ExecuteRequest", {})
        properties = execute_schema.get("properties", {})
        assert "plan_id" in properties, (
            f"OA-1: ExecuteRequest.plan_id must be a property in the OpenAPI schema. "
            f"Found properties: {list(properties.keys())}"
        )

    def test_execute_request_plan_id_is_nullable(self, openapi_schema):
        """
        ExecuteRequest.plan_id must be nullable (str | None).
        FastAPI may represent this as anyOf with null, or as a type with null,
        or via 'anyOf: [{"type": "string"}, {"type": "null"}]'.
        We accept any representation that includes both string and null.
        """
        components = openapi_schema.get("components", {}).get("schemas", {})
        execute_schema = components.get("ExecuteRequest", {})
        properties = execute_schema.get("properties", {})
        plan_id_schema = properties.get("plan_id", {})

        # Check that it's not required (must have a default)
        required_fields = execute_schema.get("required", [])
        assert "plan_id" not in required_fields, (
            "OA-1: ExecuteRequest.plan_id must NOT be required (it is optional with default=None)"
        )

        # Check for nullable representation (anyOf or type includes null)
        is_nullable = _is_nullable_schema(plan_id_schema)
        assert is_nullable, (
            f"OA-1: ExecuteRequest.plan_id must be nullable (str | None). "
            f"Got schema: {plan_id_schema}"
        )


# ---------------------------------------------------------------------------
# OA-2: PreviewStepsRequest exists as a named schema component
# ---------------------------------------------------------------------------


class TestPreviewStepsRequestInSchema:
    """OA-2: PreviewStepsRequest must be a named component in the OpenAPI schema."""

    def test_preview_steps_request_schema_exists(self, openapi_schema):
        """
        The PreviewStepsRequest model must appear in the OpenAPI components.
        Its presence is the Lock-B support signal for the /vc plugin preflight.
        """
        components = openapi_schema.get("components", {}).get("schemas", {})
        assert "PreviewStepsRequest" in components, (
            "OA-2: PreviewStepsRequest must be a named schema component in the OpenAPI document. "
            f"Found schemas: {sorted(k for k in components if 'Preview' in k or 'preview' in k)}"
        )

    def test_preview_steps_request_has_acceptance_criteria(self, openapi_schema):
        """PreviewStepsRequest must include acceptance_criteria as a required property."""
        components = openapi_schema.get("components", {}).get("schemas", {})
        req_schema = components.get("PreviewStepsRequest", {})
        properties = req_schema.get("properties", {})
        assert "acceptance_criteria" in properties, (
            "OA-2: PreviewStepsRequest must have an acceptance_criteria property"
        )
        # acceptance_criteria is required (non-optional)
        required_fields = req_schema.get("required", [])
        assert "acceptance_criteria" in required_fields, (
            "OA-2: PreviewStepsRequest.acceptance_criteria must be required (no default)"
        )


# ---------------------------------------------------------------------------
# OA-3: PreviewStepsResponse.plan_id in schema
# ---------------------------------------------------------------------------


class TestPreviewStepsResponsePlanIdInSchema:
    """OA-3: PreviewStepsResponse.plan_id is present and nullable in the OpenAPI schema."""

    def test_preview_steps_response_schema_exists(self, openapi_schema):
        """The PreviewStepsResponse component schema must exist."""
        components = openapi_schema.get("components", {}).get("schemas", {})
        assert "PreviewStepsResponse" in components, (
            "OA-3: PreviewStepsResponse must be a named schema component in the OpenAPI document"
        )

    def test_preview_steps_response_has_plan_id(self, openapi_schema):
        """PreviewStepsResponse schema must include a plan_id property."""
        components = openapi_schema.get("components", {}).get("schemas", {})
        resp_schema = components.get("PreviewStepsResponse", {})
        properties = resp_schema.get("properties", {})
        assert "plan_id" in properties, (
            f"OA-3: PreviewStepsResponse.plan_id must be a property in the OpenAPI schema. "
            f"Found properties: {list(properties.keys())}"
        )

    def test_preview_steps_response_plan_id_is_nullable(self, openapi_schema):
        """
        PreviewStepsResponse.plan_id must be nullable (str | None).
        The GET path returns None; the POST path returns a non-empty string.
        """
        components = openapi_schema.get("components", {}).get("schemas", {})
        resp_schema = components.get("PreviewStepsResponse", {})
        properties = resp_schema.get("properties", {})
        plan_id_schema = properties.get("plan_id", {})

        # Must not be required
        required_fields = resp_schema.get("required", [])
        assert "plan_id" not in required_fields, (
            "OA-3: PreviewStepsResponse.plan_id must NOT be required (defaults to None)"
        )

        is_nullable = _is_nullable_schema(plan_id_schema)
        assert is_nullable, (
            f"OA-3: PreviewStepsResponse.plan_id must be nullable. "
            f"Got schema: {plan_id_schema}"
        )


# ---------------------------------------------------------------------------
# OA-4: POST /preview-steps path exists in OpenAPI
# ---------------------------------------------------------------------------


class TestPostPreviewStepsPathInSchema:
    """OA-4: The POST /preview-steps route is present in the OpenAPI paths."""

    def test_post_preview_steps_path_exists(self, openapi_schema):
        """
        The OpenAPI paths must include a POST operation for /api/preview-steps
        (or /preview-steps depending on router prefix).
        The /vc plugin checks for this path when detecting Lock-B support.
        """
        paths = openapi_schema.get("paths", {})

        # Accept either /api/preview-steps or /preview-steps (router prefix may vary)
        candidate_paths = ["/api/preview-steps", "/preview-steps"]
        matching_path = next(
            (p for p in candidate_paths if p in paths),
            None,
        )
        assert matching_path is not None, (
            f"OA-4: Expected a preview-steps path in OpenAPI. "
            f"Checked: {candidate_paths}. "
            f"Found paths containing 'preview': "
            f"{[p for p in paths if 'preview' in p.lower()]}"
        )

        path_item = paths[matching_path]
        assert "post" in path_item, (
            f"OA-4: {matching_path} must have a POST operation. "
            f"Found operations: {list(path_item.keys())}"
        )

    def test_get_preview_steps_path_still_exists(self, openapi_schema):
        """
        OA-4 (additive): The existing GET /preview-steps route must still be
        present — the POST is additive, not a replacement.
        """
        paths = openapi_schema.get("paths", {})
        candidate_paths = ["/api/preview-steps", "/preview-steps"]
        matching_path = next(
            (p for p in candidate_paths if p in paths),
            None,
        )
        assert matching_path is not None, (
            "OA-4: preview-steps path must exist in OpenAPI"
        )

        path_item = paths[matching_path]
        assert "get" in path_item, (
            f"OA-4: {matching_path} must still have a GET operation (backward compat). "
            f"Found operations: {list(path_item.keys())}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_nullable_schema(schema: dict) -> bool:
    """
    Return True if the JSON Schema dict represents a nullable string.

    FastAPI / Pydantic v2 can emit nullable schemas in several ways:
      - anyOf: [{type: string}, {type: null}]
      - anyOf: [{type: string}] + default: null   (older pydantic)
      - type: string + nullable: true             (OpenAPI 3.0 style)

    We check the common representations produced by Pydantic v2 + FastAPI.
    """
    # anyOf containing a null type (Pydantic v2 default for Optional[str])
    any_of = schema.get("anyOf", [])
    if any_of:
        has_string = any(
            sub.get("type") == "string" for sub in any_of
        )
        has_null = any(
            sub.get("type") == "null" for sub in any_of
        )
        if has_string and has_null:
            return True

    # type list (JSON Schema draft-07+): type: [string, null]
    type_val = schema.get("type")
    if isinstance(type_val, list) and "null" in type_val and "string" in type_val:
        return True

    # OpenAPI 3.0 nullable extension
    if schema.get("type") == "string" and schema.get("nullable") is True:
        return True

    # If anyOf has a string entry and the field has a default of None,
    # that's also nullable (some Pydantic versions do this)
    if any_of and schema.get("default") is None:
        has_string = any(
            sub.get("type") == "string" for sub in any_of
        )
        if has_string:
            return True

    return False
