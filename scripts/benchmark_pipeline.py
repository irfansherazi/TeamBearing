#!/usr/bin/env python3
"""
vQA Pipeline Benchmark — Parser & E2E Execution
================================================
Benchmarks the full pipeline: Jira -> BDD -> JSON Plan -> Playwright Execution.
Uses the "Golden 10" set to establish baseline accuracy.

Usage:
    python scripts/benchmark_pipeline.py [--full]
"""

import argparse
import asyncio
import difflib
import json
import logging
import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.config import settings
from backend.engine.ac_parser import ac_parser_node
from backend.engine.graph_orchestrator import build_orchestrator_graph, make_orchestrator_state
from backend.engine.state import make_initial_state

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK_DATA_PATH = os.path.join(PROJECT_ROOT, "tests/benchmarks/golden_10_data.json")

# Component categorization for reporting (TASK-013)
COMPONENT_MAP = {
    "dropdown": ["dropdown", "select", "p-dropdown", "p-select"],
    "multiselect": ["p-multiselect", "multi-select"],
    "calendar": ["p-calendar", "date", "calendar"],
    "table": ["p-table", "grid", "column", "sort"],
    "upload": ["upload", "file", "attach"],
    "toast": ["toast", "message", "notification"],
}


async def run_benchmark(full_execution: bool = False, limit: int = 0, report_path: str = ""):
    if not os.path.exists(BENCHMARK_DATA_PATH):
        print(f"Error: Benchmark data not found at {BENCHMARK_DATA_PATH}")
        sys.exit(1)

    with open(BENCHMARK_DATA_PATH, "r") as f:
        cards = json.load(f)

    if limit > 0:
        cards = cards[:limit]

    results = []
    total_cards = len(cards)
    parser_passed = 0
    execution_passed = 0
    total_steps_executed = 0
    total_steps_verified = 0

    print(f"\n🚀 Starting Pipeline Benchmark on {total_cards} cards (Full Execution: {full_execution})...\n")

    graph = build_orchestrator_graph() if full_execution else None

    for card in cards:
        ticket_id = card["ticket_id"]
        print(f"--- Benchmarking {ticket_id}: {card['summary']} ---")

        # Prepare state
        card_role = card.get("role", "account_executive")
        state = make_initial_state(
            run_id=f"bench-{ticket_id}",
            jira_ticket_id=ticket_id,
            role=card_role,
            target_url=settings.target_url,
            mode="headless",
        )
        state["jira_ticket"] = {
            "ticket_id": ticket_id,
            "summary": card["summary"],
            "description": card["description"],
            "acceptance_criteria": card["acceptance_criteria"],
        }

        try:
            # Stage 1: Run the parser node (Jira -> Steps)
            parsed_state = await ac_parser_node(state)

            # Extract results
            updated_ticket = parsed_state.get("jira_ticket", {})
            actual_steps = updated_ticket.get("acceptance_criteria_steps", [])
            quality_result = parsed_state.get("ac_quality_result", {})

            # ── Metrics ──────────────────────────────────────────────────
            parser_success = len(actual_steps) > 0
            quality_score = quality_result.get("score", 0)

            # Calculate step coverage (fuzzy match)
            matched_steps = 0
            expected_steps = card.get("expected_steps", [])
            for exp in expected_steps:
                exp_lower = exp.lower()
                if any(difflib.SequenceMatcher(None, exp_lower, act.lower()).ratio() > 0.8 for act in actual_steps):
                    matched_steps += 1

            coverage = (matched_steps / len(expected_steps)) if expected_steps else 0

            card_execution_success = False
            step_results = []

            if parser_success:
                parser_passed += 1
                print(f"  ✅ Parser Success: {len(actual_steps)} steps. Coverage: {coverage:.0%}")

                # Stage 2: Full Execution (if requested)
                if full_execution:
                    print(f"  🏃 Starting E2E Execution for {len(actual_steps)} steps...")
                    card_steps_verified = 0

                    for i, step_text in enumerate(actual_steps):
                        print(f"    Step {i + 1}: {step_text[:80]}...")
                        orch_state = make_orchestrator_state(
                            ac_step=step_text,
                            run_id=f"bench-{ticket_id}-step-{i + 1}",
                            ticket_id=ticket_id,
                            role_name=card_role,
                        )

                        try:
                            # Run the orchestrator loop for this step
                            step_out = await graph.ainvoke(orch_state)
                            is_verified = step_out.get("verification_result", {}).get("is_verified", False)

                            step_results.append(
                                {"step": step_text, "success": is_verified, "error": step_out.get("error_log", "")}
                            )

                            if is_verified:
                                card_steps_verified += 1
                                print("      ✅ PASS")
                            else:
                                print(
                                    f"      ❌ FAIL: {step_out.get('verification_result', {}).get('failure_reason', 'Unknown error')}"
                                )
                        except Exception as step_err:
                            print(f"      💥 CRASH: {str(step_err)}")
                            step_results.append({"step": step_text, "success": False, "error": str(step_err)})

                    total_steps_executed += len(actual_steps)
                    total_steps_verified += card_steps_verified

                    if card_steps_verified == len(actual_steps) and len(actual_steps) > 0:
                        execution_passed += 1
                        card_execution_success = True
                        print("  ✅ Card Execution SUCCESS (all steps verified)")
                    else:
                        print(f"  ❌ Card Execution FAILED ({card_steps_verified}/{len(actual_steps)} steps)")
            else:
                if quality_score < 4:
                    print(f"  ⚠️  Quality Gate REJECTED (Score: {quality_score})")
                else:
                    print("  ❌ Parser Failure: No steps generated.")

            # Record metrics
            results.append(
                {
                    "ticket_id": ticket_id,
                    "parser_success": parser_success,
                    "execution_success": card_execution_success,
                    "quality_score": quality_score,
                    "coverage": coverage,
                    "actual_steps": actual_steps,
                    "step_results": step_results,
                }
            )

        except Exception as e:
            print(f"  💥 Card Crash: {str(e)}")
            results.append({"ticket_id": ticket_id, "success": False, "error": str(e)})

        print()

    # Final Summary
    print("=" * 60)
    print("VQA PIPELINE BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"Total Cards:      {total_cards}")
    print(f"Parser Passed:    {parser_passed} ({(parser_passed / total_cards) * 100:.1f}%)")

    if full_execution:
        print(f"Execution Passed:  {execution_passed} ({(execution_passed / total_cards) * 100:.1f}%)")
        step_pass_rate = (total_steps_verified / total_steps_executed) * 100 if total_steps_executed > 0 else 0
        print(f"Step Pass Rate:   {step_pass_rate:.1f}% ({total_steps_verified}/{total_steps_executed} steps)")

        # Component Breakdown (TASK-013)
        print("\nComponent Success Breakdown:")
        print("-" * 40)
        component_stats = {}
        for r in results:
            for sr in r.get("step_results", []):
                step_text = sr["step"].lower()
                success = sr["success"]
                for comp, keywords in COMPONENT_MAP.items():
                    if any(kw in step_text for kw in keywords):
                        if comp not in component_stats:
                            component_stats[comp] = {"pass": 0, "total": 0}
                        component_stats[comp]["total"] += 1
                        if success:
                            component_stats[comp]["pass"] += 1

        for comp, stats in sorted(
            component_stats.items(),
            key=lambda x: x[1]["pass"] / x[1]["total"] if x[1]["total"] > 0 else 0,
            reverse=True,
        ):
            count_total = stats["total"]
            rate = (stats["pass"] / count_total) * 100 if count_total > 0 else 0
            print(f"{comp:<15}: {rate:>5.1f}% ({stats['pass']}/{count_total})")

    print("=" * 60)

    # Save detailed report
    if not report_path:
        report_path = os.path.join(PROJECT_ROOT, ".agent-logs/benchmark_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed report saved to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="vQA Pipeline Benchmark")
    parser.add_argument("--full", action="store_true", help="Run full E2E Playwright execution")
    parser.add_argument("-n", "--limit", type=int, default=0, help="Limit number of cards to benchmark")
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase output verbosity")
    parser.add_argument("--report", type=str, default="", help="Custom report output path")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(run_benchmark(full_execution=args.full, limit=args.limit, report_path=args.report))
