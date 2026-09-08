"""
tests/test_schemas_pinned_plans.py
===================================

Unit tests for Phase 2: pinned-plan schema additions.

Covers:
  - ExecuteRequest.plan_id field exists, is optional (default None)
  - PreviewStepsRequest model exists, accepts acceptance_criteria
  - PreviewStepsResponse.plan_id field exists, is optional (default None)
  - ExecuteRequest round-trips correctly without plan_id (additive: existing
    callers that omit plan_id continue to work identically)
  - ExecuteRequest round-trips correctly with plan_id populated
"""

import pytest
from pydantic import ValidationError

from backend.api.schemas import ExecuteRequest, PreviewStepsRequest, PreviewStepsResponse


# ---------------------------------------------------------------------------
# ExecuteRequest.plan_id
# ---------------------------------------------------------------------------


class TestExecuteRequestPlanId:
    """ExecuteRequest.plan_id — optional field, default None."""

    def test_plan_id_field_exists(self):
        """plan_id field must exist on ExecuteRequest."""
        req = ExecuteRequest(jira_ticket_id="VC2-1234", role="account_executive")
        assert hasattr(req, "plan_id")

    def test_plan_id_defaults_to_none(self):
        """Existing callers that omit plan_id get None — additive contract."""
        req = ExecuteRequest(jira_ticket_id="VC2-1234", role="account_executive")
        assert req.plan_id is None

    def test_plan_id_accepts_string(self):
        """plan_id accepts a non-empty opaque string."""
        req = ExecuteRequest(
            jira_ticket_id="VC2-1234",
            role="account_executive",
            plan_id="abc123-opaque-id",
        )
        assert req.plan_id == "abc123-opaque-id"

    def test_plan_id_accepts_none_explicitly(self):
        """plan_id accepts explicit None (same as omitting it)."""
        req = ExecuteRequest(
            jira_ticket_id="VC2-1234",
            role="account_executive",
            plan_id=None,
        )
        assert req.plan_id is None

    def test_existing_fields_unchanged(self):
        """Adding plan_id must not break existing required fields."""
        req = ExecuteRequest(
            jira_ticket_id="VC2-9999",
            role="producer",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert req.jira_ticket_id == "VC2-9999"
        assert req.role == "producer"
        assert req.target_url == "https://two-test.vcreative.net"
        assert req.mode == "headless"
        assert req.plan_id is None


# ---------------------------------------------------------------------------
# PreviewStepsRequest
# ---------------------------------------------------------------------------


class TestPreviewStepsRequest:
    """PreviewStepsRequest — new POST body model for /preview-steps."""

    def test_model_exists(self):
        """PreviewStepsRequest must be importable from backend.api.schemas."""
        # Import already succeeded at module level; just confirm instantiation.
        req = PreviewStepsRequest(acceptance_criteria="Given a user logs in")
        assert req is not None

    def test_acceptance_criteria_required(self):
        """acceptance_criteria is a required field."""
        with pytest.raises(ValidationError):
            PreviewStepsRequest()  # type: ignore[call-arg]

    def test_acceptance_criteria_stored(self):
        """acceptance_criteria is stored verbatim."""
        ac_text = "Given the QO form is open\nWhen the user sets Status to Approved"
        req = PreviewStepsRequest(acceptance_criteria=ac_text)
        assert req.acceptance_criteria == ac_text

    def test_acceptance_criteria_non_empty_string(self):
        """acceptance_criteria must not be empty."""
        with pytest.raises(ValidationError):
            PreviewStepsRequest(acceptance_criteria="")

    def test_accepts_multiline_ac(self):
        """acceptance_criteria accepts multi-line strings (real AC is always multi-line)."""
        ac = (
            "Given the user is on the Dashboard\n"
            "When they click New Order\n"
            "Then the QO form opens"
        )
        req = PreviewStepsRequest(acceptance_criteria=ac)
        assert req.acceptance_criteria == ac


# ---------------------------------------------------------------------------
# PreviewStepsResponse.plan_id
# ---------------------------------------------------------------------------


class TestPreviewStepsResponsePlanId:
    """PreviewStepsResponse.plan_id — optional field, default None."""

    def _minimal_response(self, **kwargs) -> PreviewStepsResponse:
        """Build a minimal PreviewStepsResponse with required fields."""
        defaults = dict(
            ticket_id="VC2-1234",
            summary="Test ticket",
            acceptance_criteria="Given a user logs in",
            steps=["Step 1: Login"],
        )
        defaults.update(kwargs)
        return PreviewStepsResponse(**defaults)

    def test_plan_id_field_exists(self):
        """plan_id field must exist on PreviewStepsResponse."""
        resp = self._minimal_response()
        assert hasattr(resp, "plan_id")

    def test_plan_id_defaults_to_none(self):
        """Existing GET /preview-steps callers that don't set plan_id get None."""
        resp = self._minimal_response()
        assert resp.plan_id is None

    def test_plan_id_accepts_string(self):
        """plan_id accepts a non-empty opaque id (set by POST /preview-steps)."""
        resp = self._minimal_response(plan_id="abc-def-123")
        assert resp.plan_id == "abc-def-123"

    def test_plan_id_accepts_none_explicitly(self):
        """plan_id accepts explicit None."""
        resp = self._minimal_response(plan_id=None)
        assert resp.plan_id is None

    def test_existing_response_fields_unchanged(self):
        """Adding plan_id must not break existing PreviewStepsResponse fields."""
        resp = self._minimal_response(
            parse_quality="good",
            parse_quality_reason="Looks great",
        )
        assert resp.ticket_id == "VC2-1234"
        assert resp.steps == ["Step 1: Login"]
        assert resp.parse_quality == "good"
        assert resp.plan_id is None
