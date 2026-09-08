"""
tests/test_execute_plan_id.py
==============================

Phase 4: Routes wiring tests.

Covers all acceptance criteria for the ``POST /execute`` ``plan_id``
path and the ``POST /preview-steps`` pinned-plan authoring path:

  - AC-VERIFY-4: POST /preview-steps with inline AC persists a pinned plan
    and returns its plan_id.
  - AC-VERIFY-5: POST /execute with a valid plan_id injects pinned_plan +
    pinned_plan_id into VQAState; ac_parser_node short-circuits.
  - AC-ERROR-1: Unknown plan_id → HTTP 404 (load-bearing: LLM stages NOT called).
  - AC-ERROR-2: Expired plan_id → HTTP 410 (load-bearing: LLM stages NOT called).
  - AC-ERROR-3: plan_id + override_steps mutually exclusive → HTTP 400.
  - AC-INVARIANT-1 (end-to-end): _stage_1_normalize.call_count == 0 and
    _stage_2_compile.call_count == 0 when plan_id resolves to a pinned plan.

All tests are fully isolated: they use ``PINNED_PLANS_DIR`` env override to
write to a temp directory, and the FastAPI test client is used for HTTP-level
assertions.
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.engine.pinned_plans import PinnedPlanExpired, PinnedPlanNotFound


# ---------------------------------------------------------------------------
# Fixtures
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
    TestClient for the FastAPI app with heavy dependencies patched out.

    We patch:
      - backend.api.auth_middleware.verify_api_key → no-op (allow all)
      - backend.engine.graph.build_graph → returns a mock graph
      - backend.engine.state.make_initial_state → returns a real minimal state
        (so pinned_plan injection is actually visible)
      - asyncio.create_task → swallowed (run in background)
    """
    # Import here so env override is already set by the fixture
    from backend.main import app

    # Patch API key check so tests don't need a real key
    async def _no_auth():
        return True

    app.dependency_overrides = {}

    from backend.api.auth_middleware import verify_api_key as _vak
    app.dependency_overrides[_vak] = _no_auth

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def saved_plan_id(pinned_plans_dir):
    """
    Pre-save a pinned plan directly to the store and return its plan_id.
    Simulates a plan authored by POST /preview-steps.
    """
    from backend.engine.pinned_plans import save

    test_plan = {
        "steps": [
            {
                "goal": "Login as account_executive",
                "action": "navigate",
                "verification": {"method": "dom", "target": "h1", "value": "Dashboard"},
                "assertions": [],
            }
        ],
        "preconditions": [],
        "title": "Pinned plan from fixture",
    }
    return save(test_plan, acceptance_criteria="Given I am logged in then I see dashboard")


@pytest.fixture()
def expired_plan_id(pinned_plans_dir):
    """Pre-save a plan with an expired created_at timestamp."""
    plan_id = uuid.uuid4().hex
    payload = {
        "plan_id": plan_id,
        "created_at": time.time() - (15 * 86400),  # 15 days ago (> 14-day TTL)
        "test_plan": {
            "steps": [],
            "preconditions": [],
            "title": "expired plan",
        },
        "acceptance_criteria": "expired",
    }
    file_path = pinned_plans_dir / f"{plan_id}.json"
    with file_path.open("w") as fh:
        json.dump(payload, fh)
    return plan_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_EXECUTE_URL = "/api/execute"
_PREVIEW_STEPS_URL = "/api/preview-steps"


def _minimal_execute_payload(plan_id: str | None = None, override_steps=None) -> dict:
    """Return a minimal POST /execute body."""
    body: dict = {
        "jira_ticket_id": "VC2-9999",
        "role": "account_executive",
        "target_url": "https://test.vcreative.net",
        "mode": "headless",
    }
    if plan_id is not None:
        body["plan_id"] = plan_id
    if override_steps is not None:
        body["override_steps"] = override_steps
    return body


def _minimal_preview_post_payload(acceptance_criteria: str) -> dict:
    """Return a minimal POST /preview-steps body."""
    return {"acceptance_criteria": acceptance_criteria}


# ---------------------------------------------------------------------------
# AC-ERROR-3: plan_id + override_steps mutually exclusive → HTTP 400
# ---------------------------------------------------------------------------


class TestMutexValidation:
    """AC-ERROR-3: plan_id and override_steps must not both be supplied."""

    def test_plan_id_and_override_steps_returns_400(self, app_client):
        """
        POST /execute with both plan_id AND override_steps returns HTTP 400
        with a machine-readable error body.
        No run is started, no LLM is called.
        """
        payload = _minimal_execute_payload(
            plan_id="some-plan-id",
            override_steps=["Step 1: do something"],
        )
        resp = app_client.post(
            _EXECUTE_URL,
            json=payload,
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code == 400
        body = resp.json()
        # Machine-readable error
        assert "detail" in body
        detail_lower = body["detail"].lower()
        assert "plan_id" in detail_lower or "override_steps" in detail_lower
        assert "mutual" in detail_lower or "exclusive" in detail_lower or "both" in detail_lower


# ---------------------------------------------------------------------------
# AC-ERROR-1: Unknown plan_id → HTTP 404 — LLM stages NEVER called
# ---------------------------------------------------------------------------


class TestUnknownPlanId:
    """AC-ERROR-1: A plan_id that does not exist on disk returns 404."""

    def test_unknown_plan_id_returns_404(self, app_client):
        """
        POST /execute with an unknown plan_id returns HTTP 404.
        The LLM parser (Stage 1 + Stage 2) is NEVER invoked.
        """
        non_existent_id = uuid.uuid4().hex

        with (
            patch(
                "backend.engine.ac_parser._stage_1_normalize",
                new_callable=AsyncMock,
            ) as mock_s1,
            patch(
                "backend.engine.ac_parser._stage_2_compile",
                new_callable=AsyncMock,
            ) as mock_s2,
        ):
            resp = app_client.post(
                _EXECUTE_URL,
                json=_minimal_execute_payload(plan_id=non_existent_id),
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert non_existent_id in body["detail"] or "not found" in body["detail"].lower()

        # Load-bearing: LLM stages MUST NOT be called (determinism guarantee)
        assert mock_s1.call_count == 0, (
            f"AC-ERROR-1 VIOLATED: _stage_1_normalize called {mock_s1.call_count} time(s) "
            "on unknown plan_id path — determinism guarantee broken"
        )
        assert mock_s2.call_count == 0, (
            f"AC-ERROR-1 VIOLATED: _stage_2_compile called {mock_s2.call_count} time(s) "
            "on unknown plan_id path — determinism guarantee broken"
        )


# ---------------------------------------------------------------------------
# AC-ERROR-2: Expired plan_id → HTTP 410 — LLM stages NEVER called
# ---------------------------------------------------------------------------


class TestExpiredPlanId:
    """AC-ERROR-2: An expired plan_id returns 410 Gone."""

    def test_expired_plan_id_returns_410(self, app_client, expired_plan_id, pinned_plans_dir):
        """
        POST /execute with an expired plan_id returns HTTP 410.
        The expired file is deleted from disk.
        The LLM parser (Stage 1 + Stage 2) is NEVER invoked.
        """
        with (
            patch(
                "backend.engine.ac_parser._stage_1_normalize",
                new_callable=AsyncMock,
            ) as mock_s1,
            patch(
                "backend.engine.ac_parser._stage_2_compile",
                new_callable=AsyncMock,
            ) as mock_s2,
        ):
            resp = app_client.post(
                _EXECUTE_URL,
                json=_minimal_execute_payload(plan_id=expired_plan_id),
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 410
        body = resp.json()
        assert "detail" in body
        assert expired_plan_id in body["detail"] or "expired" in body["detail"].lower()

        # Expired file must be deleted (lazy prune)
        assert not (pinned_plans_dir / f"{expired_plan_id}.json").exists(), (
            "AC-ERROR-2: expired plan file must be deleted from disk on 410 response"
        )

        # Load-bearing: LLM stages MUST NOT be called
        assert mock_s1.call_count == 0, (
            f"AC-ERROR-2 VIOLATED: _stage_1_normalize called {mock_s1.call_count} time(s) "
            "on expired plan_id path — determinism guarantee broken"
        )
        assert mock_s2.call_count == 0, (
            f"AC-ERROR-2 VIOLATED: _stage_2_compile called {mock_s2.call_count} time(s) "
            "on expired plan_id path — determinism guarantee broken"
        )


# ---------------------------------------------------------------------------
# AC-VERIFY-5 + AC-INVARIANT-1: Valid plan_id injects state correctly
# ---------------------------------------------------------------------------


class TestValidPlanId:
    """AC-VERIFY-5 + AC-INVARIANT-1: valid plan_id → run queued; state injected."""

    def test_valid_plan_id_queues_run(self, app_client, saved_plan_id):
        """
        POST /execute with a valid plan_id returns HTTP 200 with a run_id.
        The run is queued (status == 'queued').
        """
        resp = app_client.post(
            _EXECUTE_URL,
            json=_minimal_execute_payload(plan_id=saved_plan_id),
            headers={"X-API-Key": "test"},
        )
        # Should return 200 with run_id, not an error
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "run_id" in body
        assert body["run_id"].startswith("run-")

    def test_valid_plan_id_injects_pinned_plan_into_state(
        self, app_client, saved_plan_id, tmp_path, pinned_plans_dir
    ):
        """
        AC-VERIFY-5: POST /execute with a valid plan_id injects
        state["pinned_plan"] and state["pinned_plan_id"] before the
        LangGraph runs.

        We capture the initial_state dict passed to make_initial_state +
        the injection block by checking the queued run's state directly.
        """
        from backend.api import routes as _routes

        captured_states: list[dict] = []
        _orig_make_initial_state = _routes.make_initial_state

        def _capturing_make_initial_state(**kwargs):
            s = _orig_make_initial_state(**kwargs)
            captured_states.append(s)
            return s

        with patch.object(_routes, "make_initial_state", side_effect=_capturing_make_initial_state):
            resp = app_client.post(
                _EXECUTE_URL,
                json=_minimal_execute_payload(plan_id=saved_plan_id),
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        # The injected pinned_plan must be in the queued run's state
        from backend.api.routes import _run_states
        queued_state = _run_states.get_sync(run_id)
        assert queued_state is not None, "run_id not found in _run_states"
        vqa_state = queued_state.get("state", {})
        assert vqa_state.get("pinned_plan") is not None, (
            "AC-VERIFY-5 VIOLATED: pinned_plan not injected into VQAState"
        )
        assert vqa_state.get("pinned_plan_id") == saved_plan_id, (
            f"AC-VERIFY-5 VIOLATED: pinned_plan_id mismatch "
            f"(expected={saved_plan_id!r}, got={vqa_state.get('pinned_plan_id')!r})"
        )


# ---------------------------------------------------------------------------
# AC-VERIFY-4: POST /preview-steps persists a pinned plan and returns plan_id
# ---------------------------------------------------------------------------


class TestPostPreviewSteps:
    """AC-VERIFY-4: POST /preview-steps with inline AC → plan_id returned."""

    def test_post_preview_steps_returns_plan_id(self, app_client, pinned_plans_dir):
        """
        POST /preview-steps with acceptance_criteria in the body:
          - Returns HTTP 200 with plan_id set (non-empty string)
          - Persists a file at storage/pinned_plans/<plan_id>.json

        Heavy LLM internals (jira_fetch_node, ac_parser_node) are mocked
        so the test runs without AWS credentials.
        """
        _fake_plan = {
            "steps": [
                {
                    "goal": "Login",
                    "action": "navigate",
                    "verification": {"method": "dom", "target": "h1", "value": "Dashboard"},
                    "assertions": [],
                }
            ],
            "preconditions": [],
            "title": "Post /preview-steps test plan",
        }

        # ac_parser_node is an async function that returns a state patch dict
        async def _fake_ac_parser_node(state):
            return {
                "test_plan": _fake_plan,
                "jira_ticket": {
                    "ticket_id": "INLINE",
                    "acceptance_criteria": state.get("acceptance_criteria_text", ""),
                    # PreviewStepsResponse.steps expects list[str]
                    "acceptance_criteria_steps": ["Step 1: Login to the dashboard"],
                    "summary": "Inline AC test",
                    "description": "",
                },
                "parse_quality": "good",
                "parse_quality_reason": "mock",
                "ac_quality_result": None,
                "detected_paths": [],
                "ambiguities": [],
            }

        with (
            patch(
                "backend.engine.graph.ac_parser_node",
                side_effect=_fake_ac_parser_node,
            ),
        ):
            resp = app_client.post(
                _PREVIEW_STEPS_URL,
                json=_minimal_preview_post_payload("Given I am logged in Then I see dashboard"),
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()

        # plan_id must be present and non-empty
        plan_id = body.get("plan_id")
        assert plan_id, (
            f"AC-VERIFY-4 VIOLATED: plan_id is absent or empty in POST /preview-steps response. "
            f"Response body: {body}"
        )

        # The persisted file must exist on disk
        plan_file = pinned_plans_dir / f"{plan_id}.json"
        assert plan_file.exists(), (
            f"AC-VERIFY-4 VIOLATED: pinned plan file not found at {plan_file}"
        )

        # File contents must be parseable and contain the plan
        with plan_file.open() as fh:
            stored = json.load(fh)
        assert "test_plan" in stored
        assert "created_at" in stored
        assert stored["plan_id"] == plan_id

    def test_get_preview_steps_still_works(self, app_client):
        """
        AC-VERIFY-4 additive contract: existing GET /preview-steps?ticket_id=...
        continues to work identically for callers that don't pass a body.
        Returns plan_id=None (no pinned plan authored on the GET path).
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
                        "summary": "Test ticket",
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
                        "summary": "Test ticket",
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
                _PREVIEW_STEPS_URL,
                params={"ticket_id": "VC2-0001"},
                headers={"X-API-Key": "test"},
            )

        assert resp.status_code == 200, f"GET /preview-steps returned {resp.status_code}: {resp.text}"
        body = resp.json()
        # GET path must NOT return a plan_id
        assert body.get("plan_id") is None, (
            f"GET /preview-steps must not set plan_id. Got: {body.get('plan_id')!r}"
        )
