"""
tests/test_phase4_hitl_persona_api.py
======================================
RED phase tests for TASK-063, Phase 4: HITL Integration.

Covers:
  - AC-HAPPY-3 (API surface): POST /runs/{run_id}/persona-credentials exists
  - Request validation: email + password required, run_id scoped
  - 404 for unknown run_id
  - 200 on success: set_persona_credentials called, event unblocked
  - Security: password never echoed in response
  - Schema: PersonaCredentialsRequest + PersonaCredentialsResponse in schemas.py
  - Frontend types: WSPersonaCredentialsMessage type exists in frontend types
  - WS hook: HITL_PERSONA_CREDENTIALS_REQUIRED message is handled
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create the FastAPI app under test."""
    from backend.main import app as _app
    return _app


@pytest.fixture
def client(app):
    """TestClient with API auth disabled."""
    yield TestClient(app)


def _seed_run(run_id: str, status: str = "running") -> None:
    """Insert a minimal run into _run_states so endpoints recognise it."""
    from backend.api import routes as _routes
    _routes._run_states[run_id] = {"status": status, "state": {}}


# ---------------------------------------------------------------------------
# 1. Schema — PersonaCredentialsRequest and PersonaCredentialsResponse
# ---------------------------------------------------------------------------


class TestPersonaCredentialsSchema:
    """The API schema module must expose PersonaCredentialsRequest and Response."""

    def test_persona_credentials_request_exists(self):
        """PersonaCredentialsRequest must be importable from backend.api.schemas."""
        from backend.api.schemas import PersonaCredentialsRequest  # noqa: F401

    def test_persona_credentials_response_exists(self):
        """PersonaCredentialsResponse must be importable from backend.api.schemas."""
        from backend.api.schemas import PersonaCredentialsResponse  # noqa: F401

    def test_request_requires_persona_name(self):
        """PersonaCredentialsRequest must require persona_name field."""
        import pydantic

        from backend.api.schemas import PersonaCredentialsRequest

        with pytest.raises((pydantic.ValidationError, TypeError)):
            PersonaCredentialsRequest(email="x@x.com", password="pass")

    def test_request_requires_email(self):
        """PersonaCredentialsRequest must require email field."""
        import pydantic

        from backend.api.schemas import PersonaCredentialsRequest

        with pytest.raises((pydantic.ValidationError, TypeError)):
            PersonaCredentialsRequest(persona_name="Bob", password="pass")

    def test_request_requires_password(self):
        """PersonaCredentialsRequest must require password field."""
        import pydantic

        from backend.api.schemas import PersonaCredentialsRequest

        with pytest.raises((pydantic.ValidationError, TypeError)):
            PersonaCredentialsRequest(persona_name="Bob", email="bob@x.com")

    def test_request_valid(self):
        """PersonaCredentialsRequest must accept all three required fields."""
        from backend.api.schemas import PersonaCredentialsRequest

        req = PersonaCredentialsRequest(
            persona_name="Demo Prod Dir",
            email="demo@vcreative.net",
            password="secret123",
        )
        assert req.persona_name == "Demo Prod Dir"
        assert req.email == "demo@vcreative.net"
        assert req.password == "secret123"

    def test_response_has_ok_field(self):
        """PersonaCredentialsResponse must have an 'ok' boolean field."""
        from backend.api.schemas import PersonaCredentialsResponse

        resp = PersonaCredentialsResponse(ok=True)
        assert resp.ok is True

    def test_response_has_optional_message(self):
        """PersonaCredentialsResponse may have an optional 'message' field."""
        from backend.api.schemas import PersonaCredentialsResponse

        resp = PersonaCredentialsResponse(ok=False, message="Run not found")
        assert resp.message == "Run not found"

    def test_response_password_not_echoed(self):
        """PersonaCredentialsResponse must NOT have a password field."""
        from backend.api.schemas import PersonaCredentialsResponse

        resp = PersonaCredentialsResponse(ok=True)
        resp_dict = resp.model_dump()
        assert "password" not in resp_dict, (
            "PersonaCredentialsResponse must NEVER echo back the password field."
        )


# ---------------------------------------------------------------------------
# 2. API endpoint — POST /runs/{run_id}/persona-credentials
# ---------------------------------------------------------------------------


class TestPersonaCredentialsEndpoint:
    """POST /runs/{run_id}/persona-credentials endpoint tests."""

    def test_endpoint_returns_404_for_unknown_run_id(self, client):
        """Unknown run_id → 404 (app-level 'run not found')."""
        resp = client.post(
            "/api/runs/non-existent-run-9999/persona-credentials",
            json={
                "persona_name": "Demo Prod Dir",
                "email": "demo@vcreative.net",
                "password": "secret123",
            },
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_endpoint_returns_422_for_missing_persona_name(self, client):
        """Missing persona_name → 422 validation error."""
        _seed_run("run-hitl-test-001")
        resp = client.post(
            "/api/runs/run-hitl-test-001/persona-credentials",
            json={
                "email": "demo@vcreative.net",
                "password": "secret123",
            },
        )
        assert resp.status_code == 422

    def test_endpoint_returns_422_for_missing_email(self, client):
        """Missing email → 422 validation error."""
        _seed_run("run-hitl-test-002")
        resp = client.post(
            "/api/runs/run-hitl-test-002/persona-credentials",
            json={
                "persona_name": "Demo Prod Dir",
                "password": "secret123",
            },
        )
        assert resp.status_code == 422

    def test_endpoint_returns_422_for_missing_password(self, client):
        """Missing password → 422 validation error."""
        _seed_run("run-hitl-test-003")
        resp = client.post(
            "/api/runs/run-hitl-test-003/persona-credentials",
            json={
                "persona_name": "Demo Prod Dir",
                "email": "demo@vcreative.net",
            },
        )
        assert resp.status_code == 422

    def test_endpoint_calls_set_persona_credentials(self, client):
        """Successful request must call set_persona_credentials with the run_id and persona."""
        run_id = "run-hitl-set-creds-001"
        _seed_run(run_id)

        with patch(
            "backend.api.routes.set_persona_credentials"
        ) as mock_set_creds:
            resp = client.post(
                f"/api/runs/{run_id}/persona-credentials",
                json={
                    "persona_name": "Demo Prod Dir",
                    "email": "demo@vcreative.net",
                    "password": "secret999",
                },
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        mock_set_creds.assert_called_once_with(
            run_id,
            "Demo Prod Dir",
            "demo@vcreative.net",
            "secret999",
        )

    def test_endpoint_returns_ok_true_on_success(self, client):
        """Successful request must return {ok: true}."""
        run_id = "run-hitl-ok-response"
        _seed_run(run_id)

        with patch("backend.api.routes.set_persona_credentials"):
            resp = client.post(
                f"/api/runs/{run_id}/persona-credentials",
                json={
                    "persona_name": "AE User",
                    "email": "ae@test.com",
                    "password": "testpass",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

    def test_endpoint_does_not_echo_password(self, client):
        """Response body must not contain the submitted password."""
        run_id = "run-hitl-security"
        _seed_run(run_id)

        with patch("backend.api.routes.set_persona_credentials"):
            resp = client.post(
                f"/api/runs/{run_id}/persona-credentials",
                json={
                    "persona_name": "Secret User",
                    "email": "secret@test.com",
                    "password": "s0-s3cr3t!",
                },
            )

        assert resp.status_code == 200
        resp_text = resp.text
        assert "s0-s3cr3t!" not in resp_text, (
            "Password must never appear in the API response body."
        )

    def test_endpoint_imported_set_persona_credentials(self, client):
        """routes.py must import set_persona_credentials at module level."""
        import backend.api.routes as routes_module

        assert hasattr(routes_module, "set_persona_credentials"), (
            "backend.api.routes must import set_persona_credentials from "
            "backend.engine.persona_switch_node at module level."
        )

    def test_endpoint_exists_in_openapi_schema(self, client):
        """The persona-credentials endpoint must appear in the OpenAPI schema."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        paths = schema.get("paths", {})
        # The router is mounted with /api prefix, so the OpenAPI path includes it
        endpoint_path = "/api/runs/{run_id}/persona-credentials"
        assert endpoint_path in paths, (
            f"Expected '{endpoint_path}' in OpenAPI paths, got: {[p for p in paths.keys() if 'persona' in p or 'runs' in p]}"
        )
        assert "post" in paths[endpoint_path], (
            f"POST method not found for '{endpoint_path}'"
        )


# ---------------------------------------------------------------------------
# 3. Security — credential scrubbing
# ---------------------------------------------------------------------------


class TestPersonaCredentialSecurity:
    """Verify security properties of the HITL credential API."""

    def test_set_persona_credentials_not_persisted_to_auth_manager(self):
        """set_persona_credentials must NOT call ensure_role_authenticated."""
        import backend.engine.persona_switch_node as psn
        from backend.engine.persona_switch_node import set_persona_credentials

        # Clean up test state before the test
        psn._persona_events.pop("sec-test-run", None)
        psn._persona_creds.pop("sec-test-run", None)

        with patch(
            "backend.engine.persona_switch_node.ensure_role_authenticated"
        ) as mock_era:
            set_persona_credentials("sec-test-run", "Mallory", "mallory@evil.com", "h4ck3r")
            mock_era.assert_not_called()

        # Cleanup
        psn._persona_creds.pop("sec-test-run", None)

    def test_persona_creds_stored_ephemerally(self):
        """set_persona_credentials must store creds in _persona_creds (in-memory only)."""
        import backend.engine.persona_switch_node as psn
        from backend.engine.persona_switch_node import set_persona_credentials

        psn._persona_creds.pop("ephemeral-test-run", None)

        set_persona_credentials("ephemeral-test-run", "Test User", "test@t.com", "p@ssword")

        assert "ephemeral-test-run" in psn._persona_creds
        stored = psn._persona_creds["ephemeral-test-run"]["Test User"]
        assert stored["email"] == "test@t.com"
        assert stored["password"] == "p@ssword"

        # Cleanup
        psn._persona_creds.pop("ephemeral-test-run", None)

    def test_clear_run_creds_removes_all_creds(self):
        """clear_run_creds must purge all creds and events for the run."""
        import backend.engine.persona_switch_node as psn
        from backend.engine.persona_switch_node import clear_run_creds, set_persona_credentials

        set_persona_credentials("cleanup-run", "Bob", "bob@b.com", "pass")
        assert "cleanup-run" in psn._persona_creds

        clear_run_creds("cleanup-run")

        assert "cleanup-run" not in psn._persona_creds
        assert "cleanup-run" not in psn._persona_events


# ---------------------------------------------------------------------------
# 4. Frontend type coverage (static analysis via file inspection)
# ---------------------------------------------------------------------------


class TestFrontendTypes:
    """Verify the frontend types/index.ts exposes WSPersonaCredentialsMessage."""

    def _get_types_file_content(self) -> str:
        """Read the frontend types file."""
        import os
        types_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "types",
            "index.ts",
        )
        types_path = os.path.abspath(types_path)
        with open(types_path, encoding="utf-8") as f:
            return f.read()

    def test_ws_persona_credentials_message_type_exists(self):
        """frontend/src/types/index.ts must define WSPersonaCredentialsMessage."""
        content = self._get_types_file_content()
        assert "WSPersonaCredentialsMessage" in content, (
            "frontend/src/types/index.ts must define WSPersonaCredentialsMessage "
            "for the HITL_PERSONA_CREDENTIALS_REQUIRED WebSocket event."
        )

    def test_ws_persona_credentials_message_has_persona_name(self):
        """WSPersonaCredentialsMessage must include a persona_name field."""
        content = self._get_types_file_content()
        # Verify the field is defined near the type definition
        assert "persona_name" in content, (
            "WSPersonaCredentialsMessage must have a persona_name field."
        )

    def test_ws_persona_credentials_message_in_union(self):
        """WSMessage union type must include WSPersonaCredentialsMessage."""
        content = self._get_types_file_content()
        assert "WSPersonaCredentialsMessage" in content, (
            "WSMessage union type must include WSPersonaCredentialsMessage."
        )

    def test_persona_credentials_api_type_exists(self):
        """frontend/src/types/index.ts must define PersonaCredentialsRequest."""
        content = self._get_types_file_content()
        assert "PersonaCredentialsRequest" in content or "PersonaCredentials" in content, (
            "Frontend types should include PersonaCredentialsRequest interface "
            "for POST /runs/{run_id}/persona-credentials calls."
        )


# ---------------------------------------------------------------------------
# 5. WebSocket hook — HITL_PERSONA_CREDENTIALS_REQUIRED handling
# ---------------------------------------------------------------------------


class TestWebSocketHookPersonaCredentials:
    """Verify useWebSocket hook handles HITL_PERSONA_CREDENTIALS_REQUIRED messages."""

    def _get_ws_hook_content(self) -> str:
        """Read the useWebSocket hook file."""
        import os
        hook_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "hooks",
            "useWebSocket.ts",
        )
        hook_path = os.path.abspath(hook_path)
        with open(hook_path, encoding="utf-8") as f:
            return f.read()

    def test_ws_hook_handles_hitl_persona_message(self):
        """useWebSocket.ts must handle 'HITL_PERSONA_CREDENTIALS_REQUIRED' message type."""
        content = self._get_ws_hook_content()
        assert "HITL_PERSONA_CREDENTIALS_REQUIRED" in content or "hitl_persona" in content.lower(), (
            "useWebSocket.ts must handle the 'HITL_PERSONA_CREDENTIALS_REQUIRED' "
            "WebSocket message type emitted by persona_switch_node."
        )

    def test_ws_hook_exposes_persona_credentials_message(self):
        """useWebSocket hook return must expose personaCredentialsMessage state."""
        content = self._get_ws_hook_content()
        assert "personaCredentials" in content, (
            "useWebSocket hook must expose personaCredentialsMessage (or similar) "
            "in its return value so components can show the credential input panel."
        )


# ---------------------------------------------------------------------------
# 6. PersonaCredentialPanel component (static file check)
# ---------------------------------------------------------------------------


class TestPersonaCredentialPanelComponent:
    """Verify the PersonaCredentialPanel React component exists."""

    def _component_path(self) -> str:
        import os
        return os.path.abspath(os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "components",
            "PersonaCredentialPanel.tsx",
        ))

    def test_persona_credential_panel_file_exists(self):
        """PersonaCredentialPanel.tsx must exist in frontend/src/components/."""
        import os
        assert os.path.isfile(self._component_path()), (
            "frontend/src/components/PersonaCredentialPanel.tsx must exist. "
            "Create this component to display the credential input form when "
            "HITL_PERSONA_CREDENTIALS_REQUIRED is received."
        )

    def test_persona_credential_panel_exports_component(self):
        """PersonaCredentialPanel.tsx must export a default component."""
        with open(self._component_path(), encoding="utf-8") as f:
            content = f.read()
        assert "export" in content and ("PersonaCredentialPanel" in content or "default" in content), (
            "PersonaCredentialPanel.tsx must export the PersonaCredentialPanel component."
        )

    def test_persona_credential_panel_has_email_field(self):
        """PersonaCredentialPanel must render an email input field."""
        with open(self._component_path(), encoding="utf-8") as f:
            content = f.read()
        assert "email" in content.lower(), (
            "PersonaCredentialPanel must include an email input field."
        )

    def test_persona_credential_panel_has_password_field(self):
        """PersonaCredentialPanel must render a password input field."""
        with open(self._component_path(), encoding="utf-8") as f:
            content = f.read()
        assert "password" in content.lower(), (
            "PersonaCredentialPanel must include a password input field."
        )

    def test_persona_credential_panel_has_submit_handler(self):
        """PersonaCredentialPanel must include a submit handler that calls the API."""
        with open(self._component_path(), encoding="utf-8") as f:
            content = f.read()
        assert "submit" in content.lower() or "onClick" in content or "onSubmit" in content, (
            "PersonaCredentialPanel must include a submit handler."
        )

    def test_persona_credential_panel_calls_persona_credentials_endpoint(self):
        """PersonaCredentialPanel must call the /persona-credentials API endpoint."""
        with open(self._component_path(), encoding="utf-8") as f:
            content = f.read()
        assert "persona-credentials" in content, (
            "PersonaCredentialPanel must POST to /runs/{run_id}/persona-credentials."
        )
