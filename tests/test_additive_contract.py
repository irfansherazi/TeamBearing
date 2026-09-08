"""
tests/test_additive_contract.py
================================

Phase 5: Additive contract verification.

Proves that existing callers of ``GET /preview-steps?ticket_id=...`` and
``POST /execute`` who do NOT supply the new ``plan_id`` / ``acceptance_criteria``
fields are unaffected — omitting the new fields is a strict no-op.

Coverage:
  - EC-COMPAT-1: POST /execute without plan_id queues a run (normal path unchanged).
  - EC-COMPAT-2: POST /execute without override_steps and without plan_id still works
    (legacy callers who supply neither new field are unaffected).
  - EC-COMPAT-3: GET /preview-steps?ticket_id=... continues to return HTTP 200 with
    plan_id=None (new optional field defaults to None, invisible to old callers).
  - EC-COMPAT-4: PreviewStepsResponse.plan_id field has default=None so deserialization
    of pre-Phase-2 GET responses (without plan_id key) succeeds.
  - EC-COMPAT-5: ExecuteRequest.plan_id is truly optional — model instantiation
    without it succeeds; the field defaults to None.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_execute_plan_id.py — isolated tmp dir for pin store)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pinned_plans_dir(tmp_path, monkeypatch):
    """Isolate the pinned plans store to a temp directory."""
    store = tmp_path / "pinned_plans"
    store.mkdir()
    monkeypatch.setenv("PINNED_PLANS_DIR", str(store))
    return store


@pytest.fixture()
def app_client(pinned_plans_dir):
    """
    TestClient for the FastAPI app with authentication patched out.
    Same setup as test_execute_plan_id.py.
    """
    from backend.api.auth_middleware import verify_api_key as _vak
    from backend.main import app

    async def _no_auth():
        return True

    app.dependency_overrides = {}
    app.dependency_overrides[_vak] = _no_auth

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# EC-COMPAT-1 / EC-COMPAT-2: POST /execute without plan_id
# ---------------------------------------------------------------------------


class TestExecuteWithoutPlanId:
    """
    Existing POST /execute callers who omit plan_id are unaffected.
    The new field is Optional[str] = None — omitting it from the request body
    must be treated identically to plan_id=None.
    """

    def test_execute_without_plan_id_queues_run(self, app_client):
        """
        EC-COMPAT-1: POST /execute with a minimal body (no plan_id, no override_steps)
        returns HTTP 200 with a run_id — the normal queue path is unchanged.
        """
        payload = {
            "jira_ticket_id": "VC2-9001",
            "role": "account_executive",
            "target_url": "https://test.vcreative.net",
            "mode": "headless",
            # plan_id deliberately omitted — legacy caller pattern
        }
        resp = app_client.post(
            "/api/execute",
            json=payload,
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code == 200, (
            f"EC-COMPAT-1 FAILED: POST /execute without plan_id returned "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "run_id" in body, (
            "EC-COMPAT-1: response must contain run_id for queued run"
        )

    def test_execute_without_override_steps_queues_run(self, app_client):
        """
        EC-COMPAT-2: POST /execute without override_steps and without plan_id
        (the standard pre-Phase-4 caller pattern) is unaffected.
        """
        payload = {
            "jira_ticket_id": "VC2-9002",
            "role": "account_executive",
            # Neither plan_id nor override_steps — both omitted
        }
        resp = app_client.post(
            "/api/execute",
            json=payload,
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code == 200, (
            f"EC-COMPAT-2 FAILED: POST /execute without override_steps or plan_id "
            f"returned {resp.status_code}: {resp.text}"
        )
        assert "run_id" in resp.json()

    def test_execute_null_plan_id_is_same_as_omitted(self, app_client):
        """
        Explicit plan_id=null in JSON must be treated identically to omitting the field.
        The run must be queued (not rejected with 422 or 400).
        """
        payload = {
            "jira_ticket_id": "VC2-9003",
            "role": "account_executive",
            "plan_id": None,  # explicit null — must be accepted
        }
        resp = app_client.post(
            "/api/execute",
            json=payload,
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code == 200, (
            f"EC-COMPAT-1 (null): plan_id=null must be accepted, "
            f"got {resp.status_code}: {resp.text}"
        )
        assert "run_id" in resp.json()


# ---------------------------------------------------------------------------
# EC-COMPAT-3: GET /preview-steps returns plan_id=None (not absent)
# ---------------------------------------------------------------------------


class TestGetPreviewStepsReturnsNullPlanId:
    """
    EC-COMPAT-3: GET /preview-steps?ticket_id=... returns HTTP 200 and the
    response body contains plan_id=None.  Old callers that don't inspect
    plan_id are unaffected; new callers can rely on None meaning 'no pin'.
    """

    def test_get_preview_steps_plan_id_is_none(self, app_client):
        """
        GET /preview-steps (existing path) must return plan_id=None in the
        response body.  The field must be present (not absent) so that
        callers relying on the schema don't get a KeyError.
        """
        with (
            patch(
                "backend.engine.graph.jira_fetch_node",
                new_callable=AsyncMock,
                return_value={
                    "jira_ticket": {
                        "ticket_id": "VC2-0001",
                        "acceptance_criteria": "Given X When Y Then Z",
                        "acceptance_criteria_steps": ["Step 1: do X"],
                        "summary": "Compat test ticket",
                        "description": "",
                    },
                    "pending_jira_comment": None,
                },
            ),
            patch(
                "backend.engine.graph.ac_parser_node",
                new_callable=AsyncMock,
                return_value={
                    "test_plan": {"steps": [], "preconditions": [], "title": ""},
                    "jira_ticket": {
                        "ticket_id": "VC2-0001",
                        "acceptance_criteria": "Given X When Y Then Z",
                        "acceptance_criteria_steps": ["Step 1: do X"],
                        "summary": "Compat test ticket",
                        "description": "",
                    },
                    "parse_quality": "good",
                    "parse_quality_reason": None,
                    "ac_quality_result": None,
                    "detected_paths": [],
                    "ambiguities": [],
                    "pending_jira_comment": None,
                },
            ),
        ):
            resp = app_client.get(
                "/api/preview-steps",
                params={"ticket_id": "VC2-0001"},
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 200, (
            f"EC-COMPAT-3: GET /preview-steps returned {resp.status_code}: {resp.text}"
        )
        body = resp.json()

        # plan_id must be present in the response body, value must be None
        assert "plan_id" in body, (
            "EC-COMPAT-3: PreviewStepsResponse must include plan_id key "
            f"(even when None) for schema compatibility. Got keys: {list(body.keys())}"
        )
        assert body["plan_id"] is None, (
            f"EC-COMPAT-3: GET /preview-steps must set plan_id=None, "
            f"got plan_id={body['plan_id']!r}"
        )


# ---------------------------------------------------------------------------
# EC-COMPAT-4: Schema-level — plan_id defaults to None (deserialization safety)
# ---------------------------------------------------------------------------


class TestSchemaDefaults:
    """
    EC-COMPAT-4: PreviewStepsResponse.plan_id has default=None so
    deserialization of a payload without the key (e.g., cached or older
    responses) succeeds without a ValidationError.

    EC-COMPAT-5: ExecuteRequest.plan_id is Optional[str]=None — model
    instantiation without the field succeeds.
    """

    def test_preview_steps_response_plan_id_defaults_to_none(self):
        """
        EC-COMPAT-4: Constructing PreviewStepsResponse without a plan_id
        argument must succeed and produce plan_id=None.
        This guards against callers that omit the field in deserialization.
        """
        from backend.api.schemas import PreviewStepsResponse

        resp = PreviewStepsResponse(
            ticket_id="VC2-0001",
            summary="Test",
            acceptance_criteria="Given X",
            steps=["Step 1: do X"],
            # plan_id deliberately omitted
        )
        assert resp.plan_id is None, (
            f"EC-COMPAT-4: PreviewStepsResponse.plan_id must default to None, "
            f"got {resp.plan_id!r}"
        )

    def test_execute_request_plan_id_defaults_to_none(self):
        """
        EC-COMPAT-5: Constructing ExecuteRequest without plan_id must succeed
        and produce plan_id=None.  Confirms the field is truly optional.
        """
        from backend.api.schemas import ExecuteRequest

        req = ExecuteRequest(
            jira_ticket_id="VC2-0001",
            role="account_executive",
        )
        assert req.plan_id is None, (
            f"EC-COMPAT-5: ExecuteRequest.plan_id must default to None, "
            f"got {req.plan_id!r}"
        )

    def test_execute_request_with_none_plan_id_is_valid(self):
        """
        Explicitly passing plan_id=None must not raise a ValidationError.
        """
        from backend.api.schemas import ExecuteRequest

        req = ExecuteRequest(
            jira_ticket_id="VC2-0001",
            role="account_executive",
            plan_id=None,
        )
        assert req.plan_id is None
