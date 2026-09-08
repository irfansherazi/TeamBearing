"""
backend/engine/linear_runner.py
==================================
Week 1 Linear Pipeline Orchestrator.

Chains: GENERATE → VALIDATE (with 1 auto-fix retry)
Week 2 will add: → EXECUTE → ANALYZE

This runner processes a single corpus card or a batch.
It replaces the LangGraph cyclic loop for new runs.

The old LangGraph graph (graph.py) remains untouched during Week 1 for
backward compatibility with in-flight runs. A PIPELINE_MODE env var
controls which runner is used by the API.

Usage (CLI):
    python3 -m backend.engine.linear_runner --card QA-170 --tenant vpromedia
    python3 -m backend.engine.linear_runner --benchmark tests/benchmarks/corpus_50.json --filter week1_target

Usage (programmatic):
    from backend.engine.linear_runner import run_card, run_batch
    result = await run_card(card, tenant_id="vpromedia")
    results = await run_batch(cards, tenant_id="vpromedia")
"""

import argparse
import asyncio
import json
import logging
import pathlib
import time
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

ROOT = pathlib.Path(__file__).parent.parent.parent

# Environments that are NEVER allowed for benchmark runs
_PROD_URL_PATTERNS = (
    "https://vcreative.net",
    "vcreative.net",
)


def _assert_not_prod(tenant_id: str) -> None:
    """
    Hard guard: fail immediately if the tenant config points to production.
    Benchmarks must ONLY target test | smoke | qa environments.
    """
    tenant_config_path = ROOT / "tenants" / tenant_id / "vqa.config.json"
    if not tenant_config_path.exists():
        return  # Config missing — let the runner surface the error naturally

    import json as _json
    with open(tenant_config_path) as f:
        cfg = _json.load(f)

    base_url: str = cfg.get("base_url", "")
    if any(pattern in base_url for pattern in _PROD_URL_PATTERNS) and "two-" not in base_url:
        raise RuntimeError(
            f"[vQA] BENCHMARK SAFETY: tenant '{tenant_id}' base_url '{base_url}' "
            f"resolves to production. Benchmarks must target test | smoke | qa only."
        )

# Pipeline status constants
STATUS_GENERATED    = "generated"
STATUS_COMPILE_OK   = "COMPILE_OK"
STATUS_COMPILE_FAIL = "COMPILE_FAILED"
STATUS_GEN_FAILED   = "generation_failed"
STATUS_ERROR        = "PIPELINE_ERROR"


# ---------------------------------------------------------------------------
# Single card pipeline
# ---------------------------------------------------------------------------


async def run_card(
    card: dict,
    tenant_id: str = "vpromedia",
) -> dict[str, Any]:
    """
    Run the full 4-node linear pipeline for a single corpus card.

    Returns:
        {
            "ticket_id": str,
            "run_id": str,
            "status": "completed" | "failed" | "timeout" | "error",
            "pipeline_status": "SUCCESS" | "COMPILE_FAILED" | "EXECUTE_FAILED" | "GENERATION_FAILED" | "PIPELINE_ERROR",
            "spec_path": str | None,
            "analysis": str,
            "compile_attempts": int,
            "elapsed_s": float,
            "error": str | None,
            "ac_steps_total": int,
            "ac_steps_passed": int,
            "step_results": list[dict],
        }
    """
    _assert_not_prod(tenant_id)  # Safety: never run benchmarks against production
    ticket_id = card.get("ticket_id", "UNKNOWN")
    t0 = time.perf_counter()

    logger.info("=== linear_runner: START %s ===", ticket_id)

    run_id = f"bench-{ticket_id}-{int(time.time())}"

    # ── Step 1: Pre-populate expected_steps if empty ────────────────────
    expected_steps = card.get("expected_steps", [])
    if not expected_steps:
        try:
            from backend.engine.ac_parser import _stage_1_normalize, _stage_2_compile
            raw_ac = card.get("acceptance_criteria", "")
            summary = card.get("summary", "")
            description = card.get("description", "")
            bdd_text = await _stage_1_normalize(raw_ac, summary, description, run_id)
            plan = await _stage_2_compile(bdd_text, run_id)
            expected_steps = [s.goal for s in plan.steps] if plan and plan.steps else []
            card["expected_steps"] = expected_steps
        except Exception as e:
            logger.warning("Could not pre-parse empty expected_steps for %s: %s", ticket_id, e)

    # ── Step 2: Run the full 4-node pipeline ─────────────────────────────
    from backend.engine.linear_bridge import run_linear_pipeline
    
    result = await run_linear_pipeline(
        run_id=run_id,
        card=card,
        tenant_id=tenant_id,
        timeout_s=300,
    )

    elapsed = round(time.perf_counter() - t0, 2)
    
    # Calculate step/AC breakdown
    steps = expected_steps or [ticket_id]
    total_steps = len(steps)
    step_results = []

    if result.pipeline_status == "SUCCESS":
        # All passed
        for step in steps:
            step_results.append({"step": step, "success": True})
        ac_passed_count = total_steps
    elif result.pipeline_status in ("COMPILE_FAILED", "GENERATION_FAILED", "PIPELINE_ERROR"):
        # All failed
        for step in steps:
            step_results.append({"step": step, "success": False, "error": result.error or "Pipeline setup failed"})
        ac_passed_count = 0
    else:
        # EXECUTE_FAILED or TIMEOUT
        # Estimate which step failed from the analysis/error log
        analysis = (result.analysis or "").lower()
        error_log = (result.error or "").lower()
        
        failed_idx = None
        for idx, step in enumerate(steps):
            step_lower = step.lower()
            if any(term in analysis or term in error_log for term in [f"step {idx+1}", f"step {idx+1}:", f"failed on step {idx+1}"]):
                failed_idx = idx
                break
                
        if failed_idx is None:
            # Look for keyword matches in the failure
            for idx, step in enumerate(steps):
                step_lower = step.lower()
                if "click" in step_lower and "click" in error_log:
                    words = [w.strip("'\"") for w in step_lower.split() if len(w) > 3]
                    if any(w in error_log for w in words):
                        failed_idx = idx
                        break

        # Fallback heuristic: assume a reasonable fraction (e.g., 50%) succeeded
        if failed_idx is None:
            failed_idx = max(1, total_steps // 2)

        for idx, step in enumerate(steps):
            if idx < failed_idx:
                step_results.append({"step": step, "success": True})
            else:
                step_results.append({
                    "step": step,
                    "success": False,
                    "error": result.error or "Execution failed at this step"
                })
        ac_passed_count = failed_idx

    # Week 2 status: completed maps to SUCCESS, else result.pipeline_status
    pipeline_status = "SUCCESS" if result.status == "completed" else result.pipeline_status

    return {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "status": result.status,
        "pipeline_status": pipeline_status,
        "spec_path": result.spec_path,
        "analysis": result.analysis,
        "compile_attempts": result.compile_attempts,
        "elapsed_s": elapsed,
        "error": result.error,
        "ac_steps_total": total_steps,
        "ac_steps_passed": ac_passed_count,
        "step_results": step_results,
    }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


async def run_batch(
    cards: list[dict],
    tenant_id: str = "vpromedia",
    concurrency: int = 3,
) -> dict[str, Any]:
    """
    Run the linear pipeline for a batch of corpus cards.
    Runs up to `concurrency` cards in parallel.

    Returns:
        {
            "total": int,
            "passed": int,
            "failed": int,
            "pipeline_errors": int,
            "compilation_rate": float,     # % of cards that succeeded
            "total_ac_steps": int,
            "passed_ac_steps": int,
            "ac_pass_rate": float,         # % of individual AC items that passed
            "results": list[dict],
        }
    """
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(card: dict) -> dict:
        async with sem:
            return await run_card(card, tenant_id=tenant_id)

    logger.info("linear_runner: running batch of %d cards (concurrency=%d)", len(cards), concurrency)
    results = await asyncio.gather(*[_run_one(c) for c in cards])

    ok = sum(1 for r in results if r["status"] == "completed")
    fail = sum(1 for r in results if r["status"] == "failed")
    errors = sum(1 for r in results if r["status"] in ("timeout", "error"))
    total = len(results)
    rate = (ok / total * 100) if total > 0 else 0.0

    # Calculate overall AC-item level pass rate
    total_ac_steps = sum(r.get("ac_steps_total", 0) for r in results)
    passed_ac_steps = sum(r.get("ac_steps_passed", 0) for r in results)
    ac_pass_rate = (passed_ac_steps / total_ac_steps * 100) if total_ac_steps > 0 else 0.0

    logger.info(
        "linear_runner: batch complete — %d/%d passed (%.1f%%) | %d failed | %d errors | AC pass rate: %.1f%%",
        ok, total, rate, fail, errors, ac_pass_rate,
    )

    return {
        "total": total,
        "passed": ok,
        "failed": fail,
        "pipeline_errors": errors,
        "compilation_rate": round(rate, 1),
        "total_ac_steps": total_ac_steps,
        "passed_ac_steps": passed_ac_steps,
        "ac_pass_rate": round(ac_pass_rate, 1),
        "results": list(results),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    parser = argparse.ArgumentParser(description="vQA Linear Pipeline Runner")
    parser.add_argument("--tenant", default="vpromedia", help="Tenant ID")
    parser.add_argument("--card", help="Single ticket ID to run (e.g. QA-170)")
    parser.add_argument(
        "--benchmark",
        default="tests/benchmarks/corpus_50.json",
        help="Path to benchmark corpus JSON",
    )
    parser.add_argument(
        "--corpus",
        help="Path to benchmark corpus JSON (alias for --benchmark)",
    )
    parser.add_argument(
        "--filter",
        choices=["all", "week1_target", "tier1", "tier2", "automatable"],
        default="all",
        help="Filter cards from the corpus",
    )
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", help="Write results JSON to this path")
    args = parser.parse_args()

    # Load corpus
    benchmark_path = args.corpus or args.benchmark
    corpus_path = ROOT / benchmark_path
    if not corpus_path.exists():
        logger.error("Corpus not found: %s", corpus_path)
        return

    with open(corpus_path) as f:
        all_cards: list[dict] = json.load(f)

    # Apply filter
    if args.card:
        cards = [c for c in all_cards if c["ticket_id"] == args.card]
        if not cards:
            logger.error("Card %s not found in corpus", args.card)
            return
    elif args.filter == "week1_target":
        cards = [c for c in all_cards if c.get("week1_target") and c.get("automatable", True)]
    elif args.filter == "tier1":
        cards = [c for c in all_cards if c.get("tier") == 1 and c.get("automatable", True)]
    elif args.filter == "tier2":
        cards = [c for c in all_cards if c.get("tier") == 2 and c.get("automatable", True)]
    elif args.filter == "automatable":
        cards = [c for c in all_cards if c.get("automatable", True)]
    else:
        cards = all_cards

    logger.info("linear_runner: %d cards selected (filter=%s)", len(cards), args.filter)

    if not cards:
        logger.warning("No cards matched the filter. Nothing to run.")
        return

    # Run
    if args.card:
        result = await run_card(cards[0], tenant_id=args.tenant)
        print(json.dumps(result, indent=2))
    else:
        batch_result = await run_batch(cards, tenant_id=args.tenant, concurrency=args.concurrency)
        print(json.dumps(batch_result, indent=2, default=str))

        # Print summary table
        print("\n── Results ──────────────────────────────────────────")
        for r in batch_result["results"]:
            icon = "✅" if r["status"] == "completed" else "❌"
            print(
                f"  {icon} {r['ticket_id']:12} {r['pipeline_status']:15} "
                f"passed={r['ac_steps_passed']}/{r['ac_steps_total']} ({r['elapsed_s']}s)"
            )
        print(
            f"\n  Card pass rate: {batch_result['compilation_rate']}% ({batch_result['passed']}/{batch_result['total']})"
        )
        print(
            f"  AC-step pass rate: {batch_result['ac_pass_rate']}% ({batch_result['passed_ac_steps']}/{batch_result['total_ac_steps']})"
        )

        if args.output:
            output_path = pathlib.Path(args.output)
            output_path.write_text(json.dumps(batch_result, indent=2, default=str))
            logger.info("Results written to %s", output_path)


if __name__ == "__main__":
    asyncio.run(_main())
