"""
backend/engine/linear_bridge.py
=================================
TASK-106: Linear Pipeline → FastAPI WebSocket Bridge.

Implements the full Generate → Validate → Execute → Analyze DAG using:
  - Python nodes (generator_node.py, validator_node.py) for LLM-backed steps.
  - ``asyncio.create_subprocess_exec`` for the Playwright Execute node
    (deterministic, no LLM in the execution hot-path).

Architecture decision (TASK-106):
  AWS Bedrock (boto3) is only available in Python, not Node.js. Rather than
  adding @aws-sdk to the frontend bundle, the bridge keeps all LLM calls in
  Python and shells out ONLY for ``npx playwright test`` execution.

Hard safety limits (matching core/pipeline.ts guardrails):
  - Compile retry ceiling:   1 (halt on second failure → COMPILE_FAILED)
  - Execution retry ceiling: 1 (strict-mode collision only; halt → EXECUTE_FAILED)
  - Per-run wall-clock timeout: 5 minutes (300 s) — SIGTERM sent after expiry.

Usage (programmatic — called from routes.py _execute_linear_run):
    from backend.engine.linear_bridge import run_linear_pipeline, LinearRunResult
    result = await run_linear_pipeline(
        run_id="run-abc123",
        card=card_dict,
        tenant_id="vpromedia",
        broadcast_fn=_broadcast_terminal_log,
        timeout_s=300,
    )

Result codes:
    "completed"  — Playwright spec compiled and executed successfully.
    "failed"     — COMPILE_FAILED or EXECUTE_FAILED after retries exhausted.
    "timeout"    — Hard 5-minute wall-clock exceeded.
    "error"      — Unexpected exception during orchestration.
"""

import asyncio
import logging
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LinearRunResult:
    """
    Structured result from a complete linear pipeline execution.

    Attributes
    ----------
    status : str
        "completed" | "failed" | "timeout" | "error"
    pipeline_status : str
        Fine-grained pipeline step outcome:
        "SUCCESS" | "COMPILE_FAILED" | "EXECUTE_FAILED" | "GENERATION_FAILED" | "PIPELINE_ERROR"
    ticket_id : str
        Jira ticket identifier from the corpus card.
    spec_path : str | None
        Absolute path to the generated .spec.ts file (None if generation failed).
    analysis : str
        Human-readable AC-level failure report from the Analyze node (empty on success).
    compile_attempts : int
        1 or 2 (number of TypeScript compilation attempts made).
    elapsed_s : float
        Wall-clock seconds from pipeline start to finish.
    error : str
        Raw exception or pipeline error message (empty on success).
    """

    status: Literal["completed", "failed", "timeout", "error"] = "error"
    pipeline_status: str = "PIPELINE_ERROR"
    ticket_id: str = "UNKNOWN"
    spec_path: Optional[str] = None
    analysis: str = ""
    compile_attempts: int = 0
    elapsed_s: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Execute node — deterministic Playwright subprocess
# ---------------------------------------------------------------------------


async def _run_playwright_spec(
    spec_path: str,
    run_id: str,
    tenant_id: str,
    broadcast_fn: Optional[Callable] = None,
    timeout_s: float = 240,
) -> tuple[bool, str]:
    """
    Execute a generated .spec.ts file via ``npx playwright test``.

    Streams stdout/stderr lines to ``broadcast_fn`` in real time.

    Returns
    -------
    (success: bool, full_output: str)
    """
    logger.info("[%s] Execute node: running %s", run_id, pathlib.Path(spec_path).name)

    env_overrides = {
        "VQA_RUN_ID": run_id,
        "VQA_TENANT_ID": tenant_id,
    }

    # Build the env dict (inherit process env, then overlay overrides)
    import os

    env = {**os.environ, **env_overrides}

    try:
        proc = await asyncio.create_subprocess_exec(
            "npx",
            "playwright",
            "test",
            spec_path,
            "--config=playwright.generated.config.ts",
            "--headed",
            "--reporter=list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
        )

        output_lines: list[str] = []

        async def _read_lines() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                output_lines.append(line)
                logger.debug("[%s] playwright: %s", run_id, line)
                if broadcast_fn:
                    try:
                        await broadcast_fn(line, "stdout")
                    except Exception:
                        pass

        try:
            await asyncio.wait_for(_read_lines(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error(
                "[%s] Execute node: Playwright timed out after %.0fs — killed",
                run_id,
                timeout_s,
            )
            return False, f"PLAYWRIGHT_TIMEOUT: exceeded {timeout_s}s"

        await proc.wait()
        success = proc.returncode == 0
        full_output = "\n".join(output_lines)

        if success:
            logger.info("[%s] Execute node: ✅ Playwright exited 0 (all tests passed)", run_id)
        else:
            logger.warning(
                "[%s] Execute node: ❌ Playwright exited %d", run_id, proc.returncode
            )

        return success, full_output

    except FileNotFoundError:
        msg = "npx not found — is Node.js installed and on PATH?"
        logger.error("[%s] Execute node: %s", run_id, msg)
        return False, msg


def _detect_strict_mode_collision(output: str) -> Optional[str]:
    """
    Parse Playwright output for strict-mode collision errors.

    Returns the colliding locator string, or None if not a collision.
    """
    import re

    # Standard Playwright strict-mode patterns
    patterns = [
        r"strict mode violation: locator\(['\"](.+?)['\"]\)",
        r"locator\(['\"](.+?)['\"]\).*?resolved to \d+ elements",
        r"Error: strict mode violation.*?locator\(['\"](.+?)['\"]\)",
    ]
    for pattern in patterns:
        m = re.search(pattern, output, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return None


def _detect_timing_failure(output: str) -> bool:
    """Detects if the playwright output contains standard timeout failure indicators."""
    timeout_patterns = [
        "TimeoutError",
        "waiting for selector",
        "waiting for locator",
        "Timeout 5000ms exceeded",
        "Timeout 30000ms exceeded",
        "timed out"
    ]
    for pattern in timeout_patterns:
        if pattern.lower() in output.lower():
            return True
    return False


def _detect_interaction_change(output: str) -> Optional[tuple[str, str]]:
    """
    Detects if the output indicates an element obscured, not clickable, or not found.
    Extracts the (role, name) of the failed locator if it was a getByRole locator.
    """
    interaction_patterns = [
        "not clickable",
        "obscured",
        "not visible",
        "locator not found",
        "waiting for locator"
    ]
    has_pattern = False
    for pattern in interaction_patterns:
        if pattern.lower() in output.lower():
            has_pattern = True
            break
            
    if not has_pattern:
        return None
        
    import re
    # Extract role and name from getByRole locator in the stack trace
    match = re.search(r'getByRole\(\s*\\?["\']([^"\']+)\\?["\']\s*,\s*\{\s*name:\s*\\?["\']([^"\']+)\\?["\']', output)
    if match:
        role = match.group(1).replace('\\', '')
        name = match.group(2).replace('\\', '')
        return role, name
        
    return None


# ---------------------------------------------------------------------------
# Analyze node — LLM failure translation
# ---------------------------------------------------------------------------


async def _run_analyze(
    card: dict,
    spec_content: str,
    execution_logs: str,
    tenant_id: str,
    run_id: str,
) -> str:
    """
    Analyze node: translate raw Playwright failure logs into AC-level human-readable report.

    Uses the lighter Haiku model (analysis is non-creative, low-latency preferred).
    Returns the analysis text (empty string on LLM failure).
    """
    ticket_id = card.get("ticket_id", "UNKNOWN")
    logger.info("[%s] Analyze node: translating failure logs for %s", run_id, ticket_id)

    # Load selectors for context
    tenant_selectors: dict = {}
    selectors_path = ROOT / "tenants" / tenant_id / "selectors.json"
    if selectors_path.exists():
        import json

        with open(selectors_path) as f:
            tenant_selectors = json.load(f)

    analyze_prompt = f"""You are vQA's failure analyst. A Playwright test for Jira ticket {ticket_id} failed.

Translate the raw Playwright failure output into an AC-level failure report that a QA engineer can act on.

## Acceptance Criteria
{card.get('acceptance_criteria', '')}

## BDD Steps Attempted
{chr(10).join(f'  {i+1}. {s}' for i, s in enumerate(card.get('expected_steps', [])))}

## Generated Spec Code
```typescript
{spec_content[:3000]}
```

## Playwright Failure Output
```
{execution_logs[-3000:]}
```

## Available Selectors
{', '.join(k for k in tenant_selectors if not k.startswith('_'))[:500]}

## Instructions
1. Identify WHICH acceptance criterion / BDD step failed.
2. State the ROOT CAUSE in plain English (not stack trace language).
3. Recommend ONE specific fix (selector change, timing fix, or test logic correction).
4. Keep your report under 200 words. Use bullet points. Be direct.
"""

    try:
        from langchain_core.messages import HumanMessage

        from backend.llm import get_llm

        llm = get_llm("linear_bridge_analyze", heavy=False, max_tokens=512, temperature=0.0)
        response = await llm.ainvoke([HumanMessage(content=analyze_prompt)])
        analysis = (response.content or "").strip()
        logger.info(
            "[%s] Analyze node: report generated (%d chars)", run_id, len(analysis)
        )
        return analysis
    except Exception as exc:
        logger.warning("[%s] Analyze node: LLM call failed: %s", run_id, exc)
        return f"[Analyze node unavailable: {exc}]"


# ---------------------------------------------------------------------------
# Main pipeline orchestrator
# ---------------------------------------------------------------------------


async def run_linear_pipeline(
    run_id: str,
    card: dict,
    tenant_id: str = "vpromedia",
    broadcast_fn: Optional[Callable] = None,
    timeout_s: float = 300,
) -> LinearRunResult:
    """
    Execute the full 4-node linear pipeline for a single corpus card.

    Pipeline DAG: Generate → Validate (1-retry) → Execute (1-retry) → Analyze

    Args
    ----
    run_id : str
        Unique run identifier for log correlation and WebSocket routing.
    card : dict
        A corpus card dict with keys: ticket_id, acceptance_criteria, expected_steps, summary.
    tenant_id : str
        Tenant identifier (default: "vpromedia").
    broadcast_fn : callable | None
        Async function signature: ``async (line: str, stream: str) -> None``.
        Called for every log line to stream to connected WebSocket clients.
    timeout_s : float
        Hard wall-clock timeout for the entire pipeline. Default: 300s (5 minutes).

    Returns
    -------
    LinearRunResult
    """
    ticket_id = card.get("ticket_id", "UNKNOWN")
    t0 = time.perf_counter()

    async def _emit(message: str, stream: str = "stdout") -> None:
        """Emit a structured log line to the broadcast function and Python logger."""
        logger.info("[%s] linear_pipeline [%s]: %s", run_id, ticket_id, message)
        if broadcast_fn:
            try:
                await broadcast_fn(message, stream)
            except Exception:
                pass

    await _emit(f"=== LINEAR PIPELINE START: {ticket_id} ===")

    try:
        result = await asyncio.wait_for(
            _run_pipeline_inner(
                run_id=run_id,
                card=card,
                tenant_id=tenant_id,
                ticket_id=ticket_id,
                emit=_emit,
            ),
            timeout=timeout_s,
        )
        result.elapsed_s = round(time.perf_counter() - t0, 2)
        await _emit(
            f"=== LINEAR PIPELINE END: {ticket_id} | status={result.status} | "
            f"pipeline={result.pipeline_status} | elapsed={result.elapsed_s}s ==="
        )
        return result

    except asyncio.TimeoutError:
        elapsed = round(time.perf_counter() - t0, 2)
        await _emit(
            f"=== LINEAR PIPELINE TIMEOUT: {ticket_id} after {elapsed}s ===", "stderr"
        )
        return LinearRunResult(
            status="timeout",
            pipeline_status="PIPELINE_TIMEOUT",
            ticket_id=ticket_id,
            elapsed_s=elapsed,
            error=f"Pipeline exceeded {timeout_s}s hard timeout.",
        )

    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        logger.exception("[%s] linear_pipeline: unexpected exception for %s", run_id, ticket_id)
        await _emit(f"PIPELINE_ERROR: {type(exc).__name__}: {exc}", "stderr")
        return LinearRunResult(
            status="error",
            pipeline_status="PIPELINE_ERROR",
            ticket_id=ticket_id,
            elapsed_s=elapsed,
            error=str(exc),
        )


async def _run_pipeline_inner(
    run_id: str,
    card: dict,
    tenant_id: str,
    ticket_id: str,
    emit: Callable,
) -> LinearRunResult:
    """
    Inner pipeline execution (no timeout wrapper — handled by run_linear_pipeline).
    Separated so asyncio.wait_for wraps the entire DAG cleanly.
    """
    # ── Node 0: REPLAY CHECK ─────────────────────────────────────────────────
    from backend.storage.accepted_test_store import get_accepted_test_store
    from backend.engine.replay_engine import ReplayEngine

    store = get_accepted_test_store()
    record = store.load(ticket_id=ticket_id, ac_steps=card.get("expected_steps", []))
    if record and record.get("replay_actions"):
        await emit(f"[Replay] Found accepted test for {ticket_id} — replaying {len(record['replay_actions'])} actions")
        engine = ReplayEngine(run_id=run_id)
        state = {
            "jira_ticket": {
                **card,
                "acceptance_criteria_steps": card.get("expected_steps", []),
            },
            "detailed_execution_log": [],
        }
        replay_result = await engine.replay(state)
        if replay_result.get("replay_succeeded"):
            await emit(f"[Replay] ✅ Smart Replay succeeded for {ticket_id}!")
            return LinearRunResult(
                status="completed",
                pipeline_status="SUCCESS",
                ticket_id=ticket_id,
            )
        await emit("[Replay] ⚠️ Replay failed — falling through to generation pipeline")

    # ── Node 1: GENERATE ─────────────────────────────────────────────────────
    await emit(f"[Generate] Calling LLM to generate Playwright spec for {ticket_id}...")

    try:
        from backend.engine.generator_node import generate_spec

        gen_result = await generate_spec(card, tenant_id=tenant_id)
    except Exception as exc:
        await emit(f"[Generate] FAILED: {exc}", "stderr")
        return LinearRunResult(
            status="failed",
            pipeline_status="GENERATION_FAILED",
            ticket_id=ticket_id,
            error=str(exc),
        )

    if gen_result.get("status") != "generated":
        err = gen_result.get("error", "Unknown generation error")
        await emit(f"[Generate] FAILED: {err}", "stderr")
        return LinearRunResult(
            status="failed",
            pipeline_status="GENERATION_FAILED",
            ticket_id=ticket_id,
            error=err,
        )

    spec_path = gen_result["spec_path"]
    spec_content = gen_result.get("spec_content", "")
    await emit(f"[Generate] ✅ Spec written to {pathlib.Path(spec_path).name}")

    # ── Node 2: VALIDATE (1-retry ceiling) ───────────────────────────────────
    await emit(f"[Validate] Compiling {pathlib.Path(spec_path).name} with tsc --noEmit...")

    try:
        from backend.engine.validator_node import validate_spec

        val_result = await validate_spec(gen_result, card, tenant_id=tenant_id)
    except Exception as exc:
        await emit(f"[Validate] CRASHED: {exc}", "stderr")
        return LinearRunResult(
            status="failed",
            pipeline_status="COMPILE_FAILED",
            ticket_id=ticket_id,
            spec_path=spec_path,
            error=str(exc),
        )

    compile_attempts = val_result.get("attempts", 0)

    if val_result.get("status") != "COMPILE_OK":
        compile_error = val_result.get("compile_error", "")
        await emit(
            f"[Validate] ❌ COMPILE_FAILED after {compile_attempts} attempt(s). "
            f"Escalating to human code reviewer.",
            "stderr",
        )
        await emit(f"[Validate] Error summary: {compile_error[:400]}", "stderr")
        return LinearRunResult(
            status="failed",
            pipeline_status="COMPILE_FAILED",
            ticket_id=ticket_id,
            spec_path=spec_path,
            compile_attempts=compile_attempts,
            error=compile_error,
        )

    await emit(
        f"[Validate] ✅ Compilation succeeded (attempt {compile_attempts}). "
        f"Selector schema validated."
    )

    # Re-read spec content in case the validator auto-fixed it
    spec_path_obj = pathlib.Path(spec_path)
    if spec_path_obj.exists():
        spec_content = spec_path_obj.read_text(encoding="utf-8")

    # ── Node 3: EXECUTE (with Self-Healing and Retry Loop — AC-8) ────────────
    await emit(f"[Execute] Running {pathlib.Path(spec_path).name} via Playwright...")

    max_retries = 3
    attempt = 1
    success = False
    exec_output = ""
    collision_locator = None
    applied_healing = False

    while attempt <= max_retries:
        if attempt > 1:
            await emit(f"[Execute] Re-running spec (attempt {attempt}/{max_retries})...")

        success, exec_output = await _run_playwright_spec(
            spec_path=spec_path,
            run_id=run_id,
            tenant_id=tenant_id,
            broadcast_fn=emit,
        )

        if success:
            healed_msg = " with self-healing" if attempt > 1 else ""
            await emit(f"[Execute] ✅ Execution completed successfully{healed_msg} on attempt {attempt}.")
            return LinearRunResult(
                status="completed",
                pipeline_status="SUCCESS",
                ticket_id=ticket_id,
                spec_path=spec_path,
                compile_attempts=compile_attempts,
            )

        # 1. Check for Strict-Mode Collision
        collision_locator = _detect_strict_mode_collision(exec_output)
        if collision_locator and attempt < max_retries:
            await emit(
                f"[Execute] ⚠ Strict-mode collision on locator '{collision_locator}'. "
                f"Requesting parent-scoped correction from LLM...",
            )
            try:
                corrected_spec = await _request_strict_mode_fix(
                    locator=collision_locator,
                    card=card,
                    spec_content=spec_content,
                    exec_output=exec_output,
                    run_id=run_id,
                )
                spec_path_obj.write_text(corrected_spec, encoding="utf-8")
                spec_content = corrected_spec
                attempt += 1
                applied_healing = True
                continue
            except Exception as exc:
                await emit(f"[Execute] Collision correction failed: {exc}", "stderr")

        # 2. Check for Timing Failure (Category 2)
        elif _detect_timing_failure(exec_output) and attempt < max_retries:
            await emit(
                f"[Execute] ⚠ Timing/load failure (Category 2) detected. "
                f"Applying incremental delay (3000ms) before retry...",
            )
            await asyncio.sleep(3.0)
            attempt += 1
            applied_healing = True
            continue

        # 3. Check for Interaction Change / Element Shift (Category 6)
        else:
            interaction_info = _detect_interaction_change(exec_output)
            if interaction_info and attempt < max_retries:
                role, name = interaction_info
                await emit(
                    f"[Execute] ⚠ Interaction shift (Category 6) detected on role='{role}', name='{name}'. "
                    f"Initiating A11y-powered self-healing...",
                )
                
                a11y_elements = card.get("a11y_elements", [])
                best_locator = None
                best_score = 0.0
                from difflib import SequenceMatcher
                
                for cand in a11y_elements:
                    if cand["role"] == role:
                        score = SequenceMatcher(None, name.lower(), cand["name"].lower()).ratio()
                        # Prefix boost (Jaro-Winkler equivalent for prefix matches, e.g. "Save" vs "Save Changes")
                        if cand["name"].lower().startswith(name.lower()) or name.lower().startswith(cand["name"].lower()):
                            score = max(score, 0.85)
                        elif name.lower() in cand["name"].lower() or cand["name"].lower() in name.lower():
                            score = max(score, 0.75)
                            
                        if score > best_score:
                            best_score = score
                            best_locator = cand
                            
                if best_score >= 0.70 and best_locator:
                    healed_locator = best_locator["locator"]
                    await emit(
                        f"[Execute] 🛠 Self-healing found alternative locator with {best_score:.2%} match similarity: "
                        f"'{healed_locator}'. Rewriting spec file inline...",
                    )
                    
                    import re
                    # Replace page.getByRole("role", {"name": "old_name"}) with the healed locator in spec_content
                    pattern = re.compile(
                        r'page\.getByRole\(\s*["\']' + re.escape(role) + r'["\']\s*,\s*\{\s*name:\s*["\']' + re.escape(name) + r'["\']\s*\}\s*\)'
                    )
                    
                    new_spec_content = pattern.sub(healed_locator, spec_content)
                    if new_spec_content == spec_content:
                        # Fallback simple replacement
                        old_locator_str = f'page.getByRole("{role}", {{"name": "{name}"}})'
                        new_spec_content = spec_content.replace(old_locator_str, healed_locator)
                        
                    if new_spec_content != spec_content:
                        spec_path_obj.write_text(new_spec_content, encoding="utf-8")
                        spec_content = new_spec_content
                        attempt += 1
                        applied_healing = True
                        continue
                    else:
                        await emit("[Execute] ❌ Failed to rewrite locator in spec content string.", "stderr")
                else:
                    await emit(
                        f"[Execute] ❌ Self-healing similarity check failed (best score {best_score:.2%} < 70%). "
                        f"No suitable alternative found in dynamic locators.",
                        "stderr",
                    )

        # No healing or retry strategy was applied/succeeded, or we reached max_retries
        break

    # ── Node 4: ANALYZE — translate failure to human-readable AC report ──────
    await emit(f"[Analyze] Translating execution failure for {ticket_id}...")
    analysis = await _run_analyze(
        card=card,
        spec_content=spec_content,
        execution_logs=exec_output,
        tenant_id=tenant_id,
        run_id=run_id,
    )
    await emit(f"[Analyze] Failure report: {analysis}")

    non_collision_msg = (
        f"[Execute] ❌ EXECUTE_FAILED (persistent strict-mode collision on '{collision_locator}'). Escalating to human code reviewer."
        if collision_locator
        else "[Execute] ❌ EXECUTE_FAILED (runtime error after self-healing attempts). Escalating to human code reviewer."
    )
    await emit(non_collision_msg, "stderr")

    return LinearRunResult(
        status="failed",
        pipeline_status="EXECUTE_FAILED",
        ticket_id=ticket_id,
        spec_path=spec_path,
        compile_attempts=compile_attempts,
        analysis=analysis,
        error=exec_output[-1000:],  # last 1000 chars of playwright output
    )


async def _request_strict_mode_fix(
    locator: str,
    card: dict,
    spec_content: str,
    exec_output: str,
    run_id: str,
) -> str:
    """
    Call the LLM to produce a parent-scoped correction for a strict-mode collision.
    One call, no retry — per the TASK-105 spec AC-4 constraint.
    """
    fix_prompt = f"""A Playwright spec failed with a strict-mode collision.

Locator that resolved to multiple elements: '{locator}'

Fix this by scoping the locator to the most specific parent container.
Do NOT change the test logic — only fix the ambiguous locator.

## Failing Spec
```typescript
{spec_content[:4000]}
```

## Playwright Error Output
```
{exec_output[-1500:]}
```

## BDD Context
{chr(10).join(f'  {i+1}. {s}' for i, s in enumerate(card.get('expected_steps', []))[:10])}

Output ONLY the corrected TypeScript. No markdown fences. No explanation.
"""

    from langchain_core.messages import HumanMessage

    from backend.engine.generator_node import _SYSTEM_PROMPT
    from backend.llm import get_llm

    llm = get_llm("linear_bridge_fix", heavy=True, max_tokens=2048, temperature=0.0)
    response = await llm.ainvoke([HumanMessage(content=fix_prompt)])
    fixed = (response.content or "").strip()

    # Strip markdown fences
    if fixed.startswith("```"):
        lines = fixed.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        fixed = "\n".join(lines[start:end]).strip()

    return fixed
