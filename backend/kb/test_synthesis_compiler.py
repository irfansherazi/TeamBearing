"""
backend/kb/test_synthesis_compiler.py
======================================
LLM-compiler translating autonomous run JSON action macros to standard, typed, and registered Playwright tests (.spec.ts).
"""

import os
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from backend.llm import get_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert test synthesis compiler specializing in converting "
    "automated exploration execution logs into standard, clean, type-safe Playwright "
    "TypeScript tests (.spec.ts).\n\n"
    "Given a JSON array of executed actions, translate them into a valid Playwright test.\n\n"
    "Guidelines:\n"
    "1. Import standard `@playwright/test` fixtures: `import {{ test, expect }} from '@playwright/test';`.\n"
    "2. The main test block should be defined using: `test('synthesis run {run_id}', async ({{ page }}) => {{ ... }});`.\n"
    "3. Map the action types correctly:\n"
    "   - 'navigate': use `await page.goto(value);`\n"
    "   - 'click': use `await page.click(target);` or appropriate Playwright locator click\n"
    "   - 'fill' or 'input': use `await page.fill(target, value);`\n"
    "   - 'select': use `await page.selectOption(target, value);`\n"
    "4. Add a standard page settling wait if appropriate: e.g. `await page.waitForLoadState('networkidle');` after navigations or heavy clicks.\n"
    "5. For any step that contains a 'state_expectation', synthesize a Playwright assertion (e.g. using `await expect(...)` or `await expect(page).toHaveURL(...)` or `await expect(page.locator(...)).toBeVisible()`).\n"
    "6. Ensure the generated file contains valid, compileable, type-safe TypeScript code. Do not include any explanation, introductory/concluding remarks, or markdown text outside the code block. Return ONLY the TypeScript code inside a markdown code block starting with ```typescript."
)


class TestSynthesisCompiler:
    """
    LLM Compiler that translates autonomous exploration JSON macros to Playwright tests,
    registers them, and automates git branch and PR operations.
    """
    __test__ = False

    def __init__(self, tests_dir: Optional[str] = None, registry_file: Optional[str] = None):
        """
        Initialise compiler with optional directories.
        """
        self.tests_dir = Path(tests_dir or os.getenv("PLAYWRIGHT_TESTS_DIR", "playwright/tests"))
        self.registry_file = Path(registry_file or os.getenv("PLAYWRIGHT_INDEX_FILE", "playwright/playwright_index.json"))

    def compile_run(self, run_id: str, action_log: List[Dict]) -> str:
        """
        Translates a list of actions to a valid Playwright TypeScript test code.
        """
        llm = get_llm("compiler", heavy=True)
        
        action_log_json = json.dumps(action_log, indent=2)
        system_msg = SYSTEM_PROMPT.format(run_id=run_id)
        user_msg = f"Translate the following exploration execution action log into a Playwright test:\n\n{action_log_json}\n\nReturn the Playwright TypeScript test code now:"
        
        response = llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
        raw_code = (response.content or "").strip()
        
        # Strip markdown fences if present
        if raw_code.startswith("```"):
            parts = raw_code.split("```")
            if len(parts) >= 3:
                raw_code = parts[1].strip()
                if raw_code.startswith("typescript"):
                    raw_code = raw_code[10:].strip()
                elif raw_code.startswith("ts"):
                    raw_code = raw_code[2:].strip()
            elif len(parts) == 2:
                # Handle single-sided fence
                raw_code = parts[1].strip()
                if raw_code.startswith("typescript"):
                    raw_code = raw_code[10:].strip()
                elif raw_code.startswith("ts"):
                    raw_code = raw_code[2:].strip()
                    
        return raw_code

    def save_test(self, run_id: str, compiled_code: str) -> Path:
        """
        Saves the compiled TypeScript code under playwright/tests/.
        """
        self.tests_dir.mkdir(parents=True, exist_ok=True)
        test_file_path = self.tests_dir / f"synthesis_run_{run_id}.spec.ts"
        with open(test_file_path, "w") as f:
            f.write(compiled_code)
        return test_file_path

    def register_test(self, run_id: str, action_log: List[Dict]) -> None:
        """
        Registers the synthesized test in the playwright registry JSON file.
        """
        registry_path = Path(self.registry_file)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        
        tests = []
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    tests = json.load(f)
                    if not isinstance(tests, list):
                        tests = []
            except (json.JSONDecodeError, IOError):
                tests = []
        
        test_id = f"synthesis_run_{run_id}"
        test_file_rel = f"tests/synthesis_run_{run_id}.spec.ts"
        
        step_names = []
        for step in action_log:
            step_name = step.get("state_expectation") or f"{step.get('action', 'action')} on {step.get('target', 'unknown')}"
            step_names.append(step_name)
            
        new_entry = {
            "id": test_id,
            "file": test_file_rel,
            "jira_keys": [],
            "description": f"Synthesized test for run {run_id}",
            "steps_count": len(action_log),
            "step_names": step_names
        }
        
        updated = False
        for i, t in enumerate(tests):
            if t.get("id") == test_id:
                tests[i] = new_entry
                updated = True
                break
                
        if not updated:
            tests.append(new_entry)
            
        with open(registry_path, "w") as f:
            json.dump(tests, f, indent=2)

    def git_checkout_branch(self, branch_name: str) -> None:
        """Helper to run git checkout."""
        subprocess.run(["git", "checkout", "-b", branch_name], check=True, capture_output=True, text=True)

    def git_add_files(self, files: List[str]) -> None:
        """Helper to run git add."""
        subprocess.run(["git", "add"] + files, check=True, capture_output=True, text=True)

    def git_commit(self, message: str) -> None:
        """Helper to run git commit."""
        subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True, text=True)

    def github_pr_create(self, title: str, body: str) -> str:
        """Helper to run gh pr create."""
        res = subprocess.run(["gh", "pr", "create", "--title", title, "--body", body], check=True, capture_output=True, text=True)
        return res.stdout.strip()

    def automate_branch_and_pr(self, run_id: str, test_file_path: Path) -> str:
        """
        Orchestrates git branch creation, staging files, committing, and opening a Pull Request.
        """
        timestamp = int(datetime.now(timezone.utc).timestamp())
        branch_name = f"synthesis/run-{run_id}-{timestamp}"
        
        try:
            self.git_checkout_branch(branch_name)
            
            # Use relative paths for git add
            rel_test_path = os.path.relpath(test_file_path, os.getcwd())
            rel_registry_path = os.path.relpath(self.registry_file, os.getcwd())
            
            self.git_add_files([rel_test_path, rel_registry_path])
            self.git_commit(f"test(synthesis): generate test for run {run_id}")
            
            pr_title = f"Synthesized Test: Run {run_id}"
            pr_body = f"Automatically generated integration test from exploratory execution run {run_id}."
            
            pr_link = self.github_pr_create(pr_title, pr_body)
            return pr_link if pr_link else f"https://github.com/mock-repo/pull/{run_id}"
            
        except Exception as e:
            logger.error(f"Git / Pull Request automation failed: {e}")
            raise
