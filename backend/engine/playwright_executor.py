import asyncio
import logging
import os
from typing import Dict

from backend.engine.state import VQAState
from backend.storage.playwright_registry import PlaywrightRegistry

logger = logging.getLogger(__name__)

async def playwright_executor_node(state: VQAState) -> Dict:
    """
    Executes a static Playwright test and streams output to WebSockets.
    
    This node:
    1. Resolves the test file path from the PlaywrightRegistry.
    2. Spawns an 'npx playwright test' subprocess.
    3. Streams stdout/stderr to the run's WebSocket log via _broadcast_terminal_log.
    4. Returns success/failure status for the reporter.
    """
    from backend.api.routes import _broadcast_terminal_log

    test_id = state.get("playwright_test_id")
    run_id = state.get("run_id", "unknown")

    if not test_id:
        logger.error(f"[{run_id}] No playwright_test_id provided in state")
        return {"last_error": "No playwright_test_id provided"}

    # Initialize registry to find the test path
    # Defaults align with Phase 1 structure
    tests_dir = os.getenv("PLAYWRIGHT_TESTS_DIR", "backend/playwright_tests")
    registry_file = os.getenv("PLAYWRIGHT_REGISTRY_FILE", "backend/storage/playwright_registry.json")
    registry = PlaywrightRegistry(tests_dir, registry_file)

    test_meta = registry.get_test(test_id)
    if not test_meta:
        logger.error(f"[{run_id}] Test ID '{test_id}' not found in registry")
        return {"last_error": f"Test ID '{test_id}' not found in registry"}

    test_path = test_meta["path"]
    if not os.path.exists(test_path):
         logger.error(f"[{run_id}] Test file not found at path: {test_path}")
         return {"last_error": f"Test file not found: {test_path}"}

    # Prepare environment
    env = os.environ.copy()
    from backend.browser.context import resolve_display
    resolve_display(env)
    env["BROWSER"] = "chromium"

    # Command to run Playwright
    # We use npx to ensure the local playwright installation is used
    cmd = ["npx", "playwright", "test", test_path]
    if state.get("execution_mode") != "headless":
        cmd.append("--headed")

    logger.info(f"[{run_id}] Spawning Playwright subprocess: {' '.join(cmd)}")

    try:
        # Start subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        # Update state with PID (for process management/cancellation)
        # Note: LangGraph state update happens via the returned dict

        # Task to stream pipes to WebSockets
        async def stream_pipe(pipe, stream_type):
            if not pipe:
                return
            while True:
                line = await pipe.readline()
                if not line:
                    break
                decoded_line = line.decode().strip()
                if decoded_line:
                    await _broadcast_terminal_log(run_id, decoded_line, stream_type)

        # Run streaming tasks in parallel
        stdout_task = asyncio.create_task(stream_pipe(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(stream_pipe(process.stderr, "stderr"))

        # Wait for process to finish
        exit_code = await process.wait()

        # Ensure all output is read/broadcasted
        await asyncio.gather(stdout_task, stderr_task)

        success = (exit_code == 0)
        logger.info(f"[{run_id}] Playwright execution finished with exit code {exit_code}")

        return {
            "static_execution_pid": None,
            "last_error": "" if success else f"Playwright test failed with exit code {exit_code}",
            "_next_node": "reporter"
        }

    except Exception as e:
        logger.exception(f"[{run_id}] Critical error during Playwright execution: {str(e)}")
        return {
            "static_execution_pid": None,
            "last_error": f"Subprocess error: {str(e)}",
            "_next_node": "reporter"
        }
