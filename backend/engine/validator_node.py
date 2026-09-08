"""
backend/engine/validator_node.py
==================================
Week 1 Linear Pipeline — Step 2: VALIDATE

Runs `npx tsc --noEmit` on a generated .spec.ts file.
If compilation fails, feeds the error back to the generator for exactly
ONE auto-fix attempt, then halts with COMPILE_FAILED if the retry also fails.

Design decisions (per TASK-101 spec §2, Step 2):
  - TypeScript errors caught here include: missing imports, unknown selector keys,
    wrong function signatures, type mismatches.
  - The TenantSelectorKey union type (from generate_selectors_types.py) ensures
    hallucinated selector keys surface as TS2345 at this stage — not at runtime.
  - Only ONE retry is allowed. If the second compile fails, the pipeline halts.
    Infinite loops are explicitly prevented.
"""

import asyncio
import json
import logging
import pathlib
import re
import subprocess
from typing import Any


logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).parent.parent.parent
TSCONFIG = ROOT / "playwright" / "tsconfig.json"


# ---------------------------------------------------------------------------
# TypeScript compilation runner
# ---------------------------------------------------------------------------


TSCONFIG_GENERATED = ROOT / "playwright" / "tsconfig.generated.json"


def _run_tsc(spec_path: pathlib.Path) -> tuple[bool, str]:
    """
    Run `tsc --noEmit` on the given spec file.

    Dynamically updates the `files` array in tsconfig.generated.json to
    include only the target spec + selector types. This isolates validation
    from pre-existing TypeScript errors in the shared utils.

    Returns:
        (success: bool, error_output: str)
    """
    # Dynamically inject this spec into the files array
    with open(TSCONFIG_GENERATED) as f:
        tsconfig = json.load(f)

    # Files paths are relative to playwright/ (where tsconfig lives)
    playwright_dir = ROOT / "playwright"
    spec_rel = spec_path.relative_to(playwright_dir)
    tenant_id = "vpromedia"  # TODO: pass as arg when multi-tenant

    tsconfig["files"] = [
        str(spec_rel).replace("\\", "/"),                     # generated spec
        f"utils/generated/{tenant_id}_selectors.ts",          # typed selector keys
    ]

    with open(TSCONFIG_GENERATED, "w") as f:
        json.dump(tsconfig, f, indent=2)

    # Use local tsc binary (installed as devDependency)
    tsc_bin = ROOT / "node_modules" / ".bin" / "tsc"
    if not tsc_bin.exists():
        tsc_bin = ROOT / "frontend" / "node_modules" / ".bin" / "tsc"
    if not tsc_bin.exists():
        return False, "tsc binary not found. Run: npm install --save-dev typescript"

    result = subprocess.run(
        [str(tsc_bin), "--noEmit", "--project", str(TSCONFIG_GENERATED)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=60,
    )
    success = result.returncode == 0
    error_output = (result.stdout + result.stderr).strip()

    # Filter output to only lines relevant to this spec file
    if not success and error_output:
        spec_name = spec_path.name
        relevant_lines = [
            line for line in error_output.splitlines()
            if spec_name in line or "error TS" in line
        ]
        if relevant_lines:
            error_output = "\n".join(relevant_lines)

    return success, error_output



# ---------------------------------------------------------------------------
# Correction prompt builder (per spec §2, Q11 template)
# ---------------------------------------------------------------------------


def _build_correction_prompt(
    original_prompt: str,
    spec_content: str,
    compiler_error: str,
) -> str:
    """Build the structured correction prompt for the auto-fix retry."""
    # Extract specific TS error codes for cleaner feedback
    error_codes = re.findall(r"TS\d+", compiler_error)
    unique_errors = list(dict.fromkeys(error_codes))

    return f"""The previously generated TypeScript file failed compilation.

## Compiler Errors
```
{compiler_error}
```

## Error Codes Detected
{', '.join(unique_errors) if unique_errors else 'See above'}

## Failed File Content
```typescript
{spec_content}
```

## Fix Instructions
1. Correct ALL TypeScript errors shown above.
2. If a selector key is invalid (TS2345), use ONLY keys from TenantSelectorKey union.
3. If an import is missing, add it.
4. Do NOT change the test logic — only fix compilation errors.
5. Output ONLY the corrected TypeScript. No markdown fences.

Generate the corrected .spec.ts file now:"""


# ---------------------------------------------------------------------------
# Validator node
# ---------------------------------------------------------------------------


async def validate_spec(
    generate_result: dict[str, Any],
    card: dict,
    tenant_id: str = "vpromedia",
) -> dict[str, Any]:
    """
    Validate a generated .spec.ts file using `tsc --noEmit`.

    Allows exactly ONE auto-fix retry on compilation failure.
    Halts with status='COMPILE_FAILED' if the retry also fails.

    Args:
        generate_result: Output from generator_node.generate_spec()
        card:            The original corpus card (for retry context)
        tenant_id:       Tenant identifier

    Returns:
        {
            "ticket_id": str,
            "spec_path": str,
            "status": "COMPILE_OK" | "COMPILE_FAILED" | "VALIDATION_ERROR",
            "attempts": int,                    # 1 or 2
            "compile_error": str | None,        # Final error if COMPILE_FAILED
        }
    """
    ticket_id = generate_result.get("ticket_id", "UNKNOWN")
    spec_path_str = generate_result.get("spec_path")

    if not spec_path_str or generate_result.get("status") != "generated":
        logger.error("validator_node: cannot validate — generation did not succeed for %s", ticket_id)
        return {
            "ticket_id": ticket_id,
            "spec_path": spec_path_str,
            "status": "VALIDATION_ERROR",
            "attempts": 0,
            "compile_error": "Generator did not produce a spec file.",
        }

    spec_path = pathlib.Path(spec_path_str)

    # ── Attempt 1: Compile ────────────────────────────────────────────────
    logger.info("validator_node: compiling %s (attempt 1)", spec_path.name)
    success, error_output = _run_tsc(spec_path)

    if success:
        logger.info("validator_node: ✅ %s compiled successfully (attempt 1)", ticket_id)
        return {
            "ticket_id": ticket_id,
            "spec_path": spec_path_str,
            "status": "COMPILE_OK",
            "attempts": 1,
            "compile_error": None,
        }

    logger.warning(
        "validator_node: ❌ %s compile failed (attempt 1). Errors:\n%s",
        ticket_id,
        error_output[:500],
    )

    # ── Attempt 2: Auto-fix retry ─────────────────────────────────────────
    logger.info("validator_node: requesting auto-fix for %s (attempt 2)...", ticket_id)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from backend.engine.generator_node import _SYSTEM_PROMPT, _build_prompt
        from backend.llm import get_llm

        tenant_context_for_retry: dict = {}
        try:
            from backend.engine.generator_node import _load_tenant_context
            tenant_context_for_retry = _load_tenant_context(tenant_id)
        except Exception:
            pass

        _, original_user_prompt = _build_prompt(card, tenant_context_for_retry)
        correction_prompt = _build_correction_prompt(
            original_user_prompt,
            generate_result.get("spec_content", ""),
            error_output,
        )

        llm = get_llm("validator_node_retry", heavy=True, max_tokens=2048, temperature=0.1)
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=correction_prompt),
        ])
        fixed_content = (response.content or "").strip()

        # Strip markdown fences
        if fixed_content.startswith("```"):
            lines = fixed_content.splitlines()
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            fixed_content = "\n".join(lines[start:end]).strip()

        spec_path.write_text(fixed_content, encoding="utf-8")
        logger.info("validator_node: auto-fix written, re-compiling...")

    except Exception as exc:
        logger.error("validator_node: auto-fix LLM call failed: %s", exc)
        return {
            "ticket_id": ticket_id,
            "spec_path": spec_path_str,
            "status": "COMPILE_FAILED",
            "attempts": 1,
            "compile_error": error_output,
        }

    # ── Compile again after fix ───────────────────────────────────────────
    success2, error_output2 = _run_tsc(spec_path)

    if success2:
        logger.info("validator_node: ✅ %s compiled successfully (attempt 2)", ticket_id)
        return {
            "ticket_id": ticket_id,
            "spec_path": spec_path_str,
            "status": "COMPILE_OK",
            "attempts": 2,
            "compile_error": None,
        }

    # Both attempts failed — halt (per spec: no third attempt)
    logger.error(
        "validator_node: ❌ %s COMPILE_FAILED after 2 attempts. Final errors:\n%s",
        ticket_id,
        error_output2[:500],
    )
    return {
        "ticket_id": ticket_id,
        "spec_path": spec_path_str,
        "status": "COMPILE_FAILED",
        "attempts": 2,
        "compile_error": error_output2,
    }
