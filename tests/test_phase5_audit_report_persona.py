"""
Phase 5 — Audit Report: Persona Switch Timeline Tests
======================================================
TASK-063 / FEAT-054

Tests for AC-HAPPY-5:
  Given a test run with at least one PERSONA_SWITCH step
  When the HTML audit report is generated
  Then each persona switch appears as a distinct step with a 🔄 icon
  Showing: previous persona name, new persona name, switch timestamp,
           credentials source (stored / initial_actor / hitl)

Tests are in RED state until reporter.py is updated with the
persona switch section.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_state(**overrides) -> dict:
    """Build the minimal VQAState-like dict needed for _render_full_report."""
    base = {
        "run_id": "run-test-123",
        "jira_ticket": {
            "ticket_id": "VC2-9999",
            "summary": "Test persona switch report",
            "acceptance_criteria_steps": ["Step 1", "Step 2"],
            "attachments": [],
            "override_login_email": "",
            "override_login_password": "",
            "credential_status": "none",
        },
        "role_context": {"role_name": "Demo AE", "role_key": "account_executive"},
        "ac_steps_completed": [0, 1],
        "ac_steps_coverage_gap": [],
        "ac_steps_skipped": [],
        "bug_log": [],
        "detailed_execution_log": [],
        "recovery_action_log": [],
        "deferred_verification_failures": [],
        "ac_quality_result": None,
        "ac_enrichment_result": None,
        "run_metrics": {},
        "cv_fallback_results": [],
        "rag_selector_stats": [],
        # FEAT-054 new fields
        "persona_switch_history": [],
        "current_persona": "account_executive",
        "ephemeral_persona_creds": {},
    }
    base.update(overrides)
    return base


def _render_report(state: dict, video_url: str = "", duration_ms: int = 1000) -> str:
    """Call _render_full_report and return the HTML."""
    from backend.engine.reporter import _render_full_report
    return _render_full_report(state, video_url, duration_ms)


# ---------------------------------------------------------------------------
# _render_persona_switch_section unit tests
# ---------------------------------------------------------------------------

class TestRenderPersonaSwitchSection:
    """Unit tests for the _render_persona_switch_section helper."""

    def test_empty_history_returns_empty_string(self):
        """No persona switches → section is omitted entirely."""
        from backend.engine.reporter import _render_persona_switch_section
        result = _render_persona_switch_section([])
        assert result == ""

    def test_none_history_returns_empty_string(self):
        """None input also yields empty string (defensive)."""
        from backend.engine.reporter import _render_persona_switch_section
        result = _render_persona_switch_section(None)
        assert result == ""

    def test_single_switch_renders_rotate_icon(self):
        """A single switch entry must render the 🔄 icon."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "🔄" in html

    def test_single_switch_shows_from_persona(self):
        """From persona role_key must appear in the section."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "account_executive" in html

    def test_single_switch_shows_to_persona(self):
        """Target persona role_key must appear in the section."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "digital_director" in html

    def test_single_switch_shows_persona_name(self):
        """Raw persona_name from Jira AC must appear in the section."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "Demo Prod dir" in html

    def test_single_switch_shows_timestamp(self):
        """Switch timestamp must appear in the rendered HTML."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "2026-05-28T20:00:00Z" in html

    def test_method_stored_shown(self):
        """Method 'stored' must appear in the rendered HTML."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "stored" in html

    def test_method_hitl_shown(self):
        """Method 'hitl' must appear in the rendered HTML for HITL switches."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "unknown_persona",
                "persona_name": "Mystery User",
                "timestamp": "2026-05-28T20:01:00Z",
                "method": "hitl",
                "duration_ms": 8500,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "hitl" in html

    def test_method_initial_actor_shown(self):
        """Method 'initial_actor' must appear for 'as yourself' switches."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "digital_director",
                "to": "account_executive",
                "persona_name": "yourself",
                "timestamp": "2026-05-28T20:02:00Z",
                "method": "initial_actor",
                "duration_ms": 1800,
            }
        ]
        html = _render_persona_switch_section(history)
        assert "initial_actor" in html

    def test_multiple_switches_rendered_as_rows(self):
        """Each switch entry must produce a distinct row/item in the HTML."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            },
            {
                "from": "digital_director",
                "to": "account_executive",
                "persona_name": "yourself",
                "timestamp": "2026-05-28T20:05:00Z",
                "method": "initial_actor",
                "duration_ms": 1500,
            },
            {
                "from": "account_executive",
                "to": "media_buyer",
                "persona_name": "Demo Media Buyer",
                "timestamp": "2026-05-28T20:10:00Z",
                "method": "stored",
                "duration_ms": 2900,
            },
        ]
        html = _render_persona_switch_section(history)
        # All three 'to' roles should appear
        assert "digital_director" in html
        assert "account_executive" in html
        assert "media_buyer" in html

    def test_multiple_switches_count_shown(self):
        """Section header should state the total number of switches."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            },
            {
                "from": "digital_director",
                "to": "account_executive",
                "persona_name": "yourself",
                "timestamp": "2026-05-28T20:05:00Z",
                "method": "initial_actor",
                "duration_ms": 1500,
            },
        ]
        html = _render_persona_switch_section(history)
        assert "2" in html  # "2 switches" or similar

    def test_duration_ms_displayed(self):
        """Duration of each switch should appear in the rendered output."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        # Should show the duration value (as ms, or formatted as seconds)
        assert "3200" in html or "3.2" in html

    def test_section_contains_table_element(self):
        """The section should use a table (or list) to display switch entries."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "persona_name": "Demo Prod dir",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                "duration_ms": 3200,
            }
        ]
        html = _render_persona_switch_section(history)
        # Section must have structured layout
        assert "<table" in html or "<ul" in html or "<ol" in html or "persona-switch" in html

    def test_missing_optional_fields_do_not_crash(self):
        """Entries missing duration_ms or persona_name should not raise."""
        from backend.engine.reporter import _render_persona_switch_section
        history = [
            {
                "from": "account_executive",
                "to": "digital_director",
                "timestamp": "2026-05-28T20:00:00Z",
                "method": "stored",
                # persona_name and duration_ms omitted
            }
        ]
        html = _render_persona_switch_section(history)
        assert "🔄" in html  # Still renders


# ---------------------------------------------------------------------------
# _render_full_report integration tests — persona section in the full report
# ---------------------------------------------------------------------------

class TestFullReportPersonaSection:
    """Tests that _render_full_report includes the persona switch section."""

    def test_no_switches_section_absent(self):
        """When persona_switch_history is empty, no persona section is rendered."""
        state = _make_minimal_state(persona_switch_history=[])
        html = _render_report(state)
        # The 🔄 icon (only in the H2 heading) must not appear when there are no switches.
        # CSS class names like 'persona-switch-section' appear in the <style> block always,
        # so we use the emoji in the visible heading text as the sentinel.
        assert "\U0001f504 Persona Switch Timeline" not in html

    def test_with_switches_section_present(self):
        """When persona_switch_history has entries, section IS rendered."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                }
            ]
        )
        html = _render_report(state)
        assert "🔄" in html

    def test_full_report_includes_both_from_and_to(self):
        """Full report HTML must contain both 'from' and 'to' role keys."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                }
            ]
        )
        html = _render_report(state)
        assert "account_executive" in html
        assert "digital_director" in html

    def test_full_report_persona_section_before_bug_log(self):
        """Persona switch section should appear before the bug log in the report."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                }
            ],
            bug_log=[
                {
                    "type": "UI",
                    "description": "Button missing",
                    "severity": "HIGH",
                }
            ],
        )
        html = _render_report(state)
        persona_pos = html.find("🔄")
        bug_pos = html.find("Bug Registry")
        assert persona_pos != -1
        assert bug_pos != -1
        assert persona_pos < bug_pos

    def test_report_still_valid_html_with_switches(self):
        """HTML document structure should remain valid (has DOCTYPE + html/head/body)."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                }
            ]
        )
        html = _render_report(state)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_three_switches_all_rendered(self):
        """All entries in persona_switch_history should appear in the full report."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                },
                {
                    "from": "digital_director",
                    "to": "account_executive",
                    "persona_name": "yourself",
                    "timestamp": "2026-05-28T20:05:00Z",
                    "method": "initial_actor",
                    "duration_ms": 1500,
                },
                {
                    "from": "account_executive",
                    "to": "media_buyer",
                    "persona_name": "Demo Media Buyer",
                    "timestamp": "2026-05-28T20:10:00Z",
                    "method": "stored",
                    "duration_ms": 2900,
                },
            ]
        )
        html = _render_report(state)
        assert "Demo Prod dir" in html
        assert "yourself" in html
        assert "Demo Media Buyer" in html

    def test_missing_persona_switch_history_key_doesnt_crash(self):
        """State dict without persona_switch_history key shouldn't crash reporter."""
        state = _make_minimal_state()
        del state["persona_switch_history"]
        # Should not raise — should behave as if empty list
        html = _render_report(state)
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------------------
# CSS styles for persona switch section
# ---------------------------------------------------------------------------

class TestPersonaSwitchStyles:
    """Verify that persona switch CSS styles are embedded in the report."""

    def test_persona_switch_css_present_when_switches_exist(self):
        """Persona switch CSS should appear when there are switch entries."""
        state = _make_minimal_state(
            persona_switch_history=[
                {
                    "from": "account_executive",
                    "to": "digital_director",
                    "persona_name": "Demo Prod dir",
                    "timestamp": "2026-05-28T20:00:00Z",
                    "method": "stored",
                    "duration_ms": 3200,
                }
            ]
        )
        html = _render_report(state)
        # The report's <style> block should contain styling for persona switch
        assert "persona-switch" in html or "persona_switch" in html
