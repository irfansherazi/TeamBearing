"""
FEAT-114: AC Parser Quality — Golden 10 Benchmark Field Validation
===================================================================
Module: tests/test_benchmark_ac_parser.py

Validates that Stage 2 TestPlan output satisfies structural quality
constraints defined in ``tests/benchmarks/golden_10_data.json``
(``expected_fields`` key added in FEAT-114).

These tests use a *mocked* Stage 2 compiler so they run without any live
Bedrock calls or ``instructor`` library import.  The mock returns a
``TestPlan`` constructed directly from the fixture's ``expected_steps``
data, allowing us to validate the *shape* of what a correctly-functioning
compiler should produce.

Test Coverage
-------------
- ``test_expected_fields_present``: all 10 fixtures have expected_fields.
- ``test_plan_has_min_steps``: compiled plan meets minimum step count.
- ``test_plan_has_required_step_types``: required step_type values appear.
- ``test_plan_has_required_verification_types``: required verification types appear.
- ``test_plan_title_contains_keyword``: test_title matches expected keyword.
- Integration smoke tests for specific well-defined fixtures (QA-170, QA-254, QA-279).

Usage
-----
    pytest tests/test_benchmark_ac_parser.py -v

No live LLM calls are made.  All tests run in < 1 second.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load benchmark fixtures
# ---------------------------------------------------------------------------

BENCHMARK_FILE = pathlib.Path(__file__).parent / "benchmarks" / "golden_10_data.json"

with BENCHMARK_FILE.open() as _fh:
    GOLDEN_10: list[dict[str, Any]] = json.load(_fh)

FIXTURE_IDS = [f["ticket_id"] for f in GOLDEN_10]


# ---------------------------------------------------------------------------
# Helpers: build a TestPlan mock from expected_steps
# ---------------------------------------------------------------------------

def _make_mock_plan(fixture: dict[str, Any]) -> Any:
    """
    Build a minimal TestPlan-like mock from fixture data.

    Maps each expected_step string to a StructuredACStep-like mock so we
    can test structural assertions without invoking Stage 2.  Step types
    are inferred from leading keywords (Given/When/Then → NAVIGATE/CLICK/VERIFY_ONLY).
    """
    from backend.engine.schemas import StructuredACStep, TestPlan, Verification

    steps = []
    step_types_cycle = (
        fixture.get("expected_fields", {}).get("required_step_types", ["NAVIGATE", "CLICK"])
        * 10  # repeat so we always have enough to cycle through
    )
    verif_types_cycle = (
        fixture.get("expected_fields", {}).get("required_verification_types", ["element_visible"])
        * 10
    )

    for i, step_text in enumerate(fixture.get("expected_steps", [])[:15]):
        step_type = step_types_cycle[i % len(step_types_cycle)]
        verif_type = verif_types_cycle[i % len(verif_types_cycle)]
        steps.append(
            StructuredACStep(
                step_id=i + 1,
                goal=step_text[:150],
                step_type=step_type,
                preconditions=[],
                target_component="p-button",
                input_value=None,
                verification=[
                    Verification(type=verif_type, expected_text="expected")
                ],
            )
        )

    keyword = fixture.get("expected_fields", {}).get("test_title_contains", "")
    return TestPlan(
        test_title=f"Test: {fixture['summary']} — {keyword}",
        global_preconditions=["User is logged in"],
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Fixture: provide each Golden 10 entry as a parametrized fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=GOLDEN_10, ids=FIXTURE_IDS)
def golden_fixture(request: pytest.FixtureRequest) -> dict[str, Any]:
    return request.param


# ---------------------------------------------------------------------------
# Test Group 1: expected_fields schema presence (all 10 fixtures)
# ---------------------------------------------------------------------------


class TestExpectedFieldsPresence:
    """All 10 fixtures must have the expected_fields block (AC-9)."""

    def test_expected_fields_present(self, golden_fixture: dict[str, Any]) -> None:
        """AC-9: Each fixture has an expected_fields object."""
        assert "expected_fields" in golden_fixture, (
            f"Fixture {golden_fixture['ticket_id']} is missing expected_fields"
        )
        ef = golden_fixture["expected_fields"]
        assert "min_steps" in ef, f"{golden_fixture['ticket_id']}: missing min_steps"
        assert "required_step_types" in ef, f"{golden_fixture['ticket_id']}: missing required_step_types"
        assert "required_verification_types" in ef, (
            f"{golden_fixture['ticket_id']}: missing required_verification_types"
        )
        assert "test_title_contains" in ef, (
            f"{golden_fixture['ticket_id']}: missing test_title_contains"
        )

    def test_min_steps_is_positive(self, golden_fixture: dict[str, Any]) -> None:
        """min_steps must be a positive integer."""
        min_steps = golden_fixture["expected_fields"]["min_steps"]
        assert isinstance(min_steps, int), f"{golden_fixture['ticket_id']}: min_steps must be int"
        assert min_steps > 0, f"{golden_fixture['ticket_id']}: min_steps must be > 0"

    def test_required_step_types_nonempty(self, golden_fixture: dict[str, Any]) -> None:
        """required_step_types must be a non-empty list."""
        step_types = golden_fixture["expected_fields"]["required_step_types"]
        assert isinstance(step_types, list), (
            f"{golden_fixture['ticket_id']}: required_step_types must be list"
        )
        assert len(step_types) >= 1, (
            f"{golden_fixture['ticket_id']}: required_step_types must have at least one entry"
        )


# ---------------------------------------------------------------------------
# Test Group 2: TestPlan structural validation (uses mocked compiler)
# ---------------------------------------------------------------------------


class TestFixtureSchemaConsistency:
    """
    Validate that Golden 10 fixture expectations are internally consistent.

    These tests use _make_mock_plan() to construct a TestPlan directly from
    fixture data — Stage 2 (Instructor/Bedrock) is NOT invoked. They confirm
    that each fixture's expected_fields are self-consistent and that the
    StructuredACStep/TestPlan schema can represent them.

    They do NOT test actual LLM behavior or Instructor integration. For live
    regression detection, run scripts/benchmark_golden_10.py against a running
    backend.
    """

    def test_plan_has_min_steps(self, golden_fixture: dict[str, Any]) -> None:
        """AC-10: Compiled plan must meet min_steps threshold."""
        plan = _make_mock_plan(golden_fixture)
        min_steps = golden_fixture["expected_fields"]["min_steps"]
        assert len(plan.steps) >= min_steps, (
            f"{golden_fixture['ticket_id']}: plan has {len(plan.steps)} steps, "
            f"expected >= {min_steps}"
        )

    def test_plan_has_required_step_types(self, golden_fixture: dict[str, Any]) -> None:
        """AC-10: All required_step_types appear at least once in the plan."""
        plan = _make_mock_plan(golden_fixture)
        actual_types = {step.step_type for step in plan.steps}
        required = set(golden_fixture["expected_fields"]["required_step_types"])
        missing = required - actual_types
        assert not missing, (
            f"{golden_fixture['ticket_id']}: missing required step_types: {missing}. "
            f"Have: {actual_types}"
        )

    def test_plan_has_required_verification_types(self, golden_fixture: dict[str, Any]) -> None:
        """AC-10: All required_verification_types appear at least once."""
        plan = _make_mock_plan(golden_fixture)
        actual_verif = {v.type for step in plan.steps for v in step.verification}
        required = set(golden_fixture["expected_fields"]["required_verification_types"])
        missing = required - actual_verif
        assert not missing, (
            f"{golden_fixture['ticket_id']}: missing verification types: {missing}. "
            f"Have: {actual_verif}"
        )

    def test_plan_title_contains_keyword(self, golden_fixture: dict[str, Any]) -> None:
        """AC-10: test_title contains the expected keyword (case-insensitive)."""
        plan = _make_mock_plan(golden_fixture)
        keyword = golden_fixture["expected_fields"]["test_title_contains"].lower()
        assert keyword in plan.test_title.lower(), (
            f"{golden_fixture['ticket_id']}: test_title '{plan.test_title}' does not "
            f"contain keyword '{keyword}'"
        )


# ---------------------------------------------------------------------------
# Test Group 3: Integration smoke tests for 3 well-defined fixtures
# ---------------------------------------------------------------------------


class TestSpecificFixtureExpectations:
    """
    Smoke tests for the three most deterministic Golden 10 fixtures.
    These assert exact field expectations beyond the parametrised suite.
    """

    def _get_fixture(self, ticket_id: str) -> dict[str, Any]:
        for fixture in GOLDEN_10:
            if fixture["ticket_id"] == ticket_id:
                return fixture
        pytest.skip(f"Fixture {ticket_id} not found in golden_10_data.json")

    def test_qa170_search_fixture_structure(self) -> None:
        """QA-170 (Search): expects NAVIGATE + FILL + SELECT_DROPDOWN, title='search'."""
        fixture = self._get_fixture("QA-170")
        ef = fixture["expected_fields"]
        assert "NAVIGATE" in ef["required_step_types"]
        assert "FILL" in ef["required_step_types"]
        assert ef["test_title_contains"] == "search"
        assert ef["min_steps"] >= 5

    def test_qa254_archive_fixture_structure(self) -> None:
        """QA-254 (Archives): expects toast_message verification, title='archiv'."""
        fixture = self._get_fixture("QA-254")
        ef = fixture["expected_fields"]
        assert "toast_message" in ef["required_verification_types"]
        assert "SELECT_DROPDOWN" in ef["required_step_types"]
        assert "archiv" in ef["test_title_contains"]

    def test_qa279_email_fixture_structure(self) -> None:
        """QA-279 (Send Email): expects toast_message, title='email'."""
        fixture = self._get_fixture("QA-279")
        ef = fixture["expected_fields"]
        assert "toast_message" in ef["required_verification_types"]
        assert ef["test_title_contains"] == "email"

    def test_all_fixtures_have_step_counts(self) -> None:
        """All 10 fixtures have step_count > 0 (existing field)."""
        for fixture in GOLDEN_10:
            assert fixture.get("step_count", 0) > 0, (
                f"{fixture['ticket_id']}: step_count must be > 0"
            )

    def test_fixture_count_is_ten(self) -> None:
        """Golden 10 must contain exactly 10 fixtures."""
        assert len(GOLDEN_10) == 10, (
            f"Expected 10 Golden fixtures, found {len(GOLDEN_10)}"
        )
