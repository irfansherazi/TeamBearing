import json
from unittest.mock import patch

import pytest

from backend.engine.human_takeover import (
    _append_to_kb_staging,
    _save_combined_hitl_entry,
    _save_to_learned_workflows,
    _write_to_vsuite_actions_kb,
    persist_user_guidance,
)


@pytest.fixture
def temp_kb_dir(tmp_path):
    """Fixture to mock KB file paths to a temporary directory."""
    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()

    with (
        patch(
            "backend.engine.human_takeover._LEARNED_WORKFLOWS_FILE", kb_dir / "blueprints" / "learned_workflows.json"
        ),
        patch("backend.engine.human_takeover._KB_VSUITE_ACTIONS_FILE", kb_dir / "vSuite-actions.md"),
        patch("backend.engine.human_takeover._HUMAN_GUIDANCE_KB_FILE", kb_dir / "human_guidance.md"),
        patch("backend.engine.human_takeover._KB_STAGING_FILE", kb_dir / "human_learned.jsonl"),
    ):
        yield kb_dir


@pytest.mark.anyio
async def test_save_to_learned_workflows(temp_kb_dir):
    ac_step = "Click the Login button"
    action_sequence = [{"event_type": "click", "best_selector": "button#login", "strategy": "css"}]
    ticket_id = "VC2-123"

    await _save_to_learned_workflows(ac_step, action_sequence, ticket_id)

    file_path = temp_kb_dir / "blueprints" / "learned_workflows.json"
    assert file_path.exists()

    data = json.loads(file_path.read_text())
    assert ac_step in data
    assert data[ac_step]["ticket_id"] == ticket_id
    assert len(data[ac_step]["action_sequence"]) == 1
    assert data[ac_step]["action_sequence"][0]["action"] == "click"


@pytest.mark.anyio
async def test_write_to_vsuite_actions_kb(temp_kb_dir):
    ac_step = "Enter 'test@example.com' into the email field"
    action_sequence = [
        {"event_type": "keyup", "best_selector": "input[name='email']", "strategy": "css", "value": "test@example.com"}
    ]
    ticket_id = "VC2-456"
    explanation = "I typed the email manually."

    await _write_to_vsuite_actions_kb(ac_step, action_sequence, ticket_id, explanation)

    file_path = temp_kb_dir / "vSuite-actions.md"
    assert file_path.exists()
    content = file_path.read_text()

    assert f"## WORKFLOW: AUTO-LEARNED — {ac_step}" in content
    assert f"SOURCE: Human Takeover — ticket {ticket_id}" in content
    assert explanation in content
    assert "CAPTURED ACTION SEQUENCE" in content
    assert "fill" in content
    assert "test@example.com" in content


@pytest.mark.anyio
async def test_save_combined_hitl_entry(temp_kb_dir):
    ac_step = "Select 'Admin' from the role dropdown"
    explanation = "Opened the dropdown and clicked Admin."
    action_sequence = [
        {"event_type": "click", "best_selector": ".dropdown", "strategy": "css"},
        {"event_type": "click", "best_selector": "text=Admin", "strategy": "get_by_text"},
    ]
    ticket_id = "VC2-789"

    await _save_combined_hitl_entry(ac_step, explanation, action_sequence, ticket_id)

    file_path = temp_kb_dir / "human_guidance.md"
    assert file_path.exists()
    content = file_path.read_text()

    assert f"## WORKFLOW: {ac_step}" in content
    assert f"JIRA: {ticket_id}" in content
    assert explanation in content
    assert "CAPTURED DOM ACTIONS" in content
    assert "Step 1" in content
    assert "Step 2" in content


@pytest.mark.anyio
async def test_append_to_kb_staging(temp_kb_dir):
    ac_step = "Submit the form"
    pw_action = {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Submit"}
    ticket_id = "VC2-000"

    await _append_to_kb_staging(ac_step, pw_action, ticket_id)

    file_path = temp_kb_dir / "human_learned.jsonl"
    assert file_path.exists()
    line = file_path.read_text().strip()
    data = json.loads(line)

    assert data["ac_step"] == ac_step
    assert data["pw_action"] == pw_action
    assert data["ticket_id"] == ticket_id
    assert data["source"] == "human_takeover"


@pytest.mark.anyio
async def test_persist_user_guidance(temp_kb_dir):
    ac_step = "Navigate to the settings page"
    guidance_text = "Click the gear icon in the top right corner."
    ticket_id = "VC2-111"

    await persist_user_guidance(guidance_text, ac_step, ticket_id)

    file_path = temp_kb_dir / "human_guidance.md"
    assert file_path.exists()
    content = file_path.read_text()

    assert f"## WORKFLOW: {ac_step}" in content
    assert "USER-PROVIDED GUIDANCE" in content
    assert guidance_text in content
    assert "INSTRUCTIONS FOR THE AGENT" in content
