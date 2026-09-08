from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from backend.engine.exploration_runner import ExplorationRunner
from backend.engine.state import make_initial_state


@pytest.mark.anyio
async def test_exploration_scroll_to_reveal():
    """AC-EXPL-1: Verify ScrollToRevealStrategy on a live page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        fixture_path = Path(__file__).parent / "fixtures" / "exploration_test.html"
        await page.goto(f"file://{fixture_path.absolute()}")

        # Set state looking for the button
        state = make_initial_state(
            run_id="test-expl-1",
            jira_ticket_id="QA-FAKE",
            role="account_executive",
            target_url="http://localhost",
            mode="headless"
        )
        state.update({
            "jira_ticket": {
                "acceptance_criteria_steps": ["Visible after scroll"]
            },
            "ac_step_index": 0,
            "last_action": {"selector": "#target-btn", "strategy": "css"},
            "failure_type": "NOT_VISIBLE"
        })
        runner = ExplorationRunner(state=state, run_id="test-expl-1")
        result = await runner.run(page)

        await browser.close()

        assert result["found"] is True
        assert any("scroll" in p.lower() for p in result["pathway_summary"].split("|"))

@pytest.mark.anyio
async def test_exploration_expand_collapsed():
    """AC-EXPL-1: Verify ExpandCollapsedParentStrategy on a live page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        fixture_path = Path(__file__).parent / "fixtures" / "exploration_test.html"
        await page.goto(f"file://{fixture_path.absolute()}")

        state = make_initial_state(
            run_id="test-expl-2",
            jira_ticket_id="QA-FAKE",
            role="account_executive",
            target_url="http://localhost",
            mode="headless"
        )
        state.update({
            "jira_ticket": {
                "acceptance_criteria_steps": ["Visible after expand"]
            },
            "ac_step_index": 0,
            "last_action": {"selector": "#child", "strategy": "css"},
            "failure_type": "DOM_ABSENT"
        })
        runner = ExplorationRunner(state=state, run_id="test-expl-2")
        result = await runner.run(page)

        await browser.close()

        assert result["found"] is True
        assert any("expand" in p.lower() for p in result["pathway_summary"].split("|"))
